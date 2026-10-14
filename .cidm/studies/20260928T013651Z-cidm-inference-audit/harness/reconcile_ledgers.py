"""Recompute the saved CIDM ledgers from raw request/response bytes.

Reads the repository's research/ evidence read-only and writes reconciliation
outputs to a separate directory. Makes no network calls. Usage:

    python -B reconcile_ledgers.py --repo <repo-root> --out <reconciliation-dir>
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cidm_accounting as acc  # noqa: E402

GPT6_BUNDLES = {
    # bundle id: (relative directory, record_kind, policy label)
    "mandatory_checked": ("research/live-gpt6-fixture/checked", "live_evaluation", "mandatory_sol_high_v2"),
    "mandatory_single_sol": ("research/live-gpt6-fixture/single-sol", "live_evaluation", "baseline_single_sol_high"),
    "conditional_first": ("research/live-gpt6-optional-fixture", "live_evaluation", "jev_conditional_sol_high_v3"),
    "conditional_hardened": ("research/live-gpt6-optional-final", "live_evaluation", "jev_conditional_sol_high_v3_hardened"),
    "fast_exit_initial": ("research/live-gpt6-fast-exit/initial", "live_development_attempt", "fast_exit_previous_policy"),
    "fast_exit_compact": ("research/live-gpt6-fast-exit/compact", "live_development_attempt", "fast_exit_previous_policy"),
}
ATTEMPTS = {
    "mandatory_attempt_A_provider_filtered": "research/live-gpt6-fixture/attempts/checked-provider-filtered.json",
    "mandatory_attempt_B_jev_stop": "research/live-gpt6-fixture/attempts/checked-jev-stop.json",
    "baseline_attempt_A_schema_mismatch": "research/live-gpt6-fixture/attempts/baseline-schema-mismatch.json",
}
SUM_FILES = {
    "research/live-gpt6-fixture": "research/live-gpt6-fixture/SHA256SUMS.txt",
    "research/live-gpt6-optional-fixture": "research/live-gpt6-optional-fixture/SHA256SUMS.txt",
    "research/live-gpt6-optional-final": "research/live-gpt6-optional-final/SHA256SUMS.txt",
    "research/live-gpt6-fast-exit": "research/live-gpt6-fast-exit/SHA256SUMS.txt",
    "research/historical-pilot": "research/historical-pilot/SHA256SUMS.txt",
}
# Narrative claims copied from the READMEs/docs (the object being audited).
CLAIMS = {
    "mandatory_checked": {"calls": 23, "tokens": 36663, "cost": 0.012201078, "latency_s": 36.311,
                          "jev": {"calls": 15, "tokens": 31700, "cost": 0.001298178},
                          "checker": {"calls": 5, "tokens": 3038, "cost": 0.010548},
                          "worker": {"calls": 3, "tokens": 1925, "cost": 0.0003549}},
    "mandatory_single_sol": {"calls": 1, "tokens": 431, "cost": 0.001726, "latency_s": 4.297},
    "conditional_first": {"calls": 13, "tokens": 25651, "cost": 0.00312019,
                          "jev": {"calls": 10, "tokens": 23812, "cost": 0.00097209},
                          "worker": {"calls": 3, "tokens": 1839, "cost": 0.00214810}},
    "conditional_hardened": {"calls": 13, "tokens": 25510, "cost": 0.006413654, "latency_s": 13.499,
                             "jev": {"calls": 10, "tokens": 23752, "cost": 0.000969654},
                             "worker": {"calls": 3, "tokens": 1758, "cost": 0.005444}},
    "fast_exit_initial": {"calls": 1, "tokens": 889, "cost": 0.00003423},
    "fast_exit_compact": {"calls": 1, "tokens": 716, "cost": 0.000026964},
    "mandatory_attempt_A_provider_filtered": {"cost": 0.000093534},
    "mandatory_attempt_B_jev_stop": {"calls": 7, "cost": 0.002400746},
    "baseline_attempt_A_schema_mismatch": {"calls": 1, "cost": 0.002172},
    "historical_eval_arm_A": {"calls": 12, "tokens": 34942, "cost": 0.25523625},
    "historical_eval_arm_B": {"calls": 40, "tokens": 131388, "cost": 0.230692994,
                              "jev": {"calls": 26, "tokens": 106358, "cost": 0.004225494},
                              "worker": {"calls": 14, "tokens": 25030}},
    "historical_development": {"cost": 0.042355456},
}


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def verify_sums(repo, out_rows):
    report = {}
    for base, sums in SUM_FILES.items():
        base_path, sums_path = repo / base, repo / sums
        listed, mismatched, missing = {}, [], []
        for line in sums_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            digest, name = line.split(None, 1)
            name = name.strip().lstrip("*")
            listed[name] = digest
            target = base_path / name
            if not target.exists():
                missing.append(name)
            elif acc.sha256_bytes(target.read_bytes()) != digest:
                mismatched.append(name)
        present = sorted(str(p.relative_to(base_path)).replace(os.sep, "/")
                         for p in base_path.rglob("*") if p.is_file())
        uncovered = [p for p in present if p not in listed and p not in ("SHA256SUMS.txt", "README.md")
                     and "__pycache__" not in p and not p.endswith(".gitignore")]
        report[base] = {"listed": len(listed), "mismatched": mismatched, "missing": missing,
                        "uncovered_files": uncovered}
        out_rows.append({"bundle": base, "listed": len(listed), "mismatched": len(mismatched),
                         "missing": len(missing), "uncovered": len(uncovered)})
    return report


def gpt6_events(repo, bundle_id, rel, record_kind, policy):
    folder = repo / rel
    events, issues = [], []
    usage_lines = {}
    usage_path = folder / "usage.jsonl"
    if usage_path.exists():
        for n, line in enumerate(usage_path.read_text(encoding="utf-8").splitlines(), 1):
            if line.strip():
                record = json.loads(line)
                if record["id"] in usage_lines:
                    issues.append({"bundle": bundle_id, "issue": "usage_jsonl_repeated_call_id",
                                   "call": record["id"], "line": n})
                usage_lines[record["id"]] = record
    numbers = sorted(int(m.group(1)) for p in folder.glob("call-*.event.json")
                     if (m := re.fullmatch(r"call-(\d+)\.event\.json", p.name)))
    if numbers != list(range(1, len(numbers) + 1)):
        issues.append({"bundle": bundle_id, "issue": "noncontiguous_call_numbers", "numbers": numbers})
    result = load_json(folder / "result.json") if (folder / "result.json").exists() else {}
    result_calls = {c["id"]: c for c in result.get("calls", [])}
    for n in numbers:
        cid = "call-" + str(n)
        event_file = load_json(folder / (cid + ".event.json"))
        request_path, response_path = folder / (cid + ".request.json"), folder / (cid + ".response.json")
        request = load_json(request_path) if request_path.exists() else None
        response = load_json(response_path) if response_path.exists() else None
        role = event_file["role"]
        ev = acc.new_event(run_id=bundle_id, task_id="production-records-3row", task_family="deterministic_extraction_arithmetic",
                           arm_id=policy, repetition_id=0, record_kind=record_kind,
                           source_record=f"{rel}/{cid}", event_id=f"{bundle_id}:{cid}",
                           parent_event_id=None, actor=role, currency="USD",
                           usage_raw=response.get("usage") if isinstance(response, dict) else None)
        acc.set_field(ev, "policy_version", event_file.get("policy_hash"), "directly_observed",
                      "no_policy_hash")
        acc.set_field(ev, "parent_event_id", None, "unavailable", "gpt6_events_not_parent_linked")
        # request identity
        if request is None:
            acc.set_field(ev, "prompt_hash", None, "unavailable", "request_file_missing")
            issues.append({"bundle": bundle_id, "call": cid, "issue": "request_file_missing"})
        else:
            recomputed = acc.fingerprint(request)
            acc.set_field(ev, "prompt_hash", recomputed, "derived")
            if recomputed != event_file.get("request_hash"):
                issues.append({"bundle": bundle_id, "call": cid, "issue": "request_hash_mismatch",
                               "event": event_file.get("request_hash"), "recomputed": recomputed})
            acc.set_field(ev, "requested_model", request.get("model"), "directly_observed")
            effort = (request.get("reasoning") or {}).get("effort") if role != "jev" else None
            acc.set_field(ev, "requested_effort", effort, "directly_observed",
                          "jev_has_no_effort_setting" if role == "jev" else "not_in_request")
            if role != "jev":
                prov = request.get("provider") or {}
                acc.set_field(ev, "fallback_status",
                              "fallbacks_disallowed" if prov.get("allow_fallbacks") is False else "fallbacks_allowed_or_unspecified",
                              "directly_observed")
        acc.set_field(ev, "confirmed_effort", None, "unavailable",
                      "provider_response_has_no_effort_field" if role != "jev" else "not_applicable")
        # response identity and usage
        if response is None:
            for name in ("provider_request_id", "returned_model", "returned_provider"):
                acc.set_field(ev, name, None, "unavailable", "response_file_missing")
            acc.set_field(ev, "status", "failed", "directly_observed")
            acc.set_field(ev, "billing_status", "unknown", "derived")
        else:
            acc.set_field(ev, "provider_request_id", response.get("id"), "provider_reported",
                          "response_has_no_id")
            acc.set_field(ev, "returned_model", response.get("model"), "provider_reported", "no_model")
            acc.set_field(ev, "returned_provider", response.get("provider"), "provider_reported",
                          "provider_field_absent")
            normalize = acc.normalize_typesafe_usage if role == "jev" else acc.normalize_openrouter_chat_usage
            usage, usage_issues = normalize(response.get("usage"))
            for issue in usage_issues:
                issues.append({"bundle": bundle_id, "call": cid, "issue": "usage:" + issue})
            for key in acc.COUNTER_FIELDS:
                acc.set_field(ev, key, usage.get(key) if usage else None, "provider_reported",
                              "not_reported_by_provider")
            acc.set_field(ev, "provider_reported_cost", usage.get("provider_reported_cost") if usage else None,
                          "provider_reported", "cost_not_reported")
            acc.set_field(ev, "status", event_file.get("status"), "directly_observed")
            acc.set_field(ev, "billing_status", "billed" if usage and usage.get("provider_reported_cost") is not None
                          else "unknown", "derived")
            # cross-check the event and usage.jsonl representations against the raw response
            for label, record in (("event", event_file), ("usage_jsonl", usage_lines.get(cid))):
                if record is None:
                    issues.append({"bundle": bundle_id, "call": cid, "issue": label + "_missing"})
                    continue
                stored = record.get("usage") or {}
                for key, raw_key in (("input_tokens", "input_tokens"), ("output_tokens", "output_tokens"),
                                     ("provider_reported_cost", "cost")):
                    if stored.get(raw_key) != ev[key]:
                        issues.append({"bundle": bundle_id, "call": cid, "issue": label + "_usage_disagrees_with_response",
                                       "field": key, "stored": stored.get(raw_key), "raw": ev[key]})
            if result_calls and cid in result_calls and result_calls[cid].get("usage", {}).get("cost") != ev["provider_reported_cost"]:
                issues.append({"bundle": bundle_id, "call": cid, "issue": "result_json_cost_disagrees"})
            if role == "jev":
                answer = (response.get("answers") or {}).get("next") or {}
                options = sorted(((request or {}).get("questions", {}).get("next", {}).get("criteria") or {}).keys())
                acc.set_field(ev, "gate_action", answer.get("choice"), "provider_reported", "no_choice")
                acc.set_field(ev, "gate_options", options, "directly_observed", "no_options")
                ev["notes"].append({"jev_probabilities": answer.get("probabilities"),
                                    "jev_confidence": answer.get("confidence")})
            else:
                content = (((response.get("choices") or [{}])[0].get("message") or {}).get("content"))
                acc.set_field(ev, "result_hash", acc.sha256_bytes(content.encode()) if isinstance(content, str) else None,
                              "derived", "no_content")
        acc.set_field(ev, "api_duration_ms", event_file.get("latency_ms"), "directly_observed", "no_latency")
        acc.set_field(ev, "started_at", None, "unavailable", "gpt6_runner_records_no_timestamps")
        acc.set_field(ev, "ended_at", None, "unavailable", "gpt6_runner_records_no_timestamps")
        acc.set_field(ev, "purpose", {"jev": "gate_decision", "worker": "unit_generation",
                                      "checker": "sol_high_review"}[role], "derived")
        acc.set_field(ev, "retry_of", None, "unavailable", "gateway_never_retries")
        events.append(ev)
    # Attach Jev phase from the journal where the api_event link exists.
    journal_path = folder / "journal.jsonl"
    if journal_path.exists():
        by_call = {e["source_record"].rsplit("/", 1)[1]: e for e in events}
        for line in journal_path.read_text(encoding="utf-8").splitlines():
            record = json.loads(line)
            if record.get("kind") == "jev_decision":
                call = (record.get("decision") or {}).get("api_event")
                if call in by_call:
                    acc.set_field(by_call[call], "gate_phase", record.get("phase"), "directly_observed")
                    if record["decision"].get("choice") != by_call[call]["gate_action"]:
                        issues.append({"bundle": bundle_id, "call": call, "issue": "journal_choice_disagrees"})
    for ev in events:
        if ev["gate_phase"] is None and ev["actor"] == "jev":
            acc.set_field(ev, "gate_phase", None, "unavailable", "no_journal_link")
    return events, issues, result


def attempt_events(repo, attempt_id, rel):
    record = load_json(repo / rel)
    events = []
    for call in record.get("calls", []):
        usage = call.get("usage") or {}
        ev = acc.new_event(run_id=attempt_id, task_id="production-records-3row",
                           task_family="deterministic_extraction_arithmetic", arm_id=attempt_id,
                           repetition_id=0, record_kind="live_development_attempt",
                           source_record=f"{rel}#{call['id']}", event_id=f"{attempt_id}:{call['id']}",
                           actor=call["role"], currency="USD", usage_raw=call.get("usage_raw"))
        acc.set_field(ev, "provider_request_id", None, "unavailable", "attempt_saved_result_only_no_response_file")
        acc.set_field(ev, "prompt_hash", call.get("request_hash"), "directly_observed", "no_request_hash")
        acc.set_field(ev, "requested_model", call.get("requested_model"), "directly_observed")
        acc.set_field(ev, "requested_effort", call.get("reasoning_effort"), "directly_observed",
                      "jev_has_no_effort_setting" if call.get("role") == "jev" else "not_recorded")
        acc.set_field(ev, "returned_model", call.get("returned_model"), "directly_observed",
                      "call_failed_before_response" if call.get("status") != "ok" else "absent")
        acc.set_field(ev, "status", "ok" if call.get("status") == "ok" else "failed", "directly_observed")
        for key, src in (("input_tokens", "input_tokens"), ("output_tokens", "output_tokens"),
                         ("cached_input_tokens", "cached_input_tokens"), ("reasoning_tokens", "reasoning_tokens")):
            acc.set_field(ev, key, usage.get(src), "provider_reported",
                          "failed_call_usage_not_returned" if call.get("status") != "ok" else "not_reported")
        acc.set_field(ev, "provider_reported_cost", usage.get("cost"), "provider_reported",
                      "failed_call_usage_not_returned" if call.get("status") != "ok" else "not_reported")
        acc.set_field(ev, "billing_status", "billed" if usage.get("cost") is not None else "unknown", "derived")
        acc.set_field(ev, "api_duration_ms", call.get("latency_ms"), "directly_observed", "no_latency")
        events.append(ev)
    return events


def historical_events(repo):
    base = repo / "research/historical-pilot"
    events, issues = [], []
    sources = [("runs-evaluation/ledger.jsonl", "live_evaluation"),
               ("runs-development/ledger.jsonl", "live_development_attempt"),
               ("combined-ledger.jsonl", None)]
    for rel, kind in sources:
        for n, line in enumerate((base / rel).read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            row = json.loads(line)
            usage = row.get("usage") or {}
            ev = acc.new_event(run_id=f"historical:{row.get('phase')}:{row.get('task_id')}:{row.get('arm')}",
                               task_id=row.get("task_id"), task_family="document_qa_" + str(row.get("phase")),
                               arm_id="historical_" + str(row.get("arm")), repetition_id=row.get("replicate"),
                               record_kind=kind or ("live_evaluation" if row.get("phase") == "evaluation"
                                                    else "live_development_attempt"),
                               source_record=f"research/historical-pilot/{rel}:{n}",
                               event_id=row.get("event_id"), actor=row.get("role"), currency="USD",
                               usage_raw=row.get("usage_raw"))
            acc.set_field(ev, "parent_event_id", row.get("parent_event_id"), "directly_observed", "root_event")
            acc.set_field(ev, "provider_request_id", row.get("generation_id"), "provider_reported", "no_generation_id")
            acc.set_field(ev, "prompt_hash", row.get("request_sha256"), "directly_observed", "no_request_hash")
            acc.set_field(ev, "requested_model", row.get("model_requested"), "directly_observed")
            acc.set_field(ev, "returned_model", row.get("model_returned"), "provider_reported", "absent")
            acc.set_field(ev, "returned_provider", row.get("provider_returned"), "provider_reported", "absent")
            acc.set_field(ev, "requested_effort", row.get("effort"), "directly_observed", "jev_has_no_effort_setting")
            acc.set_field(ev, "confirmed_effort", None, "unavailable", "provider_response_has_no_effort_field")
            acc.set_field(ev, "purpose", row.get("stage"), "directly_observed", "no_stage")
            acc.set_field(ev, "status", "ok" if row.get("status") == "ok" else "failed", "directly_observed")
            for key in ("input_tokens", "output_tokens", "cached_input_tokens", "reasoning_tokens"):
                acc.set_field(ev, key, usage.get(key), "provider_reported", "not_reported")
            raw_details = ((row.get("usage_raw") or {}).get("prompt_tokens_details") or {})
            acc.set_field(ev, "cache_write_tokens", raw_details.get("cache_write_tokens"), "provider_reported",
                          "not_in_raw_usage")
            acc.set_field(ev, "provider_total_tokens", (row.get("usage_raw") or {}).get("total_tokens"),
                          "provider_reported", "jev_reports_no_total")
            acc.set_field(ev, "provider_reported_cost", usage.get("cost"), "provider_reported", "not_reported")
            acc.set_field(ev, "billing_status", "billed" if usage.get("cost") is not None else "unknown", "derived")
            acc.set_field(ev, "started_at", row.get("started_utc"), "directly_observed", "no_timestamp")
            acc.set_field(ev, "api_duration_ms", row.get("latency_ms"), "directly_observed", "no_latency")
            ev["notes"].append({"ledger": rel})
            events.append(ev)
    # raw request/response verification for the 52 evaluation calls
    for ev in events:
        if ev["notes"][0]["ledger"] != "runs-evaluation/ledger.jsonl":
            continue
        stem = base / "runs-evaluation" / ev["event_id"]
        request_bytes = (stem.with_suffix(".request.json")).read_bytes()
        response = json.loads((stem.with_suffix(".response.json")).read_text(encoding="utf-8"))
        if acc.sha256_bytes(request_bytes) != ev["prompt_hash"] and acc.fingerprint(json.loads(request_bytes)) != ev["prompt_hash"]:
            issues.append({"event": ev["event_id"], "issue": "historical_request_hash_mismatch"})
        raw_id = response.get("id")
        if raw_id != ev["provider_request_id"]:
            issues.append({"event": ev["event_id"], "issue": "historical_generation_id_mismatch",
                           "ledger": ev["provider_request_id"], "raw": raw_id})
        raw_usage = response.get("usage") or {}
        raw_in = raw_usage.get("prompt_tokens", raw_usage.get("input_tokens"))
        raw_out = raw_usage.get("completion_tokens", raw_usage.get("output_tokens"))
        if (raw_in, raw_out, raw_usage.get("cost")) != (ev["input_tokens"], ev["output_tokens"], ev["provider_reported_cost"]):
            issues.append({"event": ev["event_id"], "issue": "historical_usage_disagrees_with_raw"})
    return events, issues


def totals(events):
    tok = [acc.io_total(e) for e in events]
    cost = [e["provider_reported_cost"] for e in events]
    lat = [e["api_duration_ms"] for e in events]
    return {"calls": len(events),
            "tokens": sum(tok) if all(t is not None for t in tok) else None,
            "unknown_token_calls": sum(t is None for t in tok),
            "cost": round(sum(c for c in cost if c is not None), 12) if all(c is not None for c in cost) else None,
            "known_cost_partial": round(sum(c for c in cost if c is not None), 12),
            "unknown_cost_calls": sum(c is None for c in cost),
            "latency_s": round(sum(lat) / 1000, 3) if all(l is not None for l in lat) else None}


def compare(claim, observed):
    rows = []
    for key, value in claim.items():
        if isinstance(value, dict):
            for sub, v in value.items():
                rows.append((key + "." + sub, v, (observed.get(key) or {}).get(sub)))
        else:
            rows.append((key, value, observed.get(key)))
    out = []
    for name, claimed, seen in rows:
        if seen is None:
            verdict = "unverifiable_from_raw"
        elif isinstance(claimed, float) or isinstance(seen, float):
            verdict = "match" if math.isclose(claimed, seen, rel_tol=0, abs_tol=5e-10) else "MISMATCH"
        else:
            verdict = "match" if claimed == seen else "MISMATCH"
        out.append({"metric": name, "claimed": claimed, "recomputed": seen, "verdict": verdict})
    return out


def role_totals(events):
    base = totals(events)
    for role in ("jev", "worker", "checker"):
        members = [e for e in events if e["actor"] == role]
        if members:
            base[role] = totals(members)
    return base


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    repo, out = args.repo.resolve(), args.out
    out.mkdir(parents=True, exist_ok=True)
    sums_rows = []
    sums = verify_sums(repo, sums_rows)
    all_events, all_issues, claim_rows, bundle_totals = [], [], [], {}
    for bundle_id, (rel, kind, policy) in GPT6_BUNDLES.items():
        events, issues, _ = gpt6_events(repo, bundle_id, rel, kind, policy)
        all_events.extend(events)
        all_issues.extend(issues)
        bundle_totals[bundle_id] = role_totals(events)
    for attempt_id, rel in ATTEMPTS.items():
        events = attempt_events(repo, attempt_id, rel)
        all_events.extend(events)
        bundle_totals[attempt_id] = role_totals(events)
    hist, hist_issues = historical_events(repo)
    all_issues.extend(hist_issues)
    split = [e for e in hist if e["notes"][0]["ledger"] != "combined-ledger.jsonl"]
    combined = [e for e in hist if e["notes"][0]["ledger"] == "combined-ledger.jsonl"]
    bundle_totals["historical_eval_arm_A"] = role_totals([e for e in split if e["record_kind"] == "live_evaluation" and e["arm_id"] == "historical_A"])
    bundle_totals["historical_eval_arm_B"] = role_totals([e for e in split if e["record_kind"] == "live_evaluation" and e["arm_id"] == "historical_B"])
    bundle_totals["historical_development"] = role_totals([e for e in split if e["record_kind"] == "live_development_attempt"])
    for name, claim in CLAIMS.items():
        for row in compare(claim, bundle_totals.get(name, {})):
            claim_rows.append({"bundle": name, **row})
    # Dedupe: the split ledgers plus the combined ledger represent the same requests twice.
    unique, dedupe_report = acc.dedupe(split + combined)
    gpt6_unique, gpt6_dedupe = acc.dedupe([e for e in all_events])
    schema_problems = {e["event_id"]: acc.validate_event(e) for e in all_events + split
                       if acc.validate_event(e)}
    # Outputs (originals untouched).
    acc.write_jsonl(out / "events.reconstructed.jsonl", all_events + split)
    (out / "checksum-verification.json").write_text(json.dumps(sums, indent=2), encoding="utf-8")
    (out / "bundle-totals.json").write_text(json.dumps(bundle_totals, indent=2), encoding="utf-8")
    (out / "reconciliation-issues.json").write_text(json.dumps(all_issues, indent=2), encoding="utf-8")
    (out / "schema-validation.json").write_text(json.dumps(schema_problems, indent=2), encoding="utf-8")
    (out / "dedupe-report.json").write_text(json.dumps({
        "historical_split_plus_combined": {"records_in": len(split) + len(combined), "unique_requests": len(unique),
                                           **dedupe_report},
        "gpt6_and_attempts": {"records_in": len(all_events), "unique_or_unidentified": len(gpt6_unique),
                              **gpt6_dedupe}}, indent=2), encoding="utf-8")
    with (out / "claims-vs-raw.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=["bundle", "metric", "claimed", "recomputed", "verdict"])
        writer.writeheader()
        writer.writerows(claim_rows)
    summary = {
        "events_reconstructed": len(all_events) + len(split),
        "checksum_mismatches": sum(len(v["mismatched"]) + len(v["missing"]) for v in sums.values()),
        "uncovered_files": {k: v["uncovered_files"] for k, v in sums.items() if v["uncovered_files"]},
        "reconciliation_issues": len(all_issues),
        "schema_invalid_events": len(schema_problems),
        "claims_checked": len(claim_rows),
        "claims_mismatched": [r for r in claim_rows if r["verdict"] == "MISMATCH"],
        "claims_unverifiable": [r for r in claim_rows if r["verdict"] == "unverifiable_from_raw"],
        "historical_representation_duplicates": len(dedupe_report["representation_duplicates"]),
        "historical_identical_prompt_distinct_requests": len(dedupe_report["identical_prompt_distinct_billed_requests"]),
        "gpt6_identical_prompt_distinct_requests": gpt6_dedupe["identical_prompt_distinct_billed_requests"],
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps({k: (v if not isinstance(v, list) else len(v)) for k, v in summary.items()
                      if k != "gpt6_identical_prompt_distinct_requests"}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
