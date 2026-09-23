# Historical CIDM pilot: reproducibility appendix

**Kenneth Vic A. Caber** proposed the Caber Interstitial Decision Mesh (CIDM). This appendix preserves one historical, bounded source-selection and answer-review pilot. It is evidence about that pilot, not a benchmark of the current training-free five-gate GPT-6 skill.

The frozen `frozen-manifest.json` and the original `REPORT.md` use the earlier abbreviated name **Kenneth A. Caber**. Those historical files are preserved byte-for-byte to maintain their provenance and hashes; the full contributor name is **Kenneth Vic A. Caber**.

## Experiment and observed results

The evaluation contained 12 synthetic document questions: four short direct, four noisy retrieval, and four cross-document tasks. Each task received one run in each arm. Two distinct development tasks were analyzed separately. Arm A supplied the full source corpus to `openai/gpt-5.6-sol` at medium effort. Arm B used TypeSafe Jev 1.13 for source selection and candidate review, with the same Sol worker and at most one correction. The evaluation ran through OpenRouter, with Azure returned for every Sol call and TypeSafe for every Jev call.

| Evaluation measure | Arm A: Sol alone | Arm B: historical CIDM |
| --- | ---: | ---: |
| Provider-accounted tokens | 34,942 | 131,388 |
| Sol tokens | 34,942 | 25,030 |
| Jev tokens | 0 | 106,358 |
| Recorded API cost | $0.25523625 | $0.230692994 |
| Sum of task elapsed times | 42.248 s | 68.923 s |
| Calls | 12 | 40 |
| Candidate answer values correct | 12/12 | 12/12 |
| Candidates passing the frozen value, citation, and status rubric | 9/12 | 11/12 |
| Answers released | 12/12 | 7/12 |
| Released answers passing the frozen rubric | 9/12 | 7/12 |

Arm B used **28.4% fewer Sol tokens** but **276.0% more total tokens**. The recorded bill was **9.6% lower**, while summed task time was **63.1% longer**. Four of five withheld CIDM candidates passed the frozen rubric; all five had correct answer values. The paired, stratified bootstrap interval was 215.5%–338.8% **more total tokens**. The 95% cost-savings interval was −29.3% to +49.1%, so this sample does not establish general cost savings.

Jev's raw responses supplied input and output token counters but no `total_tokens` field. The Jev total above is their sum (100,607 input + 5,751 output). The frozen `provider-preflight.json` records a zero completion-token price for Jev at the time; its 26 calls still cost $0.004225494 in aggregate. Reasoning tokens are a subset of output, and cached input is a subset of input; neither is counted twice.

## Reproduce the recorded analysis offline

From this directory, using Python 3.10 or later and no API key:

```sh
python -B -m unittest discover -p "test_*.py" -v
python -B verify_appendix.py
python -B analyze_measured.py --tasks tasks.json --gold gold.json --ledger combined-ledger.jsonl --runs combined-runs.jsonl --output-dir reproduced --seed 1729 --bootstrap-replicates 10000
```

`verify_appendix.py` checks the frozen source and dataset hashes, the split/combined records, all 52 evaluation call records against their saved requests and responses, the expected accounting totals, and a fresh byte-for-byte reproduction of `analysis/results.json`, `analysis/summary.md`, and `analysis/task_results.csv`. The last command writes those three regenerated files to `reproduced/` for inspection.

The data and code map is:

- `tasks.json`, `gold.json`, and `dataset.py`: entirely fictional task corpus, hidden gold labels, and deterministic generator.
- `frozen-manifest.json`, `dataset_manifest.json`, and `provider-preflight.json`: frozen experiment settings, hashes, and historical provider metadata.
- `run_benchmark.py`, `jev_decide.py`, and `grader.py`: original live harness, Jev request validation, and independent deterministic grader. The reproduction commands above do not run paid API calls.
- `analyze.py`: original frozen analyzer. `analyze_measured.py` and `amendment.md`: disclosed correction that retained fully metered failed and partial runs in resource accounting.
- `combined-ledger.jsonl` and `combined-runs.jsonl`: the two development tasks followed by the 12 evaluation tasks, both arms. Their exact components are in `runs-development/` and `runs-evaluation/`.
- `runs-evaluation/*.request.json` and `*.response.json`: 52 pairs of saved raw evaluation calls, with prompts and model responses for the fictional tasks. No authentication headers or API keys are included.
- `analysis/`: preserved results and per-task grades. `blind-grading-audit.md` describes a separate inspection of the frozen citation rubric.
- `SHA256SUMS.txt`: checksums for every appendix file except this README and the checksum file itself.

## Evidence boundary

This is an **API-execution pilot** with one replicate per synthetic task. Dataset design, code creation, review, and local controller work were not metered. The comparison measures selection **plus** review and correction policy; it does not isolate source selection. It had no mandatory Sol-high checker after five gates, no GPT-6 Luna/Sol worker routing, and no measured token savings for the present skill. It cannot establish a five-percentage-point quality noninferiority margin, reliability on real projects, or that model self-scores are calibrated probabilities.

The original `analyze.py` excluded fully metered terminal failures and partial outcomes from full resource comparisons. `analyze_measured.py` was written after evaluation began to correct that accounting rule, without changing tasks, gold answers, prompts, decisions, or grades. Both versions and the amendment are retained. The analysis can be reproduced exactly from saved records; a fresh external-model run can produce different outputs and usage. The files are local records, not independently signed provider attestations. The manifest timestamps document internal chronology but do not independently prove preregistration time.

Raw development request/response files, setup rejection records, route diagnostics, the local packaging script, and the discarded trained-router prototype are outside this appendix. The combined development ledger and runs are included so that the preserved analysis reproduces exactly. The historical report is retained as written; read it alongside this scope and the amendment.
