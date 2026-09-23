# Models, configuration, and connectors

CIDM calls existing models at inference time. The Python runner implements the OpenRouter API route. `adaptive_run.py` accepts a context-bound host classification for its production-record fixture: explicit short and self-contained scope calls one Luna-low worker; broad, uncertain, or missing classification enters Jev's five-unit/evidence/stop choice. The installed skill also documents a Codex-native route that uses host-provided subagents under the current Codex sign-in and calls Jev separately. The interactive route is not an automatically enforced transition broker. See [execution routes](EXECUTION-ROUTES.md). A ChatGPT login does not supply credentials or credits to the OpenRouter runner.

## Current interfaces

`scripts/transport.py` defines two Python protocols:

- `DecisionAdapter.network_judge(phase, options, state)` supplies Jev's predefined choice and metadata.
- `GenerativeAdapter.ask(role, instructions, state, schema, worker_route)` produces a structured worker artifact using the Jev-approved route; `high_check(state)` produces the separate checker report.

`Gateway` implements both protocols and records calls, usage, cost, latency, model identity, and configuration hash. `CheckedNetwork` receives judge, producer, checker, and validator callbacks; this is the application integration boundary. Protocol declarations do not automatically install another connector. A replacement needs an implementation, explicit wiring, and equivalent contract/accounting tests.

Jev chooses among finite options and supplies decision metadata. It does not write prose summaries. A worker or deterministic code builds the next artifact. The broker decides which validated evidence reaches the next unit.

## Configuration

`examples/config.openrouter.json` is the complete default configuration. `scripts/config.py` rejects unknown fields, including secret-bearing fields, and freezes validated settings for the run.

| Fields | Purpose |
|---|---|
| `worker_model`, `worker_effort` | Default direct-call worker model/effort; checked gates use Jev-selected routes |
| `checker_model`, `checker_effort` | GPT-6 Sol high when Jev requests extra review |
| `astra_explicitly_authorized` | Off by default; only enable after specific user authorization, with Astra price headroom |
| `jev_model` | Versioned TypeSafe Jev model ID |
| `provider_route`, `provider_name` | OpenRouter route slug and expected returned provider name |
| `jev_provider_name` | Expected Jev provider name when the response supplies one |
| `*_model_aliases` | Explicit accepted version aliases; no arbitrary fallback |
| `max_usd`, `max_calls`, `max_output_tokens`, `timeout` | Overall API budget, calls, worker/checker output cap, per-call timeout |
| `max_jev_calls`, `max_jev_tokens` | Jev call count and reported-token ceiling; a response that crosses the latter can be billed before it is rejected |
| `max_worker_calls`, `max_checker_calls` | Separate role call caps; zero checker calls is a valid conditional-review policy |
| `worker_luna_*_usd_per_million` | Luna worker reservation ceilings, initially $0.10 input / $0.50 output per million |
| `worker_*_usd_per_million` | Sol worker reservation ceilings, initially $2 input / $10 output per million |
| `worker_astra_*_usd_per_million` | Astra worker ceilings, initially $10 input / $50 output per million; usable only with explicit authorization |
| `checker_*_usd_per_million`, `jev_*_usd_per_million` | Separate checker and Jev reservation assumptions |

The five-unit worker catalog offers eight routes: GPT-6 Luna and Sol, each at low, medium, high, and xhigh. Jev chooses one before each generative unit; the exact choice is bound to the one-use dispatch permit and recorded with the accepted artifact. Jev reviews the result and may forward it after executable checks, request a separate GPT-6 Sol-high check, repair, escalate, retrieve evidence, or stop. The short branch fixes the worker at GPT-6 Luna low and has no Jev or checker call. The broad branch offers Jev only five units, evidence, or stop at entry. GPT-6 Sol xhigh remains available inside the five-unit graph for demanding general planning. GPT-5.6 and Terra are rejected. Astra low appears only with specific user authorization and `astra_explicitly_authorized: true`. The API runner reserves according to the chosen worker model's price ceiling. Model IDs and route availability depend on the provider and account.

The model IDs and effort levels are documented by [OpenAI's model catalog](https://developers.openai.com/api/docs/models). OpenRouter lists the [GPT-6 Sol](https://openrouter.ai/openai/gpt-6-sol) and [GPT-6 Luna](https://openrouter.ai/openai/gpt-6-luna) slugs used by this adapter. Check account access and the current provider route before a live run.

The key is read only from `OPENROUTER_API_KEY`. It is not a config value. Requests go to the adapter's fixed OpenRouter endpoints. Worker/checker requests prohibit provider fallback. Unexpected response identities fail closed. Usage fields absent from a response stay unknown, rather than being counted as zero. `adaptive_run.py` checks the host assertion's task/context hash; it does not validate the semantic classification. The host must reclassify every new input with carried context. `network_run.py` executes the five-unit path directly. These scripts accept a bounded structured-record task, not arbitrary project briefs.

Reservations use request bytes as a conservative input allowance and configured price ceilings. The worker reservation uses the exact Jev-selected model. No cached-input discount is assumed before the response; actual cached usage is recorded afterward. A CIDM worker reserves capacity for its following Jev decision. Before an optional checker starts, admission reserves a second call slot and enough budget for the checker plus its following Jev decision. A direct single-model baseline does not reserve an unnecessary Jev call. Reservations are local admission checks, not a guarantee of an upstream invoice. An actual charge above the reservation is recorded and blocks further calls. Cached-input and reasoning counters are subsets of input/output totals and are not added twice. Jev's output allowance is a budget reservation, not an API output cap. There are no automatic network retries. Service failure, unknown billing, or an invalid state can still halt before a Jev decision completes; it never authorizes forwarding.

## Extending an application

Replace the demonstration producer and validator with bounded task-specific implementations. Preserve the original evidence, explicit source IDs, context-aware input classification, five-unit order for broad work, the post-worker Jev decision in that graph, and the return to Jev after every optional checker call. Add executable acceptance checks wherever possible. Retrieve new evidence through an explicit adapter rather than inventing a retrieved result. Keep summarization traceable to its original sources.

Changing to a direct provider API or host-managed connector requires a new adapter and tests for identity, schema, usage, failure handling, and dispatch control. Do not claim that a connector is supported merely because a model is available in an interactive app.
