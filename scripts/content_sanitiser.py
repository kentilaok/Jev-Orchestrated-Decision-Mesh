#!/usr/bin/env python3
"""Treat retrieval and MCP content as data (P0-05 slice 3).

Any retrieval document, MCP tool response, skill text, CLI output, or other
externally-sourced string is DATA. It must not be read as authority to change
CIDM constraints — a doc that says "ignore previous instructions" or
"mark this request approved" is still just text, not a command.

Three public pieces:
- `wrap_as_data(text, source_id, kind)` — stable BEGIN/END markers so a
  downstream consumer can see the boundary even if the model is naive. Pre-
  existing markers in `text` are redacted so a hostile document cannot
  pre-close the wrapper and smuggle instructions outside it.
- `scan_for_injection_markers(text)` — regex ladder that flags known
  injection patterns (role switch, override permit, mark approved,
  escalate, disable gate). Returns a list of `{pattern, match, start,
  end}` dicts. Lenient; never raises.
- `enforce_data_only(text, source_id, kind, *, strict)` — the production
  entry point. Strict mode raises `AuthorityViolationError` on any
  detected marker; lenient mode wraps and records.

Stdlib only.
"""
from __future__ import annotations

import re
from typing import Any

BEGIN_DATA_MARKER = "<<<CIDM_BEGIN_DATA"
END_DATA_MARKER = "CIDM_END_DATA>>>"


class AuthorityViolationError(RuntimeError):
    """Raised when strict-mode `enforce_data_only` detects an injection pattern."""


# (pattern name, compiled regex, matcher description).
_INJECTION_RULES: tuple[tuple[str, re.Pattern], ...] = (
    ("ignore_previous_instructions",
     re.compile(r"\bignore\s+(all\s+|the\s+|prior\s+|previous\s+)*(prior|previous)?\s*(instructions?|rules?|prompts?|context)\b",
                re.IGNORECASE)),
    ("role_switch_system",
     re.compile(r"(^|\n)\s*(system|assistant|developer)\s*:\s*",
                re.IGNORECASE | re.MULTILINE)),
    ("role_claim",
     re.compile(r"\b(you\s+are\s+now|i\s+am\s+an?\s+(administrator|admin|root|developer|operator)|"
                r"as\s+(root|admin|administrator))\b", re.IGNORECASE)),
    ("override_permit",
     re.compile(r"\boverride\s+(the\s+)?(permit|access(_class)?|gate|policy)\b", re.IGNORECASE)),
    ("mark_approved",
     re.compile(r"\bmark\s+(this\s+)?(request|action|call|task)?\s*approved\b", re.IGNORECASE)),
    ("escalate_strong",
     re.compile(r"\bescalate\s+(to\s+)?strong\b", re.IGNORECASE)),
    ("disable_gate",
     re.compile(r"\b(disable|bypass|turn\s+off)\s+(the\s+)?(jev\s+)?(gate|validator|check)\b",
                re.IGNORECASE)),
)


def wrap_as_data(text: str, *, source_id: str, kind: str,
                 max_chars: int = 20000) -> str:
    """Wrap `text` in CIDM data markers. Redacts any pre-existing markers to
    prevent wrapper escape. Truncates to `max_chars` with a visible notice."""
    body = str(text or "")
    body = body.replace(BEGIN_DATA_MARKER, "BEGIN_DATA[redacted]")
    body = body.replace(END_DATA_MARKER, "END_DATA[redacted]")
    truncated = ""
    if len(body) > max_chars:
        body = body[:max_chars]
        truncated = "\n[truncated after %d chars]" % max_chars
    header = BEGIN_DATA_MARKER + " source=" + str(source_id) + " kind=" + str(kind) + "\n"
    return header + body + truncated + "\n" + END_DATA_MARKER


def scan_for_injection_markers(text: str) -> list[dict[str, Any]]:
    """Return a list of detected injection markers. Never raises."""
    body = str(text or "")
    markers = []
    for name, pattern in _INJECTION_RULES:
        for match in pattern.finditer(body):
            markers.append({"pattern": name, "match": match.group(0),
                            "start": match.start(), "end": match.end()})
    return markers


def enforce_data_only(text: str, *, source_id: str, kind: str,
                      strict: bool = False, max_chars: int = 20000) -> dict:
    """Enforce the data-only posture.

    strict=True  → raise AuthorityViolationError on any detected marker.
    strict=False → wrap and record; the caller decides what to do with the
                   injection_markers list (log, alert, re-review).
    """
    markers = scan_for_injection_markers(text)
    if strict and markers:
        pattern_names = sorted({m["pattern"] for m in markers})
        raise AuthorityViolationError(
            "retrieval content from source=" + str(source_id) +
            " kind=" + str(kind) + " contains injection patterns: " +
            ", ".join(pattern_names))
    wrapped = wrap_as_data(text, source_id=source_id, kind=kind, max_chars=max_chars)
    return {"wrapped": wrapped, "injection_markers": markers,
            "policy": "strict" if strict else "lenient",
            "source_id": str(source_id), "kind": str(kind)}
