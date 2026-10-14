# Stage 5 handoff — bounded retrieval and resource-governed Qwen concurrency

**Date:** 9 October 2026. **Status:** code and offline tests committed; **no 4 GB GPU benchmark performed**.

## Built

- `scripts/retrieval.py`: dense ranking in the normal `LocalHybridIndex.search` hot path now considers only a bounded indexed FTS/BM25 shortlist; no linear full-vector Python scoring by default. `bounded_dense=False` explicitly retains prior full-namespace dense search for recall benchmarking. The result reports its strategy.
- `scripts/arsenal_registry.py`: when FTS5 is unavailable, skill/experience linear fallback scans fail closed above 5,000 records instead of silently degrading with unbounded database scans.
- `scripts/local_resource_governor.py`: default physical Qwen concurrency `1`; `2` requires explicit opt-in and a minimum verified free-VRAM reading from `nvidia-smi` (default 1,536 MiB). When VRAM cannot be measured, parallel execution remains off.
- `scripts/local_lane_scheduler.py`, `scripts/local_continuity_pipeline.py`: enforce physical parallelism guard; separate A/B contexts and permits retained.
- `tests/test_local_qwen_stage5.py`: bounded SQL shortlist and concurrent-memory opt-in tests.

## Important trade-off

A lexical shortlist followed by dense ranking is fast and predictable but can **miss semantically similar records with no lexical term overlap**. This is not a general vector ANN replacement. Before using with very large mixed-language corpora, benchmark recall; evaluate Qdrant/ANN as a separate retrieval path if needed. Do not promise that millions of SOPs have constant retrieval latency.

## Windows verification

```powershell
cd 'D:\Hermes Jev CIDM'
git pull --ff-only origin feature/local-continuity-split-context-plan
py -3.11 -m unittest discover -s tests -p 'test_local_qwen_stage5.py' -v
nvidia-smi --query-gpu=memory.free --format=csv,noheader,nounits
ollama ps
```

If GPU availability is inadequate, **use serial inference with two logical specialists**. Physical parallel runs require the opt-in `--parallel 2 --allow-parallel-local` on the CLI and sufficient free VRAM; that is an experimental threshold, not a measured speedup.

**Next:** Stage 6 integration review/evaluation/reporting; production claims remain blocked pending green CI and real-provider acceptance.
