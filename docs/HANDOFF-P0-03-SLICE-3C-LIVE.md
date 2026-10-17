# Handoff — P0-03 slice 3c: first live smoke run and live negatives (17 October 2026)

**Branch:** `feature/p0-03-live-smoke`, stacked on PR #25. Retarget to `main` after #25 merges.
**Parent gate:** P0-03 (live provider execution and accounting).
**Evidence level:** live. Jev `typesafe/jev-1.13` via OpenRouter; worker via Claude Code 2.1.296 (native `claude.exe`), signed in with a claude.ai Pro subscription.
**Evidence:** `research/p0-03-smoke/` (five run folders, produced by `scripts/p0_03_smoke.py`; no secrets found by a key/token scan).

## 1. Results

| Run (UTC stamp) | Expectation | Outcome | Spend |
|---|---|---|---|
| `20261016T194815Z-provider-unavailable` | refused before launch | refused by `claude_cli`; broker never launched | $0 |
| `20261016T194815Z-wrong-model` | refused before launch | refused by `models_pinned`; broker never launched | $0 |
| `20261016T194816Z-low-budget` | broker runs, no paid call | gateway refused the first Jev call at admission; 0 Jev requests, 0 permits; audit clean | $0 |
| `20261016T194827Z-smoke` (task `native-project`) | complete answer, clean audit | **halted, not complete**; audit clean | Jev $0.00217; Claude $0.271 API-equivalent (subscription usage, not billed) |
| `20261017T061846Z-smoke` (task `p0-03-smoke`) | complete answer, clean audit | **halted, not complete**; audit clean | Jev $0.00212; Claude $0.311 API-equivalent |

All runs used policy hash `9fc5fa28de04579c…` (`max_usd = 1.0`, `max_cumulative_usd = 1.0`, `max_jev_tokens = 50000`).

The second run used `examples/p0-03-smoke.request.json`: the synthetic production-records task of the earlier GPT-6 live runs as a native request with no outstanding stages (the first run's task carries two stages its evidence cannot settle). It ran 14 Jev calls and 6 Claude workers (Sonnet low ×2, Opus low ×4) in 1 min 35 s, accepted `input`, `hidden1` and `hidden2`, and halted on `hidden3`. Its last Jev call chose `forward` (p 0.71) but took Jev tokens to 51,504, so the gateway rejected it.

## 2. The first live run (2 min 6 s, 19:48:27–19:50:34 UTC)

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

## 2b. Root cause (both runs)

1. **Claude workers read the artifact contract differently from GPT-6.** The worker prompt says "preserve predecessor hashes, and disclose unresolved issues" and shows `accepted_parent` (whose `data.parent_hashes` are *its* predecessors) next to `required_parent_hashes`. Claude repeatedly reports that difference as a "parent hash mismatch" and lists caveats and assumptions ("'Defect' is not defined…", "records are synthetic…") under `data.unresolved`. In the earlier GPT-6 runs every unit returned an empty `unresolved`.
2. **Jev repairs those candidates.** Every `repair` choice in run 2 followed a candidate whose `unresolved` named the hash "mismatch" or several caveats, with all hard checks passing and no failed criteria.
3. **The completion gate cannot pass with caveats.** On the `output` unit, `prior_units_resolved` requires every earlier unit's `unresolved` to be empty and `output_has_no_unresolved` requires the output's to be empty. With Claude's caveats in `unresolved`, the run could not release an answer even with a larger budget.
4. **Misleading check labels.** On intermediate units those two checks are not evaluated but are reported to Jev as `true`, next to a candidate that visibly lists unresolved items.
5. **Jev token budget.** Claude artifacts make Jev states about 1.8× larger than in the GPT-6 runs (about 4.3k against 2.4k tokens per call), so 50,000 tokens covers about 11 calls; any repair exhausts it.

## 3. Decision

- `scope`: P0-03 slice 3c.
- **Execution, accounting and caps: PASS** on live evidence (permits bound, identities reported, costs reconciled, caps enforced, negatives refused with zero spend).
- **End-to-end completion: FAIL** in both runs, for the reasons in §2b; not a broker or accounting defect.
- Two runs only; the evidence is recorded as it happened. No further paid runs until the contract decision below.

## 4. Open items (need Ken's decision; each changes the CIDM protocol or policy hash)

1. **Worker contract wording** (`produce()` prompt in `native_transition_broker.py`): state that `data.parent_hashes` must equal `required_parent_hashes` exactly and that `accepted_parent.data.parent_hashes` are not compared; and that `unresolved` is only for material open issues that block acceptance, with assumptions and caveats going in `claims`.
2. **Check labels for intermediate units:** report `prior_units_resolved` / `output_has_no_unresolved` as not applicable instead of `true`. Audits and Jev's view need to agree on the representation.
3. **`max_jev_tokens` for the Claude family** (for example 100,000; Jev cost stays near $0.0002 per call).
4. Then re-run the smoke run, still capped at $1.
5. Merge PR #25, then retarget this branch to `main`.

*CIDM architecture and research by Ken Caber (Kenneth Vic A. Caber).*
