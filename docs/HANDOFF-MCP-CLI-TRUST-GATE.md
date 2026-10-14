# Handoff — MCP CLI trust gate (15 October 2026)

**Branch:** `feature/mcp-cli-trust-gate`, based on `main` at `81c9cf0`.
**Parent gate:** closes the carry-over flagged in PR #13's QA — the `python scripts/mcp_registry.py refresh` CLI subcommand previously bypassed the P0-05 trust gate.
**Evidence level:** offline tests only. No model calls.

## 1. What this slice delivers

The CLI `refresh` subcommand now resolves and forwards `trusted_servers` to `catalog.ingest`, matching the Operator Console path (PR #13). Resolution order:

1. explicit `--trusted-servers a,b,c` on the command line
2. `trusted_mcp_servers` from `~/.jev/operator-console.json` (shared source of truth with the Console)
3. empty set — strict, untrusted-by-default

Changes:
- New `_resolve_cli_trusted_servers(*, cli_value, state_path)`. Corrupt/missing state file silently falls through to strict (never raises).
- Argparse layout extracted into `_build_cli_parser()` for testability.
- New `--trusted-servers` option on the `refresh` subcommand (string, default `None`).
- `main()` wires the resolved trust set into `catalog.ingest(spec, client.list_tools(), trusted_servers=…)`.

## 2. Code changes

| File | Change |
|---|---|
| `scripts/mcp_registry.py` | +30/-20 lines. Factored `_build_cli_parser`, added `_resolve_cli_trusted_servers`, `--trusted-servers` flag, forwarded the set into `ingest`. |
| `tests/test_mcp_cli_trust_gate.py` | New, 85 lines. Nine tests: CLI arg precedence, whitespace stripping, empty-string handling, state-file fallback, missing state file is strict, corrupt JSON is strict, missing field is strict, parser accepts the flag, flag defaults to `None`. |

## 3. Verification

| Check | Result |
|---|---|
| CLI trust-gate tests | 9/9 pass |
| Full offline suite | 518/518 pass, 1 opt-in Docker skip |
| Regressions on 509-test post-PR#13 baseline | 0 |
| `python -m compileall -q scripts tests` | pass |
| Live model calls | None |

## 4. Open items (unchanged)

1. Broker-subprocess knob threading (`content_policy` + `require_action_approval` through `broker_argv`).
2. HTML binding on `console/index.html`.
3. P0-06 UI / credentials / recovery hardening.
4. Approval provenance / Jev-signed evidence.
5. P0-01 CI billing banner.

## 5. Decision

- `scope`: follow-up PR closing the PR #13 QA finding.
- `decision`: **PASS pending QA**; PR against `main` after QA.

*CIDM architecture and research by Ken Caber (Kenneth Vic A. Caber).*
