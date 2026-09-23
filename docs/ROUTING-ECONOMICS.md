# Routing economics and evidence

The goal is to find the smallest model and effort that meet an explicit quality and release criterion. The decision is empirical: price alone does not show that an answer is correct, adequately sourced, or worth releasing.

## Measured GPT-6 fixture comparison

The same three-row synthetic production-record task was run once through the former mandatory-check graph, twice through the Jev-conditional-review graph (before and after final-text validator hardening), and once through a one-call GPT-6 Sol-high baseline. All final answers passed their task-specific value, production scope, trial exclusion, and source citation checks. This tiny fixture evaluates the protocol, not a recommended CIDM use case; simple questions and one-step tasks do not invoke the skill.

| Measured outcome | Former mandatory Sol-high | Conditional review after hardening | One-call Sol high |
|---|---:|---:|---:|
| Provider calls | 23 | 13 | 1 |
| Sol-high checker calls | 5 | 0 | 0 |
| Provider-accounted input + output tokens | 36,663 | 25,510 | 431 |
| Provider-reported API charge | $0.012201078 | $0.006413654 | $0.001726 |
| Sum of recorded API call latency | 36.311 s | 13.499 s | 4.297 s |
| Final value and source checks | Passed | Passed | Passed |

On this fixture, the hardened conditional run used **30.42% fewer tokens and cost 47.43% less** than the older mandatory policy, but it still used **59.19×** as many tokens and cost **3.72×** as much as one Sol-high call. The older graph's five checker calls alone cost $0.010548. The hardened run had 10 Jev calls, three Sol-low workers, and no checker. The [first conditional run](../research/live-gpt6-optional-fixture/README.md) also used zero checkers but chose two Luna-low workers and one Sol-low worker, costing $0.00312019. These runs differ in prompts and worker choices, so cost changes are **observed**, not isolated causal effects of checker policy. The [hardened trace](../research/live-gpt6-optional-final/README.md), [former mandatory trace](../research/live-gpt6-fixture/README.md), and [validation record](VALIDATION.md) preserve the evidence. A fresh replicate can differ.

**Routing consequence:** Simple questions and isolated exact-arithmetic tasks should not invoke CIDM. Within a broad CIDM project, Jev may send a small subtask to deterministic code or one worker instead of giving it five gates. The dedicated five-unit skill retains its topology while letting Jev choose whether any unit needs Sol-high review. A topology decision has its own Jev cost; none of these three runs measured that extra admission gate.

The [recorded fast-exit fixture](../research/live-gpt6-fast-exit/README.md) now measures that admission gate on the same small task. The compact Jev choice used **716 tokens and $0.000026964**, selected exact code, and ended with a validated answer. A first wording used 889 Jev tokens and $0.00003423 for the same route. The compact run used **1.66×** the provider tokens of the one-call Sol-high baseline and **1.56%** of its API dollar charge because exact code replaced the model worker. This is a demonstration of the gate's mechanics, not an estimate for broad projects or an argument to invoke CIDM for standalone easy questions.

## Three accounting units

1. **Provider tokens:** Count input and output for Jev, worker, checker, retries, and failures. Cached input is a subset of input; reasoning output is a subset of output.
2. **API dollars:** Sum the provider-reported charge for every attempted call. Keep missing charges as unknown. OpenRouter Jev and OpenRouter workers share an API bill; Codex signed in with ChatGPT does not.
3. **Codex plan usage:** Record model, effort, turn and subagent usage, remaining plan allowance, and any added ChatGPT credits. These are not API dollars. An API pricing table cannot by itself predict depletion of a subscription allowance.

For an API call with uncached input tokens `I`, cached input tokens `H`, and output tokens `O`, the illustrative model charge is

`C = (I − H) × p_in / 1,000,000 + H × p_cached / 1,000,000 + O × p_out / 1,000,000`.

