# Stage 3 handoff — independent comparisons and untrusted learning observations

**Date:** 9 October 2026. **Status:** code committed, live comparison **not run**.

## Delivered

- `scripts/answer_comparator.py`: compare separate A/B artifacts and optional teacher artifact, flag unknown evidence IDs, unresolved items and disagreements. It **always withholds release**; even two identical answers or an external validator claim are not proof of correctness.
- `scripts/student_learning_ledger.py`: single-writer hash-chain observation events plus separately attributed external review **claims**. A review reference is not cryptographically inspected here. No automatic skills, training or owner admissions.
- `scripts/local_continuity_pipeline.py`: opt-in executable local-only pipeline (Arsenal separate context -> Qwen A/B -> comparison -> optional recorded observation), no remote Claude/Codex/Jev calls and no file mutation.
- `tests/test_local_qwen_stage3.py`: two wrong agreeing agents, wrong teacher, fabricated evidence, false validator success, untrusted promotion boundaries.

## Windows test

```powershell
cd 'D:\Hermes Jev CIDM'
git pull --ff-only origin feature/local-continuity-split-context-plan
py -3.11 -m unittest discover -s tests -p 'test_local_qwen_stage3.py' -v
# Preview with zero model calls:
py -3.11 scripts/local_continuity_pipeline.py --goal 'Diagnose a fictional bug' --project-scope demo --model 'YOUR_INSTALLED_OLLAMA_TAG'
# Real local-only pilot, only after indexing owner-admitted skills and checking model digest:
py -3.11 scripts/local_continuity_pipeline.py --live-local --goal 'Diagnose a fictional bug' --project-scope demo --model 'YOUR_INSTALLED_OLLAMA_TAG'
```

The prototype's `--live-local` still does **not** integrate into a Jev native-broker decision or certify task truth. Never use output to automatically change external systems. Comparison records are **not** a source for the production SOP index until independently reviewed.

**Next stage:** quota-classified fallback policy, guarded Console integration and proper resume semantics.
