"""Arsenal Phase A: bind Fast Path eligibility to real permits and validator receipts.

The registry decides whether a matched skill is *eligible*. This executor adds
the remaining V1 conditions before any no-frontier execution:

1. an owner-authored policy file enables Fast Path and pins the exact skill and
   manifest hashes and operations (no file means disabled);
2. optionally, a calibration threshold report the owner accepted (by hash)
   met the owner's bar;
3. the operation is registered trusted host code, reversible, and has its inputs;
4. every declared validator is registered and deterministic;
5. the skill files on disk still hash to the admitted version (no TOCTOU);
6. one `fast_path.execute` permit with a `compiled_policy` basis is consumed.

A validated run is commit-eligible under the compiled policy. Any failure,
missing piece, or exception escalates to Jev with the receipts collected so far.
This module never calls a model and never commits by itself; the host does.
"""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any, Callable

from arsenal_registry import ArsenalRegistry, compile_skill
from capability_permits import HashChainLedger, PermitAuthority, digest, require

POLICY_FIELDS = {"schema_version", "enabled", "owner", "approved_at", "skills", "calibration"}


def load_policy(value: dict | None) -> dict | None:
    """Normalise an owner Fast Path policy; None means Fast Path is disabled."""
    if value is None:
        return None
    require(isinstance(value, dict) and set(value) == POLICY_FIELDS, "fast_path_policy_schema")
    require(value["schema_version"] == 1, "unsupported_fast_path_policy")
    require(type(value["enabled"]) is bool, "invalid_fast_path_enabled")
    for key in ("owner", "approved_at"):
        require(isinstance(value[key], str) and 0 < len(value[key]) <= 200, "invalid_policy_" + key)
    skills = value["skills"]
    require(isinstance(skills, dict) and len(skills) <= 200, "invalid_policy_skills")
    for skill_id, pin in skills.items():
        require(isinstance(pin, dict) and set(pin) == {"skill_hash", "manifest_hash", "operations"},
                "invalid_policy_skill_pin")
        require(all(isinstance(pin[k], str) and len(pin[k]) == 64 for k in ("skill_hash", "manifest_hash")),
                "policy_pin_requires_sha256")
        require(isinstance(pin["operations"], list) and pin["operations"]
                and all(isinstance(op, str) for op in pin["operations"]), "invalid_policy_operations")
    calibration = value["calibration"]
    require(calibration is None or (isinstance(calibration, dict)
                                    and set(calibration) == {"report_hash"}
                                    and isinstance(calibration["report_hash"], str)
                                    and len(calibration["report_hash"]) == 64),
            "invalid_policy_calibration")
    normalized = copy.deepcopy(value)
    return {**normalized, "policy_hash": digest(normalized)}


