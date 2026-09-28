"""Offline analysis of every saved Jev decision (no network).

1. Tests candidate formulas for the returned Choice `confidence` against the saved
   probabilities, to establish whether confidence is an independent measurement or
   a deterministic function of the returned distribution.
2. Classifies each five-unit gate by how many non-terminal options it offered, and
   attributes Jev tokens/charges to vacuous vs substantive gates.
3. Compares repeated identical Jev requests for decision consistency.

Usage: python -B jev_decision_analysis.py --repo <repo-root> --events <events.reconstructed.jsonl> --out <dir>
"""
from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from pathlib import Path

TERMINAL = {"stop", "retrieve_evidence"}


def h1_peak(probabilities):
    k, peak = len(probabilities), max(probabilities.values())
    return (k * peak - 1) / (k - 1)


def h2_entropy(probabilities):
    k = len(probabilities)
    entropy = -sum(p * math.log(p) for p in probabilities.values() if p > 0)
    return 1 - entropy / math.log(k)


def h3_margin(probabilities):
    ordered = sorted(probabilities.values(), reverse=True)
    return ordered[0] - ordered[1]


def collect_choice_answers(repo):
    """All Choice answers in saved Jev responses, with their source file."""
    answers = []
    for path in sorted(repo.glob("research/**/*.response.json")):
        response = json.loads(path.read_text(encoding="utf-8"))
        if not str(response.get("model", "")).startswith(("typesafe/jev", "jev")):
            continue
        request_path = Path(str(path).replace(".response.json", ".request.json"))
        request = json.loads(request_path.read_text(encoding="utf-8")) if request_path.exists() else {}
        for qid, answer in (response.get("answers") or {}).items():
            if answer.get("type") != "choice":
                continue
            answers.append({"file": str(path.relative_to(repo)), "question": qid,
                            "options": sorted((request.get("questions", {}).get(qid, {}).get("criteria") or {})),
                            "probabilities": answer["probabilities"], "confidence": answer["confidence"],
                            "choice": answer["choice"]})
    return answers


def formula_test(answers):
    out = {}
    for name, fn in (("H1_(k*peak-1)/(k-1)", h1_peak), ("H2_1-entropy/ln(k)", h2_entropy),
                     ("H3_peak_minus_second", h3_margin)):
        errors = [abs(fn(a["probabilities"]) - a["confidence"]) for a in answers if len(a["probabilities"]) > 1]
        out[name] = {"n": len(errors), "max_abs_error": round(max(errors), 6),
                     "mean_abs_error": round(sum(errors) / len(errors), 6),
                     "within_0.011": sum(e <= 0.011 for e in errors)}
    argmax_violations = [a for a in answers
                         if a["probabilities"][a["choice"]] < max(a["probabilities"].values()) - 1e-12]
    out["choice_not_argmax"] = [{"file": a["file"], "choice": a["choice"], "probabilities": a["probabilities"]}
                                for a in argmax_violations]
    out["option_count_distribution"] = dict(sorted(defaultdict(int, {
        k: sum(len(a["probabilities"]) == k for a in answers) for k in {len(a["probabilities"]) for a in answers}}).items()))
    return out


def gate_classification(events):
    rows = []
    for e in events:
        if e["actor"] != "jev" or not e.get("gate_options"):
            continue
        options = e["gate_options"]
        nonterminal = [o for o in options if o not in TERMINAL]
        notes = next((n for n in e.get("notes", []) if "jev_probabilities" in n), {})
        probabilities = notes.get("jev_probabilities") or {}
        rows.append({
            "bundle": e["run_id"], "call": e["source_record"].rsplit("/", 1)[-1], "phase": e.get("gate_phase"),
            "options": len(options), "nonterminal_options": len(nonterminal),
            "vacuous": len(nonterminal) <= 1, "choice": e["gate_action"],
            "p_choice": probabilities.get(e["gate_action"]), "confidence": notes.get("jev_confidence"),
            "tokens": (e["input_tokens"] or 0) + (e["output_tokens"] or 0),
            "input_tokens": e["input_tokens"], "cost": e["provider_reported_cost"],
            "latency_ms": e["api_duration_ms"],
            "deterministic_unit_gate": set(nonterminal) <= {"compute"} and bool(nonterminal)
                                       or (e.get("gate_phase") == "after_worker"),
        })
    return rows


