# Arsenal Phase A2 — Shadow Calibration and Evidence-Based Evaluation

**Project/thesis:** Caber Interstitial Decision Mesh (CIDM), by **Ken Caber (Kenneth Vic A. Caber)**.

**Status:** experimental implementation on recovery/Arsenal PR #2. This is **evaluation**, not a Fast Path executor.

The design question is not "Can a local embedding match something?" It is:

> Would an approved, deterministic local skill have solved this *specific* task safely, under the correct project scope, operation permit and validators, without a frontier call?

The answer requires a real run, a frozen prediction made **before** that run, and an independent human-reviewed outcome.

## Record types

The append-only JSONL ledger `~/.jev/arsenal/calibration.jsonl` contains three events sharing **run ID** and **CIDM input snapshot hash**:

| Event | Origin | Does it prove Fast Path safety? |
|---|---|---|
| `prediction` | Arsenal shadow matcher, before execution | No |
| `runtime` | Native broker result, model calls and audit status | No |
| `verdict` | Independent reviewer, with evidence reference | Reviewed label, not automatically verified by this tool |

A prediction stores task hash, scope, bug key, operation, selected skill and experience, skill/manifest hashes, exact-key evidence, local score, recommendation and candidate flag. It does **not** persist the full task/prompt. Sensitive contents must be protected in the original broker journal, skill store and review evidence.

A runtime stores actual native broker status, whether the run was a simulation, audit evidence flag, compact boolean validator outcomes, a hash of any validator/audit receipts, call count and per-role counts, and usage if completely reported. Missing token counts/costs remain `null` rather than becoming invented zeroes.

A verdict stores the reviewer's ID, an evidence reference, correct skill and experience IDs if any, and whether the particular task was independently judged safe for the proposed deterministic Fast Path.

Each ledger line contains its own SHA-256 hash and the preceding line's hash. Readers fail closed when a hash link breaks. This is **tamper-evident for accidental or partial alteration**, not protection against someone who can rewrite the entire file. For V1 use one ledger writer at a time; concurrent writers are not yet coordinated. Keep the ledger access-controlled and backed up.

**The adjudication CLI does not open or cryptographically verify the evidence reference.** That remains a human/CI review requirement. It does not make subjective labels objective proof. An audit failure or simulated run is excluded from quality scoring even if a reviewer submits a verdict.

## Instrument the native broker

Initialize the skill registry and scan relevant candidate sources first:

```bash
python scripts/arsenal_registry.py scan --skills-dir ~/.hermes/skills
```

For a standard real native run, add two opt-in flags to the existing broker command:

```bash
python scripts/native_transition_broker.py \
  --live \
  --gate-policy recovery \
  --task examples/native-project.request.json \
  --out runs/native-arsenal-a2-001 \
  --arsenal-shadow \
  --arsenal-project-scope cidm-research \
  --arsenal-calibration-ledger ~/.jev/arsenal/calibration.jsonl
```

The broker first gathers the ordinary Arsenal shadow observation. **Normal Jev/frontier routing, validator checks and commit rules are unchanged.** After completion, the broker appends compact prediction/runtime events. If calibration recording fails, the broker preserves its original status and records the calibration error as secondary metadata.

`--arsenal-calibration-ledger` requires `--arsenal-shadow`. The normal standalone shadow JSONL remains separate. A validation-only request does not count as an audited real outcome.

If a previous run already has a `result.json` with `arsenal_shadow`, it can be imported without rerunning it:

```bash
python scripts/arsenal_calibration.py \
  --ledger ~/.jev/arsenal/calibration.jsonl \
  capture \
  --run-id native-001 \
  --result runs/native-arsenal-a2-001/result.json
```

The importer refuses duplicate run IDs/events, incompatible task hashes and invalid shadow authority claims. Avoid capturing the same run with both native automatic recording and manual capture.

## Independent outcome review

