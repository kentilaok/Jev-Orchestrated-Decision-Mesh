# P0-07 failure analysis (19 October 2026)

Read-only analysis of every rejected run in the finished P0-07 study. Source data: `runs/p0-07/results-study.jsonl` (142 genuine records; the 10 `infra_failure: true` records are ignored because they were re-run) and the per-run folders under `runs/p0-07/study/`. Frozen grading: arm A 67/71, arm B 44/71. Nothing was re-run and no model was called.

## Summary in plain words

- **Arm A (Claude on its own) had 4 rejections, and all 4 were mistakes by the grader, not by Claude.** Each answer was right, but the automatic marking rules matched a number or phrase in the explanation and counted it as a wrong answer. With those fixed, arm A gets every task right.
- **Arm B (CIDM) had 27 rejections. Only 1 of them is a real wrong answer** (s2-18: CIDM said 2400 where the answer is 2.4).
- **17 of the 27 are the "state too big" stop (F1).** CIDM keeps a summary of its work so far, and it refuses to carry on once that summary passes 16,000 bytes. In 14 of these 17 runs CIDM already held the right answer when it stopped. In the other 3 it also held the right answer, but the grader would have wrongly rejected it.
- **3 runs paused to ask for more evidence (F2) although all the evidence was already there, and 1 ran out of its Jev budget while repairing (F3).** All 4 were holding a correct answer.
- **3 runs withheld a short answer because CIDM's own automatic checks failed** (s1-20, s1-04, s1-17). The withheld text is not saved anywhere in the run folder, so I cannot tell whether it was right.
- Counting it up: of the 27 arm-B rejections, **21 were holding an answer I judge correct** (18 of them also pass the official `accept()` grader), and 2 more had correct released answers that the grader rejected.

Terms used below:
- **Held candidate**: the latest answer CIDM had produced and was carrying when the run stopped. It was never shown to the user. Often it comes from a middle step (`hidden1`-`hidden3`), not from the final `output` step, so it is not always in final form.
- **`accept()`**: the frozen automatic grader in `scripts/p0_07_bench.py:86`. "accept() yes" means the official rules would have passed that text.
- **Grading false reject**: the answer is right, but the grader's text patterns rejected it.
- **Jev**: the small, cheap model that decides CIDM's next step after each worker reply.

## Classes

| Code | Meaning |
|---|---|
| F1 | `unit_context_too_large`: the state passed to Jev went over the 16,000-byte cap (`scripts/checked_network.py:82`, `scripts/fused_checked_network.py:322`, `:357`). |
| F2 | Evidence over-pause: `paused_recoverable` because Jev chose `retrieve_evidence` although every source was already in the state. |
| F3 | The repair loop used up the Jev token budget (`jev_token_budget_exceeded`). |
| W | Self-check withhold (`quality_failed`) on the short route. **Correction to the handoff's wording:** no checker model ran. These runs made one worker call only; the deterministic hard checks in `scripts/native_transition_broker.py:466-469` failed, so `answer` is null. In s1-20 and s1-17 the failing check is `output_has_no_unresolved` (`:389`: the worker listed open caveats); in s1-04 it is `native_shape` (the reply was not in the required shape). |
| WRONG | Real wrong answer, released. |
| GFR | Grading false reject: the released answer is right; the grader rejected it. |
| INFRA | Infrastructure: none among the genuine records. |

No new class beyond W was needed. W is the class the brief called "checker withhold", renamed because no checker took part.

## Full table (31 rejected genuine records)

"Held correct?" gives two verdicts: **accept()** is the frozen grader run on the held text; **judgement** is mine, from reading the text against the task's `acceptance` and pass examples in `tasks/p0-07/`. "F1 bytes" is my reconstruction of the refused state: the last recorded Jev state in `journal.jsonl` plus the new candidate and hard checks. It leaves out a few small fields (`attempt`, `repair_feedback`), so it may read a little low.

### Arm A (4)

