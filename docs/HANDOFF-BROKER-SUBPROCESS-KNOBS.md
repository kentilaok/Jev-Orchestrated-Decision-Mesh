# Handoff — Broker subprocess knob threading (15 October 2026)

**Branch:** `feature/broker-subprocess-knobs`, based on `main` at `1474d2c`.
**Parent gate:** P0-05 follow-up — threads `content_policy` and `require_action_approval` from the Operator Console state all the way through the broker subprocess to `McpEvidenceRetriever` and the inner `call_tool` sites.
**Evidence level:** offline tests only. No model calls.

## 1. What this slice delivers

Three touchpoints updated in one slice because the semantic is one knob reaching one call site through three hops:

1. **`McpEvidenceRetriever.__init__`** — accepts `content_policy='off'|'audit'|'wrap'` and `require_action_approval=False`. Validated at construction; stored on `self`. Each `call_tool` invocation forwards both.
2. **`native_transition_broker.py` CLI** — `_build_cli_parser()` extracted for testability. New flags `--content-policy {off,audit,wrap}` (default `off`) and `--require-action-approval` (store_true). Threaded into the `McpEvidenceRetriever` constructor at the one broker site that builds it.
3. **Operator Console `broker_argv`** — new optional `config` kwarg. When passed, non-default `content_policy` and `require_action_approval=True` are appended to the subprocess argv.

The chain: operator sets knobs in `/api/config` → `start_broker_job` / `validate_broker_request` can pass `config=…` → `broker_argv` emits `--content-policy wrap --require-action-approval` → `native_transition_broker.py main()` parses → `McpEvidenceRetriever(content_policy=…, require_action_approval=…)` → `call_tool(…, content_policy=…, require_action_approval=…)`.

**Note:** this slice adds the `config` kwarg to `broker_argv` but does **not** change the Operator Console's existing call sites to pass it. That one-line follow-up is left for a future slice (keeps blast radius small; `broker_argv(config=None)` is backward-compat).

## 2. Code changes

| File | Change |
|---|---|
| `scripts/mcp_registry.py` | +9 lines. `McpEvidenceRetriever.__init__` grows the two kwargs, validates `content_policy`, stores, forwards to `call_tool`. |
| `scripts/native_transition_broker.py` | +14 lines. Extracted `_build_cli_parser`; new `--content-policy` and `--require-action-approval` flags; threads both into the one `McpEvidenceRetriever` construction. |
| `scripts/operator_console.py` | +8 lines. `broker_argv` grows a `config: dict \| None = None` kwarg; appends the flags when non-default. |
| `tests/test_broker_subprocess_knobs.py` | New, 125 lines. Eight tests across three classes: `broker_argv` (3) default omit, wrap added, approval added; broker CLI (2) parses both flags, defaults match backward-compat; retriever (3) stores knobs, defaults, invalid policy raises. |

## 3. Verification

| Check | Result |
|---|---|
| Subprocess-knob tests | 8/8 pass |
| Full offline suite | 526/526 pass, 1 opt-in Docker skip |
| Regressions on 518-test post-PR#14 baseline | 0 |
| `python -m compileall -q scripts tests` | pass |
| Live model calls | None |

## 4. Open items

1. **Wire `config=…` into Console call sites of `broker_argv`.** `start_broker_job`, `validate_broker_request`, `start_resume_job` each call `broker_argv(…)` without `config=cfg`. One-line follow-up per site.
2. **HTML binding** on `console/index.html`.
3. **Approval record provenance** — Jev-signed evidence.
4. **P0-01 CI** — your billing banner.

## 5. Decision

- `scope`: follow-up PR; makes the content/approval knobs survive the subprocess boundary.
- `decision`: **PASS pending QA**; PR against `main` after QA.

*CIDM architecture and research by Ken Caber (Kenneth Vic A. Caber).*
