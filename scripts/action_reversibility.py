#!/usr/bin/env python3
"""Non-reversible-action gate (P0-05 slice 2).

Standard capability permits bind scope and single-use but do not express
whether an action can be undone. A `delete_file` call that passes a 'mutate'
permit is still non-reversible and should require an extra explicit
operator approval beyond the permit itself.

This module classifies action names and arguments by reversibility and
exports a small gate used by the broker and the Hermes adapter when they
dispatch a tool call. The classifier is deliberately conservative:
- known destructive / external-effect verbs → non_reversible.
- known read verbs → reversible.
- plain writes default to non_reversible (over-restriction forces an
  explicit decision; under-restriction silently loses the gate).
- everything else → unknown, which the gate treats as non-reversible.

Tool annotations may carry an explicit `reversibility_hint`. The stricter
direction always wins; a reversible-named action with an explicit
non_reversible hint is non-reversible. On an untrusted server (slice-1
trust gate), callers should refuse to read the hint.
"""
from __future__ import annotations

import re
from typing import Any

# Each tuple is (regex, classification). Matched left-to-right; first hit wins.
_NAME_RULES: tuple[tuple[re.Pattern, str], ...] = (
    # Destructive verbs — must be matched before softer writes.
    (re.compile(r"^(delete|drop|destroy|wipe|remove|rm|purge|erase|forget)([_\-].*)?$"),
     "non_reversible"),
    (re.compile(r"^rmdir$|^rm_dir$|^rm_rf$"), "non_reversible"),
    # External side-effect verbs: once sent, cannot be unsent.
    (re.compile(r"^(send|post|publish|deploy|release|charge|pay|notify|email|sms|"
                r"webhook|slack|tweet)([_\-].*)?$"), "non_reversible"),
    (re.compile(r"^(post_webhook|post_slack|publish_tweet)$"), "non_reversible"),
    # Plain writes default to non-reversible.
    (re.compile(r"^(write|update|patch|put|replace|overwrite|append|insert|"
                r"create)([_\-].*)?$"), "non_reversible"),
    (re.compile(r"^alter([_\-].*)?$"), "non_reversible"),
    # Reads — only after the stricter rules above so a 'read_delete_log' call
    # (unlikely but possible) still classifies as reversible by its leading verb.
    (re.compile(r"^(read|get|list|search|find|fetch|lookup|describe|show|"
                r"inspect|peek|head|tail)([_\-].*)?$"), "reversible"),
)


class NonReversibleActionError(RuntimeError):
    """Raised when a non-reversible action is attempted without an active
    operator approval."""


def classify_action(name: str, annotations: dict | None) -> str:
    """Return 'reversible', 'non_reversible', or 'unknown'.

    Precedence: an explicit `reversibility_hint` wins when it is
    'non_reversible' (strictest direction); otherwise name-based rules fire;
    a hint of 'reversible' only applies when name-rules do not say otherwise.
    """
    annotations = annotations or {}
    hint = str(annotations.get("reversibility_hint") or "").strip().lower()
    if hint == "non_reversible":
        return "non_reversible"
    name_lower = str(name or "").strip().lower()
    for pattern, classification in _NAME_RULES:
        if pattern.match(name_lower):
            return classification
    if hint == "reversible":
        return "reversible"
    return "unknown"


def is_blocked_without_approval(action: str, annotations: dict | None, *,
                                approval: dict | None) -> bool:
    """True if the action requires an approval that is not present/valid.

    `approval` is the full record (or None). Valid approvals must have
    `status == 'approved'`, a non-empty `operator`, and an `action` string
    that matches `action` exactly (same name — approvals are action-bound,
    cannot be replayed for a different call).

    Unknown classifications are treated as non_reversible: safe-by-default.
    """
    kind = classify_action(action, annotations)
    if kind == "reversible":
        return False
    # non_reversible or unknown → approval needed.
    if not isinstance(approval, dict):
        return True
    if approval.get("status") != "approved":
        return True
    operator = str(approval.get("operator") or "").strip()
    bound = str(approval.get("action") or "").strip()
    if not operator or bound != action:
        return True
    return False


def require_approval(action: str, annotations: dict | None, *,
                     approval: dict | None) -> dict:
    """Enforce the gate. Returns an informational dict on pass; raises on
    `NonReversibleActionError` otherwise."""
    kind = classify_action(action, annotations)
    if is_blocked_without_approval(action, annotations, approval=approval):
        raise NonReversibleActionError(
            action + " is " + kind + " and requires an operator approval bound to this action")
    info: dict[str, Any] = {
        "action": action, "classification": kind,
        "approval_required": kind != "reversible",
    }
    if isinstance(approval, dict) and approval.get("status") == "approved":
        info["approved_by"] = str(approval.get("operator") or "")
    return info
