"""Recovery-first supervisor for the separate-gate CIDM reference controller.

A failed candidate still cannot forward. This layer changes what happens after a
local failure: bounded recovery/replanning is preferred, and unresolved external
dependencies become resumable checkpoints instead of terminal project failure.
"""
from __future__ import annotations

import copy
from dataclasses import asdict, dataclass
from typing import Any, Callable

from atomic_mesh import fingerprint, require


@dataclass(frozen=True)
class RecoveryCheckpoint:
    checkpoint_id: str
    status: str
    active_unit: str
    active_index: int
    completed_units: tuple[str, ...]
    recovery_kind: str
    reason: str
    recovery_round: int
    policy_version: str | None
    mesh_state_hash: str | None
    event_cursor: int

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["completed_units"] = list(self.completed_units)
        return value


class RecoveryJudge:
    """Remove premature `stop` from Jev's menu while useful progress exists.

    The wrapped Jev judge still chooses the action. The adapter only changes the
    action set. An operator abort hook can restore `stop` immediately.
    """

    def __init__(self, judge: Callable, *, abort_requested: Callable[[], bool] | None = None):
        self.judge = judge
        self.abort_requested = abort_requested or (lambda: False)

    def filter_options(self, phase, options, state):
        """Return the exact option set that should be shown, hashed, and journaled."""
        offered = copy.deepcopy(options)
        # Keep at least two typed alternatives because Jev choice questions require
        # a genuine decision. Failed-result gates normally contain repair,
        # retrieve_evidence, and stop, so stop can be removed safely there.
        if "stop" in offered and len(offered) > 2 and not self.abort_requested():
            del offered["stop"]
        return offered

    def __call__(self, phase, options, state):
        decision = self.judge(phase, options, state)
        require(isinstance(decision, dict) and decision.get("choice") in options,
                "recovery_judge_invalid_choice")
        return decision


def build_recovery_network(goal, sources, judge, producer, checker, validator, *,
                           policy=None, checker_identity=None, worker_routes=None,
                           simulation=False, journal=None, units=None,
                           deterministic_units=None, abort_requested=None):
    """Construct a CheckedNetwork with recovery-first gate semantics."""
    from checked_network import CheckedNetwork, UNITS
    effective = copy.deepcopy(policy or {"version": "recovery-first-v1"})
    effective.setdefault("max_recovery_attempts", 2)
    effective.setdefault("max_verification_attempts", 2)
    return CheckedNetwork(
        goal, sources, RecoveryJudge(judge, abort_requested=abort_requested),
        producer, checker, validator, policy=effective,
        checker_identity=checker_identity, worker_routes=worker_routes,
        simulation=simulation, journal=journal,
        units=UNITS if units is None else units,
        deterministic_units=deterministic_units,
    )


