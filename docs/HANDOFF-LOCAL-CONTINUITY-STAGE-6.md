# Stage 6 handoff — saved pilot evidence, evaluation and integration review

**Date:** 9 October 2026  
**Branch:** `feature/local-continuity-split-context-plan`  
**Status:** experimental local-only implementation and stage-by-stage offline unit fixtures **committed**, **not validated on the user's Windows workstation**, **not production accepted**. Existing V1 production HOLD continues.

## Delivered this stage

- `scripts/local_continuity_pipeline.py`: optional `--out` writes a detailed run result to a new local JSON file (separate frozen context packages, separate lane proposals, permits, comparisons and learning evidence). Console starts local-only jobs and saves `runs/local-only-*/result.json`. Terminal prints only compact run metadata, not full SOP content.
- `scripts/operator_console.py`: passes the saved artifact path for Console Qwen runs.
- `scripts/local_continuity_evaluation.py`: reads local-only result JSON and reports actual lane status and usage **when present**. Any unmeasured cost, verified output quality, skill accuracy or token savings is **null**, never fabricated.
- `tests/test_local_qwen_stage6.py`: checks that evaluation refuses to invent unmeasured outcomes.

## Overall staged file index

1. [Stage 1 — Ollama read-only provider](HANDOFF-LOCAL-CONTINUITY-STAGE-1.md): strict loopback, model digest preflight, limited JSON artifacts, permit receipts.
2. [Stage 2 — independent SOP lanes](HANDOFF-LOCAL-CONTINUITY-STAGE-2.md): A direct SOP and B complementary skill/lesson, isolated contexts and provider sessions, default serialized inference.
3. [Stage 3 — comparison and learning](HANDOFF-LOCAL-CONTINUITY-STAGE-3.md): comparison withheld without external checks, reviewed evidence ledger (no auto promotion), local-only pipeline.
4. [Stage 4 — Console / mode policy](HANDOFF-LOCAL-CONTINUITY-STAGE-4.md): four-mode *policy schema*, live **Local Only** Console path, others disabled pending validation.
5. [Stage 5 — scale and memory](HANDOFF-LOCAL-CONTINUITY-STAGE-5.md): bounded dense candidate scores, FTS fallback guard, explicit physical-parallel VRAM requirements.
6. This document: pilot evidence and production acceptance plan.

## Full Windows handoff

**1 — Pull feature branch without losing local work**

```powershell
cd 'D:\Hermes Jev CIDM'
git status --short
git fetch origin --prune
git switch --track origin/feature/local-continuity-split-context-plan
# If branch already exists: git switch feature/local-continuity-split-context-plan
git pull --ff-only origin feature/local-continuity-split-context-plan
```

If `git status` shows local changes, preserve/reconcile them **before** switching. Do not use `reset --hard` or `clean -fdx`.

**2 — Run every offline test (no paid calls)**

```powershell
py -3.11 -m compileall -q scripts tests
py -3.11 -m unittest discover -s tests -v
py -3.11 scripts/local_continuity_pipeline.py --goal 'Explain a fictional Python test failure' --project-scope demo --model 'YOUR_INSTALLED_OLLAMA_TAG'
```

The preview command makes **zero** model calls. A green Python suite **must be actually observed and logged**, not inferred from these docs.

**3 — Ollama and model identity**

```powershell
ollama --version
ollama list
ollama ps
nvidia-smi --query-gpu=memory.free --format=csv,noheader,nounits
```

Select a tested **Qwen 4B Instruct, four-bit** model tag installed in your Ollama runtime. Do not assume an unverified online tag exists. Record exact local model digest, memory/VRAM occupancy, served model and context window. Keep Ollama bound to local loopback, not LAN.

**4 — Safe first live-local pilot**