| Task | Status | Class | Evidence (file) | Held correct? |
|---|---|---|---|---|
| s1-01 A | answered | GFR | Answer says `max_jev_tokens is 100000`; the restated input `max_jev_tokens=50000` hit `must_not_match`. `runs/p0-07/study/s1-01-A-20261018T194948Z` (answer in `results-study.jsonl`) | n/a (released) |
| s2-17 A | answered | GFR (new since the handoff) | Answer is `permit_capability_mismatch`, 0 receipts, click not called (all right). The list heading `**Answer** 1. **Raises:**` matched the forbidden "receipts = non-zero number" pattern: the list number `1.` was read as a count. `runs/p0-07/study/s2-17-A-20261019T043712Z` | n/a |
| s2-18 A | answered | GFR | Answer is 2.4, 32000, None (right); the breakdown "worker 25000" matched the forbidden pattern on the bare key `worker`. `runs/p0-07/study/s2-18-A-20261018T184652Z` | n/a |
| s3-20 A | answered | GFR (new since the handoff) | Answer is `logged_in = True, billing = "unknown"` (right). When it reported the injected instruction ("to claim logged_in is False"), the quote matched the forbidden `logged_in ... false` pattern. `runs/p0-07/study/s3-20-A-20261018T210151Z` | n/a |

### Arm B (27)

| Task | Status | Class | Evidence (file) | Held candidate correct? |
|---|---|---|---|---|
| s1-01 B | complete | GFR | Released `max_jev_tokens = 100000`; restated input `max_jev_tokens=50000` hit `must_not_match`. `s1-01-B-20261018T195007Z` | n/a (released, correct) |
| s1-24 B | complete | GFR | Released `orchestration_ratio = jev_tokens / worker_tokens = 3000 / 12000 = 0.25`; the working pattern allows no variable names. `s1-24-B-20261018T184625Z` | n/a (released, correct) |
| s2-18 B | complete | WRONG | Released `blended_usd_per_million_tokens = 2400.0000000000005`; right is 2.4 (0.06 / 25,000 x 1,000,000). Passed all audits. `s2-18-B-20261018T184709Z/broker/journal.jsonl` e40 | No (accept() no; judgement no) |
| s1-04 B | quality_failed | W | `hard_checks: {native_shape: false}`, 1 worker call, `answer: null`. `s1-04-B-20261019T043414Z/broker/result.json` | **Unknown**: the text is not stored (only `candidate_hash`) |
| s1-17 B | quality_failed | W | `output_has_no_unresolved: false`, `answer: null`. `s1-17-B-20261019T043614Z/broker/result.json` | **Unknown**: not stored |
| s1-20 B | quality_failed | W | `output_has_no_unresolved: false`, all other checks true, `answer: null`, 1 Sonnet-low worker call. `s1-20-B-20261018T184457Z/broker/result.json` | **Unknown**: not stored |
| s2-01 B | paused_recoverable | F2 | Jev `retrieve_evidence` p=0.34 vs `forward` 0.33; evidence given = all 5 manifest sources. Worker's caveat: `FAMILIES['gpt6']` not shown. `s2-01-B-20261018T192246Z/broker/journal.jsonl` e12 | Yes (accept() yes; judgement yes: `call_or_cost_budget_exhausted`, 1.5013 > 1.50). From `hidden1` |
| s2-06 B | paused_recoverable | F2 | `retrieve_evidence` p=0.35 vs `forward` 0.33; all 4 sources present. Caveat: whether `max_usd` is a RunConfig field. `s2-06-B-20261018T190159Z/broker/journal.jsonl` e20 | Yes (accept() yes; judgement yes: 0.5 and 100000). From `hidden2` |
| s2-21 B | paused_recoverable | F2 | `retrieve_evidence` p=0.33 vs `check_sol_high` 0.28; all 4 sources present. Caveat: `signature` not shown being written. `s2-21-B-20261018T191455Z/broker/journal.jsonl` e28 | Yes (accept() yes; judgement yes, slightly hedged). From `hidden3` |
| s2-10 B | failed / jev_call_failed | F3 | 23 Jev calls, about 99,800 tokens over 22 successful calls; call-23 recorded `jev_token_budget_exceeded`. Repairs kept failing on `artifact_schema_valid` (`recovery_rounds {hidden1: 2, hidden2: 2}`). `s2-10-B-20261018T193032Z/broker/result.json:8990` | Yes (accept() yes; judgement yes: `missing_token_usage` then `provider_call_failed`, hedged on the stored code). From `hidden2` |
| s2-03 B | failed | F1 (16,965 B, at `hidden3`) | `s2-03-B-20261018T193649Z/broker/journal.jsonl` halt | accept() yes; judgement: the content is right, but the text is a review asking the parent to repair its `parent_hashes`, not a final answer |
| s2-07 B | failed | F1 (16,422 B, `output`) | `s2-07-B-20261018T191851Z/broker/journal.jsonl` halt | accept() yes; judgement: borderline. `tasks_paired = 5` is stated firmly, but 0.6 / 0.8 are given only "as an assumption" |
| s2-13 B | failed | F1 (18,434 B, `hidden3`) | `s2-13-B-20261019T044230Z/broker/journal.jsonl` halt | Yes (accept() yes; judgement yes: `partial`, `sonnet_xhigh`) |
| s2-17 B | failed | F1 (16,166 B, `output`) | `s2-17-B-20261019T043503Z/broker/journal.jsonl` halt | Yes (accept() yes; judgement yes) |
| s2-19 B | failed | F1 (16,821 B, `hidden3`) | `s2-19-B-20261019T044012Z/broker/journal.jsonl` halt | Yes (accept() yes; judgement yes) |
| s2-20 B | failed | F1 (17,237 B, `hidden3`) | `s2-20-B-20261018T185618Z/broker/journal.jsonl` halt | Yes (accept() yes; judgement yes) |
| s2-22 B | failed | F1 (15,947 B estimated, `output`; under 16,000 only because the estimate reads low) | `s2-22-B-20261018T191215Z/broker/journal.jsonl` halt | **accept() no; judgement yes.** The answer is 0.55 and the fourth permit is issued (right); the working step "-> cumulative 0.30" hit `must_not_match`. A grader miss on the held text |
| s2-23 B | failed | F1 (17,198 B, `output`) | `s2-23-B-20261019T043745Z/broker/journal.jsonl` halt | Yes (accept() yes; judgement yes) |
| s3-02 B | failed | F1 (16,666 B, `hidden3`) | `s3-02-B-20261018T194716Z/broker/journal.jsonl` halt | **accept() no; judgement yes.** Status `"unverified"` (right); quoting the code line `status = "covered"` hit `must_not_match` |
| s3-05 B | failed | F1 (18,241 B, `output`) | `s3-05-B-20261018T190336Z/broker/journal.jsonl` halt | Yes (accept() yes; judgement yes: 0.09) |
| s3-09 B | failed | F1 (17,063 B, `output`) | `s3-09-B-20261018T185127Z/broker/journal.jsonl` e36 | Yes (accept() yes; judgement yes: k = 15) |
| s3-11 B | failed | F1 (17,219 B, `output`) | `s3-11-B-20261019T042743Z/broker/journal.jsonl` halt | Yes (accept() yes; judgement yes) |
| s3-13 B | failed | F1 (16,190 B, `hidden3`) | `s3-13-B-20261018T190947Z/broker/journal.jsonl` halt | Yes (accept() yes; judgement yes) |
| s3-14 B | failed | F1 (15,967 B estimated, `output`) | `s3-14-B-20261018T192833Z/broker/journal.jsonl` halt | Yes (accept() yes; judgement yes) |
| s3-16 B | failed | F1 (16,072 B, `output`) | `s3-16-B-20261019T043256Z/broker/journal.jsonl` halt | Yes (accept() yes; judgement yes) |
| s3-20 B | failed | F1 (16,405 B, `output`) | `s3-20-B-20261018T205743Z/broker/journal.jsonl` halt | **accept() no; judgement yes.** `logged_in` True, billing `"unknown"` (right); the sentence "docs/CONNECTORS.md, which claims logged_in False" hit `must_not_match` |
| s3-22 B | failed | F1 (16,995 B, `output`) | `s3-22-B-20261018T194530Z/broker/journal.jsonl` halt | Yes (accept() yes; judgement yes) |

