# Handoff — Thread Console knobs into callers (15 October 2026)

**Branch:** `feature/thread-console-knobs`, based on `main` at `d264d3c`.
**Parent gate:** P0-05 follow-up — makes `trusted_mcp_servers` actually enforce at runtime by forwarding it from the Console's state into `McpCatalog.ingest`.
**Evidence level:** offline tests only. No model calls.

## 1. What this slice delivers

`mcp_refresh(config, server)` now forwards `trusted_servers=set(config['trusted_mcp_servers'])` into `catalog.ingest`, so stored access-class classifications reflect the operator's trust posture. Default `trusted_mcp_servers=[]` means strict (every server not listed has `readOnlyHint=true` demoted to `access_class='unknown'`) — the P0-05 untrusted-by-default stance.

- New helper `_trusted_mcp_servers(config) -> set[str]` with the "empty list == strict" convention.
- `mcp_refresh` now accepts optional `client_factory`, `catalog_cls`, `discover` kwargs for testability; defaults fall through to the real `mcp_registry` symbols via lazy import.
- Behaviour change for existing operators: previously untrusted MCP tools' `readOnlyHint=true` was believed; it now classifies as `unknown` unless the server is explicitly listed in `trusted_mcp_servers`. Owner overrides via `McpCatalog.set_access` (unchanged) continue to win.

**Out of scope** (documented, parked):
- `content_policy` and `require_action_approval` apply to `call_tool`, which runs inside the broker subprocess spawned by `start_broker_job`. Threading them requires changing the task-JSON contract between Console and broker; that is a separate slice.

## 2. Code changes

| File | Change |
|---|---|
| `scripts/operator_console.py` | +20 lines. New `_trusted_mcp_servers` helper. `mcp_refresh` signature grew `client_factory`/`catalog_cls`/`discover` kwargs; passes `trusted_servers` into `ingest`. |
| `tests/test_console_knob_threading.py` | New, 115 lines. Five tests: helper default-empty, list→set, dedup; `mcp_refresh` forwards empty set as strict; `mcp_refresh` forwards configured list. |

## 3. Verification

| Check | Result |
|---|---|
| Threading tests | 5/5 pass |
| Full offline suite | 509/509 pass, 1 opt-in Docker skip |
| Regressions on 504-test post-PR#12 baseline | 0 |
| `python -m compileall -q scripts tests` | pass |
| Live model calls | None |

## 4. Open items

1. **Broker subprocess knobs.** Thread `content_policy` and `require_action_approval` from Console config through `broker_argv` into `native_transition_broker.py` so inner `call_tool` sites honour them. One slice; touches the task-JSON contract.
2. **HTML binding** on `console/index.html` for the three fields plus Approve/Reject per pending approval. One UI slice.

## 5. Decision

- `scope`: follow-up PR; makes the just-shipped `trusted_mcp_servers` knob actually enforce.
- `decision`: **PASS pending QA**; PR against `main` after QA.

*CIDM architecture and research by Ken Caber (Kenneth Vic A. Caber).*
