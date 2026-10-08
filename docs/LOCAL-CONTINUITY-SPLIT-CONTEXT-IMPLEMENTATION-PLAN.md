# CIDM Local Continuity + Split-Context Qwen — Implementation Plan

**Date:** 9 October 2026  
**Status:** **Proposed; implementation not started**  
**Thesis / system author:** Ken Caber (Kenneth Vic A. Caber)  
**Source:** `integration/arsenal-v1`  
**Architecture decisions:** [Split-Context Decisions](LOCAL-CONTINUITY-SPLIT-CONTEXT-DECISIONS.md)  
**Release dependency:** [V1 Production Requirements](PRODUCTION-REQUIREMENTS-HANDOFF-2026-10-08.md) — prior CI, correctness, Hermes, and permit-bound validation gaps still apply.

## 0. Objective and boundaries

Build an optional local Qwen worker that keeps CIDM useful when Claude/Codex usage is exhausted. On ordinary tasks the user chooses **Frontier only**, **Local only**, **Dual teacher-student**, or **Auto fallback**. A local task can fork into **Agent A**, retrieving direct approved SOPs and relevant verified lessons, and **Agent B**, retrieving different yet relevant complementary skills and learning evidence. Each is a separate context lane and request/session; both outputs are independently checked before CIDM releases anything.

The crucial goal is **specialized, independent SOP application**, not putting all methods into one prompt or letting two language models vote away the validator.

**Scope of this plan:** design, local Qwen provider, context-lane retrieval, orchestrated execution, comparison/learning ledger, operator switch, fallback/resumption and release tests. No implementation in this documentation commit.

### Current source capability and gap

| Existing | Reuse | Missing |
|---|---|---|
| `scripts/frontier_providers.py` provider/permit contract | model `run`, status, cancel, usage and receipts | Ollama adapter, resource governance, local-model capability attestation |
| `scripts/arsenal_registry.py` | scope-aware FTS5 skill/experience matching and hash admission | complementary-lane selector, explicit separate context packages |
| `scripts/retrieval.py` | bounded source chunks, source hashes, lexical/optional dense search | avoid linear full-vector scans on large stores; scope-first candidate reranking |
| `scripts/experience_distiller.py` | grouped verified-recovery lesson extraction | student comparison evidence ingestion and anti-pollution gates |
| `scripts/capability_permits.py` | single-use scope/receipt audit | provider-switch and parallel-lane journal binding; one serialized ledger writer |
| `scripts/native_transition_broker.py` | host selector, recovery, checkpoint and Jev decisions | mode and local-host support without fabricating Jev permits |
| `scripts/operator_console.py` and `console/index.html` | local UI, provider status and job management | four-mode switch, local model settings and split-lane run view |
| `scripts/telemetry.py` | run metrics export | end-to-end local/teacher comparative metrics |

**Do not build on the frozen inference-audit study as an active training/usage dataset.** Keep it archival; use new audited real-task observations.

## 1. Architecture: separate retrieval and inference lanes

```text
Request -> policy (mode, Jev availability, risk, workspace, resource cap)
                             |
                    snapshot + hash
                             |
                  Scoped Context Dispatcher
                      /             \
                 LANE A             LANE B
             exact/direct SOP     complementary skill
             + matching lesson    + regression/failure lesson
             + task evidence      + independent acceptance evidence
                 |                     |
             Local Qwen A          Local Qwen B
           isolated request       isolated request
                 |                     |
           candidate A             candidate B
                 \                     /
               Independent validators and disagreement analysis
                              |
                   Jev / limited local policy
                              |
             accept | repair | abstain | defer
                              |
               single-writer observation ledger
                              |
           reviewed experiences -> owner-admitted SOP
```

**Parallel** means lane-specific retrieval/prompt assembly may happen concurrently; inference requests execute concurrently **only** if the resource governor approves it. The user always benefits from independent context selection, even if the 4 GB GPU processes them sequentially.

### 1.1 Shared immutable input

Both lanes receive the same bounded *shared* contract:
`task_id`, `snapshot_hash`, `project_scope`, `goal`, `operation`, `risk`, `allowed_tools`, `success_criteria`, source identities and total budget. These fields cannot be rewritten by model output. The common contract is the **only intentional context overlap**; this does not violate separate learning lanes.

### 1.2 Lane A: direct SOP

Use project-scoped exact bug-key/task intent first, then admission-filtered lexical or semantic candidate selection. Prefer exactly **one** approved SOP and up to **two** verified matching lessons. Fetch canonical source content only **after** obtaining the metadata shortlist; recheck file hash and admission before including a procedure. An unadmitted/malformed skill may be displayed as a quarantined hint only; never as executable instruction.

