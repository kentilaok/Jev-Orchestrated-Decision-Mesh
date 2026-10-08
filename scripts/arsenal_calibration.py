"""Arsenal Phase A2: append-only shadow calibration and conservative evaluator.

Three separate event families:
  prediction: compact local routing evidence (never authority, no raw prompt);
  runtime:    broker status, actual calls, reported provider usage (not truth labels);
  verdict:    independent labelled ground truth and explicit evidence reference.

No event can authorize Fast Path or claim realised frontier savings.
Only paired, independently adjudicated, non-simulated runs contribute to the
quality metrics. Incomplete/missing usage remains unknown, never zero.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA = 1
RECOMMENDATIONS = {
    "fast_path_candidate", "load_skill_then_jev",
    "load_experience_then_jev", "jev_only",
}
HEX64 = set("0123456789abcdef")


class CalibrationError(ValueError):
    pass


def require(ok: bool, code: str) -> None:
    if not ok:
        raise CalibrationError(code)


def hash_id(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def canonical(obj: dict) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def _text(value: Any, name: str, *, max_len: int = 256) -> str:
    require(type(value) is str and 0 < len(value) <= max_len, "invalid_" + name)
    return value


def _hex(value: Any, name: str) -> str:
    _text(value, name, max_len=64)
    require(len(value) == 64 and all(c in HEX64 for c in value), "invalid_" + name)
    return value


def _optional_str(value: Any, name: str, max_len: int = 256) -> str | None:
    if value is None:
        return None
    return _text(value, name, max_len=max_len)


def _nonnegative(value: Any) -> bool:
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def _optional_usage(call: dict) -> tuple[int | None, float | None]:
    """Provider-reported usage; do not extrapolate missing usage."""
    usage = call.get("usage")
    if not isinstance(usage, dict):
        return None, None
    i, o, c = usage.get("input_tokens"), usage.get("output_tokens"), usage.get("cost")
    count = i + o if type(i) is int and i >= 0 and type(o) is int and o >= 0 else None
    cost = float(c) if _nonnegative(c) else None
    return count, cost


def prediction_event(run_id: str, task_hash: str, shadow: dict) -> dict:
    _text(run_id, "run_id")
    _hex(task_hash, "task_hash")
    require(type(shadow) is dict and shadow.get("mode") == "shadow",
            "invalid_shadow_prediction")
    require(shadow.get("authority") == "none_shadow_observation_only",
            "shadow_authority_violation")
    recommendation = shadow.get("recommendation")
    require(recommendation in RECOMMENDATIONS, "invalid_recommendation")
    candidate = shadow.get("fast_path_candidate") is True
    require(type(shadow.get("fast_path_candidate")) is bool, "invalid_candidate_flag")
    require((recommendation == "fast_path_candidate") == candidate,
            "inconsistent_fast_path_prediction")
    require(shadow.get("frontier_call_avoided") is False,
            "shadow_must_not_claim_realised_savings")
    skill_id = _optional_str(shadow.get("selected_skill_id"), "skill_id")
    experience_id = _optional_str(shadow.get("selected_experience_id"), "experience_id")
    require(not candidate or skill_id is not None, "fast_path_skill_required")
    fused = shadow.get("fused_candidates") or []
    require(isinstance(fused, list), "invalid_candidates")
    best = next((entry for entry in fused if isinstance(entry, dict)
                 and entry.get("skill_id") == skill_id), None)
    lexical = shadow.get("lexical") or {}
    match = next((m for m in lexical.get("matches", []) if isinstance(m, dict)
                  and m.get("skill_id") == skill_id), None)
    local_match = (match or {}).get("match") or {}
    score = local_match.get("score")
    require(score is None or (_nonnegative(score) and score <= 1),
            "invalid_local_match_score")
    if candidate:
        require((lexical.get("fast_path") or {}).get("eligible") is True
                and local_match.get("exact_bug_key") is True,
                "missing_fast_path_basis")
    return {
        "schema_version": SCHEMA, "kind": "prediction",
        "run_id": run_id, "task_hash": task_hash,
        "project_scope": _optional_str(shadow.get("project_scope"), "project_scope"),
        "bug_key": _optional_str(shadow.get("bug_key"), "bug_key"),
        "operation": _optional_str(shadow.get("operation"), "operation"),
        "recommendation": recommendation,
        "selected_skill_id": skill_id,
        "selected_experience_id": experience_id,
        "skill_hash": _optional_str((best or {}).get("skill_hash"), "skill_hash"),
        "manifest_hash": _optional_str((best or {}).get("manifest_hash"), "manifest_hash"),
        "lexical_score": score,
        "exact_bug_key": bool(local_match.get("exact_bug_key") is True),
        "fast_path_candidate": candidate,
        "frontier_call_avoided": False,
        "authority": "none_shadow_observation_only",
    }


def runtime_event(run_id: str, result: dict) -> dict:
    _text(run_id, "run_id")
    require(type(result) is dict, "invalid_runtime")
    task_hash = _hex(result.get("task_hash"), "task_hash")
    status = _text(result.get("status"), "runtime_status")
    require(type(result.get("simulation")) is bool, "simulation_flag_required")
    calls = result.get("calls")
    require(isinstance(calls, list), "runtime_calls_required")
    require(all(isinstance(call, dict) and isinstance(call.get("role"), str)
                for call in calls), "invalid_runtime_call")
    by_role = {}
    known_tokens = 0
    known_cost = 0.0
    complete_tokens = True
    complete_cost = True
    for call in calls:
        role = call["role"]
        by_role[role] = by_role.get(role, 0) + 1
        tokens, cost = _optional_usage(call)
        if tokens is None:
            complete_tokens = False
        else:
            known_tokens += tokens
        if cost is None:
            complete_cost = False
        else:
            known_cost += cost

    # An independent verdict, not this runtime summary, establishes whether
    # the Fast Path was genuinely safe for that task.
    audit = result.get("audit")
    native_audit = result.get("native_audit")
    hard_checks = result.get("hard_checks")
    if result.get("route") == "short_self_contained":
        checks_valid = (isinstance(hard_checks, dict) and bool(hard_checks)
                        and all(v is True for v in hard_checks.values()))
        audited = checks_valid and status == "complete"
    else:
        audited = (
            status == "complete"
            and isinstance(audit, dict) and audit.get("valid") is True
            and isinstance(native_audit, dict) and native_audit.get("valid") is True
        )
    return {
        "schema_version": SCHEMA, "kind": "runtime",
        "run_id": run_id, "task_hash": task_hash,
        "status": status, "simulation": result["simulation"],
        "audit_verified": audited,
        "calls_by_role": dict(sorted(by_role.items())),
        "actual_model_calls": len(calls),
        "reported_tokens": known_tokens if complete_tokens else None,
        "reported_cost_usd": round(known_cost, 9) if complete_cost else None,
        "source": "native_broker_result",
        "frontier_call_avoided": False,
    }


def verdict_event(
    run_id: str, task_hash: str, *, evidence_ref: str,
    expected_skill_id: str | None,
    expected_experience_id: str | None,
    fast_path_safe: bool, reviewer: str,
) -> dict:
    _text(run_id, "run_id")
    _hex(task_hash, "task_hash")
    _text(evidence_ref, "evidence_ref", max_len=1024)
    _text(reviewer, "reviewer")
    _optional_str(expected_skill_id, "expected_skill_id")
    _optional_str(expected_experience_id, "expected_experience_id")
    require(type(fast_path_safe) is bool, "invalid_safety_verdict")
    require(not fast_path_safe or expected_skill_id is not None,
            "safe_verdict_requires_expected_skill")
    return {
        "schema_version": SCHEMA, "kind": "verdict",
        "run_id": run_id, "task_hash": task_hash,
        "evidence_ref": evidence_ref, "reviewer": reviewer,
        "expected_skill_id": expected_skill_id,
        "expected_experience_id": expected_experience_id,
        "fast_path_safe": fast_path_safe,
        "source": "independent_adjudication",
    }


def _validate_event(event: dict) -> None:
    require(type(event) is dict and event.get("schema_version") == SCHEMA,
            "invalid_calibration_schema")
    require(event.get("kind") in ("prediction", "runtime", "verdict"),
            "invalid_calibration_kind")
    _text(event.get("run_id"), "run_id")
    _hex(event.get("task_hash"), "task_hash")
    if event["kind"] == "prediction":
        require(event.get("authority") == "none_shadow_observation_only"
                and event.get("frontier_call_avoided") is False,
                "unsafe_prediction_event")
        require(event.get("recommendation") in RECOMMENDATIONS,
                "invalid_recommendation")
        require(type(event.get("fast_path_candidate")) is bool,
                "invalid_fast_path_candidate")
    elif event["kind"] == "runtime":
        require(type(event.get("simulation")) is bool, "simulation_flag_required")
        require(type(event.get("audit_verified")) is bool, "audit_flag_required")
    else:
        require(event.get("source") == "independent_adjudication",
                "invalid_verdict_source")
        _text(event.get("reviewer"), "reviewer")
        _text(event.get("evidence_ref"), "evidence_ref", max_len=1024)
        require(type(event.get("fast_path_safe")) is bool, "invalid_safety_verdict")


def read_events(path: Path) -> list[dict]:
    path = Path(path).expanduser()
    if not path.exists():
        return []
    events = []
    previous_hash = None
    with path.open(encoding="utf-8") as stream:
        for line_no, line in enumerate(stream, 1):
            try:
                event = json.loads(line)
                _validate_event(event)
                require(event.get("previous_event_hash") == previous_hash,
                        "ledger_chain_broken")
                digest = event.get("event_hash")
                _hex(digest, "event_hash")
                unsigned = {key: value for key, value in event.items() if key != "event_hash"}
                require(hash_id(canonical(unsigned)) == digest,
                        "ledger_event_hash_mismatch")
            except (ValueError, TypeError) as error:
                raise CalibrationError(f"invalid_ledger_line_{line_no}:{error}") from error
            events.append(event)
            previous_hash = digest
    return events


def append_event(path: Path, event: dict) -> None:
    """Hash-linked append-only by run/kind; single writer required for V1."""
    _validate_event(event)
    path = Path(path).expanduser()
    existing = read_events(path)
    for prior in existing:
        require(not (prior["run_id"] == event["run_id"]
                     and prior["kind"] == event["kind"]),
                "duplicate_calibration_event")
        require(not (prior["run_id"] == event["run_id"]
                     and prior["task_hash"] != event["task_hash"]),
                "run_task_hash_mismatch")
    path.parent.mkdir(parents=True, exist_ok=True)
    enriched = dict(event)
    enriched["recorded_at"] = datetime.now(timezone.utc).replace(
        microsecond=0
    ).isoformat()
    enriched["previous_event_hash"] = existing[-1]["event_hash"] if existing else None
    enriched["event_hash"] = hash_id(canonical(enriched))
    with path.open("a", encoding="utf-8") as stream:
        stream.write(canonical(enriched) + "\n")


def evaluate(events: list[dict]) -> dict:
    records: dict[str, dict[str, dict]] = {}
    for event in events:
        _validate_event(event)
        entry = records.setdefault(event["run_id"], {})
        require(event["kind"] not in entry, "duplicate_calibration_event")
        require(all(previous["task_hash"] == event["task_hash"]
                    for previous in entry.values()), "run_task_hash_mismatch")
        entry[event["kind"]] = event

    counts = {
        "runs": len(records), "predictions": 0, "runtimes": 0,
        "verdicts": 0, "eligible_evaluated": 0,
        "excluded_simulated": 0, "excluded_unverified_runtime": 0,
        "excluded_missing_evidence": 0,
        "selected_skill_correct": 0, "selected_experience_correct": 0,
        "fast_path_true_positive": 0, "fast_path_false_positive": 0,
        "fast_path_false_negative": 0, "fast_path_true_negative": 0,
        "observed_frontier_calls": 0,
        "hypothetically_avoidable_calls": 0,
    }
    evaluated = []
    errors = []
    for run_id, items in sorted(records.items()):
        for kind, name in [("prediction", "predictions"), ("runtime", "runtimes"),
                           ("verdict", "verdicts")]:
            counts[name] += int(kind in items)
        p, r, v = (items.get(kind) for kind in ("prediction", "runtime", "verdict"))
        if p is None or r is None or v is None:
            counts["excluded_missing_evidence"] += 1
            continue
        if r["simulation"]:
            counts["excluded_simulated"] += 1
            continue
        if not r["audit_verified"]:
            counts["excluded_unverified_runtime"] += 1
            continue
        require(p["frontier_call_avoided"] is False, "shadow_claims_savings")
        counts["eligible_evaluated"] += 1
        skill_correct = p.get("selected_skill_id") == v.get("expected_skill_id")
        experience_correct = p.get("selected_experience_id") == v.get("expected_experience_id")
        counts["selected_skill_correct"] += int(skill_correct)
        counts["selected_experience_correct"] += int(experience_correct)
        # True positives require matching the *correct* safe skill, not merely
        # a reviewer saying there existed some safe procedure.
        predicted = p["fast_path_candidate"]
        actual = v["fast_path_safe"] and skill_correct
        confusion = (
            "fast_path_true_positive" if predicted and actual else
            "fast_path_false_positive" if predicted and not actual else
            "fast_path_false_negative" if not predicted and v["fast_path_safe"] else
            "fast_path_true_negative"
        )
        counts[confusion] += 1
        calls = r["actual_model_calls"]
        counts["observed_frontier_calls"] += calls
        hypothetical = int(predicted and actual and calls > 0)
        counts["hypothetically_avoidable_calls"] += hypothetical
        evaluated.append({
            "run_id": run_id,
            "recommendation": p["recommendation"],
            "selected_skill_correct": skill_correct,
            "selected_experience_correct": experience_correct,
            "fast_path_outcome": confusion,
            "reported_tokens": r.get("reported_tokens"),
            "reported_cost_usd": r.get("reported_cost_usd"),
            "evidence_ref": v["evidence_ref"],
            "observed_calls": calls,
            "hypothetically_avoidable_calls": hypothetical,
        })
    tp = counts["fast_path_true_positive"]
    fp = counts["fast_path_false_positive"]
    fn = counts["fast_path_false_negative"]
    denom = tp + fp
    recall_denom = tp + fn
    evaluated_count = counts["eligible_evaluated"]
    return {
        "schema_version": SCHEMA, "mode": "calibration_only",
        "authority": "none_shadow_evaluation_only",
        "summary": counts,
        "metrics": {
            "skill_selection_accuracy": round(counts["selected_skill_correct"] / evaluated_count, 6)
            if evaluated_count else None,
            "experience_selection_accuracy": round(counts["selected_experience_correct"] / evaluated_count, 6)
            if evaluated_count else None,
            "fast_path_precision": round(tp / denom, 6) if denom else None,
            "fast_path_recall": round(tp / recall_denom, 6) if recall_denom else None,
            "fast_path_false_positive_rate_among_predictions": round(fp / denom, 6)
            if denom else None,
        },
        "estimated_token_savings": None,
        "realized_frontier_calls_avoided": 0,
        "notes": [
            "Only paired independently reviewed non-simulated audited runs are scored.",
            "Hypothetical avoidable calls are task opportunities, not estimated saved model calls/tokens.",
            "Skill accuracy includes the correct null prediction when no skill was needed.",
            "No Fast Path execution is enabled and this is not proof of safe automation.",
        ],
        "evaluated": evaluated,
        "excluded_or_invalid_records": errors,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="CIDM Arsenal calibration and outcome scoring")
    parser.add_argument("--ledger", type=Path, default=Path("~/.jev/arsenal/calibration.jsonl"))
    sub = parser.add_subparsers(dest="command", required=True)

    capture = sub.add_parser("capture", help="Record a shadow prediction and native runtime")
    capture.add_argument("--run-id", required=True)
    capture.add_argument("--result", type=Path, required=True)

    label = sub.add_parser("adjudicate", help="Append independent ground truth with evidence")
    label.add_argument("--run-id", required=True)
    label.add_argument("--task-hash", required=True)
    label.add_argument("--evidence-ref", required=True)
    label.add_argument("--reviewer", required=True)
    label.add_argument("--expected-skill-id")
    label.add_argument("--expected-experience-id")
    label.add_argument("--fast-path-safe", choices=("yes", "no"), required=True)

    sub.add_parser("evaluate", help="Read-only quality scoring; no model calls")
    args = parser.parse_args(argv)
    path = args.ledger.expanduser()
    if args.command == "capture":
        result = json.loads(args.result.read_text(encoding="utf-8"))
        require("arsenal_shadow" in result, "shadow_missing_from_runtime")
        p = prediction_event(args.run_id, result["task_hash"], result["arsenal_shadow"])
        r = runtime_event(args.run_id, result)
        # Ensure both are absent before the first append.
        existing = read_events(path)
        require(not any(e["run_id"] == args.run_id for e in existing),
                "duplicate_or_partial_capture")
        append_event(path, p)
        append_event(path, r)
        output = {"recorded": ["prediction", "runtime"], "run_id": args.run_id}
    elif args.command == "adjudicate":
        existing = read_events(path)
        paired = [e for e in existing if e["run_id"] == args.run_id]
        require({e["kind"] for e in paired} >= {"prediction", "runtime"},
                "adjudication_requires_recorded_run")
        v = verdict_event(
            args.run_id, args.task_hash, evidence_ref=args.evidence_ref,
            expected_skill_id=args.expected_skill_id,
            expected_experience_id=args.expected_experience_id,
            fast_path_safe=args.fast_path_safe == "yes",
            reviewer=args.reviewer,
        )
        append_event(path, v)
        output = {"recorded": ["verdict"], "run_id": args.run_id}
    else:
        output = evaluate(read_events(path))
    print(json.dumps(output, indent=2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
