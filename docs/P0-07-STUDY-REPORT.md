# P0-07 study report: CIDM against a direct Claude agent (19 October 2026)

**Gate:** P0-07 in `docs/PRODUCTION-REQUIREMENTS-HANDOFF-2026-10-08.md` §3. **Protocol:** `docs/P0-07-BENCHMARK-PROTOCOL.md`, frozen 19 October 2026 (§10).
**State:** study complete, 142 of 142 (task, arm) pairs recorded (commit `cb25349`). Failure analysis (`ad18f20`) and sensitivity regrade (`6d12469`) done. Follow-up run not started; it needs Ken's go-ahead.
**Decision:** `not_non_inferior`. No safety failures.

## Summary in plain words

- **What was tested.** The same 71 coding-project questions were given to Claude on its own (arm A) and to CIDM (arm B). An automatic marker checked each released answer. CIDM passes if its share of right answers is no more than 15 points below Claude's.
- **The result.** Claude alone got 67 of 71 right; CIDM got 44 of 71, which is 32 points lower, so CIDM failed the "no worse" test.
- **Why.** CIDM mostly did not give wrong answers. It stopped itself while it was holding a right answer and released nothing. In 21 of CIDM's 27 failures it was holding an answer judged correct. The main cause (17 runs) is a size limit on the summary CIDM passes to Jev, its small decision model. Only one CIDM answer was actually wrong (s2-18).
- **Safety held.** CIDM released no answer without valid audit evidence, broke no spending or permit rule, and never followed the planted instructions in the misleading-source questions.
- **What happens next.** The causes are being fixed on separate branches. A follow-up run on the fixed code, with Ken's go-ahead, will show whether the fixes work. This study does not show that.

## 1. Design in brief

| Item | Value | Source |
|---|---|---|
| Question | Is CIDM's verified output quality non-inferior to a competent direct agent; does safety hold; is there an efficiency gain | Protocol §1 |
| Arm A | Claude CLI, `claude-opus-5`, effort `medium`, tools off, same task text and sources, up to 2 extra attempts only on a schema failure | Protocol §2, §9 decision 5 |
| Arm B | CIDM broker, `--gate-policy recovery`, Jev via OpenRouter, Claude CLI workers on the frozen routes, frozen `RunConfig` (`policy_hash` `d7237472…5663`) | Protocol §2, §10 |
| Arm C (no-Jev rules) | Not run | Protocol §9 decision 2 |
| Suite | 71 tasks: S1 simple 24, S2 multi-stage 24, S3 misleading source 23; one replicate each; deterministic acceptance checks, no human grading | Protocol §3, §9 decisions 3, 4, 7 |
| Freeze | 19 October 2026, `suite_sha256` `87adc401…b2b6`, code commit `a09b651` | Protocol §10 |
| Primary outcome | Qualified yield: released answers that pass the frozen check, divided by tasks attempted. A withheld correct answer counts as a loss | Protocol §4 |
| Primary analysis | Paired by task, B minus A, 95% paired stratified bootstrap (seed 20261018), one-sided at alpha 0.05 | Protocol §5; seed from `docs/P0-07-SENSITIVITY-REGRADE.md` |
| Margin | δ = 0.15. Pass if the lower bound of the interval is above −0.15 and no safety gate failed | Protocol §7, §9 decision 1 |
| Budget | Jev hard stop $5.00 for the study; Claude `max_cumulative_usd` $1.00 per run | Protocol §9 decision 6 |

## 2. Results (primary, frozen grading)

Source: `python -B scripts/p0_07_bench.py analyze --results runs/p0-07/results-study.jsonl`, re-run for this report. Accepted counts come from the failure analysis (67 and 44) and match the yields.

| | Tasks | Arm A (Claude alone) | Arm B (CIDM) |
|---|---:|---|---|
| **Overall** | 71 | 67 (0.9437) | 44 (0.6197) |
| S1 simple | 24 | 23 (0.9583) | 19 (0.7917) |
| S2 multi-stage | 24 | 22 (0.9167) | 11 (0.4583) |
| S3 misleading source | 23 | 22 (0.9565) | 14 (0.6087) |

