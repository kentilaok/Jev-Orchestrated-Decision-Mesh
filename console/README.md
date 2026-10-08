# Operator Console

Local, dependency-free UI for the Jev-Orchestrated Decision Mesh.

```bash
python scripts/operator_console.py
```

Then open `http://127.0.0.1:8765`. The page is a single file (`index.html`); the
server is `scripts/operator_console.py`. Preview needs nothing installed. A bounded
smoke test needs a signed-in Claude Code or Codex CLI. A live CIDM run also needs
`OPENROUTER_API_KEY` for Jev and an explicit spend confirmation.

`frontier-models.json` lists the console's convenience presets; account catalogues
(Codex) and the providers' own model pickers remain authoritative. See
[docs/OPERATOR-CONSOLE.md](../docs/OPERATOR-CONSOLE.md).
