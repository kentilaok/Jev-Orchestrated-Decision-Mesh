# Handoff — Hermes dispatch adapter, slice 4 (14 October 2026)

**Branch:** `feature/hermes-dispatch-adapter`.
**Parent gate:** [P0-04 Governed Hermes integration](PRODUCTION-REQUIREMENTS-HANDOFF-2026-10-08.md). Fourth of six slices.
**Evidence level:** offline tests only. No model calls.

## 1. What this slice delivers

Strong-permit approval URL injection into the Hermes chat flow. When the broker classifies a request as **strong** (destructive or spend-above-cap by keyword, or when the client sets `cidm_strong: true`), the chat response pauses with an approval URL instead of running the plan. The operator approves or rejects via the Operator Console; status is persisted in a pending approval record.

- **Classifier** `_classify_strength(goal, context, explicit_strong=False)`: keyword list covers `delete, drop, destroy, wipe, remove, truncate, deploy, prod, production, spend, charge, purchase, pay, rm -rf, force-push, force push`. Conservative by design (false positives force an explicit approve; safer than false negatives).
- **Approval token** `_create_approval_token(config, thread_id, goal, provider, gate_policy)`: 32-hex token; record written atomically to `runs/approvals/{token}.json` with status `pending`.
- **Decision** `_record_approval_decision(token, config, decision, operator)`: operator-authored transition to `approved` or `rejected`, atomic write, per-token lock.
- **Response shaping**: strong requests return a `cidm` envelope with `status: pending_approval`, `approval_token`, `approval_url`. The assistant content contains a human-readable "Approval required" message with the URL. Normal requests behave exactly as in slice 3.
- **Streaming**: when a strong request is streamed, the status chunk sequence is `[CIDM] starting → [CIDM] classified as STRONG → final content → stop → [DONE]` (skipping the "validating / plan ready" chunks that only make sense for the normal path).
- **HTTP routes**:
  - `GET /approve/{token}`: minimal self-contained HTML page showing the token, status, thread, provider, gate policy, and goal. Loopback-only, no auth beyond host guard (operator is physically at the machine). HTML escapes the goal before rendering.
  - `POST /api/approvals/{token}`: still subject to the existing Console CSRF guard (`X-CIDM-Console: 1` + Origin). Returns the updated record.

## 2. Code changes

| File | Change |
|---|---|
| `scripts/operator_console.py` | +165 lines. New `STRONG_KEYWORDS`, `_classify_strength`, `_APPROVAL_LOCKS`, `_approval_lock`, `_approvals_dir`, `_create_approval_token`, `_record_approval_decision`, `_approval_url`, `_cidm_envelope`, `Handler._send_html`; strong-aware branches in `_prepare_chat_run` and `chat_completions_stream`; new `/approve/{token}` route in `do_GET`; new `/api/approvals/{token}` route in `do_POST`. |
| `tests/test_openai_chat_endpoint.py` | +165 lines. Twelve new tests across two classes: classifier behaviour, pending-approval record creation, approval URL in content, pending marker in stream closing chunk, `_record_approval_decision` approve/unknown, GET /approve page for known/unknown tokens, POST /api/approvals CSRF requirement and successful approve. |

## 3. Verification

| Check | Result |
|---|---|
| Slice-4 tests | 12/12 pass |
| Full offline suite | 356/356 pass, 1 opt-in Docker skip |
| Regressions on 344-test post-fix baseline | 0 |
| `python -m compileall -q scripts` | pass |
| Live model calls | None |

## 4. How to try it locally

1. Start the Console with a token:
   ```powershell
   $env:CIDM_API_KEY = 'local-dev-key'
   python scripts/operator_console.py
   ```
2. Fire a destructive-looking request:
   ```powershell
   curl.exe -X POST http://127.0.0.1:8765/v1/chat/completions `
     -H 'Content-Type: application/json' `
     -H "Authorization: Bearer $env:CIDM_API_KEY" `
     -d '{"model":"cidm-jev","messages":[{"role":"user","content":"delete the production users table"}]}'
   ```
3. The response body contains an `approval_url` and the assistant content links to it. Open the URL in a browser on the same machine, review, then approve via the console or:
   ```powershell
   curl.exe -X POST "http://127.0.0.1:8765/api/approvals/<token>" `
     -H 'Content-Type: application/json' -H 'X-CIDM-Console: 1' `
     -d '{"decision":"approve","operator":"ken@local"}'
   ```

## 5. Open items for the next slice

1. **Hermes config entry (slice 5).** Edit `%LOCALAPPDATA%\hermes\config.yaml` to register CIDM as a `custom provider` with `base_url: http://127.0.0.1:8765/v1`, `key_env: CIDM_API_KEY`, `api_mode: chat_completions`, and `cidm-jev` as a model. Back up `config.yaml` first.
2. **Thread-level approval replay.** When a thread with an approved token submits its next turn, the broker should proceed instead of re-asking. Scoped for slice 5 or 6.
3. **Operator Console UI card.** The pending approvals list should show up in the Console sidebar with Approve / Reject buttons. Nice-to-have, not required to close P0-04.

## 6. Pass/hold decision for this slice

- `scope`: internal milestone, not a release
- `decision`: **PASS pending independent QA**. Review runs after push.
- `next action`: QA review of slice 4 commit, then slice 5 (Hermes config edit, backup first).

*CIDM architecture and research by Ken Caber (Kenneth Vic A. Caber).*
