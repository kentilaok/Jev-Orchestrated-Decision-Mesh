# P0-07 follow-up fixes: F2, F3 and the withheld-answer log (19 October 2026)

Branch `feature/p0-07-followup-fixes` (the finished study branch plus the F1 cap fix). Ken approved the F2 and F3 proposals in `docs/HANDOFF-2026-10-19-P0-07-STUDY-IN-PROGRESS.md` §5 and the logging fix. Nothing here was run against a model. All checks are offline.

## Summary in plain words

1. **F2, pausing for evidence that was already there.** CIDM used to give Jev a "pause and ask for more evidence" button after every worker answer, even when nothing was missing. In 3 study runs Jev pressed it by a hair's margin and the run stopped. Now the button appears only when something can actually say what is missing: the separate checker names it, or a lookup tool is connected that can go and fetch it. When an answer passes every automatic check, Jev's choices are to accept it, send it to the checker, or redo it.
2. **F3, repairs that ate the whole Jev budget.** In s2-10 CIDM kept redoing two steps until Jev's token budget ran out on the 23rd call. Now, before CIDM redoes a step, it checks that the Jev budget left can still pay for the redo and for every step still to come. If it can't, the run stops at once with the reason `jev_budget_too_low_for_retry`, instead of making one more paid call that goes over the budget.
3. **Withheld short answers are now kept.** When CIDM's checks held back a one-step answer, the run folder kept only a fingerprint (hash) of it, so nobody could check later whether it was right. Now the full candidate is saved in its own file, `withheld_candidate.json`, marked "NOT RELEASED". It is never used as the answer. The fingerprint is still there.

Tests: 768 pass, 5 skipped (756 before, plus 12 new). The frozen suite check still reports `87adc401b8297432c969aa01e3ffebf0427994a647803b3abd74ea116c55b2b6` with no problems.

## F2: evidence over-pause

**Problem.** After each worker answer, Jev is offered `retrieve_evidence`. In a study run (recovery policy, no lookup tool connected) that choice cannot fetch anything, so it ends the run as `paused_recoverable` and waits for an operator.

**Evidence.**
- `runs/p0-07/study/s2-06-B-20261018T190159Z/broker/journal.jsonl`, event `e20` (unit `hidden2`): every hard check passed. Jev's probabilities were `retrieve_evidence` 0.35, `forward` 0.33 and `check_sol_high` 0.22. The worker's caveat: it could not confirm from the excerpt whether `max_usd` is a RunConfig field.
- `s2-21-B-20261018T191455Z/broker/journal.jsonl`, `e28` (`hidden3`): all checks passed. Caveat: the excerpt does not show `signature` being written.
- `s2-01-B-20261018T192246Z/broker/journal.jsonl`, `e12` (`hidden1`): all checks passed. Caveat: `FAMILIES['gpt6']` not shown.
- Scan of every arm-B journal in `runs/p0-07/study/`: `retrieve_evidence` was offered 223 times after a fully passing answer and 19 times after a failed one. Jev chose it exactly 3 times, these 3, all after a fully passing answer and before any checker ran. No study run used a lookup tool, so every choice became a pause. Where it is offered: `CheckedNetwork.run_unit` in `scripts/checked_network.py` (the recovery policy wraps this controller via `recovery_protocol.build_recovery_network`).

**Change.**
- `scripts/checked_network.py`, `CheckedNetwork.run_unit`:
  - After a worker answer: if every hard check passes, `retrieve_evidence` is removed from the options unless a lookup tool is connected. Forward, `check_sol_high`, repair, escalate and stop are unchanged. If a hard check fails, the options are exactly as before.
  - After a checker answer: `retrieve_evidence` is offered only when the checker's valid report lists `missing_evidence`, or a lookup tool is connected.
  - New attribute `evidence_retrieval_available` (default `False`).
- `scripts/recovery_protocol.py`, `RecoverySupervisor.__init__`: sets `network.evidence_retrieval_available` when an evidence retriever (MCP plan or local index) is given. With one, `retrieve_evidence` is a bounded read-only lookup followed by a fresh Jev gate, not a pause, so it stays on offer.
- Unchanged: option ids, Jev's instructions, the fused controller (`fused_checked_network.py`), the first-gate options, and the rule that a failed answer can never be forwarded. The policy hash does not change, because the new flag is not part of the policy.

