# Handoff — OTLP ordinal-span caveat assertion (15 October 2026)

**Branch:** `feature/otlp-ordinal-caveat`, based on `main` at `570129b`.
**Parent gate:** P0-06 slice 5 — "OTLP exporter may report **ordinal** event timing rather than measured latency; do not use ordinal spans for p95 response-time claims" from the production handoff.
**Evidence level:** offline tests only. No model calls.

## 1. What this slice delivers

The OTLP exporter in `scripts/telemetry.py` has always attached a `cidm.timing="ordinal_not_wallclock"` attribute to every span (because journal events carry no wall-clock timestamps — audit defect D-05). The caveat is what tells a downstream Phoenix consumer "don't treat this span's duration as a real p95 input." But the old code embedded the key/value as literals and only one test verified it on the root span; nothing stopped a future dev from adding a new span type that forgot the caveat.

This slice makes the caveat undroppable:

- **`ORDINAL_TIMING_KEY = "cidm.timing"`** and **`ORDINAL_TIMING_VALUE = "ordinal_not_wallclock"`** are module-level constants.
- **`_assert_ordinal_caveat(spans)`** iterates every span's attribute list, extracts the `cidm.timing` entry's `stringValue`, and raises `RuntimeError("ordinal_caveat_missing:<span_name>")` if any span lacks the exact sentinel.
- **`to_otlp()`** calls the guard just before returning. Any future span type that forgets the caveat makes `to_otlp` fail loudly instead of silently producing data a Phoenix consumer could misread as measured latency.

The guard is a read-only scan over the already-built span list. No span mutation; no change to emitted output.

## 2. Code changes

| File | Change |
|---|---|
| `scripts/telemetry.py` | +22 lines. Module constants `ORDINAL_TIMING_KEY` / `ORDINAL_TIMING_VALUE`; `_assert_ordinal_caveat` function; `common` dict rebuilt from the constants; `_assert_ordinal_caveat(spans)` called at the end of `to_otlp` before `return`. |
| `tests/test_telemetry_ordinal_caveat.py` | New, 8 tests across three classes. Guard: rejects missing / wrong-value, accepts correctly-tagged. Full-span coverage: every emitted span (root, jev entries, decisions, worker/checker, units) carries the exact sentinel. Integration: a monkeypatched `_attrs` that strips the caveat from the first emitted span triggers `RuntimeError` from `to_otlp` itself. Backward-compat guard against the pre-existing root-span assertion. |
| `docs/HANDOFF-OTLP-ORDINAL-CAVEAT.md` | This handoff. |

## 3. Verification

| Check | Result |
|---|---|
| Slice tests | 8/8 pass |
| Full offline suite | 613/613 pass on re-run, 1 opt-in Docker skip + 3 POSIX-only skips (Windows host) + 1 pre-existing intermittent HTTP flake unrelated to this slice |
| Regressions on 605-test post-PR#22 baseline | 0 |
| `python -m compileall -q scripts tests` | pass |
| Live model calls | None |

## 4. Design calls honoured

- **Pure read-only guard.** `_assert_ordinal_caveat` scans; it never adds the caveat for you. If a future dev forgets `**common`, the guard raises — the fix is to add the caveat at emission, not to let the guard back-fill it.
- **Explicit `RuntimeError`, not `assert`.** `assert` is removed with `python -O`; a `RuntimeError` is unconditional, including in optimised builds.
- **No change to emitted OTLP JSON.** The constants hold the exact same key/value as before; the on-wire format is byte-identical to pre-slice when every span is correctly tagged.
- **Integration test mutates the producer only.** Patching the module constant would nullify the test (producer and verifier both read the same symbol); instead the integration test monkeypatches `_attrs` so the first span's attribute list drops the key, which is a producer-only mutation that still lets the guard fire.
- **No change to `post_otlp` or the CLI.** This slice touches the pure-function `to_otlp` only.

## 5. Open items (P0-06 next slices)

- **Slice 2d:** Operator Console UI for `max_cumulative_usd` — still blocked on threading a Console-settable `RunConfig` override into `broker_argv --config`.
- **Slice 4:** retention / backup playbook + restore drill.
- **P0-06 close-out note:** this slice closes the final production-handoff bullet listed under P0-06 "OTLP exporter may report ordinal event timing". The remaining P0-06 bullet (dedicated OS account) is operator work outside script scope. P0-07 (benchmarks + acceptance) remains the big open gate.

## 6. Decision

- `scope`: P0-06 slice 5.
- `decision`: **PASS pending QA**; PR against `main` after QA.

*CIDM architecture and research by Ken Caber (Kenneth Vic A. Caber).*
