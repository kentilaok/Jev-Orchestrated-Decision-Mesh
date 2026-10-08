"""Locate the local Hermes Agent install without guessing a single platform layout.

Order: HERMES_HOME, then ~/.hermes, then %LOCALAPPDATA%\\hermes (the Windows
installer's location). CIDM-managed skills live in a separate external
directory that Hermes loads read-only via `skills.external_dirs`.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

CIDM_EXTERNAL_SKILLS = Path("~/.jev/hermes-skills").expanduser()


def hermes_home() -> Path:
    if os.environ.get("HERMES_HOME"):
        return Path(os.environ["HERMES_HOME"]).expanduser()
    candidates = [Path.home() / ".hermes"]
    if os.environ.get("LOCALAPPDATA"):
        candidates.append(Path(os.environ["LOCALAPPDATA"]) / "hermes")
    return next((path for path in candidates if (path / "config.yaml").is_file()), candidates[0])


def hermes_executable() -> str | None:
    found = shutil.which("hermes")
    if found:
        return found
    for name in ("hermes.exe", "hermes"):
        path = hermes_home() / "bin" / name
        if path.is_file():
            return str(path)
    return None


def active_skill_roots() -> list[Path]:
    """Directories an agent loads skills from; quarantine imports must avoid them."""
    home = Path.home()
    roots = [home / ".hermes" / "skills", hermes_home() / "skills", CIDM_EXTERNAL_SKILLS,
             home / ".claude" / "skills", home / ".codex" / "skills", home / ".agents" / "skills"]
    return list(dict.fromkeys(roots))
