# Handoff — Broker-dispatch action gate (14 October 2026)

**Branch:** `feature/broker-dispatch-gate`, based on `main` at `1f70c63`.
**Parent gate:** closes the second half of the P0-05 "shape only" caveat — the non-reversible-action gate is now enforced inside `mcp_registry.call_tool`.
**Evidence level:** offline tests only. No model calls.

## 1. What this slice delivers

`mcp_registry.call_tool` now accepts an opt-in action-reversibility gate:

- `require_action_approval` (bool, default `False`): backward-compat off.
- `approval` (dict, default `None`): the action-bound operator approval record.
- When `require_action_approval=True`, the gate runs **before** the client factory is invoked: `action_reversibility.require_approval(tool, card.annotations, approval=approval)`. A non-reversible tool without a matching approval raises `NonReversibleActionError` and the external effect never fires.
- On pass, `receipt['action_reversibility']` carries `{action, classification, approval_required, approved_by?}` for the audit.

The gate honours action-bound approvals: `delete_file` cannot be run under an approval granted for `drop_table`. Pending or rejected approvals never pass. Reversible tools pass with no approval needed.

## 2. Code changes

| File | Change |
|---|---|
| `scripts/mcp_registry.py` | +13 lines. `call_tool` grows `require_action_approval` and `approval` kwargs. Gate runs before `_check_arguments` → `authority.consume` → client call. Lazy-imports `action_reversibility` so the dependency is not required unless opted in. |
| `docs/UNTRUSTED-TOOLS.md` | Updated §5(1) — the P0-05 call-site integration half is now covered for MCP dispatch. |
| `tests/test_dispatch_action_gate.py` | New, 190 lines. Seven tests: default off backward-compat, non-reversible without approval refused, non-reversible with matching approval runs (receipt detail), non-reversible with mismatched action refused, reversible passes without approval, pending approval refused, gate runs before the client factory is contacted (no external effect on refuse). Exception-type assertion is name-based to survive importlib loader duplication across test files. |

## 3. Verification

| Check | Result |
|---|---|
| Dispatch-gate tests | 7/7 pass |
| Full offline suite | 481/481 pass, 1 opt-in Docker skip |
| Regressions on 474-test post-PR#8 baseline | 0 |
| `python -m compileall -q scripts tests` | pass |
| Live model calls | None |

## 4. Open items

1. **Retriever per-chunk wrapping** (one slice, closes the retrieval half of the untrusted-content integration).
2. **Operator Console surfacing** of `content_policy`, `trusted_servers`, `require_action_approval`, and the strong-permit approval UI (parked follow-up).
3. **Approval provenance.** The approval dict is still unsigned; Jev-associated immutable evidence remains future work (`UNTRUSTED-TOOLS.md` §5(4)).

## 5. Decision

- `scope`: follow-up PR narrowing the P0-05 "shape only" caveat on the dispatch side.
- `decision`: **PASS pending QA**; PR against `main` after QA.

*CIDM architecture and research by Ken Caber (Kenneth Vic A. Caber).*
