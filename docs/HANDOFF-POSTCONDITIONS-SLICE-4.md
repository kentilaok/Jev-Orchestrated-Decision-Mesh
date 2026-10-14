# Handoff — Task postconditions, slice 4 (14 October 2026)

**Branch:** `feature/task-postconditions`. Final slice.
**Parent gate:** P0-02 — closes at the shape layer with a known-wrong-but-schema-valid candidate refused on data (not just a synthetic in-test check).
**Evidence level:** offline tests only. No model calls.

## 1. What this slice delivers

The P0-02 adversarial corpus and the operator-facing documentation.

- `tests/fixtures/postconditions/`: four JSON fixtures of broker-shaped candidates — one control (release), two refused for concealed markers, one accepted for transparent declaration. Fixture schema is self-contained: `broker_candidate`, `declared_files`, `checks`, `expected_decision`, `expected_failed`.
- `tests/test_postconditions_adversarial.py`: iterates every fixture, runs it through the real `extract_candidate_fields` → `run_checks` → `apply_postconditions` chain, asserts decision + failed list; a second test proves the corpus itself always carries at least one release and one withhold case so a future contributor cannot accidentally reduce it to all-pass.
- `docs/POSTCONDITIONS.md`: operator-facing single document — architecture, protocol, concrete checks, candidate adapter, adversarial corpus table, known limitations.

## 2. Code changes

| File | Change |
|---|---|
| `tests/fixtures/postconditions/all_green.json` | New: control release case. |
| `tests/fixtures/postconditions/concealed_todo.json` | New: schema-valid, hidden TODO → withhold. |
| `tests/fixtures/postconditions/concealed_fixme.json` | New: FIXME variant. |
| `tests/fixtures/postconditions/declared_markers_pass.json` | New: markers + declared stages → release. |
| `tests/test_postconditions_adversarial.py` | New, ~85 lines. Two tests. |
| `docs/POSTCONDITIONS.md` | New operator doc. |

## 3. Verification

| Check | Result |
|---|---|
| Slice-4 tests | 2/2 pass (one is parameterised over all four fixtures) |
| Full offline suite | 412/412 pass, 1 opt-in Docker skip |
| Regressions on 410-test post-slice-3 baseline | 0 |
| `python -m compileall -q scripts tests` | pass |
| Live model calls | None |

## 4. P0-02 pass condition — closed

> **Pass condition** (production handoff §P0-02): a known-wrong yet perfectly schema-compliant candidate fails the production-specific release checks.

Proven by `concealed_todo.json` and `concealed_fixme.json`:

- Each candidate passes every structural check in `_validate_candidate` (shape, hashes, parent links, lengths, declared unresolved).
- Each candidate's `text` contains an unresolved marker not reflected in `data.unresolved`.
- `apply_postconditions` demotes `status` from `complete` to `postconditions_failed`, clears `answer`, and records the refusal in `result['postconditions']`.

Both D-08 (structural-only release checks) and D-09 (concealed unresolved items) are closed at the shape layer.

## 5. Carry-overs (deliberate, documented in `docs/POSTCONDITIONS.md` §7)

1. Marker-to-stage pairing is loose; one declared stage currently clears all markers.
2. Classifier is syntactic; semantic unresolved detection is future work.
3. Timeouts are hard-coded (300 s build/test/lint, 30 s git).
4. The adapter sits outside `NativeTransitionBroker.run`; callers invoke `apply_postconditions` on the result.
5. Stdlib only; no PyYAML, no Pytest, no new third-party deps.

## 6. Decision for this slice

- `scope`: closes P0-02 at the shape layer.
- `decision`: **PASS pending final branch-head QA**, after which the branch opens as a PR against `main`.

*CIDM architecture and research by Ken Caber (Kenneth Vic A. Caber).*
