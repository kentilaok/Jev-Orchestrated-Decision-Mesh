# CIDM study results

**Study:** `20260928T013651Z-cidm-inference-audit` · written 2026-09-28 (UTC)

## 1. Evidence status: what was and was not run

| Evidence | Kind | Run by this study? | Can support |
|---|---|---|---|
| Public GPT-6 fixture traces (`research/live-gpt6-*`), 2026-09-23 | **Actual provider runs** (one per arm) | No: reconciled from raw bytes | Descriptive cost and accounting on one 3-row fixture |
| Historical GPT-5.6 pilot (`research/historical-pilot`) | Actual provider runs, 12 tasks × 2 arms | No: reconciled | Its own design only (different architecture) |
|  [withheld: private project evidence] |  [withheld: private project evidence] |  [withheld: private project evidence] |  [withheld: private project evidence] |
| Gate-variant replay (`reconciliation/replay-gate-variants.*.json`) | **Replay estimate** | Yes | Jev prompt-size effects, if routes stayed the same; **not outcomes** |
| Mock benchmark (`runs/mock-smoke-dev`, `runs/mock-pilot-heldout`) | **Mock simulation** | Yes | Harness and analysis plumbing **only**; no evidence about any arm |
| Offline unit tests | Tests of real code under mocks | Yes | Control behaviour and defects (F01–F16, candidate flags) |
| Live benchmark arms A–E5 | Actual provider runs | **Not run** (no budget, no credentials, egress blocked) | Would be the causal test (§7) |

## 2. Accounting coverage

| Actor | Public fixture runs | Historical pilot |  [withheld: private project evidence] | Benchmark harness (design) |
|---|---|---|---|---|
| Host / primary agent | none (Python controller, no LLM) | none (Python controller) |  [withheld: private project evidence] | metered (host classification and compression are explicit calls) |
| Jev | complete | complete |  [withheld: private project evidence] | complete |
| Workers | complete | complete |  [withheld: private project evidence] | complete |
| Checkers | complete | n/a |  [withheld: private project evidence] | complete |
| Provider generation ids | in response files | in ledger |  [withheld: private project evidence] | saved per event |
| Wall-clock latency | **not recorded** (sums of API latency only) | per task |  [withheld: private project evidence] | per attempt |

**Consequence:** no run in existence supports a complete-system savings claim for CIDM on real project work.

## 3. Measured observations: public fixture (actual provider runs, n = 1 each)

Task: 3-row production-defect rate. All five runs returned the correct, cited, trial-excluded answer. Baseline: one GPT-6 Sol-high call (431 tokens, $0.001726, 4.297 s API time).

| Run (policy) | Calls | Tokens | Charge | Summed API s | Saving vs baseline `1 − c/b` | Jev share: tokens / $ |
|---|---:|---:|---:|---:|---:|---|
| Mandatory Sol-high review (older) | 23 | 36,663 | $0.012201078 | 36.311 | **−607%** | 86.5% / 10.6% |
| Conditional review, first | 13 | 25,651 | $0.003120190 | 13.468 | **−81%** | 92.8% / 31.2% |
| Conditional review, hardened | 13 | 25,510 | $0.006413654 | 13.499 | **−272%** | 93.1% / 15.1% |
| Fast exit to exact code (previous policy) | 1 | 716 | $0.000026964 | 0.656 | +98.4% | 100% / 100% |

- **No uncertainty is computable.** Each arm has one run. With 0 quality failures in 3 conditional/mandatory CIDM runs, the one-sided 95% upper bound on the failure rate is 63%.
- **Strong-model use differed by route.** Baseline: 1 Sol-high call. Mandatory: 5 Sol-high checks. Hardened: 3 Sol-low workers. First: 1 Sol-low and 2 Luna-low.
- **Interpretation.** On this fixture, every five-unit variant costs more than a competent direct call. The fast exit's saving comes from replacing a model with fixed arithmetic code. A no-Jev rule ("use code for arithmetic") would capture the same saving, so it is not evidence for Jev gating.

## 4. Historical pilot (actual runs; reconciled)

| Measure | Value |
|---|---|
| Reproduced exactly | tokens +276% (95% CI +215.5% to +338.8%); cost saving 9.6% (CI −29.3% to +49.1%); released answers passing 7/12 vs 9/12 |
| New | 51,411 cache-write tokens at 1.25× input, 0 cache reads. The unrecouped premium accounts for about 70% of the reported cost gap. With it removed from both arms, the saving is 2.9% (derived sensitivity, not causal) |

## 5. Replay diagnostics (estimates, not measurements)

The replay drives the unchanged controllers with recorded choices and artifacts; the bytes-to-tokens fit is within about 1.3% on totals.

| Variant (hardened run) | Jev calls | Est. Jev tokens | Est. Jev $ | Share of that run's total $ |
|---|---:|---:|---:|---:|
| Measured legacy | 10 | 23,752 (measured) | $0.000970 | 15.1% |
| Fused (E1) | 6 | ~22,090 (−7%) | ~$0.000907 | saves ≈1% |
| Skip vacuous gates (E2) | 6 | ~17,360 (−27%) | ~$0.000708 | saves ≈4% |

These assume the same routes and outputs, which a replay cannot establish. Fused prompts grow (11 options per decision), which is why removing 4 of 10 calls saves only 7% of Jev tokens.

 [withheld: private project evidence]

## 7. Mock benchmark (harness validation only)

The mock pilot ran 10 arms × 12 held-out tasks × 3 repetitions:

| Check | Result |
|---|---|
| Attempts completed | 360/360 |
| Events | 3,417 (0 schema-invalid) |
| Paired comparisons with bootstrap CIs and Holm adjustment | produced |
| D0 (candidate code, all flags off) vs D (installed) | identical on every task: the instrumentation fixes changed no prompt or decision |
| E2 vs D (skip vacuous gates) | 60 fewer Jev calls (2 per broad attempt) |

The mock's accuracy table is arbitrary. Its accepted-rate and cost differences between arms (e.g. the mock "harmful" H1 verdict) **are not findings**.

## 8. Candidate implementation (offline tests)

- `candidate-skill/` passes **142/142** tests: the 130 original tests plus 12 new ones.
- The combined patch applies cleanly to HEAD.
- Against the candidate, findings F01 (usage dropped on rejection) and F11 (no generation id or timestamps) no longer reproduce. The other 14 findings are unchanged, because policy flags default off.

| Change | Kind | Status |
|---|---|---|
| Receipts keep generation id and UTC timestamps; append-only (`jev_decide.py`) | instrumentation, default on | ready for review |
| Gateway events keep generation id and timestamps | instrumentation, default on | ready for review |
| Codex usage survives post-completion rejection; `usage_status` | instrumentation, default on | ready for review |
| Broker `accounting` block (`complete_system_accounting: false`, unknown counts) | instrumentation, default on | ready for review |
| `skip_vacuous_gates` (E2) | policy flag, default off | **untested live** |
| `unresolved_policy=block_at_unit` (E3) | policy flag, default off | **untested live** |
| `jev_evidence_mode=cited_only` (E4) | policy flag, default off | **untested live** |

## 9. Answers

1. **What work actually passed through Jev, and what happened outside it?**
   - Jev saw only host-written state capsules and host-written option menus, and returned typed choices.  [withheld: private project evidence]
   - Outside Jev: scope classification, evidence gathering and summarisation, every state capsule, all "deterministic" work (reading, coding, testing, deploying, writing advice), worker dispatch, validation, repairs and final wording.  [withheld: private project evidence]
2. **Is "deterministic" routing concealing primary-model reasoning?**
   - **Yes.**  [withheld: private project evidence]The label matches SKILL.md's own definition (SKILL.md:52) only for fixed code on frozen inputs, as in the public fixture's `input`/`hidden2` units.
3. **Can requested model/effort and billed usage be verified?**
   - **Jev:** model and provider confirmed; usage and cost verified to the unit.
   - **OpenRouter workers:** model and provider confirmed; usage verified; effort never confirmed.
   - **Codex children and interactive subagents:** requested-only identity;  [withheld: private project evidence] effort never confirmed.
   - **Historical receipts:** cannot be reconciled with provider generation lookups, because no generation ids were saved.
4. **Does CIDM beat a competent direct model and a simpler no-Jev policy at the declared quality level?**
   - **Not shown; the available evidence points the other way on small tasks.**
   - On the only matched fixture, every five-unit variant cost 1.8–7.1× a single Sol-high call for the same correct answer.
   - In the historical pilot, tokens rose 276%, and the cost difference is not robust (mostly a cache-write artefact).
   - No no-Jev cascade (arm B) or router-only (arm C) comparison has ever been run live.
   - Verdict: **inconclusive for broad projects; no advantage demonstrated anywhere**.
5. **Which individual changes helped, harmed, or remain inconclusive?**
   - **Helped (accounting correctness, offline):** receipt ids and timestamps, append-only receipts, usage preserved on rejection.
   - **Inconclusive (replay estimates only):**
     - Skip vacuous gates: ≈27% fewer Jev tokens, ≈4% of run cost.
     - Fused gates: ≈7% fewer Jev tokens, ≈1% of run cost, and they change the option semantics.
     - Cited-only Jev state and block-unresolved-at-unit: no live data.
   - **Harmful or risky (evidence):**
     - Zero-shot route choices are near coin flips and non-reproducible.
     - The near-tie Jev defect fails runs after billing.
     - The structural-only release checks pass content-free answers.
6. **What is ready, what should be rejected, what remains untested?**
   - **Ready as a candidate (after review):** the four instrumentation fixes.
   - **Reject as claims** until measured: "fused gates save X%", "Jev routing selects the cheapest sufficient model", any savings figure derived from Jev-only ledgers, and the historical 9.6% saving as evidence of orchestration value.
   - **Untested:** all live arms (A, B, C, D, E1–E5); host telemetry capture; the calibration of Jev probabilities against outcomes.
   - The active installed skill is **unchanged**; promotion needs separate authorisation.

## 10. Live tests that remain unrun (exact commands; not executed)

The first command runs from the study directory with an approved cap. The provider key goes in the environment, never on the command line. Commands are shown for Linux/macOS; a PowerShell equivalent appears in `README.md` (unverified on Windows).

```bash
# preflight: shows route and schedule; 0 model calls
python -B harness/run_benchmark.py --mode mock --split heldout --reps 1 --arms A,B,C,D,E1,E2 --out runs/preflight-$(date -u +%Y%m%dT%H%M%SZ)
# pilot (≈ 216 attempts; caps are mandatory; ceiling $25 preregistered)
OPENROUTER_API_KEY=... python -B harness/run_benchmark.py --mode live --split heldout --reps 3 \
  --arms A,B,C,D,E1,E2 --max-usd 10 --per-run-usd 0.60 --per-request-usd 0.15 --i-accept-live-spend \
  --out runs/live-pilot-001
python -B harness/analyze.py --run runs/live-pilot-001
```

Also unrun:
- An OpenRouter generation-id reconciliation of new receipts.
- Codex App Server telemetry capture on the Windows host (R11).
- A provider activity export for the duplicated-row window.
