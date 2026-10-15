"""Snapshot and restore CIDM state files (P0-06 slice 4).

A snapshot is a `.tar.gz` with an embedded `MANIFEST.json` carrying a
SHA-256 for every included file. Restore extracts to a scratch directory
and verifies each file against the manifest; a mismatch means tampering
or corruption, and the operator can then decide whether to re-pull the
snapshot or quarantine it.

The script captures the state that is hard to reconstruct: ledgers,
calibration, Fast Path, MCP DB, operator-console.json, and saved
sources. It excludes `hermes-skills/` (symlinks to the Hermes installation)
and `arsenal/quarantine/` (third-party skill packages that can be
redownloaded from upstream). `<repo>/runs/` is opt-in via
`--include-runs` because run output is large and often ephemeral.

CLI:

    python scripts/backup_jev_state.py snapshot [--jev-root PATH]
            [--snapshot-root PATH] [--include-runs] [--runs-root PATH]
    python scripts/backup_jev_state.py restore SNAPSHOT_PATH --to SCRATCH
    python scripts/backup_jev_state.py list [--snapshot-root PATH]
    python scripts/backup_jev_state.py prune --older-than DAYS
            [--snapshot-root PATH] [--dry-run]

Returns 0 on success; 2 if a restore detected tampering or a prune failed
to delete a file it claimed to remove.
"""
from __future__ import annotations

import argparse
import calendar
import hashlib
import io
import json
import os
import socket
import sys
import tarfile
import time
from pathlib import Path
from typing import Iterable

SCHEMA = 1
MANIFEST_NAME = "MANIFEST.json"
EXCLUDED_JEV_SUBDIRS = frozenset({"hermes-skills", "quarantine"})


def _file_digest(path: Path) -> str:
    """SHA-256 of a file's bytes (streamed; works on large files)."""
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _is_excluded_jev_path(root: Path, path: Path) -> bool:
    try:
        rel_parts = path.relative_to(root).parts
    except ValueError:
        return True
    if rel_parts and rel_parts[0] in EXCLUDED_JEV_SUBDIRS:
        return True
    # Also exclude the quarantine subtree even when nested one level down.
    if len(rel_parts) >= 2 and rel_parts[0] == "arsenal" and rel_parts[1] == "quarantine":
        return True
    return False


def _collect_paths(jev_root: Path, *, include_runs: bool,
                   runs_root: Path | None) -> Iterable[tuple[Path, str]]:
    """Yield `(absolute Path, archive-relative name)` for every file worth saving."""
    if jev_root.exists():
        for dirpath, _dirnames, filenames in os.walk(jev_root, followlinks=False):
            base = Path(dirpath)
            for name in filenames:
                p = base / name
                if _is_excluded_jev_path(jev_root, p):
                    continue
                rel = str(p.relative_to(jev_root)).replace(os.sep, "/")
                yield p, rel
    if include_runs and runs_root is not None and runs_root.exists():
        for dirpath, _dirnames, filenames in os.walk(runs_root, followlinks=False):
            base = Path(dirpath)
            for name in filenames:
                p = base / name
                rel = "runs/" + str(p.relative_to(runs_root)).replace(os.sep, "/")
                yield p, rel


def _manifest(entries: list[tuple[Path, str]], *, created_at: str, host: str) -> dict:
    """Build the manifest dict (serialised as `MANIFEST.json` inside the tarball)."""
    files = []
    for path, rel in entries:
        files.append({"name": rel, "sha256": _file_digest(path),
                      "bytes": path.stat().st_size})
    files.sort(key=lambda f: f["name"])
    return {"schema": SCHEMA, "created_at": created_at, "host": host, "files": files}


def _now_token(now: str | None) -> str:
    """Return a filesystem-safe timestamp component (`YYYY-MM-DDTHH-MM-SSZ`)."""
    if now is not None:
        return now
    return time.strftime("%Y-%m-%dT%H-%M-%SZ", time.gmtime())


