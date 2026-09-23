---
name: caber-interstitial-decision-mesh
description: Run training-free CIDM with Jev choosing a direct or checked topology, GPT-6 Luna/Sol worker routes, and post-checker decisions. Use for the Caber decision mesh and measured routing efficiency; the checked five-unit branch has a mandatory Sol-high review.
---

# Jev-Orchestrated Decision Mesh

**Caber Interstitial Decision Mesh (CIDM)**

Main contributor and project creator: **Kenneth Vic A. Caber**. CIDM applies layered processing and selective context to existing model inference. It trains no model and updates no learned weights. Read [architecture](docs/ARCHITECTURE.md) when adapting the network, and [benchmarks](docs/BENCHMARKS.md) before making efficiency claims.

## Choose the execution route

For an interactive Codex task signed in with ChatGPT, use host-native GPT-6 Luna/Sol subagents when exact model and effort overrides are available, and call Jev separately through its configured TypeSafe/OpenRouter API. This uses the user's Codex plan allowance for OpenAI work and separate API credits for Jev. Follow the [native execution contract](docs/EXECUTION-ROUTES.md): record each selected route, original source reference, result, checker receipt, and Jev decision. The Codex host controls subagent execution; the Python checked-network audit does not automatically verify that host-native path.

Before invoking the five-unit network for a general CIDM request, ask Jev once to choose among **deterministic computation, a bounded direct Luna/Sol worker, the checked five-unit path, evidence retrieval, or stop**. Use [the typed topology request](examples/topology.request.json) as a schema example, substituting the actual goal and evidence. If the user specifically requests the checked network, retain that path. On a direct branch, apply domain checks and report the branch honestly; do not imply that a Sol-high checker ran. The single-fixture [measured comparison](docs/ROUTING-ECONOMICS.md) shows why a tiny arithmetic task should not automatically incur five Sol-high checks. This admission choice is skill-guided; the supplied `network_run.py` always runs its five-unit reference once called.

Use `scripts/network_run.py --live` only for the explicitly selected **OpenRouter API route**: it bills Jev, Luna/Sol workers, and Sol-high checkers through OpenRouter. A ChatGPT sign-in or subscription does not authenticate that script. `--offline` is a simulation. Do not silently switch routes or substitute Luna for Jev. If Jev cannot be called, stop the Jev-governed flow. For a price and quality decision, read [routing economics](docs/ROUTING-ECONOMICS.md).

## Execute the checked workflow

Use five sequential units: **input → interpret → compute → reconcile → output**. For each unit:

1. Give Jev the objective, relevant original evidence, accepted context, and predefined operations. For generative units, offer **GPT-6 Luna** and **GPT-6 Sol** at `low`, `medium`, `high`, and `xhigh`. Jev selects one exact model and effort or stops. Use deterministic code for units that do not need a generative worker.
2. Dispatch exactly the approved model, effort, and operation using a single-use permit. Workers return a compact artifact: text, structured data, source IDs, five scores from 1–5, and an optional uncalibrated self-probability.
3. Validate the artifact and run available deterministic checks. Ask Jev to authorize a separate high-effort checker call.
4. Give the checker original evidence, the candidate, relevant predecessors, and executable check results. Exclude worker self-scores, self-probability, previous checker opinions, and Jev's preferred outcome.
5. Return **every completed Sol-high result to Jev**, including an invalid-report envelope. Jev chooses `forward`, `repair`, `retrieve_evidence`, `verify_again`, or `stop`. A pass never forwards automatically.
6. Commit only when hard checks pass, the matching checker report passes, and Jev selects forward. A repair creates a new candidate requiring another checker and Jev decision. Keep repairs and rechecks bounded.

The five scores represent correctness, evidence, completeness, constraints, and usefulness. They are worker assessments, not proof. Neither these scores nor probability estimates can override failed hard checks. Provide Jev with a compact state containing the original objective, frozen constraints, verified facts with source references, unresolved assumptions, contradictions, accepted artifacts, available routes, and remaining budget. Jev chooses from typed options; it does not write that summary itself.

Jev selects typed options; it does not generate prose summaries. Code or a reasoning worker constructs summaries, preserving source references and unresolved questions. Request original evidence when compression loses necessary detail. The included demo stops on `retrieve_evidence`; an actual retrieval adapter is future work.

## Control boundaries

- Bind approvals to the precise operation, source versions, accepted context, candidate/checker hashes, and frozen configuration. Reused permits, changed inputs, or missing predecessors must block dispatch or forwarding.
- Jev controls observable operations between inference calls. It cannot intercept a model's hidden internal thinking or individual generated tokens. More granular control requires smaller bounded calls, with measured overhead.
- The default route catalog contains only GPT-6 Luna and GPT-6 Sol at `low` through `xhigh`; GPT-5.6 and Terra are excluded. Sol `xhigh` is available for difficult general planning. Prefer the least costly option likely to meet the local quality bar, but treat Jev's choice as a hypothesis until measured.
- Keep the checker at **GPT-6 Sol high**. Astra is absent unless the user specifically authorizes it and the run configuration sets `astra_explicitly_authorized: true` with sufficient cost reservations; that adds **Astra low** as an option. Do not silently select it. Model/provider changes must be explicit and recorded. A separate checker context does not guarantee statistically independent errors.
- Keep credentials in the environment. Preserve attempt logs, unknown usage, and failure status. Host callbacks are trusted code; this controller is not a sandbox.
- Do not initiate paid inference merely to explain or edit the architecture. An explicit bounded live-run request authorizes that run without another confirmation ritual.

## Reference commands

Python 3.10+; standard library only. Replace `<skill>` with this skill directory and use a new task-workspace output directory.

```text
python <skill>/scripts/network_run.py --offline --task <skill>/examples/production-records.json --out <new-run-dir>
python <skill>/scripts/audit_network.py <new-run-dir>/result.json
python <skill>/scripts/network_run.py --live --config <skill>/examples/config.openrouter.json --task <skill>/examples/production-records.json --out <new-run-dir>
python -m unittest discover -s <skill>/tests -v
```

The OpenRouter runner reads `OPENROUTER_API_KEY`. Inspect limits and model/provider availability first. Offline mode is a labeled simulation, not a Jev or Sol evaluation. The executable example handles a bounded production-record calculation; general applications require task-specific producers, validators, and evidence adapters. See [connectors](docs/CONNECTORS.md) and [validation](docs/VALIDATION.md).

## Evaluate honestly

Compare paired tasks at fixed quality and release criteria. Count **all** Jev, worker, and checker tokens, failed attempts, repairs, cost, and latency. Report abstentions and incomplete usage. Never substitute reduced worker tokens for reduced system tokens. The historical pilot increased total tokens; savings for this checked architecture remain unproven. Do not describe CIDM as foolproof or claim precedence over established research.
