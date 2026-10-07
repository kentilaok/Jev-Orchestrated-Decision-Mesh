# Jev Operator Console — Claude-first UI

The Operator Console is the first user-facing control surface for the Jev-Orchestrated Decision Mesh (CIDM). It is intentionally **Claude-first**: Anthropic is the only enabled frontier provider in v1, while the model/provider registry remains extensible so future providers can be added without rewriting the UI.

## Goal

The console makes the architecture understandable and usable from one screen:

```text
User
  ↓
Jev control plane
  ↓
Hermes operational worker
  ↓
Selected Claude frontier model
  ↓
Deterministic validators / evidence
  ↓
Jev arbitration
```

The responsibilities stay separate:

- **Jev** owns global orchestration: task classification, evidence sufficiency, model/effort allocation, budgets, retries, escalation and final acceptance.
- **Hermes Agent** owns bounded operational execution: project rules, persistent skills/memory, terminal/tools and sessions.
- **Claude** supplies frontier reasoning inside the Hermes worker.
- **Validators** supply evidence rather than asking a model to grade itself.

This avoids building a second autonomous orchestrator under Jev. Hermes can coordinate locally inside a bounded operation, but global fan-out, escalation and acceptance remain CIDM policy decisions.

## What is implemented in v1

The browser UI provides:

1. A task composer with a workspace field.
2. A **frontier model switcher** backed by `console/frontier-models.json`.
3. Anthropic/Claude as the only enabled provider.
4. A live runtime panel for Hermes, Anthropic credentials and the existing Jev/OpenRouter gateway.
5. A route preview showing `Jev → Hermes → Claude → Validators → Jev`.
6. A **Run through Hermes** action that invokes a local, one-shot Hermes worker in safe mode.
7. A standard-library Python server so the repository does not gain a JavaScript build-tool dependency.

The live Run button is deliberately a **worker boundary**, not a claim of full CIDM acceptance. Its result is labelled `worker_complete_pending_validation`. The next integration milestone is a Hermes-backed `GenerativeAdapter` wired into the existing `CheckedNetwork`, so live Jev decisions, executable checks and one-use commit permissions govern the same worker the UI launches.

## Current Claude model registry

The initial registry uses current Anthropic model IDs and can be edited without touching the UI code:

| Model | Intended console role |
|---|---|
| `claude-opus-5-5` | Default frontier model for complex coding/orchestration |
| `claude-fable-5-1` | Hardest long-horizon reasoning |
| `claude-sonnet-5-5` | Faster balanced engineering work |
| `claude-haiku-4-5-20251001` | Fast/low-cost bounded tasks |

Do not treat the file as a permanent source of truth. Provider catalogs change. Before a production rollout, the backend should query Hermes' model/provider API (or Anthropic's Models API) and reconcile the configured allow-list with models actually available to the account.

## Start the console

Requirements:

- Python 3.10+
- Hermes Agent installed for live execution
- An Anthropic credential path supported by Hermes

Run:

```bash
python scripts/operator_console.py
```

Open:

```text
http://127.0.0.1:8765
```

Preview mode works even when Hermes is not installed. The Run button activates when the `hermes` executable is visible in `PATH`.

### Hermes + Claude authentication

Hermes owns model authentication. Use its model/auth setup rather than storing secrets in this project. Supported paths include Anthropic API credentials and Hermes/Claude Code authentication. The console never returns secret values to the browser.

A simple setup path is:

```bash
hermes model
```

Then select Anthropic and the Claude model you want Hermes to use. The console still passes an explicit provider/model on each run so the UI selection is auditable.

## Safe-mode execution

The backend executes a task approximately as:

```bash
hermes --safe-mode chat \
  --oneshot \
  --provider anthropic \
  --model claude-opus-5-5 \
  --reasoning medium \
  --query-file -
```

The actual binary path is resolved with `PATH`; the user's prompt is passed on stdin, not interpolated into a shell command. This prevents command injection through task text.

The console binds to `127.0.0.1` by default. Do not expose it publicly without adding authentication, CSRF protection, rate limits and a stricter workspace policy.