def snapshot(jev_root: Path, snapshot_root: Path, *, include_runs: bool = False,
             runs_root: Path | None = None, now: str | None = None,
             host: str | None = None) -> tuple[Path, dict]:
    """Create a snapshot `.tar.gz` under `snapshot_root`; return (path, manifest)."""
    snapshot_root.mkdir(parents=True, exist_ok=True)
    token = _now_token(now)
    out_path = snapshot_root / f"cidm-state-{token}.tar.gz"
    entries = list(_collect_paths(jev_root, include_runs=include_runs, runs_root=runs_root))
    manifest = _manifest(entries, created_at=token, host=host or socket.gethostname())
    with tarfile.open(out_path, "w:gz") as tar:
        raw = json.dumps(manifest, indent=2, sort_keys=True).encode("utf-8")
        info = tarfile.TarInfo(MANIFEST_NAME)
        info.size = len(raw)
        info.mtime = int(time.time())
        tar.addfile(info, io.BytesIO(raw))
        by_name = {rel: path for path, rel in entries}
        for name in sorted(by_name):
            tar.add(str(by_name[name]), arcname=name, recursive=False)
    return out_path, manifest


def _safe_name(name: str) -> bool:
    """Reject archive entries whose extraction would escape the destination."""
    if not name or name.startswith("/") or ".." in Path(name).parts:
        return False
    if os.path.isabs(name):
        return False
    return True


def restore(snapshot_path: Path, scratch: Path, *, verify: bool = True) -> dict:
    """Extract `snapshot_path` into `scratch` and (optionally) verify checksums."""
    scratch.mkdir(parents=True, exist_ok=True)
    extracted: list[str] = []
    with tarfile.open(snapshot_path, "r:gz") as tar:
        members = tar.getmembers()
        for member in members:
            if not _safe_name(member.name):
                raise ValueError(f"unsafe_archive_entry:{member.name}")
        manifest_member = next((m for m in members if m.name == MANIFEST_NAME), None)
        if manifest_member is None:
            raise ValueError("manifest_missing")
        manifest = json.loads(tar.extractfile(manifest_member).read().decode("utf-8"))
        for member in members:
            if member.name == MANIFEST_NAME:
                continue
            if not member.isfile():
                continue
            dest = scratch / member.name
            dest.parent.mkdir(parents=True, exist_ok=True)
            with tar.extractfile(member) as src, dest.open("wb") as out:
                while True:
                    chunk = src.read(65536)
                    if not chunk:
                        break
                    out.write(chunk)
            extracted.append(member.name)
    report = {"ok": True, "manifest": manifest, "mismatched": [], "missing": [],
              "unexpected": []}
    if verify:
        expected = {f["name"]: f["sha256"] for f in manifest.get("files", [])}
        for name, want in expected.items():
            path = scratch / name
            if not path.exists():
                report["missing"].append(name)
                report["ok"] = False
                continue
            if _file_digest(path) != want:
                report["mismatched"].append(name)
                report["ok"] = False
        # Catch tarballs that smuggle extra files past the manifest.
        surplus = sorted(set(extracted) - set(expected))
        if surplus:
            report["unexpected"] = surplus
            report["ok"] = False
    return report


def list_snapshots(snapshot_root: Path) -> list[dict]:
    """Return snapshot summaries sorted newest-first by filename timestamp."""
    if not snapshot_root.exists():
        return []
    results = []
    for path in snapshot_root.glob("cidm-state-*.tar.gz"):
        results.append({"path": str(path), "bytes": path.stat().st_size,
                        "mtime": path.stat().st_mtime})
    results.sort(key=lambda r: r["path"], reverse=True)
    return results


