"""Reconcile an interactive-CIDM evidence tree (EVIDENCE_ROOT/.cidm) from raw receipts.

The interactive route stores one `<gate>.request.json` (host-written Jev request)
and one `<gate>.result.json` (scripts/jev_decide.py output) per Jev call, plus
narrative TOKEN-LOG.md / CLASSIFICATION.md files. This tool never trusts the
narrative: it recomputes calls, tokens, charges and latency from the receipts,
then compares every TOKEN-LOG table row and totals line against them.

Reads the evidence tree read-only; writes to --out only. No network.

    python -B reconcile_windows_cidm.py --cidm "<EVIDENCE_ROOT>" --out "<study>/private-reconciliation"
    [--zip "<the .cidm.zip>"]   # optional: recover per-file timestamps for ordering
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import re
import sys
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cidm_accounting as acc  # noqa: E402

# Local-validation failures in jev_decide.py raise before any network request.
NOT_SENT_CODES = {"explicit_provider_jev_model_required", "invalid_choice_criteria", "invalid_request_fields",
                  "request_must_be_object", "state_must_be_nonempty", "invalid_questions", "invalid_question_id",
                  "invalid_question_fields", "invalid_question_type", "instructions_must_be_nonempty",
                  "invalid_choice_option", "invalid_score_criteria", "invalid_noul_criteria",
                  "request_exceeds_28000_byte_guard", "invalid_json", "local_io_or_json_error",
                  "output_must_differ_from_request", "invalid_timeout", "request_file_too_large",
                  "invalid_or_missing_api_key"}
# Commit times of the published skill (+08:00), used to label the policy in force.
COMMITS = [("2026-09-23T12:29:44+08:00", "c389bec"), ("2026-09-23T14:36:18+08:00", "1e6e238"),
           ("2026-09-23T15:54:04+08:00", "9a56346"), ("2026-09-23T18:25:01+08:00", "d1f0093"),
           ("2026-09-23T19:01:33+08:00", "44d9945"), ("2026-09-23T23:37:30+08:00", "0ce0869"),
           ("2026-09-24T00:38:03+08:00", "327c36b")]
HASH = re.compile(r"\b[0-9a-f]{64}\b")
NUM = re.compile(r"^-?[\d,]+(?:\.\d+)?$")


def canonical_sha(request):
    body = json.dumps(request, sort_keys=True, ensure_ascii=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(body.encode()).hexdigest(), len(body.encode())


def billing(result):
    if result.get("status") == "ok":
        return "billed"
    raw = result.get("usage_raw") or {}
    if isinstance(raw, dict) and raw.get("cost") is not None:
        return "billed"
    code = (result.get("error") or {}).get("code")
    if code in NOT_SENT_CODES:
        return "unbilled_not_sent"
    return "unknown"


def parse_tables(text):
    """Yield (header, cells, line) for markdown table rows.

    A header is a row followed by a separator row. A row that appears outside a
    table (for example a row pasted after a paragraph) is attached to the most
    recent header with the same number of cells, so orphaned rows are not lost.
    """
    lines = text.splitlines()
    is_row = [l.strip().startswith("|") and l.strip().endswith("|") for l in lines]
    cells_of = [[c.strip() for c in l.strip().strip("|").split("|")] if r else None for l, r in zip(lines, is_row)]
    is_sep = [bool(c) and all(re.fullmatch(r":?-{2,}:?", x) for x in c if x) for c in cells_of]
    rows, header, headers_seen = [], None, []
    for i, line in enumerate(lines):
        if not is_row[i]:
            header = None
            continue
        if is_sep[i]:
            continue
        if i + 1 < len(lines) and is_sep[i + 1]:
            header = [c.lower() for c in cells_of[i]]
            headers_seen.append(header)
            continue
        current = header or next((h for h in reversed(headers_seen) if len(h) == len(cells_of[i])), None)
        if current is not None:
            rows.append((current, cells_of[i], line))
    return rows


def to_number(cell):
    c = cell.replace("$", "").replace("ms", "").replace("derived", "").replace("`", "").strip()
    c = c.split()[0] if c else c
    return float(c.replace(",", "")) if c and NUM.match(c) else None


def ledger_rows(text):
    """Call-ledger rows: have an input and output numeric column."""
    out = []
    for header, cells, line in parse_tables(text):
        if len(cells) != len(header):
            continue
        cols = {h: c for h, c in zip(header, cells)}
        inp = next((to_number(cols[h]) for h in header if h.startswith("input")), None)
        outp = next((to_number(cols[h]) for h in header if h.startswith("output")), None)
        usd = next((to_number(cols[h]) for h in header if "usd" in h or "cost" in h), None)
        if inp is None or outp is None:
            continue
        lat = next((to_number(cols[h]) for h in header if "latency" in h), None)
        out.append({"line": line.strip(), "number": cols.get("#"), "hashes": HASH.findall(line),
                    "input": int(inp), "output": int(outp), "usd": usd, "latency_ms": lat})
    return out


def totals_claims(text):
    claims = {}
    for header, cells, _ in parse_tables(text):
        if len(cells) < 2:
            continue
        label, value = cells[0].lower(), cells[1]
        number = to_number(value.replace("**", ""))
        if number is None:
            continue
        for key, pattern in (("jev_calls", r"^jev calls$"), ("jev_input", r"^jev (reported )?input tokens$"),
                             ("jev_output", r"^jev (reported )?output tokens$"),
                             ("jev_cost", r"^jev (reported )?api cost$"), ("jev_latency_ms", r"^jev api latency$")):
            if re.match(pattern, label):
                claims[key] = number
    return claims


def budget_start(text):
    m = re.search(r"at most ([\d,]+) Jev calls?, ([\d,]+) (?:reported )?Jev tokens", text)
    usd = re.search(r"\$([\d.]+) Jev API", text)
    if not m:
        return None
    return {"jev_calls": int(m.group(1).replace(",", "")), "jev_tokens": int(m.group(2).replace(",", "")),
            "jev_usd": float(usd.group(1)) if usd else None}


def policy_for(timestamp_local):
    if timestamp_local is None:
        return None
    label = None
    for when, commit in COMMITS:
        if timestamp_local >= dt.datetime.fromisoformat(when):
            label = commit
    return label or "pre-c389bec"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cidm", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--zip", type=Path)
    parser.add_argument("--tz", default="+08:00", help="timezone of zip timestamps (machine local time)")
    args = parser.parse_args(argv)
    root = args.cidm
    stamps = {}
    if args.zip:
        tz = dt.timezone(dt.timedelta(hours=int(args.tz[:3]), minutes=int(args.tz[0] + args.tz[4:])))
        for info in zipfile.ZipFile(args.zip).infolist():
            name = info.filename.split("/", 1)[1] if "/" in info.filename else info.filename
            stamps[name.rstrip("/")] = dt.datetime(*info.date_time, tzinfo=tz)
    args.out.mkdir(parents=True, exist_ok=True)
    events, runs, issues = [], {}, []
    for run_dir in sorted(p for p in root.iterdir() if p.is_dir() and p.name != "studies"):
        run = run_dir.name
        results = sorted(run_dir.rglob("*.result.json"))
        requests = {p: json.loads(p.read_text(encoding="utf-8-sig")) for p in run_dir.rglob("*.request.json")}
        by_sha = defaultdict(list)
        for path, req in requests.items():
            try:
                by_sha[canonical_sha(req)[0]].append(path)
            except (TypeError, ValueError):
                issues.append({"run": run, "file": path.name, "issue": "request_not_canonicalizable"})
        receipts = []
        for path in results:
            try:
                result = json.loads(path.read_text(encoding="utf-8-sig"))
            except json.JSONDecodeError:
                issues.append({"run": run, "file": path.name, "issue": "result_invalid_json"})
                continue
            if not (isinstance(result, dict) and ("request_sha256" in result
                                                  or (result.get("status") == "failed" and "error" in result))):
                continue
            request_path = path.with_name(path.name.replace(".result.json", ".request.json"))
            request = requests.get(request_path)
            recomputed = canonical_sha(request) if request is not None else (None, None)
            if request is None and result.get("request_sha256") in by_sha:
                request_path = by_sha[result["request_sha256"]][0]
                request = requests[request_path]
                recomputed = canonical_sha(request)
                issues.append({"run": run, "file": path.name, "issue": "result_paired_by_hash_not_name",
                               "request": request_path.name})
            if request is not None and result.get("request_sha256") not in (None, recomputed[0]):
                issues.append({"run": run, "file": path.name, "issue": "request_sha256_mismatch"})
            raw = result.get("usage_raw") if isinstance(result.get("usage_raw"), dict) else {}
            question = next(iter((request or {}).get("questions", {}) or {}), None)
            criteria = sorted(((request or {}).get("questions", {}).get(question, {}) or {}).get("criteria") or {})
            answer = (result.get("answers") or {}).get(question) if question else None
            rel = str(path.relative_to(root))
            stamp = stamps.get(rel)
            ev = acc.new_event(run_id=run, task_id=run, task_family="interactive_project_task", arm_id="installed_interactive",
                               repetition_id=0, record_kind="live_development_attempt", source_record=rel,
                               event_id=rel, actor="jev", currency="USD", usage_raw=result.get("usage_raw"))
            acc.set_field(ev, "provider_request_id", None, "unavailable", "jev_decide_cli_does_not_save_response_id")
            acc.set_field(ev, "prompt_hash", result.get("request_sha256"), "directly_observed", "no_request_hash")
            acc.set_field(ev, "requested_model", result.get("requested_model") or (request or {}).get("model"),
                          "directly_observed", "not_recorded")
            acc.set_field(ev, "returned_model", result.get("returned_model"), "provider_reported", "no_response")
            acc.set_field(ev, "returned_provider", result.get("upstream_provider"), "provider_reported", "no_response")
            acc.set_field(ev, "input_tokens", raw.get("input_tokens"), "provider_reported", "no_usage_returned")
            acc.set_field(ev, "output_tokens", raw.get("output_tokens"), "provider_reported", "no_usage_returned")
            acc.set_field(ev, "provider_total_tokens", raw.get("total_tokens"), "provider_reported", "jev_reports_no_total")
            acc.set_field(ev, "provider_reported_cost", raw.get("cost"), "provider_reported", "no_usage_returned")
            acc.set_field(ev, "api_duration_ms", result.get("latency_ms"), "directly_observed", "no_latency")
            acc.set_field(ev, "status", "ok" if result.get("status") == "ok" else "failed", "directly_observed")
            acc.set_field(ev, "billing_status", {"billed": "billed", "unknown": "unknown"}.get(billing(result), "unbilled"),
                          "derived")
            acc.set_field(ev, "started_at", stamp.isoformat() if stamp else None, "directly_observed",
                          "only_file_mtime_minute_resolution_available" if stamp is None else None)
            acc.set_field(ev, "gate_phase", path.name.replace(".result.json", ""), "derived")
            acc.set_field(ev, "gate_options", criteria, "directly_observed", "no_request")
            acc.set_field(ev, "gate_action", (answer or {}).get("choice"), "provider_reported", "no_decision")
            acc.set_field(ev, "policy_version", policy_for(stamp), "derived", "no_timestamp")
            ev["notes"].append({"error": result.get("error"), "billing": billing(result),
                                "probabilities": (answer or {}).get("probabilities"),
                                "confidence": (answer or {}).get("confidence"),
                                "request_bytes": result.get("request_bytes"),
                                "remaining_budget_claim": ((request or {}).get("state") or {}).get("remaining_budget")
                                if isinstance((request or {}).get("state"), dict) else None})
            receipts.append(ev)
        events.extend(receipts)
        # ------------------------------------------------ narrative comparison
        log_path = run_dir / "TOKEN-LOG.md"
        log = log_path.read_text(encoding="utf-8-sig") if log_path.exists() else ""
        rows = ledger_rows(log)
        claims = totals_claims(log)
        billed = [e for e in receipts if e["billing_status"] == "billed"]
        sums = {"jev_calls": len(billed), "jev_input": sum(e["input_tokens"] or 0 for e in billed),
                "jev_output": sum(e["output_tokens"] or 0 for e in billed),
                "jev_cost": round(sum(e["provider_reported_cost"] or 0 for e in billed), 12),
                "jev_latency_ms": sum(e["api_duration_ms"] or 0 for e in billed)}
        comparisons = {k: {"claimed": v, "receipts": sums[k],
                           "match": abs(v - sums[k]) < (1e-9 if k == "jev_cost" else 0.5)} for k, v in claims.items()}
        seen_lines, duplicates = Counter(r["line"] for r in rows), []
        for line, count in seen_lines.items():
            if count > 1:
                row = next(r for r in rows if r["line"] == line)
                matches = [e for e in receipts if e["prompt_hash"] in row["hashes"]
                           or (e["input_tokens"] == row["input"] and e["output_tokens"] == row["output"])]
                duplicates.append({"row_number": row["number"], "occurrences": count,
                                   "matching_receipts": len(matches),
                                   "same_latency_as_receipt": bool(matches) and all(e["api_duration_ms"] == row["latency_ms"] for e in matches),
                                   "verdict": ("document_duplicate_row" if len(matches) == 1 and count > 1
                                               else "possible_repeated_billed_call" if len(matches) >= count
                                               else "undetermined")})
        unique_rows = list({r["line"]: r for r in rows}.values())
        unlogged = [e["source_record"] for e in billed
                    if rows and not any(e["prompt_hash"] in r["hashes"] or (e["input_tokens"] == r["input"]
                                        and e["output_tokens"] == r["output"]) for r in unique_rows)]
        receiptless = [r["number"] for r in unique_rows
                       if r["input"] and not any(e["prompt_hash"] in r["hashes"] or (e["input_tokens"] == r["input"]
                                                  and e["output_tokens"] == r["output"]) for e in receipts)]
        # ------------------------------------------------ budget drift
        classification = (run_dir / "CLASSIFICATION.md").read_text(encoding="utf-8-sig") if (run_dir / "CLASSIFICATION.md").exists() else ""
        start = budget_start(classification)
        drift = []
        order = []
        for r in unique_rows:
            match = next((e for e in receipts if e["prompt_hash"] in r["hashes"]), None)
            if match is None:
                match = next((e for e in receipts if e["input_tokens"] == r["input"] and e["output_tokens"] == r["output"]), None)
            if match is not None and match not in order:
                order.append(match)
        if start and order:
            spent_tokens = spent_calls = 0
            spent_usd = 0.0
            for e in order:
                claim = e["notes"][0]["remaining_budget_claim"]
                if isinstance(claim, dict) and isinstance(claim.get("jev_tokens"), (int, float)):
                    expected = start["jev_tokens"] - spent_tokens
                    if claim["jev_tokens"] != expected:
                        drift.append({"gate": e["gate_phase"], "claimed_jev_tokens": claim["jev_tokens"],
                                      "receipt_derived": expected, "overstatement": claim["jev_tokens"] - expected})
                if e["billing_status"] == "billed":
                    spent_tokens += (e["input_tokens"] or 0) + (e["output_tokens"] or 0)
                    spent_calls += 1
                    spent_usd += e["provider_reported_cost"] or 0
        choices = Counter(e["gate_action"] for e in receipts if e["gate_action"])
        worker_choices = [c for c in choices.elements() if c.startswith(("gpt-6", "luna", "sol", "astra"))]
        first_stamp = min((e["started_at"] for e in receipts if e["started_at"]), default=None)
        runs[run] = {"policy_in_force": policy_for(dt.datetime.fromisoformat(first_stamp)) if first_stamp else None,
                     "first_receipt_local": first_stamp, "receipts": len(receipts),
                     "billed": len(billed), "billing_unknown": sum(e["billing_status"] == "unknown" for e in receipts),
                     "unbilled_not_sent": sum(e["billing_status"] == "unbilled" for e in receipts),
                     "receipt_sums": sums, "log_totals_vs_receipts": comparisons,
                     "log_rows": len(rows), "log_unique_rows": len(unique_rows), "duplicate_rows": duplicates,
                     "unlogged_billed_receipts": unlogged, "log_rows_without_receipt": receiptless,
                     "budget_start": start, "budget_drift": drift,
                     "choices": dict(choices), "worker_routes_chosen": len(worker_choices),
                     "deterministic_chosen": choices.get("deterministic", 0)}
    # ------------------------------------------------ corpus-level analysis
    billed = [e for e in events if e["billing_status"] == "billed"]
    conf_errors, near_ties, ks = [], 0, Counter()
    for e in events:
        probs, conf = e["notes"][0]["probabilities"], e["notes"][0]["confidence"]
        if isinstance(probs, dict) and len(probs) > 1 and isinstance(conf, (int, float)):
            k, peak = len(probs), max(probs.values())
            conf_errors.append(abs((k * peak - 1) / (k - 1) - conf))
            top = sorted(probs.values(), reverse=True)
            near_ties += (top[0] - top[1]) <= 0.05
            ks[k] += 1
    by_policy = defaultdict(lambda: {"runs": 0, "billed_calls": 0, "tokens": 0, "cost": 0.0})
    for name, r in runs.items():
        slot = by_policy[r["policy_in_force"]]
        slot["runs"] += 1
        slot["billed_calls"] += r["receipt_sums"]["jev_calls"]
        slot["tokens"] += r["receipt_sums"]["jev_input"] + r["receipt_sums"]["jev_output"]
        slot["cost"] = round(slot["cost"] + r["receipt_sums"]["jev_cost"], 12)
    option_kinds = Counter()
    for e in events:
        opts = e["gate_options"] or []
        option_kinds["offers_deterministic"] += "deterministic" in opts
        option_kinds["offers_worker_route"] += any(o.startswith("gpt-6") for o in opts)
        option_kinds["chose_deterministic"] += e["gate_action"] == "deterministic"
        option_kinds["chose_worker_route"] += bool(e["gate_action"]) and e["gate_action"].startswith("gpt-6")
    summary = {
        "runs": len(runs), "receipts": len(events), "billed_calls": len(billed),
        "billing_unknown": sum(e["billing_status"] == "unknown" for e in events),
        "unbilled_not_sent": sum(e["billing_status"] == "unbilled" for e in events),
        "billed_failed_calls": sum(e["billing_status"] == "billed" and e["status"] != "ok" for e in events),
        "input_tokens": sum(e["input_tokens"] or 0 for e in billed),
        "output_tokens": sum(e["output_tokens"] or 0 for e in billed),
        "reported_cost_usd": round(sum(e["provider_reported_cost"] or 0 for e in billed), 9),
        "sum_api_latency_s": round(sum(e["api_duration_ms"] or 0 for e in billed) / 1000, 3),
        "provider_generation_ids_saved": 0,
        "confidence_formula_max_abs_error": round(max(conf_errors), 4) if conf_errors else None,
        "confidence_answers_checked": len(conf_errors), "near_tie_decisions(top2_gap<=0.05)": near_ties,
        "option_count_distribution": dict(sorted(ks.items())), "gate_option_usage": dict(option_kinds),
        "by_policy_in_force": dict(by_policy),
        "runs_with_log_total_mismatch": sorted(n for n, r in runs.items() if any(not c["match"] for c in r["log_totals_vs_receipts"].values())),
        "runs_with_duplicate_rows": sorted(n for n, r in runs.items() if r["duplicate_rows"]),
        "runs_with_budget_drift": sorted(n for n, r in runs.items() if r["budget_drift"]),
        "runs_with_unlogged_billed_receipts": sorted(n for n, r in runs.items() if r["unlogged_billed_receipts"]),
        "issues": len(issues),
    }
    acc.write_jsonl(args.out / "windows-events.jsonl", events)
    (args.out / "windows-runs.json").write_text(json.dumps(runs, indent=2, default=str), encoding="utf-8")
    (args.out / "windows-summary.json").write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    (args.out / "windows-issues.json").write_text(json.dumps(issues, indent=2), encoding="utf-8")
    with (args.out / "windows-runs.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(["run", "policy_in_force", "billed", "billing_unknown", "unbilled_not_sent", "input", "output",
                         "cost_usd", "latency_ms", "log_mismatch", "duplicate_rows", "budget_drift_events",
                         "deterministic_chosen", "worker_routes_chosen"])
        for name, r in runs.items():
            s = r["receipt_sums"]
            writer.writerow([name, r["policy_in_force"], r["billed"], r["billing_unknown"], r["unbilled_not_sent"],
                             s["jev_input"], s["jev_output"], s["jev_cost"], s["jev_latency_ms"],
                             any(not c["match"] for c in r["log_totals_vs_receipts"].values()),
                             len(r["duplicate_rows"]), len(r["budget_drift"]), r["deterministic_chosen"],
                             r["worker_routes_chosen"]])
    print(json.dumps(summary, indent=1, default=str))


if __name__ == "__main__":
    main()
