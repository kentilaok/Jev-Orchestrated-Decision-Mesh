# Handoff — Hermes dispatch adapter, slice 2 (14 October 2026)

**Branch:** `feature/hermes-dispatch-adapter`.
**Parent gate:** [P0-04 Governed Hermes integration](PRODUCTION-REQUIREMENTS-HANDOFF-2026-10-08.md). Second of six slices.
**Evidence level:** offline tests only. No model calls, no live spend.

## 1. What this slice delivers

Thread continuity for the `/v1/chat/completions` endpoint, inferred from the OpenAI stateless message array. Follow-up turns in the same Hermes conversation now share a stable **thread id** and append to a per-thread journal under `runs/threads/{thread_id}.json`.

- `_first_user_content(messages)`: finds the first non-empty user message.
- `_derive_thread_id(messages)`: SHA-256 of that content, first 16 hex chars.
- `_record_thread_turn(thread_id, config, goal, provider, gate_policy)`: creates or appends a journal file with timestamp, goal (≤400 chars), provider, and gate policy.
- `chat_completions` now returns a `cidm` extension field: `{"thread_id": "...", "mode": "validate", "turn": N}`. The thread id is also included in the human-readable summary.
- OpenAI clients that don't look at `cidm` ignore it (unknown fields are allowed).

**Edge case documented, not fixed:** if Hermes compacts conversation history and drops the original first user message, the thread id will shift. This is acceptable for slice 2; slice 6 will decide whether to handle it (e.g. let the client pass an explicit `user` field, or persist the thread id as a header round-trip).

## 2. Code changes

| File | Change |
|---|---|
| `scripts/operator_console.py` | +50 lines. Added `_first_user_content`, `_derive_thread_id`, `_record_thread_turn`; `chat_completions` records the turn and returns a `cidm` extension in the response. |
| `tests/test_openai_chat_endpoint.py` | +60 lines. Six new tests: thread id stability under follow-up turns, thread id change on different first user message, system prompt does not affect thread id, response includes `cidm.thread_id`, journal appends across same-thread calls, different threads write different journals. |

## 3. Verification

| Check | Result |
|---|---|
| Slice tests (unit + HTTP, both suites) | 18/18 pass |
| Full offline suite | 336/336 pass, 1 opt-in Docker skip |
| Regressions on 330-test post-slice-1 baseline | 0 |
| `python -m compileall -q scripts tests` | pass |
| Live model calls | None |

## 4. How to see thread binding locally

```powershell
Set-Location 'D:\Hermes Jev CIDM'
$env:CIDM_API_KEY = 'local-dev-key-change-me'
python scripts/operator_console.py
```

In another shell, send two turns of the same conversation:

```powershell
$body1 = '{"model":"cidm-jev","messages":[{"role":"user","content":"Design the thing"}]}'
$body2 = '{"model":"cidm-jev","messages":[{"role":"user","content":"Design the thing"},{"role":"assistant","content":"..."},{"role":"user","content":"Now estimate cost"}]}'

curl.exe -s -X POST http://127.0.0.1:8765/v1/chat/completions `
  -H 'Content-Type: application/json' `
  -H "Authorization: Bearer $env:CIDM_API_KEY" -d $body1

curl.exe -s -X POST http://127.0.0.1:8765/v1/chat/completions `
  -H 'Content-Type: application/json' `
  -H "Authorization: Bearer $env:CIDM_API_KEY" -d $body2

Get-ChildItem 'D:\Hermes Jev CIDM\runs\threads'
```

The two responses share `cidm.thread_id`. The journal file lists two turns.

## 5. Open items for the next slice

1. **SSE status streaming (slice 3).** Emit `[Jev] routing…`, `[Worker] running…`, `[Validator] accepting…` as `data: {"choices":[{"delta":{"content":"…"}}]}` chunks, then the final content, then `data: [DONE]`. Must set `Accept: text/event-stream` branch in the handler.
2. **In-process broker port.** `validate_broker_request` currently subprocesses. For live streaming in slice 3, we will need to call `NativeTransitionBroker` in-process so status callbacks can fire during the run.
3. **Thread id in Live mode.** When slice 3+ promotes a thread to a live run, bind the CIDM run folder name to `thread-{thread_id}` so recovery can find it.

## 6. Pass/hold decision for this slice

- `scope`: internal milestone, not a release
- `decision`: **PASS as a slice milestone**; branch still not mergeable to `main` (slices 3–6 pending).
- `reviewer`: pending — independent review runs after slice 6 before PR merge.

*CIDM architecture and research by Ken Caber (Kenneth Vic A. Caber).*
