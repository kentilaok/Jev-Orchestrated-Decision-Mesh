# Routing economics and evidence

The goal is to find the smallest model and effort that meet an explicit quality and release criterion. The decision is empirical: price alone does not show that an answer is correct, adequately sourced, or worth releasing.

## Measured GPT-6 fixture comparison

The same three-row synthetic production-record task was run once through the five-unit API reference graph and once through a one-call GPT-6 Sol-high baseline. Both final answers passed the task-specific value, production scope, trial exclusion, and source citation checks. The graph run used Jev 15 times, Luna low 3 times, and Sol high as checker 5 times; the baseline used one Sol-high worker call.

| Measured outcome | Five-unit CIDM | One-call Sol high |
|---|---:|---:|
| Provider calls | 23 | 1 |
| Provider-accounted input + output tokens | 36,663 | 431 |
| Provider-reported API charge | $0.012201078 | $0.001726 |
| Sum of recorded API call latency | 36.311 s | 4.297 s |
| Final value and source checks | Passed | Passed |

On this fixture, the graph used **85.06×** as many tokens and cost **7.07×** as much as the one-call baseline. Its five Sol-high checker calls accounted for $0.010548 of the graph's $0.012201078 charge; 15 Jev calls accounted for 31,700 of its 36,663 tokens. This is one paired integration example, not an estimate for other tasks. The graph and baseline use different prompts and architectures; only the original record task, final value/scope/citation checks, provider, and GPT-6 model family are aligned. Earlier bounded development attempts are reported in [validation](VALIDATION.md). The baseline script is `scripts/compare_baseline.py`; the graph script is `scripts/network_run.py`. A fresh replicate can differ.

**Routing consequence:** For small exact-arithmetic tasks with executable checks, the general skill should let Jev choose a direct deterministic or single-worker branch before starting the five-unit checked network. The dedicated checked-gate skill retains its mandatory five-unit policy. A single route choice still has a Jev cost and needs its own matched evaluation; the comparison above does not measure that admission gate.

## Three accounting units

1. **Provider tokens:** Count input and output for Jev, worker, checker, retries, and failures. Cached input is a subset of input; reasoning output is a subset of output.
2. **API dollars:** Sum the provider-reported charge for every attempted call. Keep missing charges as unknown. OpenRouter Jev and OpenRouter workers share an API bill; Codex signed in with ChatGPT does not.
3. **Codex plan usage:** Record model, effort, turn and subagent usage, remaining plan allowance, and any added ChatGPT credits. These are not API dollars. An API pricing table cannot by itself predict depletion of a subscription allowance.

For an API call with uncached input tokens `I`, cached input tokens `H`, and output tokens `O`, the illustrative model charge is

`C = (I − H) × p_in / 1,000,000 + H × p_cached / 1,000,000 + O × p_out / 1,000,000`.