class FastPathExecutor:
    def __init__(self, registry: ArsenalRegistry, authority: PermitAuthority, *,
                 policy: dict | None = None, operations: dict | None = None,
                 validators: dict | None = None, calibration_report: dict | None = None,
                 ledger_path: Path | None = None):
        self.registry, self.authority = registry, authority
        self.policy = load_policy(policy)
        self.operations: dict[str, dict] = {}
        self.validators: dict[str, Callable] = {}
        for op_id, spec in (operations or {}).items():
            self.register_operation(op_id, **spec)
        for validator_id, fn in (validators or {}).items():
            self.register_validator(validator_id, fn)
        self.calibration_report = copy.deepcopy(calibration_report)
        self.ledger = HashChainLedger(ledger_path)

    def register_operation(self, op_id: str, *, fn: Callable, required_inputs=(), reversible: bool):
        require(isinstance(op_id, str) and op_id and callable(fn), "invalid_fast_path_operation")
        require(type(reversible) is bool, "operation_reversibility_required")
        self.operations[op_id] = {"fn": fn, "required_inputs": tuple(required_inputs),
                                  "reversible": reversible}

    def register_validator(self, validator_id: str, fn: Callable):
        require(isinstance(validator_id, str) and validator_id and callable(fn), "invalid_fast_path_validator")
        self.validators[validator_id] = fn

    def _calibration_reasons(self) -> list[str]:
        required = (self.policy or {}).get("calibration")
        if required is None:
            return []
        report = self.calibration_report
        if not isinstance(report, dict):
            return ["calibration_report_required"]
        body = {k: v for k, v in report.items() if k != "report_hash"}
        from arsenal_calibration import canonical as calibration_canonical, hash_id
        if hash_id(calibration_canonical(body)) != report.get("report_hash"):
            return ["calibration_report_hash_invalid"]
        if report.get("report_hash") != required["report_hash"]:
            return ["calibration_report_not_owner_accepted"]
        return [] if report.get("meets_operator_threshold") is True else ["calibration_threshold_not_met"]

    def evaluate(self, task: str, *, project_scope: str | None, bug_key: str | None,
                 operation: str | None, inputs: dict) -> dict:
        """Decide Fast Path readiness without executing anything."""
        require(isinstance(inputs, dict), "fast_path_inputs_must_be_object")
        match = self.registry.match(task, project_scope=project_scope, bug_key=bug_key, operation=operation)
        best = (match.get("matches") or [None])[0] if match.get("decision") == "known_skill" else None
        reasons: list[str] = []
        if best is None:
            reasons.append("no_known_skill")
        else:
            reasons.extend(match["fast_path"]["reasons"])
        policy = self.policy
        if policy is None:
            reasons.append("fast_path_policy_absent")
        elif not policy["enabled"]:
            reasons.append("fast_path_policy_disabled")
        pin = (policy or {}).get("skills", {}).get(best["skill_id"]) if best else None
        if best is not None and policy is not None:
            if pin is None:
                reasons.append("skill_not_in_owner_policy")
            else:
                if pin["skill_hash"] != best["skill_hash"] or pin["manifest_hash"] != best["manifest_hash"]:
                    reasons.append("policy_pin_hash_mismatch")
                if operation not in pin["operations"]:
                    reasons.append("operation_not_in_owner_policy")
        reasons.extend(self._calibration_reasons())
        spec = self.operations.get(operation) if operation else None
        if spec is None:
            reasons.append("operation_not_registered")
        else:
            if not spec["reversible"]:
                reasons.append("operation_not_reversible")
            missing = [name for name in spec["required_inputs"] if name not in inputs]
            if missing:
                reasons.append("missing_required_inputs")
        declared = best["validators"] if best else []
        if best is not None and any(v not in self.validators for v in declared):
            reasons.append("declared_validator_not_registered")
        reasons = list(dict.fromkeys(reasons))
        return {"decision": "fast_path_ready" if not reasons else "escalate_to_jev",
                "reasons": reasons, "skill_id": best["skill_id"] if best else None,
                "skill_hash": best["skill_hash"] if best else None,
                "manifest_hash": best["manifest_hash"] if best else None,
                "skill_path": best["skill_path"] if best else None,
                "validators": list(declared), "operation": operation,
                "policy_hash": (policy or {}).get("policy_hash"),
                "match_hash": digest({k: v for k, v in match.items() if k != "experience_matches"}),
                "experience_matches": [m["lesson_id"] for m in match.get("experience_matches", [])]}

    def _record(self, outcome: dict) -> dict:
        event = {"kind": "fast_path_attempt", **{k: v for k, v in outcome.items() if k != "artifact"}}
        self.ledger.append(event)
        return outcome

    def execute(self, task: str, *, project_scope: str | None, bug_key: str | None,
                operation: str | None, inputs: dict) -> dict:
        decision = self.evaluate(task, project_scope=project_scope, bug_key=bug_key,
                                 operation=operation, inputs=inputs)
        base = {"decision": decision, "commit_eligible": False, "frontier_call_avoided": False,
                "receipts": [], "artifact": None, "artifact_hash": None}
        if decision["decision"] != "fast_path_ready":
            return self._record({**base, "status": "escalate_to_jev", "reason": "not_ready"})
        # Re-hash the admitted files immediately before execution.
        current = compile_skill(Path(decision["skill_path"]))
        if current.skill_hash != decision["skill_hash"] or current.manifest_hash != decision["manifest_hash"]:
            return self._record({**base, "status": "escalate_to_jev", "reason": "skill_changed_on_disk"})
        scope = {"skill_id": decision["skill_id"], "skill_hash": decision["skill_hash"],
                 "manifest_hash": decision["manifest_hash"], "operation": operation,
                 "inputs_hash": digest(inputs), "project_scope": project_scope, "bug_key": bug_key}
        basis = {"kind": "compiled_policy", "policy_hash": decision["policy_hash"],
                 "skill_id": decision["skill_id"], "skill_hash": decision["skill_hash"],
                 "manifest_hash": decision["manifest_hash"]}
        permit_id = self.authority.issue("fast_path.execute", scope, basis)
        self.authority.consume(permit_id, "fast_path.execute", scope)
        outcome: dict[str, Any] = {**base, "permit_id": permit_id}
        try:
            artifact = self.operations[operation]["fn"](copy.deepcopy(inputs))
            require(isinstance(artifact, dict), "fast_path_operation_must_return_object")
            outcome["artifact"], outcome["artifact_hash"] = artifact, digest(artifact)
            for validator_id in decision["validators"]:
                verdict = self.validators[validator_id](copy.deepcopy(artifact), copy.deepcopy(inputs))
                passed, detail = verdict if isinstance(verdict, tuple) else (verdict, None)
                require(type(passed) is bool, "validator_must_return_boolean")
                outcome["receipts"].append({"validator": validator_id, "passed": passed,
                                            "detail_hash": digest(detail) if detail is not None else None,
                                            "artifact_hash": outcome["artifact_hash"]})
            if outcome["receipts"] and all(r["passed"] for r in outcome["receipts"]):
                outcome.update(status="validated_under_compiled_policy", commit_eligible=True,
                               frontier_call_avoided=True, reason="all_declared_validators_passed")
            else:
                failed = [r["validator"] for r in outcome["receipts"] if not r["passed"]]
                outcome.update(status="escalate_to_jev", reason="validator_failed",
                               recovery_input={"failed_validators": failed, "skill_id": decision["skill_id"],
                                               "artifact_hash": outcome["artifact_hash"]})
        except Exception as error:
            outcome.update(status="escalate_to_jev", reason="operation_error",
                           error=type(error).__name__ + ": " + str(error)[:200])
        self.authority.receipt(permit_id, {"status": outcome["status"],
                                           "artifact_hash": outcome["artifact_hash"],
                                           "receipts": outcome["receipts"]})
        return self._record(outcome)


