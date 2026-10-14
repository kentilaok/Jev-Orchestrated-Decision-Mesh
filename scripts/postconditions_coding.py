#!/usr/bin/env python3
"""Concrete postcondition checks for coding tasks (P0-02 slice 2).

Each public function returns a `PostconditionCheck` ready to be fed into
`postconditions.run_checks()`. Checks are intentionally small, deterministic,
and side-effect free beyond the subprocess call they document.

Supported checks:
- build_exit_zero(cmd)             : build command returned 0.
- tests_exit_zero(cmd)             : test command returned 0.
- lint_clean(cmd)                  : lint command returned 0.
- files_changed_match_declared()   : git diff vs candidate['files_changed'].
- no_concealed_unresolved()        : output text has no undeclared markers
                                     (closes audit finding D-09 at this layer).

CIDM project policy: stdlib only.
"""
from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
from pathlib import Path

_PC_PATH = Path(__file__).resolve().parent / "postconditions.py"
_pc_spec = importlib.util.spec_from_file_location("postconditions", _PC_PATH)
_pc = importlib.util.module_from_spec(_pc_spec)
sys.modules.setdefault("postconditions", _pc)
_pc_spec.loader.exec_module(_pc)

PostconditionCheck = _pc.PostconditionCheck
PostconditionResult = _pc.PostconditionResult

_TAIL_CHARS = 400
_SUBPROCESS_TIMEOUT = 300  # seconds; evaluators that need more should wrap.
_UNRESOLVED_PATTERNS = (
    (re.compile(r"\bTODO\b", re.IGNORECASE), "TODO"),
    (re.compile(r"\bFIXME\b", re.IGNORECASE), "FIXME"),
    (re.compile(r"\bUNRESOLVED\b", re.IGNORECASE), "UNRESOLVED"),
    (re.compile(r"\bXXX\b"), "XXX"),
)


def _run_cmd(cmd: list, workspace: Path) -> tuple[int, str, str]:
    proc = subprocess.run(cmd, cwd=str(workspace), capture_output=True,
                          text=True, timeout=_SUBPROCESS_TIMEOUT)
    return proc.returncode, proc.stdout, proc.stderr


def _exit_zero_check(name: str, kind: str, cmd: list, *, pass_msg: str,
                     fail_msg: str) -> PostconditionCheck:
    def evaluate(candidate: dict, workspace: Path) -> PostconditionResult:
        rc, out, err = _run_cmd(cmd, workspace)
        evidence = {"cmd": list(cmd), "returncode": rc,
                    "stdout_tail": out[-_TAIL_CHARS:], "stderr_tail": err[-_TAIL_CHARS:]}
        if rc == 0:
            return PostconditionResult(status="pass", evidence=evidence,
                                       reasoning=pass_msg)
        return PostconditionResult(status="fail", evidence=evidence,
                                   reasoning=fail_msg + " (exit " + str(rc) + ")")
    return PostconditionCheck(name=name, kind=kind, required=True, evaluator=evaluate)


def build_exit_zero(cmd: list) -> PostconditionCheck:
    return _exit_zero_check("build_exit_zero", "build", cmd,
                            pass_msg="build command exited 0",
                            fail_msg="build command failed")


def tests_exit_zero(cmd: list) -> PostconditionCheck:
    return _exit_zero_check("tests_exit_zero", "tests", cmd,
                            pass_msg="test command exited 0",
                            fail_msg="test command failed")


def lint_clean(cmd: list) -> PostconditionCheck:
    return _exit_zero_check("lint_clean", "lint", cmd,
                            pass_msg="lint command exited 0",
                            fail_msg="lint reported issues")


def files_changed_match_declared() -> PostconditionCheck:
    """Compare `candidate['files_changed']` against the workspace's actual
    git-visible modifications. Both sides use POSIX-style paths.

    Fail cases:
    - a file is modified but not declared (undeclared)
    - a file is declared but not modified (missing)
    """
    def evaluate(candidate: dict, workspace: Path) -> PostconditionResult:
        declared = set(str(p).replace("\\", "/") for p in candidate.get("files_changed") or [])
        proc = subprocess.run(["git", "status", "--porcelain=1"], cwd=str(workspace),
                              capture_output=True, text=True, timeout=30)
        if proc.returncode != 0:
            return PostconditionResult(status="unresolved",
                                       evidence={"stderr_tail": proc.stderr[-_TAIL_CHARS:]},
                                       reasoning="git status failed; is this a repo?")
        actual = set()
        for line in proc.stdout.splitlines():
            if not line.strip():
                continue
            # porcelain=1 layout: XY<space>path (or XY<space>old -> new for renames)
            path = line[3:].strip()
            if " -> " in path:
                path = path.split(" -> ", 1)[1]
            actual.add(path.replace("\\", "/"))
        undeclared = sorted(actual - declared)
        missing = sorted(declared - actual)
        evidence = {"declared": sorted(declared), "actual": sorted(actual),
                    "undeclared": undeclared, "missing": missing}
        if not undeclared and not missing:
            return PostconditionResult(status="pass", evidence=evidence,
                                       reasoning="declared files match the workspace diff")
        reason = []
        if undeclared:
            reason.append("undeclared: " + ", ".join(undeclared))
        if missing:
            reason.append("missing: " + ", ".join(missing))
        return PostconditionResult(status="fail", evidence=evidence,
                                   reasoning="; ".join(reason))
    return PostconditionCheck(name="files_changed_match_declared", kind="files",
                              required=True, evaluator=evaluate)


def no_concealed_unresolved() -> PostconditionCheck:
    """Scan `candidate['output']` for unresolved-marker words. Any marker not
    reflected in `candidate['unresolved_stages']` is a concealed unresolved
    item (audit finding D-09)."""
    def evaluate(candidate: dict, workspace: Path) -> PostconditionResult:
        output = str(candidate.get("output") or "")
        declared_stages = [str(s).strip() for s in (candidate.get("unresolved_stages") or [])
                           if str(s).strip()]
        markers_found = []
        for pattern, label in _UNRESOLVED_PATTERNS:
            match = pattern.search(output)
            if match:
                # Context: 40 chars around the match for the evidence.
                start = max(0, match.start() - 20)
                end = min(len(output), match.end() + 20)
                markers_found.append(label + " @ ..." + output[start:end] + "...")
        evidence = {"markers_found": markers_found, "declared_stages": declared_stages}
        if not markers_found:
            return PostconditionResult(status="pass", evidence=evidence,
                                       reasoning="no unresolved markers in output")
        if declared_stages:
            # Any declared stage satisfies all markers for this slice. A tighter
            # pairing of marker-to-stage can land in a later slice if needed.
            return PostconditionResult(status="pass", evidence=evidence,
                                       reasoning="markers present but declared in unresolved_stages")
        return PostconditionResult(status="fail", evidence=evidence,
                                   reasoning="unresolved markers in output are not declared")
    return PostconditionCheck(name="no_concealed_unresolved", kind="unresolved",
                              required=True, evaluator=evaluate)
