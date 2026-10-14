# Jev Operator Console

The Operator Console is a local UI for supervising the Jev-Orchestrated Decision Mesh (CIDM). It does not merge Jev, Hermes, and a frontier model into one opaque agent.

```text
Operator -> Jev policy -> Hermes procedure/skills -> frontier worker -> validators -> Jev arbitration
```

Jev owns global routing, evidence, budget, and acceptance. Hermes owns local procedural execution and reusable skills. Claude Code is the default frontier worker; Codex is an alternative whose model list comes from the signed-in account. The console never fakes a Jev decision.

## Start

Python 3.10+ is sufficient; there is no JavaScript build step.

```bash
python scripts/operator_console.py            # http://127.0.0.1:8765
python scripts/operator_console.py --no-open --port 8765 --state runs/console-state.json
```

UI state is stored at `~/.jev/operator-console.json` by default (`--state` or `JEV_OPERATOR_STATE` override it).

## Views

| View | What it shows | Actions |
|---|---|---|
| **Operate** | Goal, accepted context, up to six source excerpts, route preview | Preview (no calls); validate a broker request (no calls); bounded smoke test; live CIDM run |
| **Providers** | Claude Code and Codex sign-in, billing source, model catalogue (account-derived or presets), CIDM route coverage, Jev key presence | Re-check accounts; sign in (launches the CLI's own login); adopt the Codex account model list |
| **Arsenal** | Registry skills with admission state, verified lessons, calibration metrics, owner-threshold report, executed Fast Path counts | Read-only |
| **MCP catalogue** | Configured MCP servers (env var names only), catalogued tool counts, compact search cards with bytes avoided | Refresh one server (starts its configured command after confirmation) |
| **Runs & recovery** | Runs under `runs/`: status, route, gate policy, committed units, calls, checkpoints | Telemetry summary; OTLP download; resume a paused run (operator ID plus spend confirmation) |
| **Hermes skills** | Skills in the source folder merged with Hermes' dashboard state | Enable/disable through Hermes' `PUT /api/skills/toggle`; open the folder |

## Execution modes

- **Preview route** (default): shows the intended route without model usage or project changes.
- **Bounded smoke test**: one tool-free, schema-checked call through the selected provider. The prompt goes over stdin, the call runs in an empty temporary workspace, and it consumes an `operator`-basis `frontier.run` permit. It checks account authentication and model availability. **It is not a Jev-governed CIDM result.** It needs an explicit model from the provider's list.
- **CIDM broker (live)**: runs `scripts/native_transition_broker.py --live` in the background with the chosen provider and gate policy (recovery-first by default). The job writes `runs/console-<time>/request.json` and `run/`, and the Operate view polls its journal tail. The run fails closed before any paid call if the account cannot serve the CIDM route catalogue. **It requires ticking the spend confirmation**, because it makes separately billed Jev API calls and uses provider plan usage within the configured caps. Only one live job runs at a time.

A paused run (`paused_recoverable`) appears in **Runs & recovery** with its active unit and pause reason. **Resume** continues it in a new folder after re-verifying the checkpoint, and records the operator ID. It can also grant the paused unit a fresh replan budget.

## Hermes skills

The default skill source is `~/.hermes/skills/` (`HERMES_HOME` changes it). Add one folder per skill with a `SKILL.md`. For live toggles, start Hermes' local management API:

```bash
hermes dashboard --no-open
```

The default endpoint is `http://127.0.0.1:9119` (`HERMES_DASHBOARD_URL` overrides it). A toggle changes Hermes' own skill state and takes effect in a new Hermes session. When the dashboard is unreachable, the console lists folder skills but refuses to pretend a toggle was applied. Hermes trust and Arsenal admission are separate: enabling a skill in Hermes does not admit it for Fast Path.

## Security and trust boundaries

- **Loopback only:** the server refuses to bind to non-loopback addresses.
- **Host checks:** every request must carry a loopback `Host` header on the console's port, which blocks DNS rebinding.
- **CSRF:** every POST needs `X-CIDM-Console: 1`, a JSON content type, and a same-origin `Origin` when present. A foreign web page cannot drive the console.
- **Response headers:** CSP, `X-Frame-Options: DENY`, `nosniff`, and `no-referrer`.
- **Credentials:** desktop-app cookies, OAuth tokens, and API keys are never read or returned. Claude account and organization IDs are reduced to an opaque reference. Codex reports only its login method.
- **Explicit actions:** live runs, resumes, and MCP server refreshes require explicit confirmation flags in the request.
- **Opening folders:** only directories can be opened. Sign-in launches the provider CLI directly, not a shell command string.
- **No silent fallback:** missing models or accounts are reported as errors and never substituted.

## Environment variables

| Variable | Purpose |
|---|---|
| `JEV_OPERATOR_STATE` | Console state JSON path |
| `HERMES_HOME` | Hermes home and default skill source (unset: `~/.hermes`, else `%LOCALAPPDATA%\hermes`) |
| `HERMES_DASHBOARD_URL` | Hermes dashboard API URL |
| `OPENROUTER_API_KEY` | Jev calls for live CIDM runs (read by the broker, never shown) |
| `CODEX_HOME` | Location of Codex's model catalogue cache |

## Test

```bash
python -m unittest tests/test_operator_console.py tests/test_operator_console_security.py -v
```

These cover persisted defaults, skill discovery, route previews, provider configuration merging, Host/Origin/header guards against a real server, spend and refresh confirmations, path-safe run access, the permit-bound smoke test, and broker request limits.

## Next milestones

1. A Hermes dispatch adapter that accepts Jev-issued permits, so Hermes procedures can run inside a CIDM unit.
2. Project profiles that select different Hermes skill bundles and MCP evidence plans per workspace.
3. Live progress for long broker runs, using the D-05 call timestamps.
