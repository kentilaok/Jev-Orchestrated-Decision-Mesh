# P0-07 benchmark protocol (DRAFT, not frozen)

**Status:** draft for Ken's decisions. Nothing here is preregistered until §9 is filled in, signed and dated, and the file hash is recorded in §10. No paid run may use this protocol before then.
**Parent gate:** P0-07 in `PRODUCTION-REQUIREMENTS-HANDOFF-2026-10-08.md` §3. Method follows `THESIS.md` "Falsifiable evaluation protocol".
**Depends on:** P0-03 (live execution). The P0-03 smoke run supplies the per-task cost estimate needed for the budget in §6.

## 1. Question

Is CIDM's verified output quality **non-inferior** to a competent direct agent on the same tasks, does operational safety hold, and is there any efficiency gain? Savings are reported only if measured; they are not a V1 release claim.

## 2. Arms

Routing follows the 2026-10-14 decision: Jev via OpenRouter, workers via the local Claude CLI. Codex is out of scope for this study (decided 2026-10-16).

| Arm | What runs | Notes |
|---|---|---|
| **A. Direct agent** (comparator) | Claude CLI, same model and effort as CIDM's worker, given the same task text and the same source package, one attempt plus the same retry ceiling CIDM gets | The "competent direct Claude agent" from P0-07 |
| **B. CIDM** | Broker `--gate-policy recovery`, Jev via OpenRouter, Claude CLI worker, frozen `RunConfig` | `max_cumulative_usd` set per §6 |
| **C. Deterministic no-Jev rules** (optional) | Broker with Jev decisions replaced by fixed rules | Only if Ken selects it in §9; isolates what Jev adds |

Arms see identical sources, tools, time ceilings and release criteria. Run order is randomised per task.

## 3. Task suite

Three strata, as P0-07 requires. Tasks are written and frozen before any evaluation run and are never used for prompt or policy tuning.

| Stratum | Definition | Pass is decided by |
|---|---|---|
| **S1 Simple deterministic** | Single-step, self-contained, one correct answer | Deterministic validator |
| **S2 Multi-stage / recovery** | Needs several units; at least one task in three is built to trigger a repair, retrieval or pause/resume | Deterministic validator where possible, blind human grading otherwise |
| **S3 Unknown / misleading source** | Source package contains a stale, contradictory or injected document | Validator for the answer, plus a check that the misleading content was not acted on |

Tasks are coding-project tasks in this repo's domain, not synthetic arithmetic (P0-07 excludes toy fixtures). Each task ships with a frozen source package, a gold answer or acceptance test, and a stratum label.

## 4. Outcomes

**Primary (quality):** *qualified yield*, meaning released outputs that pass the frozen acceptance check, divided by tasks attempted. A withheld correct answer counts as a coverage loss, not a win (`THESIS.md` step 3).

**Safety (hard gates, any one fails the study):**
- an invalid release (output released that fails its acceptance check while CIDM's gates said pass);
- a permit, approval or spend-cap bypass;
- acting on injected content in S3.

**Secondary (efficiency, reported separately, never summed across billing units):**
- OpenRouter dollars (Jev), measured;
- Claude CLI cost as the CLI's API-equivalent estimate, labelled as an estimate (it is not the subscription bill);
- tokens per role, model calls per role, retries, rejected candidates, failures, operator actions;
- wall-clock time, median and p95.

Unknown usage is reported as unknown, never as zero.

## 5. Analysis

- Paired by task. Primary analysis: one-sided non-inferiority test on the difference in qualified yield (B minus A) at the margin δ chosen in §9, alpha 0.05 one-sided, with a 95% paired stratified bootstrap interval (seed recorded).
- Per-stratum results are reported, but the non-inferiority decision is on the pooled primary outcome unless §9 says otherwise.
- Every run is kept, including failures and negative findings.
- Grading is blind to arm. An independent reviewer, not the author of the task suite, signs off on grades before unblinding.

## 6. Sample size and budget

Sample size for a binary non-inferiority comparison, assuming both arms have true qualified yield p = 0.85 (an **assumption** to replace with the P0-03 smoke-run result), alpha 0.05 one-sided, power 0.80. These are unpaired figures; pairing by task usually lowers the requirement, but the reduction depends on a correlation we have not measured, so the unpaired figure is the conservative plan.

| Margin δ | Tasks per arm |
|---|---:|
| 10 percentage points | 158 |
| 15 percentage points | 71 |
| 20 percentage points | 40 |

Per-task cost is unknown until P0-03 runs. Budget = tasks × arms × measured per-task cost, plus headroom, set in §9 after the smoke run.

## 7. Stop / go rules

- **Stop immediately** on any safety-gate failure in §4. Report it; do not rerun to replace it.
- **Stop** when cumulative OpenRouter spend reaches the budget in §9.
- **Interim look:** none, unless §9 adds one with an alpha-spending rule. No peeking at outcomes mid-study.
- **Go (pass):** lower bound of the 95% interval for B minus A is above −δ, and no safety gate failed.
- **Fail:** otherwise. Efficiency claims are made only if the corresponding interval excludes zero.

## 8. What this study cannot show

It covers Claude CLI workers only, on this repo's task domain, at the frozen config. It says nothing about Codex, other task distributions, or subscription-bill savings (the CLI reports an API-equivalent estimate, not the plan charge).

## 9. Decisions needed from Ken (fill in, then freeze)

| # | Decision | Proposal | Ken's choice |
|---|---|---|---|
| 1 | Non-inferiority margin δ | 15 pp (71 tasks per arm) | |
| 2 | Include arm C (no-Jev rules)? | No for V1; adds a third arm's cost | |
| 3 | Task split across S1/S2/S3 | Equal thirds | |
| 4 | Who authors tasks, who grades | Tasks authored before any run; grader is a fresh reviewer who did not author them | |
| 5 | Worker model and effort for arms A and B | Decide after P0-03 smoke run | |
| 6 | Total OpenRouter budget | Set after P0-03 measures per-task cost | |
| 7 | Replicates per task | 1, since 71+ tasks already dominates cost | |

## 10. Freeze record

Filled in when frozen: date, signer, SHA-256 of this file, commit, `RunConfig.policy_hash`, task-suite hash.

*CIDM architecture and research by Ken Caber (Kenneth Vic A. Caber).*
