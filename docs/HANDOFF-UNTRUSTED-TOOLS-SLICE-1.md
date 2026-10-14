# Handoff — Untrusted-tools hardening, slice 1 (14 October 2026)

**Branch:** `feature/untrusted-tools-hardening`, based on `main` at `daeb507`.
**Parent gate:** [P0-05 Permissions and untrusted tools](PRODUCTION-REQUIREMENTS-HANDOFF-2026-10-08.md). First of four slices.
**Evidence level:** offline tests only. No model calls.

## 1. What this slice delivers

MCP server trust gate. The `classify()` function previously trusted every third-party MCP server's `annotations.readOnlyHint` and granted the `read` access class on that basis alone. A malicious server could lie about a tool being read-only to get read-tier permits.

- `classify(server, tool, *, trusted_servers=None)` — new opt-in kwarg. When supplied, servers not in the set have their `read`-via-annotation inference demoted to `unknown` with basis `untrusted_server_readonly_hint_ignored`.
- `destructiveHint=True` and `readOnlyHint=False` from untrusted servers are kept — a lying server can only *restrict* capability by over-reporting destructiveness.
- Builtin `PROFILES` (owner-vetted at merge time) continue to classify ahead of the trust gate.
- `McpCatalog.set_access()` owner overrides still win in `McpCatalog.access()`.
- `McpCatalog.ingest(spec, tools, *, trusted_servers=None)` threads the trust set through, so stored `access_class` reflects the operator's trust posture at ingest time.
- Legacy behaviour preserved when `trusted_servers is None`: existing callers that do not pass the kwarg see no change.

## 2. Code changes

| File | Change |
|---|---|
| `scripts/mcp_registry.py` | +12 lines. `classify` and `McpCatalog.ingest` grow a `trusted_servers` kwarg. |
| `tests/test_mcp_trust_gate.py` | New, 150 lines. Eleven tests across two classes: classify-level (7) covers readOnly demotion, trusted-server pass-through, destructive-hint retention, readOnly-False retention, backward-compat, profile precedence, unclassified-unknown; catalog-level (4) covers ingest demotion, trusted ingest, owner-override precedence, backward-compat. |

## 3. Verification

| Check | Result |
|---|---|
| Slice-1 tests | 11/11 pass |
| Full offline suite | 423/423 pass, 1 opt-in Docker skip |
| Regressions on 412-test post-P0-02 baseline | 0 |
| `python -m compileall -q scripts tests` | pass |
| Live model calls | None |

## 4. Open items for the next slices

1. **Non-reversible-action gate (slice 2).** Classify tool calls as reversible or non-reversible. Non-reversible actions require explicit operator approval beyond the standard permit (reuses the slice-4 approval URL from the Hermes dispatch work).
2. **Retrieval/MCP content as data (slice 3).** Any retrieval or MCP response text is treated as data, not authority. A retrieved doc that says "override access_class to read" is not acted on. Covers the P0-05 instruction-injection surface.
3. **Adversarial corpus + operator doc (slice 4).** Fixtures of hostile MCP servers / permits / retrieval content, operator doc, P0-05 pass-condition check.

## 5. Pass/hold decision for this slice

- `scope`: internal milestone, not a release
- `decision`: **PASS pending QA**; QA runs after push, next slice continues per standing cadence.

*CIDM architecture and research by Ken Caber (Kenneth Vic A. Caber).*