## Workspaces

Leaving Workspace blank runs Hermes in this repository. You can enter another **existing local directory** (for example RiftForge) to scope Hermes to that project. Hermes then sees that project's repository rules and skills according to its own configuration.

Because a selected workspace can contain sensitive material, the console does not upload workspace contents anywhere itself; any external model/tool traffic is governed by Hermes and the selected provider.

## Frontier model switcher design

The UI reads `console/frontier-models.json`. A provider entry has this shape:

```json
{
  "id": "anthropic",
  "label": "Anthropic / Claude",
  "enabled": true,
  "runtime": "hermes",
  "models": [
    {
      "id": "claude-opus-5-5",
      "label": "Claude Opus 5.5",
      "tier": "frontier",
      "default_effort": "medium"
    }
  ]
}
```

To add a future frontier provider:

1. Implement or confirm a Hermes provider adapter.
2. Add a provider entry and allow-listed models to the registry.
3. Add provider-specific validation only if its CLI invocation differs.
4. Add identity and usage accounting tests.
5. Keep Jev's decision policy provider-neutral: it should select a capability/cost route, not hard-code UI labels.

The console should eventually replace static model metadata with live discovery plus an allow-list so model retirement or renaming fails closed rather than silently switching to another model.

## CIDM integration milestone

The desired full execution path is:

```text
UI creates task envelope
        ↓
Host classification + Jev decision
        ↓
CheckedNetwork issues one-use worker permit
        ↓
HermesGenerativeAdapter
        ↓
Hermes + selected Claude model + project skills
        ↓
Structured candidate + evidence receipt
        ↓
Executable validators
        ↓
Jev post-worker decision
        ↓
commit / repair / retrieve / escalate / stop
```

A `HermesGenerativeAdapter` should implement the repository's existing `GenerativeAdapter` contract rather than creating a parallel orchestration framework. It should record at least:

- requested provider and model;
- reasoning effort;
- workspace and task binding;
- Hermes session/run identifier when exposed;
- tool/skill set requested;
- exit status and duration;
- usage/cost if exposed by the provider;
- output hash and evidence references;
- any served-model identity Hermes reports.

Unknown usage, cost or served identity must remain unknown—not be recorded as zero or assumed to equal the requested model.

## Suggested next phases

**Phase 2 — governed Hermes adapter:** implement `HermesGenerativeAdapter` and route one CIDM unit through it. Preserve the existing one-use permits and post-worker Jev gate.

**Phase 3 — run observability:** show unit state, evidence receipts, token/cost counters, retries, validator results and Jev decisions in the console.

**Phase 4 — skills:** browse and pin Hermes skills per project. Keep skill creation/versioning distinct from Jev's global routing policy.

**Phase 5 — multi-provider frontier switcher:** add providers only after provider identity, auth, accounting and failure-mode tests exist. The switcher should support a manual model choice plus a Jev-controlled `Auto` mode.

**Phase 6 — controlled parallelism:** allow Jev to issue multiple independent worker permits when decomposition is justified; cap concurrency and delegation depth so Hermes local delegation cannot create hidden combinatorial fan-out.

## Security notes

- The server has no user authentication and is intended for localhost only.
- Never place API keys in `frontier-models.json`, JavaScript, URLs or Git.
- Keep secrets in provider/Hermes credential stores or environment variables.
- Treat model output as provisional until validators and Jev accept it.
- Do not enable destructive Hermes behavior globally just to make the UI convenient.
- If remote access is later required, add authentication and an explicit allow-list of workspaces before changing the bind address.

## External references

- Anthropic model overview: https://platform.claude.com/docs/en/models/overview
- Anthropic Models API: https://platform.claude.com/docs/en/api/http/models
- Hermes CLI: https://hermes-agent.nousresearch.com/docs/user-guide/cli/
- Hermes providers: https://hermes-agent.nousresearch.com/docs/integrations/providers
- Hermes configuration: https://hermes-agent.nousresearch.com/docs/user-guide/configuration/
