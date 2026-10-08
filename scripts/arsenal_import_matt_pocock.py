"""Stage a pinned external skill catalogue as unadmitted CIDM/Hermes skills.

Does not install packages, run scripts, grant permissions, or execute skills.
Dry run is default. Actual copying requires --install and a clean checked-out
upstream revision. The destination must not contain the skill already.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

PIN_RE = re.compile(r"^[0-9a-f]{40}$")
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


def require(value: bool, reason: str) -> None:
    if not value:
        raise ValueError(reason)


def git_output(root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(root), *args],
        check=True, capture_output=True, text=True, timeout=20,
    )
    return completed.stdout.strip()


def preflight_source(root: Path, pinned_revision: str) -> None:
    require(root.is_dir(), "upstream_checkout_not_found")
    require(bool(PIN_RE.fullmatch(pinned_revision)), "invalid_upstream_revision")
    require(git_output(root, "rev-parse", "HEAD") == pinned_revision,
            "upstream_revision_mismatch")
    # Reject changed or untracked files; ignored files are further filtered
    # by git ls-files below so only committed source content can be staged.
    require(git_output(root, "status", "--porcelain", "--untracked-files=all") == "",
            "upstream_checkout_is_dirty")


def selected_skills(catalogue: dict, requested: list[str], include_review: bool) -> list[dict]:
    require(catalogue.get("schema_version") == 1, "unknown_catalogue_schema")
    require(isinstance(catalogue.get("skills"), list), "invalid_skill_catalogue")
    available = {item["name"]: item for item in catalogue["skills"]}
    require(len(available) == len(catalogue["skills"]), "duplicate_skill_name")
    for item in available.values():
        require(bool(ID_RE.fullmatch(item["name"])), "invalid_skill_name")
        require(item["invocation"] in ("model", "user"), "invalid_invocation")
        require(item["priority"] in ("core", "review", "restricted"), "invalid_priority")
    names = requested or [
        name for name, item in available.items()
        if item["priority"] == "core" or
        (include_review and item["priority"] == "review")
    ]
    for name in names:
        require(name in available, "unknown_requested_skill")
    return [available[name] for name in dict.fromkeys(names)]


def manifest_for(item: dict, catalogue: dict) -> dict:
    name = item["name"]
    risk = "high" if item["priority"] == "restricted" else "medium"
    return {
        "schema_version": 1,
        "id": "matt-pocock-" + name,
        "type": "methodology-skill",
        "version": catalogue["pinned_revision"][:12],
        "description": item["purpose"][:500],
        "project_scope": catalogue["default_scope"],
        "triggers": {
            "bug_keys": [],
            "phrases": [item["purpose"][:240]],
            "keywords": [name.replace("-", " ")],
        },
        "permissions": {
            "read_files": False,
            "write_files": False,
            "shell": False,
            "network": False,
            "spawn_subagents": False,
            "issue_tracker_write": False,
        },
        "risk": risk,
        "frontier_required": True,
        "validators": [],
        "operations": [],
        "admission": {"status": "candidate", "owner_approved": False},
        "source": {
            "kind": "upstream-curated",
            "repository": catalogue["upstream"],
            "revision": catalogue["pinned_revision"],
            "path": item["upstream_path"],
            "license": catalogue["license"],
            "invocation": item["invocation"],
        },
    }


def import_catalogue(
    source_root: Path,
    destination: Path,
    catalogue_path: Path,
    *,
    requested: list[str] | None = None,
    include_review: bool = False,
    install: bool = False,
) -> dict:
    catalogue = json.loads(catalogue_path.read_text(encoding="utf-8"))
    require(catalogue.get("source_id") == "matt-pocock-real-engineers",
            "unexpected_catalogue_source")
    root = source_root.expanduser().resolve()
    preflight_source(root, catalogue["pinned_revision"])
    licence = root / "LICENSE"
    require(licence.is_file() and 0 < licence.stat().st_size <= 100_000,
            "upstream_license_missing")
    selected = selected_skills(catalogue, requested or [], include_review)
    tracked = set(
        git_output(root, "ls-files", "--cached", "-z").split("\0")
    )
    require("LICENSE" in tracked, "upstream_license_not_tracked")
    planned = []
    dest_root = destination.expanduser().resolve()
    home = Path.home()
    active_roots = [
        home / ".hermes" / "skills",
        home / ".claude" / "skills",
        home / ".codex" / "skills",
    ]
    if os.environ.get("HERMES_HOME"):
        active_roots.append(Path(os.environ["HERMES_HOME"]).expanduser() / "skills")
    require(
        all(not dest_root.is_relative_to(path.resolve()) for path in active_roots),
        "cannot_import_directly_into_active_agent_skill_directory",
    )
    for item in selected:
        rel = Path(item["upstream_path"])
        require(not rel.is_absolute() and ".." not in rel.parts, "unsafe_upstream_path")
        src = (root / rel).resolve()
        require(src.is_relative_to(root) and src.is_dir(), "missing_or_escaped_skill_directory")
        require((src / "SKILL.md").is_file(), "skill_document_missing")
        files = [path for path in src.rglob("*") if path.is_file()]
        require(len(files) <= 250, "skill_file_count_limit")
        require(not any(path.is_symlink() for path in src.rglob("*")), "skill_symlink_forbidden")
        require(all(path.stat().st_size <= 2_000_000 for path in files), "skill_file_too_large")
        require(all(path.relative_to(root).as_posix() in tracked for path in files),
                "untracked_or_ignored_skill_file")
        require(not (src / "ARSENAL.json").exists(),
                "upstream_arsenal_manifest_conflict")
        target = dest_root / ("matt-pocock-" + item["name"])
        require(not target.exists(), "destination_skill_already_exists")
        require(not (src / "UPSTREAM_LICENSE.txt").exists(),
                "upstream_license_destination_conflict")
        manifest = manifest_for(item, catalogue)
        planned.append((src, target, manifest))
    # All sources/destinations are checked before the first write.
    written = []
    if install:
        dest_root.mkdir(parents=True, exist_ok=True)
        for src, target, manifest in planned:
            shutil.copytree(src, target)
            shutil.copy2(licence, target / "UPSTREAM_LICENSE.txt")
            (target / "ARSENAL.json").write_text(
                json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
            written.append(str(target))
    return {
        "status": "staged" if install else "dry_run",
        "upstream_revision": catalogue["pinned_revision"],
        "skills": [
            {"skill_id": manifest["id"], "source": str(src), "destination": str(target),
             "invocation": manifest["source"]["invocation"], "admission": "candidate"}
            for src, target, manifest in planned
        ],
        "written": written,
        "authority": "none_owner_admission_required",
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument(
        "--dest", type=Path,
        default=Path("~/.jev/arsenal/quarantine/matt-pocock"),
        help="Candidate quarantine folder, never an active agent skills directory",
    )
    parser.add_argument(
        "--catalogue", type=Path,
        default=Path(__file__).resolve().parents[1] / "arsenal/sources/matt-pocock.json",
    )
    parser.add_argument("--skill", action="append", default=[])
    parser.add_argument("--include-review", action="store_true")
    parser.add_argument("--install", action="store_true", help="Copy skill files and candidate manifests")
    args = parser.parse_args(argv)
    result = import_catalogue(
        args.source_root, args.dest, args.catalogue,
        requested=args.skill, include_review=args.include_review, install=args.install,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