### 1.3 Lane B: complementary skill and different learning

Issue a separate retrieval query targeting *verification, failure modes, testing and alternative methods*, not a duplicated Lane A prompt. Exclude Lane A's `skill_id`, `skill_hash`, `lesson_id`, provenance and essentially duplicate contents; filter by project scope, permissions, time validity and applicable task class. Prefer a distinct review/regression method over an unrelated, high-scoring skill. Record why Lane B is complementary.

If no relevant distinct content exists: label `no_complementary_sop`, use a verifier-only context if validators exist, or skip Lane B. **No manufactured diversity.**

Lane B's first response must not see candidate A; a subsequent optional critique can be a *new*, separately metered stage.

### 1.4 Fixed retrieval budgets and scale

Proposed pilot settings (not measured performance guarantees):
- Max one direct SOP + two lessons in A; one complementary SOP + two lessons in B; independent source evidence fragments.
- Per-lane context approximately **4,096 tokens** initially, bounded generation output, one 4B Q4 model loaded. Target fewer than 8 relevant source chunks, never thousands.
- Hard candidate shortlist via FTS5 + metadata/access predicates; no unbounded `SELECT *`/full collection scans in interactive paths.
- Pre-compute embeddings at ingest, cache by content/model hash and invalidate by hash change. Rerank only a capped lexical shortlist initially; use Qdrant/ANN if later benchmarks prove necessary.
- Record p50/p95 retrieval latency, candidate-count limits, cache hit rate, number of missed known-answer cases and growth with 1K/10K/100K fixture records.
- Run expensive library ingestion/embeddings outside the user-response hot path.

## 2. Provider mode and authority policy

| `execution_mode` | Provider behaviour | Qwen lanes |
|---|---|---|
| `frontier_only` | Existing Claude/Codex; **no Qwen** | none |
| `local_only` | Ollama only; no Claude/Codex calls | A; B if helpful and resources allow |
| `dual_shadow` | Teacher and Qwen see frozen shared task independently; compare and record | A + optional B; teacher also independent |
| `auto_fallback` | Frontier first, local only on **confirmed configured quota/availability condition** | A + optional B after classified fallback |

Policy `authority_mode`:
- `jev_managed`: Jev retains global decisions, including local worker routes.
- `limited_local_continuity`: only an explicit, **separately owner-approved, versioned deterministic policy** for low-risk, reversible actions when Jev/network unavailable. Missing authority yields `deferred_requires_jev` or `needs_operator`; **never** mint a fake Jev-decision basis.

Distinguish model provider entitlement errors, rate limits, model unavailable, temporary network errors, context-limit errors and safety denials. Only explicitly configured classes trigger fallback. Save provider error class, rate limit, mode and model identity in the run journal. Never silently spend paid frontier tokens after entering `local_only`.

A frontier quota error can occur after earlier successful units; resume from a **verified checkpoint** and exact committed prefix. Do not replay irreversible external actions or duplicate side effects. Any provider switch affecting a permit must generate a **new properly authorised scoped permit** with a fresh model identity; spent permits remain spent.

## 3. Proposed modules and interfaces

**Suggested changes (future work):**

- New `scripts/ollama_provider.py`: `OllamaLocalProvider` implementing existing `FrontierProvider` shape (or a carefully named neutral `WorkerProvider` alias without breaking compatibility). Loopback-only client, `/api/tags` status/models, bounded `/api/chat` or `/api/generate` JSON schema outputs, timeout/cancel, model-id-and-digest attestation, usage tokens when the runtime reports them, no remote URL by default.
- New `scripts/local_continuity_policy.py`: mode, permissions, signed/frozen policy identity, quota classifier, breaker/explicit fallback and risk/authority decisions. Separate "no frontier worker" from "offline / no Jev".
- New `scripts/split_context_dispatch.py`: `ContextPackage`, A direct-SOP selector, B complementary-skill selector, hash/citation/source access checks, duplicate prevention and independent request construction.
- New `scripts/local_lane_scheduler.py`: bounded queue/concurrency semaphore, warm-model lifecycle, timeout/cancel, serial default with optional `max_parallel_local=2` under memory check. No parallel writer of one ledger.
- New `scripts/answer_comparator.py`: structured claim/evidence/SOP-step alignment, test/validator receipts, disagreement labels `agree_verified`, `agree_unverified`, `disagree`, `incomplete`, `timeout`. Model agreement is not an independent acceptance criterion.
- New `scripts/student_learning_ledger.py`: queued single-writer hash-linked observations to a dedicated student ledger/SQLite store. Persist candidate outputs as observations; require external validation and reviewer evidence for promotable training lessons.
- Update `scripts/frontier_providers.py` and `scripts/native_transition_broker.py`: local provider and mode selection, same scope/usage/audit contract; wire context dispatcher and independent validators. Keep legacy `--host claude|codex` paths unchanged.
- Update `scripts/operator_console.py`, `console/index.html`: four modes, explicit fallback opt-in, local model status, two-lane context provenance, memory mode, comparison results, spend/permit indication and `frontier unavailable` notice.
- Update `scripts/telemetry.py` plus existing distiller/admission integration: mark per-lane model calls and compare/adjudicate observations without granting authority to retrieval data.

