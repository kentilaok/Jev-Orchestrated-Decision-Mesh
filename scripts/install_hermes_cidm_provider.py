#!/usr/bin/env python3
"""Register CIDM as a Hermes `custom provider`.

Writes a marked `providers.cidm` block into the user's Hermes `config.yaml` so
that `hermes chat --model cidm-jev` routes every turn to the local CIDM broker
at http://127.0.0.1:8765/v1 (OpenAI chat-completions compat). The CIDM broker
then runs Jev's five-unit decision, issues permits, invokes workers via the
local Claude/Codex CLIs, validates, and returns the final answer.

Design points:
- Backup `config.yaml` to `config.yaml.bak-cidm-{timestamp}` before any change.
- Idempotent: re-running replaces the previous marked block in place; a vanilla
  install over an unchanged target reports no change.
- Refuses to run when the user already has an *active* top-level `providers:`
  block, since silently merging into user YAML without a parser is unsafe.
  In that case the user adds the `cidm:` sub-entry manually (the installer
  prints the exact text to append) and the installer records that it did not
  modify the file.
- Reversible with `--uninstall`.
- `--dry-run` reports what would change without touching disk.

CIDM project policy keeps the toolchain stdlib-only; this installer deliberately
does not import PyYAML. The block it writes is syntactically valid YAML and the
surrounding Hermes config is treated as opaque text.
"""
from __future__ import annotations

import argparse
import re
import shutil
import sys
import time
from pathlib import Path

BEGIN_MARKER = "# BEGIN cidm-provider (managed by install_hermes_cidm_provider.py)"
END_MARKER = "# END cidm-provider"

BLOCK_BODY = """\
providers:
  cidm:
    base_url: "http://127.0.0.1:8765/v1"
    key_env: "CIDM_API_KEY"
    api_mode: chat_completions
    model: cidm-jev
    streaming: true
"""

ACTIVE_PROVIDERS_RE = re.compile(r"^providers:\s*$", re.MULTILINE)


class InstallerError(RuntimeError):
    pass


def default_target() -> Path:
    """Return the active Hermes config.yaml path on this machine."""
    try:
        from hermes_paths import hermes_home  # type: ignore
        return hermes_home() / "config.yaml"
    except Exception:
        base = Path.home() / "AppData" / "Local" / "hermes" / "config.yaml"
        return base


def render_block() -> str:
    return BEGIN_MARKER + "\n" + BLOCK_BODY + END_MARKER + "\n"


def _has_managed_block(text: str) -> bool:
    return BEGIN_MARKER in text and END_MARKER in text


def _strip_managed_block(text: str) -> str:
    pattern = re.compile(re.escape(BEGIN_MARKER) + r".*?" + re.escape(END_MARKER) + r"\n?",
                         re.DOTALL)
    return pattern.sub("", text)


def _has_active_providers_block(text: str) -> bool:
    """True iff config.yaml already contains an uncommented top-level
    `providers:` entry outside of a managed CIDM block."""
    cleaned = _strip_managed_block(text)
    for line in cleaned.splitlines():
        if ACTIVE_PROVIDERS_RE.match(line):
            return True
    return False


def _make_backup(path: Path) -> Path:
    stamp = time.strftime("%Y%m%d%H%M%S")
    backup = path.with_suffix(path.suffix + ".bak-cidm-" + stamp)
    shutil.copy2(path, backup)
    return backup


def install(path: Path, *, dry_run: bool = False) -> dict:
    if not path.is_file():
        raise InstallerError("Hermes config not found at " + str(path))
    original = path.read_text(encoding="utf-8")
    desired_block = render_block()
    if _has_managed_block(original):
        stripped = _strip_managed_block(original).rstrip() + "\n\n" + desired_block
    else:
        if _has_active_providers_block(original):
            raise InstallerError(
                "Active top-level 'providers:' block already present in " + str(path) +
                ". Add the CIDM entry manually inside that block:\n\n" +
                "  cidm:\n" +
                "    base_url: \"http://127.0.0.1:8765/v1\"\n" +
                "    key_env: \"CIDM_API_KEY\"\n" +
                "    api_mode: chat_completions\n" +
                "    model: cidm-jev\n" +
                "    streaming: true\n")
        stripped = original.rstrip() + "\n\n" + desired_block
    if stripped == original:
        return {"changed": False, "would_change": False, "path": str(path)}
    if dry_run:
        return {"changed": False, "would_change": True, "path": str(path)}
    backup = _make_backup(path)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(stripped, encoding="utf-8")
    tmp.replace(path)
    return {"changed": True, "would_change": True, "path": str(path), "backup": str(backup)}


def uninstall(path: Path, *, dry_run: bool = False) -> dict:
    if not path.is_file():
        raise InstallerError("Hermes config not found at " + str(path))
    original = path.read_text(encoding="utf-8")
    if not _has_managed_block(original):
        return {"changed": False, "path": str(path)}
    stripped = _strip_managed_block(original).rstrip() + "\n"
    if dry_run:
        return {"changed": False, "would_change": True, "path": str(path)}
    backup = _make_backup(path)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(stripped, encoding="utf-8")
    tmp.replace(path)
    return {"changed": True, "path": str(path), "backup": str(backup)}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Install CIDM as a Hermes custom provider")
    parser.add_argument("--target", type=Path, default=None,
                        help="Path to Hermes config.yaml (default: platform-specific)")
    parser.add_argument("--uninstall", action="store_true",
                        help="Remove the CIDM provider block instead of installing")
    parser.add_argument("--dry-run", action="store_true",
                        help="Report what would change without writing")
    args = parser.parse_args(argv)
    target = args.target or default_target()
    try:
        if args.uninstall:
            result = uninstall(target, dry_run=args.dry_run)
        else:
            result = install(target, dry_run=args.dry_run)
    except InstallerError as exc:
        sys.stderr.write("install_hermes_cidm_provider: " + str(exc) + "\n")
        return 2
    for key in ("changed", "would_change", "path", "backup"):
        if key in result:
            sys.stdout.write("%s=%s\n" % (key, result[key]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
