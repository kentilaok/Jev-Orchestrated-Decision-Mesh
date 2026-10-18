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

## 4. Next steps

1. Author the remaining 65 tasks (to 24/24/23) to the difficulty target above; keep or replace the six pilot tasks. `python scripts/p0_07_bench.py validate --expect-full` must pass.
2. Ken reviews the suite and its checks, then the freeze record (§10) gets the suite and file hashes and Ken's countersignature.
3. Study run: `python scripts/p0_07_bench.py run` (resumable; Pro rate limits may spread it over days).

*CIDM architecture and research by Ken Caber (Kenneth Vic A. Caber).*
