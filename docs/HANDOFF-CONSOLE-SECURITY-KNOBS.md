# Handoff — Operator Console security knobs (15 October 2026)

**Branch:** `feature/console-security-knobs`, based on `main` at `564dc5c`.
**Parent gate:** P0-05 follow-up — surfaces the three security knobs on the Operator Console state and adds an approvals listing endpoint.
**Evidence level:** offline tests only. No model calls.

## 1. What this slice delivers

Three new state-config fields (persisted via `StateStore`) and one listing endpoint so an operator can read and edit the P0-05 knobs from `/api/*` instead of only through Python kwargs:

- `trusted_mcp_servers: list[str]` — names of MCP servers whose annotations are trusted by `mcp_registry.classify`'s trust gate. Default `[]`.
- `content_policy: 'off' | 'audit' | 'wrap'` — default `off`. Enforced by `_merge_config` validation.
- `require_action_approval: bool` — default `False`.
- `GET /api/approvals` — returns `{"pending": [...], "decided": [...]}` built by reading `runs/approvals/*.json`. Records are sorted by creation / decision timestamps.

Validation in `_merge_config`:
- Invalid `content_policy` value raises `ValueError`.
- Non-bool `require_action_approval` raises.
- Non-list or non-string-entry `trusted_mcp_servers` raises.

UI wiring on `console/index.html` is deferred — the API shape is stable now and the HTML can bind to it in a follow-up without touching semantics.

## 2. Code changes

| File | Change |
|---|---|
| `scripts/operator_console.py` | +52 lines. `DEFAULT_CONFIG` gains the three fields. `_merge_config` validates them with explicit `ValueError`s. New `list_approvals(config)` reads the approvals directory, splits pending vs decided. `do_GET` routes `/api/approvals`. |
| `tests/test_console_security_knobs.py` | New, 125 lines. Eleven tests: defaults (1), merge validation (7), approvals listing (3) including empty case, pending/decided split, token length bound. |

## 3. Verification

| Check | Result |
|---|---|
| Security-knobs tests | 11/11 pass |
| Full offline suite | 504/504 pass, 1 opt-in Docker skip |
| Regressions on 493-test post-PR#11 baseline | 0 |
| `python -m compileall -q scripts tests` | pass |
| Live model calls | None |

## 4. Open items

1. **HTML binding** on `console/index.html` — read `/api/state` and `/api/approvals`, render editors for the three fields plus Approve/Reject buttons per pending approval. Mechanical.
2. **Thread knobs into actual callers.** The config is readable; `mcp_registry.call_tool` call sites in the Operator Console's `start_broker_job` and recovery path still pass `trusted_servers=None` and `content_policy='off'`. Follow-up slice reads from `config` and passes the right kwargs.
3. **Approval POST through the UI.** `/api/approvals/<token>` already exists (from PR #5); the HTML form needs a listener.

## 5. Decision

- `scope`: follow-up PR; narrows the "no operator UI for security knobs" open item.
- `decision`: **PASS pending QA**; PR against `main` after QA.

*CIDM architecture and research by Ken Caber (Kenneth Vic A. Caber).*
