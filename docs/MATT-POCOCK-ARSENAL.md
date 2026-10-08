# Matt Pocock Skills — governed CIDM Arsenal source

**Source:** https://github.com/mattpocock/skills  
**Upstream author:** Matt Pocock  
**Upstream license:** MIT  
**Pinned review revision:** `f3fc5632f401156837ee3872f14fe33ccf1024ea`  
**Catalogue:** `arsenal/sources/matt-pocock.json`  
**State:** candidate source, not automatically installed or owner-admitted.

## Why include these skills?

Matt Pocock's *Skills for Real Engineers* focuses on small, composable engineering practices: reproduce and diagnose bugs, test at public seams, build deep modules, maintain project vocabulary and ADRs, review diffs, and make more useful handoffs.

These practices align well with CIDM's recovery, validation, experience distillation and frontier-token reduction goals.

The upstream library has both **user-invoked workflow commands** and **model-invoked reference skills**. Preserve that distinction. A workflow command must not silently become a globally autonomous router.

## Initial curated selection

| Skill | Tier | CIDM use | Boundary |
|---|---|---|---|
| `diagnosing-bugs` | Core | Failure → reproducer → repair → regression test | Hard checks still gate commits |
| `tdd` | Core | Red/green/refactor with public-interface tests | CIDM selects required validators |
| `codebase-design` | Core | Deep modules, minimal exposed interfaces | Architecture suggestions, not policy |
| `domain-modeling` | Core | Glossary, domain language, ADR context | Project-controlled document writes |
| `writing-for-agents` | Core | Compact context pointers and skill instructions | Do not rewrite authoritative permits |
| `code-review` | Review | Standards + spec review with evidence | Parallel subagents require Jev permit |
| `retro` | Review | Feed environmental improvements into Experience Plane | No automatic skill/policy promotion |
| `grill-with-docs` | Review | Clarify requirements and document vocabulary | Only for explicit exploratory workflow |
| `to-spec` | Review | Turn agreed context into a spec | No unilateral issue-tracker writes |
| `to-tickets` | Review | Traceable dependency-aware task decomposition | Jev owns global work planning |
| `improve-codebase-architecture` | Review | Architecture opportunities report | Proposed changes need approval/tests |
| `pr` | Review | Concise PR evidence and blast-radius summary | No automatic merges |
| `handoff` | Review | Compact durable session handoffs | Keep source/skill provenance |
| `implement` | Restricted | Full implementation workflow | Overlaps CIDM/Hermes orchestration |
| `implement-spec` | Restricted | Parallel task graph | Do not permit autonomous fan-out |
| `ask-matt` | Restricted | Upstream routing command | CIDM/Jev is the authoritative router |
| `wayfinder` | Restricted | Cross-session project orchestration | Never independently control project state |
| `triage` | Restricted | Issue lifecycle automation | External write needs separate permit |

The importer defaults to **Core** only. Review-tier skills are opt-in. Restricted ones require choosing the exact skill and remain inert candidate material until they have been adapted and reviewed.

No upstream skill is given an executable Fast Path merely because it has an appealing methodology or is popular.

## Local staging (no frontier calls, no heavy models)

Use a **pinned checkout** of the upstream repository:

```bash
git clone https://github.com/mattpocock/skills.git matt-pocock-skills
cd matt-pocock-skills
git checkout f3fc5632f401156837ee3872f14fe33ccf1024ea
cd ..
```

Preview the Core set without copying anything:

```bash
python scripts/arsenal_import_matt_pocock.py \
  --source-root ./matt-pocock-skills \
  --dest ~/.jev/arsenal/quarantine/matt-pocock
```

Stage only the Core set to **quarantine** (no execution or admission):

```bash
python scripts/arsenal_import_matt_pocock.py \
  --source-root ./matt-pocock-skills \
  --dest ~/.jev/arsenal/quarantine/matt-pocock \
  --install
```

To explicitly select a Review skill:

```bash
python scripts/arsenal_import_matt_pocock.py \
  --source-root ./matt-pocock-skills \
  --dest ~/.jev/arsenal/quarantine/matt-pocock \
  --skill retro \
  --install
```

