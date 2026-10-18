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
| `scripts/operator_console.py` | New `max_cumulative_usd` field in `DEFAULT_CONFIG`, validation branch in `_merge_config`, `broker_argv` emission; `start_resume_job` validates the checkpoint policy and resumes with its cap. |
| `scripts/native_transition_broker.py` | `_parse_positive_usd` argparse type, new `--max-cumulative-usd` CLI arg, injection into `settings` before `RunConfig.from_dict`. |
| `console/index.html` | Number input, label and helper paragraph; one line in `loadSecurity`; cap parsing and validation in `saveSecurity`. |
| `tests/test_console_max_cumulative_usd.py` | New, 26 tests: Console config merge (default/accept/reject), `broker_argv` emission, broker CLI parse (accept + reject), end-to-end precedence driven through the real `main()` up to `PermitAuthority` (CLI wins over file), Console resume keeps the checkpoint's cap and rejects a malformed checkpoint policy before creating the resume folder, Console UI static markers + a Save-handler guard against bad input clearing the cap + regression guard on earlier P0-05/P0-06 Security fields. |
| `docs/HANDOFF-CONSOLE-MAX-CUMULATIVE-USD.md` | This handoff. |

## 3. Verification

| Check | Result |
|---|---|
| Slice tests | 26/26 pass (after QA round 2) |
| Full offline suite | 654/654 pass, 1 opt-in Docker skip + 4 POSIX-only skips (Windows host) |
| Regressions on 628-test post-PR#24 baseline | 0 |
| `python -m compileall -q scripts tests` | pass |
| Live model calls | None |

## 4. Design calls honoured

- **CLI flag over config-file wiring.** I had framed slice 2d as "needs `broker_argv --config` wiring" in earlier handoffs, but a dedicated flag matches the existing `--content-policy` / `--require-action-approval` / `--secret-env-names` pattern and is a smaller surface. Future RunConfig knobs can follow the same path or move to a shared `--config` file when enough of them stack up.
- **CLI wins over `--config` file.** `EndToEndBrokerOverrideTests` drives the real `main()` and asserts the kwarg `PermitAuthority` receives; a mutation that deletes the override fails it. This matches the usual UNIX convention (explicit flag beats implicit file).
- **Bool guard.** JSON `true` would otherwise sneak through `isinstance(value, (int, float))` because `bool` subclasses `int` in Python. Explicit `isinstance(value, bool)` early-reject.
- **UI: number input, blank means null.** Consistent with the number-input convention; the Save handler parses blank → `null` so the operator can clear a cap by emptying the field.
- **Help paragraph names the behaviour.** The operator reads that "stop after the one that busted" is intentional and that Codex contributes `None` to cumulative tracking today. No surprises.

## 4a. QA round 1 (commit 6e63b8d: FAIL) and fixes

1. **Bad input silently cleared the cap.** A number input reports unparseable text as `""`, which the Save handler sent as `null`. Fix: reject `validity.badInput` and non-positive/non-finite values in the browser before POST.
2. **Changing the cap broke Console resume.** The cap is part of `policy_hash`, so resuming with the Console's current cap raised `resume_config_mismatch`. Fix: `start_resume_job` passes the cap stored in `checkpoint.json` `policy.max_cumulative_usd`. Pre-2b checkpoints cannot be resumed at all: slice 2b added the field to `RunConfig.to_dict()`, which changed `policy_hash`. That predates this slice.
3. **End-to-end tests did not test `main()`.** They copied the override logic. Replaced with tests that drive `main()`; mutation-checked (deleting the override or the resume fix fails 5 tests).
4. Help text now says the cap is per launch (each resume starts a fresh ledger at $0), that Claude cost is an API-equivalent estimate, and that Jev/OpenRouter credits are bounded separately.

QA round 2 (commit 342b850: PASS WITH NITS). Fixed: static regression test for the Save-handler guard (mutation-checked: dropping either check fails it); `_drive` also patches `frontier_providers.build_provider` and `Gateway` to raise, so a refactor cannot turn the offline test into a live call; `start_resume_job` rejects a non-dict bundle/policy or invalid cap with HTTP 400 before `mkdir` (no orphan resume folder).

QA round 3 (commit c517c16: PASS WITH NITS). Fixed in f229447: the malformed-checkpoint test now asserts no `-resume-` folder is created, and checkpoint cap errors are prefixed `checkpoint policy:`. Round-4 nits (assert the message prefix; this line) were folded into the P0-03 branch.

Not fixed (nits, logged): the Resume confirm does not show which cap will apply (help text says it); clearing a set cap to blank does not ask for confirmation; a 400-digit JSON integer returns HTTP 500 instead of 400 (nothing saved); a hand-edited invalid cap in the state file blocks the Console until fixed by hand; an int cap from a CLI `--config` file (`5`) hashes differently from the Console's float (`5.0`), so such a run cannot be resumed from the Console.

## 5. Open items

With this slice merged, **all script-side P0-06 bullets are closed and no UI carry-overs remain**. Remaining items are not slice-sized:

- **Operator work (not a slice):** dedicated OS account for the Jev operator role, as mentioned in the P0-06 handoff.
- **P0-03 prereq:** decide whether Codex should be priced from `RunConfig` ceilings so cumulative tracking stays honest when Codex is primary worker.
- **P0-07 (V1 gate):** benchmarks + acceptance report. Not a one-slice job; needs preregistered protocol + sample size + comparator (direct Claude/Codex agent) agreed with Ken before any paid run.

## 6. Decision

- `scope`: P0-06 slice 2d.
- `decision`: **PASS pending QA**; PR against `main` after QA.

*CIDM architecture and research by Ken Caber (Kenneth Vic A. Caber).*
