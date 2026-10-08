# CIDM Arsenal Architecture V1 — Frontier-Efficient, Thin-Client

**Status:** future build direction.

**Constraint:** V1 must not require heavy local generative-model inference, fine-tuning, GPU-heavy workloads, or sustained local compute. A modest workstation should be able to operate the system as a control node while still using lightweight local intelligence—deterministic policy, lexical search, CPU embeddings, small rerankers, caches, code analysis, and compiled skill knowledge—to avoid unnecessary frontier calls.

The design target is:

> **Expand capability horizontally under a fixed CIDM authority boundary. Do not stack autonomous orchestrators vertically.**

Jev remains the global decision authority. Hermes remains the operational skill/runtime layer. Frontier models remain workers. Every added tool is a capability that can be permitted, denied, measured, and audited.

---

## 1. V1 operating assumptions

V1 is designed to run comfortably on a low-resource developer machine such as:

- 16 GB system RAM
- 4 GB VRAM
- ordinary SSD
- no continuously loaded local model
- no local training requirement

The workstation may run lightweight processes:

- CIDM/Jev controller
- Hermes
- MCP servers/gateway
- LeanCTX read-path tooling
- local state/ledgers
- Git/worktrees
- browser/UI
- SQLite FTS5/BM25 indexes
- FastEmbed/ONNX CPU embeddings
- a small CPU reranker for top-k candidates
- deterministic policy/rule evaluation
- skill/experience signature matching
- AST/tree/file analysis and validators
- content-addressed caches

Heavy work should be remote or optional:

- frontier generation/reasoning
- large corpus embedding backfills when local throughput is insufficient
- large rerankers or expensive evaluation models
- vector search at scale
- long-lived observability storage
- optional durable workflow service

Local Qwen/Ajax/Odysseus **generative** inference is deliberately deferred from V1. The architecture must leave a model-adapter slot so local workers can be added later without changing CIDM policy.

---

## 2. Local cognitive substrate — reduce frontier work before it starts

V1 should be **frontier-efficient**, not frontier-dependent.

The workstation should answer cheap questions locally whenever the answer can be derived from deterministic policy, indexed system knowledge, approved skills, or small CPU models.

### 2.1 Decision ladder

Every task should move through the cheapest sufficient tier:

```text
TIER 0  deterministic policy / exact signatures
        |
        | unresolved
        v
TIER 1  lexical retrieval (SQLite FTS5 / BM25)
        |
        | ambiguous
        v
TIER 2  local semantic embedding match (FastEmbed / ONNX CPU)
        |
        | close candidates
        v
TIER 3  small local reranker on top-k only
        |
        | still uncertain / novel / consequential
        v
TIER 4  Jev model decision
        |
        | substantive reasoning required
        v
TIER 5  Claude / Codex frontier worker
```

A frontier call is therefore an **escalation**, not the default mechanism for classification, retrieval, or known-procedure selection.

### 2.2 Tier 0 — deterministic intelligence

The cheapest layer should handle anything that can be proved from structured state.

Use:

- exact task/skill IDs
- file extensions and repository paths
- regex and typed parsers
- JSON Schema
- hash/signature matching
- CIDM policy tables
- known bug keys
- dependency graphs
- AST and syntax-tree inspection
- ripgrep/file indexes
- test exit codes
- static-analysis results
- Git diff/status
- cached successful tool receipts
- project/user capability rules

Examples:

```text
bug_key == "wordpress.memberpress.logged_out_visibility"
    -> candidate skill = memberpress-public-protection

file_changed == "*.py"
    -> required validators += python_compile + unit_tests

task_type == "rewrite_email"
    -> no repository worker required

known source hash + known transform + cached accepted result
    -> reuse cache if policy permits
```

These require no LLM tokens.

### 2.3 Tier 1 — SQLite FTS5/BM25 local lexical memory

Use SQLite FTS5 as a tiny local knowledge index for:

- skill descriptions
- bug signatures
- command/error messages
- filenames/symbols
- experience summaries
- project rules
- known fixes
- tool capabilities

FTS5 provides built-in BM25 ranking and snippets. It is especially useful for exact technical strings where embeddings can be worse:

- error codes
- class names
- plugin names
- commands
- function names
- IDs
- stack traces

This should be the first search over the local experience/skill catalog.

### 2.4 Tier 2 — FastEmbed / ONNX local semantic matching

Use a **small embedding model**, not a generative LLM.

FastEmbed is appropriate for V1 because it is CPU-first, ONNX-based, quantized, and does not require PyTorch.

Use it for:

- task -> skill similarity
- question -> experience similarity
- bug description -> known bug cluster
- query -> local document candidates
- tool intent -> capability candidates
- duplicate/near-duplicate detection

The embedding model should be loaded only when needed or kept as a modest CPU process with a strict memory budget.

No GPU is required.

### 2.5 Tier 3 — small CPU reranker

A small cross-encoder reranker can cheaply refine only the best lexical/embedding candidates.

Example V1 pattern:

```text
1000+ skills / lessons
      |
SQLite BM25 + embedding search
      |
    top 20
      |
MiniLM-class ONNX reranker
      |
     top 3
      |
confidence threshold
```

Qdrant/FastEmbed documentation currently lists an ONNX MiniLM reranker around 80 MB, making this class of model realistic on a 16 GB RAM workstation.

Run reranking only on a small candidate set.

