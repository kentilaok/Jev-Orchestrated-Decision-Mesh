# Task Postconditions

**Status:** closes P0-02 at the shape layer. Coding-task postconditions ship with concrete checks; non-coding task classes follow the same protocol as they are declared.

Task-specific deterministic release gates applied *after* `NativeTransitionBroker._validate_candidate` has accepted the shape, hashes, parent links, and declared unresolved fields of a candidate. Structural validation does not establish the **truth** of the candidate's claims; postconditions do, within what deterministic checks can prove.

## 1. Why

Audit finding **D-08** (structural-only release checks) and **D-09** (concealed unresolved items) remain open until Jev withholds release on a schema-valid-but-wrong candidate. This module adds that withhold path without editing the broker's complex invariant-heavy class.

## 2. Shape

```
NativeTransitionBroker.run(spec)                   # structural validation
        │
        ▼
result = {status: "complete", answer: "…", …}      # or already-failed
        │
        │  caller invokes:
        ▼
scripts/postconditions_broker.apply_postconditions(
    result=result,
    broker_candidate=…,
    declared_files=…,
    workspace=…,
    checks=[…])
        │
        ▼
result['postconditions'] = {decision, results, failed, unresolved}
if decision == 'withhold' and result['status'] == 'complete':
    result['status'] = 'postconditions_failed'
    result['answer'] = None
```

The adapter never silently rewrites a broker-reported failure; if the broker already said `quality_failed` or `audit_failed`, that diagnosis stays, and the postconditions report sits alongside it.

## 3. Protocol

Each check is a `PostconditionCheck`:

| Field | Meaning |
|---|---|
| `name` | Stable identifier used in reports (`tests_exit_zero`, `no_concealed_unresolved`, …). |
| `kind` | Coarse category (`build`, `tests`, `files`, `lint`, `unresolved`, …). Used for grouping in audit UIs. |
| `required` | `True` → a non-pass withholds release. `False` → informational only. |
| `evaluator` | `(candidate: dict, workspace: Path) -> PostconditionResult`. |

Each evaluator returns a `PostconditionResult`:

| Field | Meaning |
|---|---|
| `status` | `pass` / `fail` / `unresolved`. |
| `evidence` | JSON-serialisable dict (exit codes, file lists, output tails). |
| `reasoning` | Short human-readable sentence. Non-empty. |
| `name` | Set by the runner from `check.name`; evaluators do not supply it. |

An evaluator that raises is captured as `unresolved` with the exception type and text in `reasoning` — the runner never crashes the broker.

## 4. Coding-task checks

| Factory | Behaviour |
|---|---|
| `build_exit_zero(cmd)` | Runs `cmd` in `workspace`; pass iff exit 0. Captures returncode and 400-char stdout/stderr tails. 300 s subprocess timeout. |
| `tests_exit_zero(cmd)` | Same shape, for the test runner. |
| `lint_clean(cmd)` | Same shape, for the lint runner. |
| `files_changed_match_declared()` | `git status --porcelain=1` in `workspace`; pass iff declared `candidate['files_changed']` equals the actual changed set. Fail with `undeclared` / `missing` lists in evidence. Rename `A -> B` resolves to `B`. Requires `git` on PATH. |
| `no_concealed_unresolved()` | Scans `candidate['output']` for `TODO`, `FIXME`, `UNRESOLVED`, `XXX` (case-insensitive). A marker present with an empty `candidate['unresolved_stages']` fails (closes D-09 at this layer). Markers plus at least one declared stage passes. |

Commands are lists (`["python", "-m", "pytest"]`) — never a shell string — so there is no shell-injection surface. `cmd[0]` resolves via PATH; the operator is responsible for pinning build tool versions.

## 5. Candidate shape adapter

`extract_candidate_fields(broker_candidate, declared_files)` maps the broker's internal shape:

```yaml
broker_candidate:
  text: "<assistant output>"
  data:
    summary: "…"
    claims: ["…"]
    unresolved: ["optional declared stages"]
    parent_hashes: […]
    source_hashes: […]
  source_ids: […]
  five_scores: [1..5] * 5
  self_probability: 0..1 | null
```

to the generic shape the checks consume:

```yaml
candidate:
  output: "<broker_candidate.text>"
  files_changed: ["<declared>"]           # caller-supplied (from spec)
  unresolved_stages: ["<data.unresolved>"]
```

Fields the checks do not use (`claims`, `source_hashes`, scores) are not forwarded; the adapter is intentionally lossy to keep check inputs small and auditable.

## 6. Adversarial corpus

`tests/fixtures/postconditions/*.json` holds the P0-02 pass-condition evidence. Each fixture is a self-contained JSON object:

| Key | Meaning |
|---|---|
| `name`, `description` | Audit identifier and one-liner. |
| `broker_candidate` | Full broker-shaped candidate. |
| `declared_files` | What the candidate claims it changed. |
| `checks` | List of check factory names (keys of `CHECK_FACTORIES` in the test). |
| `expected_decision` | `release` or `withhold`. |
| `expected_failed` | Expected names in the withhold list. |

Current fixtures:

| Fixture | Decision | What it proves |
|---|---|---|
| `all_green.json` | release | Control: a clean candidate ships. |
| `concealed_todo.json` | withhold | Schema-valid candidate hides a `TODO`. |
| `concealed_fixme.json` | withhold | Same, with `FIXME`. |
| `declared_markers_pass.json` | release | Transparent candidate with declared stages ships. |

`AdversarialCorpusTests.test_corpus_contains_both_release_and_withhold_cases` enforces that the corpus always carries at least one of each outcome, so a future contributor cannot accidentally reduce it to all-pass.

## 7. Known limitations

1. **Marker-to-stage pairing is loose.** `no_concealed_unresolved` passes as soon as *any* declared stage is present when markers appear. Tighter pairing (match each marker to a named stage) can land as a follow-up slice if a real task class trips the gap.
2. **Classifier is syntactic.** A worker that writes `later we need to clean this up` without a marker word passes the check. Semantic unresolved detection is out of scope; the shape layer is honest about its coverage.
3. **Timeouts are hard-coded.** Build/test/lint commands cap at 300 s; `git` at 30 s. Operator-configurable timeouts land when a real task class needs them.
4. **No in-broker hook yet.** The adapter sits outside `NativeTransitionBroker.run`; callers must invoke `apply_postconditions` on the result. A future slice can promote it to a `run(…, postconditions=…)` kwarg if operators ask.
5. **Stdlib only.** No PyYAML, no Pytest. All checks shell out through `subprocess.run`.

*CIDM architecture and research by Ken Caber (Kenneth Vic A. Caber).*