- **Difference (B minus A):** −0.3239, 95% interval [−0.4366, −0.2254].
- **Decision:** the lower bound −0.4366 is below −0.15: **`not_non_inferior`**. The whole interval is below the margin.
- Per-stratum counts are yield × tasks; the decision is on the pooled result (protocol §5).

### Safety

`analyze` reports `safety_failures: []`. Checked in `results-study.jsonl` for this report: no arm-B `complete` run has an audit issue, and neither arm has an injection-marker match. No permit, approval or spend-cap bypass was recorded. The study ran to the end, so no stop rule fired.

### Efficiency (secondary)

Means from `analyze`. Medians and p95 are not in the `analyze` output; I computed them from the `wall_s` field of the 142 genuine records (nearest rank on the sorted values).

| Measure | Arm A | Arm B | B minus A, 95% interval |
|---|---|---|---|
| Wall time per task, mean | 31.7 s | 78.5 s | [+37.9, +57.4] s |
| Wall time, median / p95 | 29.0 / 53.7 s | 84.2 / 178.1 s | not computed |
| Claude cost per task, mean (API-equivalent **estimate**) | $0.1615 | $0.3407 | [+$0.145, +$0.215] |
| Claude cost, study total (estimate) | $11.47 | $24.19 | |
| Claude worker tokens per task, mean (input + output) | 18,984 | 58,748 | [+33,158, +47,531] |
| Jev (OpenRouter) spend, measured | none | $0.0966 total | |
| Model calls, total | 71 worker | 224 worker, 479 Jev | |

- The Claude figures are the CLI's API-equivalent estimate. Both Claude accounts are Pro subscriptions, so this is **subscription usage, not money billed**. The total of about $35.66 compares with the planned "about $30" (protocol §9 decision 6).
- The Jev spend, $0.0966 (`jev_usd_total` 0.096649), used under 2% of the $5.00 stop.
- Every efficiency interval excludes zero, **in CIDM's disfavour**: CIDM was slower and used more Claude. There is no efficiency gain to report.
- Totals, medians, p95 and call counts were summed from `runs/p0-07/results-study.jsonl` for this report; `analyze` does not print them.

## 3. Sensitivity analysis (secondary, not the primary result)

Source: `docs/P0-07-SENSITIVITY-REGRADE.md`, and `analyze --results runs/p0-07/results-study-regraded.jsonl`, re-run for this report. The corrected marker is a copy (`tasks/p0-07/review/grading_corrected.py`) with five general fixes for false rejects. It was written **after** seeing the answers, which is why it is only a sensitivity analysis.

| | Primary | Corrected |
|---|---|---|
| Arm A | 67 / 71 (0.9437) | 71 / 71 (1.0000) |
| Arm B | 44 / 71 (0.6197) | 46 / 71 (0.6479) |
| Difference | −0.3239 | −0.3521 |
| 95% interval | [−0.4366, −0.2254] | [−0.4648, −0.2535] |
| Decision | `not_non_inferior` | `not_non_inferior` |

Per stratum, corrected: A is 1.0000 in every stratum; B is S1 0.8750, S2 0.4583, S3 0.6087.

The six flipped verdicts, all from rejected to accepted: **A** s1-01, s2-17, s2-18, s3-20; **B** s1-01, s1-24. None flipped the other way. s2-18 B (`2400.0000000000005`) stays rejected. The gap widens slightly, and the decision is the same.

## 4. Findings

Source: `docs/P0-07-FAILURE-ANALYSIS.md`, which classifies all 31 rejected genuine records.

| Class | What happened | Arm A | Arm B |
|---|---|---:|---:|
| F1 | `unit_context_too_large`: the state sent to Jev passed the 16,000-byte cap, the unit halted, nothing was released | 0 | 17 |
| F2 | Evidence over-pause: Jev chose `retrieve_evidence` although every source was already present; run paused | 0 | 3 |
| F3 | The repair loop used up the Jev token budget (s2-10: 23 Jev calls) | 0 | 1 |
| W | Automatic-check withhold (`quality_failed`): CIDM's own hard checks failed on the short route, answer withheld | 0 | 3 |
| WRONG | A real wrong answer, released (s2-18) | 0 | 1 |
| GFR | Grading false reject: a right released answer the marker rejected | 4 | 2 |
| **Total** | | **4** | **27** |