Minimal interface sketch (**design only**, not an existing API):

```json
{
  "task_id": "task-001",
  "snapshot_hash": "sha256:...",
  "execution_mode": "local_only",
  "authority_mode": "jev_managed",
  "project_scope": "demo",
  "lane_policy": {
    "a": "direct_sop",
    "b": "complementary_review",
    "require_distinct_sources": true,
    "max_parallel_local": 1,
    "context_limit_tokens_per_lane": 4096
  },
  "max_local_calls": 2,
  "max_frontier_calls": 0,
  "allowed_operations": ["read", "propose"],
  "expected_validators": ["artifact_schema", "source_hash", "task_postconditions"]
}
```

The dispatched `ContextPackage` must carry `lane_id`, `package_hash`, model ID/digest, each `sop_id`/`skill_id`/`lesson_id` plus versions/hashes, source refs, prompt token estimate and access/expiry attributes. Validator receipts refer back to exact task+lane package hashes.

## 4. Implementation sequence with acceptance gates

### Phase 0 — Foundation and clean-baseline checks

- Address **existing** preproduction blockers, especially GitHub Actions job failures before recorded steps and missing live acceptance; do not conceal regressions underneath the new feature.
- Freeze a representative, permission-safe, fictional set of tasks and expected postconditions (20 short deterministic, 20 SOP-directed coding/debugging, 20 ambiguous/out-of-domain to start; scale after useful results).
- Capture existing provider performance, usage availability, memory and test outcomes; document missing baseline metrics.

**Exit:** documented baseline fixture, tests runnable on Windows and CI, mode/permission design reviewed.

### Phase 1 — Ollama provider + manual local-only path (smallest useful pilot)

- Install/pin Ollama on Windows, quantized Qwen **4B** model from an explicitly verified registry tag; record real content/model digest instead of assuming tag immutability.
- Implement local provider (status/models, structured output, timeouts/cancel, usage, permit receipts) using bound `127.0.0.1` endpoint by default. Avoid sending secrets to model prompts.
- Implement `local_only` worker path and independent *deterministic* validators; no dual agents or automatic fallback needed to deliver initial continuity.
- Include `unknown`/`needs_evidence`/`needs_operator` statuses. Explicitly refuse high-risk operations without verified governing authority.
- Unit tests use a fake Ollama HTTP endpoint; optional live local smoke test records actual Ollama and GPU usage.

**Exit:** a bounded SOP task completes via Qwen with **zero Claude/Codex worker calls**, valid permit/accounting receipts and verified postconditions. The app reports whether Jev still required cloud access.

### Phase 2 — Split-context lanes and scheduler

- Implement immutable shared task contract plus two separate retrieval branches. Select A direct SOP + lessons; B complementary distinct skill + different lessons.
- Enforce project access, admission status, source hashes, no leakage of A proposal into B's initial prompt, and relevance checks. Gracefully skip B when no credible complement exists.
- Run two isolated Qwen sessions; maintain a **single loaded model** and serial generation default. Independent prompt assemblies may execute concurrently.
- Add bounded queue, per-lane timeouts/cancellation, safe partial results and single-writer journaling. Test abort/retry without duplicated external effects.
- Add optional physical parallel toggle only after VRAM/RAM stress tests on the actual 4 GB GPU; default remains 1.
- Detect self-similar SOP material to prevent duplicate advice masquerading as independent reasoning.

**Exit:** proof from captured **two different context hashes + two different skill/lesson sets**, independent answers, the same immutable task contract, deterministic validation, and no cross-lane prompt contamination.

### Phase 3 — Model comparisons and reviewed learning