def avoidance_summary(events: list[dict]) -> dict:
    """Frontier-call avoidance from executed attempts only; shadow data is excluded."""
    attempts = [e for e in events if e.get("kind") == "fast_path_attempt"]
    avoided = [e for e in attempts if e.get("frontier_call_avoided") is True]
    reasons: dict[str, int] = {}
    for event in attempts:
        reasons[event.get("reason", "unknown")] = reasons.get(event.get("reason", "unknown"), 0) + 1
    return {"attempts": len(attempts), "frontier_calls_avoided": len(avoided),
            "escalated_to_jev": sum(e.get("status") == "escalate_to_jev" for e in attempts),
            "by_reason": dict(sorted(reasons.items())),
            "by_skill": {sid: sum(e.get("decision", {}).get("skill_id") == sid for e in avoided)
                         for sid in sorted({e.get("decision", {}).get("skill_id") for e in avoided})},
            "note": "Counts executed, validated Fast Path attempts; one attempt may replace "
                    "several Jev/worker calls, so tokens saved remain unmeasured."}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate CIDM Fast Path readiness (no execution)")
    parser.add_argument("--db", type=Path, default=Path("~/.jev/arsenal/arsenal.db").expanduser())
    parser.add_argument("--policy", type=Path)
    parser.add_argument("--calibration-report", type=Path)
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("check")
    check.add_argument("--task", required=True)
    check.add_argument("--project-scope")
    check.add_argument("--bug-key")
    check.add_argument("--operation")
    summary = sub.add_parser("summary")
    summary.add_argument("--ledger", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "summary":
        print(json.dumps(avoidance_summary(HashChainLedger(args.ledger).read()), indent=2, sort_keys=True))
        return 0
    policy = json.loads(args.policy.read_text(encoding="utf-8")) if args.policy else None
    report = (json.loads(args.calibration_report.read_text(encoding="utf-8"))
              if args.calibration_report else None)
    with ArsenalRegistry(args.db) as registry:
        executor = FastPathExecutor(registry, PermitAuthority(), policy=policy, calibration_report=report)
        # The CLI has no trusted operation handlers, so it reports readiness of
        # everything except operation registration; hosts register handlers in code.
        result = executor.evaluate(args.task, project_scope=args.project_scope, bug_key=args.bug_key,
                                   operation=args.operation, inputs={})
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
