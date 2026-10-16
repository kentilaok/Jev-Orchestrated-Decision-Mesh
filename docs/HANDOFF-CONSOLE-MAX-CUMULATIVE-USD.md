# Handoff — Console UI + CLI override for max_cumulative_usd (15 October 2026)

**Branch:** `feature/console-max-cumulative-usd`, based on `main` at `a16e300`.
**Parent gate:** P0-06 slice 2d (final cleanup) — close the Operator Console UI carry-over from slice 2b (PR #20) by threading a Console-settable `max_cumulative_usd` into the broker subprocess so a Console-launched job actually inherits the cap.
**Evidence level:** offline tests only. No model calls.

## 1. What this slice delivers

Slice 2b (PR #20) added `max_cumulative_usd` to `RunConfig` and taught `PermitAuthority` to refuse new permits past the cap. But Console-launched broker jobs never passed `--config` and never knew the cap existed. This slice closes that loop:

- **Operator Console** gains a `max_cumulative_usd: float | None` field in `DEFAULT_CONFIG` (default `None`). `_merge_config` validates: `None` disables, otherwise a positive finite number (rejects zero, negative, infinity, NaN, non-number, and `bool`).
- **`broker_argv`** emits `--max-cumulative-usd <value>` when the Console config carries a non-null cap; omits the flag at default.
- **`native_transition_broker.py` CLI** gets `--max-cumulative-usd` with a positive-finite-float `argparse.type`. The parsed value overrides any `max_cumulative_usd` present in the `--config` JSON before the `RunConfig.from_dict` build, so the CLI flag wins over file-set values.
- **`console/index.html`** gets a `<input type="number">` with id `maxCumulativeUsd` in the Security view. `loadSecurity()` reads `state.config.max_cumulative_usd` (empty when null); `saveSecurity()` parses the text (blank → `null`) and POSTs it under `max_cumulative_usd`. Help paragraph names the "stop after the one that busted" semantic and the Codex-cost-is-unknown caveat.

The broker-side RunConfig override order of precedence is explicit:

1. Default: `max_cumulative_usd=None` (no cap).
2. If `--config FILE` carries `max_cumulative_usd`, it is loaded into `settings`.
3. If `--max-cumulative-usd VALUE` is also on the CLI, it overrides the file value.

## 2. Code changes

| File | Change |
|---|---|
| `scripts/operator_console.py` | +12 lines. New `max_cumulative_usd` field in `DEFAULT_CONFIG`, validation branch in `_merge_config`, `broker_argv` emission. |
| `scripts/native_transition_broker.py` | +14 lines. `_parse_positive_usd` argparse type, new `--max-cumulative-usd` CLI arg, injection into `settings` before `RunConfig.from_dict`. |
| `console/index.html` | +4 lines of markup (number input, label, helper paragraph), +1 line in `loadSecurity`, +2 lines in `saveSecurity`. |
| `tests/test_console_max_cumulative_usd.py` | New, 19 tests across five classes: Console config merge (default/accept/reject), `broker_argv` emission, broker CLI parse (accept + reject), end-to-end RunConfig precedence (CLI wins over file), Console UI static markers + regression guard on earlier P0-05/P0-06 Security fields. |
| `docs/HANDOFF-CONSOLE-MAX-CUMULATIVE-USD.md` | This handoff. |

## 3. Verification

| Check | Result |
|---|---|
| Slice tests | 19/19 pass |
| Full offline suite | 647/647 pass, 1 opt-in Docker skip + 4 POSIX-only skips (Windows host) |
| Regressions on 628-test post-PR#24 baseline | 0 |
| `python -m compileall -q scripts tests` | pass |
| Live model calls | None |

## 4. Design calls honoured

- **CLI flag over config-file wiring.** I had framed slice 2d as "needs `broker_argv --config` wiring" in earlier handoffs, but a dedicated flag matches the existing `--content-policy` / `--require-action-approval` / `--secret-env-names` pattern and is a smaller surface. Future RunConfig knobs can follow the same path or move to a shared `--config` file when enough of them stack up.
- **CLI wins over `--config` file.** The handoff doc says so explicitly, and the test proves it. This matches the usual UNIX convention (explicit flag beats implicit file).
- **Bool guard.** JSON `true` would otherwise sneak through `isinstance(value, (int, float))` because `bool` subclasses `int` in Python. Explicit `isinstance(value, bool)` early-reject.
- **UI: number input, blank means null.** Consistent with the number-input convention; the Save handler parses blank → `null` so the operator can clear a cap by emptying the field.
- **Help paragraph names the behaviour.** The operator reads that "stop after the one that busted" is intentional and that Codex contributes `None` to cumulative tracking today. No surprises.

## 5. Open items

With this slice merged, **all script-side P0-06 bullets are closed and no UI carry-overs remain**. Remaining items are not slice-sized:

- **Operator work (not a slice):** dedicated OS account for the Jev operator role, as mentioned in the P0-06 handoff.
- **P0-03 prereq:** decide whether Codex should be priced from `RunConfig` ceilings so cumulative tracking stays honest when Codex is primary worker.
- **P0-07 (V1 gate):** benchmarks + acceptance report. Not a one-slice job; needs preregistered protocol + sample size + comparator (direct Claude/Codex agent) agreed with Ken before any paid run.

## 6. Decision

- `scope`: P0-06 slice 2d.
- `decision`: **PASS pending QA**; PR against `main` after QA.

*CIDM architecture and research by Ken Caber (Kenneth Vic A. Caber).*
