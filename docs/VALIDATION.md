# Validation scope

The conditional-review and context-bound routing GPT-6 skill has **82 passing offline tests** on Python 3.12. The runners require Python 3.10+ and use only the standard library. The [historical pilot appendix](../research/historical-pilot/README.md) independently passes **40 tests** and its verifier.

The tests cover one-use approvals, exact-operation binding, gate order, predecessor and policy integrity, Jev-selected Luna/Sol worker routes, default exclusion of Astra, explicit Astra authorization, checker isolation, direct forwarding after hard checks, optional review, review recheck/repair, bounded escalation, invalid worker/checker envelopes, final-text value/source/scope checks, and Jev decisions after every five-unit output and requested checker return. The audit detects mutated committed packets. Transport tests mock model-specific reservations, role call caps, the post-response Jev token ceiling, identity, usage accounting, reserved Jev follow-up capacity, and sanitized failure logs. Entry-routing tests cover a conservative broad default, task/context-bound host assertions, a one-worker Luna-low short route, and the restricted Jev menu for broad work. Metrics tests keep unknown usage unknown and avoid invented quality gains. The one-call baseline tests cover live-call shape, answer grading, failed-call accounting, and offline simulation.

The included production-record fixture produces **50 defects per 1,000 production items**, excludes trial records, commits five units, and passes the journal audit in offline mode when no short classification is supplied. Its fake decision/checker functions are explicitly marked as simulation. The default offline adaptive run also selected five units and the journal audit verified five committed post-worker Jev decisions; these are simulated decisions and zero API calls. This demonstrates controller behavior; it does not measure live Jev or Sol quality.

The [live GPT-6 run after final-text hardening](../research/live-gpt6-optional-final/README.md) completed all five units on Azure via OpenRouter: **10 Jev calls, 3 Sol-low worker calls, zero Sol-high checks, 13 calls total, 25,510 tokens, $0.006413654 reported API cost**. Its final answer and journal audit passed. A [first conditional run](../research/live-gpt6-optional-fixture/README.md), before the final-text hardening, had 13 calls, zero checkers, 25,651 tokens, and $0.00312019; Jev selected two Luna-low workers and one Sol-low worker. The [previous mandatory-review trace](../research/live-gpt6-fixture/README.md) had 23 calls, 36,663 tokens, and $0.012201078, including five Sol-high checks. The hardened run cost **47.43% less** than that older policy on this fixture, while costing **3.72×** as much as the correct one-call Sol-high baseline ($0.001726). Different prompts and routes prevent treating these individual differences as causal policy estimates.

The [previous-policy fast-exit evidence](../research/live-gpt6-fast-exit/README.md) contains two live Jev choices on the same fictional task. Both selected exact code with one Jev call and no worker/checker. The compact request used **716 reported tokens and $0.000026964**; its predecessor wording used 889 tokens and $0.00003423. The compact route's final value, scope, and citation checks passed. These are development observations of the earlier entry policy; they do not measure the new Luna-low short branch, semantic classification accuracy, or broad-project savings.

The older evidence bundle also preserves bounded attempts: one checker failed with HTTP 404 because the direct OpenAI endpoint was excluded by an account zero-retention policy; an Azure attempt reached a valid second-unit worker artifact but Jev chose stop before checking it; an initial baseline result had the correct numerical answer and citation but failed an exact unit-string check, so its schema was corrected. Those are disclosed development attempts, not extra successful replicates. The account's privacy policy was not weakened. All three successful five-unit runs have checksummed request, response, usage, and result records with separate offline verifiers. The current audit script reads both protocol versions.

No general reliability guarantee, token-saving claim, probability calibration claim, or production-readiness claim follows from these results. The earlier 12-task pilot is documented in [BENCHMARKS.md](BENCHMARKS.md); it increased total tokens. The bounded runner verifies that a host classification is bound to the task and context hash; it does not judge whether the classification is correct. Codex-native subscription execution is specified in [EXECUTION-ROUTES.md](EXECUTION-ROUTES.md), but the Python broker does not automatically audit that host workflow. A separate high-effort checker can share errors with the worker.

## Reproduce

```bash
python -m unittest discover -s tests -v
python scripts/network_run.py --offline --task examples/production-records.json --out runs/validation-001
python scripts/audit_network.py runs/validation-001/result.json
python scripts/compare_baseline.py --offline --task examples/production-records.json --out runs/baseline-validation-001
python research/live-gpt6-fixture/verify_live.py
python research/live-gpt6-optional-fixture/verify_optional.py
python research/live-gpt6-optional-final/verify_optional.py
python research/live-gpt6-fast-exit/verify_fast_exit.py
python scripts/adaptive_run.py --offline --task examples/production-records.json --out runs/broad-validation-001
python research/historical-pilot/verify_appendix.py
```

Use a fresh output directory for each attempt. Raw run logs can contain task data; they are excluded from version control by default. The skill contains no training dataset, learned routing checkpoint, or private conversation transcript.
