# Arsenal V1 — implementation guide

This page documents what is built for [Arsenal V1](ARSENAL-V1.md), how to use each component, and where each one stops. Every component is standard-library Python, tested offline, and governed by the same rule:

> A tool can suggest a route, but only Jev, or an owner-admitted compiled policy, can authorize a state transition.

**Evidence level:** offline tests and local smoke checks only. No component here has a matched live efficiency or quality result. Do not claim token, cost, or frontier-call savings from it until a frozen evaluation measures them.

| Component | Module | Phase | Authority it has |
|---|---|---|---|
| Capability permits | `scripts/capability_permits.py` | B (item 18) | Records and enforces authority; grants none by itself |
| Frontier providers | `scripts/frontier_providers.py` | B | None; runs only with a consumed `frontier.run` permit |
| Fast Path executor | `scripts/arsenal_fastpath.py` | A (14–17) | Commit eligibility only under an owner policy plus passing validators |
| Calibration thresholds | `scripts/arsenal_calibration.py` | A2 | None; a report never enables execution |
| MCP catalogue | `scripts/mcp_registry.py` | C | None; calls need `mcp.read` or `mcp.mutate` permits |
| Hybrid retrieval | `scripts/retrieval.py` | D | None; scores are ranking evidence |
| Sandbox and secrets | `scripts/sandbox.py` | F | None; never commits |
| Browser permit classes | `scripts/browser_capability.py` | F | None; every action needs its class permit |
| Telemetry | `scripts/telemetry.py` | G | None; the journal stays authoritative |
| Checkpoint resume | `scripts/recovery_protocol.py` | H | None; a checkpoint is a state record, not a permit |
| Operator Console | `scripts/operator_console.py`, `console/index.html` | B/G | Operator actions only; live runs need explicit confirmation |

## Capability permits

`PermitAuthority.issue(capability, scope, basis)` returns a single-use permit whose scope hash binds the exact action. `consume` checks the capability, scope hash, expiry, and single use. `receipt` records the outcome hash. The ledger is hash-chained JSONL, tamper-evident for partial edits but not for a full rewrite.

Accepted bases: `jev_decision`, `cidm_mesh_dispatch` (names the mesh dispatch event and its gate), `host_short_classification`, `cidm_recovery_evidence`, `compiled_policy` (Fast Path only), and `operator`. **Strong** capabilities need a Jev basis: `mcp.mutate`, `browser.mutate`, `browser.submit_transaction`, `sandbox.import_artifacts`, `secret.use`.

The native broker now issues one `frontier.run` permit per worker or checker call. Each permit names the exact dispatch event and gate from the journal. `audit_permit_ledger` checks issue, consumption, receipts, and journal binding. A failed permit audit withholds release, like a failed journal audit. Live runs write `permits.jsonl` next to `result.json`.

## Frontier providers (Phase B)

One contract over both hosts: `status()`, `list_models()`, `capabilities()`, `run(request, permit)`, `cancel(run_id)`, `usage(run_id)`.

```bash
python scripts/frontier_providers.py status --provider claude
python scripts/frontier_providers.py models --provider codex
python scripts/frontier_providers.py coverage --provider codex
```

- **Claude Code** is the primary worker. Status comes from `claude auth status --json`, with account and organization IDs reduced to a short opaque reference. The provider warns when `ANTHROPIC_API_KEY` could switch billing away from the subscription. Claude Code has no non-interactive model catalogue, so its presets are reported as `unverified` and never as `covered`.
- **Codex** models come from the account catalogue (`codex debug models`). Codex serves that catalogue from a local cache it refreshes in the background, so the result includes `cache_age_seconds`. On this project's first check, a stale cache omitted GPT-6 Luna and Sol until Codex refreshed it.
- `route_coverage` compares CIDM's frozen route catalogue (every worker route plus the checker) with the account catalogue. **A live native broker run fails closed with `route_preflight_failed` before any paid call** when coverage is `partial` or `unavailable`. It never substitutes a model. `--skip-route-preflight` disables this check and records `skipped`.

## Fast Path (Phase A, items 14–17)

The registry still decides *eligibility* (admitted hashes, low risk, `frontier_required: false`, declared validators, scope, preapproved operation, exact bug key). `FastPathExecutor` adds the remaining conditions:

1. An owner policy file enables Fast Path and pins each skill's exact `skill_hash`, `manifest_hash`, and operations. **No policy file means disabled.**
2. Optionally, the policy cites a calibration `report_hash` that met the owner's bar.
3. The operation is registered trusted host code, marked reversible, with its required inputs present.
4. Every validator the manifest declares is registered.
5. The skill files are re-hashed immediately before execution.
6. One `fast_path.execute` permit with a `compiled_policy` basis is consumed.

All validators passing gives `validated_under_compiled_policy` with `commit_eligible: true`; the host performs the commit. Anything else escalates to Jev with the receipts so far and a `recovery_input`. The executor's ledger records frontier-call avoidance only for executed, validated attempts: `python scripts/arsenal_fastpath.py summary --ledger ~/.jev/arsenal/fast-path.jsonl`. `check` reports readiness without executing anything.