**Tests** (`tests/test_p0_07_followup_fixes.py`, `EvidenceOfferTests`). Jev is a fake that always presses `retrieve_evidence` when it is offered.
- A passing answer is never offered `retrieve_evidence`, and the run completes.
- The s2-01 pattern (a passing answer with a caveat) gets forward and the checker, but not `retrieve_evidence`.
- Old safety: a failing answer still gets `retrieve_evidence`, never gets forward, and the run pauses.
- A checker that names missing evidence brings `retrieve_evidence` back, and the run pauses with `recovery_kind: retrieve_evidence`.
- A passing checker report does not offer it.
- With a lookup tool connected, it is still offered on a passing answer, and the lookup adds the new source.

`tests/test_recovery_resume.py` was updated. Its fixture paused by having Jev press `retrieve_evidence` on a passing answer, which is exactly the F2 behaviour. The pause now comes from the new path: Jev asks for the checker, the checker names the missing runbook, then Jev chooses `retrieve_evidence`. All 7 resume tests (tamper, state hash, operator and budget reset) pass unchanged in what they assert.

**Risks and open questions.**
- **Ken to confirm:** keeping `retrieve_evidence` whenever a lookup tool is connected is my reading of "the controller can name it". Without this, the MCP and local-index retrieval features would stop working on passing answers.
- After a *failed* hard check, `retrieve_evidence` is still offered. No hard check names a missing source, but removing it there would also change which gates hide `stop` under the recovery policy. Study data: never chosen there (0 of 19).
- After a failed checker report that names no missing evidence, a gate can now have only `repair` and `stop`. The recovery policy then leaves `stop` visible, where before it was hidden. This never happened in the study, because no checker ran.
- The fused controller still offers `retrieve_evidence` everywhere. The study did not use it. Apply the same rule there only if Ken wants it.
- The worker caveats behind F2 have not gone away. Jev may now forward such answers, or send them to the checker. On the output unit, a caveat still blocks release through the `output_has_no_unresolved` check.

## F3: repair loop hits the Jev token budget

**Problem.** s2-10 failed with `jev_call_failed` after 23 Jev calls (about 99,800 tokens against the 100,000 Claude-family default). The gateway only rejects a call after it has been made and billed (`scripts/transport.py`, `jev_token_budget_exceeded`). So the last call was paid for and then thrown away.

**Why the repairs did not converge** (`runs/p0-07/study/s2-10-B-20261018T193032Z/broker/journal.jsonl`):
1. Jev picked `sonnet_low` for every attempt and never escalated.
2. About half the candidates broke the artifact contract: text over 1,200 characters (`artifact_text_limit`, at `e12`, `e23` and `e58`), and once a wrong parent hash (`e42`).
3. The candidates that passed every check (`e17`, `e28`, `e47`, `e53` and `e64`) carried the same caveat each time: `_error_code`'s mapping "is not shown", so the exact error string "cannot be confirmed". Jev chose `repair` on these. The feedback then sent to the worker named no failed check (`failed_criteria: []`), so the worker had nothing concrete to fix and repeated the caveat. This is the F2 pattern again, showing up as repairs instead of a pause.
4. The recovery policy then allowed 2 attempts × 3 rounds per unit. hidden1 took 4 attempts before forwarding at `e34`. hidden2 used all 6 and was still repairing when the budget ran out (`e66` halt).

**Change.** `scripts/native_transition_broker.py`, `NativeTransitionBroker._judge`. Before the Jev call that would start a **retry** of a unit (phase `authorize_unit` with `repair_feedback` set, which covers repair, escalate, replan and re-run after new evidence), the broker requires:
- Jev calls remaining ≥ 2 × (this unit + units after it), and
- Jev tokens remaining ≥ that number of calls × the largest Jev call so far.

If not, it raises `jev_budget_too_low_for_retry` before any call is made. The recovery policy reports `status: failed` with `error: jev_budget_too_low_for_retry`. The first try of each unit is never held back. Jev still makes every decision; this only refuses to start a retry the budget cannot finish.

**Check on the stored runs** (an offline replay of the rule over every arm-B journal):
- s2-10 would stop at `e50`, the first hidden2 replan. At that point 67,211 tokens were spent, and 6 more calls at up to 5,842 tokens each were needed against 32,789 left. That saves 7 Jev calls and 3 worker calls, and replaces `jev_call_failed` with a clear reason.
- Every completed study run had no retries, so the rule would not have stopped any of them.
- The only other run where it would have fired is the infrastructure record `s3-20-B-20261018T195522Z` (Claude usage limit, re-run later).