Use actual provider-reported charges for results. The formula is a forecast: provider routing, regional processing, caching, tool charges, and billing rules may change it. The default local reservation makes **no assumed cache discount**. [OpenAI API pricing](https://developers.openai.com/api/docs/pricing) lists the current base rates. [Codex pricing](https://learn.chatgpt.com/docs/pricing) lists separate plan and credit terms.

For a CIDM run with `n` completed or attempted units, total cost is

`C_CIDM = C_Jev-topology + Σ_i (C_Jev-before,i + C_worker,i + C_Jev-after-worker,i + q_i × (C_Sol-high,i + C_Jev-after-check,i)) + C_repairs + C_failed-attempts + C_other-tools`, where `q_i = 1` only when Jev requests a checker for unit `i`.

Set `C_Jev-topology = 0` when comparing executions of the five-unit runner alone; its project-level topology choice is a separate skill-guided step.

For a fast-exit direct branch, `C_CIDM = C_Jev-fast-gate + C_direct-operation + C_other-tools`. The implemented branch makes no automatic post-worker Jev or checker call. A deterministic branch has `C_direct-operation = 0` in provider charges; local code execution and development still have resource costs outside the API ledger.

Deterministic operations have no generative worker charge. Jev remains required before and after each executed unit in CIDM. A Sol-high reviewer adds its own call and following Jev decision only when selected. Count actual call outcomes rather than assuming all `q_i` are zero or one.

## Break-even test

Let `C_S` be the measured cost of a quality-matched single-Sol baseline per task. Let `C_L` be the Luna-first worker cost, `C_J` **all** Jev decisions including those after checkers, `E[C_H]` the expected cost of selected Sol-high checker calls alone, and `C_R` retries and other overhead. If Luna avoids an additional Sol worker on fraction `r` of comparable tasks, the simplified expected cost is

`C_cascade = C_L + C_J + E[C_H] + C_R + (1 − r) C_S`.

Under those particular assumptions, `C_cascade < C_S` only when `r > (C_L + C_J + E[C_H] + C_R) / C_S`. A quoted 5% threshold applies only if **all** added overhead is 5% of the baseline. Jev calls, selected checkers, retries, and lower release coverage can change the threshold. Compare at equal answer quality and release coverage with uncertainty intervals.

The pasted examples such as “about one to three cents per request,” “20 Luna calls equal one Sol call,” and fixed cache/escalation schedules are **illustrative forecasts**. The 20:1 ratio refers to base token price at the same token footprint, not equal tasks or equal answer quality. Reasoning effort does not fix token output. Never present those scenarios as an observed CIDM result.

The first conditional five-unit run's Jev calls used 23,812 tokens and $0.00097209, an observed blended **$0.04082 per million**; its workers used 1,839 tokens and $0.00214810, a blended **$1.16808 per million**. The ratio **23,812 / 1,839 = 12.95** measures orchestration tokens relative to worker tokens. This mix explains why the run used 59.52× the baseline's tokens while costing 1.81× as much. These are blended outcomes from one run, not advertised token prices or a general efficiency result. See [orchestration metrics and budgets](ORCHESTRATION-BUDGETS.md).

## Audit of the premium-website forecast

The supplied scenario compares a supposed single GPT-6 Sol Max website request costing **$0.2035** with a Jev/Luna-to-Sol-High path costing **$0.07022**. The arithmetic `1 − 0.07022 / 0.2035 = 65.49%` is correct **for those two assumed dollar amounts**. The scenario does not report actual input/output tokens per step, a completed website, Jev API charges, the number of optional reviews Jev would select, retries, tool execution, or equivalent acceptance results. It therefore does not establish that CIDM reduces the cost of building a premium website by 60–70%. A “$10,000 website” is a project brief, not an API price or a measurable quality rubric.

The other quoted percentages—36.0% for a modeled Sol-XHigh branch, 32.8% for an Opus branch, and 3.3% extra for a Sol-Max branch—are likewise arithmetic on incomplete assumptions. Opus and Sol Max are **not worker routes in this skill**; the allowed catalog is GPT-6 Luna/Sol at low through xhigh, with Astra low only after specific authorization. The proposed 1,000-request mix and 90–95% saving have no observed traffic distribution, quality parity, or full-cost ledger. Jev is TypeSafe's model; “Jev/Luna” must not be interpreted as one model invocation.

To test a website claim, freeze a detailed brief (pages, responsive states, content, accessibility, SEO, functional features, delivery format), source material, tools, revision allowance, and acceptance rubric. Run a Sol-only agent and CIDM on the same held-out briefs with randomized order and comparable quality targets. Include every Jev, Luna, Sol-high checker, Sol integration, repair, browser test, and tool call in the record. Report completed sites and acceptance failures alongside total tokens, API dollars or Codex credits, and latency. The measured three-row defect-rate fixture above shows that adding five checked stages can substantially **increase** consumption on an easy task; project complexity may change the balance, but that requires direct evidence.

## Routing inputs and stops

Jev may use task scope, source coverage, hard-check outcomes, contradictions, remaining budget, and measured historical route quality. Keep route options typed and bounded. If probability estimates are used, label whether they are model-reported or calibrated on held-out CIDM tasks. There is no calibrated CIDM escalation threshold yet; do not hard-code `0.82`, `90%` early-stop targets, or a claimed probability of Sol improvement from the illustrative conversation.

Escalate when a specific defect or unmet requirement makes another call valuable and capacity remains. Stop when the answer satisfies the frozen release rule, when evidence cannot support an answer, or when the next call cannot be admitted. The revised five-unit network always returns a candidate to Jev before committing it; the optional-check path has its own measured fixture and needs evaluation on broader project tasks.

For evaluation, freeze task strata, source evidence, validator, outcome rubric, route catalog, and budget before paired runs. Measure every arm against a strong single-model baseline. Report correct values, evidence support, released answers, provider tokens, API charges or Codex credits, latency, and failure counts separately. Preserve all attempts and unknown counters. The [historical CIDM pilot](BENCHMARKS.md) increased total tokens; it did not exercise the current five-unit checked graph.
