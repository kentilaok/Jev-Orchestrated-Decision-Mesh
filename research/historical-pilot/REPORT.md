# CIDM versus Sol: first controlled pilot

**The current CIDM prototype did not save total tokens.** It reduced Sol's token use, but Jev's context processing and review added substantially more tokens. The observed API bill was slightly lower, while the release policy withheld valid answers.

Caber Interstitial Decision Mesh (CIDM) was proposed by **Kenneth A. Caber**. This pilot tests one bounded implementation, not the full proposed recursive, heterogeneous-model application.

## Measured results

Twelve held-out synthetic tasks; one paired run per task. Both arms used `openai/gpt-5.6-sol` at `medium` effort through the same Azure endpoint on OpenRouter. CIDM also used `typesafe/jev-1.13`, which returned `typesafe/jev-1.13-20260917`.

| Metric | Sol alone | CIDM + same Sol | Observed change |
|---|---:|---:|---:|
| All model tokens | 34,942 | 131,388 | **276.0% more** |
| Sol tokens only | 34,942 | 25,030 | **28.4% fewer** |
| Jev tokens | 0 | 106,358 | Added overhead |
| Recorded API cost | $0.255236 | $0.230693 | **9.6% lower** |
| Sum of per-task elapsed time | 42.248 s | 68.923 s | **63.1% longer** |
| API calls | 12 | 40 | 28 more |
| Answer values correct before release filtering | 12/12 | 12/12 | Same on these tasks |
| Answers released | 12/12 | 7/12 | Five withheld by CIDM |
| Released answers passing frozen value/citation/status checks | 9/12 | 7/12 | Lower delivered coverage |

All 52 evaluation calls returned measured input, output, and cost. Reasoning is already included in output tokens and was not added twice. Jev's outputs were free in dollar terms but still counted as 5,751 reported output tokens. There were no API failures during evaluation; five CIDM runs ended without releasing their candidate.

The total is an operational sum of each provider's token counts. Different tokenizers mean it is not a universal measure of information or hardware computation.

## Quality interpretation

Both arms generated correct final answer values on all 12 tasks, including appropriate null values where facts were missing or contradictory. The frozen primary check additionally required specified supporting citations for every field and the correct complete/partial status. Raw candidates passed that stricter check on 9/12 baseline tasks and 11/12 CIDM tasks.

CIDM withheld five candidates. Four of those passed even the strict frozen check. The fifth had correct answer values but incomplete citations under that rubric. Thus the current release policy is too conservative on this sample; smaller worker context alone did not make the final system more useful.

An independent blind audit confirmed the expected values but found several unnecessarily strict citation requirements in the synthetic grader. These are disclosed in [the audit](blind-grading-audit.md). The frozen grades were not changed after the run. In particular, the 9/12 baseline primary score does **not** mean it answered only 75% of factual values correctly.

## Why the token count grew

CIDM ran Jev before Sol to select relevant source units, then ran Jev again to assess the actual answer against the original corpus. It also requested the five self-scores and uncertainty metadata from Sol. Two tasks required an additional worker/review cycle. This yielded 14 Sol calls plus 26 Jev calls, compared with 12 Sol calls alone.

Jev processed 100,607 input tokens across those calls. Repeated full-source checks preserved access to evidence, but the repeated reads overwhelmed the 9,912-token reduction in Sol consumption. Cheap tokens are still tokens.

The small observed cost reduction is possible because Jev's token price is much lower. It does not imply total-token savings or equal-quality performance.

## Experimental controls

- Three strata: four short direct questions, four noisy-document retrieval tasks, and four cross-document tasks with dependencies, exceptions, conflicts, or missing data. Long cases contain 16–20 document units; one requires the complete set.
- Two separate development tasks checked API compatibility and the pipeline. Both arms passed them. Evaluation thresholds were not tuned to held-out results.
- Identical source corpus, user question, answer fields, fixed Sol model/effort, allowed tools, output requirements, and per-arm resource caps. CIDM's additional metadata is counted as method overhead; the baseline was not padded to match it.
- A used full context and could repair structural errors. B used Jev-selected exact source text and could perform a Jev-authorized semantic correction. The comparison therefore measures source selection **plus review and correction policy**, not source selection alone.
- Original sources were retained. Review saw actual worker artifacts and full original evidence. No golden answers entered worker or Jev prompts.
- Serial execution alternated which arm ran first. There was no cross-arm conversational memory or explicit response cache. All Sol responses reported zero cached-input tokens.
- The controller was deterministic Python, with no hidden host-model inference in the measured path. Grading was deterministic and independent of arm labels, scores, costs, and Jev decisions.
- The dataset, gold labels, harness, prompts, model metadata, and original analysis code were hashed in [the frozen manifest](frozen-manifest.json) before evaluation. Their hashes still match.

## Uncertainty and limits

The paired, stratified task bootstrap estimates a 95% interval of **215.5%–338.8% more tokens**. The cost-saving interval is **−29.3% to +49.1%**, so the small cost reduction is not a robust general result. The conservative interval for the served primary pass-rate difference is −52.5 to +29.1 percentage points.

This is a 12-task feasibility pilot with one replicate per task. It is not powered to establish a five-percentage-point quality noninferiority margin. The tasks are synthetic and mostly closed-answer document problems; they do not establish results for coding projects, production data, long multi-turn projects, or the nine-route Terra/Sol/Astra system.

The Jev relevance and release thresholds were fixed engineering heuristics, not empirically calibrated probabilities of successful task completion. The review also asked Jev to assess aggregate answers involving arithmetic and cross-document dependencies, areas where a future controller should provide executable checks and narrower evidence judgments. This experiment exposes a weakness of the current configuration, not a proof that every CIDM configuration fails.

A correction to the offline analyzer preserved fully measured failed/rejected/partial runs in token totals, while retaining their quality outcomes. The original frozen analyzer is preserved, the corrected file is separate, and [the amendment](amendment.md) documents the change. No task, prompt, threshold, accepted answer, or gold label was changed after evaluation.

## Spend and setup boundary

The evaluation's reported API cost was **$0.485929244** across both arms. Four development runs cost **$0.042355456**. A successful Azure compatibility probe cost **$0.00304**. Two earlier direct-OpenAI requests were rejected by the account's zero-data-retention restriction without returning usage; their token/cost counters remain unknown in the setup records.

The controller reserved $0.32 against those unknown setup attempts for budget purposes. That reservation is not recorded spend. The bounded test stayed below the $3 spending cap, including that conservative reservation.

Research, dataset/harness creation, independent review, and this Codex conversation were one-time preparation and are unmetered here. We make an API-execution comparison, not a complete development-lifecycle token-saving claim. The user's privacy settings were unchanged. Credentials are absent from the artifacts.

## Next version to test

Keep these results as the frozen baseline. Before another held-out run, improve the review policy on separate calibration cases, use code for numerical checks, and give Jev focused changes and supporting spans instead of repeatedly sending the full corpus. Then test multi-step workloads where reused source memory can offset the initial selection cost. Treat each as a new experiment; do not tune this dataset until it appears favorable.

Detailed paired results and uncertainty are in [the analysis](analysis/summary.md), [machine-readable results](analysis/results.json), and [task results](analysis/task_results.csv). Requests, responses, usage ledgers, source data, grader, tests, and reproduction scripts are included in this evidence package.
