# Handoff — Untrusted-tools hardening, slice 4 (14 October 2026)

**Branch:** `feature/untrusted-tools-hardening`. Final slice.
**Parent gate:** **P0-05 closes at the shape layer.**
**Evidence level:** offline tests only. No model calls.

## 1. What this slice delivers

The P0-05 pass-condition evidence and operator-facing documentation.

- `tests/test_untrusted_tools_adversarial.py`: fourteen adversarial tests composed across the three defensive modules shipped in slices 1-3. Four classes:
  - `NoEscalationFromReadTests` (2): untrusted MCP cannot fake `read`; honest `destructiveHint=true` on an untrusted server is still believed as `mutate` (safer direction).
  - `NoUnauthorisedExternalWriteTests` (6): destructive and external-effect actions without approval are refused; action-bound approvals cannot be replayed; pending/rejected approvals never pass; unknown actions are safe-by-default.
  - `NoBypassFromUntrustedContentTests` (5): strict mode refuses `mark_approved`, `disable_gate`, and role-switch patterns; lenient mode wraps and records; a hostile pre-close of the DATA wrapper is redacted.
  - `ComposedP005PassConditionTests` (1): a worst-case attack (untrusted MCP + destructive name + hostile retrieval text) is refused by every gate independently — the P0-05 pass condition.
- `docs/UNTRUSTED-TOOLS.md`: operator document — architecture, each gate's semantics, composed pass condition, five honest limitations (call-site integration pending, syntactic classifier, English-only patterns, no crypto on approvals yet, Fast Path admission still accepts `calibration=null`).

## 2. Code changes

| File | Change |
|---|---|
| `tests/test_untrusted_tools_adversarial.py` | New, 165 lines. 14 adversarial tests. |
| `docs/UNTRUSTED-TOOLS.md` | New operator doc, ~130 lines. |

## 3. Verification

| Check | Result |
|---|---|
| Slice-4 adversarial tests | 14/14 pass |
| Full offline suite | 466/466 pass, 1 opt-in Docker skip |
| Regressions on 452-test post-slice-3 baseline | 0 |
| `python -m compileall -q scripts tests` | pass |
| Live model calls | None |

## 4. P0-05 pass condition — closed

> **Pass condition** (production handoff §P0-05): *adversarial tests prove no escalation from read, no unauthorised external write, no bypass from an untrusted MCP annotation or changed skill file.*

Each clause is proven on data by a composed-gate test:

- **No escalation from read.** `test_malicious_mcp_cannot_fake_read_access` — untrusted server's `readOnlyHint=true` demoted to `unknown`.
- **No unauthorised external write.** `test_delete_without_approval_is_blocked`, `test_send_email_without_approval_is_blocked`, `test_approval_bound_to_different_action_cannot_be_replayed`.
- **No bypass from untrusted content.** `test_retrieval_asking_to_mark_approved_is_refused_strict`, `test_retrieval_asking_to_disable_gate_is_refused_strict`, `test_hostile_content_cannot_escape_the_wrapper`.
- **All three composed.** `test_full_attack_chain_is_refused`.

## 5. Carry-overs (documented in `UNTRUSTED-TOOLS.md` §5)

1. Call-site integration into `retrieval.py` / broker is a follow-up PR.
2. Classifier is syntactic; semantic rename escapes keyword list.
3. Injection patterns are English and keyword-based.
4. Approvals carry no crypto yet (Jev-associated immutable evidence is still future work).
5. Fast Path admission with `calibration=null` is not hardened in this PR.

## 6. Decision for this slice

- `scope`: closes P0-05 at the shape layer.
- `decision`: **PASS pending final branch-head QA**, then PR + merge.

*CIDM architecture and research by Ken Caber (Kenneth Vic A. Caber).*
