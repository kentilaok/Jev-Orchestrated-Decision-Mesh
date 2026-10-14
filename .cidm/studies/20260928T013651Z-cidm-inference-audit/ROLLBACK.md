# Rollback and isolation

Nothing in this study modified the active skill, the repository's tracked files, or any project system.

| Asset | State after this study | How to verify or restore |
|---|---|---|
| Installed skill (`<SKILL_ROOT>`) | Untouched. This container cannot reach it; the uploaded copy was compared read-only | Compare with `provenance/repo-file-sha256.txt` (all 370 tracked files equal HEAD `327c36b`) |
| Repository tracked files | Untouched. The study lives only under `.cidm/studies/20260928T013651Z-cidm-inference-audit/` | `git status` shows only the study directory. To discard it: `git rm -r --cached .cidm/studies/20260928T013651Z-cidm-inference-audit` (or revert the study commit) |
| Candidate skill | Separate copy in `candidate-skill/`; never installed | Delete the directory; nothing else references it |
| Project evidence (`.cidm`) | Read-only; analysed from a private scratch copy; not committed | n/a |

## Installing the candidate for a live A/B test (only after separate authorisation)

1. Install the candidate under a **different** skill name and path, for example `<codex skills dir>\caber-interstitial-decision-mesh-candidate`, so the active skill is not replaced.
2. Or run the benchmark harness, which imports the candidate's `scripts/` only in its own attempt processes (arms D0, E2–E5).
3. **Roll back:** delete the candidate directory. The active skill never changed.

## Promotion (if the evidence later supports it)

1. Apply `patches/candidate-all.patch` on a feature branch: `git apply patches/candidate-all.patch`.
2. Run `python -m unittest discover -s tests -v` (expect 142 tests).
3. Open a pull request for owner review.

**Revert:** `git revert <merge-commit>` or `git apply -R patches/candidate-all.patch`. Receipts written with the new fields remain readable by the old code, because the new fields are only added.
