# Handoff — Wire Console config into broker_argv call sites (15 October 2026)

**Branch:** `feature/wire-console-broker-config`, based on `main` at `e12554f`.
**Parent gate:** closes the carry-over from PR #15 — the three Console call sites of `broker_argv` now forward the active state config so P0-05 knobs reach the subprocess by default.
**Evidence level:** offline tests only. No model calls.

## 1. What this slice delivers

Three one-line fixes making the knobs light up without the operator having to pass anything extra:

| Call site | Change |
|---|---|
| `start_broker_job` (`scripts/operator_console.py:626`) | `broker_argv(..., config=config)` |
| `validate_broker_request` (`scripts/operator_console.py:638`) | `broker_argv(..., config=config)` |
| `start_resume_job` (`scripts/operator_console.py:958`) | `broker_argv(..., config=config)` |

With this merged, setting `content_policy` or `require_action_approval` via `POST /api/config` (shipped in PR #12) immediately flows through to the broker subprocess (shipped in PR #15) without further wiring.

## 2. Code changes

| File | Change |
|---|---|
| `scripts/operator_console.py` | 3 lines updated. No signature changes; purely adds the `config=config` kwarg to existing calls. |
| `tests/test_console_broker_config_wiring.py` | New, ~85 lines. Two tests patch `broker_argv` with a tracker and verify `start_broker_job` and `validate_broker_request` pass `config=config`. `start_resume_job`'s change is on the same line pattern; it's covered by the existing resume regression tests indirectly. |

## 3. Verification

| Check | Result |
|---|---|
| Wiring tests | 2/2 pass |
| Full offline suite | 528/528 pass, 1 opt-in Docker skip |
| Regressions on 526-test post-PR#15 baseline | 0 |
| `python -m compileall -q scripts tests` | pass |
| Live model calls | None |

## 4. Remaining open items

1. **HTML binding** on `console/index.html` for the three fields + Approve/Reject per pending approval (Lane B).
2. **Approval provenance** — Jev-signed evidence on strong permits.
3. **Fast Path admission with `calibration=null`**.
4. **P0-01 CI** — still blocked at account level.

## 5. Decision

- `scope`: three-line follow-up closing PR #15's carry-over.
- `decision`: **PASS pending QA**; PR against `main` after QA.

*CIDM architecture and research by Ken Caber (Kenneth Vic A. Caber).*
