# CIDM — Complete Thesis and Future Build Direction

This document is the canonical entry point for the Caber Interstitial Decision Mesh (CIDM) research thesis and its version-one Arsenal design. The thesis is deliberately published as **repository documentation**, not as the GitHub repository description.

**Document status:** architecture and research direction. Some supporting implementations are experimental and remain on [PR #2](https://github.com/kentilaok/Jev-Orchestrated-Decision-Mesh/pull/2), not the default branch. A documented capability does not imply it is deployed, benchmarked, enabled, owner-admitted or available in the current release.

## The complete thesis

The thesis comprises the following documents. Each covers a distinct part of the system:

| Document | Purpose | Status |
|---|---|---|
| [Research thesis](THESIS.md) | Original CIDM thesis, control protocol, evidence, limits, tests and extensions | Published thesis |
| [Architecture](ARCHITECTURE.md) | Five-unit decision mesh and reference architecture | Reference design |
| [Execution routes](EXECUTION-ROUTES.md) | Classification, short path and project-scale reasoning | Reference design |
| [Orchestration budgets](ORCHESTRATION-BUDGETS.md) | Resource accounting, model escalation and bounded decisions | Research and control design |
| [Gate fusion](GATE-FUSION.md) | Separate/fused decision boundaries and state-bound permits | Experimental protocol |
| [Recovery and experience distillation](RECOVERY-AND-DISTILLATION.md) | Bounded recovery, project continuity, verified lessons and Hermes skills | Experimental extension; implementation in PR #2 |
| [Arsenal V1](ARSENAL-V1.md) | Frontier-efficient system, local cognitive substrate, agents/tools, memory and build phases | Future-build architecture; partial implementation in PR #2 |
| [Arsenal manifest and admission](ARSENAL-MANIFEST.md) | Searchability vs trust, skill manifests, hashes, permissions, explicit admission | Planned governance; partial implementation in PR #2 |
| [Matt Pocock skills](MATT-POCOCK-ARSENAL.md) | Pinned curated external methodology source, boundaries and quarantine | Candidate source; importer and tests in PR #2 |
| [Roadmap](ROADMAP.md) | Historical research and rollout roadmap | Supporting context |
| [Benchmarks](BENCHMARKS.md) | Reported benchmark setup and measurement context | Historical evidence; do not infer deployment-wide performance |
| [Routing economics](ROUTING-ECONOMICS.md) | Relative model/orchestration costs and hypothesis tests | Research context |
| [Validation](VALIDATION.md) | Test/evidence criteria and qualifying outcomes | Supporting methodology |
| [Connectors](CONNECTORS.md) | External tool integration boundaries | Supporting design |
| [MCP evidence](MCP-EVIDENCE.md) | Evidence and MCP boundary considerations | Supporting design |
| [Research context](RESEARCH-CONTEXT.md) | Related work and foundations | Supporting research |

## One governing proposition

> Grow CIDM by adding specialised, replaceable, measurable capabilities beneath a stable decision authority. Do not grow it by layering independent orchestration authorities on top of one another.

The system separates authority from ability:

```text
User / project / Operator Console
               |
               v
        LOCAL COGNITIVE SUBSTRATE
        exact policy and signatures
        SQLite FTS5 / BM25
        small CPU embeddings and reranking
        versioned skills + verified experiences
               |
         route evidence only
               |
               v
              JEV
      CIDM global decision plane
      scope / permits / limits / recover
               |
      bounded authorised operations
               |
               v
             HERMES
         execution / skills / tools
               |
       MCP / sandbox / browser / RAG
               |
       frontier workers as needed
          Claude Code / Codex
               |
        artifact / evidence / receipts
               |
               v
       DETERMINISTIC VALIDATORS
               |
          Jev accept / repair
               |
               v
      IMMUTABLE EVENT / EXPERIENCE LEDGER
               |
        verified lessons / skill proposals
               |
       versioned review and admission
```

A known low-risk operation may *eventually* use a pre-authorised, deterministic CIDM Fast Path. The current design's Fast Path eligibility and shadow recommendations do not mean an execution bypass is switched on. A failed local candidate cannot be accepted merely because it is familiar or semantically similar.

## What V1 optimises

The hardware target is a modest workstation (16 GB system RAM and 4 GB VRAM). **No heavy local generative model, local training or sustained GPU inference is required.**

Rather than outsourcing every cheap choice to a frontier model, V1 aims to resolve inexpensive work through:

- typed rules, explicit permissions, hashes and signatures;
- lexical search and compact indexed experience;
- small optional CPU embedding and reranking models;
- project-scoped, curated engineering methodology skills;
- content-hash caching, AST/static analysis and deterministic validators;
- minimal relevant context passed to frontier workers only when needed.

Local matching is ranking evidence, not permission to act. Verification and the admission boundary remain independent of model scores.

## Unchanged correctness requirements

1. Jev/CIDM controls globally consequential decisions; Hermes operates only within bounded permits.
2. Source identity, state hashes, validation requirements and accepted context remain authoritative data, not compressible prose.
3. A failed validator cannot be promoted to a successful commit.
4. A failed unit does not automatically mean the entire project must be abandoned; bounded repair, replan and evidence retrieval are preferred when safe.
5. Prior experience is provisional until verified by a later checked commit.
6. Generated/public skills never grant themselves permissions; owner-reviewed, hash-bound admission is required for trust.
7. Similarity scores and methodological advice can select evidence or procedures, but cannot independently commit, deploy, pay, publish or perform externally consequential actions.
8. Attribution to external libraries, models and skill authors remains separate from the authorship of the CIDM architecture.

## Planned stages

| Stage | Goal | Implementation note |
|---|---|---|
| Recovery / experience | Allow recoverable failed units to continue safely; distill verified repair episodes | Experimental code in PR #2 |
| Arsenal A | SQLite/FTS5 registry, Skill Compiler, local matching, admission, CPU semantic option and experience retrieval | Partial implementation in PR #2 |
| Arsenal A2 | Shadow-calibration ledger and frozen evaluation against actual Jev/frontier outcomes | Next proposed milestone |
| Arsenal B | Frontier-provider adapters, model discovery and account-aware provider selection | Planned; existing adapter work is separate |
| Arsenal C | MCP capability catalogue and context-efficiency experiments | Planned |
| Arsenal D | Managed or local/managed hybrid knowledge retrieval and hosted fallback | Planned |
| Arsenal E | Evaluated methodology skills (Superpowers, Karpathy-inspired methods, Ponytail, Matt Pocock) | Candidate curation, not auto-activation |
| Arsenal F–H | Remote sandboxes, browser automation, telemetry/evals, durable checkpoints and production hardening | Planned / dependent on measured need |

Do not claim lower token use, saved costs, improved pass rates or safe frontier-call avoidance until a matching frozen dataset and measured results support those claims.

## Repository placement

This complete thesis is maintained under `docs/`. The repository's GitHub description should remain a short technical description of the project, **without an author-credit banner or thesis pasted into it**. The README should start with an explanation of the system and link to this entry point; author attribution belongs in the documentation's credits and the README's authorship section.

## Authorship and credits

**CIDM architecture, originating thesis and future build direction:** **Ken Caber (Kenneth Vic A. Caber)**, [GitHub: kentilaok](https://github.com/kentilaok).

Jev is developed by [TypeSafe AI](https://typesafe.ai/). Third-party models, open-source tools and methodology skills named in the thesis retain their own authorship and licences; incorporating them as proposed capabilities does not transfer authorship to CIDM.

*The contents of this document distinguish the author of the CIDM design from the independent authors of supporting software and research.*