Review the original task, the matched skill/manifest hash, CIDM's accepted evidence and validator receipts, final status and any manual human confirmation. Verify that the candidate's proposed operation would have been sufficient, within permits, to pass the same validators.

Then record an **independently reviewed** label:

```bash
python scripts/arsenal_calibration.py \
  --ledger ~/.jev/arsenal/calibration.jsonl \
  adjudicate \
  --run-id native-001 \
  --task-hash <EXACT_64_CHARACTER_CIDM_INPUT_HASH> \
  --evidence-ref runs/native-arsenal-a2-001/result.json \
  --reviewer reviewed-by-operator \
  --expected-skill-id your-reviewed-skill-id \
  --fast-path-safe no
```

Use `--fast-path-safe yes` **only** where the reviewer has established that the predicted preapproved deterministic operation, scopes, permissions and validators would have sufficed. A general code fix that needed frontier reasoning should be `no`. A different matching skill may be specified as the expected skill; a predicted fast candidate for the *wrong* skill is counted as unsafe.

For a no-skill task omit `--expected-skill-id`. For experience-only cases `--expected-experience-id` may identify the correct lesson, but past experience does not itself authorize execution.

Do not adjudicate from the model's confidence, embedding score, or recommendation alone. Evidence should be stable and traceable, ideally tied to a commit/source hash or an immutable CI log.

## Evaluation

```bash
python scripts/arsenal_calibration.py \
  --ledger ~/.jev/arsenal/calibration.jsonl \
  evaluate
```

The evaluator reports:

- eligible, complete reviewed real runs vs missing, simulated or unaudited data;
- selected-skill and selected-experience correctness;
- Fast Path true positives, false positives, false negatives and true negatives;
- precision, recall and false positive rate among predicted Fast Path candidates;
- reported observed model calls and a task-level count of *hypothetical* avoidable opportunities;
- `estimated_token_savings: null` and `realized_frontier_calls_avoided: 0`, because shadow mode cannot actually save calls or identify per-task counterfactual token use.

**Interpretation warning:** Hypothetical opportunities are **not** guaranteed calls saved. A task may have multiple Jev, worker and checker calls, a deterministic solution may only replace one component, and quality/cost equivalence must be experimentally established. A high precision on a tiny dataset is not evidence of production safety.

If there are no reviewed Fast Path predictions, precision is `null` rather than 0 or 1.

## Frozen benchmark before Fast Path

Construct a frozen, versioned set of representative tasks from different projects and risk classes:

1. repeatable exact bug-key and validator-bound tasks;
2. same bug-key but different project context (negative transfer);
3. nearly matching text with different underlying cause;
4. stale/changed skill hash (admission revoked);
5. missing or ambiguous operation/validator;
6. nonreversible/external write requests;
7. partial evidence, paused-recoverable and failed-audit runs;
8. synthetic test cases marked as such and **excluded from real-run metrics**.

Every dataset item should include a reviewer, evidence, expected result and explicit rationale. Keep model/provider versions, scope, skill hash, threshold and dataset revision stable while comparing strategies.

Promotion should require an operator-defined safety threshold, adequate real reviewed sample size, zero critical invariant breaches and a separately tested deterministic operation with independent validator receipts. **No automatic Fast Path activation is implemented by Phase A2.**

## Implementation

- `scripts/arsenal_calibration.py` — append-only events, CLI capture/adjudicate/evaluate and conservative metrics
- `scripts/native_transition_broker.py` — optional calibration collection after a real run
- `tests/test_arsenal_calibration.py` — adversarial and workflow regression tests
- `scripts/arsenal_registry.py` — candidate skill/experience retrieval
- `scripts/arsenal_shadow.py` — observation-only routing and hybrid candidate fusion

The historical and full design constraints remain in [Complete Thesis](COMPLETE-THESIS.md) and [Arsenal V1](ARSENAL-V1.md). The actual calibration ledger must remain an operational artifact; do not commit secrets, private tasks, raw provider transcripts or personal data to the public repository.
