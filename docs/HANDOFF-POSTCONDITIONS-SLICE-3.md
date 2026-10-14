# Handoff — Task postconditions, slice 3 (14 October 2026)

**Branch:** `feature/task-postconditions`.
**Parent gate:** P0-02. Third of four slices.
**Evidence level:** offline tests only. No model calls.

## 1. What this slice delivers

A thin adapter module that integrates postconditions into the broker's acceptance step **without editing** `NativeTransitionBroker`. Callers that want postconditions pass the result through `apply_postconditions()` after `run()` returns.

- `scripts/postconditions_broker.py`:
  - `extract_candidate_fields(broker_candidate, declared_files)`: maps the broker's internal candidate shape (`text`, `data.unresolved`, …) to the generic shape (`output`, `files_changed`, `unresolved_stages`).
  - `apply_postconditions(result, broker_candidate, declared_files, workspace, checks)`: runs the checks via `postconditions.run_checks`, mutates `result` in place to add a `postconditions` entry (the serialised report), and demotes `result['status']` to `postconditions_failed` + clears `answer` **only** when the broker had reported `complete`. If the broker had already reported a different failure, that diagnosis is preserved and both failures are visible.
- `postconditions.run_checks` now duck-types evaluator return values so a check created from a differently-loaded `postconditions` module (common in test discovery via `importlib`) still interoperates.
- Rolled in two slice-2 QA nits: `XXX` marker is now case-insensitive (matches `TODO/FIXME/UNRESOLVED`), and the git-dependent files-changed tests gain `@skipUnless(shutil.which("git"))` for portability.

## 2. Code changes

| File | Change |
|---|---|
| `scripts/postconditions.py` | +4/-4 lines. `run_checks` drops the `isinstance` check in favour of duck-typing. |
| `scripts/postconditions_broker.py` | New, 55 lines. Adapter + integration function. |
| `scripts/postconditions_coding.py` | +4/-3 lines. `XXX` pattern case-insensitive; `sys.modules.get` pattern for the `postconditions` import so loader order is irrelevant. |
| `tests/test_postconditions_broker.py` | New, 160 lines. Nine tests across three classes: adapter extraction (3), result mutation (5), end-to-end pass-condition surface (1 — a schema-valid candidate with a concealed TODO is refused). |
| `tests/test_postconditions_coding.py` | +4 lines. `shutil.which("git")` skip guard on the files-changed class; add XXX cases to the marker-detection test. |

## 3. Verification

| Check | Result |
|---|---|
| Slice-3 tests | 9/9 pass |
| Full offline suite | 410/410 pass, 1 opt-in Docker skip |
| Regressions on 401-test post-slice-2 baseline | 0 |
| `python -m compileall -q scripts tests` | pass |
| Live model calls | None |

## 4. P0-02 pass condition — early signal

The pass-condition test `test_schema_valid_candidate_with_concealed_todo_is_refused` already satisfies the P0-02 shape layer: a broker candidate that is schema-valid, hash-correct, and would otherwise be released is **refused** when its `text` contains an undeclared `TODO`. The final adversarial corpus arrives in slice 4.

## 5. Open items for the next (final) slice

1. **Adversarial corpus of known-wrong candidates** (`tests/fixtures/postconditions/*.json`).
2. **`docs/POSTCONDITIONS.md`** operator doc: architecture, how to declare checks per task class, extension points, known limitations.
3. **Final QA + PR**. After slice 4 pushes, run the final branch-head review and open the PR against `main`.

## 6. Pass/hold decision for this slice

- `scope`: internal milestone, not a release
- `decision`: **PASS pending independent QA**. QA then slice 4 directly (standing autonomous cadence).

*CIDM architecture and research by Ken Caber (Kenneth Vic A. Caber).*