The importer:

1. requires the **exact pinned upstream commit** and a clean tracked checkout;
2. copies only the requested allowlisted skill subdirectories, their bundled references, and the upstream MIT licence notice (`UPSTREAM_LICENSE.txt`);
3. refuses symlinks, path escapes, existing destinations, and oversized packages;
4. creates conservative `ARSENAL.json` manifests with denied permissions;
5. never executes skill code, installs packages, changes model sessions, or calls external services;
6. never grants owner admission.

After staging, index the quarantined candidates without exposing them to an active Hermes session:

```bash
python scripts/arsenal_registry.py scan \
  --skills-dir ~/.jev/arsenal/quarantine/matt-pocock
python scripts/arsenal_registry.py list
```

**Do not place quarantined files directly into an active agent skills directory.** The importer rejects the default Hermes, Claude Code, and Codex skill directories, including a configured `HERMES_HOME/skills`.

After reviewing a skill and its manifest, source, scripts, permissions and tests, an operator may explicitly hash-admit that exact copy using `arsenal_registry.py admit --skill-id ...`. The separate activation/copy into Hermes should be handled by a controlled, owner-approved deployment process. Quarantined candidates have **no execution authority**; the importer deliberately does not provide an automatic activate command.

Discovered skills can provide **relevant procedural context** to a frontier worker, but CIDM must continue to apply existing permissions, evidence requirements, validators and Jev decisions.

## Admission is a separate security review

A candidate must be reviewed for:

- upstream source hash, licence and bundled references/scripts;
- requested file/network/shell/tool permissions;
- whether instructions call other skills or spawn subagents;
- project scope and interaction with existing Superpowers/Karpathy/Ponytail skills;
- externally consequential actions (tickets, PRs, commits, deployment);
- regression tests and measurable impact on correctness/token usage.

Even after human review, actual admission is only the registry's local hash-bound record. Changing the skill or its manifest invalidates previous admission.

For these **methodology skills**, do not set `frontier_required: false` without a separately evaluated deterministic procedure, explicit low-risk operation, and validators. Most should remain `frontier_required: true`: the purpose is to improve quality and minimise repeated context, not to pretend a prose engineering skill is deterministic code.

## Avoid overlapping method controllers

CIDM decides **what to do, when, with which resources, and whether to commit**.

Hermes may apply:

- Matt's `diagnosing-bugs` for a bounded debugging unit;
- `tdd` at a chosen test seam;
- `codebase-design` when architecture guidance is needed;
- `writing-for-agents` to create more efficient reference documents;
- `retro` to propose candidate reusable improvements.

If both Superpowers' debugging procedure and Matt's `diagnosing-bugs` match, select one primary method per unit and evaluate the alternative in a controlled comparison. Do not load both entire playbooks into every prompt.

## Performance and experience metrics

Tag each CIDM execution with the exact method skill/version/hash. Measure:

- task completion and validator pass rate;
- regression/bug recurrence rate;
- quality of TDD test seams;
- frontier tokens and duration;
- repeat prompts / unnecessary context;
- feedback-loop length;
- useful findings in reviews/retros;
- negative transfer when a skill made things worse.

A skill may improve a workflow without reducing its frontier cost. Keep both metrics visible and do not automatically promote an unverified lesson.

## Deferred

Avoid installing the complete upstream plugin plus editable skills simultaneously (duplicate skill names and redundant context). Do not let `ask-matt`, `implement-spec`, `wayfinder`, or `triage` become parallel global orchestrators. Never track upstream `main` automatically in the trusted skill store; new upstream releases should generate new candidate hashes and fresh evaluation.

**Boundary:** Matt Pocock's skills enrich the **engineering methodology arsenal**. They do not replace Jev, Hermes, validators, the Experience Plane, or the Arsenal owner-admission gate.


---

*CIDM architecture and research direction: Ken Caber (Kenneth Vic A. Caber). External projects and skills retain their respective authorship and licences.*