If the local reranker is slow, uncertain, or the task is high-value, fall back to a hosted reranker.

### 2.6 Skill Compiler

Hermes skills should not exist only as prose loaded into a frontier prompt.

On admission, compile every approved skill into a machine-readable local index:

```yaml
skill_id: wordpress-memberpress-public-protection
version: 3
hash: ...

triggers:
  lexical:
    - "logged out can still view product"
    - "memberpress protection not public"
  bug_keys:
    - wordpress.memberpress.logged_out_visibility
  semantic_examples:
    - "protected WooCommerce product visible when signed out"

preconditions:
  project_type: wordpress
  plugins:
    - memberpress

required_capabilities:
  - read_files
  - wordpress_admin

required_validators:
  - anonymous_browser_check

risk: medium
frontier_required: false
```

The compiler should produce:

- FTS5 records
- local embeddings
- trigger examples
- permission requirements
- validator contract
- project scopes
- known failure signatures
- recovery links
- skill version/hash

This turns accumulated Hermes knowledge into **locally searchable executable knowledge**, reducing prompt stuffing and frontier classification.

### 2.7 Experience Cache

The Experience Plane should expose a lightweight local lookup service:

```text
bug_key / symptom / validator failure
        |
        +--> exact signature lookup
        |
        +--> BM25
        |
        +--> embedding similarity
        |
        +--> local reranking
        |
        v
previous verified recovery
```

A retrieved experience does not become authority. It proposes:

- likely skill
- known dead ends
- known successful strategy
- required validator

CIDM still enforces the current policy and evidence.

### 2.8 CIDM Fast Path

CIDM should support a no-frontier route for **pre-authorized, deterministic, reversible operations**.

Requirements:

1. exact stable bug-key match to an approved skill for V1; lexical/semantic similarity may select context but does not authorize Fast Path;
2. skill version/hash is admitted in the Arsenal Registry;
3. project scope matches;
4. required inputs are present;
5. permissions are predeclared;
6. operation is within configured risk tier;
7. deterministic validators exist;
8. no unresolved ambiguity or missing evidence.

Then:

```text
task
  |
local skill/signature match
  |
CIDM compiled policy check
  |
bounded Hermes/tool execution
  |
deterministic validators
  |
  +-- pass -> commit under pre-authorized policy
  |
  +-- fail -> Jev recovery/escalation
```

This is not bypassing CIDM. It is CIDM executing a **compiled policy** instead of paying for a model decision that has already been encoded and validated.

Any novel, ambiguous, destructive, externally consequential, or policy-sensitive task must escalate to Jev.

### 2.9 Local resource budget

V1 should enforce explicit lightweight-compute ceilings:

- no resident generative LLM
- default CPU execution for embeddings/reranking
- one local semantic worker by default
- small quantized/ONNX models preferred
- configurable process RAM cap
- no automatic GPU reservation
- batch/background embedding backfill throttled
- cache embeddings by content hash
- rerank only top-k
- evict/reload models when idle if necessary

The RTX 3050 4 GB remains available for UI/normal workstation use rather than becoming a required AI inference device.

---

## 3. Target architecture

```text
                         USER / PROJECT
                               |
                               v
                    +----------------------+
                    | OPERATOR CONSOLE     |
                    | task / project / UI  |
                    +----------+-----------+
                               |
                               v
                    +----------------------+
                    | JEV / CIDM           |
                    | DECISION PLANE       |
                    |                      |
                    | classify             |
                    | permit               |
                    | budget               |
                    | recover              |
                    | verify               |
                    | accept / stop        |
                    +----------+-----------+
                               |
                   bounded capability permit
                               |
             +-----------------+------------------+
             |                                    |
             v                                    v
   +--------------------+              +----------------------+
   | HERMES             |              | RETRIEVAL PLANE      |
   | EXECUTION PLANE    |              | Qdrant Cloud         |
   | skills / tools     |              | hybrid retrieval     |
   +---------+----------+              | hosted reranker      |
             |                         +----------+-----------+
             |                                    |
             +-----------------+------------------+
                               |
                               v
                    +----------------------+
                    | CONTEXT GATEWAY      |
                    | LeanCTX V1           |
                    | MCP catalog          |
                    | cached reads         |
                    | shell compression    |
                    +----------+-----------+
                               |
                               v
                    +----------------------+
                    | FRONTIER ADAPTERS    |
                    |                      |
                    | Claude Code          |
                    | Codex / ChatGPT      |
                    | future providers     |
                    +----------+-----------+
                               |
                               v
                     candidate / evidence
                               |
                               v
                    +----------------------+
                    | VALIDATORS           |
                    | tests / contracts    |
                    | source checks        |
                    | security checks      |
                    +----------+-----------+
                               |
                               v
                              JEV
                    accept / repair / replan
                               |
             +-----------------+------------------+
             |                                    |
             v                                    v
   +--------------------+              +----------------------+
   | EXPERIENCE PLANE   |              | OBSERVABILITY        |
   | bugs / recoveries  |              | Phoenix + OTel       |
   | verified lessons   |              | traces / evals       |
   | Hermes skills      |              | datasets / replay    |
   +--------------------+              +----------------------+
```

---

## 4. Core V1 components

### 4.1 Jev / CIDM — global authority

**Role:** global control plane.

Jev owns:

- task classification
- capability admission
- model selection
- evidence requirements
- budget ceilings
- recovery policy
- commit authorization
- terminal-stop decisions

No external framework gains global commit authority.

**V1 rule:** a tool can suggest a route, but only Jev can authorize a state transition.

---

### 4.2 Hermes — operational runtime

**Role:** execute bounded CIDM-authorized work.

Hermes owns:

- skill loading
- reusable procedures
- local tool invocation
- project procedures
- memory needed for current execution
- bounded local subagent/tool coordination
- experience-derived skills

Hermes does **not** own global project fan-out, global budget escalation, or final commit authority.

---

## 5. Frontier model layer

### 5.1 Claude Code adapter — primary V1 worker

Use Claude Code as the primary engineering frontier worker while it is the user's main model environment.

Authentication rule:

- use Claude Code's own supported login/session
- never read, export, copy, or proxy private OAuth tokens
- never depend on browser-cookie extraction
- surface whether the session is subscription-authenticated or API-key-authenticated
- use the account's own model selector as authoritative

CIDM invokes Claude through a narrow adapter contract:

```text
run(task, project_dir, model, permissions, timeout)
  -> candidate
  -> tool receipts
  -> exit status
  -> usage/status when available
```

A Claude result is still provisional until CIDM validation and Jev authorization.

### 5.2 Codex / ChatGPT adapter — first-class optional worker

Prefer the official ChatGPT-account integration path when practical.

OpenAI's Sign in with ChatGPT flow can:

- authenticate an eligible ChatGPT account
- request plan-usage permission
- list the selected account's current model catalog
- use the selected model slug for inference
- refresh credentials without scraping the ChatGPT desktop app

Codex app-server can also be driven using a ChatGPT-plan OAuth access token.

**V1 direction:** evolve the current Codex CLI wrapper toward a proper account-aware Codex/ChatGPT adapter with an account-specific model picker.

### 5.3 Frontier adapter contract

All frontier providers should implement the same logical interface:

```text
provider.status()
provider.list_models()
provider.run()
provider.cancel()
provider.usage()
provider.capabilities()
```

The adapter must report unknown usage/cost as unknown, never zero.

---

## 6. Context plane

### 6.1 LeanCTX — recommended V1 context gateway

**Decision:** BUILD / integrate first.

Use LeanCTX primarily for its lightweight read-path and MCP capabilities:

- cached repository reads
- delta/context-aware reads
- command-output compression
- persistent session knowledge
- context budgeting
- measurable token/cost ledger
- multi-repo search
- MCP gateway/tool-catalog reduction
- Shadow Mode for before/after measurement

Particularly valuable for CIDM is the downstream MCP catalog gateway: instead of putting every MCP tool schema into the frontier model's prompt, the model can search a compact tool catalog and call only the selected tool.

#### Claude subscription caveat

Claude Pro/Max OAuth does not support arbitrary custom `ANTHROPIC_BASE_URL` proxying. Therefore:

- use LeanCTX MCP/read-path + shell compression with Claude Code subscription login
- do not require LeanCTX wire-level proxy compression for the Claude subscription path
- wire-level proxy experiments belong to an API-key/provider-gateway configuration

This makes LeanCTX compatible with V1 without interfering with Claude login.

### 6.2 Headroom — V1.x controlled A/B, not default

**Decision:** EXPERIMENT after LeanCTX baseline.

Headroom's strongest property is reversible Compress-Cache-Retrieve (CCR):

- compresses tool/search/code/log content
- retains the original
- lets an agent recover full content when required
- preserves high-entropy values such as identifiers/hashes
- leaves the provider cache hot zone intact

Why not deploy it simultaneously with LeanCTX on day one:

- both change model-visible context
- stacked compression makes regressions hard to attribute
- CIDM needs clean causal measurements

Plan:

1. establish uncompressed baseline
2. run LeanCTX Shadow Mode
3. enable LeanCTX if quality is noninferior
4. A/B Headroom separately
5. choose one primary context transform path per frontier adapter

### 6.3 LLMLingua — defer

Useful as a research baseline, but not a V1 default because CIDM often carries exact schemas, hashes, source IDs, errors, and permit data.

If tested later, only compress natural-language evidence copies; never mutate authoritative protocol payloads.

---

## 7. MCP as the capability bus

**Decision:** BUILD around MCP.

Every external capability should prefer an MCP-compatible boundary when possible.

Examples:

- GitHub
- browser/search
- files
- ticketing
- databases
- design tools
- observability
- retrieval
- project-specific tools

CIDM does not blindly expose the entire catalog to a worker.

Instead:

```text
available MCP servers
        |
        v
capability registry
        |
        v
tool search / ranking
        |
        v
Jev permit
        |
        v
selected tool call
```

LeanCTX's MCP Tool-Catalog Gateway is a strong V1 candidate because it can collapse many downstream MCP schemas into a small discovery/call surface.

---

## 8. Retrieval and durable knowledge

### 8.1 Hybrid local + Qdrant retrieval — recommended V1

**Decision:** BUILD a two-tier retrieval plane: local lexical/semantic prefiltering for cheap decisions, with managed Qdrant for larger durable collections.

Reasons:

- local query embeddings can be generated cheaply with FastEmbed/ONNX
- large backfills can be local-throttled or remote when needed
- dense + sparse named vectors
- lexical + semantic hybrid retrieval
- metadata/payload filtering
- multi-stage queries
- reciprocal-rank fusion
- managed Cloud option
- Cloud Inference can create embeddings remotely