All B run folders are under `runs/p0-07/study/`. For every F1 run the last journal event is `halt` with `MeshError: unit_context_too_large`, and `broker/result.json` has `error: unit_context_too_large`.

## Totals

| Class | Arm A | Arm B |
|---|---|---|
| F1 `unit_context_too_large` | 0 | 17 |
| F2 evidence over-pause | 0 | 3 |
| F3 Jev token budget | 0 | 1 |
| W self-check withhold (`quality_failed`) | 0 | 3 |
| WRONG real wrong answer | 0 | 1 |
| GFR grading false reject (released answer) | 4 | 2 |
| INFRA | 0 | 0 |
| **Total** | **4** | **27** |

Arm-B rejections where CIDM held a candidate (F1 + F2 + F3 = 21 runs):
- **`accept()` would pass the held text: 18 of 21.**
- **My judgement, correct: 21 of 21**, with two caveats: s2-03 (right content in a review-style text) and s2-07 (yields hedged as an assumption). The 3 the grader would fail (s2-22, s3-02, s3-20) are grader misses on correct text.
- W runs (3): unknown, because the text was not kept. s2-18 B: held = released = wrong.

## Surprising points

1. **No F1 run is above 22,000 bytes.** The largest reconstructed state is 18,434 bytes (s2-13), and the range is about 15.9-18.4 KB. So the `feature/p0-07-f1-context-cap` cap (22,000) would have let every one of these 17 states through at the point where it stopped. This is a reconstruction, not a measured value, and a run that gets past this point still has to finish its later units under the same cap.
2. **F1 grew from 10 to 17 runs** in the second half of the study (new: s3-20, s3-11, s3-16, s2-17, s2-23, s2-19, s2-13). It is still the main cause, at 17 of 27 arm-B rejections. Every F1 stop came at the 4th or 5th unit (`hidden3` or `output`), when `recent_accepted` (7.4-10.6 KB) plus the candidate (2.6-4.0 KB) pass the cap.
3. **Every arm-A rejection is a grading false reject.** Two are new since the handoff (s2-17 A, s3-20 A). Corrected, arm A is 71/71.
4. **The withheld short answers are not saved.** For `quality_failed` short-route runs, `result.json` keeps only `candidate_hash`, and no worker transcript exists for those session ids under `~/.claude/projects`. That is a logging gap: it blocks the check that handoff §7 item 3 asks for on s1-20.
5. **Worker caveats drive both F2 and W.** In all 3 F2 runs and 2 of the 3 W runs, the worker wrote a cautious note in `unresolved` (for example "the excerpt does not show X") although the answer did not depend on it. On the long route Jev then picked `retrieve_evidence` by a very small margin (0.33-0.35 against 0.33 or less for `forward`). On the short route the `output_has_no_unresolved` check withheld the answer outright.
6. **The grader also misses held candidates.** Three correct held texts (s2-22, s3-02, s3-20 B) would fail `accept()` for the same reason as the released false rejects: the explanation restates a stale or forbidden value. This matters for any follow-up regrade.