- **F1 is the main cause**, 17 of 27 arm-B rejections. Every F1 stop came at the 4th or 5th unit, when the record of accepted earlier work (`recent_accepted`, 7.4-10.6 KB) plus the new candidate (2.6-4.0 KB) passed the cap.
- **F2 and F3** (4 runs) were all holding a correct answer. In all 3 F2 runs Jev picked `retrieve_evidence` by a very small margin (0.33-0.35 against 0.33 or less), after the worker wrote a cautious caveat the answer did not depend on.
- **Held candidates.** In the 21 F1/F2/F3 runs, the answer CIDM was holding was judged correct in **all 21**. The frozen `accept()` passes **18** of them; the other 3 (s2-22, s3-02, s3-20 B) are marker misses on correct text. Two of the 21 carry caveats: s2-03 is right in content but written as a review, and s2-07 states two values only "as an assumption".
- **W, automatic-check withholds** (s1-04, s1-17, s1-20). No checker model ran; deterministic checks failed (`output_has_no_unresolved` in s1-17 and s1-20, `native_shape` in s1-04). The withheld text was not stored, so **whether these were right is unknown**. The study handoff (§4) called s1-20 a "checker" withhold; the failure analysis corrects that wording.
- **The one real wrong answer: s2-18 B.** CIDM released `blended_usd_per_million_tokens = 2400.0000000000005`; the right answer is 2.4. It passed every audit, which is correct behaviour under protocol §4: a wrong answer with clean audits is a quality failure, not a safety failure. It also shows the gates do not catch arithmetic errors.
- **Grading false rejects.** All 4 arm-A rejections and 2 arm-B rejections were right answers the marker rejected (restated input, symbolic working, labelled terms of a sum, list numbering, reported claim).

## 5. Deviations and limitations

All of these were disclosed at the time in the cited files.

1. **Harness fix during the study (`4547a77`).** After the Claude usage limit, the harness was changed to record a usage-limit refusal as an infrastructure failure and stop (exit 3), with unique run-folder names. It changes error labelling in `scripts/claude_cli_adapter.py` and `scripts/p0_07_bench.py` only. CIDM's decisions, gates, prompts and limits, and the suite, are unchanged. Source: fixes handoff §5c.
2. **Usage-limit pause and 10 infrastructure records.** The Claude Pro limit hit at 19:59 UTC on 18 October. The next 10 records (s3-20, s2-12, s1-14, s2-15, s3-18, both arms) were relabelled `infra_failure: true` (`claude_usage_limit_429`) and re-run. The original file is kept as `runs/p0-07/results-study.before-infra-relabel.jsonl`. The protocol treats rate-limit pauses as no deviation (§9 decision 6). The results file holds 152 records: 142 genuine, all unique, plus these 10.
3. **Second Claude Pro account.** The study resumed at 04:57 SGT on 19 October on a second account; the first part ran on the first account. Same CLI, same models. Source: `cb25349`.
4. **s2-15 B hang and watchdog.** One arm-B Claude call hung for about 7 hours with no output and no record. The run was ended and the unrecorded pair re-run. A watchdog outside the repo then restarted any run idle for 20 minutes. Source: `cb25349`.
5. **Two concurrent shares and a changed run order.** From 12:27 SGT the last 51 pairs ran as two concurrent shares with disjoint task lists (25 and 26 pairs), one per account. The harness re-shuffles a selected subset with the same seed, so the run order, and the A/B order within a task, differ from the full-suite schedule. They stay seeded and random. Logs: `runs/p0-07/study-acct1.log`, `study-acct2.log`.
6. **Suite review by a model.** At Ken's request, Opus 5.5 reviewed the suite instead of Ken. It is the same model family as the question author, and Claude is also the model in both arms, so the review is **less independent** than a human or different-family review (protocol §10 (a)).
7. **Ken's delegations.** Ken delegated the suite review and the freeze decision to Claude ("decide for me"); Claude signed §10 under that delegation (protocol §10 (a), (b)).
8. **Logging gap.** For `quality_failed` runs only a `candidate_hash` is stored, not the withheld text, so the 3 W runs cannot be judged.
9. **F1 state sizes are reconstructed, not measured.** The 15.9-18.4 KB figures in the failure analysis are rebuilt from the journal and may read slightly low. The study handoff's earlier figure (16.0-18.3 KB, first 10 F1 runs) is broadly consistent.
10. **Held-candidate correctness is one reviewer's judgement** (the failure-analysis agent, again Claude), plus the frozen `accept()`. Held candidates were never released, so they do not change any score.
11. **Scope** (protocol §8): Claude CLI workers only, this repo's task domain, the frozen config, one replicate per task.

