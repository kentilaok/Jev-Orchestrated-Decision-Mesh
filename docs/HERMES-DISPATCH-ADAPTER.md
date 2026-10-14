# Hermes Dispatch Adapter

**Status:** experimental; closes P0-04 "Governed Hermes integration" at the broker-V1 scope. Live frontier execution is still gated by P0-03.

Routes a Hermes chat session through CIDM so Jev gates every turn: decision, permit, worker, validator, acceptance. Hermes stays the GUI and conversation host; CIDM owns authorisation and audit.

## 1. Architecture

```
Hermes chat (user types)
        │ POST /v1/chat/completions
        ▼
127.0.0.1:8765  (Operator Console / CIDM broker)
        │ Auth: Bearer $CIDM_API_KEY
        │ Loopback-only Host
        ▼
_prepare_chat_run()
  • _messages_to_task      (last user msg → goal, prior → context)
  • _derive_thread_id      (sha256 of first user msg, 16 hex)
  • _record_thread_turn    (atomic append to runs/threads/{id}.json)
  • _classify_strength     (destructive keywords → strong)
        │
        ├── normal → validate_broker_request()  → final content
        └── strong → _create_approval_token()   → approval URL
        │
        ▼
chat_completions (non-stream)  |  chat_completions_stream (SSE)
        │                              │
        ▼                              ▼
OpenAI chat.completion JSON    text/event-stream:
                               data: {role:"assistant"}
                               data: [CIDM] starting …
                               data: [CIDM] validating …
                               data: [CIDM] plan ready
                               data: <final content>
                               data: {finish_reason:"stop"}
                               data: [DONE]
```

Everything hangs off a single loopback port (8765) with two guards: bearer-token auth for the OpenAI route and the existing Console-CSRF header for `/api/*` routes.

## 2. Install

```powershell
Set-Location 'D:\Hermes Jev CIDM'
python scripts/install_hermes_cidm_provider.py --dry-run
python scripts/install_hermes_cidm_provider.py
```

The installer backs up `%LOCALAPPDATA%\hermes\config.yaml` to `config.yaml.bak-cidm-<timestamp>` and appends a marked block:

```yaml
# BEGIN cidm-provider (managed by install_hermes_cidm_provider.py)
providers:
  cidm:
    base_url: "http://127.0.0.1:8765/v1"
    key_env: "CIDM_API_KEY"
    api_mode: chat_completions
    model: cidm-jev
    streaming: true
# END cidm-provider
```

Re-running the installer replaces the block in place. If a user already has an active top-level `providers:` block, the installer refuses and prints the exact text to add manually.

## 3. Run

Terminal A — start the CIDM broker:

```powershell
Set-Location 'D:\Hermes Jev CIDM'
$env:CIDM_API_KEY = 'your-local-key'
python scripts/operator_console.py
```

Terminal B — Hermes session:

```powershell
$env:CIDM_API_KEY = 'your-local-key'
hermes chat --model cidm-jev
```

Both processes must see the same `CIDM_API_KEY`. Without it the broker fails closed with HTTP 401.

## 4. Auth and transport

| Element | Setting |
|---|---|
| Address | `127.0.0.1:8765` only. DNS-rebinding guard: non-loopback `Host` → 403. |
| OpenAI route auth | `Authorization: Bearer $CIDM_API_KEY`. Missing or wrong → 401. |
| Console route auth | `X-CIDM-Console: 1` header + same-origin `Origin`. Operator actions only. |
| Content type | `application/json` required on POST. |
| Streaming | `text/event-stream` with `Cache-Control: no-store` and `X-Accel-Buffering: no`. Each event flushed as it is emitted. |
| Fail-closed | `CIDM_API_KEY` unset in the broker's env → every `/v1/chat/completions` request is rejected 401. |

## 5. Strong requests and approval

Strength classifier (`_classify_strength`): the request is `strong` if the goal or context contains any of `delete, drop, destroy, wipe, remove, truncate, update, alter, shutdown, revoke, rotate, grant, deploy, prod, production, merge to main, force-push, force push, spend, charge, purchase, pay, rm -rf`, or if the client sent `cidm_strong: true`. The classifier is conservative — false positives force an explicit approval (safe), false negatives lose the gate.

