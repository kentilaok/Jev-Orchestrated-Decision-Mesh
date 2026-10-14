#!/usr/bin/env python3
"""Task-specific postconditions for CIDM release gating (P0-02 slice 1).

The native broker's structural `_validate_candidate` checks shape, hashes,
parent links, and declared unresolved fields. It does not establish the
*truth* of the candidate's claims — a schema-valid, hash-correct candidate
can still be wrong, concealing an unresolved issue (audit D-09) or claiming
a test passed when it did not.

A postcondition is a small, deterministic evaluator a task class attaches to
a candidate. The runner collects every check's result and gives the broker a
single release/withhold decision. Later slices wire this into the broker's
acceptance step and ship concrete checks for coding tasks.

This module is stdlib-only and side-effect free (unless an evaluator chooses
to shell out). It raises `ValueError` on misuse.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable

VALID_STATUSES = ("pass", "fail", "unresolved")


@dataclass(frozen=True)
class PostconditionResult:
    """Outcome of a single check evaluator.

    status      — one of pass / fail / unresolved.
    evidence    — JSON-serialisable dict (exit codes, file lists, hashes).
    reasoning   — short human-readable sentence explaining the status.
    name        — set by the runner; evaluators don't need to supply it.
    """
    status: str
    evidence: dict[str, Any]
    reasoning: str
    name: str = ""

    def __post_init__(self):
        if self.status not in VALID_STATUSES:
            raise ValueError("status must be one of " + ", ".join(VALID_STATUSES))
        if not self.reasoning or not self.reasoning.strip():
            raise ValueError("reasoning is required")

    def as_dict(self) -> dict[str, Any]:
        return {"name": self.name, "status": self.status,
                "evidence": self.evidence, "reasoning": self.reasoning}


@dataclass(frozen=True)
class PostconditionCheck:
    """A declarable check a task class attaches to a candidate.

    name       — stable identifier (e.g. 'tests_green').
    kind       — coarse category ('build', 'tests', 'files', 'lint',
                 'unresolved', 'synthetic' for tests).
    required   — True → a non-pass withholds release. False → informational.
    evaluator  — callable(candidate: dict, workspace: Path) ->
                 PostconditionResult. The runner catches exceptions.
    """
    name: str
    kind: str
    required: bool
    evaluator: Callable[[dict, Path], PostconditionResult]

    def __post_init__(self):
        if not self.name or not self.name.strip():
            raise ValueError("name is required")
        if not self.kind or not self.kind.strip():
            raise ValueError("kind is required")
        if not callable(self.evaluator):
            raise ValueError("evaluator must be callable")


@dataclass(frozen=True)
class PostconditionReport:
    """Aggregated outcome of running a check list on one candidate."""
    decision: str  # 'release' or 'withhold'
    results: list[PostconditionResult]
    failed: list[str] = field(default_factory=list)
    unresolved: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {"decision": self.decision,
                "results": [r.as_dict() for r in self.results],
                "failed": list(self.failed),
                "unresolved": list(self.unresolved)}


def run_checks(checks: Iterable[PostconditionCheck], *, candidate: dict,
               workspace: Path) -> PostconditionReport:
    """Run every check and compute the release decision.

    A required check with status != 'pass' withholds release. An evaluator
    that raises is captured as 'unresolved' with the exception text in the
    reasoning. Optional checks never withhold release but their results are
    recorded for the audit.
    """
    results: list[PostconditionResult] = []
    failed: list[str] = []
    unresolved: list[str] = []
    for check in checks:
        try:
            raw = check.evaluator(candidate, workspace)
            if not isinstance(raw, PostconditionResult):
                raise TypeError("evaluator must return PostconditionResult, got "
                                + type(raw).__name__)
            result = PostconditionResult(status=raw.status, evidence=raw.evidence,
                                         reasoning=raw.reasoning, name=check.name)
        except Exception as exc:
            result = PostconditionResult(status="unresolved", evidence={"exception": type(exc).__name__},
                                         reasoning="evaluator raised: " + str(exc)[:300],
                                         name=check.name)
        results.append(result)
        if check.required:
            if result.status == "fail":
                failed.append(check.name)
            elif result.status == "unresolved":
                unresolved.append(check.name)
    decision = "release" if not failed and not unresolved else "withhold"
    return PostconditionReport(decision=decision, results=results,
                               failed=failed, unresolved=unresolved)
