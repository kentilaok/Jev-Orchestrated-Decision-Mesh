# Handoff — P0-03 slice 3c: first live smoke run and live negatives (17 October 2026)

**Branch:** `feature/p0-03-live-smoke`, stacked on PR #25. Retarget to `main` after #25 merges.
**Parent gate:** P0-03 (live provider execution and accounting).
**Evidence level:** live. Jev `typesafe/jev-1.13` via OpenRouter; worker via Claude Code 2.1.296 (native `claude.exe`), signed in with a claude.ai Pro subscription.
**Evidence:** `research/p0-03-smoke/` (four run folders, produced by `scripts/p0_03_smoke.py`; no secrets found by a key/token scan).

## 1. Results

| Run (UTC stamp) | Expectation | Outcome | Spend |
|---|---|---|---|
| `20261016T194815Z-provider-unavailable` | refused before launch | refused by `claude_cli`; broker never launched | $0 |
| `20261016T194815Z-wrong-model` | refused before launch | refused by `models_pinned`; broker never launched | $0 |
| `20261016T194816Z-low-budget` | broker runs, no paid call | gateway refused the first Jev call at admission; 0 Jev requests, 0 permits; audit clean | $0 |
| `20261016T194827Z-smoke` | complete answer, clean audit | **halted, not complete**; audit clean | Jev $0.00217; Claude $0.271 API-equivalent (subscription usage, not billed) |

All runs used policy hash `9fc5fa28de04579c…` (`max_usd = 1.0`, `max_cumulative_usd = 1.0`, `max_jev_tokens = 50000`).

## 2. The live run (2 min 6 s, 19:48:27–19:50:34 UTC)

What worked (P0-03 requirements on execution and accounting):

- 13 Jev calls, every one returned `typesafe/jev-1.13-20260917`, each with an OpenRouter request ID and a reported cost; `result.json` matches the gateway's `usage.jsonl`.
- 5 Claude worker calls (1 Opus low, 4 Sonnet medium). Each was bound to its own consumed `frontier.run` permit with a costed receipt, served-model identity `reported_match`, and a `session_id`.
- Token accounting complete: frontier 61,148 input / 8,875 output, no unknown usage.
- Both caps held with a wide margin; the cumulative ledger never came near $1.
- 29 Claude Code session variables from the launching desktop session were removed before the broker started (names in `smoke-report.json`).
- Offline re-audit of the committed copy: no issues; hashes match the run's report.

Why it did not complete:

- Units `input` and `hidden1` forwarded. On unit `hidden2`, Jev chose `repair` on all four worker returns although **every hard check passed and no failed criteria were given**. The instructions say to forward when all executable checks pass.
- After two repair limits and two recovery replans, the 13th Jev call took cumulative Jev tokens to 52,642. That exceeded `max_jev_tokens` (50,000), so the gateway rejected the call (`jev_token_budget_exceeded`) and the network halted with `MeshError: jev_call_failed`. The token budget behaved as designed. The cost of that last call ($0.000204) is still counted.

## 3. Decision

- `scope`: P0-03 slice 3c.
- **Execution, accounting and caps: PASS** on live evidence (permits bound, identities reported, costs reconciled, caps enforced, negatives refused with zero spend).
- **End-to-end completion: FAIL** for this run, because of Jev's repair loop on a unit that passed every hard check.
- No re-run was attempted; the evidence is recorded as it happened.

## 4. Open items (need Ken's decision)

1. Investigate Jev's `after_worker` choices on `hidden2`: compare the state and criteria Jev saw (`broker/call-5` … `call-12` request/response files) with the instruction to forward on passing checks. Candidates: tighter `after_worker` instructions, or a repair cap that forces `forward`/`stop` when hard checks pass and no criterion fails.
2. Decide whether `max_jev_tokens = 50000` is right for a five-unit recovery run (this run used about 4.4k tokens per Jev call).
3. Re-run the smoke run after (1), still capped at $1.
4. Merge PR #25, then retarget this branch to `main`.

*CIDM architecture and research by Ken Caber (Kenneth Vic A. Caber).*
