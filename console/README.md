# Operator Console

Local UI for the Jev-Orchestrated Decision Mesh.

## Start

```bash
python scripts/operator_console.py
```

Then open `http://127.0.0.1:8765`.

Preview mode works without Hermes. Live execution requires Hermes in `PATH` and a configured Anthropic credential path.

## Design

```text
Jev → Hermes → selected Claude model → validators → Jev
```

Anthropic is the only enabled provider in v1. Edit `frontier-models.json` to change the allow-listed Claude models. See `docs/OPERATOR-CONSOLE.md` for architecture, security boundaries and the roadmap to a governed `HermesGenerativeAdapter`.
