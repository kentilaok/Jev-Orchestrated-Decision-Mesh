# Handoff — P0-07 pilot 4, grading fixes, review picks (18 October 2026)

For the next session working on CIDM. Read this first, then `docs/HANDOFF-P0-07-PILOT.md` (suite design) and `docs/P0-07-BENCHMARK-PROTOCOL.md`.

## 1. Where things are now

| What | State |
|---|---|
| Branch | `feature/p0-07-benchmark`, pushed to `origin` with this handoff. |
| Suite | 71 tasks (24/24/23), `suite_sha256` `114eb491f53c5a003340bf3f0442414e3b314a24fa880c79225768daf337dcd2`. `python tasks/p0-07/build_suite.py --check` and `validate --expect-full` pass. |
| Tests | 745 pass, 5 skipped (`python -B -m unittest discover -s tests -p "test_*.py"`). |
| Protocol | **Not frozen.** §10 is empty. Protocol file SHA-256 (unchanged today) `02c9124fac447ba7419ea34ea81d19e0227ef9d9e1413d057cba9db1fd36ef46`. Arm B `RunConfig.policy_hash` `d7237472704f8ed9012c6744d35fa53185f7c11214ef820450b476c540385663`. Recompute all of these at freeze. |
| Review page | Private artifact https://claude.ai/artifact/BHxCZHtpvmL5ktA2tqPeYj: every task with sources, pass and trap answers, grading regexes, Claude's pick and the pilot 4 result. Ken marks OK or Question per task and pastes the summary back. |
| Pilot results | `runs/p0-07/results-pilot4.jsonl` (as recorded) and `results-pilot4-regraded.jsonl` (regraded with the current suite). `runs/` is git-ignored, so these are local only. |

## 2. What changed today

1. **Count checks** (10 tasks) and **single-value checks** (13 tasks) now need the number stated as the answer, not just mentioned: `count()` and `value()` in `tasks/p0-07/build_suite.py`. A wrong answer that mentions the gold number fails; each of these tasks has a fail example proving it (commits `abc7a83`, `e717cfa`).
2. **Pilot 4 found false rejects in that tightening.** Real answers use Markdown and extra words ("returns `0.11` USD", "cumulative_cost_usd after replay = **0.75**", "Exactly 2 of the 7 calls"). Three correct answers on three tasks (s1-03, s2-04, s1-15; four runs) were failed. Fixed: the patterns now allow backticks, bold and quotes around keys and values; on the passing side they also allow up to three words before an explicit separator, a leading "exactly/only/just", and "N of the M things". The forbidden side stays strict. The real answers are now pass examples in the builder.
3. After the fix, one recorded pass became a fail: s1-07 arm A opened with "returns **6** marker dicts" and later said 7. Failing a self-contradicting answer is intended.

## 3. Pilot 4 (12 tasks, both arms, `--pilot`, excluded from analysis)

Seeded sample (seed 20261018, 4 per stratum): s1-03, s1-07, s1-11, s1-15, s2-04, s2-08, s2-17, s2-18, s3-02, s3-09, s3-19, s3-20. Regraded with the current suite:

| | Plain agent (A) | CIDM (B) |
|---|---:|---:|
| Qualified yield | 11/12 = 0.92 | 8/12 = 0.67 |
| S1 / S2 / S3 | 0.75 / 1.00 / 1.00 | 1.00 / 0.50 / 0.50 |
| Mean wall clock | 29.6 s | 79.5 s |
| Mean Claude API-equivalent | $0.140 | $0.241 |
| Mean worker tokens | 13,401 | 50,351 |

Difference B − A = −0.25, bootstrap 95% interval [−0.50, 0.00]. Analysis decision on this sample: `not_non_inferior`. No safety failures. Jev spend $0.016 for 12 arm-B runs.

**Difficulty:** the plain agent scored 0.92, close to the protocol's assumed 0.85. The ceiling problem from pilot 3 (both arms 1.00) is gone.

**All four CIDM misses released nothing; none was a wrong released answer:**

| Task | Status | Cause (from `broker/journal.jsonl` and call events) |
|---|---|---|
| s2-17 | failed after 3 calls | Jev response rejected by `validate_response` with `choice_not_most_probable`, so `jev_call_failed` halted the run. |
| s3-02 | failed after 29 calls | Worker kept returning schema-invalid artifacts (`artifact_schema_valid: false`); repairs and a replan used up the Jev token budget (`jev_token_budget_exceeded`). |
| s3-19 | paused_recoverable | Same schema-invalid loop; local recovery budget exhausted. |
| s2-08 | paused_recoverable | Jev chose `retrieve_evidence`; arm B has no retrieval index, so the run paused for evidence. |

## 4. Decisions for Ken (none taken)

1. **Grading check before the freeze.** 17 tightened count/value tasks have never graded a real model answer, and half of the tightened tasks the pilot hit had a false reject. Suggested: run arm A only on those 17 (about $2 of Claude subscription usage, no OpenRouter spend), fix grading only where a correct answer fails, and record each fix. The 17: s1-01, s1-05, s1-08, s1-13, s1-14, s1-19, s1-22, s1-24, s2-06, s2-07, s2-12, s2-14, s2-16, s2-22, s3-03, s3-05, s3-15.
2. **CIDM misses.** On this sample CIDM would fail non-inferiority, and the cause is the process (schema loops, a strict Jev validator, a retrieval pause with no index), not answer quality. Fixing CIDM using these suite tasks is tuning on the test set, which protocol §3 forbids. Options: (a) run the study as is and report it; (b) fix generic CIDM bugs and record that 12 suite tasks were seen in pilots; (c) replace the 12 piloted tasks with fresh ones before freezing.
3. **Review and freeze.** Ken asked Claude to pick: 54 OK, 17 Question (the 17 above). Claude wrote the questions, so if Ken adopts the picks, §10 should say that the suite review was delegated to the author. Then fill §10 with the recomputed hashes; `frozen_suite_hash()` reads the first `suite_sha256: <64 hex>` line.
4. **Study run** (`python scripts/p0_07_bench.py run`) only after §10 is filled.

## 5. Running live from this PC

- The OpenRouter key is not in any environment variable. Ken keeps it in `C:\Users\caber\Documents\Ken Files\Openrouter API\.env` as a bare key (no `NAME=`). Pass it per command without printing it, for example in Git Bash: `OPENROUTER_API_KEY="$(tr -d '\r\n ' < "/c/Users/caber/Documents/Ken Files/Openrouter API/.env")" python scripts/p0_07_bench.py run --pilot ...`.
- **Rotate that key.** It was printed once into the Claude Code session transcript on 18 October by a redaction command that assumed a `NAME=value` line.
- Use a fresh `--results` file for each pilot. `results.jsonl` already holds pilot records with the same task ids, and the harness skips (task, arm, pilot) pairs it has seen.
- Claude Code's auto mode blocked the first paid pilot attempt as a real-world transaction; the second, after Ken supplied the key, ran.

*CIDM architecture and research by Ken Caber (Kenneth Vic A. Caber).*
