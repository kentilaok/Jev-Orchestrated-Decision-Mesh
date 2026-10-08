# ADR: Local Continuity and Split-Context Student Agents

**Date:** 9 October 2026  
**Status:** Proposed architecture / documentation only — **not implemented**  
**Project:** Caber Interstitial Decision Mesh (CIDM), Ken Caber (Kenneth Vic A. Caber)  
**Parent:** `integration/arsenal-v1` (preproduction; PR #3 remains unmerged)

## Decision summary

CIDM should offer a **reliable local continuation path** when Claude Code or Codex reaches an account usage limit. A quantized **Qwen student worker** must be able to operate using verified, project-scoped SOPs and deterministic validation, without pretending to have frontier-level competence.

Support **two specialised local student lanes** in the same task, without placing all skills and lessons into one shared prompt:

- **Lane A — Direct SOP executor:** retrieve the most directly applicable, approved domain-specific procedure and matching verified lessons. It proposes a structured answer or bounded action plan.
- **Lane B — Complementary specialist:** independently retrieve *different*, relevant engineering skills, testing procedures, risk patterns, or verified lessons. It challenges assumptions or proposes an alternative; it does **not** ingest Lane A's private working context or draft before its first answer.
- Both receive a **small common task contract** (goal, immutable snapshot, access scope, success criteria, budgets). Their additional retrieved context is distinct and hash-recorded.
- A deterministic **comparison + validator** checks SOP compliance, evidence, objective tests, and disagreements. Jev remains the governing authority whenever available. Agreement between two instances of the same Qwen model is **not independent verification**.
- Store both candidate outputs as *untrusted observations*. Promote only independently verified lessons under owner review/admission; logging comparisons does not fine-tune Qwen weights.

**Do not force irrelevant diversity.** If there is no valid complementary skill/lesson with the same access and project scope, omit Lane B, or give it an independent verification-only context with no claimed skill match. Never reuse the same procedure under a different label just to satisfy two-agent operation.

## Motivating discussion / goals

1. **Usage-limit resilience:** user must manually switch to Qwen at any time and optionally opt into automatic fallback on authenticated quota/rate-limit conditions.
2. **Dual-learning experiments:** Qwen and an available frontier model may answer the same frozen task independently, compare results, and record reviewed learning evidence.
3. **Split-context local parallelism:** Lane A uses directly relevant SOP knowledge; Lane B uses different, complementary skill/learning. Two bounded context paths operate in parallel logically rather than one combined context tunnel.
4. **Scale:** larger SOP/experience archives must not produce linearly growing prompt size or retrieval time. Retrieve top-k only within scoped, approved indexes, and record retrieval latency.
5. **Resource envelope:** initial workstation approximately **16 GB RAM, RTX 3050 4 GB VRAM**. Use **one** Qwen 4B-class quantized model instance, small per-lane context, **one generation at a time by default**. Independently prepared lanes may queue; true simultaneous generations are an opt-in benchmark once memory headroom is measured.
6. **Hallucination control:** bound actions and claims to cited evidence, schema, SOP, validators, and clear `unknown`/`needs_evidence`/`needs_review` outcomes. Never promise zero hallucinations.
7. **Architectural integrity:** local workers never become a new independent Jev. No model/skill may self-authorise external writes or change policy.

## Four operator-selectable modes

| Mode | Intended behaviour | Approval and network semantics |
|---|---|---|
| **Frontier only** | Existing Claude/Codex path; no local model calls. | Existing Jev/permits; normal frontier account requirements. |
| **Local only** | Local Qwen, one or two SOP-specialised lanes. **No frontier worker calls.** | Jev remains remote *unless* local decision policy is selected. Never silently invoke a cloud worker. |
| **Dual / teacher-student** | Available Claude/Codex and local Qwen independently process the same immutable input; optional two local sublanes. | Teacher is not ground truth; accepted outcome still requires validators and Jev where available. |
| **Automatic fallback** | Frontier first. Only after a **classified** quota exhaustion or configured sustained availability condition may the worker route to local. | Explicit opt-in; record switch reason, preserved task/context hashes, local scope and permitted risk. Do not silently retry non-idempotent operations. |

Mode selection and **which provider is allowed** are separate from **decision-authority availability**:

- `jev_managed`: existing remote Jev decisions. Local inference is not fully offline.
- `local_continuity`: for Jev/network outage, a **separate, limited deterministic policy** may permit only owner-approved, reversible, verifiable SOP actions. Otherwise return `deferred_requires_jev` or `needs_operator`. No invented Jev decision or fake permit basis.
- A subscription UI limit must be distinguishable from an API key's billing/entitlement failure; detection relies on explicit provider responses. Unknown cause is not assumed to be quota exhaustion.
- Never fall back from a safety denial, permission refusal, invalid evidence, or missing validators. Budget caps, operator choices, privacy restrictions and input provenance survive provider changes.

## Split-context contract: fork early, join after proposals

```text
                     Frozen task contract + acceptance criteria
                                        |
                         CIDM authorised context dispatcher
                              /                   \
          Lane A: direct SOP retrieval      Lane B: complementary retrieval
          approved SOP + matching lesson    independent skill/failure learning
                    |                                  |
               Qwen session A                     Qwen session B
                    |                                  |
              Candidate A                         Candidate B
                     \                                /
                     Independent evidence/tests/comparison
                                     |
                           Jev or limited local policy
                                     |
                             Accepted / repair / defer
                                     |
                      Observations -> reviewed learning ledger
```

Separate retrieval means two independent **context packages**, **run IDs**, **prompt/evidence hashes**, and **permission filters**, not two copies of model weights. All execution effects remain non-mutating until accepted and separately authorised.

Lane selection example:

- User: diagnose a Python failing test.
- Lane A: `python-test-failure-diagnosis` SOP, traceback source, previously verified bug-key lesson.
- Lane B: different `verification-before-completion` or `regression-test-design` skill, acceptance tests and known negative cases.
- Shared: task ID, project scope, redacted task statement, allowed operations, expected checks.
- Lane B must not be handed Lane A's solution before initial independent execution; second-pass critique of A can be scheduled **after** the independent comparisons, under a separate receipt.

## Knowledge-scale observations found in the existing code

- `scripts/arsenal_registry.py` already performs indexed FTS5/BM25 candidate selection, project-scoped `match` and verified experience matching; skill admission remains a separate hash-bound boundary.
- `scripts/retrieval.py` already caps result counts/chunk sizes and stores source/hash metadata.
- **Performance concern:** `LocalHybridIndex.dense` reads **all vectors in a namespace** and computes similarities in Python; this is effectively linear in indexed vectors per query. Do **not** place a growing large library through this hot path. First shortlist lexical candidates and rerank, then evaluate indexed ANN/Qdrant only if justified by benchmarks.
- When FTS5 is unavailable, some registry matching paths scan and sort the full table. Production local-continuity mode should verify FTS5 availability and use an explicit bounded fallback / error instead of accepting unlimited slow scans.
- The `ExperienceDistiller` groups verified recovery episodes, but a reported `verified_recovery` still needs trustworthy external validators and human/CI-adjudicated provenance. Observation counts alone do not authorise a skill.
- `HashChainLedger` is documented **single-writer**; parallel lanes must NOT write independently to the same hash-chained ledger. Use a one-writer event aggregator/queue.
- Existing `--host` and Operator Console provider enum supports **Claude / Codex only**, so Qwen local, mode switches and the split-context orchestrator **are not yet coded**.

## Concurrency decision

**Logical parallelism first; physical parallel inference only when measured safe.**

- Default: concurrently retrieve/build Lane A and B; serialize requests to one warmed Qwen instance, with per-lane context isolated. This avoids CPU/GPU thrash and duplicate resident weights.
- Experimental: `num_parallel=2` only if a local benchmark on actual PC confirms acceptable VRAM headroom, task-quality preservation and end-to-end speed. If the model spills to CPU, automatic capacity governance reduces to 1.
- Use a bounded queue, one shared model loader, explicit cancellation and timeouts, run-specific workspace/snapshot IDs; keep provider use observable.
- This is **not** two different Qwen models or two autonomous agents with tool-approval authority.

## Data governance and learning

Record compact append-only **candidate** facts: task ID/snapshot, mode, lane, model ID + quant hash, context package hash, SOP/skill/lesson IDs + hashes, scores, timestamps, usage (or `unknown`), test outcomes, differences and release arbitration. Raw confidential prompts stay in access-controlled project storage with a retention policy.

Three storage levels:
1. **Raw observation:** model outputs and disagreements, not trusted instruction.
2. **Verified experience:** postcondition tests and independently cited reviewer/CI evidence, with explicit uncertainty and failure labels.
3. **Owner-admitted SOP:** separately reviewed, versioned, hash-bound and scoped procedure. Revocation removes it from future trusted retrieval.

Reject reward hacking: no automatic promotion from agreement, frontier-model prestige, self-report or passing schema alone. Conflicting teacher/student output is a *diagnostic signal*, not permission for an extra model to decide arbitrarily.

## Explicitly not decided / deferred

- No automatic model-weight training or LoRA/QLoRA in first release.
- No guaranteed latency speedup or accuracy improvement from parallel Qwen sessions.
- No requirement to run Qdrant or managed services on day one.
- No bypass of unresolved V1 production gates (CI, live tests, Hermes dispatch, correctness).
- No claim that local-only means fully offline while Jev still uses a cloud endpoint.
- No replacement of the CIDM thesis's single governing authority with model voting.

## Next document

See [Local Continuity — Implementation Plan](LOCAL-CONTINUITY-SPLIT-CONTEXT-IMPLEMENTATION-PLAN.md) for component interfaces, phases, acceptance tests, resource budgets, Windows deployment and release criteria.
