---
name: caber-interstitial-decision-mesh
description: "Orchestrate broad, multi-stage projects with CIDM's default five-unit Jev network; use one GPT-6 Luna-low worker only for a self-contained short request. Classify every new input with its carried context. Sol-high review is optional. Do not invoke for simple standalone questions unless explicitly requested."
---

# Jev-Orchestrated Decision Mesh

**Caber Interstitial Decision Mesh (CIDM)**

Main contributor and project creator: **Kenneth Vic A. Caber**. CIDM applies layered processing and selective context to existing model inference. It trains no model and updates no learned weights. Read [architecture](docs/ARCHITECTURE.md) when adapting the network, and [benchmarks](docs/BENCHMARKS.md) before making efficiency claims.

## When to invoke

Use CIDM for a broad project that has meaningful stages, several evidence sources or agents, and acceptance checks that benefit from routing and review. Answer simple standalone yes/no questions and routine one-step tasks directly; do not invoke this skill merely to classify them. When CIDM is invoked, first classify **each new user input together with the carried project context**. A short follow-up to a continuing project is not automatically a short task. Record the input, relevant accepted context, reason for the classification, and selected path. If the input plus context is broad, multi-step, or uncertain, enter the five-unit network by default. Only a self-contained request that can be completed and validated in one bounded response takes the short path: one **GPT-6 Luna low** worker, task-specific validation, then finish. Classify the next user input afresh, using its carried context. If the user explicitly requests a CIDM demonstration or evaluation on a small fixture, label it as a demonstration rather than a recommended deployment route.

## Choose the execution route

For an interactive Codex task signed in with ChatGPT, use host-native GPT-6 Luna/Sol subagents when exact model and effort overrides are available, and call Jev separately through its configured TypeSafe/OpenRouter API. This uses the user's Codex plan allowance for OpenAI work and separate API credits for Jev. Follow the [native execution contract](docs/EXECUTION-ROUTES.md): record each selected route, original source reference, result, optional checker receipt, and Jev decision. The Codex host controls subagent execution; the Python network audit does not automatically verify that host-native path.

The host or controller makes the initial classification from the new input **and** carried context. This is a host assertion, not a Jev decision or a learned task classifier. If scope is missing or uncertain, default to five units. Jev then makes typed decisions inside each unit. Do not let an apparent low-cost subtask or a brief follow-up skip the network while the broader project still needs multiple stages. Within a selected unit, Jev may choose an exact operation or a Luna/Sol worker, request evidence, or stop. The short path calls Luna low once and has no Jev or Sol-high follow-up; do not claim Jev reviewed its output. [The topology contract](examples/topology.request.json) and [bounded `adaptive_run.py` example](docs/EXECUTION-ROUTES.md) apply only to the structured production-record fixture; they do not automatically classify arbitrary Codex project messages. In interactive Codex use, this classification and transition record are skill instructions, not an enforced host-native broker. The saved [fast-exit evidence](research/live-gpt6-fast-exit/README.md) measured an earlier policy that permitted Jev to choose exact code on an easy fixture. It does not validate the new Luna-low short path.

Use `scripts/network_run.py --live` only for the explicitly selected **OpenRouter API route**: it bills Jev, Luna/Sol workers, and Sol-high checkers through OpenRouter. A ChatGPT sign-in or subscription does not authenticate that script. `--offline` is a simulation. Do not silently switch routes or substitute Luna for Jev. If Jev cannot be called, stop the Jev-governed flow. For a price and quality decision, read [routing economics](docs/ROUTING-ECONOMICS.md).

## Execute the five-unit workflow

Use five sequential units: **input → interpret → compute → reconcile → output**. For each unit:

1. Give Jev the objective, relevant original evidence, accepted context, and predefined operations. For generative units, offer **GPT-6 Luna** and **GPT-6 Sol** at `low`, `medium`, `high`, and `xhigh`. Jev selects one exact model and effort or stops. Use deterministic code for units that do not need a generative worker.
2. Dispatch exactly the approved model, effort, and operation using a single-use permit. Workers return a compact artifact: text, structured data, source IDs, five scores from 1–5, and an optional uncalibrated self-probability.
3. Validate the artifact and run available deterministic checks. Return **every completed worker or deterministic result to Jev**. Jev chooses `forward`, `repair`, `escalate`, `check_sol_high`, `retrieve_evidence`, or `stop` from eligible options. A valid candidate may forward without Sol High; failed hard checks never can.
4. If Jev chooses `check_sol_high`, run a separate Sol-high invocation on the exact candidate, original evidence, relevant predecessors, and executable checks. Exclude worker self-scores, self-probability, previous checker opinions, and Jev's preferred outcome.
5. Return **every completed Sol-high result to Jev**, including an invalid-report envelope. Jev then chooses `forward`, `repair`, `escalate`, `verify_again`, `retrieve_evidence`, or `stop`. A checker pass never forwards automatically.
6. Commit only when hard checks pass and Jev selects forward. If a checker was requested, its matching valid passing report is additionally required. Repairs and escalation create new candidates and fresh Jev decisions. Keep attempts and rechecks bounded.

