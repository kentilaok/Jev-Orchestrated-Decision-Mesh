# CIDM Arsenal Architecture V1 — Frontier-First, Thin-Client

**Status:** future build direction.

**Constraint:** V1 must not require local LLM inference, fine-tuning, GPU-heavy embedding, or sustained local compute. A modest workstation should be able to operate the system as a control node while frontier models and managed retrieval/evaluation services perform expensive work.

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
- small SQLite/JSON metadata stores

Heavy work should be remote:

- frontier inference
- embeddings
- reranking
- vector search at scale
- LLM evaluation
- long-lived observability storage
- optional durable workflow service

Local Qwen/Ajax/Odysseus model inference is deliberately **deferred from V1**. The architecture must leave a model-adapter slot so local workers can be added later without changing CIDM policy.

---

## 2. Target architecture

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

## 3. Core V1 components

### 3.1 Jev / CIDM — global authority

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

### 3.2 Hermes — operational runtime

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

## 4. Frontier model layer

### 4.1 Claude Code adapter — primary V1 worker

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

### 4.2 Codex / ChatGPT adapter — first-class optional worker

Prefer the official ChatGPT-account integration path when practical.

OpenAI's Sign in with ChatGPT flow can:

- authenticate an eligible ChatGPT account
- request plan-usage permission
- list the selected account's current model catalog
- use the selected model slug for inference
- refresh credentials without scraping the ChatGPT desktop app

Codex app-server can also be driven using a ChatGPT-plan OAuth access token.

**V1 direction:** evolve the current Codex CLI wrapper toward a proper account-aware Codex/ChatGPT adapter with an account-specific model picker.

### 4.3 Frontier adapter contract

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

## 5. Context plane

### 5.1 LeanCTX — recommended V1 context gateway

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

### 5.2 Headroom — V1.x controlled A/B, not default

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

### 5.3 LLMLingua — defer

Useful as a research baseline, but not a V1 default because CIDM often carries exact schemas, hashes, source IDs, errors, and permit data.

If tested later, only compress natural-language evidence copies; never mutate authoritative protocol payloads.

---

## 6. MCP as the capability bus

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

## 7. Retrieval and durable knowledge

### 7.1 Qdrant Cloud — recommended V1 vector/search service

**Decision:** BUILD using managed Qdrant rather than local vector infrastructure.

Reasons:

- no local embedding workload required
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

### 7.2 Hosted reranker — recommended

Do not run BGE locally in V1.

Implement a provider-neutral reranker interface.

Preferred hosted candidates:

- **Cohere Rerank v4** — strong multilingual and semi-structured/JSON support
- **Voyage rerank-3 / rerank-3-lite** — strong hosted retrieval/reranking option

The exact provider should be benchmarked on the real transcript/query set rather than selected only from vendor claims.

### 7.3 Chroma — development fallback only

Good for a tiny local POC, but V1 production direction should be managed Qdrant to keep storage/search infrastructure off the workstation.

### 7.4 FAISS — benchmark/library only

Excellent vector-search library, but V1 should not require us to build persistence, metadata filtering, multi-user service, hybrid retrieval, backup, and operational APIs around FAISS ourselves.

---

## 8. Routing

### 8.1 Jev remains the authoritative router

Do not replace CIDM routing with another agent graph.

### 8.2 Semantic Router — optional pre-Jev hint layer

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

V1 can initially use deterministic rules + Jev and add Semantic Router only after enough traffic exists to justify it.

---

## 9. Model gateway

### 9.1 Direct account adapters first

For the first usable V1:

- Claude Code direct adapter
- Codex/ChatGPT direct adapter
- per-provider model discovery
- per-provider account status
- CIDM-owned selection policy

This keeps subscription semantics explicit and easy to debug.

### 9.2 LiteLLM — optional API-era gateway

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

## 10. Engineering methodology skill arsenal

Skills are procedures, not authorities.

They must be installed through a governed skill-admission process and enabled by project/task policy.

### 10.1 Superpowers — selectively adopt

**Recommended initial skills:**

- systematic-debugging
- verification-before-completion
- test-driven-development
- writing-plans
- requesting-code-review
- receiving-code-review
- using-git-worktrees

**Do not** hand global orchestration to its subagent workflow. CIDM remains the project controller.

### 10.2 Karpathy-inspired skills — selectively adopt

Treat these as third-party distillations of publicly described practices, not official Karpathy software.

Recommended concepts:

- task routing
- context engineering
- verification
- recurring-error codification

Do not install an always-on routing file that competes with Jev. Convert useful procedures into CIDM/Hermes-scoped skills.

### 10.3 Ponytail — recommended

Strong fit for the execution plane because it pushes workers toward:

- reuse before invention
- minimal implementation
- avoiding unnecessary abstractions
- reducing generated code

Use the implementation/review/audit variants as bounded Hermes methodology skills.

### 10.4 Taste — project-specific

Useful for web/design/brand work.

Taste's current skills can search/extract design references and grade output against brand evidence through its MCP service.

Use only for relevant visual/design projects. It is not a generic code-quality authority.

### 10.5 Caveman-style compression — optional

May help compact internal summaries or handoffs, but readability and exactness are more important in CIDM protocol data.

Do not apply it to:

- permits
- validator outputs
- hashes
- errors
- source evidence
- user-facing deliverables

---

## 11. Skill admission and registry

**Decision:** BUILD before large-scale skill installation.

