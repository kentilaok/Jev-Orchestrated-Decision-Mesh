# CIDM retention and restore drill

**Purpose.** Keep an off-box copy of the state CIDM cannot regenerate (permit
ledgers, calibration, Fast Path, MCP catalogue, operator console settings,
saved sources), prove the snapshot restores to a scratch environment, and
set an explicit retention floor and ceiling.

## 1. What is backed up (and what is not)

**Included by default** (from `~/.jev/`):

| Path | Why it matters |
|---|---|
| `arsenal/arsenal.db` | Arsenal V1 SQLite — skills, lessons, calibration index |
| `arsenal/mcp.db` | MCP catalogue, trust gate state |
| `arsenal/calibration.jsonl` | Shadow calibration ledger |
| `arsenal/fast-path.jsonl` | Fast Path admission ledger |
| `arsenal/shadow.jsonl` | Native shadow observations |
| `operator-console.json` | Console config (Security knobs, provider defaults) |
| `sources/**` | Operator-saved sources |

**Opt-in** via `--include-runs`:

| Path | Why it is opt-in |
|---|---|
| `<repo>/runs/console-*/permits.jsonl` | Permit ledgers — audit trail. Large; include selectively |
| `<repo>/runs/console-*/result.json` | Per-run result snapshots |

**Excluded**:

| Path | Reason |
|---|---|
| `hermes-skills/` | Symlinks to the Hermes install; reproducible from Hermes |
| `arsenal/quarantine/**` | Third-party skill packages redownloadable from upstream |
| Secrets | None are stored on disk by CIDM; nothing to back up |

## 2. Retention policy

| Snapshot age | Action |
|---|---|
| 0–30 days | Keep every snapshot. The last 30 daily snapshots are the warm restore surface. |
| 30 days–1 year | Keep weekly (Sunday) snapshots; prune the rest. |
| > 1 year | Keep monthly (first Sunday) snapshots; prune the rest. |
| Any snapshot that failed restore verification | Keep for forensic review, mark with `.quarantine` suffix (manual). |

The script's `prune --older-than DAYS` enforces the first threshold. The
weekly / monthly thinning is a manual quarterly task; schedule a 10-minute
operator slot every three months to run it.

## 3. Where snapshots live

Default location: `~/.jev-backups/cidm-state-YYYY-MM-DDTHH-MM-SSZ.tar.gz`.
Treat this directory the same way as `~/.jev/`: hardened to the current user
via `python scripts/harden_jev_permissions.py --jev-root ~/.jev-backups`.

For off-box retention, copy the tarballs to:

- A separate physical drive you own, OR
- A private cloud bucket you control (no shared buckets, no vendor
  telemetry), OR
- Encrypted removable media.

Do not push snapshots to a public bucket, a shared drive, or any location
where the operator-console.json's Hermes dashboard URL would be exposed.

## 4. Routine (daily / 2 min)

1. Close the Operator Console if it is running (so `arsenal.db` and
   `mcp.db` are not mid-write).
2. `python scripts/backup_jev_state.py snapshot`
3. Copy the resulting `.tar.gz` to the off-box location.

The script prints a JSON summary with the snapshot path, file count, and
host. Save that summary in your retention log (plain text file, one line
per snapshot is enough).

## 5. Restore drill (monthly / 10 min)

Run this once a month against the most recent snapshot. The drill proves
the snapshot is actually restorable — not just that the file exists.

```powershell
# Pick the latest snapshot.
python scripts/backup_jev_state.py list

# Restore into a scratch directory (NOT ~/.jev).
$scratch = "D:\restore-test\$(Get-Date -Format yyyyMMdd)"
python scripts/backup_jev_state.py restore `
    "$HOME\.jev-backups\cidm-state-LATEST.tar.gz" --to $scratch

# Confirm the restore report says ok=true. If mismatched or missing has
# any entries, the snapshot is corrupt — mark it .quarantine and re-run
# the drill against the previous snapshot before trusting it.
```

Open the scratch directory and spot-check that the files you expect are
there (`operator-console.json`, `arsenal/arsenal.db`, the calibration
ledger). The drill is a success only if the report prints `"ok": true`
and the ledgers look sane under inspection.

Delete the scratch directory when the drill is done. Do not point CIDM at
a restored tree unless you are deliberately recovering from a loss.

## 6. Recovery from loss

If `~/.jev/` is corrupted or lost:

1. Stop the Operator Console.
2. Rename the broken `~/.jev/` to `~/.jev-broken-<timestamp>/` (do not
   delete — keep for forensics).
3. Restore the most recent snapshot that passed the monthly drill into a
   staging directory.
4. Verify ledgers manually: open the permit ledger of the last known-good
   run, confirm the hash chain is intact (`python -c "from
   capability_permits import HashChainLedger; HashChainLedger('path').read()"`).
5. Move the staging directory to `~/.jev/`.
6. Re-run `python scripts/harden_jev_permissions.py` so ACLs are tight on
   the restored tree.
7. Start the Operator Console. The `cumulative_cost_usd` on each permit
   ledger will replay from the restored receipts; any live run that was
   mid-flight when the loss happened is lost and must be re-launched.

## 7. Rotation of operator credentials

CIDM does not store API keys or OAuth tokens on disk. Credentials live in:

- `OPENROUTER_API_KEY` (environment variable, Jev-side only)
- Claude Code CLI's own keychain / token store
- Codex CLI's own keychain / token store

**Rotation is independent of CIDM backups.** When you rotate any of the
above, update the environment or the CLI; CIDM state does not need to
change. The permit ledgers continue to be valid because they bind to
hashes of request shape, not to the credentials that performed the call.

## 8. What the restore drill proves

If this drill passes every month, you can claim with evidence:

- Snapshots are restorable.
- The ledger hash chain survives the round trip.
- You can get a scratch environment up without a live-run or external
  dependency.

If the drill fails for two consecutive months on different snapshots, the
backup pipeline itself is broken — stop taking new snapshots until the
root cause is understood, because an untested backup is worse than none.

*CIDM architecture and research by Ken Caber (Kenneth Vic A. Caber).*
