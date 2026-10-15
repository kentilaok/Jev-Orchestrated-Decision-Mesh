"""Tighten ~/.jev and runs/ to the current user only (P0-06 slice 3).

A single-user Windows workstation (or a single-operator POSIX host) should
own the permit ledger, calibration ledger, Fast-Path ledger, MCP DB, saved
prompts, checkpoint JSON, and run output under `~/.jev` and `<repo>/runs`.

On POSIX, every directory is set to 0o700 and every file to 0o600.
On Windows (NTFS), each path has inheritance stripped and a single explicit
grant of Full control to the invoking user via `icacls`.

The script is idempotent: a second run on an already-hardened tree is a
no-op (POSIX chmod rewrites the same bits; icacls re-applies the same ACE).

Running elevated is not required for user-owned paths; a hardened path that
is already owned by another account will fail with the OS error surfaced.

CLI:

    python scripts/harden_jev_permissions.py [--jev-root PATH] [--runs-root PATH]
                                             [--user NAME] [--dry-run] [--verbose]

Returns 0 if every reachable path was hardened (or skipped as missing), and
2 if any path raised an OS error or any icacls call returned non-zero.
"""
from __future__ import annotations

import argparse
import getpass
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Callable, Iterable

POSIX_DIR_MODE = 0o700
POSIX_FILE_MODE = 0o600


def _iter_tree(root: Path) -> Iterable[Path]:
    """Yield `root` and every descendant without following symlinks.

    Yield order is root-first, breadth-first — the inner loop still has to
    walk its own children anyway, and icacls / chmod on a directory does
    not depend on its contents already being tightened.
    """
    if not root.exists():
        return
    yield root
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        base = Path(dirpath)
        for name in filenames:
            yield base / name
        for name in dirnames:
            yield base / name


def _icacls_argv(path: Path, user: str, is_dir: bool) -> list[str]:
    """Build the `icacls` command for one NTFS path.

    `/inheritance:r` strips inherited ACEs so the grant list is explicit;
    `/grant:r` replaces the user's existing grants (not additive).
    `(OI)(CI)F` on a directory sets Object Inherit + Container Inherit so
    future children inherit the Full-control ACE from this container.
    """
    perm = "(OI)(CI)F" if is_dir else "F"
    return ["icacls", str(path), "/inheritance:r", "/grant:r", f"{user}:{perm}"]


def _apply_posix(path: Path, *, dry_run: bool, verbose: bool,
                 log: Callable[[str], None]) -> int:
    mode = POSIX_DIR_MODE if path.is_dir() else POSIX_FILE_MODE
    if verbose or dry_run:
        log(f"chmod {oct(mode)} {path}")
    if dry_run:
        return 0
    try:
        os.chmod(path, mode)
    except OSError as exc:
        log(f"chmod failed on {path}: {exc}")
        return 1
    return 0


def _apply_windows(path: Path, user: str, *, dry_run: bool, verbose: bool,
                   runner: Callable, log: Callable[[str], None]) -> int:
    argv = _icacls_argv(path, user, path.is_dir())
    if verbose or dry_run:
        log("$ " + " ".join(argv))
    if dry_run:
        return 0
    try:
        result = runner(argv, capture_output=True, text=True, shell=False)
    except OSError as exc:
        log(f"icacls launch failed on {path}: {exc}")
        return 1
    if result.returncode != 0:
        log(f"icacls failed on {path} (rc={result.returncode}): "
            f"{(result.stderr or '').strip()}")
        return result.returncode
    return 0


def harden_path(path: Path, *, user: str, dry_run: bool, verbose: bool, platform: str,
                runner: Callable, log: Callable[[str], None]) -> int:
    if platform == "win32":
        return _apply_windows(path, user, dry_run=dry_run, verbose=verbose,
                              runner=runner, log=log)
    return _apply_posix(path, dry_run=dry_run, verbose=verbose, log=log)


def harden_tree(root: Path, *, user: str, dry_run: bool, verbose: bool, platform: str,
                runner: Callable, log: Callable[[str], None]) -> dict:
    """Harden every path under `root`. Returns a per-root summary dict."""
    if not root.exists():
        log(f"skip missing root: {root}")
        return {"root": str(root), "processed": 0, "skipped": True, "errors": 0}
    processed = 0
    errors = 0
    for path in _iter_tree(root):
        rc = harden_path(path, user=user, dry_run=dry_run, verbose=verbose,
                         platform=platform, runner=runner, log=log)
        if rc != 0:
            errors += 1
            continue
        processed += 1
    return {"root": str(root), "processed": processed, "skipped": False, "errors": errors}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jev-root", type=Path, default=Path("~/.jev").expanduser(),
                        help="Jev state root (default ~/.jev)")
    parser.add_argument("--runs-root", type=Path,
                        default=Path(__file__).resolve().parents[1] / "runs",
                        help="Run output root (default <repo>/runs)")
    parser.add_argument("--user", default=getpass.getuser(),
                        help="User to grant Full control on Windows (default invoker)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print the chmod/icacls plan without applying it")
    parser.add_argument("--verbose", action="store_true",
                        help="Print every operation to stderr")
    args = parser.parse_args(argv)

    def log(message: str) -> None:
        print(message, file=sys.stderr)

    results = []
    for root in (args.jev_root, args.runs_root):
        results.append(harden_tree(root, user=args.user, dry_run=args.dry_run,
                                   verbose=args.verbose, platform=sys.platform,
                                   runner=subprocess.run, log=log))

    summary = {"platform": sys.platform, "user": args.user, "dry_run": args.dry_run,
               "roots": results}
    print(json.dumps(summary, indent=2))
    return 0 if all(r["errors"] == 0 for r in results) else 2


if __name__ == "__main__":
    raise SystemExit(main())
