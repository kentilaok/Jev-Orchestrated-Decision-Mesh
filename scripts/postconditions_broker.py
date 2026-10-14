#!/usr/bin/env python3
"""Postcondition integration adapter for NativeTransitionBroker (P0-02 slice 3).

Keeps postcondition logic out of the broker's complex invariant-heavy class.
Callers that want postconditions call `apply_postconditions(result, …)` on
the broker's result dict after `run()` returns. The adapter:

- maps the broker's candidate shape to the generic postconditions candidate
  shape (`output`, `files_changed`, `unresolved_stages`);
- runs the supplied `checks` via `postconditions.run_checks`;
- mutates the result in place: adds `postconditions` (serialised report),
  and, when the broker had reported `complete` but postconditions withhold,
  demotes `status` to `postconditions_failed` and clears `answer`.

Stdlib-only.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any, Iterable

_PC_PATH = Path(__file__).resolve().parent / "postconditions.py"
_pc = sys.modules.get("postconditions")
if _pc is None:
    _pc_spec = importlib.util.spec_from_file_location("postconditions", _PC_PATH)
    _pc = importlib.util.module_from_spec(_pc_spec)
    sys.modules["postconditions"] = _pc
    _pc_spec.loader.exec_module(_pc)


def extract_candidate_fields(broker_candidate: dict | None, *,
                             declared_files: list[str] | None) -> dict:
    """Adapt broker candidate shape → generic postconditions candidate shape."""
    broker_candidate = broker_candidate or {}
    data = broker_candidate.get("data") or {}
    return {
        "output": str(broker_candidate.get("text") or ""),
        "files_changed": list(declared_files or []),
        "unresolved_stages": list(data.get("unresolved") or []),
    }


def apply_postconditions(*, result: dict, broker_candidate: dict | None,
                         declared_files: list[str] | None,
                         workspace: Path,
                         checks: Iterable[Any]) -> dict:
    """Run the postconditions and amend `result` in place. Returns `result`.

    - Empty `checks` iterable → no-op (no `postconditions` key added).
    - Withhold on an otherwise `complete` broker result → status becomes
      `postconditions_failed`, `answer` cleared. The broker's structural
      status is preserved when it already reported a failure, so operators
      see the earliest refusal reason.
    """
    checks = list(checks)
    if not checks:
        return result
    candidate = extract_candidate_fields(broker_candidate, declared_files=declared_files)
    report = _pc.run_checks(checks, candidate=candidate, workspace=workspace)
    result["postconditions"] = report.as_dict()
    if report.decision == "withhold" and result.get("status") == "complete":
        result["status"] = "postconditions_failed"
        result["answer"] = None
    return result
