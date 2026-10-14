# Stage 2 handoff — split-context Qwen specialist lanes

**Date:** 9 October 2026. **Status:** code and mocked offline tests committed; **not live benchmarked**.

## Built

- `scripts/split_context_dispatch.py`: freeze task/scope/success criteria, independently query direct A SOP + evidence lessons and complementary B skill/lessons, reject revoked/untrusted SOP loading, recheck skill hashes, enforce package-size limits, and record separate context-package hashes. B does **not** see A's private SOP or proposed answer in its first prompt.
- `scripts/local_lane_scheduler.py`: launch at most two separate read-only Qwen sessions with one permit and workspace per lane. Default `max_parallel=1` serial inference for 4 GB GPU; `max_parallel=2` opt-in experiment, not performance-certified.
- `tests/test_local_qwen_stage2.py`: mock dual-lane package isolation, mismatched snapshot, revoked skill, tampered file, distinct permits, bounded queue.
- No physical GPU speedup or quality claim is made.

## Usage and boundaries

Existing admitted skills must be indexed in `~/.jev/arsenal/arsenal.db`; absent admissions the system must **not** promote discovered skill prose to trusted executable procedure. A/B are *proposal generators only*; the validator/arbiter and learning systems are next stages.

To inspect tests on Windows:
```powershell
cd 'D:\Hermes Jev CIDM'
git pull --ff-only origin feature/local-continuity-split-context-plan
py -3.11 -m unittest discover -s tests -p 'test_local_qwen_stage2.py' -v
```

**Follow-up before production:** recheck metadata validity and access-control filtering of experience lessons, benchmark queue and same-weight concurrency on the real machine; ensure no dishonest claim of context independence merely from different prompt hashes.

**Next stage:** structured disagreement analysis, one-writer observation ledger and independently reviewed promotion.
