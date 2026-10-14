# Handoff — Hermes dispatch adapter, slice 3 (14 October 2026)

**Branch:** `feature/hermes-dispatch-adapter`.
**Parent gate:** [P0-04 Governed Hermes integration](PRODUCTION-REQUIREMENTS-HANDOFF-2026-10-08.md). Third of six slices.
**Evidence level:** offline tests only. No model calls.

## 1. What this slice delivers

Server-sent-events streaming for `/v1/chat/completions`. When Hermes sends `"stream": true`, the response is a sequence of OpenAI `chat.completion.chunk` events with intermediate status chunks ("[CIDM] starting", "[CIDM] validating request", "[CIDM] plan ready") followed by the final content, a `finish_reason=stop` closing chunk, and a `data: [DONE]` sentinel. Non-stream requests retain the slice-1 single-object behaviour (regression test enforces this).

- `_prepare_chat_run(payload, config)`: shared broker handshake extracted from `chat_completions`; builds goal/context, validates, records the thread turn, returns the data both the non-stream and stream paths need.
- `chat_completions_stream(payload, config)`: generator yielding SSE-formatted lines.
- `_sse(chunk)`: formats a dict as a `data: ...\n\n` SSE event.
- `Handler._send_sse(generator)`: HTTP responder that sets `text/event-stream`, `Cache-Control: no-store`, `X-Accel-Buffering: no`, and flushes after each event so Hermes sees status in real time.
- `do_POST` detects `payload["stream"] is True` and routes to the streamer; otherwise unchanged.

## 2. Code changes

| File | Change |
|---|---|
| `scripts/operator_console.py` | +50 lines. New `_prepare_chat_run`, `chat_completions_stream`, `_sse`, `Handler._send_sse`. `chat_completions` now delegates its envelope construction through `_prepare_chat_run`. `do_POST` branches on `stream`. |
| `tests/test_openai_chat_endpoint.py` | +50 lines. Six unit tests (SSE format, [DONE] sentinel, status before content, `finish_reason=stop` on closing chunk, shared id/model across chunks, non-stream regression) and one HTTP smoke test (actual `text/event-stream` response end-to-end). |

## 3. Verification

| Check | Result |
|---|---|
| Slice-3 tests | 7/7 pass |
| Full offline suite | 343/343 pass, 1 opt-in Docker skip |
| Regressions on 336-test post-slice-2 baseline | 0 |
| `python -m compileall -q scripts tests` | pass |
| Live model calls | None |

## 4. How to see streaming locally

```powershell
Set-Location 'D:\Hermes Jev CIDM'
$env:CIDM_API_KEY = 'local-dev-key-change-me'
python scripts/operator_console.py
```

```powershell
curl.exe -N -X POST http://127.0.0.1:8765/v1/chat/completions `
  -H 'Content-Type: application/json' `
  -H "Authorization: Bearer $env:CIDM_API_KEY" `
  -d '{"model":"cidm-jev","messages":[{"role":"user","content":"hi"}],"stream":true}'
```

Expect a cascade of `data: {...}` lines ending in `data: [DONE]`.

## 5. Open items for the next slice

1. **Strong-permit approval URL injection (slice 4).** When Jev classifies a request as "strong" (writes, deletes, spend above cap), the stream pauses with an assistant message containing `http://127.0.0.1:8765/approve/{token}` and closes with a `pending` finish reason. The next thread turn resumes if the operator approved in the Console.
2. **Live mode toggle.** All status chunks today describe the validate-only path. Slice 5 will add an opt-in live mode behind a flag; the status text pattern will become `[Jev] ...`, `[Worker] ...`, `[Validator] ...`.
3. **Streaming + in-process broker.** For live status events to fire *during* execution, slices 5+ will need to port `validate_broker_request`'s subprocess to an in-process `NativeTransitionBroker` call so progress callbacks can run.

## 6. Pass/hold decision for this slice

- `scope`: internal milestone, not a release
- `decision`: **PASS pending independent QA on this slice**. Reviewer runs after push.
- `next action`: QA review of slice 3 commit, then slice 4.

*CIDM architecture and research by Ken Caber (Kenneth Vic A. Caber).*
