# Jev Operator Console

The Operator Console is an experimental local UI for supervising the Jev-Orchestrated Decision Mesh (CIDM) without turning Jev, Hermes, and a frontier model into one opaque agent.

```text
Operator -> Jev policy -> Hermes procedure/skills -> frontier worker -> validators -> Jev arbitration
```

Jev owns global routing, evidence, budget, and acceptance policy. Hermes owns local procedural execution and reusable skills. Claude Code is the default frontier worker in v0.1; Codex is available as an optional switch. Preview mode never pretends to be a live Jev call.

## Start

Python 3.10+ is sufficient; there is no JavaScript build step.

```bash
python scripts/operator_console.py
```

The console binds to `127.0.0.1:8765` and stores its UI state at `~/.jev/operator-console.json` by default.

## Hermes Skills workspace

The **Hermes Skills** page provides a dedicated source-folder workflow:

1. The default source is `~/.hermes/skills/`.
2. Click **Open folder** to open that directory in Finder/File Explorer/the Linux file manager.
3. Add one folder per skill, with a `SKILL.md` inside it.
4. Click **Refresh** to re-scan the source.
5. When Hermes' dashboard API is reachable, use the toggle beside each skill to enable or disable it.

Hermes treats `~/.hermes/skills/` as its primary skill directory. It also supports external skill directories through `skills.external_dirs`. If the console points at another source directory, add that directory to Hermes' configuration so Hermes can load the same skills.

Start Hermes' local management API with:

```bash
hermes dashboard --no-open
```

The default endpoint is `http://127.0.0.1:9119`. The console uses Hermes' own `GET /api/skills` and `PUT /api/skills/toggle` endpoints. A toggle therefore changes Hermes' skill state rather than renaming files or maintaining a second registry. Changes take effect in a new Hermes session.

If the dashboard is not reachable, the UI can still list skills from the source folder but it refuses to pretend a toggle was applied.

## Frontier account switcher

The **Frontier Accounts** page exposes two local adapters:

- **Claude Code** — default.
- **Codex** — optional.

The console does not read or copy credentials from the Claude or ChatGPT/Codex desktop apps. Instead, each CLI uses its supported sign-in flow with the same subscription account.

### Claude Code

Run `claude`, then `/login` if needed. Claude Code can use an eligible Claude subscription account. The `/model` menu is the authoritative list for that account, and `--model` can select a model for a one-shot run.

The UI includes convenience presets:

- `default`
- `claude-sonnet-5-5`
- `claude-opus-5-5`
- `claude-fable-5-1`

Availability remains account- and rollout-dependent. There is no silent model fallback in the console.

If `ANTHROPIC_API_KEY` is present, Claude Code may prefer API-key billing over subscription authentication. Use Claude Code's `/status` view to verify the billing/auth source before live work.

### Codex

Run:

```bash
codex login
codex login status
```

Authenticate with the ChatGPT account associated with your Codex access. The UI includes current Codex-oriented presets:

- `default`
- `gpt-6.1-sol`
- `gpt-6-sol`
- `gpt-6-luna`

Actual options depend on the ChatGPT plan, workspace policy, and rollout. The console surfaces provider errors instead of silently substituting a model.

## Execution modes

### Preview only

Default. Produces the intended route without model usage or project mutation:

```text
Input -> Jev -> Hermes -> selected frontier -> Validators -> Jev
```

### Frontier direct

Runs the selected locally authenticated CLI explicitly:

- Claude: `claude [--model <id>] -p <task>`
- Codex: `codex exec --sandbox read-only [--model <id>] <task>`

This mode is primarily for validating local account authentication and the frontier switcher before the full Jev/Hermes dispatch adapter is connected.

### Hermes + Jev

The UI exposes this target mode but deliberately fails closed today. It is not simulated.

A production adapter must:

1. accept a bounded Jev-authorized operation,
2. bind the selected Hermes skill set,
3. dispatch the selected frontier worker,
4. return candidate output and evidence receipts to Jev,
5. apply hard validators before commit,
6. keep retry/delegation budgets visible to the CIDM ledger.

## Security and trust boundaries

- The web server binds to loopback by default.
- Desktop-app cookies and bearer tokens are never read by this project.
- Credential files are not returned to the browser.
- Preview mode is the default.
- Skill toggles fail closed unless Hermes confirms them.
- Codex direct execution is forced to read-only sandbox mode in this MVP.
- Global agent fan-out remains a Jev concern; Hermes may orchestrate only inside a bounded operation.
- Missing model/account capabilities are surfaced as errors, not guessed.

## Environment variables

| Variable | Purpose |
|---|---|
| `JEV_OPERATOR_STATE` | Override the console state JSON path |
| `HERMES_HOME` | Change the default Hermes home and skill source |
| `HERMES_DASHBOARD_URL` | Override the Hermes dashboard API URL |

## Test

```bash
python -m unittest tests/test_operator_console.py -v
```

The console tests cover persisted defaults, skill-folder discovery, Claude-first route previews, and provider configuration merging.

## Next milestones

1. Implement the live Jev decision adapter.
2. Add a Hermes dispatch adapter that accepts Jev-issued bounded permits.
3. Add supported live model discovery where each provider exposes a non-destructive interface.
4. Record usage/budget counters without converting unknown values to zero.
5. Bind validator outputs and artifact hashes into the existing CIDM commit protocol.
6. Add project profiles so RiftForge, Gatebreaker, and other workspaces can select different Hermes skill bundles.
