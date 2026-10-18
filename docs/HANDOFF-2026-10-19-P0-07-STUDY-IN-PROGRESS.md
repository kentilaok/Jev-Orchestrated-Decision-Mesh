# Handoff — P0-07 study run in progress, paused on the Claude usage limit (19 October 2026)

For the next agent continuing P0-07. **Read this file first.** It supersedes the "next steps" in earlier handoffs. Background, in order: `docs/HANDOFF-2026-10-19-P0-07-FIXES-AND-REPLACEMENTS.md` (§5a review fixes, §5b freeze, §5c study notes and the usage-limit fix), `docs/HANDOFF-2026-10-18-P0-07-PILOT-4.md`, `docs/P0-07-BENCHMARK-PROTOCOL.md`.

## 1. Where things are

| What | State |
|---|---|
| Branch | `feature/p0-07-benchmark`, pushed. The head is this handoff's commit. Earlier commits: `4547a77` (usage-limit harness fix), `beee12f` (study notes), `fab32be` (**freeze**), `a09b651` (frozen suite and code). |
| Protocol | **Frozen** (§10 filled 19 October under Ken's delegation). Suite `suite_sha256` `87adc401b8297432c969aa01e3ffebf0427994a647803b3abd74ea116c55b2b6`, 71 tasks (S1 24, S2 24, S3 23). Do not edit the suite, or the protocol above §10. |
| Study run | **Paused** at 82 genuine (task, arm) pairs of 142, plus 10 infrastructure records. The Claude Pro session limit hit at 19:59 UTC on 18 October. The CLI said it "resets 7:40am (Asia/Singapore)", that is 23:40 UTC. Still limited at 20:08 UTC. |
| Spend so far | Claude about $16.39 API-equivalent (subscription usage, not billed); Jev/OpenRouter $0.060 of the $5.00 hard stop. |
| Tests | 753 pass, 5 skipped (`python -B -m unittest discover -s tests -p "test_*.py"`). `python -B tasks/p0-07/build_suite.py --check`: no problems, hash as above. The freeze gate passes. |
| F1 fix | Branch `feature/p0-07-f1-context-cap` (`e187462`, pushed). **Not** used by the study; it is for the follow-up run. |

## 2. How to resume (the next action)

1. Check that the limit has lifted with one tiny call. It costs a few tokens. Look for `api_error_status` 429 or `usage_limit_reached`:
   ```bash
   claude -p "Reply with the single word ok." --output-format json
   ```
2. Resume from the repo root. This is the same command as before. **Never print the key.** The key file is a bare key with no `NAME=`:
   ```bash
   OPENROUTER_API_KEY="$(tr -d '\r\n ' < "/c/Users/caber/Documents/Ken Files/Openrouter API/.env")" python -B scripts/p0_07_bench.py run --results runs/p0-07/results-study.jsonl > runs/p0-07/study.log 2>&1
   ```
   Run it in the background. It re-runs the 10 infrastructure pairs first, then continues in the seeded order. Recorded genuine pairs are skipped.
3. Ken's go-ahead for this study covers resuming it (19 October, "Proceed"). A new or different paid run (pilot, follow-up) needs a new go-ahead, with scope and cost.
4. Exit codes and stops:
   - `3` with `"reason": "claude_usage_limit"`: the limit hit again. One infrastructure record was written. Wait for the reset and resume.
   - `1` with `safety_gate`: **stop and report to Ken**. Do not rerun to replace it (protocol §4).
   - `0` with `study_jev_budget_reached`: the $5 Jev stop.
   - `0` with `done`: all pairs recorded.
5. Watch it. Each new line of `runs/p0-07/results-study.jsonl` is one run. For arm-B failures, the reason is `error` in `<run_dir>/broker/result.json`. On Windows, set `PYTHONIOENCODING=utf-8` before printing answers (they contain `→`).

## 3. Decisions Ken made in this session (in his words, summarised)

1. **Model review by Opus 5.5:** done, and every flag was fixed (handoff §5a).
2. **"Do the delegated freeze":** done; §10 holds both delegations (handoff §5b).
3. **"Proceed"** with the paid study run, after the scope and cost were stated.
4. **Keep the study on the frozen code.** Record `unit_context_too_large` as a CIDM finding and patch it after the study, for a follow-up run. Do not patch CIDM mid-study.
5. **"Proceed with recommended fix":** F1 fix built on a separate branch (see §5). The study stays on the frozen code.
6. **Usage-limit records:** mark the 10 as infrastructure failures, keep the original file, patch the harness to record a limit refusal as infrastructure and stop, record it as a harness fix, and resume after the reset. Done (`4547a77`).
7. **Asked "should we lessen its gates?"** Claude's answer was no: the gates are not what blocks CIDM (§4 below), and the one wrong answer already got past them. Ken did not overrule this.

## 4. Results so far (82 genuine pairs, frozen grading)

| Arm | Accepted |
|---|---|
| A (direct Claude) | 39 / 41 |
| B (CIDM) | 23 / 41 |

All 20 rejections, classified:

| Run | Status / reason | Class |
|---|---|---|
| s3-09, s2-20, s3-05, s3-13, s2-22, s2-07, s3-14, s2-03, s3-22, s3-02 (all B) | `failed` / `unit_context_too_large` | **F1**: 16,000-byte Jev state cap (10 runs) |
| s2-06, s2-21, s2-01 (B) | `paused_recoverable` | **F2**: Jev chose `retrieve_evidence` although the evidence was present |
| s2-10 (B) | `failed` / `jev_call_failed` (`jev_token_budget_exceeded`) | **F3**: the repair loop used up the Jev token budget (23 Jev calls) |
| s1-20 (B) | `quality_failed` | The checker withheld the answer; not yet inspected |
| s2-18 (B) | `complete`, wrong answer | Real miss: 2400.0000000000005 instead of 2.4, released with clean audits |
| s1-24 (B) | `complete`, rejected | **Grading false reject**: `= jev_tokens / worker_tokens = 3000 / 12000 = 0.25`; the `value()` working pattern allows no names |
| s2-18 (A) | `answered`, rejected | **Grading false reject**: the bare key `worker` matched "worker 25000" in the breakdown |
| s1-01 (A) and s1-01 (B) | rejected | **Grading false reject**: the restated input `RunConfig(…, max_jev_tokens=50000)` was read as a second answer |

In 8 of the 11 F1/F2/F3 runs, the candidate CIDM was holding would have been accepted. That is a rough regrade of the last `provisional_return`, which is not always in final form.

**Reporting plan agreed with Ken:** the frozen grading is the primary result. A corrected regrade of **both** arms (the 4 false rejects so far: 2 per arm) is reported alongside as a labelled sensitivity analysis. Keep adding false rejects as the run continues. Do not change the suite.

## 5. Findings and fixes

- **F1, `unit_context_too_large`** (the biggest cause). Caps are in `scripts/checked_network.py:82` and `scripts/fused_checked_network.py:322` and `:357`. Measured: failing states were about 16.0-18.3 KB. The largest part is `recent_accepted` (7.5-10.6 KB), then the candidate (about 3-4 KB) and the evidence. **Fix on `feature/p0-07-f1-context-cap` (`e187462`):** `MAX_UNIT_STATE_BYTES = 22000`, kept `JEV_REQUEST_RESERVE_BYTES = 6000` inside `jev_decide.MAX_REQUEST_BYTES = 28000`. The largest non-state request part seen was 4,189 bytes. Nothing is trimmed. 3 tests in `tests/test_controller.py` (`UnitStateLimitTests`). The branch is cut from `a09b651`; merge or rebase onto `feature/p0-07-benchmark` after the study.
- **F2, evidence over-pause:** not fixed. The proposal, which is Ken's design call because it changes how CIDM asks an operator: offer `retrieve_evidence` only when Jev can name a source that is actually missing; when all hard checks pass, send the answer on to the checker.
- **F3, repair loop hits the Jev token budget:** not fixed. The proposal: cap repair rounds below the budget so the unit fails fast, and inspect s2-10 for why the repairs did not converge.
- **Harness fix (`4547a77`, a disclosed deviation from `a09b651`):** `ClaudeUsageLimitError("claude_usage_limit")` (a subclass of `ClaudeCliError`) in `scripts/claude_cli_adapter.py`. In `scripts/p0_07_bench.py`: an infrastructure failure in either arm, stop with exit code 3, and a unique run-folder suffix. Details in the fixes handoff §5c.

## 6. Data files

- `runs/p0-07/results-study.jsonl`: live results. It is **gitignored**, so it exists only on this PC. Records 82-91 carry `infra_failure: true` and `infra_reason: claude_usage_limit_429`.
- `runs/p0-07/results-study.before-infra-relabel.jsonl`: the untouched original from before the relabel (SHA-256 `9e6afe54…b638`).
- `runs/p0-07/study/<task>-<arm>-<stamp>/`: per-run folders (broker logs, Jev requests and responses, `attempts.json`). Also local only.
- **Snapshot committed with this handoff:** `docs/p0-07-study-snapshot/` holds copies of both JSONL files as of the pause (`results-study.jsonl` SHA-256 `2dd71d5e…7981`). It is for an agent on another machine. The run folders are not included. **The live file in `runs/` stays authoritative.** If you continue on another machine, copy the snapshot to `runs/p0-07/results-study.jsonl` first, and expect missing run folders for the old records.
- `runs/p0-07/review.html`: the review page (local), with picks superseded by the model review.

## 7. After the study finishes (in order)

1. `python -B scripts/p0_07_bench.py analyze --results runs/p0-07/results-study.jsonl` gives the primary result (non-inferiority, safety, efficiency per protocol §5).
2. Sensitivity regrade: apply corrected grading to both arms' stored answers (`tasks/p0-07/review/regrade.py` shows the pattern). Fix the false-reject patterns in a copy of the grading, not in the frozen suite, and report both numbers.
3. Inspect s1-20 B (the checker withhold) and the F2 runs, and decide whether each candidate was correct.
4. Write the study report: results, findings F1-F3, the deviation (the harness fix), the review independence caveat (Opus 5.5, same family) and the delegations.
5. Follow-up run (**needs Ken's go-ahead**, new results file): merge the F1 branch (and F2/F3 if Ken approves), then run arm B on the affected tasks.
6. Housekeeping: `.claude/worktrees/f1-context-cap` is a git worktree inside this checkout. Remove it after merging (`git worktree remove .claude/worktrees/f1-context-cap`).

## 8. Standing rules

- Ask Ken before every **new** paid run; state the scope and rough cost. Resuming this study is already approved.
- Never print the OpenRouter key (`C:\Users\caber\Documents\Ken Files\Openrouter API\.env`, a bare key). Ken was told to rotate it after it leaked on 18 October. He said "Proceed" when asked, but never explicitly confirmed the rotation.
- No CIDM or suite changes on `feature/p0-07-benchmark` until the study ends. Work on the fixes goes on separate branches or worktrees: the running study launches the broker from `scripts/` for every arm-B task.
- Explain things to Ken in plain terms; he found the jargon hard to follow.

*CIDM architecture and research by Ken Caber (Kenneth Vic A. Caber).*
