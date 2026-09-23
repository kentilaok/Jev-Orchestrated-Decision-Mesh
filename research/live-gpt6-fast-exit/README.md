# Jev fast-exit gate: two saved API calls

**23 September 2026 · Synthetic production records · Kenneth Vic A. Caber**

These are two development runs of one compact Jev topology decision on the same three-row arithmetic fixture. Both chose `deterministic`, after which exact code calculated **50 defects per 1,000 production items**, excluded the trial row, and cited `[records]`. Each run made one Jev call and **zero worker/checker calls**. A standalone yes/no or one-step question would not invoke CIDM; this small fixture exists to test the gate inside the skill.

| Observed measure | Initial wording | Compact wording |
|---|---:|---:|
| Jev input + output tokens | 889 | 716 |
| Provider-reported Jev charge | $0.00003423 | $0.000026964 |
| Worker calls | 0 | 0 |
| Output value/scope/citation checks | Passed | Passed |

The compact gate used **173 fewer Jev tokens** on this one repeated task. Against the saved one-call Sol-high baseline (431 tokens, $0.001726), the compact gate plus exact code used **1.66×** as many provider tokens and **1.56%** of the API dollars. It selected a different kind of solution, so this comparison does not establish model-to-model quality parity for open tasks. The previous five-unit conditional-review runs used 25,651 and 25,510 tokens on this fixture; this fast exit avoids those repeated decisions when exact code suffices.

From this directory, run `python -B verify_fast_exit.py`. It checks the checksum inventory, request hash, returned Jev model/provider, usage totals, selected route, answer checks, and task identity against the saved baseline. It makes no API calls. `initial/` and `compact/` contain the complete saved synthetic request, response, event, usage, and result files. `SHA256SUMS.txt` covers all evidence files except itself and this README. The files contain no API key or authorization header.

The gate produced **716 tokens**, not a guaranteed per-request limit. The configuration can cap future Jev calls and reject a decision that crosses its reported token ceiling, but upstream usage may already have been billed. No project-scale token or quality saving follows from two development runs on one exact-arithmetic fixture.
