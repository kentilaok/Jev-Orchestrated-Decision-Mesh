"""Single-use CIDM capability permits for consequential tool and model actions.

Arsenal V1 rule: a tool can suggest a route, but only Jev (or an owner-admitted
compiled policy) can authorize a state transition. Every frontier run, MCP call,
sandbox action, browser action, and Fast Path execution therefore consumes one
permit whose scope hash binds the exact action. A permit is authorization data,
not a credential, and it never carries secret values.

The ledger is append-only, hash-chained JSONL. It is tamper-evident for partial
alteration, not protection against someone who can rewrite the whole file.
"""
from __future__ import annotations

import copy
import hashlib
import json
import threading
import time
import uuid
from pathlib import Path
from typing import Any


class PermitError(ValueError):
    pass


def require(ok: bool, code: str) -> None:
    if not ok:
        raise PermitError(code)


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


# Capability classes and the authorization bases each one accepts.
# "strong" classes change external state or expose secrets; they never accept
# an operator console click or a compiled policy on their own.
CAPABILITIES = {
    "frontier.run": {"strong": False},
    "retrieval.query": {"strong": False},
    "mcp.read": {"strong": False},
    "mcp.mutate": {"strong": True},
    "browser.read": {"strong": False},
    "browser.extract": {"strong": False},
    "browser.mutate": {"strong": True},
    "browser.submit_transaction": {"strong": True},
    "sandbox.create": {"strong": False},
    "sandbox.exec": {"strong": False},
    "sandbox.import_artifacts": {"strong": True},
    "secret.use": {"strong": True},
    "fast_path.execute": {"strong": False},
}

BASES = {
    # A Jev typed decision; the receipt names the gate and its state hash.
    "jev_decision": {"decision_id", "choice", "state_hash"},
    # A dispatch already authorized inside a CIDM mesh (the mesh event names its gate).
    "cidm_mesh_dispatch": {"event_id", "gate_id", "action_hash"},
    # The explicit short route: a host classification bound to one input snapshot.
    "host_short_classification": {"snapshot_hash", "classification_source"},
    # Recovery retrieval after Jev selected retrieve_evidence.
    "cidm_recovery_evidence": {"unit_id", "decision_event_id", "mesh_version"},
    # An owner-admitted compiled Fast Path policy.
    "compiled_policy": {"policy_hash", "skill_id", "skill_hash", "manifest_hash"},
    # A human operator action in the local console.
    "operator": {"operator", "reason"},
}

WEAK_ONLY_BASES = {"operator", "compiled_policy", "host_short_classification"}


def validate_basis(capability: str, basis: dict) -> dict:
    require(capability in CAPABILITIES, "unknown_capability")
    require(isinstance(basis, dict) and basis.get("kind") in BASES, "invalid_permit_basis")
    kind = basis["kind"]
    fields = BASES[kind]
    require(fields <= set(basis), "permit_basis_missing_fields")
    for key in fields:
        value = basis[key]
        require(isinstance(value, (str, int)) and not isinstance(value, bool)
                and 0 < len(str(value)) <= 256, "invalid_permit_basis_field")
    if kind == "jev_decision":
        require(basis.get("live") is True or basis.get("simulation") is True,
                "jev_basis_must_declare_live_or_simulation")
    if kind == "compiled_policy":
        require(capability == "fast_path.execute", "compiled_policy_only_authorizes_fast_path")
    if CAPABILITIES[capability]["strong"]:
        require(kind not in WEAK_ONLY_BASES, "strong_capability_requires_jev_basis")
    return copy.deepcopy(basis)


class HashChainLedger:
    """Append-only JSONL with a SHA-256 link to the previous line. Single writer."""

    def __init__(self, path: Path | None):
        self.path = Path(path).expanduser() if path is not None else None
        self.memory: list[dict] = []
        self.lock = threading.Lock()
        self._last = None
        if self.path is not None and self.path.exists():
            for event in self.read():
                self._last = event["event_hash"]

    def read(self) -> list[dict]:
        if self.path is None:
            return copy.deepcopy(self.memory)
        if not self.path.exists():
            return []
        events, previous = [], None
        with self.path.open(encoding="utf-8") as stream:
            for number, line in enumerate(stream, 1):
                event = json.loads(line)
                unsigned = {k: v for k, v in event.items() if k != "event_hash"}
                require(event.get("previous_event_hash") == previous, f"ledger_chain_broken_line_{number}")
                require(digest(unsigned) == event.get("event_hash"), f"ledger_hash_mismatch_line_{number}")
                events.append(event)
                previous = event["event_hash"]
        return events

    def append(self, event: dict) -> dict:
        with self.lock:
            record = copy.deepcopy(event)
            record["recorded_at"] = round(time.time(), 3)
            record["previous_event_hash"] = self._last
            record["event_hash"] = digest(record)
            if self.path is None:
                self.memory.append(record)
            else:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("a", encoding="utf-8") as stream:
                    stream.write(canonical(record) + "\n")
            self._last = record["event_hash"]
            return copy.deepcopy(record)


