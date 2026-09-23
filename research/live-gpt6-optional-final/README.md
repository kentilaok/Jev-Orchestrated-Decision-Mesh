# Conditional-review GPT-6 run after output validation hardening

**23 September 2026 · Synthetic production records · Kenneth Vic A. Caber**

This saved live run used CIDM's five-unit protocol with Jev after every unit output. The final-output validator required the correct rate, production scope, trial exclusion, and `[records]` citation in the user-facing text as well as the structured data. Jev forwarded all five units after their executable checks passed. It did not request Sol High.

| Observed measure | This run |
|---|---:|
| Jev calls | 10 |
| Worker calls | 3 GPT-6 Sol low |
| Sol-high checker calls | 0 |
| Total provider calls | 13 |
| Provider-accounted tokens | 25,510 |
| Provider-reported API charge | $0.006413654 |
| Sum of API call latencies | 13.499 s |
| Accepted units and post-worker Jev decisions | 5 each |

Jev consumed 23,752 tokens and $0.000969654; workers consumed 1,758 tokens and $0.005444. The final answer reported **50 defects per 1,000 production items**, excluded trial records, and cited the original synthetic `[records]` source.

The [previous conditional run](../live-gpt6-optional-fixture/README.md) selected Luna low, Sol low, and Luna low, and cost $0.00312019. This run selected Sol low three times and cost $0.006413654. Both avoided checker calls; their different worker selections show variability even on the same tiny task. Relative to the [older mandatory-review run](../live-gpt6-fixture/README.md), this run used **30.42% fewer tokens and cost 47.43% less**. Relative to the separately recorded one-call Sol-high baseline, it still used **59.19×** as many tokens and cost **3.72×** as much. These are individual observations with changed policies and prompts, not estimates of causal checker savings or broad-project performance.

From this directory, run `python -B verify_optional.py` to recheck saved checksums, request hashes, model/provider responses, call usage, worker-to-Jev order, committed units, and final value. From the repository root, run `python scripts/audit_network.py research/live-gpt6-optional-final/result.json` to check the current broker audit. Neither command sends an API request. The records contain fictional task data and no API key or authorization header. `SHA256SUMS.txt` covers every evidence file except itself and this README.

The optional Sol-high branch was exercised by offline tests. This specific live run demonstrates Jev-authorized direct forwarding after hard checks and does not measure the quality of Jev's choice to skip extra review on open-ended tasks.
