# Handoff — Untrusted-tools call-site integration (14 October 2026)

**Branch:** `feature/untrusted-tools-callsites`, based on `main` at `81e784c`.
**Parent gate:** closes the "shape only" carry-over from P0-05 at the primary MCP call site; retriever surface accepts the kwarg but full wrapping remains a follow-up.
**Evidence level:** offline tests only. No model calls.

## 1. What this slice delivers

- `mcp_registry.call_tool(..., content_policy='off'|'audit'|'wrap')`. Default `off` preserves existing behaviour. `audit` scans the MCP tool result text with `content_sanitiser.scan_for_injection_markers` and records the matches on the receipt. `wrap` additionally runs `wrap_as_data(text, source_id='mcp:<server>:<tool>', kind='mcp_tool_result')` so the downstream source text is bracketed by `<<<CIDM_BEGIN_DATA … CIDM_END_DATA>>>` markers and visibly inert.
- `retrieval.RetrievalEvidenceRetriever(..., content_policy=…)`. Same three values, validated at construction. The surface is in place so operators can start setting the kwarg; actual text wrapping on each returned chunk is a one-slice follow-up because it also touches `as_sources` and the content hashes stored in the local index.
- Unknown `content_policy` values raise `ValueError` at the API boundary.

## 2. Code changes

| File | Change |
|---|---|
| `scripts/mcp_registry.py` | +13 lines. `call_tool` grows a `content_policy` kwarg; audit/wrap branch inside the `try` after `source_text` is computed. Lazy-import of `content_sanitiser` avoids a cycle. |
| `scripts/retrieval.py` | +4 lines. `RetrievalEvidenceRetriever.__init__` accepts `content_policy`, validates, stores. |
| `docs/UNTRUSTED-TOOLS.md` | Updated §5(1) to describe the partial integration. |
| `tests/test_untrusted_tools_integration.py` | New, 155 lines. Eight tests: five on `call_tool` (default off, audit records markers, wrap wraps text, wrap also records markers, unknown policy raises), three on the retriever (default off, wrap stored, unknown raises). |

## 3. Verification

| Check | Result |
|---|---|
| Integration tests | 8/8 pass |
| Full offline suite | 474/474 pass, 1 opt-in Docker skip |
| Regressions on 466-test post-PR#7 baseline | 0 |
| `python -m compileall -q scripts tests` | pass |
| Live model calls | None |

## 4. Open items

1. **Retriever text wrapping (follow-up).** Thread `content_policy` into `RetrievalEvidenceRetriever.__call__` so each returned chunk's text is wrapped when `wrap` is active. Requires revisiting the content-hash semantics inside the local index.
2. **Broker dispatch wiring (follow-up).** Call `action_reversibility.require_approval(action, annotations, approval=…)` at the broker's tool-dispatch site to enforce the non-reversibility gate at runtime, not just as a callable module.
3. **Operator policy wiring.** The Operator Console does not yet surface the `content_policy` and `trusted_servers` knobs. A later slice adds a config field + a UI control.

## 5. Decision

- `scope`: internal follow-up PR, not a new P0 gate; narrows the P0-05 "shape only" caveat.
- `decision`: **PASS pending QA**; PR against `main` after QA.

*CIDM architecture and research by Ken Caber (Kenneth Vic A. Caber).*
