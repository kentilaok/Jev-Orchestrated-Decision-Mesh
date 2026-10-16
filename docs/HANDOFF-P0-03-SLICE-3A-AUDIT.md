# Handoff — P0-03 slice 3a: offline re-audit of a live run folder (16 October 2026)

**Branch:** `feature/p0-03-live-smoke`, stacked on PR #25 head `f229447` (not yet merged). Retarget to `main` after #25 merges.
**Parent gate:** P0-03 (live provider execution and accounting), requirements 3 and 4.
**Evidence level:** offline tests only. No model calls.

## 1. Stage plan (agreed decisions, 2026-10-16)

Jev via OpenRouter, worker via Claude CLI only (Codex skipped). First live run capped at $1 on the Jev side (`RunConfig.max_usd=1.0`) and `max_cumulative_usd=1.0` on the Claude permit ledger.

| Slice | Content | Spend |
|---|---|---|
| **3a (this)** | `scripts/p0_03_audit.py`: re-audit a saved broker `--out` folder | none |
| 3b | Capped smoke runner with `--dry-run`; negative runs that stop before a paid call (wrong model, low budget, provider unavailable); offline tests with a fake `claude` executable | none |
| 3c | Real smoke run plus live negative runs, evidence committed under `research/p0-03-smoke/` | paid, **ask Ken first** |

## 2. What this slice delivers

`python scripts/p0_03_audit.py RUN_DIR [--config FILE] [--host claude]` prints a JSON report and exits 0 (no issues) or 1. It recomputes, without trusting the run's own audit fields:

- permit ledger hash chain and `audit_permit_ledger` (issued once, consumed once, receipted, basis in journal);
- every successful frontier call names a consumed `permit_id`; consumed permits never exceed call records. A call refused at permit issue (cap reached) is recorded as failed with no consumption, so it is not flagged;
- a released answer requires `status == complete`, a clean Jev order audit and a clean native call audit;
- Jev cost recomputed from `jev_provider_events`, must match `jev_api_cost_usd` and stay within `max_usd`; unknown Jev usage must leave the cost `null`;
- no permit issued once receipted cost reached `max_cumulative_usd`;
- frontier calls with unknown usage are counted as unknown and never summed.

Evidence collected: status, task hash, source hashes, policy hash, SHA-256 of `result.json` / `journal.jsonl` / `permits.jsonl`, per-call requested and served model, identity verification, `session_id`, permits consumed, route coverage status.

## 3. Code changes

| File | Change |
|---|---|
| `scripts/p0_03_audit.py` | New auditor (stdlib plus existing CIDM modules). |
| `scripts/native_transition_broker.py` | Successful call records now keep `session_id` (P0-03 req. 3: provider IDs when available) and `permit_id` (binds each call to its permit). |
| `tests/test_p0_03_audit.py` | 12 tests: one clean permit-backed recovery run built from fakes, then one tamper per check, plus CLI exit codes. |
| `tests/test_console_max_cumulative_usd.py`, `docs/HANDOFF-CONSOLE-MAX-CUMULATIVE-USD.md` | PR #25 round-4 nits: assert the `checkpoint` error prefix; log QA round 3. |

## 4. Verification

| Check | Result |
|---|---|
| Slice tests | 12/12 pass |
| Full offline suite | 666 pass, 1 opt-in Docker skip + 4 POSIX-only skips |
| `compileall`, `git diff --check` | pass |
| Live model calls | none |

## 5. Known limits

- Runs saved before this slice have no `permit_id` on call records and will fail the binding check; the auditor targets new P0-03 runs.
- Codex runs are not exercised (Codex is out of scope for P0-03 V1).
- The auditor checks structure and accounting, not answer quality.

## 6. Decision

- `scope`: P0-03 slice 3a.
- `decision`: **PASS pending QA**.

*CIDM architecture and research by Ken Caber (Kenneth Vic A. Caber).*
