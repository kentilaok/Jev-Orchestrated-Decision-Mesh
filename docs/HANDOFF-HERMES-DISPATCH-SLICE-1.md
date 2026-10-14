# Handoff — Hermes dispatch adapter, slice 1 (14 October 2026)

**Branch:** `feature/hermes-dispatch-adapter`, based on `main` at `9fbf384`.
**Slice commit:** `a86ca59`.
**Parent gate:** [P0-04 Governed Hermes integration](PRODUCTION-REQUIREMENTS-HANDOFF-2026-10-08.md). This slice does not close P0-04; it lands the first of six slices.
**Evidence level:** offline tests only. **No model calls, no live spend.**

## 1. What this slice delivers

A loopback `POST /v1/chat/completions` endpoint on the Operator Console that speaks the OpenAI chat-completions shape. Hermes 0.21.5 can register this as a `custom provider` and route a model (e.g. `cidm-jev`) through it with zero code changes on the Hermes side.

**In this slice:**
- OpenAI-shape envelope (`id`, `object`, `created`, `model`, `choices`, `usage`).
- Bearer-token auth via the `CIDM_API_KEY` environment variable (fail-closed when unset).
- Loopback-only Host guard, mirroring the existing Console protections.
- `--validate-only` broker path: the response summarises the plan but **no worker, Jev, or checker call is made**.
- Model whitelist (`cidm-jev` only).

**Deliberately out of scope** (deferred to later slices):
- Thread continuity (slice 2).
- SSE status streaming (slice 3).
- Strong-permit approval URL injection (slice 4).
- `config.yaml` provider entry on the Hermes side (slice 5).
- Adversarial bypass pass + docs (slice 6).

## 2. Code changes

| File | Change |
|---|---|
| `scripts/operator_console.py` | +120 lines. Added `CHAT_MODELS`, `_messages_to_task`, `chat_completions`, `_openai_guard`, and a short-circuit in `do_POST` for `/v1/chat/completions`. Existing `/api/*` routes are untouched. |
| `tests/test_openai_chat_endpoint.py` | New. 12 tests: 5 unit (envelope shape, usage block, model whitelist, empty/missing messages, validate-only marker) + 7 HTTP (missing/wrong bearer, cross-origin Host, valid bearer, bad payload, no-CSRF-header requirement for OpenAI route, regression that `/api/*` still enforces the CSRF header). |

## 3. Verification

| Check | Result |
|---|---|
| New slice tests | 12/12 pass |
| Full offline suite (`python -m unittest discover -s tests`) | 330/330 pass, 1 opt-in Docker skip |
| Regressions on 318-test baseline | 0 |
| `python -m compileall -q scripts tests` | pass |
| Live model calls | None |

## 4. How to try it locally

```powershell
Set-Location 'D:\Hermes Jev CIDM'
$env:CIDM_API_KEY = 'local-dev-key-change-me'
python scripts/operator_console.py
```

Then from another shell:

```powershell
curl.exe -X POST http://127.0.0.1:8765/v1/chat/completions `
  -H 'Content-Type: application/json' `
  -H "Authorization: Bearer $env:CIDM_API_KEY" `
  -d '{"model":"cidm-jev","messages":[{"role":"user","content":"hello"}]}'
```

Expected: a JSON `chat.completion` envelope with an assistant message starting with `[CIDM validate]`.

## 5. Open items for the next slice

1. **Thread ID derivation (slice 2).** OpenAI's API is stateless; "same Hermes thread" is inferred by hashing the first user message. Journal lives at `runs/threads/{thread_id}.json`.
2. **Thread edge case.** If Hermes compacts the context and drops the original first user message, continuity breaks. Document in slice 6; do not try to fix in slice 2.
3. **`CIDM_API_KEY` bootstrap.** Operator must set the env var before starting the Console. A later slice could auto-generate and persist a key at `~/.jev/cidm-api-key` on first start.

## 6. Pass/hold decision for this slice

- `release_commit`: `a86ca59`
- `scope`: internal milestone, not a release
- `decision`: **PASS as a slice milestone**; branch not yet mergeable to `main` (further slices required for P0-04).
- `reviewer`: pending — independent review runs after slice 6 before PR merge.

*CIDM architecture and research by Ken Caber (Kenneth Vic A. Caber); OpenAI chat-completions schema is used only as a wire protocol, not as a vendor dependency.*
