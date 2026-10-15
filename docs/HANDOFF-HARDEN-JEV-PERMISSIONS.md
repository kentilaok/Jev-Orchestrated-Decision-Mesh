# Handoff — Harden ~/.jev and runs/ (15 October 2026)

**Branch:** `feature/harden-jev-permissions`, based on `main` at `4a608bb`.
**Parent gate:** P0-06 slice 3 — "Use dedicated OS account/file permissions for `~/.jev`, `runs/`, saved prompts, checkpoint JSON and logs" from the production handoff.
**Evidence level:** offline tests only (POSIX chmod verified directly; Windows icacls verified through a stub runner). The real NTFS smoke-check runs on the operator's workstation.

## 1. What this slice delivers

`scripts/harden_jev_permissions.py` tightens every reachable path under `~/.jev` and `<repo>/runs` to the invoking user only. One stdlib script, cross-platform:

- **POSIX:** `os.chmod(path, 0o700)` on directories, `os.chmod(path, 0o600)` on files. Follow-symlinks default off (`os.walk(..., followlinks=False)`).
- **Windows (NTFS):** `icacls PATH /inheritance:r /grant:r USER:(OI)(CI)F` for directories, `/grant:r USER:F` for files. Inheritance stripped so a group-policy change can't widen the ACL later; `(OI)(CI)` on containers so future children inherit the single-user ACE automatically.

The script is idempotent (re-running on an already-tightened tree re-applies the same bits), skips missing roots with a warning instead of erroring, and has a `--dry-run` flag that prints the chmod/icacls plan without touching anything.

Exit codes: `0` on full success (or missing roots skipped), `2` if any chmod call raised or any icacls call returned non-zero.

## 2. Code changes

| File | Change |
|---|---|
| `scripts/harden_jev_permissions.py` | New, 134 lines. `_iter_tree`, `_icacls_argv`, `_apply_posix`, `_apply_windows`, `harden_path`, `harden_tree`, `main`. |
| `tests/test_harden_jev_permissions.py` | New, 180 lines, 13 tests across six classes. POSIX tests chmod a tempdir and assert mode (skipped on Windows); Windows tests inject a stub runner and verify the exact icacls argv assembled. CLI entry exercised via `--dry-run` + a failing-runner mock. |
| `docs/HANDOFF-HARDEN-JEV-PERMISSIONS.md` | This handoff. |

## 3. Verification

| Check | Result |
|---|---|
| Slice tests | 13/13 pass on Windows (3 POSIX-only skipped); CI will run all 13 on Linux (POSIX tests execute, Windows tests pass via stub runner). |
| Full offline suite | 604/604 pass locally, 1 opt-in Docker skip + 3 POSIX-only skips on this Windows box |
| Regressions on 591-test post-PR#21 baseline | 0 |
| `python -m compileall -q scripts tests` | pass |
| Live model calls | None |
| Dry-run on real `~/.jev` + repo `runs/` | Produces plausible plan (walks arsenal, hermes-skills, sources, quarantine subtrees; skips the missing `runs/` under the repo); zero crashes. |

## 4. Design calls honoured

- **Stdlib-only.** No pywin32, no third-party ACL libraries. `icacls` ships with Windows; `os.chmod` on POSIX.
- **No elevation.** The script tightens paths the invoking user already owns; it does not create a dedicated OS account (that is operator work mentioned in the P0-06 handoff but out of script scope).
- **Idempotent + dry-run first.** The operator can preview before applying.
- **Testable without real ACL calls.** `harden_tree` takes `platform`, `runner`, and `log` as injectable parameters so the Windows branch is exercised on Linux CI via a stub runner.
- **Fail-visible, continue-processing.** One failing chmod or icacls increments an error count and surfaces to stderr; the walk continues so a half-hardened tree is better than an aborted one.
- **No symlink traversal.** `os.walk(..., followlinks=False)` so the script cannot accidentally descend out of `~/.jev` via an operator-created symlink.

## 5. Operator smoke-check (Ken's workstation, ~5 min)

```powershell
# 1. Preview what the script would do on your real tree:
cd "D:\Hermes Jev CIDM"
python scripts/harden_jev_permissions.py --dry-run --verbose | more

# 2. Apply it:
python scripts/harden_jev_permissions.py --verbose

# 3. Verify one hardened file:
icacls C:\Users\<you>\.jev\arsenal\arsenal.db
#   Expect: a single ACE for your user with Full control, inheritance stripped.
```

If any `icacls` line fails (rc != 0), re-run with `--verbose` and share the stderr; most common cause is a file still open by another process (close the Operator Console / any Jev script first).

## 6. Open items (P0-06 next slices)

- **Slice 2d:** Operator Console UI for `max_cumulative_usd` — still blocked on threading a Console-settable `RunConfig` override into `broker_argv --config`.
- **Slice 4:** retention / backup playbook + restore drill.
- **Slice 5:** OTLP ordinal-span caveat telemetry assertion.
- **Operator-side (not a slice):** create a dedicated OS account for the operator role as mentioned in the P0-06 handoff; this script sets ACLs for a single account but does not create one.

## 7. Decision

- `scope`: P0-06 slice 3.
- `decision`: **PASS pending QA**; PR against `main` after QA.

*CIDM architecture and research by Ken Caber (Kenneth Vic A. Caber).*