Recommended retrieval path:

```text
user/task query
     |
     +---- lexical / BM25 --------+
     |                            |
     +---- dense semantic --------+
                                  |
                                  v
                              RRF fusion
                                  |
                               top 20-50
                                  |
                                  v
                              reranker API
                                  |
                                top 5-10
                                  |
                                  v
                       frontier worker / Jev
```

For Solutions Empowerment, access/product/source metadata should be payload filters rather than prompt instructions alone.

### 8.2 Local-first reranker with hosted fallback

Do not require a large BGE-class reranker locally in V1. Use a small ONNX cross-encoder locally for routine top-k reranking, and keep a hosted reranker as the stronger fallback.

Implement a provider-neutral reranker interface.

Hosted fallback candidates:

- **Cohere Rerank v4** — strong multilingual and semi-structured/JSON support
- **Voyage rerank-3 / rerank-3-lite** — strong hosted retrieval/reranking option

The exact provider should be benchmarked on the real transcript/query set rather than selected only from vendor claims.

### 8.3 Chroma — development fallback only

Good for a tiny local POC, but V1 production direction should be managed Qdrant to keep storage/search infrastructure off the workstation.

### 8.4 FAISS — benchmark/library only

Excellent vector-search library, but V1 should not require us to build persistence, metadata filtering, multi-user service, hybrid retrieval, backup, and operational APIs around FAISS ourselves.

---

## 9. Routing

### 9.1 Jev remains the authoritative router

Do not replace CIDM routing with another agent graph.

### 9.2 Semantic Router — optional pre-Jev hint layer

**Decision:** EXPERIMENT, not authority.

Potential role:

```text
incoming request
       |
       v
cheap semantic classification
       |
high confidence ---------- uncertain
       |                      |
       v                      v
route hint                  Jev
       \_____________________/
                 |
                 v
                Jev
```

Semantic Router may reduce unnecessary frontier calls for obvious task categories, but:

- it cannot authorize tools
- it cannot commit artifacts
- it cannot skip Jev on consequential tasks
- pin an explicitly tested release line because the project has undergone a breaking rewrite

V1 should first use the local cognitive substrate (compiled rules + FTS5 + FastEmbed + small reranker). Semantic Router becomes an optional implementation/benchmark once that simpler path has enough traffic to evaluate.

---

## 10. Model gateway

### 10.1 Direct account adapters first

For the first usable V1:

- Claude Code direct adapter
- Codex/ChatGPT direct adapter
- per-provider model discovery
- per-provider account status
- CIDM-owned selection policy

This keeps subscription semantics explicit and easy to debug.

### 10.2 LiteLLM — optional API-era gateway

**Decision:** DEFER from the mandatory path; keep an adapter slot.

LiteLLM is useful when we move to centrally managed provider credentials because it supplies:

- one model API
- budgets
- rate limits
- routing/fallbacks
- spend tracking
- traffic mirroring
- guardrails
- model access policies

It can also front Claude Code/Codex clients, but introducing another billing/authentication hop is unnecessary for the initial account-based V1.

Adopt LiteLLM when the requirement becomes:

> one managed enterprise model gateway across many users/providers.

Do not introduce it merely to wrap two already-working authenticated frontier clients.

---

## 11. Engineering methodology skill arsenal

Skills are procedures, not authorities.

They must be installed through a governed skill-admission process and enabled by project/task policy.

### 11.1 Superpowers — selectively adopt

**Recommended initial skills:**

- systematic-debugging
- verification-before-completion
- test-driven-development
- writing-plans
- requesting-code-review
- receiving-code-review
- using-git-worktrees

**Do not** hand global orchestration to its subagent workflow. CIDM remains the project controller.

### 11.2 Karpathy-inspired skills — selectively adopt

Treat these as third-party distillations of publicly described practices, not official Karpathy software.

Recommended concepts:

- task routing
- context engineering
- verification
- recurring-error codification

Do not install an always-on routing file that competes with Jev. Convert useful procedures into CIDM/Hermes-scoped skills.

### 11.3 Ponytail — recommended

Strong fit for the execution plane because it pushes workers toward:

- reuse before invention
- minimal implementation
- avoiding unnecessary abstractions
- reducing generated code

Use the implementation/review/audit variants as bounded Hermes methodology skills.

### 11.4 Taste — project-specific

Useful for web/design/brand work.

Taste's current skills can search/extract design references and grade output against brand evidence through its MCP service.

Use only for relevant visual/design projects. It is not a generic code-quality authority.

### 11.5 Matt Pocock — Skills for Real Engineers (curated)

**Decision:** ADD a pinned external methodology source, not a second orchestrator.

