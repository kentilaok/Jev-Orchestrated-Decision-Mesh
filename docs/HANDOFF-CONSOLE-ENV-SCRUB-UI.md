# Handoff — Operator Console UI for secret_env_names (15 October 2026)

**Branch:** `feature/console-env-scrub-ui`, based on `main` at `bb2ac38`.
**Parent gate:** P0-06 slice 2c (cleanup) — close the Operator Console UI carry-over from slice 2a. Backend already works end to end; this slice gives the operator a textarea instead of hand-editing `~/.jev/operator-console.json`.
**Evidence level:** HTML static assertions only. No model calls, no network calls.

## 1. What this slice delivers

The Security view in `console/index.html` now has a **Secret env var names** textarea next to **Trusted MCP servers**, with the same comma-or-newline parsing. `loadSecurity()` reads `state.config.secret_env_names` into the textarea on view activation; `saveSecurity()` POSTs the parsed list back under the `secret_env_names` key alongside the other P0-05 knobs. The server-side `_merge_config` validation added in PR #19 catches invalid entries (empty strings, strings containing `=`, non-list input) at the HTTP boundary, so no new server-side change was needed.

Scope deliberately excluded: the `max_cumulative_usd` cap from slice 2b lives on `RunConfig`, not on the Operator Console config. Surfacing it in the UI would need a separate slice that threads a Console-level `RunConfig` override through `broker_argv --config`.

## 2. Code changes

| File | Change |
|---|---|
| `console/index.html` | +9 lines of markup (textarea, label, helper paragraph) and +2 lines of JS (`loadSecurity` populates, `saveSecurity` includes `secret_env_names` in the POST body). |
| `tests/test_console_env_scrub_ui.py` | New, 5 tests: textarea id present, label mentions the knob, `loadSecurity` references both `secret_env_names` and `secretEnvNames`, save body carries `secret_env_names:`, regression guard that the existing P0-05 Security markers are untouched. |
| `docs/HANDOFF-CONSOLE-ENV-SCRUB-UI.md` | This handoff. |

## 3. Verification

| Check | Result |
|---|---|
| Slice tests | 5/5 pass |
| Full offline suite | 591/591 pass, 1 opt-in Docker skip |
| Regressions on 586-test post-PR#20 baseline | 0 |
| Live model calls | None |

## 4. Design calls honoured

- **Mirror the Trusted-MCP-servers UI exactly.** Same textarea pattern, same `/[,\n]/` split, same `.filter(Boolean)` discard-empty. One mental model for the operator.
- **Help text names the hardcoded defaults.** The helper paragraph lists the hardcoded names (`OPENROUTER_API_KEY`, `OPENAI_API_KEY`, `CODEX_API_KEY`, `GITHUB_TOKEN`, `GH_TOKEN`, `TYPESAFE_API_KEY`) so the operator knows what is already covered and understands "additive".
- **No new API endpoint.** Reuses `/api/state` for load and the generic `save()` helper (which POSTs the whole config back) for save; the server already runs `_merge_config` validation on the merged payload.
- **No server-side change.** The validation that lands bad input on PR #19 is still the only validation; the UI gives it one more entry point.

## 5. Open items (P0-06 next slices)

- **`max_cumulative_usd` UI** (deferred): needs a slice that threads a Console-settable `RunConfig` override into `broker_argv --config` first.
- **Slice 3:** `scripts/harden_jev_permissions.py` NTFS/POSIX ACL defaults for `~/.jev` + `runs/`.
- **Slice 4:** retention / backup playbook + restore drill.
- **Slice 5:** OTLP ordinal-span caveat telemetry assertion.

## 6. Decision

- `scope`: P0-06 slice 2c.
- `decision`: **PASS pending QA**; PR against `main` after QA.

*CIDM architecture and research by Ken Caber (Kenneth Vic A. Caber).*
