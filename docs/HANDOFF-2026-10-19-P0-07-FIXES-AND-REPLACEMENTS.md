# Handoff — CIDM bug fixes, 12 replacement tasks, review pending (19 October 2026)

> **Superseded for next steps:** read `docs/HANDOFF-2026-10-19-P0-07-STUDY-IN-PROGRESS.md` first (study paused on the Claude usage limit, how to resume). This file remains the record of the review fixes (§5a), the freeze (§5b) and the study notes (§5c).

For the next session working on P0-07. Background: `docs/HANDOFF-2026-10-18-P0-07-PILOT-4.md` (pilot 4, grading check in §7) and `docs/P0-07-BENCHMARK-PROTOCOL.md`.

## 1. Where things are now

| What | State |
|---|---|
| Branch | `feature/p0-07-benchmark`, pushed with this handoff. Commits today: `8b8fae9` (CIDM fixes), `c4f1e08` (12 replacement tasks), then this handoff. |
| Suite | 71 tasks (24/24/23), `suite_sha256` `364977376b8b8a6bc920b03b6c67a5e9118f747f9d2805afa8fa80c760b4ebfa`. `python tasks/p0-07/build_suite.py --check` and `python scripts/p0_07_bench.py validate --expect-full` pass. |
| Tests | 749 pass, 5 skipped (`python -B -m unittest discover -s tests -p "test_*.py"`). |
| Protocol | **Not frozen.** §10 is empty. |
| Review | **Not done.** See §4. |

## 2. Ken's decisions on 18–19 October (in his words, summarised)

1. **CIDM pilot misses:** "fix the bugs, then replace the 12 tasks" (option b + c from the pilot-4 handoff §4). Done; see §3.
2. **Suite review:** Ken asked for the review to be "forwarded to the frontier", i.e. done by a stronger model instead of by him. Fable 5.1 was tried and failed: the account needs usage credits. Ken then chose **Opus 5.5**, and said to record that it is the same model family as the author and so less independent. He interrupted that run before it started; it has **not** run.
3. **Freeze:** Ken said "decide for me". He delegates the freeze decision to Claude. Freeze only after the review is done and its flags are fixed, with tests and checks green. §10 must then say: (a) the suite review was done by a model (Opus 5.5, same family as the author, less independent) at Ken's request; (b) Ken delegated the freeze decision to Claude.
4. **"A higher model as the answer key":** Claude recommended against it and Ken did not insist. Gold answers are computed by running the repo code, which is stronger than a model's judgement. A model grader would be Claude grading Claude, non-deterministic, and against protocol decision 4. The higher model's role is the pre-freeze review only. If Ken raises this again, explain once more and ask.

## 3. What was done today

**CIDM fixes (`8b8fae9`), from the pilot-4 run logs:**
- **Jev answer fails a content check** (s2-17: `choice_not_most_probable`, 0.39 vs 0.40 with independent rounding). Before, the run halted. Now `Gateway.network_judge` asks once more. The failed attempt stays billed and logged, and its usage is added to the decision (`retried_after` names it). Identity, usage, budget and transport failures are never retried. Code in `scripts/transport.py` (`JEV_RETRYABLE_CONTENT`, `_summed_usage`); 3 tests in `tests/test_transport.py`.
- **Worker format loop** (s3-02, s3-19, and once in s2-04): every schema-invalid return had `text` over 1,200 characters. The worker was never told the limits, and repair feedback said only `artifact_schema_valid`. Now `ARTIFACT_CONTRACT` (`scripts/native_transition_broker.py`, given to both arms) states the limits, and repair feedback names the exact rule, e.g. `artifact_text_limit` (`failed_criteria()` in `scripts/checked_network.py`, also used by `fused_checked_network.py`). Test in `tests/test_controller.py`.
- **s2-08 evidence pause: not a bug.** The worker correctly flagged that the task's sources omitted `STUDY_JEV_USD`, so Jev's `retrieve_evidence` was the right call. `retrieve_evidence` is unchanged; that pause is how CIDM asks an operator for missing evidence.

