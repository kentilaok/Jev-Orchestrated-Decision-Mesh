# Earlier mandatory Sol-high policy: GPT-6 fixture and baseline

**23 September 2026 · Synthetic records · Kenneth Vic A. Caber**

This appendix preserves the **previous** five-unit policy, in which every unit required a Sol-high check. The current CIDM policy returns every worker output to Jev and lets Jev request Sol High only when needed. The recorded request/response files below remain unchanged so the earlier outcome can be independently rechecked.

The task was to report defects per 1,000 **production** items, exclude a trial row, and cite `[records]`. The input had production segments A and B totaling 20 defects in 400 items, plus one excluded trial segment. The exact reference is **50 defects per 1,000 production items**. Both completed runs returned 50 and passed their declared source/scope checks.

The checked run used the fixed five-unit sequence, with a separate Sol-high check and subsequent Jev choice after each unit. The one-call baseline used GPT-6 Sol high with the same original records and a structured final response. Both used the OpenRouter API with an explicit Azure provider route and no provider fallback. The reported charges are API dollars, not ChatGPT subscription credits.

| Observed measure | Checked CIDM | Single Sol high |
|---|---:|---:|
| Provider calls | 23 | 1 |
| Total provider-accounted tokens | 36,663 | 431 |
| Provider-reported cost | $0.012201078 | $0.001726 |
| Sum of API call latencies | 36.311 s | 4.297 s |
| Final value, scope, and citation checks | Pass | Pass |

The checked call inventory was **15 Jev**, **5 Sol-high checker**, and **3 Luna-low worker** requests. Jev consumed 31,700 tokens and $0.001298178; checkers consumed 3,038 tokens and $0.010548; workers consumed 1,925 tokens and $0.0003549. The checkers account for 86.45% of this run's API dollars. The checked path used **85.06×** the tokens and cost **7.07×** as much as the matched one-call baseline on this small task.

## Recheck recorded data

From this directory, run `python -B verify_live.py`. It makes no provider calls. It verifies the SHA-256 inventory, request hashes, response identities, usage linkage, totals, call order, the five accepted units, and the baseline's output checks. From the repository root, `python scripts/audit_network.py research/live-gpt6-fixture/checked/result.json` additionally audits the broker events and post-checker Jev transitions using the saved request files. `SHA256SUMS.txt` covers all evidence files except itself and this explanatory README.

`checked/` and `single-sol/` include the complete saved request, response, event, usage, and result files for the successful synthetic runs. The `attempts/` directory preserves the result records of earlier bounded attempts:

| Attempt | Observed result | Recorded cost | Accounting note |
|---|---|---:|---|
| Checked A | Direct OpenAI provider was excluded by an account zero-retention guardrail; checker HTTP 404; no unit committed | $0.000093534 | Two Jev calls metered; failed checker usage unavailable |
| Checked B | Azure served the models, but Jev selected stop before checking the second unit; one unit committed | $0.002400746 | Seven successful, fully metered calls; prompt policy was then clarified |
| Baseline A | Correct value/scope/citation, but the unit field failed the originally strict literal-format check | $0.002172 | One fully metered call; schema was amended to request the exact unit string |

The completed checked and baseline runs followed those corrections. These are development attempts, not independent task replicates. The account's zero-retention policy was not changed. The saved artifacts contain synthetic records and exclude API keys and authorization headers.

## What this establishes

The live records establish that the specified GPT-6 models, Jev endpoint, Azure route, checked transitions, accounting, and one-call baseline can execute on this fixture. A single paired fixture does **not** estimate performance across websites, coding projects, or other task distributions. The baseline prompt and checked graph differ by design, and latency here is the sum of provider call times rather than a full product user experience. Cost and token ratios describe only these recorded completions. The historical 12-task pilot is a separate GPT-5.6 source-selection design, preserved in the adjacent appendix.
