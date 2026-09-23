# Contributing

CIDM is led by **Kenneth Vic A. Caber**. Changes should preserve the documented execution contract and state their evidence level.

Keep the core direction training-free. Changes should improve inference-time routing, evidence handling, executable checks, model/provider adapters, or measured efficiency. Do not add training pipelines or learned checkpoints to the current project.

Before proposing a change:

1. Run `python -m unittest discover -s tests -v` without API credentials.
2. Add a behavioral regression for a concrete bug or an adapter contract change.
3. Preserve the Sol-high result → Jev option decision → eligible commit sequence.
4. Keep secrets, raw user prompts, private data, and live logs out of commits. Runtime traces belong in ignored run directories.
5. State whether evidence is simulated, live integration, or a controlled comparison. A successful trace alone does not establish accuracy or token savings.

Efficiency studies should compare complete trajectories at comparable answer quality and release coverage. Count Jev, producers, checkers, retries, rejected work, and retrieval. Report unknown usage as unknown, and preserve unfavorable results.

Model and connector changes need explicit configuration, truthful response-model validation, bounded usage accounting, and tests for malformed responses and failed checks. Do not silently substitute a provider or change effort levels.

Use small, focused pull requests with the problem, resulting behavior, validation, and remaining limitations. Contributions are accepted under the project's MIT license.
