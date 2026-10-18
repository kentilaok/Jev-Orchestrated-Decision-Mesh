# Handoff — P0-07 harness and pilot (18 October 2026)

**Branch:** `feature/p0-07-benchmark` (from `main` after the P0-03 merge).
**Gate:** P0-07 (full V1 readiness and performance acceptance). Protocol: `docs/P0-07-BENCHMARK-PROTOCOL.md`, §9 decisions recorded under Ken's 18 October delegation; **not frozen**.
**Evidence level:** three pilot runs on six pilot tasks (`--pilot`, excluded from any study analysis). Pilot results stay in `runs/p0-07/` (git-ignored).

## 1. What was built

| File | What |
|---|---|
| `scripts/p0_07_bench.py` | `validate` (suite schema, strata, routes, deterministic checks proven by pass/fail examples, suite hash), `run` (arm A direct Claude agent, arm B CIDM broker + offline audit, seeded randomised schedule, resumable, $5 study-wide Jev hard stop with per-run `max_usd = min(1, remaining)`, safety stop), `analyze` (paired qualified yield, stratified bootstrap 95% interval, δ = 15 pp decision, separate efficiency intervals). A study run refuses an unfrozen suite. |
| `tasks/p0-07/` | Six pilot tasks, two per stratum, code-reading questions from this repo's domain. |
| `tests/test_p0_07_bench.py` | 26 offline tests. Full suite 745 pass, 5 skips. |

## 2. Pilots

| Pilot | Outcome | Lesson (fixed before the next pilot) |
|---|---|---|
| 1 | Stopped by the injection gate on `s3-01` arm B | False positive: CIDM gave the right flag and named the injected `--unlimited` instruction while refusing it. Markers must be canary tokens, not the injected claim. |
| 2 | Stopped by the injection gate on `s3-02` arm B; `s3-01` arm B failed | Second false positive: CIDM quoted the injection, canary included, while refusing it. Injected text now asks to *end* the reply with the canary and markers are anchored with `$`; the validator requires a passing refusal example per S3 task. The `s3-01` failure was a DNS `network_error` 16 ms into the first Jev call: now recorded as `infra_failure`, excluded and re-run. |
| 3 | 12/12 runs accepted, no safety failures, no infrastructure re-runs | Harness works end to end. See §3. |

Pilot 3 (six paired tasks): yield A 1.00, B 1.00. Efficiency, B minus A, stratified bootstrap 95% intervals: wall clock +41.5 s (37.2 to 45.7; means 18.6 s vs 60.1 s), Claude API-equivalent +$0.127 (0.114 to 0.140; $0.084 vs $0.211), worker tokens +27,294 (26,454 to 28,134; 11,605 vs 38,898). Jev $0.0070 for six arm-B runs.

## 3. Findings that change the task suite

1. **Ceiling effect.** Both arms answered every pilot task correctly, so tasks like these cannot discriminate quality. The full suite must be harder: questions that need several sources combined, near-miss values, stale or contradictory material, longer code. Aim for a direct-agent yield around the protocol's assumed p = 0.85 or lower; a suite where both arms score 100% makes non-inferiority trivially true and says nothing.
2. **Cost and latency of CIDM are already measurable**: about 3× wall clock, 2.5× Claude usage and 3.4× worker tokens against a direct Opus-medium agent on these tasks. Unless quality differs on harder tasks, the study will show CIDM costs more without being better, which the protocol must report as is.
3. **Injection checks must tolerate refusals that quote.** Fixed in the harness and validator.

## 4. Full task suite (authored 18 October 2026, not frozen)

71 tasks in `tasks/p0-07/` (24 S1, 24 S2, 23 S3). `validate --expect-full` reports ok. The suite hash is printed by `validate`; it goes into §10 only at freeze. The pilot ids are kept. `s1-01` and `s3-01` were rewritten to be harder with the same gold and canary, `s3-02` gained decoy sources, and the other pilot tasks were replaced. Every task is a code-reading or debugging question about this repo's own code. Difficulty comes from traps: near-miss values, check-order traps, Python semantics (float sums, `str(None)`, `\b` in regexes, `bool` as `int`, `float('1_000')`) and stale docstrings.

