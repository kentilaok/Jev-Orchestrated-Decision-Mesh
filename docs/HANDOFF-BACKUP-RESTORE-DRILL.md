# Handoff — Retention/backup playbook + restore drill (15 October 2026)

**Branch:** `feature/backup-restore-drill`, based on `main` at `318a336`.
**Parent gate:** P0-06 slice 4 — "Establish retention periods and an access-controlled backup for permit, calibration, checkpoint and run evidence. Restore from backup in a scratch environment" from the production handoff.
**Evidence level:** offline tests only. The real restore drill runs monthly on the operator workstation.

## 1. What this slice delivers

Two artefacts: a snapshot/restore script that captures the state CIDM cannot regenerate, and an operator playbook that spells out retention thresholds plus a monthly restore drill the operator can execute without consulting this code.

- **`scripts/backup_jev_state.py`** — stdlib-only snapshot tool with four subcommands (`snapshot`, `restore`, `list`, `prune`). A snapshot is a `.tar.gz` with an embedded `MANIFEST.json` carrying a SHA-256 for every included file; restore extracts to a scratch directory and verifies each file against the manifest, so corruption or tampering is caught before the operator trusts the backup.
- **`docs/BACKUP-RESTORE-DRILL.md`** — the playbook: what gets backed up (ledgers, calibration, Fast Path, MCP DB, Console config, saved sources), what is excluded by default (`hermes-skills/`, `arsenal/quarantine/`, repo `runs/`), where snapshots live, retention thresholds (30-day daily, then weekly to 1yr, then monthly), the monthly restore drill, recovery-from-loss procedure, and the rotation policy (CIDM stores no on-disk credentials; rotation is independent of these backups).

Design calls locked in:

- Default jev root: `~/.jev`. Default snapshot root: `~/.jev-backups`.
- `hermes-skills/` and `arsenal/quarantine/` excluded by default (symlinks + redownloadable third-party packages).
- `<repo>/runs/` is opt-in via `--include-runs` (large, ephemeral; operator picks when it's worth bundling).
- Prune parses the operator-supplied timestamp from the filename (`cidm-state-<ISO>.tar.gz`), not file `mtime`, so backdated test snapshots and copied-around tarballs still prune honestly.
- Restore refuses path-traversal entries (`..`, absolute paths) with `ValueError("unsafe_archive_entry:<name>")`.
- Restore returns a report dict (`ok`, `manifest`, `mismatched`, `missing`) rather than raising on mismatch, so the CLI can surface a clean exit code (0 ok / 2 corrupt) and the operator sees the specific files that failed verification.

## 2. Code changes

| File | Change |
|---|---|
| `scripts/backup_jev_state.py` | New, 231 lines. Pure stdlib. Functions: `_file_digest`, `_is_excluded_jev_path`, `_collect_paths`, `_manifest`, `_now_token`, `snapshot`, `_safe_name`, `restore`, `list_snapshots`, `_snapshot_timestamp`, `prune`, `main`. |
| `tests/test_backup_restore.py` | New, 268 lines, 13 tests across eight classes. Collect-paths exclusion rules; manifest SHA-256 fidelity; snapshot creation + sort-by-timestamp; round-trip restore (byte-identical); tamper detection on restore; path-traversal rejection on restore; list sorted newest-first; prune honours threshold + dry-run; CLI subcommand round trip. |
| `docs/BACKUP-RESTORE-DRILL.md` | New playbook. |
| `docs/HANDOFF-BACKUP-RESTORE-DRILL.md` | This handoff. |

## 3. Verification

| Check | Result |
|---|---|
| Slice tests | 13/13 pass |
| Full offline suite | 626/626 pass, 1 opt-in Docker skip + 3 POSIX-only skips on this Windows box |
| Regressions on 613-test post-PR#23 baseline | 0 |
| `python -m compileall -q scripts tests` | pass |
| Live model calls | None |

## 4. Design decisions I want to call out for review

- **No encryption at rest.** The snapshots carry no credentials (CIDM stores none on disk) and no customer data, so I left encryption to the operator's off-box destination choice. If a snapshot is copied into a shared location this changes — the playbook names that explicitly. Flag if you want encryption baked into the tool.
- **Prune by filename token, not `mtime`.** I chose this because `mtime` rotates when a tarball is copied or restored, which makes "age" lie. The filename token is operator-controlled and stable. The trade-off is that a filename not matching the convention is never pruned; non-snapshot files are left alone which is the right default.
- **Restore to scratch only.** The script will not overwrite `~/.jev/` directly even if told. The operator does the staging + move + rehardening manually. This is deliberately conservative: a bad restore wiping live state is worse than a restore that stops short.
- **Monthly restore drill is operator work, not CI.** Running a real restore in CI would need a seeded `~/.jev/`; the slice tests already prove the restore mechanism, so the monthly drill is specifically about catching off-box pipeline rot (bad bucket perms, cosmic-ray bit-flip on removable media, etc.).

## 5. Operator action (~15 min, first time)

1. Create `~/.jev-backups/`:
   ```powershell
   mkdir "$HOME\.jev-backups"
   python scripts/harden_jev_permissions.py --jev-root "$HOME\.jev-backups"
   ```
2. Take the first snapshot and confirm the JSON report:
   ```powershell
   python scripts/backup_jev_state.py snapshot
   ```
3. Run the monthly restore drill from `docs/BACKUP-RESTORE-DRILL.md` §5 against that snapshot. If it reports `"ok": true`, you have a baseline. If not, fix the pipeline before taking another snapshot — an untested backup is worse than none.
4. Decide an off-box destination (separate drive / private bucket / encrypted removable media) and set up a copy step.

## 6. Open items (P0-06 remaining)

- **Slice 2d:** Console UI for `max_cumulative_usd` — still needs Console → `RunConfig` override wiring.
- **Operator work (not a slice):** dedicated OS account for the Jev operator role.
- **Live-run (P0-03) prereq:** decide whether Codex should be priced from `RunConfig` ceilings so cumulative tracking stays honest when Codex is primary worker.

With PR #23 closing the OTLP bullet and this slice closing the retention/restore bullet, the script-side P0-06 work is complete.

## 7. Decision

- `scope`: P0-06 slice 4.
- `decision`: **PASS pending QA**; PR against `main` after QA.

*CIDM architecture and research by Ken Caber (Kenneth Vic A. Caber).*
