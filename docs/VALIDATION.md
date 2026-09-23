# Validation scope

The GPT-6 skill has **58 passing offline tests** on Python 3.12. The runner requires Python 3.10+ and uses only the standard library. The [historical pilot appendix](../research/historical-pilot/README.md) independently passes **40 tests** and its verifier.

The tests cover one-use approvals, exact-operation binding, gate order, predecessor and policy integrity, Jev-selected Luna/Sol worker routes, default exclusion of Astra, explicit Astra authorization, checker isolation, hard-check rejection, pre-check repair, repair/recheck limits, oversized invalid checker envelopes, and Jev decisions after checker returns. Transport tests mock responses to check model-specific reservations, identity, configuration, usage accounting, reserved Jev follow-up capacity, and sanitized failure logs. The one-call baseline tests cover live-call shape, answer grading, failed-call accounting, and offline simulation. Subprocess tests run without site packages or API credentials.

The included production-record fixture produces **50 defects per 1,000 production items**, excludes trial records, commits five units, and passes the journal audit in offline mode. Its fake decision/checker functions are explicitly marked as simulation. This demonstrates controller behavior; it does not measure live Jev or Sol quality.

The [saved live GPT-6 fixture](../research/live-gpt6-fixture/README.md) completed all five units on Azure via OpenRouter: **15 Jev decisions, 3 Luna-low workers, 5 Sol-high checks, 23 calls total, 36,663 tokens, $0.012201078 reported API cost**. Its final answer and journal audit passed. A one-call GPT-6 Sol-high baseline on the same original record task passed value, scope, exclusion, and citation checks with **431 tokens and $0.001726**. The five-unit path spent **85.06×** the tokens and **7.07×** the API dollars on this fixture.

The evidence bundle also preserves earlier bounded attempts: one checker failed with HTTP 404 because the direct OpenAI endpoint was excluded by an account zero-retention policy; an Azure attempt reached a valid second-unit worker artifact but Jev chose stop before checking it; an initial baseline result had the correct numerical answer and citation but failed an exact unit-string check, so its schema was corrected. Those are disclosed development attempts, not extra successful replicates. The account's privacy policy was not weakened. The successful run and baseline have checksummed request, response, usage, and result records; `research/live-gpt6-fixture/verify_live.py` rechecks them offline.

No general reliability guarantee, token-saving claim, probability calibration claim, or production-readiness claim follows from these results. The earlier 12-task pilot is documented in [BENCHMARKS.md](BENCHMARKS.md); it increased total tokens. Codex-native subscription execution is specified in [EXECUTION-ROUTES.md](EXECUTION-ROUTES.md), but the Python broker does not automatically audit that host workflow. A separate high-effort checker can share errors with the worker.

## Reproduce

```bash
python -m unittest discover -s tests -v
python scripts/network_run.py --offline --task examples/production-records.json --out runs/validation-001
python scripts/audit_network.py runs/validation-001/result.json
python scripts/compare_baseline.py --offline --task examples/production-records.json --out runs/baseline-validation-001
python research/live-gpt6-fixture/verify_live.py
python research/historical-pilot/verify_appendix.py
```

Use a fresh output directory for each attempt. Raw run logs can contain task data; they are excluded from version control by default. The skill contains no training dataset, learned routing checkpoint, or private conversation transcript.
