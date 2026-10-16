# Handoff — P0-03 slice 3b: capped smoke runner and negative runs (17 October 2026)

**Branch:** `feature/p0-03-live-smoke`, stacked on PR #25. Retarget to `main` after #25 merges.
**Parent gate:** P0-03 (live provider execution and accounting).
**Evidence level:** offline tests only. No model calls, no network.

## 1. What this slice delivers

`python scripts/p0_03_smoke.py (--dry-run | --live) [--negative low-budget|wrong-model|provider-unavailable]`

- One capped run of the broker with Jev via OpenRouter and the worker via the Claude CLI (`--host claude --gate-policy recovery`). Default task: `examples/native-project.request.json`.
- Both caps default to, and may not exceed, `SMOKE_CEILING_USD = 1.0`: `RunConfig.max_usd` (Jev) and `max_cumulative_usd` (Claude permit ledger).
- **Preflight, no model calls:** task validates; Jev model is the pinned `typesafe/jev-1.13` and the worker family is Claude; both caps within the ceiling; `OPENROUTER_API_KEY` present (reported as a boolean only); Claude CLI installed and signed in, with billing channel, auth method, subscription type and the `ANTHROPIC_API_KEY` warning recorded.
- `--dry-run` prints the preflight and the exact broker command; nothing is created or launched.
- `--live` writes `runs/p0-03-smoke/<UTC stamp>-<mode>/`: `config.json`, `broker/` (broker `--out`), broker stdout/stderr, and `smoke-report.json` (preflight, command, exit code, result status, Jev cost, full slice-3a audit, expectation). A run folder is never reused.
- Exit 0 when the run met its expectation, 1 when it did not, 2 when refused before launch.
- Launched from inside a Claude Code session (CLI or desktop app), the runner removes that session's variables (`CLAUDECODE`, `CLAUDE_CODE_*`, `CLAUDE_AGENT_SDK_*`, `CLAUDE_PID`, `CLAUDE_PREVIEW_*`, and an inherited `ANTHROPIC_BASE_URL`) before the preflight and the broker, so the worker `claude` uses the operator's own sign-in rather than the host session's endpoint. Removed names (never values) are in `session_env_removed`. The provider status check now runs with the provider's `env`.

## 2. Negative runs (each must stop before any paid call)

| Negative | How | Where it stops |
|---|---|---|
| `provider-unavailable` | Claude CLI path that does not exist | preflight `claude_cli`; broker never launched |
| `wrong-model` | Jev model `typesafe/jev-0.0-wrong` | preflight `models_pinned`; broker never launched |
| `low-budget` | `max_usd = 1e-6` | real broker launches; the gateway refuses the first Jev call at admission (no HTTP), the recovery network halts with `failed`; audit clean, 0 Jev requests, 0 permits consumed, $0 |

A preflight negative counts only when its targeted check is one that refused.

## 3. Code changes

| File | Change |
|---|---|
| `scripts/p0_03_smoke.py` | New runner. |
| `scripts/native_transition_broker.py` | `--claude-executable` (Claude host only, refused otherwise before anything is written). |
| `scripts/frontier_providers.py` | `ClaudeCodeProvider.status()` runs `claude auth status` with the provider's `env` (default `os.environ`, unchanged for existing callers). |
| `tests/test_p0_03_smoke.py` | 13 tests: session-variable removal (and a base URL set outside a session is kept), dry run, missing key, both caps above the ceiling, non-Claude family, both preflight negatives, low-budget through the real broker subprocess (dummy key, dead proxy, fake `claude` that leaves a marker if a model call is attempted), clean and tampered live runs with a fake broker, folder reuse, broker flag guard. |

## 4. Verification

| Check | Result |
|---|---|
| Slice tests | 11/11 pass |
| Full offline suite | 713 pass, 5 skips |
| `compileall`, `git diff --check`, CI validate-only and evidence verifiers | pass |
| Live model calls | none |

## 5. Before slice 3c (paid, Ken's go-ahead)

1. Install Claude Code with the **native installer** (`claude.exe`). On Windows an npm `claude.cmd` shim passes the status check, but the adapter's shell-free `Popen` cannot start the bare name, and a `.cmd` path would route the JSON-schema argument through `cmd.exe` parsing. Pass `--claude-executable` with the full `.exe` path if it is not on PATH.
2. Sign in to Claude Code with the subscription; make sure `ANTHROPIC_API_KEY` is not set unless API billing is intended.
3. Set `OPENROUTER_API_KEY` in the environment yourself.
4. `python scripts/p0_03_smoke.py --dry-run` must report `"ok": true`.
5. Run the three negatives, then the live smoke run; copy each run folder under `research/p0-03-smoke/` (`runs/` is git-ignored), check it holds no secrets, and commit.

## 6. Known limits

- The positive path is tested with a fake broker; the first real end-to-end run is slice 3c.
- Claude Code has no non-interactive model catalogue, so route coverage stays `unverified`; served identity comes from `modelUsage` per call.
- Claude cost on the permit ledger is the CLI's API-equivalent estimate, not a bill under a subscription.

## 7. Decision

- `scope`: P0-03 slice 3b.
- `decision`: **PASS pending QA**.

*CIDM architecture and research by Ken Caber (Kenneth Vic A. Caber).*