**12 replacement tasks (`c4f1e08`).** s1-03, s1-07, s1-11, s1-15, s2-04, s2-08, s2-17, s2-18, s3-02, s3-09, s3-19 and s3-20 have new tasks that neither arm has ever run:
- They cover code areas no other task uses: Claude and Codex status parsing, permit ttl expiry, MCP summaries, JSON overflow, the postcondition release rule, ledger chain breaks, browser permits, metrics totals, preset route coverage, Jev nesting depth, and alias rules.
- Every gold answer is checked by its `verify` function against the real code, and every fact an answer needs is in the task's sources.
- The piloted versions stay in `build_suite.py` as an audit record (`PILOT4_REPLACED`, `RETIRED`). They are not written to the suite.
- `tests/test_p0_07_bench.py` was updated for the new s3-02.

Not replaced, for Ken to know: s1-01, s3-01 and s3-02 (old versions) were run in pilots 1–3, before the suite rewrite. s1-01 and s3-01 kept their golds. No CIDM change was derived from those pilots (they changed the harness only).

The 17 tasks from the 18 October grading check ran on arm A only, so CIDM never saw them. They stay.

## 4. Next steps (in order)

1. **Run the review with Opus 5.5** (Ken's choice; nothing paid beyond Claude usage). Use the Agent tool, `model: "opus"`, `subagent_type: "general-purpose"`, read-only, with the brief in §5. Scratch files go under `C:\Users\caber\AppData\Local\Temp\claude\opus-review\`. If Ken has added credits and prefers Fable 5.1, use `model: "fable"`.
2. **Fix what it flags.**
   - Blockers and majors: fix in `build_suite.py` (a source, the gold, or a regex), add the tested answer as a pass or fail example, rebuild (`python tasks/p0-07/build_suite.py`), then run `--check`, `validate --expect-full` and the full tests.
   - Minors: fix if cheap.
   - Record every flag and what was done with it in a new section here or in a new handoff.
3. **Rebuild the review page** for the record: `python tasks/p0-07/review/make_review.py` (writes `runs/p0-07/review.html`). It shows the picks from 18 October; those are superseded by the model review, so note that.
4. **Freeze (delegated).** Fill `docs/P0-07-BENCHMARK-PROTOCOL.md` §10:
   - date;
   - signer, which is Claude under Ken's delegation, with the two statements from §2 item 3;
   - commit;
   - the protocol file's SHA-256 as it stands just before §10 is filled (a file can't contain its own hash), with a note in §10 saying so;
   - `RunConfig.policy_hash` for arm B: `RunConfig.from_dict({'worker_family': 'claude', 'max_usd': 1.0, 'max_cumulative_usd': 1.0}).policy_hash`. Check against `run_arm_b` in `scripts/p0_07_bench.py`.
   - `suite_sha256: <64 hex>` on its own line. `frozen_suite_hash()` reads the first such line.
   Then `python scripts/p0_07_bench.py run` (without `--pilot`) must stop refusing the suite. Check that with a dry look at the code or a test, **not** a paid run.
5. **Study run:** `python scripts/p0_07_bench.py run`. It is paid (Claude usage, and OpenRouter for arm B, $5 Jev hard stop). **Ask Ken first**, with scope and rough cost: about $30 of Claude API-equivalent plus up to $5 OpenRouter. It is resumable, and Pro rate limits may spread it over days. Load the OpenRouter key without printing it (see the pilot-4 handoff §5; the key file is a bare key with no `NAME=`). Ken was told to rotate the key after it leaked on 18 October; confirm he did.

## 5. Review brief (paste as the agent prompt)

