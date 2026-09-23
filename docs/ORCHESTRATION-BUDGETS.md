# Orchestration budgets and observable metrics

CIDM measures model work **and** the work spent deciding what model work to do. The reference `scripts/metrics.py` adds role totals to new run results. It does not label a call avoidable without a frozen task outcome and counterfactual route. A Jev-only log with no complete primary-agent, worker, or checker usage supports only a **partial** total; missing usage must not be entered as zero.

## Measured overhead in the saved fixture

| Run | Jev tokens | Worker tokens | Jev / worker tokens | Jev blended USD/M tokens | Worker blended USD/M tokens |
|---|---:|---:|---:|---:|---:|
| First five-unit conditional run | 23,812 | 1,839 | 12.95× | $0.04082 | $1.16808 |
| Later five-unit conditional run | 23,752 | 1,758 | 13.51× | $0.04082 | $3.09670 |
| Previous compact Jev fast exit | 716 | 0 | undefined | $0.03766 | undefined |

The blended rates divide each role's **observed provider charge** by its **reported input plus output tokens**. They are not catalog prices. Input/output composition, caching, provider routing, and the selected worker model changed between runs. Jev's low price per token explains why 59.52× the provider tokens in the first conditional graph cost 1.81× the one-call Sol-high baseline. It does not make repeated Jev calls free. [Raw role totals](../research/live-gpt6-optional-fixture/README.md) and [the later run](../research/live-gpt6-optional-final/README.md) support the table. The [fast-exit trace](../research/live-gpt6-fast-exit/README.md) records one TypeSafe decision under the earlier routing policy; it is not a test of the new Luna-low short path.

## Boundaries enforced by the runner

`examples/config.openrouter.json` contains the current run defaults: `max_usd = 1.50`, `max_calls = 40`, `max_jev_calls = 30`, `max_jev_tokens = 50,000`, `max_worker_calls = 12`, and `max_checker_calls = 10`. These are safety ceilings for a bounded example, not optimized values for a project. The revised short branch structurally allows **zero Jev calls, one Luna-low worker, and zero checkers**. Broad or unclassified inputs enter the five-unit branch, which still permits bounded repair and conditional review.

The call caps are checked **before dispatch**. The reported Jev-token ceiling is checked before another call and again when each response arrives. If a response crosses the ceiling, the decision is rejected and no dependent work is released; tokens already spent upstream may still be billed. `max_usd` uses conservative per-call reservations and blocks future calls when reported cost is missing or exceeds the ceiling. These mechanisms cannot guarantee an upstream invoice or predict a model's exact token output.

For every transition, recompute remaining Jev calls, tokens, and API dollars from append-only provider receipts. Do not carry forward a number typed into an earlier Jev prompt. When a provider omits `total_tokens`, use reported input plus output; cached input and reasoning output are subsets, not additions. Missing usage or a mismatch between a stated balance and receipts makes the budget unverified and prevents another dependent dispatch until resolved. Before launching a worker or checker, reserve a following Jev decision slot and a conservative cost/token envelope. A positive pre-call balance is an admission check, not a guarantee that the next response cannot overshoot the ceiling.

The proposed LOW/MEDIUM/HIGH/EXTREME token budgets in the source conversation are **design examples**, not measured thresholds. The former compact Jev fast gate used 716 tokens in one run and 889 in another; a fixed 750-token ceiling would have rejected the latter. Those measurements do not size the new short branch. Select caps from representative held-out project data, monitor legitimate halts, and publish the chosen policy before evaluating it.

## Price-aware admission

The dated [API and Codex price tables](ROUTING-ECONOMICS.md#published-api-list-prices) give a rate for each permitted model, but a budget decision needs a **token envelope**, including the carried context and maximum output. Estimate the next transition as `Jev decision + selected worker + optional Sol-high check and following Jev decision + allowed repair`, with each term charged using its own input, cache-read, cache-write, and output counts. A short Luna-low branch has no Jev or checker term. For comparable token footprints under OpenAI Standard short-context API pricing, Sol costs 20 times Luna and Astra costs five times Sol; actual calls can have different context and reasoning output. [OpenAI's reasoning guide](https://developers.openai.com/api/docs/guides/reasoning) explains that reasoning tokens are billed as output. Effort changes the likely token volume, not the model's listed per-token rate.

Keep two independent limits when a Codex worker is signed in with ChatGPT and Jev uses OpenRouter: **external API USD** for Jev and **Codex included usage or credits** for the worker. [Codex pricing](https://learn.chatgpt.com/docs/pricing) lists GPT-6 Standard credit rates and says included usage cannot be inferred from credit prices alone. Neither limit converts automatically into the other. Astra remains disabled unless specifically authorized. Tool charges, provider routing, failed calls, and cache-write premiums belong in the cost reserve when applicable; a simple input/output projection is not a guaranteed upper bound.

## Metrics to report

- `orchestration_ratio = jev_tokens / worker_tokens` when both counts are complete and worker tokens are positive. Report primary-agent tokens separately; if the primary agent did substantive work and its usage is unavailable, mark the whole-run ratio incomplete rather than treating the agent as free. The revised one-worker short branch has zero Jev tokens by design, excluding host classification work. The previous deterministic fast exit has no worker denominator, so its ratio is undefined.
- `cost_multiplier = CIDM total reported API cost / matched baseline reported API cost` only for matched, fully measured **all-API** runs. Include root agent, subagents, retries, and checkers in any whole-run comparison. For a mixed subscription-host/API run, report Codex credits or included-allowance usage and external API dollars separately; there is no single dollar multiplier without a declared conversion and complete billing evidence. If worker usage or the baseline bill is missing, the multiplier is unknown.
- `quality_gain_binary` is the difference in pass/fail status under one shared task rubric. `cost_per_quality_gain_usd` is undefined when that gain is zero or negative. Broader work needs a richer frozen quality scale.
- `worker_calls`, `jev_passes`, `checker_calls`, `escalations`, and `early_exit_selected` are observed counters. `avoidable_escalations`, `avoidable_worker_calls`, and `early_exit_possible` remain `null` until an outcome-aware counterfactual evaluator labels them. Missing usage counters also remain unknown.

Expected-value stopping can be written as `P(material improvement) × value of that improvement − cost of the next call`. Jev and worker self-probabilities are not calibrated on CIDM project outcomes, and the value term is task-dependent. The current runner therefore uses executable eligibility, bounded options, source evidence, and hard budgets; it does not automate a threshold from illustrative probabilities such as 3% or 65%.
