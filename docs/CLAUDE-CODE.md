# Running CIDM in Claude Code (Sonnet and Opus)

CIDM supports two worker families. The unit graph, Jev gates, permits, checks and audits are identical; only the worker catalogue and host differ.

| | GPT-6 family (default) | Claude family |
|---|---|---|
| Host | Codex (interactive) or `codex exec` broker | Claude Code (interactive) or `claude -p` broker |
| Worker routes Jev may choose | `luna_*`, `sol_*` × low/medium/high/xhigh | `sonnet_*`, `opus_*` × low/medium/high/xhigh |
| Models | `openai/gpt-6-luna`, `openai/gpt-6-sol` | `anthropic/claude-sonnet-5`, `anthropic/claude-opus-5` |
| Short self-contained path | one Luna low | one Sonnet low |
| Optional separate checker (`check_sol_high` option id) | Sol high | Opus high |
| Config | `worker_family: "gpt6"` | `worker_family: "claude"` |

Jev is unchanged in both families: it is a separate TypeSafe decision service called through `scripts/jev_decide.py` (or the broker), with its own API credential. Claude does not replace Jev, and Jev does not replace a Claude worker.

The option id `check_sol_high` is kept on both families so saved traces and audits stay comparable; on the Claude family it dispatches the Opus-high checker.

## Install

Claude Code reads skills from `~/.claude/skills/<name>/SKILL.md` (personal) or `.claude/skills/<name>/SKILL.md` (project), and subagents from `~/.claude/agents/` or `.claude/agents/`.

```bash
# personal install (use a separate name if you want it beside an existing copy)
cp -r <repo> ~/.claude/skills/caber-interstitial-decision-mesh
cp <repo>/claude/agents/*.md ~/.claude/agents/
```

The three subagents pin their model in frontmatter:

| Subagent | `model` | Use |
|---|---|---|
| `cidm-worker-sonnet` | `sonnet` | Jev chose a `sonnet_*` route, or the short path |
| `cidm-worker-opus` | `opus` | Jev chose an `opus_*` route |
| `cidm-checker-opus` | `opus` | Jev chose `check_sol_high` |

All three have read-only tools (`Read`, `Grep`, `Glob`) and return the same structured artifact as the Codex workers.

## Interactive procedure (Claude Code as host)

Follow `SKILL.md` exactly as on Codex, with these substitutions:

1. Offer Jev the Claude catalogue (`sonnet_low` … `opus_xhigh`), not GPT-6 routes.
2. Dispatch the chosen route to the matching subagent. The subagent's `model` alias selects Sonnet or Opus; **effort is not settable per subagent**, so record the requested effort and mark `confirmed_effort: unavailable`.
3. The host (the main Claude Code model) is unmetered by CIDM, exactly like the Codex primary agent. Work done by the host, including anything labelled "deterministic" that involves reading, interpreting, writing code or writing prose, is model work: record its usage as unknown, never as zero.

## Controlled route (headless broker)

`scripts/native_transition_broker.py --host claude` runs each worker and checker as one `claude -p` child:

```
claude -p --output-format json --model <claude-sonnet-5|claude-opus-5> --effort <low|medium|high|xhigh>
       --tools "" --strict-mcp-config --no-session-persistence --json-schema <artifact schema>
```

```bash
python scripts/native_transition_broker.py --validate-only --host claude --task examples/native-project.request.json
python scripts/native_transition_broker.py --live --host claude --task examples/native-project.request.json --out runs/claude-001
```

`--live` uses your Claude Code sign-in (plan usage, or API billing if Claude Code is signed in with an API key) plus separately billed Jev calls. It has not been run in this repository.

Compared with the Codex adapter, `scripts/claude_cli_adapter.py`:

- **Confirms the served model** from the CLI's per-model usage report. A mismatch fails the call; auxiliary models are recorded.
- **Normalises Anthropic usage.** Anthropic reports `input_tokens`, `cache_creation_input_tokens` and `cache_read_input_tokens` separately. The adapter returns `input_tokens` as their sum, with cache reads and writes as subsets, so they are never added twice.
- **Labels cost honestly.** It returns the CLI's `total_cost_usd` as `api_equivalent_cost_usd`. Under a subscription this is an estimate, not a bill.
- **Keeps reported usage on rejection.** When a completed call's output is rejected (schema mismatch, error result, identity conflict), the usage stays attached to the error.
- **Never confirms effort.** Effort is not reported back, so it remains requested-only.

The OpenRouter runners (`network_run.py`, `adaptive_run.py --live`, `compare_baseline.py`) stay GPT-6 only. The gateway refuses Claude worker and checker calls, so no Claude API spend path exists there.

## Verify offline

```bash
python -m unittest tests.test_claude_host -v
```