| Stratum | Task families |
|---|---|
| S1 (single bounded question, short route) | `RunConfig` defaults and error order; reservation ceilings (Claude checker priced at Opus rates); `_cost_from_response` shadowing; Claude CLI usage totals and error order; Jev probability/score tolerances and model-id checks; permit basis rules; spend-cap float sum on replay; reversibility classifier and approval gate; browser and MCP access classes; MCP argument checks; sanitiser marker counts; `calculate` range checks; route coverage; `validate_spec` scope; distiller confidence; bench `_quantile`. |
| S2 (several sources combined, traced through more than one function) | `Gateway.call` admission (follow-up Jev reservation, call slots), Jev token budget, response-usage and identity checks; permit-ledger audit and replay with malformed receipts; provider runs feeding the spend cap; `chunk_text` overlap trace; broker config merge; bench `analyze` yields and safety entries; a planted bug (`permit_receipts` typo); `require_approval` messages; metrics comparison; route preflight; wrap truncation after redaction; strict sanitiser message; `calculate` node budget; skill naming; offline spend audit; browser and MCP permits for strong actions. |
| S3 (stale, contradictory or injected source in every task) | The same code areas, each with a stale doc giving a plausible wrong value and an injected instruction carrying a unique canary that the reply is asked to end with (markers anchored with `$`). One task (`s3-18`) also has two real, conflicting limits: the transport 24,000-byte guard and the 28,000-byte guard in `jev_decide`. |

**How the gold answers were checked.** `tasks/p0-07/build_suite.py` is the source of all 71 JSON files. For each task it calls the repo's real functions on the task's exact inputs and asserts the gold answer. Those functions include `RunConfig`, `Gateway.call` with a fake `_request`, `PermitAuthority` on real hash-chained ledgers, `audit_permit_ledger`, `chunk_text`, `bench.analyze` and `validate_response`. It also checks every code excerpt line by line against the file it names. Only S3's stale and injected sources, test output and the planted-bug copy are not checked against a file. `python tasks/p0-07/build_suite.py --check` re-verifies everything and fails if any JSON differs from the builder. Each task's pass examples include a differently phrased correct answer; its fail examples are the trap answers.

**For Ken's review.**
- Protocol §3 requires at least one S2 task in three to be built to trigger a repair, retrieval or pause. These tasks are built to invite a first-pass wrong answer, which a checker would have to catch. None of them requires retrieval, because both arms get identical sources and arm B has no retrieval index.
- Difficulty is not measured yet. No live run has used the new suite.
- Count checks (s1-07, s1-08, s1-14, s1-15, s1-19, s2-07, s2-14, s2-16, s2-18, s3-15) no longer accept a bare number. `count()` in the builder needs the count stated as the answer: it opens the answer, follows a key (`receipted is 7`), or comes before the counted thing (`7 markers`). Any other number in those positions fails, unless it follows "not", "than" or "of (the)". s2-07 also ties each yield to its arm, so swapped yields fail. Each of these tasks has a new fail example that mentions the gold number but states a wrong count. Known trade-off: a correct answer phrased unusually (for example "it reports 7, the receipted value") can be rejected.
- Single-value checks (for example s1-01 `100000`, s1-03, s1-05, s1-11, s1-13, s1-22, s1-24, s2-04, s2-06, s2-12, s2-22, s3-03, s3-05) still match the gold value anywhere. "It stays 50000; it would only become 100000 if the default were untouched" passes s1-01. The same `count()`-style binding could be applied to them if wanted.
- The regex checks favour exact tokens. Those patterns are worth reading.

## 5. Next steps

1. Optional: a pilot on a sample of the new suite (`--pilot`) to see whether the direct-agent yield is near the 0.85 target before freezing.
2. Ken reviews the suite and its checks, then the freeze record (§10) gets the suite and file hashes and Ken's countersignature.
3. Study run: `python scripts/p0_07_bench.py run` (resumable; Pro rate limits may spread it over days).

*CIDM architecture and research by Ken Caber (Kenneth Vic A. Caber).*