```powershell
py -3.11 scripts/local_qwen_run.py --live-local --model 'YOUR_INSTALLED_OLLAMA_TAG' --prompt 'Explain why a fictional JSON parse failed.'
py -3.11 scripts/local_continuity_pipeline.py --live-local --model 'YOUR_INSTALLED_OLLAMA_TAG' --project-scope demo --goal 'Explain a fictional Python test failure' --out 'runs/local-continuity-smoke-result.json'
py -3.11 scripts/local_continuity_evaluation.py --runs runs --out 'runs/local-continuity-evaluation.json'
```

**Note:** `--out` creates a file and refuses overwrite. Use a unique filename on subsequent runs. If no owner-admitted skill exists, the lanes may propose ungrounded answers; that is **not** a successful SOP-based test. Create and separately approve a synthetic demonstration SOP and complement in a disposable test registry before claiming skill retrieval worked.

**5 — Operator Console**

```powershell
py -3.11 scripts/operator_console.py
```

Open `http://127.0.0.1:8765` locally, select **Qwen local**, refresh installed model list, set a real project scope, preview the policy, then explicitly run **Local only** on a fictional test. Other worker modes are visible but not yet live-enabled in the Console. Never put credentials or confidential customer content into example prompts.

## Release acceptance table — do not silently skip

| Gate | Required evidence | Current state |
|---|---|---|
| S1 provider | Green offline tests + one local Ollama digest-confirmed run | **Not independently run** |
| S2 split context | Two admitted, relevant and distinct source hashes, no A leakage into B | **Mock fixtures only** |
| S3 outcomes | Independent correctness/validator receipts, false teacher and false agreement rejected | **Comparator observational; no task-specific checked acceptance** |
| S4 model switching | Typed real quota error, checkpoint-safe switch, no safety-bypass | **Policy only; not wired to broker** |
| S5 resource/scale | Actual GPU/RAM, 1K/10K/100K retrieval recall/latency; optional 2-way benchmark | **Not benchmarked** |
| S6 Jev/Hermes | Permits and actual Jev gate receipts, governed Hermes dispatch, integration acceptance | **Existing V1 blockers remain** |
| CI | Green GitHub Actions 3.10/3.11/3.12 | **Not green at last inspection** |
| Security | Secrets, SOP injection, cross-project access tests, log retention, restore | **Incomplete** |

## Known limitations / corrective work required

1. The operator-issued `frontier.run` permit in Local Only is legitimate for a **read-only proposal**, **not** a Jev checked accepted artifact. Complete Jev integration with authentic decision receipts before enabling stateful work.
2. The Local Only pipeline retains SOP contents in saved JSON result. Use restricted NTFS ACLs, a private local run directory, and retention/purge rules; never commit `runs/` or paste private results into public issues.
3. The model is identified by local `/api/tags` hash before inference; the Ollama response does not cryptographically bind the served weights to that hash.
4. Two Qwen lanes may share the same underlying model bias; context diversity cannot replace independent validators.
5. Teacher/student dual **simultaneous provider execution** and real **automatic usage-limit failover** are not yet integrated. Require trusted structured error signals, checkpoint receipts and fully audited Jev/local policy changes before turning them on.
6. The local knowledge registry still needs an approved policy for source revocation, skill/lesson lifetimes and provenance review.
7. The retrieval shortlisting optimisation trades semantic-only recall for bounded work; evaluate before applying to multilingual/high-recall corpora.
8. Neither docs nor unit test files establish that GitHub Actions actually executed, that a local Qwen model was installed, or that token savings have been demonstrated.

## Recommended immediate continuation

First repair existing GitHub Actions job start failures and run the offline test suite locally. Then run a **small non-sensitive Ollama smoke test** and validate that both lanes receive distinct admitted SOPs. Only after real error identity/usage, Jev checkpoint authority, quality validators and Hermes dispatch are working should the four-mode automatic fallback and teacher-student run be fully activated.

**No `main` merge or production acceptance is authorised by this experimental implementation.**

*CIDM architecture and design by Ken Caber (Kenneth Vic A. Caber); external model/software/skills retain their authorship.*
