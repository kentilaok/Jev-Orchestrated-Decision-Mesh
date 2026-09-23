"""Offline, independently graded accounting for the bounded CIDM pilot.

No network calls, model calls, credentials, or inferred billing rates are used.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import random
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from grader import grade_response

ARMS = ("A", "B")
PHASES = ("development", "evaluation")
TOKEN_FIELDS = ("input_tokens", "output_tokens", "total_tokens", "reasoning_tokens", "cached_input_tokens")


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    result = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"{path}:{line_number}: expected JSON object")
        result.append(value)
    return result


def valid_count(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def valid_cost(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0


def normalize_usage(event: dict) -> dict:
    """Total is authoritative when present; reasoning/cache are subsets, never additions."""
    raw = event.get("usage") or {}
    values = {name: raw.get(name) if valid_count(raw.get(name)) else None for name in TOKEN_FIELDS}
    source = "reported" if values["total_tokens"] is not None else "unknown"
    if values["total_tokens"] is None and values["input_tokens"] is not None and values["output_tokens"] is not None:
        values["total_tokens"] = values["input_tokens"] + values["output_tokens"]
        source = "input_plus_output"
    values["cost"] = raw.get("cost") if valid_cost(raw.get("cost")) else None
    values["total_source"] = source
    values["diagnostics"] = []
    if values["reasoning_tokens"] is not None and values["output_tokens"] is not None and values["reasoning_tokens"] > values["output_tokens"]:
        values["diagnostics"].append("reasoning_tokens exceeds output_tokens")
    if values["cached_input_tokens"] is not None and values["input_tokens"] is not None and values["cached_input_tokens"] > values["input_tokens"]:
        values["diagnostics"].append("cached_input_tokens exceeds input_tokens")
    return values


def aggregate_events(events: list[dict]) -> dict:
    usage = [normalize_usage(event) for event in events]
    result = {"event_count": len(events), "statuses": dict(Counter(e.get("status", "missing") for e in events))}
    for name in (*TOKEN_FIELDS, "cost"):
        known = [u[name] for u in usage if u[name] is not None]
        result[name] = {
            "known_sum": sum(known),
            "known_events": len(known),
            "unknown_events": len(events) - len(known),
            "complete": bool(events) and len(known) == len(events),
        }
    result["reported_total_events"] = sum(u["total_source"] == "reported" for u in usage)
    result["derived_total_events"] = sum(u["total_source"] == "input_plus_output" for u in usage)
    result["usage_diagnostics"] = [f"{e.get('event_id', '?')}: {message}" for e, u in zip(events, usage) for message in u["diagnostics"]]
    result["latency_ms_known_sum"] = sum(e["latency_ms"] for e in events if valid_cost(e.get("latency_ms")))
    return result


def binomial_cdf(k: int, n: int, p: float) -> float:
    return sum(math.comb(n, i) * p**i * (1 - p)**(n-i) for i in range(k+1))


def binomial_interval(k: int, n: int, alpha: float = 0.05) -> list[float] | None:
    """Exact Clopper-Pearson interval, computed without third-party packages."""
    if not n:
        return None
    lo = 0.0
    hi = 1.0
    if k > 0:
        left, right = 0.0, 1.0
        for _ in range(80):
            mid = (left + right) / 2
            if 1 - binomial_cdf(k-1, n, mid) < alpha / 2:
                left = mid
            else:
                right = mid
        lo = (left + right) / 2
    if k < n:
        left, right = 0.0, 1.0
        for _ in range(80):
            mid = (left + right) / 2
            if binomial_cdf(k, n, mid) > alpha / 2:
                left = mid
            else:
                right = mid
        hi = (left + right) / 2
    return [lo, hi]


def paired_quality(pairs: list[tuple[bool, bool]]) -> dict:
    """Paired task-pass difference with a conservative nondegenerate exact CI.

    Two 97.5% Clopper-Pearson discordance intervals have simultaneous coverage
    at least 95% by the union bound. Project their difference onto [-1, 1].
    Unlike resampling all-success observations, this retains uncertainty.
    """
    n = len(pairs)
    plus = sum(b and not a for a, b in pairs)
    minus = sum(a and not b for a, b in pairs)
    ci = None
    if n:
        plus_ci = binomial_interval(plus, n, alpha=0.025)
        minus_ci = binomial_interval(minus, n, alpha=0.025)
        ci = [max(-1.0, plus_ci[0] - minus_ci[1]), min(1.0, plus_ci[1] - minus_ci[0])]
    return {
        "paired_tasks": n,
        "A_pass_B_fail": minus,
        "A_fail_B_pass": plus,
        "both_pass": sum(a and b for a, b in pairs),
        "both_fail": sum(not a and not b for a, b in pairs),
        "difference_B_minus_A": (plus-minus)/n if n else None,
        "ci95": ci,
        "ci_method": "Conservative projection of Bonferroni-adjusted exact binomial intervals for the two paired discordance probabilities",
        "population_inference": "Descriptive uncertainty for this fixed small pilot; no population superiority or quality-equivalence proof.",
    }


def quantile(values: list[float], probability: float) -> float:
    index = (len(values)-1) * probability
    low, high = math.floor(index), math.ceil(index)
    return values[low] + (values[high]-values[low]) * (index-low)


def savings_bootstrap(task_metrics: list[dict], metric: str, *, seed: int = 1729, draws: int = 10000) -> dict:
    """Resample paired tasks within each stratum; all runs/calls stay with a task."""
    group = defaultdict(list)
    for row in task_metrics:
        group[row["stratum"]].append(row)
    baseline = sum(r["A"][metric] for r in task_metrics)
    treatment = sum(r["B"][metric] for r in task_metrics)
    estimate = 1 - treatment / baseline if baseline > 0 else None
    rng = random.Random(seed)
    estimates = []
    for _ in range(draws):
        sampled = [rng.choice(rows) for _, rows in sorted(group.items()) for _ in rows]
        a = sum(r["A"][metric] for r in sampled)
        b = sum(r["B"][metric] for r in sampled)
        if a > 0:
            estimates.append(1 - b/a)
    estimates.sort()
    return {
        "A_sum": baseline,
        "B_sum": treatment,
        "savings_rate": estimate,
        "ci95": [quantile(estimates, 0.025), quantile(estimates, 0.975)] if estimates else None,
        "seed": seed,
        "requested_draws": draws,
        "valid_draws": len(estimates),
        "task_clusters": len(task_metrics),
        "strata": {k: len(v) for k, v in sorted(group.items())},
        "method": "Paired task-cluster percentile bootstrap, stratified by task stratum",
        "scope": "Empirical fixed-pilot estimate. A narrow or degenerate CI does not guarantee generalization.",
    }


def key_for(record: dict) -> tuple:
    return (record.get("phase"), record.get("task_id"), record.get("replicate"), record.get("arm"))


def summarize_quality(rows: list[dict]) -> dict:
    n = len(rows)
    return {
        "scheduled_runs": n,
        "complete_runs": sum(r["run_status"] == "complete" for r in rows),
        "partial_runs": sum(r["run_status"] == "partial" for r in rows),
        "failed_runs": sum(r["run_status"] == "failed" for r in rows),
        "missing_runs": sum(r["run_status"] == "missing" for r in rows),
        "released_runs": sum(r["released"] for r in rows),
        "served_task_passes": sum(r["served_task_pass"] for r in rows),
        "served_task_pass_rate": sum(r["served_task_pass"] for r in rows)/n if n else None,
        "served_pass_rate_ci95": binomial_interval(sum(r["served_task_pass"] for r in rows), n),
        "served_mean_answer_accuracy": sum(r["served_answer_accuracy"] for r in rows)/n if n else None,
        "served_mean_evidence_accuracy": sum(r["served_evidence_accuracy"] for r in rows)/n if n else None,
        "raw_candidates": sum(r["candidate_present"] for r in rows),
        "raw_candidate_task_passes": sum(r["raw_task_pass"] for r in rows),
        "raw_candidate_task_pass_rate_all_scheduled": sum(r["raw_task_pass"] for r in rows)/n if n else None,
        "withheld_candidates": sum(r["candidate_present"] and not r["released"] for r in rows),
        "withheld_correct_candidates": sum(r["raw_task_pass"] and not r["released"] for r in rows),
        "elapsed_seconds_known_sum": sum(r["elapsed_seconds"] or 0 for r in rows),
    }


def analyze(tasks_path: str | Path, gold_path: str | Path, ledger_path: str | Path,
            runs_path: str | Path, output_dir: str | Path, *, seed: int = 1729,
            bootstrap_replicates: int = 10000, replicates: int = 1) -> dict:
    if replicates != 1:
        raise ValueError("This bounded pilot requires exactly one replicate per task.")
    if bootstrap_replicates <= 0:
        raise ValueError("bootstrap_replicates must be positive")
    tasks_doc = json.loads(Path(tasks_path).read_text(encoding="utf-8-sig"))
    gold_doc = json.loads(Path(gold_path).read_text(encoding="utf-8-sig"))
    tasks = tasks_doc["tasks"]
    gold = gold_doc["tasks"]
    if len({task["id"] for task in tasks}) != len(tasks):
        raise ValueError("Duplicate task IDs in task manifest")
    ledger = read_jsonl(Path(ledger_path))
    runs = read_jsonl(Path(runs_path))
    # Accept either conventional replicate index (0 or 1), while rejecting mixtures.
    observed_replicates = {r.get("replicate") for r in runs if r.get("phase") in PHASES}
    replicate_index = next(iter(observed_replicates)) if len(observed_replicates) == 1 else 0
    if replicate_index not in (0, 1) or isinstance(replicate_index, bool):
        replicate_index = 0
    by_key = defaultdict(list)
    events_by_key = defaultdict(list)
    by_id = defaultdict(list)
    for run in runs:
        by_key[key_for(run)].append(run)
    for event in ledger:
        events_by_key[key_for(event)].append(event)
        by_id[event.get("event_id")].append(event)
    issues = defaultdict(list)
    expected = set()
    rows = []
    details = []
    for task in tasks:
        task_id, phase, stratum = task["id"], task["split"], task["stratum"]
        if phase not in PHASES:
            raise ValueError(f"Unknown task phase: {phase}")
        if task_id not in gold:
            raise ValueError(f"Missing independent gold for {task_id}")
        for arm in ARMS:
            key = (phase, task_id, replicate_index, arm)
            expected.add(key)
            candidates = by_key[key]
            run = candidates[0] if len(candidates) == 1 else {}
            run_events = events_by_key[key]
            if len(candidates) != 1:
                issues[phase].append(f"{task_id}/{arm}: expected one run, found {len(candidates)}")
            if run.get("status") != "complete":
                issues[phase].append(f"{task_id}/{arm}: run is {run.get('status', 'missing')}")
            if not run_events:
                issues[phase].append(f"{task_id}/{arm}: no ledger events")
            role_counts = Counter(e.get("role") for e in run_events)
            if not role_counts["worker"]:
                issues[phase].append(f"{task_id}/{arm}: no worker event")
            if arm == "B" and not role_counts["jev"]:
                issues[phase].append(f"{task_id}/{arm}: no Jev event")
            event_ids = run.get("event_ids", [])
            if not isinstance(event_ids, list):
                issues[phase].append(f"{task_id}/{arm}: event_ids is not a list")
                event_ids = []
            if len(event_ids) != len(set(event_ids)):
                issues[phase].append(f"{task_id}/{arm}: repeated event reference")
            for event_id in event_ids:
                matches = by_id.get(event_id, [])
                if len(matches) != 1 or key_for(matches[0]) != key:
                    issues[phase].append(f"{task_id}/{arm}: invalid or ambiguous event reference {event_id}")
            if set(event_ids) != {e.get("event_id") for e in run_events}:
                issues[phase].append(f"{task_id}/{arm}: run/ledger event coverage differs")
            candidate = run.get("candidate")
            released = run.get("released") is True
            if released and candidate is None:
                issues[phase].append(f"{task_id}/{arm}: released without a candidate")
            served = grade_response(gold[task_id], candidate if released else None)
            raw = grade_response(gold[task_id], candidate)
            accounting = aggregate_events(run_events)
            row = {
                "task_id": task_id, "phase": phase, "stratum": stratum,
                "replicate": replicate_index, "arm": arm,
                "run_status": run.get("status", "missing"), "released": released,
                "candidate_present": candidate is not None,
                "served_task_pass": bool(served["task_pass"]),
                "served_answer_accuracy": served["answer_accuracy"],
                "served_evidence_accuracy": served["evidence_accuracy"],
                "raw_task_pass": bool(raw["task_pass"]),
                "raw_answer_accuracy": raw["answer_accuracy"],
                "raw_evidence_accuracy": raw["evidence_accuracy"],
                "event_count": len(run_events),
                "failed_events": sum(e.get("status") == "failed" for e in run_events),
                "worker_events": role_counts["worker"], "jev_events": role_counts["jev"],
                "total_tokens_known": accounting["total_tokens"]["known_sum"],
                "total_tokens_complete": accounting["total_tokens"]["complete"],
                "cost_known": accounting["cost"]["known_sum"],
                "cost_complete": accounting["cost"]["complete"],
                "elapsed_seconds": run.get("elapsed_seconds") if valid_cost(run.get("elapsed_seconds")) else None,
            }
            rows.append(row)
            details.append({"task_id": task_id, "phase": phase, "arm": arm, "served_grade": served, "raw_candidate_grade": raw})
    for key, group in by_key.items():
        if key not in expected:
            issues[key[0]].append(f"Unexpected run key {key}; retained in run inventory")
    for event in ledger:
        phase = event.get("phase")
        if key_for(event) not in expected:
            issues[phase].append(f"Unexpected ledger event {event.get('event_id')}; usage retained in phase totals")
        if not event.get("event_id") or len(by_id[event.get("event_id")]) != 1:
            issues[phase].append(f"Missing or duplicate event ID {event.get('event_id')}")
        if event.get("status") not in ("ok", "failed"):
            issues[phase].append(f"Invalid event status for {event.get('event_id')}")
        if event.get("role") not in ("worker", "jev"):
            issues[phase].append(f"Invalid event role for {event.get('event_id')}")
        for diagnostic in normalize_usage(event)["diagnostics"]:
            issues[phase].append(f"{event.get('event_id')}: {diagnostic}")
    if any(phase not in PHASES for phase in issues):
        for phase in PHASES:
            issues[phase].append("Records with unknown/missing phase cannot be assigned to evaluation or development")
    results = {
        "version": "1.0", "design": {
            "evaluation_tasks_expected": 12, "development_tasks_expected": 2,
            "replicates_per_task": 1, "strata_expected": 3, "evaluation_tasks_per_stratum_expected": 4,
            "arm_A": "Fixed Sol medium baseline with full source context",
            "arm_B": "Bounded CIDM source-selection and review prototype with the same Sol medium worker; every Jev and worker call included",
            "cidm_scope": "Jev selects source context and reviews candidates, with bounded retry; not a full adaptive recursive multi-model graph",
            "gate_calibration": "Declared heuristics and uncalibrated self-assessments; no thresholds fitted to the evaluation results",
            "quality_endpoint": "Independent task pass on candidate actually released to the user; withheld or missing candidates score zero",
            "token_definition": "Provider total when supplied, otherwise input plus output; reasoning is a subset of output and cached input a subset of input",
            "cost_definition": "Explicit recorded billing cost only; no inferred prices or assumption that null costs are zero",
            "bootstrap_seed": seed, "bootstrap_replicates": bootstrap_replicates,
            "controller": "Deterministic Python; no hidden host-model generation during the measured pilot",
            "excluded_creation_overhead": "Dataset, harness, analysis and prompt creation overhead is unmetered and separate from recorded runtime",
            "claims_scope": "Bounded offline-analyzed pilot; no full-lifecycle efficiency, population superiority, or quality-equivalence claim",
        }, "phases": {}, "per_task_grades": details,
        "all_record_inventory": {"ledger_events": len(ledger), "runs": len(runs), "unrecognized_phase_issues": {str(k): v for k, v in issues.items() if k not in PHASES}},
    }
    for phase in PHASES:
        phase_tasks = [t for t in tasks if t["split"] == phase]
        phase_rows = [r for r in rows if r["phase"] == phase]
        phase_events = [e for e in ledger if e.get("phase") == phase]
        design_issues = []
        if len(phase_tasks) != (12 if phase == "evaluation" else 2):
            design_issues.append(f"Expected {12 if phase == 'evaluation' else 2} {phase} tasks, found {len(phase_tasks)}")
        strata_counts = dict(Counter(t["stratum"] for t in phase_tasks))
        if phase == "evaluation" and (len(strata_counts) != 3 or any(n != 4 for n in strata_counts.values())):
            design_issues.append(f"Expected three strata with four evaluation tasks each, found {strata_counts}")
        phase_issues = list(dict.fromkeys(issues[phase] + design_issues))
        arms = {}
        for arm in ARMS:
            events = [e for e in phase_events if e.get("arm") == arm]
            arms[arm] = {"quality": summarize_quality([r for r in phase_rows if r["arm"] == arm]), "accounting": aggregate_events(events)}
        tokens_complete = not phase_issues and all(arms[a]["accounting"]["total_tokens"]["complete"] for a in ARMS)
        cost_complete = not phase_issues and all(arms[a]["accounting"]["cost"]["complete"] for a in ARMS)
        task_metrics = []
        pairs = []
        for task in phase_tasks:
            task_rows = {r["arm"]: r for r in phase_rows if r["task_id"] == task["id"]}
            pairs.append((task_rows["A"]["served_task_pass"], task_rows["B"]["served_task_pass"]))
            task_metrics.append({"task_id": task["id"], "stratum": task["stratum"], **{arm: {"tokens": task_rows[arm]["total_tokens_known"], "cost": task_rows[arm]["cost_known"]} for arm in ARMS}})
        by_model = []
        model_keys = sorted({(str(e.get("model_requested", "missing")), str(e.get("model_returned", "unknown")), str(e.get("arm", "unknown")), str(e.get("role", "unknown"))) for e in phase_events})
        for requested, returned, arm, role in model_keys:
            model_events = [e for e in phase_events if (str(e.get("model_requested", "missing")), str(e.get("model_returned", "unknown")), str(e.get("arm", "unknown")), str(e.get("role", "unknown"))) == (requested, returned, arm, role)]
            by_model.append({"model_requested": requested, "model_returned": returned, "arm": arm, "role": role, "accounting": aggregate_events(model_events)})
        per_stratum = {}
        for stratum in sorted(strata_counts):
            selected_ids = {t["id"] for t in phase_tasks if t["stratum"] == stratum}
            stratum_rows = [r for r in phase_rows if r["stratum"] == stratum]
            per_stratum[stratum] = {
                arm: {"quality": summarize_quality([r for r in stratum_rows if r["arm"] == arm]),
                      "accounting": aggregate_events([e for e in phase_events if e.get("task_id") in selected_ids and e.get("arm") == arm])}
                for arm in ARMS
            }
            stratum_metrics = [m for m in task_metrics if m["stratum"] == stratum]
            per_stratum[stratum]["token_savings"] = savings_bootstrap(stratum_metrics, "tokens", seed=seed, draws=bootstrap_replicates) if tokens_complete else None
            per_stratum[stratum]["cost_savings"] = savings_bootstrap(stratum_metrics, "cost", seed=seed, draws=bootstrap_replicates) if cost_complete else None
            stratum_pairs = [(next(r for r in stratum_rows if r["task_id"] == task_id and r["arm"] == "A")["served_task_pass"], next(r for r in stratum_rows if r["task_id"] == task_id and r["arm"] == "B")["served_task_pass"]) for task_id in sorted(selected_ids)]
            per_stratum[stratum]["paired_quality"] = paired_quality(stratum_pairs)
        results["phases"][phase] = {
            "task_count": len(phase_tasks), "strata": strata_counts,
            "issues": phase_issues, "schedule_and_linkage_complete": not phase_issues,
            "full_token_result_admissible": tokens_complete,
            "full_cost_result_admissible": cost_complete,
            "arms": arms, "by_model": by_model, "per_stratum": per_stratum,
            "paired_served_quality": paired_quality(pairs),
            "token_savings": savings_bootstrap(task_metrics, "tokens", seed=seed, draws=bootstrap_replicates) if tokens_complete else None,
            "cost_savings": savings_bootstrap(task_metrics, "cost", seed=seed, draws=bootstrap_replicates) if cost_complete else None,
            "failed_attempts": sum(e.get("status") == "failed" for e in phase_events),
            "billing_note": "Raw billed cost can change with caching, model prices and billing terms even at equal total tokens. Missing billing prevents a full cost result.",
        }
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "results.json").write_text(json.dumps(results, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    with (destination / "task_results.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]) if rows else ["task_id", "arm"])
        writer.writeheader()
        writer.writerows(rows)
    (destination / "summary.md").write_text(render_report(results), encoding="utf-8")
    return results


def percent(value: float | None) -> str:
    return "unavailable" if value is None else f"{value:.1%}"


def interval(values: list[float] | None) -> str:
    return "unavailable" if values is None else f"[{percent(values[0])}, {percent(values[1])}]"


def metric_text(accounting: dict, name: str) -> str:
    field = accounting[name]
    amount = f"{field['known_sum']:.6f}" if name == "cost" else f"{field['known_sum']:,}"
    return amount if field["complete"] else f"{amount} known; {field['unknown_events']}/{accounting['event_count']} unknown"


def render_report(results: dict) -> str:
    lines = ["# CIDM versus fixed Sol: bounded pilot", "",
             "This is a 12-task evaluation pilot with one paired replicate per task, stratified into three groups of four. Two development tasks are accounted for separately. It is not proof of population superiority or quality equivalence.", "",
             "A is the fixed Sol medium baseline with full source context. B is a bounded CIDM source-selection and review prototype using the same Sol medium worker, with Jev review and bounded retry. It is not the full adaptive recursive multi-model graph. B includes every recorded Jev and worker call, including failed attempts. Independent hidden-gold grading scores the candidate actually released; withheld and missing outputs score zero. Raw candidate grades expose over-rejection.", "",
             "Routing and release use declared heuristics and uncalibrated self-assessments. No success threshold is fitted to these evaluation results.", "",
             "Runtime orchestration is deterministic Python; there is no hidden host-model generation during the measured pilot. Dataset, prompt, harness, and analysis creation overhead is unmetered and excluded. These results make no full-lifecycle efficiency claim.", ""]
    for phase in ("evaluation", "development"):
        result = results["phases"][phase]
        lines += [f"## {phase.capitalize()}", "", f"Tasks: {result['task_count']}. Failed attempts retained: {result['failed_attempts']}.", "",
                  "| Arm | Complete / scheduled | Released | Served passes | Raw passes / scheduled | Correct withheld | Total tokens | Recorded cost |",
                  "|---|---:|---:|---:|---:|---:|---:|---:|"]
        for arm in ARMS:
            q, a = result["arms"][arm]["quality"], result["arms"][arm]["accounting"]
            lines.append(f"| {arm} | {q['complete_runs']}/{q['scheduled_runs']} | {q['released_runs']} | {q['served_task_passes']}/{q['scheduled_runs']} | {q['raw_candidate_task_passes']}/{q['scheduled_runs']} | {q['withheld_correct_candidates']} | {metric_text(a, 'total_tokens')} | {metric_text(a, 'cost')} |")
        lines += [""]
        for metric, admissible in (("token", "full_token_result_admissible"), ("cost", "full_cost_result_admissible")):
            estimate = result[f"{metric}_savings"]
            if result[admissible] and estimate:
                lines.append(f"Full {metric} savings, 1 − sum(B)/sum(A): {percent(estimate['savings_rate'])}; 95% interval {interval(estimate['ci95'])}.")
            else:
                lines.append(f"Full {metric} result: **inadmissible** because scheduled-run, event linkage, or usage/billing coverage is incomplete. Known sums are partial accounting only.")
        quality = result["paired_served_quality"]
        lines += ["", f"Paired served task-pass difference (B − A): {percent(quality['difference_B_minus_A'])}; conservative 95% interval {interval(quality['ci95'])}. Discordant pairs: A only {quality['A_pass_B_fail']}; B only {quality['A_fail_B_pass']}.", "",
                  "### By stratum", "", "| Stratum | Arm | Complete / scheduled | Served passes | Correct withheld | Tokens | Cost |", "|---|---|---:|---:|---:|---:|---:|"]
        for stratum, group in result["per_stratum"].items():
            for arm in ARMS:
                q, a = group[arm]["quality"], group[arm]["accounting"]
                lines.append(f"| {stratum} | {arm} | {q['complete_runs']}/{q['scheduled_runs']} | {q['served_task_passes']}/{q['scheduled_runs']} | {q['withheld_correct_candidates']} | {metric_text(a, 'total_tokens')} | {metric_text(a, 'cost')} |")
        lines += ["", "### Call and model inventory", "", "| Arm | Role | Requested model | Returned model | Calls | Failed | Input | Output | Total | Reasoning subset | Cached subset | Cost |", "|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
        for item in result["by_model"]:
            a = item["accounting"]
            numbers = " | ".join(metric_text(a, name) for name in (*TOKEN_FIELDS[:3], "reasoning_tokens", "cached_input_tokens", "cost"))
            lines.append(f"| {item['arm']} | {item['role']} | {item['model_requested']} | {item['model_returned']} | {a['event_count']} | {a['statuses'].get('failed', 0)} | {numbers} |")
        if result["issues"]:
            lines += ["", "Coverage issues (none are removed from the scheduled denominator):", ""]
            lines += [f"- {issue}" for issue in result["issues"]]
        lines += [""]
    lines += ["## Accounting and uncertainty", "",
              "Total tokens use the provider-reported total when available, otherwise input plus output. Reasoning tokens are already part of output; cached input is already part of input. Neither is added a second time. Null usage is unknown, including null Jev output, and is never silently treated as zero. Authentication failures remain in the ledger and scheduled denominator.", "",
              f"Savings intervals use a paired task-cluster percentile bootstrap, resampling within each stratum, with seed {results['design']['bootstrap_seed']} and {results['design']['bootstrap_replicates']:,} draws. All calls belonging to a task move together. A degenerate bootstrap interval does not guarantee future outcomes. Quality intervals project simultaneous Bonferroni-adjusted exact binomial bounds on the two paired discordance probabilities; all-success outcomes retain uncertainty.", "",
              "Cost is admissible only when explicit billing covers every event and the schedule is complete. No price table is inferred. Raw billed cost may differ because of caching, model prices, or billing terms. Development is displayed separately and never amortized into evaluation savings. No prompts, thresholds, tasks, or accepted outcomes are adjusted by this analysis.", "",
              "Machine-readable details: `results.json`; paired task audit: `task_results.csv`.", ""]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    here = Path(__file__).resolve().parent
    parser.add_argument("--tasks", type=Path, default=here / "tasks.json")
    parser.add_argument("--gold", type=Path, default=here / "gold.json")
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--runs", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=1729)
    parser.add_argument("--bootstrap-replicates", type=int, default=10000)
    args = parser.parse_args()
    result = analyze(args.tasks, args.gold, args.ledger, args.runs, args.output_dir, seed=args.seed, bootstrap_replicates=args.bootstrap_replicates)
    evaluation = result["phases"]["evaluation"]
    print(json.dumps({"output_dir": str(args.output_dir.resolve()), "full_token_result_admissible": evaluation["full_token_result_admissible"], "full_cost_result_admissible": evaluation["full_cost_result_admissible"], "coverage_issues": len(evaluation["issues"])}, indent=2))


if __name__ == "__main__":
    main()
