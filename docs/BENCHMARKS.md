# Benchmarks and evidence

**Main contributor: Kenneth Vic A. Caber.**

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

The [historical reproducibility appendix](../research/historical-pilot/README.md) includes the synthetic task dataset and gold labels, frozen manifest, original harness and grader, an accounting amendment, saved call ledger, all 52 evaluation request/response pairs, regenerated analysis, checksums, and an offline verifier. The saved analysis reproduces byte-for-byte without API access. A new external model run can produce different answers and usage; the record is not an independently signed provider attestation.

## Current training-free path

The revised entry policy sends broad, multi-step, or uncertain inputs to five units by default. Within that graph, Jev acts before a unit and after **every completed unit output**; it can forward after executable checks or request Sol High for extra review. Only an explicitly short, self-contained input takes one Luna-low worker and hard validation. This new entry policy has no live matched efficiency result yet. In the [hardened GPT-6 synthetic fixture](../research/live-gpt6-optional-final/README.md), five units completed with **zero checker calls, 25,510 tokens, and $0.006413654** across 13 calls. A [first conditional run](../research/live-gpt6-optional-fixture/README.md) also skipped checkers and cost $0.00312019 with different worker choices. The [earlier mandatory-check fixture](../research/live-gpt6-fixture/README.md) used **36,663 tokens and $0.012201078** across 23 calls. A correct one-call Sol-high baseline used **431 tokens and $0.001726**. The hardened path cost **47.43% less than the old policy on this fixture**, while still costing **3.72×** the one-call baseline. Different prompts and worker routes prevent causal attribution of the entire difference to checker policy. None of these small runs estimates performance on broad projects. The historical GPT-5.6 pilot above is a separate architecture.

An earlier trained numeric-router experiment was **discarded** following the design correction. Its checkpoint, learned advisor, and synthetic classification accuracy are not part of the published path or evidence of current network performance. Neural-network concepts are architectural inspiration only.

Before claiming a better or cheaper solver:

1. Freeze task strata, sources, acceptance criteria, model IDs/efforts, budgets, and the analysis plan before evaluation.
2. Compare against a capable single-model baseline, the historical mandatory-review policy, and the current conditional-review graph under frozen prompts and acceptance criteria.
3. Count every worker, checker, Jev call, repair, refusal, failure, and relevant tool operation. Report missing counters explicitly.
4. Report correctness, evidence support, release coverage, tokens, cost, and latency separately; retain unsuccessful runs.
5. Use paired held-out tasks and uncertainty intervals. Do not tune on evaluation outcomes or infer success from model self-scores.

No current result supports describing CIDM as foolproof, universally more efficient, or a trained Transformer.