Every installed skill should have an Arsenal Manifest entry:

```yaml
id: systematic-debugging
type: methodology-skill

source:
  repository: ...
  revision: ...
  license: ...

scope:
  - debugging

permissions:
  shell: false
  network: false
  write_files: false

trust:
  tier: reviewed
  owner_approved: true

conflicts:
  - none

evaluation:
  suite: debugging-v1
  last_passed: ...
  regressions: ...

hash: ...
enabled: true
```

### Admission workflow

```text
external skill / generated skill
          |
          v
      quarantine
          |
          +-- inspect provenance/license
          +-- static instruction review
          +-- requested permissions
          +-- prompt-injection review
          +-- conflict review
          +-- evaluation tasks
          |
          v
      owner approval
          |
          v
  pinned version + hash
          |
          v
      enabled arsenal
```

### ClawHub

Use ClawHub as a **discovery source**, not as a trust root.

Its versioning/search ecosystem is useful, but community skills should enter through quarantine and explicit CIDM skill admission.

Never auto-install or auto-update a production skill from a public registry.

---

## 12. Observability and evaluation

### 12.1 Phoenix + OpenTelemetry — recommended V1

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

### 12.2 What every run should measure

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

## 13. Experience plane

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

## 14. Durable execution

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

## 15. LangGraph

**Decision:** do not use as CIDM's core orchestrator.

It provides useful persistence and graph execution, but directly overlaps CIDM's state-transition role.

Acceptable future use:

- an external application workflow may call CIDM as one bounded node

Not acceptable:

- reimplementing Jev/CIDM policy as a LangGraph graph
- having LangGraph independently decide commit/escalation rules

---

## 16. DSPy

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

## 17. OpenClaw

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

## 18. V1 build matrix

| Component | V1 status | Compute location | Reason |
|---|---|---|---|
| Jev/CIDM | **Core** | local/lightweight | authority and recovery |
| Hermes | **Core** | local/lightweight | skills and execution |
| Claude Code adapter | **Core** | frontier/cloud | primary worker |
| Codex/ChatGPT adapter | **Core** | frontier/cloud | alternate worker + model switch |
| MCP capability bus | **Core** | local/remote mix | standard tool boundary |
| LeanCTX read-path | **Core experiment** | local/lightweight | context/tool-catalog efficiency |
| Qdrant Cloud | **Core** | managed cloud | hybrid retrieval |
| Hosted reranker | **Core** | cloud API | retrieval precision |
| Phoenix + OpenTelemetry | **Core** | cloud/VPS/managed | tracing/evaluation |
| Skill Admission Registry | **Core** | local Git/state | trust/provenance |
| Experience Distiller | **Core** | local/lightweight | verified learning |
| Superpowers subset | **Approved candidates** | skill only | engineering procedure |
| Karpathy-derived subset | **Approved candidates** | skill only | context/task methodology |
| Ponytail | **Approved candidate** | skill only | reduce overengineering |
| Taste | **Project-specific** | remote MCP | design/brand work |
| Headroom | **A/B later** | local/lightweight | reversible compression |
| Semantic Router | **A/B later** | cloud encoder/local lib | cheap route hints |
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

## 19. Recommended implementation order

### Phase A — make the frontier arsenal safe

1. Finalize `FrontierProvider` adapter contract.
2. Keep Claude Code as default provider.
3. Add official Codex/ChatGPT account integration/model discovery.
4. Add provider health/account/model state to Operator Console.
5. Ensure every frontier execution receives a CIDM capability permit.

### Phase B — reduce context/tool overhead

6. Add MCP capability registry.
7. Integrate LeanCTX in read-path/Shadow Mode.
8. Put downstream MCP servers behind catalog discovery instead of exposing every schema.
9. Record context/tool-catalog savings in CIDM/Phoenix traces.

### Phase C — knowledge retrieval

10. Provision managed Qdrant.
11. Move knowledge collections behind project/access namespaces.
12. Enable dense + sparse hybrid retrieval.
13. Add hosted reranker adapter.
14. Bind retrieved chunks to source IDs/hashes in CIDM.

### Phase D — governed skill arsenal

15. Add Arsenal Manifest schema.
16. Add skill quarantine/admission commands.
17. Import a small reviewed methodology set:
    - systematic debugging
    - verification before completion
    - TDD
    - planning
    - Ponytail minimalism
    - selected context-engineering rules
18. Record exact loaded skill versions in every run.
19. Connect Experience Distiller promotions to the same admission registry.

### Phase E — measurement

20. Instrument CIDM/Hermes/frontier/retrieval with OpenTelemetry.
21. Connect Phoenix.
22. Create frozen evaluation datasets.
23. Measure baseline vs LeanCTX.
24. Measure hybrid retrieval + reranker vs current retrieval.
25. Measure each methodology skill for completion, regression, tokens, and latency.

### Phase F — production resilience

26. Persistent checkpoint reconstruction.
27. Add Temporal only if workflow duration/external waits justify it.
28. Evaluate Headroom separately against LeanCTX.
29. Evaluate Semantic Router only when routing volume justifies an extra layer.
30. Evaluate LiteLLM when multi-user/API-key governance becomes necessary.

---

## 20. V1 non-goals

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

## 21. V1 success criteria

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
12. every optimisation is benchmarked against a frozen baseline before becoming default.

---

## 22. Governing thesis

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
