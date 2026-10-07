# Recovery-first CIDM and Experience Distillation

**Status:** experimental architecture extension. It preserves the existing CIDM reference controllers as baselines and adds a new supervisory layer rather than rewriting historical protocol semantics.

## Problem

CIDM's core safety invariant is valuable: **a candidate that fails hard checks cannot be forwarded or committed**.

The earlier controllers also made a stronger operational assumption: a local unit that returns anything other than `forwarded` ends the top-level run. That is safe, but brittle for long-lived autonomous work. A recoverable gate failure, missing evidence, or exhausted local repair loop can therefore terminate an otherwise viable project.

The recovery-first extension separates:

```text
candidate may not advance
          !=
project may not continue
```

## Recovery-first control plane

The new `scripts/recovery_protocol.py` provides two components.

### RecoveryJudge

`RecoveryJudge` wraps the normal Jev judge. When a gate contains both `stop` and at least one bounded progress option, it withholds `stop` from the offered action set.

Jev still chooses among the remaining actions. The wrapper does not fabricate a decision.

An operator abort callback can immediately restore `stop`. This preserves a true terminal path for explicit cancellation or external policy.

### RecoverySupervisor

`RecoverySupervisor` runs the ordinary separate-gate `CheckedNetwork` one unit at a time.

It keeps the original forward eligibility rules. It does **not** commit failed candidates.

Its behaviour is:

```text
forwarded
  -> next unit

repair_limit / verification_limit / non-explicit stop
  -> fresh local replan of the same unit
  -> bounded by max_recovery_rounds

needs_evidence
  -> trusted read-only evidence retriever if configured
  -> append new immutable source IDs
  -> retry same unit

needs_evidence without retriever
  -> paused_recoverable checkpoint

recovery budget exhausted
  -> paused_recoverable checkpoint

controller exception / integrity failure
  -> failed
```

A checkpoint includes the active unit, committed prefix, recovery reason, recovery round, policy version, mesh state hash, and journal cursor.

The intended host can persist that checkpoint, satisfy the dependency, and resume from the same in-memory network or reconstruct a later resumable host adapter. A checkpoint is not a permit and cannot authorize a commit.

## Configurable local attempts

The legacy `CheckedNetwork` still defaults to its original limits, but now reads:

- `max_recovery_attempts` — default 2, bounded 1–8
- `max_verification_attempts` — default 2, bounded 1–4

This keeps historical behaviour unchanged unless an experiment opts into a different policy.

The fused protocol remains a separate experimental baseline. Its deferred permits encode a two-attempt assumption and should not be generalized until a recovery-specific fused permit contract is designed and audited.

## Evidence recovery

A recovery evidence callback receives a bounded packet containing:

- goal
- active unit
- committed prefix
- recent events
- current source manifest

It may return **new** source IDs only. Existing sources cannot be silently replaced.

The supervisor hashes every added source, increments the mesh version, records `recovery_evidence_added`, and retries the same unit. A stale permit from before evidence retrieval cannot be reused because the mesh state changes.

The evidence callback is trusted integration code, just like the existing producer/checker/validator callbacks. A production host should constrain it to read-only connectors and record source provenance.

## Experience Distillation

`scripts/experience_distiller.py` creates an experience plane beside the decision and execution planes.

```text
CIDM / Hermes run
       |
       v
append-only events
       |
       v
experience extraction
       |
       +-- unresolved failure ----------> retained as evidence only
       |
       +-- failure -> verified commit --> verified experience
                                      |
                                      v
                                grouped lesson
                                      |
                         repeated or owner-approved
                                      |
                                      v
                              Hermes SKILL.md
```

This is **not model-weight training**. It is retrieval/procedural context that reduces repeated reasoning.

### Promotion rule

A model explanation is not enough to create durable skill knowledge.

A recovery is considered verified only when a failure event for a unit is followed later by a `checked_commit` for that same unit.

By default, a lesson becomes promotable after **two verified observations**. The operator can explicitly approve a one-off lesson with `--owner-approved`.

Every generated skill includes provenance back to run IDs, failure events, verification events, and accepted artifact hashes.

### Raw ledger

The raw experience ledger is append-only JSONL. The default is:

```text
~/.jev/experience/ledger.jsonl
```

Distilled lessons default to:

```text
~/.jev/experience/lessons.json
```

These are local runtime state rather than source-controlled claims.

### Distill saved CIDM research runs

```bash
python scripts/experience_distiller.py \
  --scan-dir research \
  --skills-dir ~/.hermes/skills
```

The scan recursively considers `result.json` and `*.result.json` files that contain CIDM event arrays.

With the default promotion threshold, a single successful recovery creates a provisional lesson but does not write a Hermes skill.

To approve a known one-off recovery:

```bash
python scripts/experience_distiller.py path/to/result.json \
  --skills-dir ~/.hermes/skills \
  --owner-approved
```

After skill files are written, Hermes should reload or begin a new session so its skill registry sees the change.

## Three-plane architecture

```text
                  JEV DECISION PLANE
         scope / evidence / budget / arbitration
                          |
                          v
                HERMES EXECUTION PLANE
          skills / memory / tools / frontier model
                          |
                          v
                    VALIDATORS
                          |
                          v
                 JEV ACCEPT / RECOVER
                          |
                          v
                EXPERIENCE PLANE
       raw evidence -> lessons -> verified skills
                          |
                          +------> future Hermes runs
```

The learning plane never receives authority to bypass the decision plane.

A distilled skill is advice about a previously verified procedure. Current evidence, current policy, current validators, and current Jev permits remain authoritative.

## Stability criteria

The recovery-first architecture should not be called stable merely because it completes more runs.

Evaluation should measure at least:

- project completion rate
- correct candidate rate
- released-answer quality
- false-negative gate rate
- recoveries attempted
- recoveries that later validate
- checkpoints requiring owner/external input
- terminal integrity failures
- repeated-bug recurrence before and after skill promotion
- Jev, worker and checker calls
- total tokens, cost and latency
- skill precision: how often a loaded skill helps vs misleads

A recovery policy is an improvement only if it raises useful completion without weakening commit invariants or producing runaway retry cost.

## Initial safety invariants

1. Failed hard checks still remove forward eligibility.
2. Recovery never mutates a committed artifact.
3. Newly retrieved evidence uses new source IDs and hashes.
4. Checkpoints are state records, not permits.
5. A distilled lesson requires a later verified commit.
6. Automatic skill promotion requires repeated verified observations.
7. Owner approval can promote a single verified lesson, but cannot turn an unverified failure into a skill.
8. Current evidence and validators override old skills.
9. Operator abort remains terminal.
10. Raw experience remains available for audit even when a lesson or skill is later archived.

## Next implementation milestones

1. Add persistent reconstruction/resume of a checkpoint across process restarts.
2. Give the Operator Console a recovery/checkpoint view and experience-learning view.
3. Connect Hermes' skill enable/disable UI to distilled-skill provenance.
4. Add project-scoped skill namespaces so unrelated projects do not cross-contaminate.
5. Add negative-transfer telemetry when a skill is loaded but a different recovery succeeds.
6. Design a recovery-first fused permit protocol instead of extending the current two-attempt fused contract implicitly.
7. Benchmark against the current separate-gate and fused baselines on frozen project-scale tasks.
