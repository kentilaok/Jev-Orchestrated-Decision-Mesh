---
name: caber-interstitial-decision-mesh
description: Run or extend training-free CIDM orchestration with Jev decisions between bounded operations and after each Sol-high check. Use for the Caber decision mesh, checked gate architecture, and controlled efficiency evaluation.
---

# Caber Interstitial Decision Mesh

Main contributor and project creator: **Kenneth Vic A. Caber**. This work-in-progress skill applies layered processing and selective context to existing model inference. It trains no model and updates no learned weights. Read [architecture](docs/ARCHITECTURE.md) when adapting the network, and [benchmarks](docs/BENCHMARKS.md) before making efficiency claims.

## Execute the checked workflow

Use five sequential units: **input → interpret → compute → reconcile → output**. For each unit:

1. Give Jev the objective, relevant original evidence, accepted context, and predefined operations. Jev selects a bounded operation or stops.
2. Dispatch exactly that operation using a single-use permit. Workers return a compact artifact: text, structured data, source IDs, five scores from 1–5, and an optional uncalibrated self-probability.
3. Validate the artifact and run available deterministic checks. Ask Jev to authorize a separate high-effort checker call.
4. Give the checker original evidence, the candidate, relevant predecessors, and executable check results. Exclude worker self-scores, self-probability, previous checker opinions, and Jev's preferred outcome.
5. Return **every completed Sol-high result to Jev**, including an invalid-report envelope. Jev chooses `forward`, `repair`, `retrieve_evidence`, `verify_again`, or `stop`. A pass never forwards automatically.
6. Commit only when hard checks pass, the matching checker report passes, and Jev selects forward. A repair creates a new candidate requiring another checker and Jev decision. Keep repairs and rechecks bounded.

The five scores represent correctness, evidence, completeness, constraints, and usefulness. They are worker assessments, not proof. Neither these scores nor probability estimates can override failed hard checks.

Jev selects typed options; it does not generate prose summaries. Code or a reasoning worker constructs summaries, preserving source references and unresolved questions. Request original evidence when compression loses necessary detail. The included demo stops on `retrieve_evidence`; an actual retrieval adapter is future work.

## Control boundaries

- Bind approvals to the precise operation, source versions, accepted context, candidate/checker hashes, and frozen configuration. Reused permits, changed inputs, or missing predecessors must block dispatch or forwarding.
- Jev controls observable operations between inference calls. It cannot intercept a model's hidden internal thinking or individual generated tokens. More granular control requires smaller bounded calls, with measured overhead.
- Use OpenAI-family workers and a separate high-effort checker by default. Model/provider changes must be explicit and recorded. A separate checker context does not guarantee statistically independent errors.
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

Live mode reads `OPENROUTER_API_KEY`. Inspect limits and model/provider availability first. Offline mode is a labeled simulation, not a Jev or Sol evaluation. The executable example handles a bounded production-record calculation; general applications require task-specific producers, validators, and evidence adapters. See [connectors](docs/CONNECTORS.md) and [validation](docs/VALIDATION.md).

## Evaluate honestly

Compare paired tasks at fixed quality and release criteria. Count **all** Jev, worker, and checker tokens, failed attempts, repairs, cost, and latency. Report abstentions and incomplete usage. Never substitute reduced worker tokens for reduced system tokens. The historical pilot increased total tokens; savings for this checked architecture remain unproven. Do not describe CIDM as foolproof or claim precedence over established research.