Policy shape:

```json
{"schema_version": 1, "enabled": true, "owner": "owner-id", "approved_at": "2026-10-08",
 "skills": {"skill-id": {"skill_hash": "<sha256>", "manifest_hash": "<sha256>", "operations": ["op"]}},
 "calibration": {"report_hash": "<sha256 of an accepted threshold report>"}}
```

Calibration additions: `evaluate` now counts **negative transfer**, meaning a loaded skill or lesson that the independent reviewer says was the wrong one. `thresholds` computes a Wilson lower bound on Fast Path precision over reviewed real runs, and requires a minimum sample and zero false positives:

```bash
python scripts/arsenal_calibration.py --ledger ~/.jev/arsenal/calibration.jsonl thresholds \
  --min-reviewed 30 --min-precision-lower-bound 0.95
```

The report is hash-bound to the ledger head and always says `fast_path_enablement_allowed: false`. Only an owner policy that cites its hash can use it.

## MCP capability catalogue (Phase C)

```bash
python scripts/mcp_registry.py servers                      # read configs; starts nothing
python scripts/mcp_registry.py refresh --server Roblox_Studio
python scripts/mcp_registry.py search --query "read script source" --access read
python scripts/mcp_registry.py classify --server S --tool T --access read --owner owner-id
```

- Discovery reads project `.mcp.json`, Claude Code `~/.claude.json` (user and per-project), and Codex `~/.codex/config.toml` (Python 3.11+). Only environment variable *names* are reported.
- The stdlib clients speak MCP over stdio (newline-delimited JSON-RPC) or streamable HTTP. `refresh` starts one configured server, explicitly.
- Access classes are conservative. Precedence: owner override, then the built-in Roblox Studio profile from [MCP evidence](MCP-EVIDENCE.md), then server annotations, then `unknown`. Unknown tools are never treated as read-only.
- `search` returns compact cards (server, tool, one-sentence summary, access class, required arguments, schema hash). It reports `bytes_avoided` against the full catalogue, in bytes rather than tokens.
- `call_tool` checks arguments against the schema, consumes an `mcp.read` or `mcp.mutate` permit bound to the server, tool, argument hash, and schema hash, and returns an evidence receipt plus a bounded source (≤ 1,200 characters, truncation flagged). The full result is kept in an evidence directory.

**Recovery integration.** `McpEvidenceRetriever` runs a bounded plan of read-only calls. With `--gate-policy recovery`, Jev's `retrieve_evidence` becomes the next planned read: a new hashed source, then a fresh Jev gate on the same unit. The standalone broker no longer has to halt.

```bash
python scripts/native_transition_broker.py --live --gate-policy recovery \
  --task request.json --evidence-plan plan.json --out runs/native-mcp-001
```

Plan shape: `{"steps": [{"server": "Roblox_Studio", "tool": "script_read", "arguments": {...}, "title": "..."}], "max_calls": 4}`. Every step must be a read-class tool.

## Hybrid retrieval (Phase D)

```bash
python scripts/retrieval.py ingest --namespace project --root ./docs
python scripts/retrieval.py search --namespace project --query "rollback owner"
python scripts/retrieval.py embed --model BAAI/bge-small-en-v1.5          # optional, needs fastembed
```

- `LocalHybridIndex` chunks documents to ≤ 1,100 characters and keys every chunk by ID and content hash. It filters by namespace and access group as payload filters, not prompt instructions, and fuses BM25 with optional dense rankings by RRF.
- Reranking is local first (`LocalCrossEncoder`, FastEmbed), with `HostedReranker` (Cohere `v2/rerank` or Voyage `v1/rerank`, key from the environment, model named explicitly) used by `FallbackReranker` only when local is unavailable or weak.
- `QdrantRetriever` reaches managed Qdrant over REST (HTTPS, or a local URL). It runs dense or dense+sparse RRF queries with namespace and access filters, and drops any point whose payload text no longer matches its hash.
- `RetrievalEvidenceRetriever` feeds recovery runs under `retrieval.query` permits (`--retrieval-index`, `--retrieval-namespace`).

## Sandbox, secrets, and browser (Phase F)

`DockerSandboxProvider` implements `create` / `exec` / `export_artifacts` / `destroy` / `reap_expired`:

- **Isolation:** `--network none`, `--cap-drop ALL`, `no-new-privileges`, and CPU, memory, and PID limits. `sleep <ttl>` as PID 1 makes the container stop itself at the TTL.
- **Egress:** V1 Docker supports `none` only. An allowlist needs a proxying provider and is refused.
- **Snapshots:** a deterministic tar of regular files, skipping `.git`, `node_modules`, virtualenvs, and `runs`.
- **Artifact import:** a **strong** capability. Allowlisted globs only, regular files only, path-escape checked, every file hashed.
- **Secrets:** `SecretBroker` resolves owner-registered `secret://env/NAME` references at exec time into the Docker CLI's environment and passes them by name (`-e NAME`). Values never appear in argv, ledgers, or prompts, and are redacted from captured output. Using a secret needs a separate strong `secret.use` permit.
- **Smoke test:** the real container test is opt-in (`CIDM_RUN_DOCKER_TESTS=1`, local image `node:22-alpine`). It was run and passed on the build workstation.

