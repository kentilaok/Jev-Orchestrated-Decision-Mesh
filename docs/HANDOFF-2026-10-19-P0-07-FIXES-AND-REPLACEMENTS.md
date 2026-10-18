# Handoff — CIDM bug fixes, 12 replacement tasks, review pending (19 October 2026)

For the next session working on P0-07. Read this first. Background: `docs/HANDOFF-2026-10-18-P0-07-PILOT-4.md` (pilot 4, grading check in §7) and `docs/P0-07-BENCHMARK-PROTOCOL.md`.

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

## 6. Standing rules (also in Claude's memory)

- Ask Ken before every paid run; say the scope and the rough cost.
- Never print the OpenRouter key.
- §10 is filled only under Ken's explicit go-ahead. He gave it on 19 October as "decide for me", conditional on the review being done (§2 item 3).

*CIDM architecture and research by Ken Caber (Kenneth Vic A. Caber).*