def unit_of_gate(rows):
    """Label the unit a gate governs from gate order in the five-unit traces."""
    order = ("input", "hidden1", "hidden2", "hidden3", "output")
    by_bundle = defaultdict(list)
    for row in rows:
        by_bundle[row["bundle"]].append(row)
    for bundle, gates in by_bundle.items():
        unit_index = 0
        for row in sorted(gates, key=lambda r: int(r["call"].split("-")[1])):
            row["unit"] = order[unit_index] if unit_index < 5 else None
            if row["phase"] in ("after_worker", "after_sol_high") and row["choice"] == "forward":
                unit_index += 1
    return rows


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--events", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    repo = args.repo.resolve()
    events = [json.loads(line) for line in args.events.read_text(encoding="utf-8").splitlines() if line.strip()]
    answers = collect_choice_answers(repo)
    formulas = formula_test(answers)
    five_unit = [e for e in events if e["run_id"] in ("mandatory_checked", "conditional_first", "conditional_hardened")]
    rows = unit_of_gate(gate_classification(five_unit))
    for row in rows:
        row["deterministic_unit_gate"] = row["unit"] in ("input", "hidden2")
    summary = {}
    for bundle in ("mandatory_checked", "conditional_first", "conditional_hardened"):
        members = [r for r in rows if r["bundle"] == bundle]
        total_tokens = sum(r["tokens"] for r in members)
        total_cost = sum(r["cost"] for r in members)
        det = [r for r in members if r["deterministic_unit_gate"]]
        vac = [r for r in members if r["vacuous"]]
        summary[bundle] = {
            "jev_gates": len(members), "jev_tokens": total_tokens, "jev_cost": round(total_cost, 12),
            "vacuous_gates(<=1 nonterminal option)": len(vac),
            "vacuous_gate_tokens": sum(r["tokens"] for r in vac),
            "gates_governing_deterministic_units": len(det),
            "deterministic_unit_gate_tokens": sum(r["tokens"] for r in det),
            "deterministic_unit_gate_token_share_of_jev": round(sum(r["tokens"] for r in det) / total_tokens, 4),
            "choices": dict(sorted(defaultdict(int, {c: sum(r["choice"] == c for r in members)
                                                     for c in {r["choice"] for r in members}}).items())),
            "min_p_choice": min(r["p_choice"] for r in members if r["p_choice"] is not None),
            "any_stop_or_repair_or_check_chosen": any(r["choice"] not in ("forward", "compute") and not r["choice"].startswith(("luna", "sol"))
                                                      for r in members),
        }
    # consistency of byte-identical Jev requests
    groups = defaultdict(list)
    for e in events:
        if e["actor"] == "jev" and e.get("prompt_hash") and e.get("gate_action") is not None:
            notes = next((n for n in e.get("notes", []) if "jev_probabilities" in n), {})
            groups[e["prompt_hash"]].append({"record": e["source_record"], "choice": e["gate_action"],
                                             "probabilities": notes.get("jev_probabilities"),
                                             "confidence": notes.get("jev_confidence"),
                                             "input_tokens": e["input_tokens"], "output_tokens": e["output_tokens"]})
    repeats = {h[:16]: v for h, v in groups.items() if len(v) > 1}
    consistency = {h: {"n": len(v), "same_choice": len({x["choice"] for x in v}) == 1,
                       "same_probabilities": len({json.dumps(x["probabilities"], sort_keys=True) for x in v}) == 1,
                       "same_usage": len({(x["input_tokens"], x["output_tokens"]) for x in v}) == 1,
                       "records": [x["record"] for x in v]} for h, v in repeats.items()}
    # worker route selections made by Jev in authorize_unit gates
    route_choices = [{"bundle": r["bundle"], "unit": r["unit"], "choice": r["choice"], "p_choice": r["p_choice"],
                      "options": r["options"]} for r in rows if r["phase"] == "authorize_unit" and not r["deterministic_unit_gate"]]
    report = {"confidence_formula_test": formulas, "gate_summary": summary,
              "identical_request_consistency": consistency, "jev_worker_route_choices": route_choices,
              "n_choice_answers": len(answers)}
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "jev-decision-analysis.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    with (args.out / "gates.csv").open("w", encoding="utf-8") as stream:
        keys = list(rows[0])
        stream.write(",".join(keys) + "\n")
        for r in rows:
            stream.write(",".join(json.dumps(r[k]) if not isinstance(r[k], str) else r[k] for k in keys) + "\n")
    print(json.dumps({"n_choice_answers": len(answers),
                      "formula_max_abs_error": {k: v["max_abs_error"] for k, v in formulas.items() if isinstance(v, dict) and "max_abs_error" in v},
                      "choice_not_argmax": len(formulas["choice_not_argmax"]),
                      "gate_summary": summary}, indent=1))


if __name__ == "__main__":
    main()
