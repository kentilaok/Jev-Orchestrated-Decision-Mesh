# CIDM execution routes

CIDM separates **who chooses the next action** from **who generates or checks an artifact**. Jev is TypeSafe's decision model. GPT-6 Luna and Sol are OpenAI generative workers. A Luna pass is not a Jev pass.

## Choose the transport before a run

| Route | Luna/Sol worker and optional Sol-high checker | Jev decisions | Usage boundary | Implemented here |
|---|---|---|---|---|
| Codex with ChatGPT sign-in | Codex-hosted model-specific subagents or Codex SDK/CLI threads | Explicit TypeSafe/OpenRouter Jev call | Codex consumes plan usage or ChatGPT credits; Jev consumes separate API credits | Skill-guided orchestration; no automatic native broker in the Python reference runner |
| OpenRouter API | OpenRouter model calls | OpenRouter Jev endpoint | All model calls consume OpenRouter API credits | `scripts/network_run.py --live` |
| Offline simulation | Deterministic fixture functions | Fake typed choices | No provider usage | `scripts/network_run.py --offline` |

The recommended interactive route, when model-specific subagents are available in a ChatGPT-signed-in Codex session, is **Codex-native Luna/Sol plus separately authenticated Jev**. This uses the user's included Codex allowance until its limits apply. It does not convert a ChatGPT subscription into an OpenAI Platform or OpenRouter API allowance. `network_run.py --live` always uses OpenRouter for Jev **and** workers/checkers; it is not a subscription-backed run. If Codex was signed in with an API key, its calls follow API pricing rather than included plan usage. See [OpenAI Docs authentication](https://learn.chatgpt.com/docs/auth) and [Codex pricing](https://learn.chatgpt.com/docs/pricing).

The Codex-native route is an agent workflow described by this skill, not an automatically enforced adapter in `network_run.py`. Its model identity, token totals, and approval evidence must be logged by the host; the Python run audit covers only its own runner. If that evidence is unavailable, report the gap instead of claiming a machine-verified run. For a repeatable standalone application, use the OpenRouter runner or implement and validate a separate native adapter.

## Scope classification before an API run

The host/controller classifies the current input together with accepted project context before running `scripts/adaptive_run.py`. Record the classification and bind it to the exact task and context. The classification is an assertion by the host, not a Jev or learned model judgment; the bounded runner checks its binding, not its semantic truth. A broad, multi-step, uncertain, or unclassified task enters the five-unit branch by default. Jev's entry choice on that branch is limited to `five_unit`, `retrieve_evidence`, or `stop`; it cannot replace the graph with a single worker or exact code. A request explicitly classified as short and self-contained runs **one GPT-6 Luna-low worker**, validates its result, and finishes without Jev or Sol-high calls. The next user input requires a fresh classification that includes any continuing project context.

The short route is an explicit one-worker exit, not a claim of Jev or five-unit review. If final hard checks fail, withhold the answer. The CLI handles only the bounded production-record fixture; the host supplies the classification and its context binding. It is not a general language or project classifier. The saved [fast-exit calls](../research/live-gpt6-fast-exit/README.md) belong to the earlier policy: one Jev decision selected exact code on the small fixture. They are historical evidence of that path, not a measurement of this Luna-low short route.

For the fixture, `--context-summary` passes the carried context (at most 2,000 characters), and `--classification` accepts JSON with exactly `snapshot_hash`, `multiple_steps`, `broad_project`, `ambiguous`, and `depends_on_context`. The four signals must be booleans. Compute `snapshot_hash` with `input_snapshot_hash(task, context_summary)` from `scripts/adaptive_run.py`; a changed task or context invalidates the assertion. All four `false` means short and self-contained. Any `true`, or no classification file, means broad or uncertain. For example, from the repository root, create a file only after the host has established that this particular fixture is independent:

```python
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path("scripts").resolve()))
from adaptive_run import input_snapshot_hash

task = json.loads(Path("examples/production-records.json").read_text(encoding="utf-8"))
context = ""
classification = {
    "snapshot_hash": input_snapshot_hash(task, context),
    "multiple_steps": False,
    "broad_project": False,
    "ambiguous": False,
    "depends_on_context": False,
}
Path("short-classification.json").write_text(json.dumps(classification), encoding="utf-8")
```

Run that short fixture with `python scripts/adaptive_run.py --offline --task examples/production-records.json --classification short-classification.json --out <fresh-dir>`. Omit `--classification` to exercise the conservative five-unit default. In live mode, add `--live --config examples/config.openrouter.json` in place of `--offline`; it consumes API credits. The JSON is a host assertion, so a false claim can still misroute work despite a valid hash. A new input or changed context requires a new classification file.

