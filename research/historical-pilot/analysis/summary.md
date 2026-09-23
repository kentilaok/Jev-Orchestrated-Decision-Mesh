# CIDM versus fixed Sol: bounded pilot

This is a 12-task evaluation pilot with one paired replicate per task, stratified into three groups of four. Two development tasks are accounted for separately. It is not proof of population superiority or quality equivalence.

A is the fixed Sol medium baseline with full source context. B is a bounded CIDM source-selection and review prototype using the same Sol medium worker, with Jev review and bounded retry. It is not the full adaptive recursive multi-model graph. B includes every recorded Jev and worker call, including failed attempts. Independent hidden-gold grading scores the candidate actually released; withheld and missing outputs score zero. Raw candidate grades expose over-rejection.

Routing and release use declared heuristics and uncalibrated self-assessments. No success threshold is fitted to these evaluation results.

Analysis amendment: terminal failed, rejected, and partial outcomes retain all measured consumption and remain in paired comparisons. Only incomplete measurement or call coverage blocks a full consumption result. Correct null answers with expected partial status can pass independent grading. See amendment.md for the frozen-analyzer correction.

Runtime orchestration is deterministic Python; there is no hidden host-model generation during the measured pilot. Dataset, prompt, harness, and analysis creation overhead is unmetered and excluded. These results make no full-lifecycle efficiency claim.

## Evaluation

Tasks: 12. Failed attempts retained: 0.

| Arm | Recorded / scheduled | Status complete / partial / failed | Released | Served passes | Raw passes / scheduled | Correct withheld | Total tokens | Recorded cost |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| A | 12/12 | 10 / 2 / 0 | 12 | 9/12 | 9/12 | 0 | 34,942 | 0.255236 |
| B | 12/12 | 7 / 0 / 5 | 7 | 7/12 | 11/12 | 4 | 131,388 | 0.230693 |

Full token savings, 1 − sum(B)/sum(A): -276.0%; 95% interval [-338.8%, -215.5%].
Full cost savings, 1 − sum(B)/sum(A): 9.6%; 95% interval [-29.3%, 49.1%].

Paired served task-pass difference (B − A): -16.7%; conservative 95% interval [-52.5%, 29.1%]. Discordant pairs: A only 2; B only 0.

### By stratum

| Stratum | Arm | Recorded / scheduled | Served passes | Correct withheld | Tokens | Cost |
|---|---|---:|---:|---:|---:|---:|
| cross_document | A | 4/4 | 1/4 | 0 | 16,107 | 0.121791 |
| cross_document | B | 4/4 | 1/4 | 2 | 70,285 | 0.162181 |
| noisy_retrieval | A | 4/4 | 4/4 | 0 | 16,482 | 0.109980 |
| noisy_retrieval | B | 4/4 | 3/4 | 1 | 48,858 | 0.035869 |
| short_direct | A | 4/4 | 4/4 | 0 | 2,353 | 0.023465 |
| short_direct | B | 4/4 | 3/4 | 1 | 12,245 | 0.032643 |

### Call and model inventory

| Arm | Role | Requested model | Returned model | Calls | Failed | Input | Output | Total | Reasoning subset | Cached subset | Cost |
|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| A | worker | openai/gpt-5.6-sol | openai/gpt-5.6-sol | 12 | 0 | 33,290 | 1,652 | 34,942 | 504 | 0 | 0.255236 |
| B | worker | openai/gpt-5.6-sol | openai/gpt-5.6-sol | 14 | 0 | 21,819 | 3,211 | 25,030 | 881 | 0 | 0.226467 |
| B | jev | typesafe/jev-1.13 | typesafe/jev-1.13-20260917 | 26 | 0 | 100,607 | 5,751 | 106,358 | 0 known; 26/26 unknown | 0 known; 26/26 unknown | 0.004225 |

## Development

Tasks: 2. Failed attempts retained: 0.

| Arm | Recorded / scheduled | Status complete / partial / failed | Released | Served passes | Raw passes / scheduled | Correct withheld | Total tokens | Recorded cost |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| A | 2/2 | 1 / 1 / 0 | 2 | 2/2 | 2/2 | 0 | 3,750 | 0.027245 |
| B | 2/2 | 1 / 1 / 0 | 2 | 2/2 | 2/2 | 0 | 12,852 | 0.015110 |

Full token savings, 1 − sum(B)/sum(A): -242.7%; 95% interval [-242.7%, -242.7%].
Full cost savings, 1 − sum(B)/sum(A): 44.5%; 95% interval [44.5%, 44.5%].

Paired served task-pass difference (B − A): 0.0%; conservative 95% interval [-88.8%, 88.8%]. Discordant pairs: A only 0; B only 0.

### By stratum

| Stratum | Arm | Recorded / scheduled | Served passes | Correct withheld | Tokens | Cost |
|---|---|---:|---:|---:|---:|---:|
| cross_document | A | 1/1 | 1/1 | 0 | 3,338 | 0.024160 |
| cross_document | B | 1/1 | 1/1 | 0 | 10,204 | 0.009430 |
| short_direct | A | 1/1 | 1/1 | 0 | 412 | 0.003085 |
| short_direct | B | 1/1 | 1/1 | 0 | 2,648 | 0.005680 |

### Call and model inventory

| Arm | Role | Requested model | Returned model | Calls | Failed | Input | Output | Total | Reasoning subset | Cached subset | Cost |
|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| A | worker | openai/gpt-5.6-sol | openai/gpt-5.6-sol | 2 | 0 | 3,570 | 180 | 3,750 | 66 | 0 | 0.027245 |
| B | worker | openai/gpt-5.6-sol | openai/gpt-5.6-sol | 2 | 0 | 1,543 | 232 | 1,775 | 0 | 0 | 0.014675 |
| B | jev | typesafe/jev-1.13 | typesafe/jev-1.13-20260917 | 4 | 0 | 10,368 | 709 | 11,077 | 0 known; 4/4 unknown | 0 known; 4/4 unknown | 0.000435 |

## Accounting and uncertainty

Total tokens use the provider-reported total when available, otherwise input plus output. Reasoning tokens are already part of output; cached input is already part of input. Neither is added a second time. Null usage is unknown, including null Jev output, and is never silently treated as zero. Authentication failures remain in the ledger and scheduled denominator.

Savings intervals use a paired task-cluster percentile bootstrap, resampling within each stratum, with seed 1729 and 10,000 draws. All calls belonging to a task move together. A degenerate bootstrap interval does not guarantee future outcomes. Quality intervals project simultaneous Bonferroni-adjusted exact binomial bounds on the two paired discordance probabilities; all-success outcomes retain uncertainty.

Cost is admissible only when explicit billing covers every event and the schedule is complete. No price table is inferred. Raw billed cost may differ because of caching, model prices, or billing terms. Development is displayed separately and never amortized into evaluation savings. No prompts, thresholds, tasks, or accepted outcomes are adjusted by this analysis.

Machine-readable details: `results.json`; paired task audit: `task_results.csv`.
