# Handoff — project move, P0-07 suite, offline local model (18 October 2026)

For the next session working on CIDM. Read this first, then `docs/HANDOFF-P0-07-PILOT.md`.

> **P0-07 status here is out of date.** For P0-07, read `docs/HANDOFF-2026-10-18-P0-07-PILOT-4.md` instead: it records pilot 4, the grading fixes, the review picks and the decisions still open. Sections 1 and 3 (folder move, offline local model) are still current.

## 1. Where things are now

| What | State |
|---|---|
| Project folder | **Moved** from `D:\Laptop Transfer\Hermes Jev CIDM` to `C:\Users\caber\Documents\Ken Files\Hermes Jev CIDM`. Exact copy (checksums verified, git intact). The old D: folder is empty; delete it once no session or terminal still points there. |
| Branch | `feature/p0-07-benchmark` at `b3573ab`, pushed to `origin` (github.com/kentilaok/Jev-Orchestrated-Decision-Mesh). No upstream tracking is set locally; push with `git push origin feature/p0-07-benchmark`. `main` has newer citation/DOI commits that do not touch this branch's files. |
| Uncommitted | `.claude/` (local Claude Code settings, untracked; leave it) and this handoff file. |
| Older sessions | The session "Hermes Jev CIDM project" still has the old D: path as its folder. Continue the work from a session opened in the new folder. |

Any absolute path to `D:\Laptop Transfer\...` in notes, scripts or session memory is stale. Code in the repo uses relative paths (`Path(__file__)`), so nothing in the code needed changing.

## 2. P0-07 — what was done and what is next

Done (commit `b3573ab`):
- 71 tasks in `tasks/p0-07/` (24 S1 / 24 S2 / 23 S3). `python scripts/p0_07_bench.py validate --expect-full` → ok.
- `tasks/p0-07/build_suite.py` generates the JSON, checks every gold answer by running the real repo functions, and checks code excerpts against their files. `--check` re-verifies and fails if any JSON drifted.
- `tests/test_p0_07_bench.py` checks the full suite instead of the pilot counts. Full offline suite: 745 pass, 5 skipped.
- `docs/HANDOFF-P0-07-PILOT.md` §4 lists task families and how golds were verified.

Next (in order, none of it done yet):
1. Optional pilot on a sample of the new suite (`python scripts/p0_07_bench.py run --pilot --task ...`) to see whether the direct-agent yield lands near the 0.85 target. **This is a paid live run** (Claude usage + OpenRouter for Jev); get Ken's go-ahead first.
2. Ken reviews the suite and its checks, then fills and countersigns the freeze record (protocol §10). Do not fill §10 yourself.
3. Study run (`python scripts/p0_07_bench.py run`), resumable.

Open points flagged for Ken (in the pilot handoff §4): S2's "one in three triggers repair/retrieval/pause" is met only by repair-prone traps (no retrieval index in arm B); a few count checks use bare numbers, so a wrong answer mentioning the gold number would pass.

## 3. Offline local model (outside the repo, on this PC)

Goal from Ken: when there is no internet, Hermes keeps working on a local model.

| Piece | Setting |
|---|---|
| Runtime | Ollama 0.40.5, `%LOCALAPPDATA%\Programs\Ollama`, API `http://127.0.0.1:11434` (OpenAI-compatible at `/v1`). Starts with Windows. |
| Model | `hf.co/mradermacher/Qwen3.5-9B-ultra-uncensored-heretic-v2-i1-GGUF:i1-Q6_K` (7.4 GB). Qwen3.5-9B with refusals removed by Heretic (4/100 refusals vs 86/100; MMLU 0.784 vs 0.786). It has no built-in refusals, so limits come from system prompts and CIDM's permits/approval gate. |
| Context | User env var `OLLAMA_CONTEXT_LENGTH=32768`. Measured on the RTX 3060 12 GB: 32K = 7.8 GB, 64K = 8.9 GB (safe maximum), 96K = 10.0 GB (almost no headroom), 128K spills to CPU. Hermes needs more than 4K (its prompt and tools did not fit at 4,096). |
| Hermes | `%LOCALAPPDATA%\hermes\config.yaml` has a marked block `BEGIN/END local-offline-fallback` with `fallback_providers: [custom → the model above at http://127.0.0.1:11434/v1]`. Backup: `config.yaml.bak-offline-20261018T212755`. Primary is unchanged (`anthropic/claude-opus-4.6` via auto). `hermes fallback list` shows the chain. |
| Verified | Simulated offline (dead proxy, localhost exempt): Hermes fell back and answered in 22 s, 100% GPU, 32K context. Offline it also saw its skills and its memory tool. |

Known limits offline:
- **Jev has no offline version.** It is reachable only via OpenRouter or TypeSafe's API (`scripts/jev_decide.py` `ENDPOINTS`), and the Claude CLI workers also need the internet. So the CIDM broker (`cidm-jev`) does not run offline; only plain Hermes does. An offline CIDM would need Jev replaced locally (deterministic rules, i.e. the protocol's unimplemented "arm C", or the local model as gate). That would drop the Jev guarantees, so it is a design decision for Ken.
- Hermes **auxiliary tasks** (context compression, memory tidy-ups) use `auxiliary: auto` (online), so long offline sessions may fail to compress. Fix if wanted: point `auxiliary.*` or a `fallback_chain` at the same local endpoint.
- **CIDM lessons**: none promoted yet (`~/.jev/hermes-skills` does not exist; Hermes is not pointed at it via `skills.external_dirs`). Lessons come from broker runs, which need the internet.
- The CIDM Hermes provider (`scripts/install_hermes_cidm_provider.py`) is **not** installed in the current Hermes config.

## 4. Suggested next steps for the new session

1. Confirm the folder: `git status` in the new path, then `python -B -m unittest discover -s tests -p "test_*.py"`.
2. Ask Ken whether to run the P0-07 pilot (paid) or go straight to his suite review.
3. If offline use matters beyond chat: offer to route Hermes auxiliary tasks to the local model, and raise the offline-Jev question as a design decision.
4. Optionally commit this handoff on the branch (it is untracked now).

*CIDM architecture and research by Ken Caber (Kenneth Vic A. Caber).*