## Codex-native procedure

1. Invoke CIDM for a broader project with meaningful stages, evidence, or review needs, or when explicitly requested. Answer simple standalone yes/no questions and routine one-step tasks directly, without this skill. For every new input to an invoked CIDM workflow, classify the input with accepted project context and record the rationale and context version. If broad, multi-step, or uncertain, use the five-unit network; Jev may retrieve missing evidence or stop, but does not shorten the topology. If short and self-contained, make one GPT-6 Luna-low call, apply task-specific hard checks, and finish. Confirm the active Codex sign-in and model availability before dispatch. Use a dedicated workspace for the ledger. Do not export ChatGPT session tokens or use them as an API key.
2. For the five-unit route, record the user's objective, constraints, source IDs and hashes, completed units, available routes, budget mode, and outstanding questions. Send a bounded state plus typed route options to Jev with `scripts/jev_decide.py`. The key is read from `OPENROUTER_API_KEY`; record Jev usage and provider identity.
3. Execute only the option Jev selected. For a generative unit, request a host-native subagent with the exact `gpt-6-luna` or `gpt-6-sol` model and `low`/`medium`/`high`/`xhigh` effort. Reserve Sol `xhigh` for planning that warrants it. When model overrides or subagents are unavailable, stop or deliberately choose the separately billed API route before dispatch. Do not silently substitute models. Deterministic units use code.
4. Give the worker original source references and only the relevant accepted predecessor artifacts. Require a compact typed artifact, five 1–5 self-scores, and a source map. Keep full original evidence retrievable. Treat self-scores and model probability as unverified observations.
5. Apply task-specific deterministic checks. Return every completed worker or deterministic result to Jev. Jev chooses `forward`, `repair`, `escalate`, `check_sol_high`, `retrieve_evidence`, or `stop`. The broker omits `forward` when a hard check fails. Self-scores and confidence cannot override those checks.
6. Only if Jev chooses `check_sol_high`, invoke a distinct `gpt-6-sol` **high** checker on the exact candidate and evidence. Hide the worker's self-scores, probability, previous checker opinions, and Jev's preferred answer. Send every completed checker result, including a bounded invalid-result envelope, back to Jev for a further choice.
7. Commit only if hard checks pass and Jev chooses `forward`. If a Sol-high check was requested, its matching report must also be valid and passing. Keep permits single-use, repairs and rechecks bounded, and failed or unknown conditions uncommitted. Record the model/effort, source and artifact hashes, optional checker receipt, both Jev decisions when applicable, attempted calls, and usage. Do not claim that Jev intervened within one inference call.

For programmatic plan-backed Codex calls, official options include the [Codex SDK](https://learn.chatgpt.com/docs/codex-sdk), [non-interactive `codex exec`](https://learn.chatgpt.com/docs/non-interactive-mode), and [App Server](https://learn.chatgpt.com/docs/app-server). These run the Codex agent harness under its configured sign-in; they do not provide raw Responses API calls under a subscription. `codex exec --json` emits `turn.completed.usage` with input, cached input, output, and reasoning output counters. Count all child threads and verify whether any host aggregate already includes them before summing. Cached input is part of input, and reasoning output is part of output; neither is added twice.

For example, a trusted local runner can invoke a selected worker as `codex exec -m gpt-6-luna -c model_reasoning_effort=low -s read-only --output-schema <artifact-schema.json> --json -`, passing only that unit's instructions and evidence through stdin. The runner must validate the final artifact, record the JSONL usage and actual model information available from the host, and require a fresh Jev decision before the next dispatch. [Codex configuration](https://learn.chatgpt.com/docs/config-file/config-reference) documents `model_reasoning_effort`; the [non-interactive guide](https://learn.chatgpt.com/docs/non-interactive-mode) documents JSONL usage and structured output. This command is an integration pattern; the included `network_run.py` does not execute it.

## Capacity and failure rule

The five-unit reference always returns each completed worker output to Jev. The API runner reserves capacity for a worker **and its following Jev decision**. If Jev requests a checker, the runner similarly reserves the Sol-high call and the Jev decision after it. The short route ends after its one validated Luna-low result. Native Codex usage limits are plan-managed, so the skill can request a bounded run and inspect available usage, but it cannot guarantee the host will admit the next turn. See [orchestration budgets](ORCHESTRATION-BUDGETS.md) for call and token ceilings.

When Jev is unavailable, stop the CIDM flow. A Luna classifier may help summarize state, but it does not become Jev. Do not use a model-generated replacement decision while reporting the result as Jev-governed.