The five scores represent correctness, evidence, completeness, constraints, and usefulness. They are worker assessments, not proof. Neither these scores nor probability estimates can override failed hard checks. Provide Jev with a compact state containing the original objective, frozen constraints, verified facts with source references, unresolved assumptions, contradictions, accepted artifacts, available routes, and remaining budget. Jev chooses from typed options; it does not write that summary itself.

Jev selects typed options; it does not generate prose summaries. Code or a reasoning worker constructs summaries, preserving source references and unresolved questions. Request original evidence when compression loses necessary detail. The included demo stops on `retrieve_evidence`; an actual retrieval adapter is future work.

## Control boundaries

- Bind approvals to the precise operation, source versions, accepted context, candidate hash, optional checker hash, and frozen configuration. Reused permits, changed inputs, or missing predecessors must block dispatch or forwarding.
- Jev controls observable operations between inference calls. It cannot intercept a model's hidden internal thinking or individual generated tokens. More granular control requires smaller bounded calls, with measured overhead.
- The default route catalog contains only GPT-6 Luna and GPT-6 Sol at `low` through `xhigh`; GPT-5.6 and Terra are excluded. Sol `xhigh` is available for difficult general planning. Prefer the least costly option likely to meet the local quality bar, but treat Jev's choice as a hypothesis until measured.
- When Jev requests extra review, use **GPT-6 Sol high** and return its result to Jev. Sol High is not a prerequisite for every unit. Astra is absent unless the user specifically authorizes it and the run configuration sets `astra_explicitly_authorized: true` with sufficient cost reservations; that adds **Astra low** as an option. Do not silently select it. Model/provider changes must be explicit and recorded. A separate checker context does not guarantee statistically independent errors.
- Keep credentials in the environment. Preserve attempt logs, unknown usage, and failure status. Host callbacks are trusted code; this controller is not a sandbox.
- Set budgets for Jev calls and reported tokens, worker calls, checker calls, and total API dollars. The intended short path has one Luna-low worker call and no Jev or checker call. A token ceiling can reject an over-budget Jev decision after usage is reported; it cannot undo charges already incurred. Report [orchestration metrics](docs/ORCHESTRATION-BUDGETS.md) and keep unknown counters unknown.
- Do not initiate paid inference merely to explain or edit the architecture. An explicit bounded live-run request authorizes that run without another confirmation ritual.

## Reference commands

Python 3.10+; standard library only. Replace `<skill>` with this skill directory and use a new task-workspace output directory.

```text
python <skill>/scripts/network_run.py --offline --task <skill>/examples/production-records.json --out <new-run-dir>
python <skill>/scripts/audit_network.py <new-run-dir>/result.json
python <skill>/scripts/adaptive_run.py --offline --task <skill>/examples/production-records.json --out <new-run-dir>
python <skill>/scripts/adaptive_run.py --offline --task <skill>/examples/production-records.json --classification <host-assertion.json> --context-summary <carried-context> --out <new-run-dir>
python <skill>/scripts/adaptive_run.py --live --config <skill>/examples/config.openrouter.json --task <skill>/examples/production-records.json --out <new-run-dir>
python <skill>/scripts/network_run.py --live --config <skill>/examples/config.openrouter.json --task <skill>/examples/production-records.json --out <new-run-dir>
python -m unittest discover -s <skill>/tests -v
```

The OpenRouter runner reads `OPENROUTER_API_KEY`. Inspect limits and model/provider availability first. Omit `--classification` for the conservative five-unit default; for the short fixture, create an exact task-and-context-bound assertion as shown in [execution routes](docs/EXECUTION-ROUTES.md#scope-classification-before-an-api-run). The runner checks the assertion's hash, not whether the host classified the work correctly. Offline mode is a labeled simulation, not a Jev or Sol evaluation. The executable example handles a bounded production-record calculation; its `context_summary` participates in classification and the Jev entry state, while the five-unit demo itself consumes the structured task and original records. General applications require task-specific producers, validators, and evidence adapters. See [connectors](docs/CONNECTORS.md) and [validation](docs/VALIDATION.md).

## Evaluate honestly

Compare paired tasks at fixed quality and release criteria. Count **all** Jev, worker, and checker tokens, failed attempts, repairs, cost, and latency. Track Jev tokens divided by worker tokens, cost multipliers, actual early exits, and quality outcomes; leave avoidable-call counts unknown without a counterfactual rubric. Report abstentions and incomplete usage. Never substitute reduced worker tokens for reduced system tokens. The historical pilot increased total tokens; broad-project savings remain unmeasured. Do not describe CIDM as foolproof or claim precedence over established research.
