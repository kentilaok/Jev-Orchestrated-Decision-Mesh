# Handoff — P0-03 closure: requirement-by-requirement evidence (18 October 2026)

**Gate:** P0-03 (live provider execution and accounting), from `docs/PRODUCTION-REQUIREMENTS-HANDOFF-2026-10-08.md` §3.
**State:** slices 3a–3c merged to `main` (`e6cc8a5`). Launch providers in scope: Jev via OpenRouter, worker via Claude Code CLI. Codex is out of scope for P0-03 V1.
**Evidence:** `research/p0-03-smoke/` (six run folders); handoffs `HANDOFF-P0-03-SLICE-3A-AUDIT.md`, `-3B-SMOKE.md`, `-3C-LIVE.md`. The passing live run is `20261017T062818Z-smoke`.

## Requirements

| # | Requirement | Evidence | Status |
|---|---|---|---|
| 1 | Billing mode, live model ID, effort support, frozen route catalogue | Preflight: Claude `auth_method: claude.ai`, `billing: subscription`, `subscription_type: pro`; Jev pinned `typesafe/jev-1.13`, served `typesafe/jev-1.13-20260917` on every call; Claude served IDs from `modelUsage` (`reported_match` on every worker). Claude Code has no non-interactive catalogue, so route coverage is `unverified`, and the CLI does not report effort (`actual_effort: null`). | **Met, with stated limits** |
| 2 | Real Jev pre-dispatch decision, tool-free child, return-to-Jev arbitration, release audit | Run 3: `authorize_unit` → Claude worker (`--tools ""`, `--strict-mcp-config`, no session persistence) → `after_worker` for all five units; broker order, native and permit audits valid. | **Met** |
| 3 | Request/response IDs, journal/permit hashes, source binding, usage, billing channel, rejection evidence, exit status | Jev OpenRouter request IDs (13–14 per run), Claude `session_id` per call, SHA-256 of `result.json` / `journal.jsonl` / `permits.jsonl` / `usage.jsonl`, `source_hashes`, per-call usage, billing channel in preflight, rejection evidence in the negatives and runs 1–2, broker exit codes in each `smoke-report.json`. | **Met** |
| 4 | Zero unauthorized calls, single-use permits, no missing Jev decision, no unvalidated release | `scripts/p0_03_audit.py` re-audit of every committed run is clean: each successful call bound to one consumed `frontier.run` permit, no reuse, ledger chain valid, order audit clean, no release without `complete` and clean audits. | **Met** |
| 5 | Provider unavailable, wrong model, schema-invalid, low-budget, cancelled; no silent fallback | Live: provider unavailable and wrong model refused before launch; low budget refused by the gateway before any HTTP request ($0). Offline only: schema-invalid response (`test_codex_cli_adapter.test_schema_json_and_usage_fail_closed`, `test_native_transition_broker.test_mismatched_return_is_counted_as_failed_billed_call`) and cancellation (`test_frontier_permits.test_cancel_stops_an_in_flight_run`). No fallback model in any path. | **Partly live** — see gaps |
| 6 | All model work accounted; unreported usage `unknown`, never zero | Jev and Claude usage reported on every call; unknown-usage handling enforced by the broker and checked by the auditor (`unknown_usage_summed_as_known`). The interactive primary host is not offered as a route in this test. | **Met** |

**Pass condition:** "signed-off live run and negative runs are auditable, repeatable and bounded by approved spending caps."

- Auditable: yes; every committed run re-audits clean offline and its hashes match its report.
- Bounded: yes; $1 caps on both sides, never approached (three paid runs: Jev $0.0057, Claude $0.855 API-equivalent in total).
- Repeatable: the runner and caps are scripted (`python scripts/p0_03_smoke.py --live`). One passing run is recorded; repeat rates belong to P0-07.
- Signed off: **pending Ken.**

## Gaps carried forward

1. **Schema-invalid and cancelled are offline-only.** A real model cannot be made to return a schema-invalid artifact on demand, and the broker CLI has no external cancel trigger (cancel exists at the provider level). Closing these live needs either a stub worker executable behind a live Jev call or a broker cancel hook; neither is required for the other gates.
2. **Hard kill mid-call** (process terminated while a worker runs) would leave a consumed permit without a receipt; the auditor flags this (`consumed_without_receipt`). Not exercised live.
3. **CI (P0-01)** has not run green for these commits; the last checks were blocked at the account level.

## Decision

- `scope`: P0-03.
- `decision`: **PASS for execution, accounting and caps; ready for Ken's sign-off**, with the two offline-only negatives recorded as gaps.

*CIDM architecture and research by Ken Caber (Kenneth Vic A. Caber).*