- Add `dual_shadow` teacher path with identical task snapshot and project rules. Teacher and Qwen do not see each other's initial drafts.
- Capture all outputs, latency, token usage, role, provider, real model identity, validation receipts, differences, abstentions and failures.
- Append via a single recorder. Distil *only* externally verified lessons, including failure diagnoses and success paths, into provisional experience. Require owner admission and tests for executable SOP changes.
- Add clear separation between raw observations, independently verified lessons and trusted admitted SOP. Learning ledger does **not** update model weights.

**Exit:** reproducible comparison record with a known-wrong answer rejected despite valid schema or cross-model agreement; no automatic promotion from unverified agreement.

### Phase 4 — Frontier quota fallback and checkpoint continuity

- Detect named rate-limit/quota conditions from actual provider responses, not arbitrary error strings alone.
- Provide mode switch in Operator Console. Test `frontier_only`, `local_only`, `dual_shadow`, `auto_fallback`; defaults remain explicit and backwards compatible.
- On confirmed quota fault in `auto_fallback`, use the checkpointed committed prefix, immutable source bindings and a **new** permit for Qwen under the applicable authority. Record fallback reason and show local capability boundary.
- Distinguish offline limited-continuity mode from Qwen-only remote-Jev operation; impose deterministic policy on the former. Failed/missing approvals stop/defer, not silently permit.
- Preserve all existing paused/resume semantics and audit logs.

**Exit:** tests prove quota-triggered switch works without losing accepted work, while invalid-credential, policy refusal, bad evidence and unknown-error cases do **not** trigger unauthorised switching. Local-only never calls remote worker.

### Phase 5 — Scale and resource optimisation

- Remove all-vector Python dense scans from the hot query path. Use shortlist-then-rerank by default; ANN/Qdrant optional based on measurements.
- Benchmark increasing library sizes, verified-SOP precision/recall, stale skill behavior, duplicate contexts and prompt token budgets.
- Test single vs dual local generations on the real PC for throughput, GPU/CPU offload, peak RAM/VRAM, p95 latency, and answer quality.
- Only enable `max_parallel_local=2` if measured gains and memory/safety criteria pass. Otherwise maintain two **logical** specialists executed sequentially.

**Exit:** bounded prompt size and acceptable p95 retrieval latency at representative corpus sizes; model mode respects memory governor without hangs or OOM.

### Phase 6 — Operator release, documentation, evaluation and migration

- End-to-end smoke tests through console/Hermes once permit-bound Hermes dispatch exists; screenshots and logs for all modes.
- Freeze provider/mode matrix and publish CLI/local Windows setup, downgrade instructions, data backup/restore, model cache behavior, secret/retention policy, learning admissions and rollback.
- Compare local-only, dual, auto-fallback and frontier-only quality on frozen tasks, including costs and verified completion. Report unknown usage separately and **do not** claim savings if unmeasured.
- Run adversarial prompts, fake SOP injection, private-scope leakage attempts, two-agent agreement on wrong facts, invalid quotas, permit replay, overlapping checkpoint resumes and ledger concurrency failures.

**Exit:** release gate/owner approval, audit clean, CI green, independent acceptance report. Only then consider integrating into mainline V1.

## 5. Test matrix (required negative cases)

| Class | Required assertion |
|---|---|
| Distinct retrieval | A and B have different retrieved SOPs/lessons, distinct package hashes and applicable scope. |
| No valid B candidate | Lane B is skipped/verifier-only, **not** filled with irrelevant skill. |
| Context isolation | Private A lesson/answer isn't included in B's pre-answer prompt; no cross-project source enters either. |
| Retrieval scaling | Top-k fixed and bounded; no unbounded dense/full-table scan at scale; trace retrieval latency. |
| Read-only local-only | No frontier worker calls; rejects mutation without separate authorised permit. |
| False agreement | Two Qwen copies give same wrong answer; task postcondition rejects release. |
| False teacher | Claude/Codex differs but is wrong; validator and adjudication do not automatically choose teacher. |
| Quota fault | Identified quota error may fall back only if configured, with new permit and clear log. |
| Safety denial | Denial never falls back to bypass rules. |
| Jev unavailable | No fake Jev decision; only preapproved limited local operations allowed, otherwise defer. |
| Cancel/resume | Worker timeout/cancellation does not reuse a permit, double-commit or replay external action. |
| Concurrent logs | A/B events serialized; chain reads and audit validate after stress. |
| Provenance | Tampered skill hash/version and revoked skill excluded from trusted contexts. |
| Resource exhaustion | GPU/RAM or timeout pressure reduces concurrency/abstains without losing state. |
| Learning pollution | Repeated agreement and fake reviewer verdict cannot auto-admit SOPs. |
| Secret/privacy | No credentials in model prompt, untrusted SOP log, GitHub docs or cloud telemetry. |
| Backward compatibility | Existing Claude/Codex single-worker broker paths still work unchanged. |