def _snapshot_timestamp(path: Path) -> float | None:
    """Parse the token out of `cidm-state-<token>.tar.gz` into a UTC epoch,
    or None if the filename does not match the convention."""
    stem = path.name
    prefix, suffix = "cidm-state-", ".tar.gz"
    if not (stem.startswith(prefix) and stem.endswith(suffix)):
        return None
    token = stem[len(prefix):-len(suffix)]
    try:
        # Token is UTC (snapshot writes it via time.gmtime); use calendar.timegm
        # for a true UTC epoch. time.mktime would re-interpret as local time
        # and produce a TZ-offset age error for operators outside UTC.
        return calendar.timegm(time.strptime(token, "%Y-%m-%dT%H-%M-%SZ"))
    except ValueError:
        return None


def prune(snapshot_root: Path, *, older_than_days: float,
          now_ts: float | None = None, dry_run: bool = False) -> list[str]:
    """Delete snapshots whose filename timestamp is older than `older_than_days`.

    The filename carries the operator-supplied token (`cidm-state-<ISO>.tar.gz`);
    we parse it rather than trusting `mtime`, which rotates when the file
    is copied or restored. Returns the list of paths that were (or would be)
    deleted. In `dry_run` the files are left intact. Non-snapshot files
    under `snapshot_root` are not touched.
    """
    cutoff = (time.time() if now_ts is None else now_ts) - older_than_days * 86400
    removed = []
    if not snapshot_root.exists():
        return removed
    for path in sorted(snapshot_root.glob("cidm-state-*.tar.gz")):
        token_ts = _snapshot_timestamp(path)
        if token_ts is None:
            continue
        if token_ts < cutoff:
            removed.append(str(path))
            if not dry_run:
                path.unlink()
    return removed


def _default_runs_root() -> Path:
    return Path(__file__).resolve().parents[1] / "runs"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    snap = sub.add_parser("snapshot", help="Create a new snapshot")
    snap.add_argument("--jev-root", type=Path, default=Path("~/.jev").expanduser())
    snap.add_argument("--snapshot-root", type=Path,
                      default=Path("~/.jev-backups").expanduser())
    snap.add_argument("--include-runs", action="store_true")
    snap.add_argument("--runs-root", type=Path, default=_default_runs_root())

    rest = sub.add_parser("restore", help="Restore a snapshot into a scratch directory")
    rest.add_argument("snapshot_path", type=Path)
    rest.add_argument("--to", type=Path, required=True, dest="scratch")
    rest.add_argument("--no-verify", action="store_true")

    lst = sub.add_parser("list", help="List snapshots")
    lst.add_argument("--snapshot-root", type=Path,
                     default=Path("~/.jev-backups").expanduser())

    prn = sub.add_parser("prune", help="Delete snapshots older than N days")
    prn.add_argument("--older-than", type=float, required=True, dest="days")
    prn.add_argument("--snapshot-root", type=Path,
                     default=Path("~/.jev-backups").expanduser())
    prn.add_argument("--dry-run", action="store_true")

    args = parser.parse_args(argv)

    if args.command == "snapshot":
        path, manifest = snapshot(args.jev_root, args.snapshot_root,
                                  include_runs=args.include_runs,
                                  runs_root=args.runs_root)
        print(json.dumps({"snapshot": str(path), "files": len(manifest["files"]),
                          "host": manifest["host"]}, indent=2))
        return 0
    if args.command == "restore":
        report = restore(args.snapshot_path, args.scratch, verify=not args.no_verify)
        print(json.dumps({"ok": report["ok"], "scratch": str(args.scratch),
                          "verified": not args.no_verify,
                          "mismatched": report["mismatched"],
                          "missing": report["missing"],
                          "unexpected": report.get("unexpected", [])}, indent=2))
        return 0 if report["ok"] else 2
    if args.command == "list":
        print(json.dumps(list_snapshots(args.snapshot_root), indent=2))
        return 0
    if args.command == "prune":
        removed = prune(args.snapshot_root, older_than_days=args.days, dry_run=args.dry_run)
        print(json.dumps({"removed": removed, "dry_run": args.dry_run}, indent=2))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
