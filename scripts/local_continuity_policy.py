"""Safe provider-mode decisions, separate from Jev authorisation and provider calls."""
from __future__ import annotations

MODES = ("frontier_only", "local_only", "dual_shadow", "auto_fallback")
# These must originate from *trusted provider adapters*, not from arbitrary
# stderr or model-generated prose.
FALLBACK_CLASSES = ("quota_exhausted", "rate_limited")


def decide_worker_mode(*, mode, authority_mode="jev_managed", frontier_error=None,
                       fallback_enabled=False, operation="read", snapshot_hash=None,
                       checkpoint_verified=False):
    if mode not in MODES:
        raise ValueError("unknown_worker_mode")
    if authority_mode not in ("jev_managed", "limited_local_continuity"):
        raise ValueError("unknown_authority_mode")
    if operation not in ("read", "propose"):
        raise ValueError("local_continuity_mutation_prohibited")
    if authority_mode == "limited_local_continuity":
        # This prototype can return read-only proposals but can neither commit
        # nor claim an authoritative Jev decision while Jev is unavailable.
        governance = "read_only_operator_proposal_not_jev"
    else:
        governance = "requires_real_jev_decision_for_commit"
    if mode == "frontier_only":
        return {"mode": mode, "route": "frontier", "governance": governance,
                "fallback": False}
    if mode == "local_only":
        return {"mode": mode, "route": "local", "governance": governance,
                "fallback": False, "frontier_worker_calls_allowed": 0}
    if mode == "dual_shadow":
        return {"mode": mode, "route": "both_shadow", "governance": governance,
                "fallback": False, "release": "withheld_until_independent_validation"}
    if not fallback_enabled:
        return {"mode": mode, "route": "frontier", "fallback": False,
                "governance": governance, "fallback_reason": "not_enabled"}
    if frontier_error is None:
        return {"mode": mode, "route": "frontier", "fallback": False,
                "governance": governance}
    if not isinstance(frontier_error, dict):
        raise ValueError("structured_provider_error_required")
    verified = frontier_error.get("trusted_adapter_classification") is True
    kind = frontier_error.get("error_class")
    if not verified or kind not in FALLBACK_CLASSES:
        return {"mode": mode, "route": "halt", "fallback": False,
                "governance": governance, "fallback_reason": "error_not_approved_for_fallback"}
    if not isinstance(snapshot_hash, str) or not snapshot_hash:
        return {"mode": mode, "route": "halt", "fallback": False,
                "governance": governance, "fallback_reason": "missing_snapshot_hash"}
    if not checkpoint_verified:
        return {"mode": mode, "route": "halt", "fallback": False,
                "governance": governance, "fallback_reason": "checkpoint_not_verified"}
    return {"mode": mode, "route": "local", "fallback": True,
            "governance": governance, "fallback_reason": kind,
            "snapshot_hash": snapshot_hash, "new_permit_required": True,
            "frontier_worker_calls_allowed": 0}