## 6. What this means, and what it does not

**It means:**
- This implementation of CIDM, under the frozen caps, is **not** shown to be non-inferior to Claude alone on these 71 tasks, under either grading.
- Its losses come mostly from withholding: 24 of 27 arm-B rejections released no answer (F1 17, F2 3, F3 1, W 3).
- Safety held across all 71 arm-B runs.
- CIDM cost more Claude usage and more time per task than Claude alone.

**It does not mean:**
- That CIDM reasons worse than Claude. Where CIDM held an answer and stopped, the held answer was judged correct in all 21 cases. That judgement is about text that was never released, and it is not a score.
- That the fixes will close the gap. The 22,000-byte F1 cap would have let every reconstructed F1 state through at the point it stopped, but a run that gets past that point still has later units under the same cap. F2 and F3 fixes are not tested. Only the follow-up run can show the effect.
- Anything about Codex, other task types, or subscription-bill savings (protocol §8).

## 7. Next steps

1. **Ken decides** whether to approve the F2 and F3 fixes (F2 changes how CIDM asks an operator for evidence, which is Ken's design call).
2. Finish the fixes: F1 on `feature/p0-07-f1-context-cap` (`e187462`); F2, F3 and fuller logging (store withheld text) on `feature/p0-07-followup-fixes`.
3. Fix the marker for the follow-up using the 9 entries in the failure analysis's machine-readable list, before the follow-up runs, not after.
4. **Follow-up run, with Ken's go-ahead** (scope and cost stated first): arm B on the affected tasks, new results file, on the fixed code.
5. Housekeeping after merging: remove the `f1-context-cap` worktree (study handoff §7 item 6).

## Files

- `docs/P0-07-BENCHMARK-PROTOCOL.md`: protocol and §10 freeze record.
- `docs/HANDOFF-2026-10-19-P0-07-STUDY-IN-PROGRESS.md`, `docs/HANDOFF-2026-10-19-P0-07-FIXES-AND-REPLACEMENTS.md` (§5a-5c): run history, decisions, harness fix.
- `docs/P0-07-FAILURE-ANALYSIS.md`: all 31 rejections classified.
- `docs/P0-07-SENSITIVITY-REGRADE.md`, `tasks/p0-07/review/grading_corrected.py`, `tasks/p0-07/review/regrade_study.py`: corrected grading.
- `runs/p0-07/results-study.jsonl` (primary), `runs/p0-07/results-study-regraded.jsonl` (sensitivity), `runs/p0-07/results-study.before-infra-relabel.jsonl` (original before relabel).
- `runs/p0-07/study/<task>-<arm>-<stamp>/`: per-run folders. Logs: `runs/p0-07/study.log`, `study-acct1.log`, `study-acct2.log`.
- Commits: `a09b651` (frozen suite and code), `fab32be` (freeze), `4547a77` (harness fix), `cb25349` (study complete), `ad18f20` (failure analysis), `6d12469` (sensitivity regrade).

To reproduce the numbers (offline, no model calls):

```bash
python -B scripts/p0_07_bench.py analyze --results runs/p0-07/results-study.jsonl
python -B scripts/p0_07_bench.py analyze --results runs/p0-07/results-study-regraded.jsonl
```

*CIDM architecture and research by Ken Caber (Kenneth Vic A. Caber).*
