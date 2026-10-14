# Handoff — Task postconditions, slice 1 (14 October 2026)

**Branch:** `feature/task-postconditions`, based on `main` at `abee82a`.
**Parent gate:** [P0-02 Task-specific correctness and evidence boundaries](PRODUCTION-REQUIREMENTS-HANDOFF-2026-10-08.md). First of four slices.
**Evidence level:** offline tests only. No model calls.

## 1. What this slice delivers

The data types and runner that P0-02 needs. A task class attaches `PostconditionCheck`s to a candidate; `run_checks` returns a `PostconditionReport` with a release/withhold decision the broker can act on. Later slices supply concrete checks for coding tasks and wire the runner into the broker's acceptance step.

- `PostconditionResult(status, evidence, reasoning, name)` — status ∈ {pass, fail, unresolved}; `__post_init__` enforces valid status and non-empty reasoning.
- `PostconditionCheck(name, kind, required, evaluator)` — frozen dataclass; evaluator is `(candidate, workspace) -> PostconditionResult`.
- `PostconditionReport(decision, results, failed, unresolved)` — JSON-serialisable via `as_dict()`.
- `run_checks(checks, *, candidate, workspace)` — runs every check, captures evaluator exceptions as `unresolved` with the exception text, and computes decision:
  - any required check with `status != 'pass'` → `withhold`
  - every required check `pass` → `release`
  - optional checks are recorded but never withhold release.

## 2. Code changes

| File | Change |
|---|---|
| `scripts/postconditions.py` | New, 120 lines. Stdlib-only, side-effect free unless an evaluator chooses to shell out. |
| `tests/test_postconditions.py` | New, 110 lines. Twelve tests across three classes: result shape (3), check shape (3), runner behaviour (6). |

## 3. Verification

| Check | Result |
|---|---|
| Slice-1 tests | 12/12 pass |
| Full offline suite | 387/387 pass, 1 opt-in Docker skip |
| Regressions on 375-test post-P0-04 baseline | 0 |
| `python -m compileall -q scripts tests` | pass |
| Live model calls | None |

## 4. Open items for the next slice

1. **Coding-class concrete checks (slice 2).** `scripts/postconditions_coding.py` with build-exit-code, test-exit-code, declared-vs-actual files-changed, lint-clean, and no-concealed-unresolved. Each gets a red test with a known-wrong candidate.
2. **Broker integration (slice 3).** Hook `run_checks()` into `NativeTransitionBroker._validate_candidate` (or a sibling step) so Jev's acceptance refuses release on withhold. Audit findings D-08 and D-09 close here.
3. **Adversarial corpus + docs (slice 4).** `tests/fixtures/postconditions/*.json` with known-wrong candidates; `docs/POSTCONDITIONS.md` operator doc; the P0-02 pass-condition test: a schema-compliant but wrong candidate fails release.

## 5. Pass/hold decision for this slice

- `scope`: internal milestone, not a release
- `decision`: **PASS pending independent QA**. Review runs after push.
- `next action`: QA review of slice 1 commit, then slice 2.

*CIDM architecture and research by Ken Caber (Kenneth Vic A. Caber).*