class RecoverySupervisor:
    """Run CheckedNetwork unit-by-unit with bounded recovery rounds.

    Repair/verification limits trigger a fresh local replan of the same unit.
    Missing evidence can call a trusted read-only evidence retriever. If that
    dependency cannot be resolved, the supervisor emits an auditable checkpoint.
    """

    def __init__(self, network, *, evidence_retriever: Callable[[dict], dict | None] | None = None,
                 max_recovery_rounds: int = 2):
        require(type(max_recovery_rounds) is int and 0 <= max_recovery_rounds <= 8,
                "invalid_recovery_round_limit")
        self.network = network
        self.evidence_retriever = evidence_retriever
        self.max_recovery_rounds = max_recovery_rounds
        self.recovery_rounds: dict[str, int] = {}
        self.checkpoint: RecoveryCheckpoint | None = None

    def _event(self, kind: str, **data):
        return self.network.mesh.record(kind, **data)

    def _state_hash(self):
        try:
            return self.network.mesh.state_hash()
        except Exception:
            return None

    def _checkpoint(self, unit, index: int, kind: str, reason: str) -> dict:
        completed = tuple(packet["id"] for packet in self.network.committed)
        round_no = self.recovery_rounds.get(unit.id, 0)
        payload = {
            "status": "paused_recoverable",
            "active_unit": unit.id,
            "active_index": index,
            "completed_units": list(completed),
            "recovery_kind": kind,
            "reason": reason,
            "recovery_round": round_no,
            "policy_version": getattr(self.network, "policy_version", None),
            "mesh_state_hash": self._state_hash(),
            "event_cursor": len(self.network.mesh.events),
        }
        checkpoint_id = fingerprint(payload)
        self.checkpoint = RecoveryCheckpoint(
            checkpoint_id=checkpoint_id, status=payload["status"],
            active_unit=unit.id, active_index=index, completed_units=completed,
            recovery_kind=kind, reason=reason, recovery_round=round_no,
            policy_version=payload["policy_version"],
            mesh_state_hash=payload["mesh_state_hash"],
            event_cursor=payload["event_cursor"],
        )
        self._event("recovery_checkpoint", unit_id=unit.id,
                    checkpoint=self.checkpoint.to_dict())
        return self._result("paused_recoverable", checkpoint=self.checkpoint.to_dict())

    def _append_evidence(self, packet: dict, *, unit_id: str):
        require(isinstance(packet, dict) and packet, "retrieved_evidence_must_be_nonempty_object")
        mesh = self.network.mesh
        added = []
        for sid, source in packet.items():
            require(isinstance(sid, str) and sid and sid not in mesh.sources,
                    "retrieved_source_id_must_be_new")
            require(isinstance(source, dict) and isinstance(source.get("text"), str)
                    and 0 < len(source["text"]) <= 1200, "invalid_retrieved_source")
            mesh.sources[sid] = copy.deepcopy(source)
            mesh.source_hashes[sid] = fingerprint(source)
            added.append({"id": sid, "hash": mesh.source_hashes[sid]})
        mesh.version += 1
        self._event("recovery_evidence_added", unit_id=unit_id, added=added)
        feedback = {
            "verdict": "insufficient_evidence",
            "failed_criteria": [],
            "reason": "New original evidence was added; reassess the same unit against the expanded source set.",
            "missing_evidence": [],
            "source_ids": [item["id"] for item in added],
        }
        self.network.recovery_feedback = feedback
        mesh.last_issue = {
            "recovery_kind": "evidence_added", "unit_id": unit_id,
            "source_ids": [item["id"] for item in added],
            "feedback": copy.deepcopy(feedback),
        }

    def _fresh_replan(self, unit, outcome: str):
        round_no = self.recovery_rounds.get(unit.id, 0) + 1
        self.recovery_rounds[unit.id] = round_no
        failed_criteria = []
        missing_evidence = []
        reason = f"Fresh bounded replan after {outcome}."
        for event in reversed(self.network.mesh.events):
            if event.get("unit_id") != unit.id:
                continue
            if event.get("kind") == "post_worker_decision":
                checks = event.get("hard_checks") or {}
                if isinstance(checks, dict):
                    failed_criteria = [k for k, passed in checks.items() if passed is False]
                break
            if event.get("kind") == "post_checker_decision":
                receipt = event.get("receipt") or {}
                result = receipt.get("result") if isinstance(receipt, dict) else None
                if isinstance(result, dict):
                    failed_criteria = list(result.get("failed_criteria") or [])
                    missing_evidence = list(result.get("missing_evidence") or [])
                    reason = result.get("reason") or reason
                break
        feedback = {
            "verdict": "repair_required",
            "failed_criteria": failed_criteria,
            "reason": reason,
            "missing_evidence": missing_evidence,
            "recovery_round": round_no,
        }
        self.network.recovery_feedback = feedback
        issue = {
            "recovery_kind": "replan", "unit_id": unit.id,
            "prior_outcome": outcome, "recovery_round": round_no,
            "feedback": copy.deepcopy(feedback),
        }
        self.network.mesh.last_issue = issue
        self._event("recovery_replan", **issue)

    def _result(self, status: str, **extra) -> dict:
        network = self.network
        result = {
            "status": status,
            "answer": getattr(network, "final", None),
            "protocol_version": "cidm-recovery-first-v1",
            "base_protocol_version": getattr(network, "protocol_version", "cidm-conditional-review-v3"),
            "policy_version": getattr(network, "policy_version", None),
            "simulation": network.mesh.simulation,
            "committed": copy.deepcopy(network.committed),
            "checks": copy.deepcopy(network.checks),
            "events": copy.deepcopy(network.mesh.events),
            "recovery_rounds": copy.deepcopy(self.recovery_rounds),
        }
        result.update(extra)
        return result

    def run(self) -> dict:
        network = self.network
        try:
            index = len(network.committed)
            require([p["id"] for p in network.committed] == [u.id for u in network.units[:index]],
                    "recovery_committed_prefix_invalid")
            while index < len(network.units):
                unit = network.units[index]
                outcome = network.run_unit(unit, index)
                if outcome == "forwarded":
                    index += 1
                    continue

                if outcome == "needs_evidence":
                    if self.evidence_retriever is None:
                        return self._checkpoint(
                            unit, index, "retrieve_evidence",
                            "Additional original evidence is required before this unit can continue.",
                        )
                    packet = self.evidence_retriever({
                        "goal": network.mesh.goal,
                        "unit": {"id": unit.id, "name": unit.name, "objective": unit.objective},
                        "committed": copy.deepcopy(network.committed),
                        "events": copy.deepcopy(network.mesh.events[-8:]),
                        "source_manifest": list(network.mesh.sources),
                    })
                    if not packet:
                        return self._checkpoint(
                            unit, index, "retrieve_evidence",
                            "The evidence retriever returned no new evidence.",
                        )
                    self._append_evidence(packet, unit_id=unit.id)
                    continue

                if outcome in ("repair_limit", "verification_limit"):
                    used = self.recovery_rounds.get(unit.id, 0)
                    if used < self.max_recovery_rounds:
                        self._fresh_replan(unit, outcome)
                        continue
                    return self._checkpoint(
                        unit, index, "recovery_budget_exhausted",
                        f"Local recovery budget exhausted after {used} replans; candidate remains uncommitted.",
                    )

                # A remaining stop is explicit: the filtered gate could not remove
                # it while preserving a valid typed choice, or the operator/judge
                # intentionally selected it. Do not auto-recover over that choice.
                if outcome == "stopped_by_jev":
                    return self._result("stopped_by_jev", terminal=True)

                return self._result(outcome)

            network.final = network.committed[-1]["artifact"]["text"] if network.committed else None
            self._event("recovery_complete", completed_units=[p["id"] for p in network.committed])
            return self._result("complete")
        except Exception as error:
            self._event("halt", error=type(error).__name__ + ": " + str(error))
            return self._result("failed", error=str(error))