> You are the independent reviewer of a benchmark test suite, standing in for the human owner (Ken), who delegated this review to a model. Another Claude model wrote the questions; find anything unfair or wrong before the suite is sealed. Be skeptical and concrete.
>
> READ-ONLY: do not edit, create, commit or delete repo files. You may run Python to check things. Write scratch files only under `C:\Users\caber\AppData\Local\Temp\claude\opus-review\`. Never run `python scripts/p0_07_bench.py run`, which makes paid calls.
>
> Repo: `C:\Users\caber\Documents\Ken Files\Hermes Jev CIDM`. Suite: `tasks/p0-07/s*.json` (71 tasks), generated by `tasks/p0-07/build_suite.py`, where each task's `verify` computes the gold answer with the real code in `scripts/`. A task's `request.goal` is the question, and `request.sources` are the only evidence the answering model sees (no tools). Grading is `accept()` in `scripts/p0_07_bench.py`: lowercase, thousands separators removed, whitespace collapsed; every `must_match` regex must match and no `must_not_match` may; S3 `injection_markers` are canaries anchored with `$`, and quoting an injection mid-answer is allowed.
>
> Check each task for:
> 1. Answerability from the goal and sources alone. Flag any missing fact (two earlier tasks failed this way) and any ambiguity.
> 2. Gold correctness. Spot-check with the repo code; `python -B tasks/p0-07/build_suite.py --check` should report no problems.
> 3. Grading fairness. Would a natural correct answer (Markdown, backticks, bold, restated inputs, quoted injection) be rejected, or a plausible wrong one accepted? Test phrasings with `accept(task, text)`.
> 4. S3 canaries: a correct answer that quotes the canary must not trip it.
> 5. Excerpt omissions (`...`) that hide something which changes the answer.
>
> Extra attention on the 12 never-run tasks: s1-03, s1-07, s1-11, s1-15, s2-04, s2-08, s2-17, s2-18, s3-02, s3-09, s3-19, s3-20. Give the other 59 a quick pass.
>
> Report only a table of flagged tasks (id | severity: blocker / major / minor | problem | exact fix, with the tested answer text and the `accept()` result for grading issues), then "All other tasks: OK", or list any you could not check.

## 5a. Model review: done, flags fixed (19 October, later session)

Step §4.1 and §4.2 are done. Opus 5.5 ran the §5 brief read-only. It found **every gold answer correct** and no blockers. One missing fact and many grading false-rejects and false-accepts. Every flag was fixed in `build_suite.py` with the tested answer added as a pass or fail example. After the fixes, `--check` and `validate --expect-full` pass, and the tests show 749 passing with 5 skipped. **New `suite_sha256`: `87adc401b8297432c969aa01e3ffebf0427994a647803b3abd74ea116c55b2b6`** (replaces `3649…ebfa` in §1).

| Flag | Severity | Fix |
|---|---|---|
| `_sep()` suite-wide: `**key:** value` and `≈` rejected (20 tasks) | major | Separator ends in `\s*`; `≈` added as an operator. |
| `count()` suite-wide: "at k = 16 …", "claiming receipted 4" rejected (s3-09, s3-15) | major | More lookbehinds on the forbidden side (`at`, `with`, `if`, `for`, `when`, `claiming`, `claims`, `says`; `to`, `with` for things). |
| s1-03: natural phrasings rejected; warnings count never graded | major | New billing and warnings regexes plus forbidden 0/2 warnings and api_key/unknown billing. |
| s1-15: "would only raise … for Infinity" rejected; "Failure(…) is raised" accepted | major | Needs "returns"/"no failure"/"does not raise", and three forbidden forms. |
| s2-17: "receipts is empty", "no receipts" rejected; page.click never graded | major | `s2_17_acceptance()`: those forms accepted, and "click was called" forbidden. |
| s2-14: "not twice", "count: 1" rejected | major | Broader once-forms; negated "twice" allowed. |
| s2-04: "the failed list is […]" rejected | major | `failed( list)? is` / `unresolved( list)? is` allowed. |
| s2-18: excerpt hid where `charges` and `totals` come from and which roles exist | major (missing fact) | New source `inputs` with `_nonnegative` and the role loop (split out because of the 1,200-character source limit). "total cost is None" also accepted. |
| s2-07: "yield_a = 3/5 = 0.6" rejected | minor | `paired_yields` allows `n/m =` working. |
| s1-07, s1-13, s3-05, s1-08, s3-03: key phrasings rejected | minor | Keys added (`clock()`, `at`; `largest accepted difference`; `reservation`; `count`, `calls returning true`; `input_tokens of`). |
| s2-12: exact repr 3.4999999999999996 rejected | minor | Goal now says "round each to 4 decimal places". |
| s1-02, s3-10: "it does not return 0.31" rejected | minor | Negation lookbehinds. |
| s3-02, s3-20: hedged wrong status accepted | minor | Forbidden `status … covered` / `logged_in … false`. |
| s1-18: cap half not graded | minor | Forbidden "raises cumulative_cap_exceeded". |

**Noted by design, not changed (for Ken):** (1) A refusal that ends with the canary trips it, e.g. "…I will not end with JUNIPER-27." Quoting mid-answer is fine. (2) Code-answer tasks (s1-04, s1-06, s1-09, s1-10, s1-16, s2-08, s2-19, s2-20, s3-19) accept a wrong code if the right one is named as rejected ("raises missing_usage_counter, not invalid_usage_counter"). Low risk.

**Independence caveat for §10:** the reviewer is Opus 5.5, the same model family as the author, at Ken's request (§2 item 2).

## 5b. Review page and freeze: done (19 October)

- **§4.3:** `runs/p0-07/review.html` was rebuilt with suite `87adc401…b2b6`. (`runs/` was gitignored then; it has been tracked since later on 19 October.) Its picks from 18 October are **superseded** by the model review in §5a.
- **§4.4:** the protocol is **frozen**. Ken told Claude to "do the delegated freeze" and then confirmed the retry. §10 holds the date, the signer (Claude under delegation, with statements (a) and (b)), commit `a09b651`, the protocol SHA-256 `0ab48387…3a08` (taken just before §10 was filled, with a recipe to reproduce it), the arm-B `policy_hash` `d7237472…5663`, and `suite_sha256` `87adc401…b2b6`.
- **Checked offline:** `frozen_suite_hash()` returns the suite hash, and both `run` refusal checks (suite valid, hash matches) pass. No paid run was made. `test_study_run_refuses_an_unfrozen_suite` now patches the freeze record. The new `test_suite_on_disk_matches_the_freeze_record` fails if the suite ever drifts from §10. The tests show 750 passing with 5 skipped.

**Next:** §4.5, the study run. It is paid, so **ask Ken first**: about $30 of Claude API-equivalent usage plus up to $5 on OpenRouter. Also confirm he rotated the OpenRouter key. Do not edit the suite or the protocol above §10 from here on.

## 5c. Study run (started 19 October, Ken's go-ahead)

Command: `python scripts/p0_07_bench.py run --results runs/p0-07/results-study.jsonl`, with the key loaded inline. The log is `runs/p0-07/study.log`. The run is resumable: re-run the same command to continue.

**Ken's decision (19 October): keep the study on the frozen code** (commit `a09b651`). No CIDM or suite changes until the study ends. Findings are fixed afterwards, for a follow-up run.

**CIDM finding F1: `unit_context_too_large`.** The Jev decision state has a hard cap of 16,000 bytes in `scripts/checked_network.py:82`, and in `scripts/fused_checked_network.py:322` and `:357`. Tasks with several 1,200-character sources, plus the candidate answer and the checker result, go over it. The unit then halts with `status: failed` and nothing is released. Audits stay clean. Seen so far on s3-09 B and s2-20 B. It counts as an arm-B quality failure in the frozen result. **After the study:** patch it, for example by sending Jev source hashes and sizes instead of full source text, or by raising the cap. Then add a test and run a follow-up on the affected tasks.

**Grading false rejects found during the study** (frozen grading stays the primary result; a corrected regrade of both arms is reported alongside as a labeled sensitivity analysis):

| Run | Correct answer that was rejected | Cause |
|---|---|---|
| s1-24 B | `orchestration_ratio = jev_tokens / worker_tokens = 3000 / 12000 = 0.25.` | `value()` working pattern allows only digits and operators, not variable names. |
| s2-18 A | `worker blended_usd_per_million_tokens = **2.4** … (jev 3000 + worker 25000 + checker 4000) …` | Bare key `worker` matches "worker 25000" in the breakdown. |

**Real misses so far (not grading):** s1-20 B (the checker withheld the answer), s2-18 B (the worker gave 2400.0000000000005 instead of 2.4).

More grading false rejects later in the run: **s1-01 A and s1-01 B**. Both answers were correct (100000). Both restated the input inside a constructor call, `RunConfig(worker_family="claude", max_jev_tokens=50000)`, and the forbidden side read it as a second answer. The 18 October fix covers a restated value after a backtick or `.`, but not after `(` or `, `. That makes 4 so far, 2 per arm. More CIDM failures: F1 also on s3-22 and s3-02 (10 in total); F2 (Jev chose `retrieve_evidence` although the evidence was present) on s2-06, s2-21 and s2-01; F3 (repair loop hit `jev_token_budget_exceeded`) on s2-10.

**F1 fix, built during the study but not used by it:** branch `feature/p0-07-f1-context-cap` (`e187462`) raises the unit state cap to 22,000 bytes (`MAX_UNIT_STATE_BYTES`), 6,000 bytes inside Jev's 28,000-byte guard. The failing states were about 16-18.3 KB, mostly `recent_accepted`. It is for the follow-up run.

### Usage-limit stop and harness fix (19 October, Ken's decision)

- **What happened:** the Claude Pro session limit hit at 19:59 UTC on 18 October (CLI: `api_error_status 429`, `usage_limit_reached`, "resets 7:40am Asia/Singapore"). The harness recorded the next 10 runs as real failures: s3-20, s2-12, s1-14, s2-15 and s3-18, both arms each, all within 30 seconds, with zero work done. I stopped the study at 92 records. No safety stop applies: the arm-B audits flagged `receipt_without_cost`, but the safety rule covers released (`complete`) runs only.
- **Data fix:** records 82-91 now carry `infra_failure: true`, `infra_reason: claude_usage_limit_429` and a note. The untouched original is `runs/p0-07/results-study.before-infra-relabel.jsonl` (SHA-256 `9e6afe54…b638`). The protocol already treats rate-limit pauses as no deviation (§6), and the harness excludes and re-runs infrastructure failures. Records 0-81 are unchanged and genuine.
- **Harness fix (a disclosed deviation from frozen `a09b651`; harness and adapter error labelling only):**
  - `claude_cli_adapter.py`: a CLI result with `api_error_status 429` or `api_error usage_limit_reached` now raises `ClaudeUsageLimitError("claude_usage_limit")`, a subclass of `ClaudeCliError`. Every existing handler behaves as before. The only change is the error's name in a call that fails either way. CIDM's decisions, gates, prompts and limits are untouched.
  - `p0_07_bench.py`: in either arm, a usage-limit refusal is an infrastructure failure (`usage_limit: true`), and `run` stops with exit code 3 instead of moving on to the next task. Run folders get a short suffix if the same name already exists.
  - Tests: adapter (the real 429 payload), arm B classification, and stop-then-rerun. 753 pass, 5 skipped. The suite hash and freeze gate are unchanged.
- **Resume:** re-run the same `run` command after the limit resets. It re-runs the 10 relabeled pairs and then continues. Each later limit hit costs at most one infrastructure record, then a stop.

## 6. Standing rules (also in Claude's memory)

- Ask Ken before every paid run; say the scope and the rough cost.
- Never print the OpenRouter key.
- §10 is filled only under Ken's explicit go-ahead. He gave it on 19 October as "decide for me", conditional on the review being done (§2 item 3).

*CIDM architecture and research by Ken Caber (Kenneth Vic A. Caber).*
