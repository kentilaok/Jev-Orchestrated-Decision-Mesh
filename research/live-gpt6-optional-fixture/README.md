# Conditional Sol-high review: recorded GPT-6 fixture

**23 September 2026 · Synthetic production records · Kenneth Vic A. Caber**

This is the first conditional-review integration run. The final-output text validator was strengthened afterward; the [later saved run](../live-gpt6-optional-final/README.md) exercises that stricter validation. The original request, response, and result records here remain unchanged.

This is one live OpenRouter API run of CIDM's revised five-unit controller. Jev authorized each unit and reviewed **every unit output**. It forwarded all five units after the executable checks passed. Jev did not request a Sol-high review on this task, so the run made **zero checker calls**. The final answer correctly reported **50 defects per 1,000 production items**, excluded the trial row, and cited `[records]`.

| Observed measure | Conditional-review run |
|---|---:|
| Jev decisions | 10 |
| Generative workers | 3: Luna low, Sol low, Luna low |
| Sol-high checker calls | 0 |
| Total provider calls | 13 |
| Provider-accounted tokens | 25,651 |
| Provider-reported API cost | $0.00312019 |
| Five committed units and post-worker Jev decisions | 5 each |

Jev consumed 23,812 tokens and $0.00097209; workers consumed 1,839 tokens and $0.00214810. This observed run used **30.04% fewer tokens and cost 74.43% less** than the [earlier mandatory-check run](../live-gpt6-fixture/README.md) on the same synthetic task. The earlier run used a different policy and chose different worker routes, so this pair does not isolate the causal effect of removing the checkers. Against the separately recorded one-call Sol-high baseline (431 tokens, $0.001726), the conditional run still used **59.52×** as many tokens and cost **1.81×** as much. All three final answers passed their stated task checks.

## Reproduce the audit without API access

From this directory, run `python -B verify_optional.py`. It checks the SHA-256 inventory, every saved request hash, response model/provider, reported usage, worker-to-Jev call order, five accepted units, and final answer. From the repository root, run `python scripts/audit_network.py research/live-gpt6-optional-fixture/result.json` to check broker authorization and commit order. Neither command sends an API request.

This folder includes all saved request, response, event, journal, usage, and result files for the run. The records use fictional data and contain no API key or authorization header. `SHA256SUMS.txt` covers every evidence file except itself and this README. The current account's zero-retention guardrail remained enabled; the explicit Azure provider route succeeded.

This one fixture verifies that the **optional-check path can execute without Sol High** and still keep Jev at every observable output boundary. It does not establish quality or cost for open-ended projects. The optional Sol-high branch is covered by offline controller and transport tests; this particular live run did not invoke it.
