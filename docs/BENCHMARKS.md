# Benchmarks and evidence

**Work in progress.** Main contributor: **Kenneth Vic A. Caber**.

The historical CIDM pilot **did not save total tokens**. It reduced Sol usage and recorded a slightly lower API bill, but added substantial Jev overhead and withheld five answers. These results do not establish efficiency of the current training-free five-unit network.

## Historical selection-and-review pilot

The experiment used 12 held-out synthetic tasks, one paired run per task, and the same `openai/gpt-5.6-sol` model at `medium` effort in both arms. Both used the same Azure endpoint through OpenRouter. CIDM additionally used `typesafe/jev-1.13`.

The baseline received the full source corpus and could repair structural errors. CIDM selected source text through Jev, requested worker metadata, reviewed answers through Jev, and could request a semantic correction. This measured selection **plus review and correction policy**, not selection alone. It did not use a Sol-high checker after each of five units.

| Evaluation metric | Sol alone | Historical CIDM + same Sol |
| --- | ---: | ---: |
| All provider-accounted tokens | 34,942 | 131,388 |
| Sol tokens | 34,942 | 25,030 |
| Jev tokens | 0 | 106,358 |
| Recorded API cost | $0.255236 | $0.230693 |
| Sum of task elapsed times | 42.248 seconds | 68.923 seconds |
| API calls | 12 | 40 |
| Candidates with all answer values correct | 12/12 | 12/12 |
| Candidates passing frozen value/citation/status checks | 9/12 | 11/12 |
| Answers released | 12/12 | 7/12 |
| Released answers passing the frozen checks | 9/12 | 7/12 |

Observed changes: **276.0% more total tokens**, **28.4% fewer Sol tokens**, **9.6% lower API cost**, and **63.1% longer summed task time**. Lower-priced Jev processing explains how cost could fall while token consumption grew.

## Quality and uncertainty

All candidate answer values were correct on this sample. The primary acceptance rule also required specified citations for each field and the correct complete/partial status. CIDM withheld five candidates: four passed even that strict rubric; the fifth had correct values but incomplete citations under the frozen rules. A checker or release gate can therefore reduce useful answer coverage.

A separate blind source audit confirmed the expected values and identified unnecessarily strict citation requirements in parts of the grader. The preregistered grades were preserved. A citation failure must not be described as an incorrect factual answer without examining the failed criterion.

The paired stratified bootstrap interval was **215.5%–338.8% more tokens** at 95% confidence. The corresponding interval for cost savings was **−29.3% to +49.1%**. The small observed bill reduction is not a robust general cost-saving result.

With 12 synthetic tasks and one replicate, this pilot was not powered to demonstrate a five-percentage-point quality noninferiority margin. It does not establish performance on coding projects, production workloads, or arbitrary multi-step delegation.

## Accounting boundary

All 52 evaluation calls supplied measured input, output, and cost. Reasoning tokens were already included in output tokens and were not counted twice. Jev output tokens were counted even when their monetary price was zero. Different provider tokenizers make the combined count operational accounting, not a universal measure of compute or information.

The comparison covers API execution. One-time research, dataset and harness creation, and review were outside that boundary. Some earlier setup attempts lacked usage counters; unknowns were not treated as zero. The pilot therefore does not establish complete development-lifecycle savings.

This document summarizes the historical report. The public repository does not include private request/response logs or claim that this summary alone reproduces the original experiment. A reproducible public benchmark needs a versioned dataset, grader, configuration, analysis code, and appropriately redacted usage evidence.

## Current training-free path

The present design requires Jev authorization, a separate Sol-high check, and a subsequent Jev option decision for every computational unit. These additional checks have a cost. The historical figures above are not measurements of that architecture, and successful integration is not a comparative benchmark.

An earlier trained numeric-router experiment was **discarded** following the design correction. Its checkpoint, learned advisor, and synthetic classification accuracy are not part of the published path or evidence of current network performance. Neural-network concepts are architectural inspiration only.

Before claiming a better or cheaper solver:

1. Freeze task strata, sources, acceptance criteria, model IDs/efforts, budgets, and the analysis plan before evaluation.
2. Compare against a capable single-model baseline and a matched graph without mandatory high-effort checkers.
3. Count every worker, checker, Jev call, repair, refusal, failure, and relevant tool operation. Report missing counters explicitly.
4. Report correctness, evidence support, release coverage, tokens, cost, and latency separately; retain unsuccessful runs.
5. Use paired held-out tasks and uncertainty intervals. Do not tune on evaluation outcomes or infer success from model self-scores.

No current result supports describing CIDM as foolproof, universally more efficient, or a trained Transformer.