On a strong request the broker:
1. Writes an approval record `runs/approvals/{token}.json` with `status=pending`.
2. Returns an assistant message containing the approval URL `http://127.0.0.1:8765/approve/{token}`.
3. In streaming mode, emits `[CIDM] classified as STRONG; approval required` as a status chunk before the URL.
4. Leaves the plan unexecuted. The response envelope carries `cidm.status=pending_approval` and `cidm.approval_token`.

The operator opens the URL, reviews, and POSTs:

```powershell
curl.exe -X POST "http://127.0.0.1:8765/api/approvals/<token>" `
  -H 'Content-Type: application/json' -H 'X-CIDM-Console: 1' `
  -d '{"decision":"approve","operator":"you@local"}'
```

Approval tokens are **one-shot**: once decided (approved or rejected) the token cannot be flipped. A new request creates a new token.

## 6. Threads

Every turn is journaled under `runs/threads/{thread_id}.json`. The thread id is `sha256(first_user_message)[:16]`; follow-up turns in the same Hermes conversation share it. The journal records timestamp, goal (≤400 chars), provider, and gate policy per turn. Concurrent same-thread writes are serialised by a per-thread lock and committed with `os.replace` for atomicity.

Edge case: if Hermes compacts conversation history and drops the original first user message, the thread id shifts. This is acceptable for broker V1; a later slice can pass an explicit `user` field to pin the thread.

## 7. Adversarial pass condition (tests/test_hermes_dispatch_adversarial.py)

| Vector | Expected behaviour | Test |
|---|---|---|
| No bearer | 401 | A.1 |
| Wrong bearer | 401 | A.2 |
| Rebound Host header | 403 | B |
| Console-CSRF header without bearer | 401 | C |
| Unknown model | 400 `invalid_request_error` | D |
| Strong request as "normal" | returns pending approval, record is `pending` on disk | E |
| Approval POST without CSRF header | 403, record stays `pending` | F |
| Re-decide a decided token | 400 `already rejected` | G |
| GET on `/v1/chat/completions` | no broker run, no 500 | H |

All nine pass.

## 8. Rollback

```powershell
python scripts/install_hermes_cidm_provider.py --uninstall
```

Or restore the specific backup copy:

```powershell
Copy-Item -Force 'C:\Users\Ken\AppData\Local\hermes\config.yaml.bak-cidm-<ts>' `
                 'C:\Users\Ken\AppData\Local\hermes\config.yaml'
```

The managed block is marker-bounded (`# BEGIN cidm-provider … # END cidm-provider`), so a text editor can remove it by hand without touching the rest of the Hermes config.

## 9. Known limitations

1. **Validate-only today.** The broker runs `--validate-only`; it reports the plan it would have run and does not call Claude/Codex. Live execution is gated behind P0-03 (one capped non-production live run with full audit); the OpenAI endpoint will promote to live when that gate clears.
2. **Thread id instability under compaction.** See §6.
3. **Classifier false negatives.** The strength classifier only sees keywords. Semantically-destructive requests phrased without those words slip through. The `cidm_strong: true` opt-in lets a caller force the strong path.
4. **In-process broker port pending.** Current path shells out to `native_transition_broker.py`. For live status callbacks during real execution the broker must move in-process; scoped for a later slice.
5. **Timestamp collision in installer backups.** `strftime("%Y%m%d%H%M%S")` is 1-second granular; two installs in the same second overwrite the earlier backup. Operator-driven, low risk.
6. **Linux/macOS default target.** The installer's default path is Windows-oriented. On other OSes pass `--target` explicitly.

## 10. Verification snapshot (2026-10-14)

| Metric | Value |
|---|---|
| Full offline suite | 375 tests, 1 opt-in Docker skip |
| Adversarial pass tests | 9/9 |
| Installer verified against real Hermes config | yes, backup `config.yaml.bak-cidm-20261014155609` |
| Live model calls | none |

*CIDM architecture and research by Ken Caber (Kenneth Vic A. Caber). OpenAI chat-completions schema is used only as a wire protocol, not as a vendor dependency.*
