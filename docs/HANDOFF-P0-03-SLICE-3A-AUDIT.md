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
| `tests/test_p0_03_audit.py` | 35 tests: clean permit-backed recovery, fused and short-route runs built from fakes; legitimate shapes that must pass (refused-at-issue call, retrieval permit on the same ledger, resumed run, route-preflight failure, run stopping after crossing the cap); one tamper per check; CLI exit codes. |
| `tests/test_console_max_cumulative_usd.py`, `docs/HANDOFF-CONSOLE-MAX-CUMULATIVE-USD.md` | PR #25 round-4 nits: assert the `checkpoint` error prefix; log QA round 3. |

## 4. Verification

| Check | Result |
|---|---|
| Slice tests | 35/35 pass; 12 auditor mutants all caught |
| Full offline suite | 691 pass, 1 opt-in Docker skip + 4 POSIX-only skips |
| `compileall`, `git diff --check` | pass |
| Live model calls | none |

## 4a. QA round 1 (commit 9331e78: FAIL) and fixes

1. **HIGH, pre-existing (PR #20):** real Claude runs never put a cost on permit receipts. `ClaudeCliAdapter` reports `api_equivalent_cost_usd` at the top level of its response; `_BoundedProvider` looked only inside `usage`, so `max_cumulative_usd` limited nothing. Fixed in `8251035` (`_cost_from_response`), with tests through the real `_parse`. The auditor now flags `cumulative_cap_unverifiable` when a cap is set and a frontier receipt has no cost. A call refused at permit issue is now `not_launched`, not `unknown_child_ran`.
2. Short-route runs crashed the auditor; now checked for the single pinned worker and passing hard checks.
3. Fused runs were checked with the wrong order audit; now chosen by `protocol_version`.
4. Resumed runs were falsely flagged; calls carried from a checkpoint are reported (`resumed_calls_carried`) and not bound to this ledger; the journal must be a tail of the events.
5. Retrieval/MCP permits on the same ledger were counted as frontier permits; only `frontier.run` counts, and `permit_id` reuse across calls is flagged.
6. The auditor's config was never checked; broker `main()` now writes `config_policy_hash` into `result.json` (also on route-preflight failure), and the auditor flags `config_mismatch` / `config_policy_hash_missing`. New `--max-cumulative-usd` flag mirrors the broker's.
7. Weak tests: added the missing cases; mutation run catches all 12 mutants, including the `>=` cap boundary.
8-12. Route-preflight results no longer flagged; Jev overspend is checked on known costs even when another event is unknown; journal is compared with the result's events and known token totals are recomputed; the order audit also runs on unreleased broad-route runs; a missing `result.json` is reported (`result_missing`) and the ledger is still audited.

## 4b. QA round 2 (17 October 2026) and fixes

1. **MED:** the cap replay summed only `frontier.run` receipts, while `PermitAuthority` sums every costed receipt and refuses every capability. A costed retrieval/MCP receipt could push the ledger past the cap unseen. The auditor now mirrors the authority; only frontier receipts must carry a cost. Non-finite costs are ignored as the authority ignores them on replay.
2. **MED:** a corrupt `result.json` or `journal.jsonl` raised a traceback instead of a report. Now reported as `result_unreadable:*` / `journal_unreadable:*`, and the ledger is still audited.
3. **LOW:** the CLI silently overrode `worker_family` from `--config`; it now refuses a host/family mismatch exactly as the broker does.
4. Closed a known limit: Jev events in `result.json` are cross-checked against the gateway's `usage.jsonl` (id, status, request id, cost): `jev_usage_log_missing` / `jev_usage_log_mismatch`. Jev request IDs and the `usage.jsonl` SHA-256 are in the evidence.
5. Checked and not a defect: Claude adapter refusals before launch are recorded `not_launched` (`ClaudeCliError` inherits `ran = False`).

Tests: 44 in this file (9 new); the new cap test fails when only frontier receipts are summed.

## 5. Known limits

- **Trust model:** the auditor catches broker bugs and accidental corruption, not deliberate rewriting. The ledger chain can be rebuilt and `result.json` is read as written; the recorded hashes mean something only once committed with the evidence bundle in slice 3c.
- Billing channel (subscription vs API key) is recorded by the slice 3b smoke runner's preflight, not by the auditor.
- "Zero unauthorized calls" is proven by permit binding for successful calls; a failed call that launched has no `permit_id` on its record, so it is covered only by the count check.
- Runs saved before this slice have no `permit_id` or `config_policy_hash` and will be flagged; the auditor targets new P0-03 runs.
- Codex runs are not exercised (Codex is out of scope for P0-03 V1).
- The auditor checks structure and accounting, not answer quality.

## 6. Decision

- `scope`: P0-03 slice 3a.
- `decision`: **PASS** after QA round 2 fixes (full offline suite 711 pass, 5 skips).

*CIDM architecture and research by Ken Caber (Kenneth Vic A. Caber).*
