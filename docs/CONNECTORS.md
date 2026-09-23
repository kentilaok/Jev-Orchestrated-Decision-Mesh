# Models, configuration, and connectors

CIDM calls existing models at inference time. Only the OpenRouter adapter is implemented. ChatGPT or Codex browser login does not supply API authentication or API credits.

## Current interfaces

`scripts/transport.py` defines two Python protocols:

- `DecisionAdapter.network_judge(phase, options, state)` supplies Jev's predefined choice and metadata.
- `GenerativeAdapter.ask(role, instructions, state, schema)` produces a structured worker artifact; `high_check(state)` produces the separate checker report.

`Gateway` implements both protocols and records calls, usage, cost, latency, model identity, and configuration hash. `CheckedNetwork` receives judge, producer, checker, and validator callbacks; this is the application integration boundary. Protocol declarations do not automatically install another connector. A replacement needs an implementation, explicit wiring, and equivalent contract/accounting tests.

Jev chooses among finite options and supplies decision metadata. It does not write prose summaries. A worker or deterministic code builds the next artifact. The broker decides which validated evidence reaches the next unit.

## Configuration

`examples/config.openrouter.json` is the complete default configuration. `scripts/config.py` rejects unknown fields, including secret-bearing fields, and freezes validated settings for the run.

| Fields | Purpose |
|---|---|
| `worker_model`, `worker_effort` | Explicit OpenAI model ID and low/medium/high/xhigh effort |
| `checker_model`, `checker_effort` | Explicit OpenAI model ID; checker effort must remain high |
| `jev_model` | Versioned TypeSafe Jev model ID |
| `provider_route`, `provider_name` | OpenRouter route slug and expected returned provider name |
| `jev_provider_name` | Expected Jev provider name when the response supplies one |
| `*_model_aliases` | Explicit accepted version aliases; no arbitrary fallback |
| `max_usd`, `max_calls`, `max_output_tokens`, `timeout` | Budget, number of attempts, worker/checker output cap, per-call timeout |
| `*_input_usd_per_million`, `*_output_usd_per_million` | Conservative reservation assumptions per role; not a current price catalog |

The default worker is Sol medium; the checker is Sol high. This release fixes those roles for a run. Automatic selection of the cheapest adequate model/effort across Terra, Sol, and Astra remains future work requiring evaluation; changing config manually is supported. Model IDs and route availability depend on the provider and account.

The key is read only from `OPENROUTER_API_KEY`. It is not a config value. Requests go to the adapter's fixed OpenRouter endpoints. Worker/checker requests prohibit provider fallback. Unexpected response identities fail closed. Usage fields absent from a response stay unknown, rather than being counted as zero.

Reservations use request bytes as a conservative input allowance and configured price ceilings. Before a checker starts, admission reserves two call slots and enough budget for both the checker and a maximum-size following Jev request. They are local admission checks, not a guarantee of an upstream invoice. An actual charge above the reservation is recorded and blocks further calls. Cached-input and reasoning counters are subsets of input/output totals and are not added twice. Jev's output allowance is a budget reservation, not an API output cap. There are no automatic network retries. Service failure, unknown billing, or an invalid state can still halt before a Jev decision completes; no unchecked transition is released.

## Extending an application

Replace the demonstration producer and validator with bounded task-specific implementations. Preserve the original evidence, explicit source IDs, five-unit order, and post-checker Jev return path. Add executable acceptance checks wherever possible. Retrieve new evidence through an explicit adapter rather than inventing a retrieved result. Keep summarization traceable to its original sources.

Changing to a direct provider API or host-managed connector requires a new adapter and tests for identity, schema, usage, failure handling, and dispatch control. Do not claim that a connector is supported merely because a model is available in an interactive app.
