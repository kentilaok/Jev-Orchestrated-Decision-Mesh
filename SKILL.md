---
name: caber-interstitial-decision-mesh
description: "Orchestrate broad, multi-stage projects with CIDM: Jev routes GPT-6 Luna/Sol work and decides after every output; Sol-high review is optional. Use for projects needing evidence, delegation, and bounded review. Do not invoke for simple yes/no questions or routine one-step tasks."
---

# Jev-Orchestrated Decision Mesh

**Caber Interstitial Decision Mesh (CIDM)**

Main contributor and project creator: **Kenneth Vic A. Caber**. CIDM applies layered processing and selective context to existing model inference. It trains no model and updates no learned weights. Read [architecture](docs/ARCHITECTURE.md) when adapting the network, and [benchmarks](docs/BENCHMARKS.md) before making efficiency claims.

## When to invoke

Use CIDM for a broad project that has meaningful stages, several evidence sources or agents, and acceptance checks that benefit from routing and review. Answer simple yes/no questions and routine one-step tasks directly; do not start Jev, a subagent, or this skill merely to classify them. Once a project qualifies, Jev is the first CIDM decision. A small subtask *inside* that project may still be routed to deterministic code or Luna Low. If the user explicitly requests a CIDM demonstration or evaluation on a small fixture, label it as a demonstration rather than a recommended deployment route.

## Choose the execution route

For an interactive Codex task signed in with ChatGPT, use host-native GPT-6 Luna/Sol subagents when exact model and effort overrides are available, and call Jev separately through its configured TypeSafe/OpenRouter API. This uses the user's Codex plan allowance for OpenAI work and separate API credits for Jev. Follow the [native execution contract](docs/EXECUTION-ROUTES.md): record each selected route, original source reference, result, optional checker receipt, and Jev decision. The Codex host controls subagent execution; the Python network audit does not automatically verify that host-native path.

Before invoking the five-unit network for a qualifying CIDM project, ask Jev **one compact typed fast-exit question**: exact code, one Luna-low worker, one Sol-high worker, five units, retrieve evidence, or stop. Use [the typed topology request](examples/topology.request.json) for the decision contract. The [bounded `adaptive_run.py` example](docs/EXECUTION-ROUTES.md) implements that choice for structured production records. It does not turn this skill into a general-purpose application. A direct branch uses task-specific checks and has no automatic Jev follow-up; do not claim five-unit review. If the user specifically requests five units, preserve that topology. [Measured fast-exit evidence](research/live-gpt6-fast-exit/README.md) shows one Jev choice can avoid a repeated gate loop on a checkable subtask.

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
- Set budgets for Jev calls and reported tokens, worker calls, checker calls, and total API dollars. The fast-exit direct branch admits one Jev choice and at most one worker call. A token ceiling can reject an over-budget Jev decision after usage is reported; it cannot undo charges already incurred. Report [orchestration metrics](docs/ORCHESTRATION-BUDGETS.md) and keep unknown counters unknown.
- Do not initiate paid inference merely to explain or edit the architecture. An explicit bounded live-run request authorizes that run without another confirmation ritual.

## Reference commands

Python 3.10+; standard library only. Replace `<skill>` with this skill directory and use a new task-workspace output directory.

```text
python <skill>/scripts/network_run.py --offline --task <skill>/examples/production-records.json --out <new-run-dir>
python <skill>/scripts/audit_network.py <new-run-dir>/result.json
python <skill>/scripts/adaptive_run.py --offline --task <skill>/examples/production-records.json --out <new-run-dir>
python <skill>/scripts/adaptive_run.py --live --config <skill>/examples/config.openrouter.json --task <skill>/examples/production-records.json --out <new-run-dir>
python <skill>/scripts/network_run.py --live --config <skill>/examples/config.openrouter.json --task <skill>/examples/production-records.json --out <new-run-dir>
python -m unittest discover -s <skill>/tests -v
```

The OpenRouter runner reads `OPENROUTER_API_KEY`. Inspect limits and model/provider availability first. Offline mode is a labeled simulation, not a Jev or Sol evaluation. The executable example handles a bounded production-record calculation; general applications require task-specific producers, validators, and evidence adapters. See [connectors](docs/CONNECTORS.md) and [validation](docs/VALIDATION.md).

## Evaluate honestly

Compare paired tasks at fixed quality and release criteria. Count **all** Jev, worker, and checker tokens, failed attempts, repairs, cost, and latency. Track Jev tokens divided by worker tokens, cost multipliers, actual early exits, and quality outcomes; leave avoidable-call counts unknown without a counterfactual rubric. Report abstentions and incomplete usage. Never substitute reduced worker tokens for reduced system tokens. The historical pilot increased total tokens; broad-project savings remain unmeasured. Do not describe CIDM as foolproof or claim precedence over established research.
