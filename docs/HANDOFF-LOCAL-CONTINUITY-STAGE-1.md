# Stage 1 handoff — Local Qwen provider and read-only continuity pilot

**Date:** 9 October 2026. **Branch:** `feature/local-continuity-split-context-plan`. **Status:** implementation committed, **CI/local Ollama run not independently verified**.

## Built

- `scripts/ollama_provider.py`: bounded, loopback-only stdlib Ollama provider implementing existing `FrontierProvider` run/usage/cancel/permit protocol. Exact model ID and pre-run tag digest verification, no tool instructions or tool calls, JSON-schema postvalidation, bounded request/response, strict model-served name, token counts when provided.
- `scripts/local_qwen_run.py`: read-only CLI for **local-only** proposals; `--live-local` required to actually call the local model. `preview` makes **zero** model calls.
- `tests/test_local_qwen_stage1.py`: mock transport tests for isolation, identity, schema, usage, permits and loopback.
- Outputs are `unverified_proposal`, **not** a checked Jev final result. User or deterministic evaluator must validate before accepting any work.

## Windows commands (PowerShell)

```powershell
cd 'D:\Hermes Jev CIDM'
git switch feature/local-continuity-split-context-plan
git pull --ff-only origin feature/local-continuity-split-context-plan
py -3.11 -m unittest discover -s tests -p 'test_local_qwen_stage1.py' -v
ollama list
ollama ps
# Identify the exact installed tag and, for production safety, the actual digest from your local model listing.
py -3.11 scripts/local_qwen_run.py --model 'YOUR_EXACT_INSTALLED_TAG' --prompt 'Summarise this fictional test.'
# Only when the local model is installed and running:
py -3.11 scripts/local_qwen_run.py --live-local --model 'YOUR_EXACT_INSTALLED_TAG' --prompt 'Summarise this fictional test.'
```

A real provider response can be unverified or uncertain; this is expected. Stage 1 does not route inside the existing Jev broker, does not change the Operator Console, does not provide automatic quota fallback or independent Agents A/B, and does not prove any quality/latency/cost improvement.

## Caveats and next stage

- The model digest is checked against local `/api/tags` immediately before calling inference; Ollama's chat response does **not independently attest** the served weight digest. Protect the local service from malicious modification and use `--digest` in production tests.
- Cancelling local HTTP is best effort; shared provider adapter concurrency must remain 1 until scheduling is implemented.
- This is an intentional **low-risk operator-authorised read-only worker**; Jev permits and production task-specific acceptance are future integration gates.
- **Next:** Stage 2 separated A direct SOP / B complementary skill + lesson packages and bounded one-model scheduler.

**Verification gate:** run test suite on your Windows machine and record successful results; do not infer green CI from the existence of tests.
