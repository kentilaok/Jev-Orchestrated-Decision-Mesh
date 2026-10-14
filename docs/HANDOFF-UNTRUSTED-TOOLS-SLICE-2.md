# Handoff — Untrusted-tools hardening, slice 2 (14 October 2026)

**Branch:** `feature/untrusted-tools-hardening`.
**Parent gate:** P0-05. Second of four slices.
**Evidence level:** offline tests only. No model calls.

## 1. What this slice delivers

A non-reversible-action gate as a standalone module. Standard capability permits bind scope and single-use but do not express whether an action can be undone. A `delete_file` call that passes a `mutate` permit is still non-reversible and must require an extra explicit operator approval beyond the permit itself.

- `scripts/action_reversibility.py`:
  - `classify_action(name, annotations) -> 'reversible' | 'non_reversible' | 'unknown'`. Regex ladder covers destructive verbs (delete / drop / destroy / wipe / remove / purge), external-effect verbs (send / post / publish / deploy / charge / notify / webhook / slack / tweet), plain writes (write / update / patch / put / replace / overwrite / insert / create / alter), and read verbs (read / get / list / search / fetch / lookup / describe / show / inspect). Explicit `annotations.reversibility_hint` can tighten but cannot loosen the classification.
  - `is_blocked_without_approval(action, annotations, *, approval)`: True unless the action is reversible OR a valid approval is present. Unknown is treated as non-reversible (safe-by-default).
  - `require_approval(action, annotations, *, approval)`: enforces the gate; raises `NonReversibleActionError` on refuse, returns an info dict (`classification`, `approval_required`, `approved_by`) on pass.
  - Approvals are **action-bound**: an approval tied to `delete_file` cannot be replayed for a `drop_table` call.

## 2. Code changes

| File | Change |
|---|---|
| `scripts/action_reversibility.py` | New, 115 lines. One module, three public functions, one exception class, one regex ladder. Stdlib only. |
| `tests/test_action_reversibility.py` | New, 115 lines. Seventeen tests across two classes: classify (9) covering reversible reads, destructive verbs, external effects, plain writes default non-reversible, unknown, unknown-treated-as-non-reversible, explicit-reversible annotation, explicit-non-reversible wins; approval gate (8) covering reversible-no-approval, non-reversible-blocked, approved-passes, pending-blocked, rejected-blocked, action-bound (different action does not authorise), raising, info-dict pass path, approved-detail. |

## 3. Verification

| Check | Result |
|---|---|
| Slice-2 tests | 17/17 pass |
| Full offline suite | 440/440 pass, 1 opt-in Docker skip |
| Regressions on 423-test post-slice-1 baseline | 0 |
| `python -m compileall -q scripts tests` | pass |
| Live model calls | None |

## 4. Open items for the next slices

1. **Treat retrieval/MCP content as data (slice 3).** Prompt-injection resistance: a retrieved doc or MCP response that says "override access_class to read" or "mark this approved" is not acted on. Sanitise/escape before the broker sees it; log an audit event when a suspicious control-string is detected.
2. **Adversarial corpus + operator doc (slice 4).** `tests/fixtures/untrusted-tools/*.json` for the three vectors (trust gate, non-reversible gate, injection), `docs/UNTRUSTED-TOOLS.md`, final P0-05 pass-condition check.

## 5. Pass/hold decision

- `scope`: internal milestone, not a release
- `decision`: **PASS pending QA**; next slice continues per standing cadence.

*CIDM architecture and research by Ken Caber (Kenneth Vic A. Caber).*