Use actual provider-reported charges for results. The formula is a forecast: provider routing, regional processing, caching, tool charges, and billing rules may change it. The default local reservation makes **no assumed cache discount**. [OpenAI API pricing](https://developers.openai.com/api/docs/pricing) lists the current base rates. [Codex pricing](https://learn.chatgpt.com/docs/pricing) lists separate plan and credit terms.

For a CIDM run with `n` completed or attempted units, total cost is

`C_CIDM = Σ_i (C_Jev-before,i + C_worker,i + C_Jev-check-authorization,i + C_Sol-high,i + C_Jev-after,i) + C_repairs + C_failed-attempts + C_other-tools`.

Deterministic worker operations have no generative worker charge. The mandatory Sol-high checker still applies in the checked five-unit network. Do not report Luna worker savings as total system savings.

## Break-even test

Let `C_S` be the measured cost of a quality-matched single-Sol baseline per task. Let `C_L` be the Luna-first worker cost, `C_J` all Jev decisions, `C_H` required Sol-high checking, and `C_R` other retries and overhead. If Luna avoids an additional Sol worker on fraction `r` of comparable tasks, the simplified expected cost is

`C_cascade = C_L + C_J + C_H + C_R + (1 − r) C_S`.

Under those particular assumptions, `C_cascade < C_S` only when `r > (C_L + C_J + C_H + C_R) / C_S`. A quoted 5% threshold would apply only if the entire added overhead were 5% of the baseline. CIDM's Jev calls and five required Sol-high checks can make it materially higher. Compare at equal answer quality and release coverage, and include uncertainty intervals; otherwise an apparent saving may simply reflect abstention or missed work.

The pasted examples such as “about one to three cents per request,” “20 Luna calls equal one Sol call,” and fixed cache/escalation schedules are **illustrative forecasts**. The 20:1 ratio refers to base token price at the same token footprint, not equal tasks or equal answer quality. Reasoning effort does not fix token output. Never present those scenarios as an observed CIDM result.

## Audit of the premium-website forecast

The supplied scenario compares a supposed single GPT-6 Sol Max website request costing **$0.2035** with a Jev/Luna-to-Sol-High path costing **$0.07022**. The arithmetic `1 − 0.07022 / 0.2035 = 65.49%` is correct **for those two assumed dollar amounts**. The scenario does not report actual input/output tokens per step, a completed website, Jev API charges, five mandatory Sol-high checks, retries, tool execution, or equivalent acceptance results. It therefore does not establish that CIDM reduces the cost of building a premium website by 60–70%. A “$10,000 website” is a project brief, not an API price or a measurable quality rubric.

The other quoted percentages—36.0% for a modeled Sol-XHigh branch, 32.8% for an Opus branch, and 3.3% extra for a Sol-Max branch—are likewise arithmetic on incomplete assumptions. Opus and Sol Max are **not worker routes in this skill**; the allowed catalog is GPT-6 Luna/Sol at low through xhigh, with Astra low only after specific authorization. The proposed 1,000-request mix and 90–95% saving have no observed traffic distribution, quality parity, or full-cost ledger. Jev is TypeSafe's model; “Jev/Luna” must not be interpreted as one model invocation.

To test a website claim, freeze a detailed brief (pages, responsive states, content, accessibility, SEO, functional features, delivery format), source material, tools, revision allowance, and acceptance rubric. Run a Sol-only agent and CIDM on the same held-out briefs with randomized order and comparable quality targets. Include every Jev, Luna, Sol-high checker, Sol integration, repair, browser test, and tool call in the record. Report completed sites and acceptance failures alongside total tokens, API dollars or Codex credits, and latency. The measured three-row defect-rate fixture above shows that adding five checked stages can substantially **increase** consumption on an easy task; project complexity may change the balance, but that requires direct evidence.

## Routing inputs and stops

Jev may use task scope, source coverage, hard-check outcomes, contradictions, remaining budget, and measured historical route quality. Keep route options typed and bounded. If probability estimates are used, label whether they are model-reported or calibrated on held-out CIDM tasks. There is no calibrated CIDM escalation threshold yet; do not hard-code `0.82`, `90%` early-stop targets, or a claimed probability of Sol improvement from the illustrative conversation.

Escalate when a specific defect or unmet requirement makes another call valuable and capacity remains. Stop when the answer satisfies the frozen release rule, when evidence cannot support an answer, or when the next call cannot be admitted. A five-unit checked run always applies the mandatory checker policy before committing a unit. A different conditional-checker policy would be a different architecture and needs its own evaluation.

For evaluation, freeze task strata, source evidence, validator, outcome rubric, route catalog, and budget before paired runs. Measure every arm against a strong single-model baseline. Report correct values, evidence support, released answers, provider tokens, API charges or Codex credits, latency, and failure counts separately. Preserve all attempts and unknown counters. The [historical CIDM pilot](BENCHMARKS.md) increased total tokens; it did not exercise the current five-unit checked graph.
