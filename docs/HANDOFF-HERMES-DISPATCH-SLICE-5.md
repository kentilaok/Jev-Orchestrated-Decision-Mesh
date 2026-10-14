# Handoff — Hermes dispatch adapter, slice 5 (14 October 2026)

**Branch:** `feature/hermes-dispatch-adapter`.
**Parent gate:** [P0-04 Governed Hermes integration](PRODUCTION-REQUIREMENTS-HANDOFF-2026-10-08.md). Fifth of six slices.
**Evidence level:** offline tests + one real Hermes config.yaml edit (reversible). No model calls.

## 1. What this slice delivers

The Hermes side of the dispatch adapter. A new, reversible, idempotent installer registers CIDM as a Hermes `custom provider` so `hermes chat --model cidm-jev` routes every turn through the local CIDM broker.

- `scripts/install_hermes_cidm_provider.py`: new script with `--install` (default), `--uninstall`, `--dry-run`, `--target <path>`.
- Writes a marked block (`# BEGIN cidm-provider … # END cidm-provider`) to the user's Hermes `config.yaml`.
- Always creates a timestamped backup (`config.yaml.bak-cidm-<ts>`) before any change.
- Re-running replaces the previous marked block in place. Running on an unchanged target reports no change.
- Refuses to run when the user already has an *active* top-level `providers:` block in their YAML, since silently merging into user YAML without a parser is unsafe. In that case the installer prints the exact text to append and exits non-zero.
- CIDM project policy keeps the toolchain stdlib-only; this installer deliberately does not import PyYAML.
- Reversible: `--uninstall` removes the marked block and makes a fresh backup.

**Registered block (what Hermes will see):**

```yaml
providers:
  cidm:
    base_url: "http://127.0.0.1:8765/v1"
    key_env: "CIDM_API_KEY"
    api_mode: chat_completions
    model: cidm-jev
    streaming: true
```

## 2. Code changes

| File | Change |
|---|---|
| `scripts/install_hermes_cidm_provider.py` | New, 155 lines. Public API: `render_block()`, `install(path, dry_run=False)`, `uninstall(path, dry_run=False)`, `InstallerError`. Private: marker constants, `_has_managed_block`, `_strip_managed_block`, `_has_active_providers_block`, `_make_backup`, `default_target`. CLI: `main(argv=None)`. |
| `tests/test_install_hermes_cidm_provider.py` | New, 125 lines. Eight tests: render contents + markers; install creates backup + writes block + preserves seed; install is idempotent; install replaces an outdated marked block; uninstall removes block but keeps seed; uninstall on absent block is a noop; dry-run writes nothing; install refuses when an active `providers:` block already exists. |

## 3. Verification

| Check | Result |
|---|---|
| Slice-5 unit tests | 8/8 pass |
| Full offline suite | 366/366 pass, 1 opt-in Docker skip |
| Regressions on 358-test post-slice-4 baseline | 0 |
| Dry-run against the real Hermes config | `would_change=True` reported, no file written |
| Real install against `%LOCALAPPDATA%\hermes\config.yaml` | Backup `config.yaml.bak-cidm-20261014155609` created; `providers.cidm` block written at lines 2333–2341 |
| Re-run of installer against the installed config | `changed=False` (idempotent) |
| Live model calls | None |

## 4. How to try it end-to-end

Terminal A — start the CIDM broker:

```powershell
Set-Location 'D:\Hermes Jev CIDM'
$env:CIDM_API_KEY = 'local-dev-key'
python scripts/operator_console.py
```

Terminal B — point Hermes at it (the broker must have the same env var):

```powershell
$env:CIDM_API_KEY = 'local-dev-key'
hermes chat --model cidm-jev
```

Hermes will stream the broker's status chunks (`[CIDM] starting`, `[CIDM] validating…`, `[CIDM] plan ready`) then the plan summary. Strong requests (containing destructive verbs or `cidm_strong: true`) produce an approval URL you open in the Operator Console.

## 5. Rollback

```powershell
python scripts/install_hermes_cidm_provider.py --uninstall
```

Or restore from the backup file:

```powershell
Copy-Item -Force 'C:\Users\Ken\AppData\Local\hermes\config.yaml.bak-cidm-20261014155609' 'C:\Users\Ken\AppData\Local\hermes\config.yaml'
```

## 6. Open items for the next (final) slice

1. **Adversarial pass tests (P0-04 pass condition).** Prove that an ordinary Hermes conversation that does *not* select `cidm-jev` cannot reach the broker; prove that the dashboard API cannot bypass; prove that an unapproved strong request cannot execute as a normal one.
2. **Full operator-facing documentation** `docs/HERMES-DISPATCH-ADAPTER.md`: architecture diagram, install/uninstall, auth, approval flow, troubleshooting, known limitations.
3. **Reviewer rubric** against P0-04's pass condition before opening the PR for merge to `main`.

## 7. Pass/hold decision for this slice

- `scope`: internal milestone, not a release
- `decision`: **PASS pending independent QA**. Review runs after push.
- `next action`: QA review of slice 5 commit, then slice 6.

*CIDM architecture and research by Ken Caber (Kenneth Vic A. Caber).*