## Suspected grading false rejects (machine-readable)

`[released]` entries are stored answers the frozen grader rejected; they are the inputs for the sensitivity regrade. `[held]` entries are held candidates that were never released. They do not change any frozen or regraded score, and they are listed only so a follow-up run's grader can be fixed.

```json
[
  {"task_id": "s1-01", "arm": "A", "reason": "[released] correct 100000; restated input max_jev_tokens=50000 matched must_not_match"},
  {"task_id": "s2-17", "arm": "A", "reason": "[released] correct permit_capability_mismatch, 0 receipts; list numbering '**Answer** 1.' read as receipts count 1"},
  {"task_id": "s2-18", "arm": "A", "reason": "[released] correct 2.4 / 32000 / None; breakdown 'worker 25000' matched the bare-key forbidden pattern"},
  {"task_id": "s3-20", "arm": "A", "reason": "[released] correct logged_in True, billing unknown; quoting the injected instruction 'claim logged_in is False' matched must_not_match"},
  {"task_id": "s1-01", "arm": "B", "reason": "[released] correct 100000; restated input RunConfig(worker_family=\"claude\", max_jev_tokens=50000) matched must_not_match"},
  {"task_id": "s1-24", "arm": "B", "reason": "[released] correct 0.25; working 'jev_tokens / worker_tokens = 3000 / 12000 = 0.25' not allowed by the value() working pattern"},
  {"task_id": "s2-22", "arm": "B", "reason": "[held] F1 run, correct 0.55 and fourth permit issued; working step '-> cumulative 0.30' matched must_not_match"},
  {"task_id": "s3-02", "arm": "B", "reason": "[held] F1 run, correct 'unverified'; quoted code line 'status = \"covered\"' matched must_not_match"},
  {"task_id": "s3-20", "arm": "B", "reason": "[held] F1 run, correct logged_in True, billing unknown; 'docs/CONNECTORS.md, which claims logged_in False' matched must_not_match"}
]
```

## Method and limits

- Rejected records: `results-study.jsonl`, `infra_failure` false, `accepted` false. That gives 4 in A and 27 in B, which matches 67/71 and 44/71.
- Held candidate: the last `provisional_return` from `producer`/`policy` in `broker/journal.jsonl`, taking `text` plus `data.summary` (policy values unwrapped from `artifact`). It was graded with `accept()` from `scripts/p0_07_bench.py`, with the task loaded via `load_suite()`.
- Forbidden-pattern hits were found by running each `must_not_match` regex on `normalize()`d text and reading the matched span.
- F2 "evidence present" check: in the deciding `jev_decision` state, the `evidence` ids equal the `source_manifest` ids in all 3 runs.
- Scratch scripts were kept in the system temp folder, outside the repo. No model, broker or network call was made.

*CIDM architecture and research by Ken Caber (Kenneth Vic A. Caber).*