class PermitAuthority:
    """Issue, consume, and receipt single-use capability permits."""

    def __init__(self, ledger_path: Path | None = None, *, default_ttl_seconds: float = 900,
                 clock=time.time):
        require(0 < default_ttl_seconds <= 86_400, "invalid_permit_ttl")
        self.ledger = HashChainLedger(ledger_path)
        self.default_ttl = default_ttl_seconds
        self.clock = clock
        self._permits: dict[str, dict] = {}
        self._used: set[str] = set()
        self.lock = threading.Lock()

    def issue(self, capability: str, scope: dict, basis: dict, *, ttl_seconds: float | None = None,
              budget: dict | None = None) -> str:
        require(isinstance(scope, dict) and scope, "permit_scope_required")
        checked = validate_basis(capability, basis)
        ttl = self.default_ttl if ttl_seconds is None else ttl_seconds
        require(0 < ttl <= 86_400, "invalid_permit_ttl")
        require(budget is None or isinstance(budget, dict), "invalid_permit_budget")
        permit_id = uuid.uuid4().hex
        now = self.clock()
        grant = {
            "permit_id": permit_id, "capability": capability,
            "scope_hash": digest(scope), "scope": copy.deepcopy(scope),
            "basis": checked, "basis_hash": digest(checked),
            "issued_at": now, "expires_at": now + ttl,
            "budget": copy.deepcopy(budget),
        }
        with self.lock:
            self._permits[permit_id] = grant
        self.ledger.append({"kind": "permit_issued", **{k: v for k, v in grant.items() if k != "scope"},
                            "scope_keys": sorted(scope)})
        return permit_id

    def consume(self, permit_id: str, capability: str, scope: dict) -> dict:
        with self.lock:
            require(isinstance(permit_id, str) and permit_id in self._permits, "unknown_permit")
            require(permit_id not in self._used, "permit_already_used")
            grant = self._permits[permit_id]
            require(grant["capability"] == capability, "permit_capability_mismatch")
            require(grant["scope_hash"] == digest(scope), "permit_scope_mismatch")
            require(self.clock() <= grant["expires_at"], "permit_expired")
            self._used.add(permit_id)
        self.ledger.append({"kind": "permit_consumed", "permit_id": permit_id,
                            "capability": capability, "scope_hash": grant["scope_hash"]})
        return copy.deepcopy(grant)

    def receipt(self, permit_id: str, outcome: dict) -> dict:
        require(permit_id in self._used, "receipt_requires_consumed_permit")
        require(isinstance(outcome, dict), "invalid_receipt_outcome")
        return self.ledger.append({"kind": "permit_receipt", "permit_id": permit_id,
                                   "outcome_hash": digest(outcome),
                                   "status": outcome.get("status")})

    def events(self) -> list[dict]:
        return self.ledger.read()


def audit_permit_ledger(events: list[dict], journal_events: list[dict] | None = None) -> dict:
    """Check that every consumed permit was issued once, used once, and receipted.

    With a CIDM journal, `cidm_mesh_dispatch` bases must name a real dispatch
    event whose gate and action hash match.
    """
    issues, issued, consumed, receipted = [], {}, set(), set()
    dispatch = {e.get("id"): e for e in journal_events or [] if e.get("kind") in ("dispatch", "deferred_dispatch")}
    for event in events:
        kind, pid = event.get("kind"), event.get("permit_id")
        if kind == "permit_issued":
            if pid in issued:
                issues.append("duplicate_issue:" + str(pid))
            issued[pid] = event
            basis = event.get("basis") or {}
            if journal_events is not None and basis.get("kind") == "cidm_mesh_dispatch":
                source = dispatch.get(basis.get("event_id"))
                if (source is None or source.get("gate_id") != basis.get("gate_id")
                        or source.get("action_hash") != basis.get("action_hash")):
                    issues.append("basis_not_in_journal:" + str(pid))
        elif kind == "permit_consumed":
            if pid not in issued:
                issues.append("consumed_without_issue:" + str(pid))
            elif pid in consumed:
                issues.append("double_consumption:" + str(pid))
            elif issued[pid].get("scope_hash") != event.get("scope_hash"):
                issues.append("consumed_scope_mismatch:" + str(pid))
            consumed.add(pid)
        elif kind == "permit_receipt":
            if pid not in consumed:
                issues.append("receipt_without_consumption:" + str(pid))
            receipted.add(pid)
    missing = sorted(consumed - receipted)
    issues.extend("consumed_without_receipt:" + pid for pid in missing)
    return {"valid": not issues, "issues": issues, "issued": len(issued),
            "consumed": len(consumed), "receipted": len(receipted),
            "unused": sorted(set(issued) - consumed)}