`browser_capability` maps actions to `browser.read`, `browser.extract`, `browser.mutate`, and `browser.submit_transaction`. Clicks on submit, pay, buy, send, publish, or delete controls, and Enter, escalate to `submit_transaction`. `BrowserSession` enforces an origin allowlist (including after redirects) on an injected Playwright-style page. `launch_playwright` is used only when Playwright is installed.

## Telemetry (Phase G)

```bash
python scripts/telemetry.py runs/native-001/result.json --summary
python scripts/telemetry.py runs/native-001/result.json --out spans.json
python scripts/telemetry.py runs/native-001/result.json --endpoint http://127.0.0.1:6006
```

Spans cover the run, each unit, every Jev decision, and every frontier call, with OpenInference span kinds and `cidm.event_id` links back to the journal. Journal events have no wall-clock timestamps, so span times are **ordinal** and flagged `cidm.timing=ordinal_not_wallclock`. Unknown usage is omitted and flagged, never written as zero. The export is OTLP/JSON. An OpenTelemetry Collector accepts it; route Phoenix through a collector if your Phoenix build accepts only protobuf. `run_summary` lists the ARSENAL-V1 §14.2 measurements that a result actually contains.

## Checkpoint resume (Phase H)

A recovery run that pauses (`paused_recoverable`) writes `checkpoint.json`. The file is hash-bound and records the mesh, committed prefix, sources, policy, recovery rounds, and carried call receipts. Resume in a **new** output folder:

```bash
python scripts/native_transition_broker.py --live --gate-policy recovery --task request.json \
  --resume runs/first/checkpoint.json --resume-sources new-evidence.json --operator owner-id \
  --out runs/first-resumed
```

Restore verifies:

- the bundle hash, task snapshot hash, and configuration hash;
- the policy version, source hashes, and committed artifact hashes;
- the checkpoint's mesh state hash.

Every pre-checkpoint Jev gate is marked spent. Added evidence (new IDs only) and `--reset-recovery-rounds` are operator actions, recorded with the operator ID. Resumed runs pass the same journal, native-call, and permit audits.

## Operator Console

See [Operator Console](OPERATOR-CONSOLE.md). It exposes all of the above read-only, plus three explicit actions: a bounded smoke test, a live broker run with spend confirmation, and resume.

## Hermes and local tool setup

`scripts/hermes_paths.py` finds Hermes at `HERMES_HOME`, then `~/.hermes`, then `%LOCALAPPDATA%\hermes` (the Windows installer location). CIDM-managed skills live in a separate folder, `~/.jev/hermes-skills`, which Hermes loads read-only through `skills.external_dirs`:

```bash
python scripts/install_hermes_skill.py            # wrapper skill + external_dirs entry (config.yaml backed up)
python scripts/arsenal_registry.py scan --skills-dir "$LOCALAPPDATA/hermes/skills"
pip install -r requirements-arsenal-semantic.txt  # optional FastEmbed CPU layer
python scripts/arsenal_semantic.py build --model BAAI/bge-small-en-v1.5
pip install playwright==1.62.0 && python -m playwright install chromium   # optional browser tier
```

The wrapper is regenerated from the repository's `SKILL.md`; edit the repository copy and re-run the installer. The Matt Pocock importer refuses every active skill root, including the Hermes home, `~/.jev/hermes-skills`, and Claude Code, Codex and `~/.agents` skill folders.

## Not built (needs accounts, downloads, or an owner decision)

- **LeanCTX and Headroom** context gateways: external tools. The MCP catalogue's compact search is the in-repo measurement point.
- **Managed services:** a provisioned Qdrant Cloud collection, a hosted reranker key, a running Phoenix instance, and an E2B or Daytona sandbox. Adapters exist for Qdrant and the rerankers; each runs only when configured.
- **Hermes dispatch adapter:** Hermes loads the CIDM skill and the console talks to Hermes' dashboard API, but running Hermes procedures *inside* a permit-bound CIDM unit remains future work.
- **Methodology skill activation:** the Matt Pocock core skills can be staged in quarantine from the pinned checkout; copying a reviewed skill into an active skill folder and hash-admitting it remain owner decisions.
- **Temporal, LiteLLM, Semantic Router, DSPy:** deferred by the V1 plan.
- **The audit study's default-off policy variants** (skip vacuous gates, cited-only evidence, block-at-unit unresolved): hypotheses for live testing, not applied.

*CIDM architecture and research direction: Ken Caber (Kenneth Vic A. Caber). External projects and skills retain their respective authorship and licences.*
