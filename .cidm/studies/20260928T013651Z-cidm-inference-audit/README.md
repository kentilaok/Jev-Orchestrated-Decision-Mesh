# Study `20260928T013651Z-cidm-inference-audit`

An inference-economics audit of the Caber Interstitial Decision Mesh (CIDM), attributed in this project to Kenneth Vic A. Caber. The study investigates the design; it makes no claim about scientific priority or patentability.

**Status:** audit, reconciliation, offline tests, replay, mock harness validation and candidate fixes are done. **No live model calls were made** (no approved budget; egress blocked). Start with `RESULTS.md` §9.

## Artifacts

| Path | What it is |
|---|---|
| `AUDIT.md` | Architecture, call paths with file:line citations, ledger audits, defect register, unknowns |
| `RESEARCH.md` | R1–R12 verification (snippet level) and claim-to-experiment map |
| `RESULTS.md` | Evidence status, accounting coverage, measured vs estimated vs mock results, answers, unrun live tests |
| `EXPERIMENT.yaml` / `EXPERIMENT.json` | Frozen preregistration (hashes in `provenance/preregistration-sha256.txt`) |
| `model-registry.json`, `pricing-snapshot.json` | Route identities, verification levels, dated prices corroborated against recorded charges |
| `schemas/event.schema.json` | Append-only event format (null + reason; provenance labels; raw usage preserved) |
| `fixtures/` | 19 fictional tasks (7 dev, 12 held-out; disjoint lineages); `answer-keys/` are read only by `harness/grade.py` |
| `harness/` | Accounting library, reconcilers, replay, Jev decision analysis, budget guard, providers (mock + live), arms, runner, grader, analysis |
| `tests/` | `test_accounting.py` (20), `test_harness.py` (14: budget, grader, key separation) and `test_audit_findings.py` (16 findings, F01–F16, against the unchanged code) |
| `reconciliation/` | Public-evidence reconstruction: `events.reconstructed.jsonl`, `claims-vs-raw.csv`, checksum, dedupe and pricing reports, `jev-decision-analysis.json`, replay results |
| `events.jsonl`, `results.csv` | Raw-derived records of the published evidence (copies of the reconstructed events and per-bundle totals) |
| `runs/mock-smoke-dev/`, `runs/mock-pilot-heldout/` | **Mock** harness validation (not evidence) |
| `candidate-skill/`, `patches/`, `CHANGELOG.md`, `ROLLBACK.md` | Feature-flagged candidate and how to test or revert it |
| `provenance/` | Environment, file hashes, test logs (Python 3.10–3.13 matrix) |

Private project evidence (`.cidm` ledgers) was analysed separately and is **not** in this public directory. The private study package holds the full `AUDIT.md`/`RESULTS.md` and `private-reconciliation/`.

## Commands verified in this study (Linux, Python 3.11, run from this directory)

```bash
python -B -m unittest discover -s tests -v                                   # 50 tests
(cd candidate-skill && python -B -m unittest discover -s tests -v)           # 142 tests
python -B harness/reconcile_ledgers.py --repo ../../.. --out reconciliation
python -B harness/jev_decision_analysis.py --repo ../../.. --events reconciliation/events.reconstructed.jsonl --out reconciliation
python -B harness/replay_gate_variants.py --repo ../../.. --out reconciliation --scripts-rev 9a56346
python -B harness/build_fixtures.py --out fixtures                            # reproduces MANIFEST hashes
python -B harness/run_benchmark.py --mode mock --split dev --reps 1 --out runs/<new-dir>
python -B harness/analyze.py --run runs/<new-dir>
python -B harness/reconcile_windows_cidm.py --cidm <path-to-.cidm> --out <private-dir> --zip <path-to-.cidm.zip>
```

## Windows equivalents (UNVERIFIED: not executed on Windows)

```powershell
$Study = "<EVIDENCE_ROOT>\studies\20260928T013651Z-cidm-inference-audit"
Set-Location -LiteralPath $Study
py -3.12 -B -m unittest discover -s tests -v
py -3.12 -B harness\reconcile_windows_cidm.py --cidm "<EVIDENCE_ROOT>" --out "$Study\private-reconciliation"
# Live pilot: needs an explicit approved cap. Set OPENROUTER_API_KEY in this session by your usual
# secure method; never put it on the command line or in a file inside the study.
py -3.12 -B harness\run_benchmark.py --mode live --split heldout --reps 3 --arms A,B,C,D,E1,E2 `
   --max-usd 10 --per-run-usd 0.60 --per-request-usd 0.15 --i-accept-live-spend --out "$Study\runs\live-pilot-001"
```

On Windows, `harness/run_benchmark.py` expects the repository layout: the study directory three levels below a checkout containing `scripts/`. Arm D imports `REPO:scripts`, so point it at a checkout whose `scripts/` equals the installed skill.

## Regenerating omitted large files

- The mock pilot's raw events and candidates are not committed (about 15 MB). Rerun:
  `python -B harness/run_benchmark.py --mode mock --split heldout --reps 3 --out runs/mock-pilot-heldout-regen`
  Mock outputs are keyed on prompt content, so decisions reproduce; timestamps differ.
- `snapshot/` (the frozen skill copy) is not committed; recreate it with `git archive 327c36b SKILL.md README.md agents docs examples scripts tests`. Hashes are in `provenance/snapshot-sha256.txt`.