Upstream: [mattpocock/skills](https://github.com/mattpocock/skills) (MIT); reviewed and pinned in `arsenal/sources/matt-pocock.json`.

Core candidates:

- `diagnosing-bugs` — reproducible failure/feedback-loop discipline;
- `tdd` — public-seam red/green/refactor tests;
- `codebase-design` — deep modules and small exposed interfaces;
- `domain-modeling` — shared vocabulary, glossary and ADRs;
- `writing-for-agents` — compact context pointers, more reliable skill instructions.

Review-tier candidates include `code-review`, `retro`, `to-spec`, `to-tickets`, `grill-with-docs` and `handoff`. Model-invoked reference methods can be offered as bounded context; upstream user-invoked workflow commands remain explicitly invoked. Restrict upstream routers, full-workflow implementers and parallel subagent workflows: Jev still owns project planning, tool permission and final commit.

`scripts/arsenal_import_matt_pocock.py` can stage selected skills from an exact pinned and clean upstream checkout. Its default mode is read-only preview. With `--install`, it copies selected skill directories plus **candidate-only** `ARSENAL.json` manifests into `~/.jev/arsenal/quarantine/matt-pocock`, never directly into the active Hermes skill folder. Admission and activation are separate controlled steps.

This intentionally avoids making a GitHub plugin auto-update a trusted procedural dependency. All new versions require re-review and measured evaluation, especially where Matt's workflow overlaps Superpowers or Karpathy-derived methods.

See [Matt Pocock Skills — governed Arsenal source](MATT-POCOCK-ARSENAL.md).

### 11.6 Caveman-style compression — optional

May help compact internal summaries or handoffs, but readability and exactness are more important in CIDM protocol data.

Do not apply it to:

- permits
- validator outputs
- hashes
- errors
- source evidence
- user-facing deliverables

---

## 12. Skill admission and registry

**Decision:** BUILD before large-scale skill installation.

This boundary is now partially implemented in `scripts/arsenal_registry.py`.

Each Arsenal-aware skill may contain:

```text
some-skill/
  SKILL.md
  ARSENAL.json
```

`SKILL.md` remains the procedural document. `ARSENAL.json` supplies machine-readable scope, triggers, requested permissions, risk, validators, and predeclared operations.

The skill package itself is **not the authority for admission**. Owner approval is stored separately in the local Arsenal SQLite database and bound to the exact hashes of both `SKILL.md` and the normalized manifest. A changed skill or manifest therefore loses its effective admission until explicitly reviewed again.

### Admission workflow

```text
external / generated skill
          |
          v
      searchable index
          |
          +-- inspect provenance/license
          +-- static instruction review
          +-- requested permissions
          +-- prompt-injection review
          +-- validator review
          +-- operation/risk review
          +-- evaluation tasks
          |
          v
 explicit local owner admission
          |
          v
 exact skill hash + manifest hash
          |
          v
 eligible for policy evaluation
```

Commands:

```bash
python scripts/arsenal_registry.py scan --skills-dir ~/.hermes/skills
python scripts/arsenal_registry.py admit --skill-id some-reviewed-skill
python scripts/arsenal_registry.py revoke --skill-id some-reviewed-skill
```

A public or model-generated skill can therefore be useful for retrieval before it is trusted for execution.

See [Arsenal Manifest and Skill Admission](ARSENAL-MANIFEST.md).

### ClawHub

Use ClawHub as a **discovery source**, not as a trust root.

Its versioning/search ecosystem is useful, but community skills should enter through quarantine and explicit CIDM skill admission.

Never auto-install or auto-update a production skill from a public registry.

---

## 13. Remote execution and browser arsenal

### 13.1 Cloud sandbox — recommended V1 capability

**Decision:** ADD one remote sandbox provider so frontier workers can compile, install dependencies, run tests, generate artifacts, and execute untrusted code without consuming the local workstation.

Strong candidates:

- **E2B** — isolated microVM per agent/session, pause/resume, filesystem, browser/desktop options, egress controls, metrics, and existing Codex/Claude/OpenAI-agent integrations.
- **Daytona** — isolated cloud sandboxes with dedicated filesystem/network/runtime resources, snapshots/persistence, Linux/Windows/macOS/GPU options, and SDK/API control.

V1 should implement a provider-neutral `SandboxProvider` interface and choose one first rather than integrating both simultaneously.

Suggested permit shape:

```text
sandbox.create(
  image,
  cpu_limit,
  ram_limit,
  network_policy,
  ttl,
  project_snapshot
)
```

CIDM controls:

- whether a sandbox may be created
- repository snapshot/branch
- filesystem scope
- egress allowlist
- TTL
- maximum spend/runtime
- which artifacts may be imported back

The sandbox never receives commit authority.

### 13.2 Secrets — Infisical or sandbox-native secret proxy

**Decision:** ADD before giving frontier agents broad external-service access.

Prefer secret systems where the agent can use a credential without reading its plaintext.

Candidates:

- **Infisical Agent Proxy**
- E2B/Daytona secret injection/proxy capabilities

CIDM permits should reference secret capability IDs, not raw secret values.

### 13.3 Browser automation

**Decision:** ADD in two tiers.

**Deterministic/browser-testing tier: Playwright**

- Playwright CLI/skills for coding-agent workflows
- Playwright MCP when structured MCP browser control is more useful
- accessibility-snapshot interactions avoid requiring a vision model for ordinary DOM workflows

**Cloud-browser tier: Browserbase + Stagehand**

Use when browser sessions should be moved off the workstation or when production browser automation needs hosted session infrastructure. Stagehand adds natural-language `act`/`extract`/`observe` while Browserbase provides the cloud browser.

CIDM should distinguish:

```text
READ_BROWSER
EXTRACT_BROWSER
MUTATE_BROWSER
SUBMIT_TRANSACTION
```

Only the latter two should require stronger permits.

---

## 14. Observability and evaluation

### 14.1 Phoenix + OpenTelemetry — recommended V1

**Decision:** BUILD.

CIDM's append-only journal remains the authoritative forensic record.

Phoenix provides the analytical plane:

- OpenTelemetry traces
- model/tool spans
- retrieval evaluations
- response evaluations
- versioned datasets
- experiments
- prompt/model comparisons
- replay/debugging

Recommended separation:

```text
CIDM journal
    = authority / audit

Phoenix
    = analysis / observability / experiments
```

Trace identifiers should link the two systems.

### 14.2 What every run should measure

- task/project ID
- CIDM protocol version
- selected provider/model
- skills loaded
- tools offered
- tools actually called
- context bytes/tokens before transforms
- context bytes/tokens after transforms
- retrieval candidates and scores
- reranker results
- Jev decisions
- recovery decisions
- validator outcomes
- frontier usage when reported
- cost when known
- latency
- accepted/rejected outcome
- experience lessons emitted
- skill usage and later success/failure

Unknown accounting fields remain `null`/unknown.

---

## 15. Experience plane

The already implemented recovery/distillation layer becomes a first-class V1 service:

```text
run
 |
 v
CIDM journal
 |
 +-- failure
 +-- recovery note
 +-- validator result
 +-- checked commit
 |
 v
Experience Distiller
 |
 +-- raw experience ledger
 +-- provisional lesson
 +-- verified lesson
 |
 repeated verification / owner approval
 |
 v
project-scoped Hermes skill
```

The next V1 work should connect:

- skill usage -> Phoenix trace
- skill ID/version -> CIDM event
- failure after skill use -> negative-transfer event
- successful repair -> recovery note
- promoted skill -> Arsenal Manifest

This lets the arsenal improve while retaining provenance.

---

## 16. Durable execution

### Temporal — V1.x / production hardening

**Decision:** design for it; do not make it a V1 dependency.

Temporal is attractive for one missing property: surviving process/machine failure across long workflows.

Future layout:

```text
Temporal workflow
      |
      v
CIDM transaction/activity
      |
      +-- Jev decision
      +-- Hermes execution
      +-- retrieval
      +-- checker
      +-- external wait
      |
      v
CIDM checkpoint/commit
```

Temporal manages durability and external waits.

CIDM still manages correctness and authorization.

Do not let Temporal workflow code become a second decision brain.

---

## 17. LangGraph

**Decision:** do not use as CIDM's core orchestrator.

It provides useful persistence and graph execution, but directly overlaps CIDM's state-transition role.

Acceptable future use:

- an external application workflow may call CIDM as one bounded node

Not acceptable:

- reimplementing Jev/CIDM policy as a LangGraph graph
- having LangGraph independently decide commit/escalation rules

---

## 18. DSPy

**Decision:** offline optimisation only.

Good future use:

```text
verified CIDM dataset
       |
       v
offline DSPy experiment
       |
       v
candidate prompt/policy
       |
       v
held-out evaluation
       |
       v
human/CIDM review
       |
       v
versioned production prompt
```

DSPy must never rewrite production Jev policy automatically.

---

## 19. OpenClaw

**Decision:** not a core runtime in V1.

OpenClaw overlaps strongly with Hermes.

Useful future roles:

- messaging/channel edge
- source of skill-loading/gating ideas
- optional user interface endpoint
- ClawHub discovery ecosystem

Avoid:

```text
Jev -> Hermes -> OpenClaw -> another autonomous agent
```

Prefer:

```text
channel/OpenClaw
       |
       v
CIDM API
       |
       v
Jev -> Hermes
```

---

## 20. V1 build matrix

| Component | V1 status | Compute location | Reason |
|---|---|---|---|
| Jev/CIDM | **Core** | local/lightweight | authority and recovery |
| Hermes | **Core** | local/lightweight | skills and execution |
| Claude Code adapter | **Core** | frontier/cloud | primary worker |
| Codex/ChatGPT adapter | **Core** | frontier/cloud | alternate worker + model switch |
| MCP capability bus | **Core** | local/remote mix | standard tool boundary |
| LeanCTX read-path | **Core experiment** | local/lightweight | context/tool-catalog efficiency |
| SQLite FTS5 + FastEmbed | **Core** | local/lightweight | lexical + semantic skill/experience retrieval |
| Small ONNX reranker | **Core** | local/lightweight | cheap top-k relevance decisions |
| Qdrant Cloud | **Core** | managed cloud | durable/scaled hybrid retrieval |
| Hosted reranker | **Fallback** | cloud API | stronger reranking when local confidence is insufficient |
| Phoenix + OpenTelemetry | **Core** | cloud/VPS/managed | tracing/evaluation |
| E2B or Daytona | **Core experiment** | managed cloud | isolated code execution off local machine |
| Infisical / sandbox secret proxy | **Core experiment** | managed/self-hosted | keep secrets out of agent context |
| Playwright | **Core tool** | local/light/cloud | deterministic browser automation/testing |
| Browserbase + Stagehand | **Project-specific** | managed cloud | offloaded resilient browser automation |
| Skill Admission Registry | **Core** | local Git/state | trust/provenance |
| Experience Distiller | **Core** | local/lightweight | verified learning |
| Superpowers subset | **Approved candidates** | skill only | engineering procedure |
| Matt Pocock methods | **Pinned candidates** | skill only | debugging, TDD, domain language, architecture, review |
| Karpathy-derived subset | **Approved candidates** | skill only | context/task methodology |
| Ponytail | **Approved candidate** | skill only | reduce overengineering |
| Taste | **Project-specific** | remote MCP | design/brand work |
| Headroom | **A/B later** | local/lightweight | reversible compression |
| Skill Compiler + CIDM Fast Path | **Core** | local/lightweight | execute known validated procedures without frontier calls |
| Semantic Router | **A/B later** | local lib | benchmark against simpler local routing |
| LiteLLM | **Later** | cloud/VPS | multi-provider API gateway |
| Temporal | **Later** | cloud/VPS | crash-safe long workflows |
| DSPy | **Offline later** | cloud/frontier | prompt/program optimisation |
| OpenClaw | **Edge later** | optional | channels/ecosystem |
| ClawHub | **Discovery only** | remote | skill source, never trust root |
| LangGraph | **Not core** | n/a | overlaps CIDM authority |
| LLMLingua | **Research only** | n/a | lossy context risk |
| Chroma | **Dev fallback** | local | simple small POC |
| FAISS | **Benchmark only** | local | library, not operational DB |
| Qwen/Ajax/local LLM | **Deferred** | future GPU/cloud | no V1 local inference |

---

## 21. Recommended implementation order

### Build status (October 2026)

The integrated main line implements the code-only parts of every phase below; [Arsenal V1 — implementation guide](ARSENAL-V1-BUILD.md) documents each component, its commands and its limits. All of it is offline-tested; none of it has a matched live efficiency or quality result.

| Phase | Built | Still open |
|---|---|---|
| A | Registry, compiler, admission, shadow, calibration (A2); Fast Path bound to owner policy, permits and validator receipts (14); negative-transfer metric (16); hash-bound Wilson threshold report (17) | Real reviewed observations to score shadow predictions (15); calibrated thresholds from that data |
| B | `FrontierProvider` contract (14); Claude Code default (15); account-derived Codex catalogue and route-coverage preflight (16); console provider health (17); a `frontier.run` permit on every broker call (18) | Claude model discovery (no non-interactive catalogue); a Sign-in-with-ChatGPT app-server adapter |
| C | MCP capability registry and compact catalogue search with bytes-avoided measurement (19, 21, 22); permit-bound read-only evidence retrieval for recovery runs | LeanCTX integration and token-level context measurement (20) |
| D | Local hybrid index with namespace/access filters, RRF, local-first rerank with hosted fallback, Qdrant REST adapter, chunk IDs and hashes (24–27) | A provisioned Qdrant collection and hosted reranker keys (23) |
| E | Importer and quarantine (unchanged) | Owner-approved import of the reviewed methodology set; per-run skill hash recording (28–30) |
| F | `SandboxProvider` with a Docker provider, secret references, egress `none`, strong artifact import (31, 32); browser permit classes (33) | A managed sandbox (E2B/Daytona); allowlist egress; Browserbase (34) |
| G | Journal-to-OpenTelemetry export for Phoenix (35); run summaries | A running Phoenix and frozen evaluation datasets (36–41) |
| H | Persistent checkpoint reconstruction and operator-attributed resume (42) | Temporal, Headroom, Semantic Router, LiteLLM evaluations (43–46) |

### Phase A — local cognitive substrate

**Implemented in the current experimental branch:**

1. SQLite skill/bug/trigger registry with FTS5 when available.
2. `SKILL.md` compiler with conservative treatment of unmanifested skills.
3. `ARSENAL.json` schema and machine-readable scope/permissions/risk/validators/operations.
4. Exact bug-key and lexical task matching.
5. Separate hash-bound local owner admission and revocation.
6. Fast Path **eligibility evaluation**; execution is not yet automatic.
7. Experience Distiller generation of conservative candidate manifests.
8. Direct indexing of verified distilled lessons into SQLite/FTS5 as context-only experience memory.
9. Native broker shadow observations can distinguish `load_experience_then_jev` from `jev_only`.
8. Optional FastEmbed/ONNX semantic index with skill-hash caching.
9. Optional FastEmbed cross-encoder reranking for top-k candidates.
10. RRF Shadow Mode that fuses lexical + semantic rankings without bypassing Jev.
11. Shadow JSONL records for would-be Fast Path decisions.
12. Native transition-broker Shadow observer with failure isolation and no authority.

**Remaining Phase A items and their status:**

13. Experience-summary indexing beyond promoted skills — verified lessons are indexed directly (`index-lessons`).
14. Bind eligible operations to real CIDM permits and validator receipts — **built** (`scripts/arsenal_fastpath.py`); disabled unless an owner policy pins exact hashes.
15. Score Shadow predictions against eventual Jev/frontier/validator outcomes — tooling built (A2); needs real reviewed runs.
16. Negative-transfer measurement when a local match later fails — **built** (`negative_transfer` in calibration `evaluate`).
17. Establish calibrated promotion thresholds before enabling any non-exact Fast Path class — threshold report **built** (`thresholds`); the thresholds themselves need real data, and V1 Fast Path still requires an exact bug key.

### Phase A2 — calibration and independent outcome review (experimental)

The first shadow-calibration implementation lives in `scripts/arsenal_calibration.py` and `docs/ARSENAL-CALIBRATION.md`.

- Native broker opt-in `--arsenal-calibration-ledger` records an **unchanged-before-execution** shadow prediction and a separate real-run summary.
- Appended predictions, runtime facts and operator-review verdicts bind to the same run ID and input snapshot hash.
- Prompt text is not duplicated in the calibration ledger; source evidence remains in its owning broker/CI journal.
- A reviewed outcome must cite evidence and a reviewer identity. The current tool stores those assertions but does not independently retrieve or cryptographically verify the evidence.
- Simulated, unaudited or unlabelled runs are excluded from quality scores.
- Counterfactual token savings are deliberately unknown; no model calls are actually avoided by shadow instrumentation.
- Skills and experience matches remain context until separately admitted; automatic Fast Path execution remains disabled.
- Next: execute regression suite in CI, collect frozen real-task observations, and calibrate safety thresholds before considering any executable Fast Path.

See [Arsenal Phase A2 Calibration](ARSENAL-CALIBRATION.md).

### Phase B — frontier adapter safety

14. Finalize the `FrontierProvider` adapter contract.
15. Keep Claude Code as the default frontier provider.
16. Add supported Codex/ChatGPT account model discovery.
17. Add provider health/account/model state to Operator Console.
18. Ensure every frontier execution receives a CIDM capability permit.

### Phase C — context and MCP efficiency

19. Add MCP capability registry.
20. Integrate LeanCTX in read-path/Shadow Mode.
21. Put downstream MCP servers behind catalog discovery rather than exposing every schema.
22. Record context/tool-catalog savings in CIDM/Phoenix traces.

### Phase D — knowledge retrieval

23. Provision managed Qdrant for durable/scaled collections.
24. Move knowledge collections behind project/access namespaces.
25. Enable dense + sparse hybrid retrieval.
26. Use local reranking first and hosted reranking as fallback.
27. Bind retrieved chunks to source IDs/hashes in CIDM.

### Phase E — governed methodology arsenal

28. Import a small reviewed methodology set:
    - systematic debugging
    - verification before completion
    - TDD
    - planning
    - Ponytail minimalism
    - Matt Pocock diagnosing-bugs, tdd, codebase-design, domain-modeling, writing-for-agents
    - selected context-engineering rules
29. Record exact loaded skill versions/hashes in every run.
30. Route Experience Distiller promotions through the same registry/admission boundary.

### Phase F — remote execution and browser tools

31. Add one remote sandbox provider behind `SandboxProvider`.
32. Add secret capability references and egress policies.
33. Add Playwright automation with read/mutate permit classes.
34. Add Browserbase/Stagehand only where hosted browser sessions are justified.

### Phase G — measurement

35. Instrument CIDM/Hermes/frontier/retrieval with OpenTelemetry.
36. Connect Phoenix.
37. Create frozen evaluation datasets.
38. Measure frontier-call avoidance from deterministic/skill/local-semantic tiers.
39. Measure baseline vs LeanCTX.
40. Measure hybrid retrieval + local reranker vs hosted alternatives.
41. Measure each methodology skill for completion, regression, tokens, and latency.

### Phase H — production resilience

42. Add persistent checkpoint reconstruction.
43. Add Temporal only if workflow duration/external waits justify it.
44. Evaluate Headroom separately against LeanCTX.
45. Evaluate Semantic Router against the simpler local substrate only when traffic justifies it.
46. Evaluate LiteLLM when multi-user/API-key governance becomes necessary.

---

## 22. V1 non-goals

Do not spend V1 effort on:

- training a local model
- running a large local embedding/reranking stack
- building a custom vector database
- adding multiple autonomous agent frameworks
- auto-installing public skills
- dynamically changing Jev policy from model output
- lossy compression of protocol state
- hidden fallback between models
- unbounded agent/subagent fan-out
- claiming token/cost savings before measurement

---

## 23. V1 success criteria

Arsenal V1 is successful if:

1. one operator can switch Claude/Codex providers without changing CIDM logic;
2. model availability is account-derived rather than hard-coded where supported;
3. every consequential tool/model action is attributable to a CIDM permit;
4. the workstation remains a lightweight control node;
5. RAG does not require local model inference;
6. tool-catalog/context overhead is measurable;
7. every installed skill has source, version/hash, permissions, project scope, and evaluation status;
8. failed gates recover rather than prematurely ending projects when recovery is possible;
9. verified experience can become governed procedural knowledge;
10. Phoenix/CIDM traces can explain why a run succeeded, failed, escalated, or stopped;
11. no new component can independently bypass validators or commit policy;
12. routine known tasks can resolve skill/tool/experience candidates without a frontier call;
13. local semantic helpers stay within explicit CPU/RAM budgets;
14. the system records how many Jev/frontier calls were avoided and why;
15. every optimisation is benchmarked against a frozen baseline before becoming default.

---

## 24. Governing thesis

**CIDM Arsenal Principle**

> A capable autonomous system should grow by adding specialized, replaceable capabilities beneath a stable decision authority—not by stacking additional autonomous decision makers above or beside it.

The architecture should therefore prefer:

```text
one authority + many governed capabilities
```

over:

```text
agent -> agent -> orchestrator -> agent -> framework
```

The result is intended to be easier to audit, cheaper to evolve, and safer to improve through accumulated verified experience.


---

*CIDM architecture and research direction: Ken Caber (Kenneth Vic A. Caber). External projects and skills retain their respective authorship and licences.*
