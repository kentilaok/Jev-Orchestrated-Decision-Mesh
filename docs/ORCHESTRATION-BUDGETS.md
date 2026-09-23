# Orchestration budgets and observable metrics

CIDM measures model work **and** the work spent deciding what model work to do. The reference `scripts/metrics.py` adds role totals to new run results. It does not label a call avoidable without a frozen task outcome and counterfactual route.

## Measured overhead in the saved fixture

| Run | Jev tokens | Worker tokens | Jev / worker tokens | Jev blended USD/M tokens | Worker blended USD/M tokens |
|---|---:|---:|---:|---:|---:|
| First five-unit conditional run | 23,812 | 1,839 | 12.95× | $0.04082 | $1.16808 |
| Later five-unit conditional run | 23,752 | 1,758 | 13.51× | $0.04082 | $3.09670 |
| Compact Jev fast exit | 716 | 0 | undefined | $0.03766 | undefined |

The blended rates divide each role's **observed provider charge** by its **reported input plus output tokens**. They are not catalog prices. Input/output composition, caching, provider routing, and the selected worker model changed between runs. Jev's low price per token explains why 59.52× the provider tokens in the first conditional graph cost 1.81× the one-call Sol-high baseline. It does not make repeated Jev calls free. [Raw role totals](../research/live-gpt6-optional-fixture/README.md) and [the later run](../research/live-gpt6-optional-final/README.md) support the table. The [fast-exit trace](../research/live-gpt6-fast-exit/README.md) records one TypeSafe decision on the same fictional task.

## Boundaries enforced by the runner

`examples/config.openrouter.json` contains the current run defaults: `max_usd = 1.50`, `max_calls = 40`, `max_jev_calls = 30`, `max_jev_tokens = 50,000`, `max_worker_calls = 12`, and `max_checker_calls = 10`. These are safety ceilings for a bounded example, not optimized values for a project. The fast-exit direct branches structurally allow **one Jev decision, zero or one worker, and zero checkers**. The five-unit branch still permits bounded repair and conditional review.

The call caps are checked **before dispatch**. The reported Jev-token ceiling is checked before another call and again when each response arrives. If a response crosses the ceiling, the decision is rejected and no dependent work is released; tokens already spent upstream may still be billed. `max_usd` uses conservative per-call reservations and blocks future calls when reported cost is missing or exceeds the ceiling. These mechanisms cannot guarantee an upstream invoice or predict a model's exact token output.

The proposed LOW/MEDIUM/HIGH/EXTREME token budgets in the source conversation are **design examples**, not measured thresholds. The compact fast gate used 716 tokens in one run and 889 in another; a fixed 750-token ceiling would have rejected the latter. Select caps from representative held-out project data, monitor legitimate halts, and publish the chosen policy before evaluating it.

## Metrics to report

- `orchestration_ratio = jev_tokens / worker_tokens` when both counts are complete and worker tokens are positive. A deterministic fast exit has no worker denominator, so the ratio is undefined.
- `cost_multiplier = CIDM total reported API cost / matched baseline reported cost` when both bills are complete and tasks match. A subscription-host run needs a separate Codex-credit comparison; API dollars are not a substitute.
- `quality_gain_binary` is the difference in pass/fail status under one shared task rubric. `cost_per_quality_gain_usd` is undefined when that gain is zero or negative. Broader work needs a richer frozen quality scale.
- `worker_calls`, `jev_passes`, `checker_calls`, `escalations`, and `early_exit_selected` are observed counters. `avoidable_escalations`, `avoidable_worker_calls`, and `early_exit_possible` remain `null` until an outcome-aware counterfactual evaluator labels them. Missing usage counters also remain unknown.

Expected-value stopping can be written as `P(material improvement) × value of that improvement − cost of the next call`. Jev and worker self-probabilities are not calibrated on CIDM project outcomes, and the value term is task-dependent. The current runner therefore uses executable eligibility, bounded options, source evidence, and hard budgets; it does not automate a threshold from illustrative probabilities such as 3% or 65%.
