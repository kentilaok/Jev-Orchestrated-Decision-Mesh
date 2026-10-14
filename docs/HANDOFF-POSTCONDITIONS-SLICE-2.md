# Handoff — Task postconditions, slice 2 (14 October 2026)

**Branch:** `feature/task-postconditions`.
**Parent gate:** P0-02. Second of four slices.
**Evidence level:** offline tests only. No model calls.

## 1. What this slice delivers

Concrete postcondition checks for coding tasks. Each check is a factory that returns a `PostconditionCheck` ready for `postconditions.run_checks()`.

| Check | Semantics |
|---|---|
| `build_exit_zero(cmd)` | Runs the declared build command in the workspace; pass iff exit code 0. |
| `tests_exit_zero(cmd)` | Same shape, for tests. |
| `lint_clean(cmd)` | Same shape, for lint. |
| `files_changed_match_declared()` | `git status --porcelain=1` in the workspace; pass iff the declared `candidate['files_changed']` set equals the actual changed set. Fail with `undeclared` / `missing` lists in the evidence. Rename `A -> B` resolves to `B`. |
| `no_concealed_unresolved()` | Scans `candidate['output']` for `TODO`, `FIXME`, `UNRESOLVED`, `XXX`. Marker present but no `candidate['unresolved_stages']` declared → fail (closes audit D-09 at this layer). Markers declared → pass. No markers → pass. |

All checks are stdlib-only. Subprocess timeout is 300s; `git status` sub-call uses 30s. Evidence is JSON-serialisable: `cmd`, `returncode`, `stdout_tail`, `stderr_tail`, `declared`, `actual`, `undeclared`, `missing`, `markers_found`, `declared_stages`.

## 2. Code changes

| File | Change |
|---|---|
| `scripts/postconditions_coding.py` | New, 125 lines. Five factory functions + a shared `_exit_zero_check` helper. Loads `postconditions.py` via importlib and registers it in `sys.modules` so dataclass construction resolves correctly. |
| `tests/test_postconditions_coding.py` | New, 140 lines. Fourteen tests across five classes: build (3), tests (2), files-changed (3), lint (2), no-concealed-unresolved (4). Each failing case has a matching passing case. Files-changed tests init a real local git repo in a tempdir. |

## 3. Verification

| Check | Result |
|---|---|
| Slice-2 tests | 14/14 pass |
| Full offline suite | 401/401 pass, 1 opt-in Docker skip |
| Regressions on 387-test post-slice-1 baseline | 0 |
| `python -m compileall -q scripts` | pass |
| Live model calls | None |
| Subprocess calls | Only to `python -c 'pass'`, `python -c 'raise SystemExit(N)'`, `git init / add / commit / status`. No model/CLI calls. |

## 4. Open items for the next slice

1. **Broker integration (slice 3).** Call `run_checks(coding_checks, candidate=..., workspace=...)` inside `NativeTransitionBroker` (likely as a post-`_validate_candidate` step). On `withhold`, refuse Jev acceptance and persist the report alongside the run's journal. Closes audit D-08 at the broker layer.
2. **Marker-to-stage pairing (deferred, documented).** `no_concealed_unresolved` passes as soon as *any* declared stage is present when markers are found; tighter marker-to-stage pairing is possible later if the shape layer proves too loose. Not required for the P0-02 pass condition.
3. **Timeouts configurable.** 300s subprocess cap is generous but not operator-configurable. Add a `timeout` kwarg to the factories when the first real task class trips it.

## 5. Pass/hold decision for this slice

- `scope`: internal milestone, not a release
- `decision`: **PASS pending independent QA**. Review runs after push.
- `next action`: QA review, then slice 3 broker integration.

*CIDM architecture and research by Ken Caber (Kenneth Vic A. Caber).*