**Tests** (`RetryBudgetTests`):
- With 11,000 tokens and 1,000-token calls, a retry at hidden1 stops with `jev_budget_too_low_for_retry` after 4 Jev calls. No call fails and no extra worker call runs.
- With the normal budget, the same repair goes ahead and the run completes with clean audits.
- With a tight budget and no retry, the first try of each unit runs and completes.

**Risks and open questions.**
- The size estimate uses the largest call so far. Jev states grow as units are accepted, so later calls can be bigger. The rule can still be slightly optimistic, and the gateway's hard limit stays as the backstop.
- It does not fix why repairs fail to converge. Possible later fixes for Ken to choose from: do not offer `repair` on a passing answer when the feedback would name no defect, or have Jev escalate after a contract failure repeats. Neither is in this change.
- Only the native broker has this check. `network_run.py` and `adaptive_run.py` use their own gateway limits.

## Logging gap: withheld short-route answers

**Problem.** For `quality_failed` short-route runs (s1-20, s1-04, s1-17), `broker/result.json` and the `short_result` journal event keep only `candidate_hash`. The worker's text is not stored anywhere (`runs/p0-07/study/s1-20-B-20261018T184457Z/broker/result.json`, `s1-04-B-20261019T043414Z`, `s1-17-B-20261019T043614Z`).

**Why only a hash was stored.** I found no deliberate safety reason. The short route was added in commit `44d9945` (23 September, "Add controlled Codex CLI transition broker"), and neither the commit message nor the docs explain the choice. The long five-unit route already saves every worker candidate in full in `journal.jsonl` (`provisional_return` events), including ones that were never released. So keeping withheld text in the run folder is not a new kind of exposure. What the code does protect is that a withheld candidate never becomes `answer`. That protection is kept.

**Change.** `scripts/native_transition_broker.py`:
- New `NativeTransitionBroker._keep_withheld`. When a short-route run ends without release (`quality_failed`, or `audit_failed` on the call check), the broker writes `withheld_candidate.json` in the broker folder. It holds `released: false`, a `notice` beginning "NOT RELEASED", the status, the hard checks, `candidate_hash` and the full candidate.
- `result.json` gets one new key, `withheld_candidate: {file, candidate_hash, released: false}`. It holds no text.
- `answer`, the printed summary line and the `short_result` journal event are unchanged. The stored candidate's fingerprint equals `candidate_hash`, so the file can be checked against the original record.

**Tests** (`WithheldCandidateLogTests`):
- The s1-20 pattern (a caveat causes `output_has_no_unresolved: false`): the file exists, is labelled, and its hash matches. The text appears nowhere in `result.json`, and the journal event is byte-for-byte the old format.
- The s1-04 pattern (`native_shape: false`): the candidate is stored.
- A released answer writes no file and adds no key.

**Risks and open questions.**
- `runs/` is tracked in a public repo. Withheld text will be published with the run folders, as long-route candidates already are. A worker can echo source text or injected instructions. Nothing reads this file back into a model or the grader. Rescan before pushing, as for any run output.
- Older run folders are unchanged. Their withheld text cannot be recovered.
- Long-route held candidates were already in the journal, so this fix covers only the short route.

## Files changed

| File | Change |
|---|---|
| `scripts/checked_network.py` | F2 option rule and the `evidence_retrieval_available` flag |
| `scripts/recovery_protocol.py` | F2: the supervisor sets the flag when a retriever is given |
| `scripts/native_transition_broker.py` | F3 retry budget check in `_judge`; `_keep_withheld` for the short route |
| `tests/test_p0_07_followup_fixes.py` | New, 12 tests |
| `tests/test_recovery_resume.py` | Fixture now pauses through a checker that names the missing runbook |

Not touched: the suite, the grading, the protocol, `scripts/p0_07_bench.py`, anything under `runs/`, and other docs. `SKILL.md` and `docs/ARCHITECTURE.md` still describe `retrieve_evidence` as one of the "eligible" options. That stays true, but a one-line note about the new eligibility rule could be added once Ken accepts it.

*CIDM architecture and research by Ken Caber (Kenneth Vic A. Caber).*