Use pure unit fixtures first, then opt-in locally generated Ollama responses, then a small real but non-sensitive project pilot. CI should never depend on local GPU or live paid credentials.

## 6. Workstation settings and deployment

Target checkout (after a reviewed feature merge or using the feature branch):
`D:\Hermes Jev CIDM`

Suggested **initial defaults**, to validate on the real system:
- model: one quantized Qwen 4B Instruct, four-bit; **pin actual digest** after validating model variant/tool support;
- local endpoint: `http://127.0.0.1:11434` only;
- local generation concurrency: **1**, with independent A/B lane contexts;
- context: approximately `4096` tokens **per lane**, not shared; adjust based on measured KV-cache usage and model's real served context;
- output cap, request timeout, overall run timeout and maximum repair rounds enforced centrally;
- modes: `frontier_only`, `local_only`, `dual_shadow`, `auto_fallback`;
- fallback: **OFF by default** until the user explicitly enables it;
- Fast Path: remain disabled until governed calibration;
- no remote browser/MCP write when fully offline unless preauthorised by a narrowly scoped deterministic policy.

Example *future* PowerShell smoke commands (not available today):

```powershell
# Install and inspect a verified Ollama model first:
ollama --version
ollama list
ollama ps
# After implementation, a local-only validate/smoke entry point should exist.
# Its exact CLI command MUST be documented from the implemented parser and tests.
```

Do not invent a `--host qwen` command for the current broker: its implemented choices are presently `claude` and `codex`.

## 7. Acceptance metrics and decision

Metrics for each task/lane: selection accuracy, SOP/version/hash consistency, input and output tokens **as actually reported**, unknown-usage count, latency, peak VRAM/RAM, queue wait, retrieval p50/p95, failed validations, correct abstentions, detected bad agreements, model identity, reviewer acceptance, stale skill rejections, permit violations, recovery outcome and completed-task quality.

**Proposed pilot policy** (targets to finalise before benchmarking):
- **0** unauthorised external mutations or permit replays;
- **0** cross-project context leaks;
- **100%** of accepted outputs satisfy the declared deterministic release tests;
- all unverified/novel/high-consequence outcomes withheld or explicitly escalated;
- measurable latency/memory and quality; no speculative claim of superiority from 4B quantization;
- for hardware, accept physical two-request parallelism **only** if quality is preserved and throughput improves without resource exhaustion.

Compare against the competent direct Claude/Codex baseline on matched tasks with cost, quality, latency and total calls. Do not treat a frontier answer, Jev judgment alone, or two agreeing Qwen copies as a substitute for independently verifiable task success.

## 8. Dependencies and delivery slices

Recommended PR slices:
1. **Local provider + local-only smoke** — provider contract, no auto route or student learning.
2. **Split-context retrieval + two-lane scheduler** — measurable context separation.
3. **Independent comparison + review ledger** — observational, not self-training.
4. **UI mode switch + quota fallback** — authenticated error classification and no unsafe bypass.
5. **Retrieval/memory optimisation and pilot release evidence** — benchmarked and signed off.

All slices target the integration development branch through review. Keep changes behind disabled feature flags until tests are green. The existing **[PR #3](https://github.com/kentilaok/Jev-Orchestrated-Decision-Mesh/pull/3)** release blocker remains; this extension should **not** be claimed as shipped or merged into `main` by the existence of these documents.

## 9. Developer handoff checklist

- [ ] Establish reliable green CI baseline and record test logs before feature work.
- [ ] Decide model exact tag + verified digest + licence and local RAM/VRAM benchmark.
- [ ] Define narrow local continuity decision rules separately from Jev receipts.
- [ ] Implement provider and fake HTTP tests, then local-only preview.
- [ ] Build scope-filtered A/B retrieval with genuinely distinct SOP/skill/lesson evidence.
- [ ] Keep independent pre-comparison contexts and one permit per run/lane.
- [ ] Implement memory-adaptive scheduler and serial ledger writer.
- [ ] Add comparator with deterministic tests and honest uncertainty statuses.
- [ ] Add observation ledger and reviewed experience promotion, never untrusted auto-learning.
- [ ] Add four-mode operator switch, explicit fallback semantics and safe resumption.
- [ ] Optimize growing dense retrieval and verify 1K/10K/100K index behaviour.
- [ ] Complete release safety/quality/performance evaluations and operator approval.
- [ ] Update original production handoff with measured release evidence when available.

**Release state now: design documented; implementation intentionally not performed.**
