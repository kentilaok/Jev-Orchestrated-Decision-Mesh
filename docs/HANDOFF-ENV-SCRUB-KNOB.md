# Handoff — Env-scrub knob end to end (15 October 2026)

**Branch:** `feature/env-scrub-knob`, based on `main` at `03aff96`.
**Parent gate:** P0-06 slice 2a — "Verify secret references, process environment scrubbing… before granting persistent access" from the production handoff. Pairs with the already-landed hardcoded scrub set inside both CLI adapters.
**Evidence level:** offline tests only. No model calls.

## 1. What this slice delivers

The adapters have always scrubbed a fixed set of secret env var names (`OPENROUTER_API_KEY`, `OPENAI_API_KEY`, `CODEX_API_KEY`, `GITHUB_TOKEN`, `GH_TOKEN`, plus `TYPESAFE_API_KEY` on Claude). Each adapter also accepts a `secret_env_names` constructor kwarg that is additively merged into the frozen set — but no caller used it. This slice threads an operator-settable list through every call site, so adding a project-specific name in the Operator Console (or on the broker CLI) actually scrubs it from the worker subprocess environment.

- **Operator Console** gains a `secret_env_names: list[str]` config field (default `[]`). `_merge_config` validates list-of-non-empty-strings-without-`=` and rejects everything else (non-list, empty entry, non-string, `=` in entry).
- **`broker_argv`** emits `--secret-env-names A,B,C` when the list is non-empty; omits the flag entirely at default. Matches the pattern used by `--content-policy` and `--require-action-approval`.
- **`native_transition_broker.py` CLI** gets `--secret-env-names` with a tiny argparse `type=` parser that splits the comma string, rejects empty / `=`-containing entries, and threads the parsed list into the `build_provider` options kwargs when non-empty.
- **`ClaudeCodeProvider` / `CodexProvider`** both accept `secret_env_names=()` and forward it to the adapter constructor when they build their default adapter. Explicit adapters (passed via `adapter=`) are untouched — that path is a test seam.
- **`ClaudeCliAdapter`** gained the same `secret_env_names` input validation Codex already had; previously a non-string entry would have raised `AttributeError` inside `n.upper()`. Codex side unchanged.

## 2. Code changes

| File | Change |
|---|---|
| `scripts/operator_console.py` | `+6` lines. New `secret_env_names` default, `_merge_config` validation branch, and `broker_argv` emission. |
| `scripts/native_transition_broker.py` | `+16` lines. New `_parse_secret_env_names` helper, new `--secret-env-names` CLI arg, options threading before `build_provider`. |
| `scripts/frontier_providers.py` | `+4` lines. `secret_env_names=()` kwarg on `ClaudeCodeProvider.__init__` and `CodexProvider.__init__`, forwarded to the adapter when building the default. |
| `scripts/claude_cli_adapter.py` | `+4` lines. Parity validation of `secret_env_names` (list/tuple/set of non-empty strings without `=`). |
| `tests/test_env_scrub_knob.py` | New, 19 tests. Covers Console config merge, `broker_argv` emission, broker CLI parsing (accept + reject), both providers forwarding to adapters, Claude adapter rejecting invalid input, and one integration test that mocks `subprocess.Popen` to confirm an operator-added name is actually missing from the child env dict. |
| `docs/HANDOFF-ENV-SCRUB-KNOB.md` | This handoff. |

## 3. Verification

| Check | Result |
|---|---|
| Slice tests | 19/19 pass |
| Full offline suite | 560/560 pass, 1 opt-in Docker skip |
| Regressions on 541-test post-PR#18 baseline | 0 |
| `python -m compileall -q scripts tests` | pass |
| Live model calls | None |

## 4. Design calls honoured

- **Additive, not replace.** Operator-added names union with the hardcoded set; `OPENROUTER_API_KEY` et al. stay scrubbed regardless of what the Console contains.
- **Case-insensitive, declared case-insensitive.** Entries are upper-cased before comparison, mirroring the pre-existing adapter behaviour.
- **Validation on both ends.** The Console rejects bad config, the broker CLI rejects bad flags, the Claude adapter rejects bad constructor input. No silent coercion anywhere.
- **UI deferred.** `operator_console.py` JSON config carries the knob; `console/index.html` Security view does not render it yet. A later cleanup slice can surface it next to `trusted_mcp_servers`.

## 5. Open items (P0-06 next slices)

- **Slice 2b:** cumulative spend-cap state on the permit ledger (adapter outcome → `receipt(..., cost_usd=…)` → `_cumulative_cost_usd` replay → `issue()` refuses when a new budget would push past `RunConfig.max_cumulative_usd`).
- Slice 3: `scripts/harden_jev_permissions.py` NTFS/POSIX ACL defaults for `~/.jev` + `runs/`.
- Slice 4: retention / backup playbook + restore drill.
- Slice 5: OTLP ordinal-span caveat telemetry assertion.

## 6. Decision

- `scope`: P0-06 slice 2a.
- `decision`: **PASS pending QA**; PR against `main` after QA.

*CIDM architecture and research by Ken Caber (Kenneth Vic A. Caber).*
