# Validation scope

This training-free publication candidate has **43 passing offline tests** on Python 3.12. The runner requires Python 3.10+ and uses only the standard library.

The tests cover one-use approvals, exact-operation binding, gate order, predecessor and policy integrity, checker isolation, hard-check rejection, repair/recheck limits, oversized invalid checker envelopes, and Jev decisions after checker returns. Transport tests mock responses to check identity, configuration, usage accounting, cost reservations, reserved Jev follow-up capacity, and sanitized failure logs. A subprocess test runs the offline CLI without site packages or API credentials.

The included production-record fixture produces **50 defects per 1,000 production items**, excludes trial records, commits five units, and passes the journal audit in offline mode. Its fake decision/checker functions are explicitly marked as simulation. This demonstrates controller behavior; it does not measure live Jev or Sol quality.

The refactored configurable adapter has **not received a new live end-to-end evaluation** for this publication. Previous prototype live runs do not validate every behavior of the refactored release. Model availability, account policy, provider usage formats, and latency must be checked in a bounded live trial before deployment.

No general reliability guarantee, token-saving claim, probability calibration claim, or production-readiness claim follows from these tests. The earlier paired pilot is documented in [BENCHMARKS.md](BENCHMARKS.md); it increased total tokens. A separate high-effort checker can share errors with the worker.

## Reproduce

```bash
python -m unittest discover -s tests -v
python scripts/network_run.py --offline --task examples/production-records.json --out runs/validation-001
python scripts/audit_network.py runs/validation-001/result.json
```

Use a fresh output directory for each attempt. Raw run logs can contain task data; they are excluded from version control by default. This repository contains no training dataset, learned routing checkpoint, or private conversation transcript.
