"""CIDM Arsenal V1: compile and search Hermes skills locally.

The required path is standard-library only: SQLite + FTS5 when available.
Every SKILL.md may be indexed for discovery. Only a sibling ARSENAL.json that
is explicitly admitted and owner-approved can qualify for CIDM Fast Path.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,95}$")
WORD_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{1,79}")
RISKS = {"low", "medium", "high", "critical"}
TYPES = {"methodology-skill", "recovery-skill", "tool-skill", "project-skill"}


class ArsenalError(ValueError):
    pass


def require(ok: bool, code: str) -> None:
    if not ok:
        raise ArsenalError(code)


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def string_list(value: Any, field: str, limit: int = 64) -> list[str]:
    require(isinstance(value, list) and len(value) <= limit, "invalid_" + field)
    out: list[str] = []
    for item in value:
        require(isinstance(item, str) and 0 < len(item.strip()) <= 240, "invalid_" + field)
        item = item.strip()
        if item not in out:
            out.append(item)
    return out


def parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---\n", 4)
    if end < 0:
        return {}, text
    meta: dict[str, str] = {}
    for line in text[4:end].splitlines():
        if ":" not in line or line.lstrip().startswith("#"):
            continue
        key, value = line.split(":", 1)
        key, value = key.strip(), value.strip().strip("\"'")
        if key and value and re.fullmatch(r"[A-Za-z0-9_-]+", key):
            meta[key] = value
    return meta, text[end + 5:]


def section(body: str, title: str) -> str:
    match = re.search(
        rf"(?ims)^##+\s+{re.escape(title)}\s*$\n(.*?)(?=^##+\s+|\Z)", body
    )
    return match.group(1).strip() if match else ""


def bullets(text: str) -> list[str]:
    out: list[str] = []
    for line in text.splitlines():
        match = re.match(r"^\s*(?:[-*]|\d+[.)])\s+(.+?)\s*$", line)
        if match and match.group(1).strip() not in out:
            out.append(match.group(1).strip())
    return out


def normalize_manifest(value: Any) -> dict[str, Any]:
    require(isinstance(value, dict), "manifest_must_be_object")
    required = {
        "schema_version", "id", "type", "version", "description", "project_scope",
        "triggers", "permissions", "risk", "frontier_required", "validators",
        "operations", "admission",
    }
    require(required <= set(value), "manifest_missing_required_fields")
    require(value["schema_version"] == 1, "unsupported_manifest_schema")
    require(isinstance(value["id"], str) and ID_RE.fullmatch(value["id"]), "invalid_manifest_id")
    require(value["type"] in TYPES, "invalid_skill_type")
    require(isinstance(value["version"], (str, int)) and str(value["version"]), "invalid_version")
    require(isinstance(value["description"], str) and value["description"].strip(), "invalid_description")
    scopes = string_list(value["project_scope"], "project_scope", 24)
    require(bool(scopes), "project_scope_required")

    raw_triggers = value["triggers"]
    require(isinstance(raw_triggers, dict), "invalid_triggers")
    require(set(raw_triggers) <= {"bug_keys", "phrases", "keywords"}, "unknown_trigger_field")
    triggers = {
        key: string_list(raw_triggers.get(key, []), "trigger_" + key)
        for key in ("bug_keys", "phrases", "keywords")
    }
    require(all(ID_RE.fullmatch(key) for key in triggers["bug_keys"]), "invalid_bug_key")

    permissions = value["permissions"]
    require(
        isinstance(permissions, dict) and len(permissions) <= 32
        and all(isinstance(key, str) and ID_RE.fullmatch(key) for key in permissions)
        and all(type(flag) is bool for flag in permissions.values()),
        "invalid_permissions",
    )
    require(value["risk"] in RISKS, "invalid_risk")
    require(type(value["frontier_required"]) is bool, "invalid_frontier_required")
    validators = string_list(value["validators"], "validators", 32)
    operations = string_list(value["operations"], "operations", 32)
    admission = value["admission"]
    require(
        isinstance(admission, dict)
        and admission.get("status") in {"candidate", "admitted", "rejected", "archived"}
        and type(admission.get("owner_approved")) is bool,
        "invalid_admission",
    )
    return {
        "schema_version": 1,
        "id": value["id"],
        "type": value["type"],
        "version": str(value["version"]),
        "description": value["description"].strip(),
        "project_scope": scopes,
        "triggers": triggers,
        "permissions": dict(sorted(permissions.items())),
        "risk": value["risk"],
        "frontier_required": value["frontier_required"],
        "validators": validators,
        "operations": operations,
        "admission": {
            "status": admission["status"],
            "owner_approved": admission["owner_approved"],
        },
        "source": value.get("source", {}),
    }


@dataclass(frozen=True)
class CompiledSkill:
    skill_id: str
    name: str
    description: str
    version: str
    project_scope: tuple[str, ...]
    skill_path: str
    skill_hash: str
    manifest_hash: str | None
    admitted: bool
    risk: str
    frontier_required: bool
    validators: tuple[str, ...]
    operations: tuple[str, ...]
    permissions: dict[str, bool]
    triggers: dict[str, list[str]]
    search_text: str


def compile_skill(path: Path) -> CompiledSkill:
    require(path.is_file() and path.name == "SKILL.md", "skill_md_required")
    text = path.read_text(encoding="utf-8")
    require(0 < len(text) <= 200_000, "invalid_skill_size")
    meta, body = parse_frontmatter(text)
    name = meta.get("name", path.parent.name)
    description = meta.get("description") or next(
        (line.strip("# ") for line in body.splitlines() if line.strip()), name
    )

    discovered = {"bug_keys": [], "phrases": [], "keywords": []}
    tick = chr(96)
    for line in bullets(section(body, "Trigger")):
        clean = line.replace(tick, "")
        if match := re.match(r"(?i)Bug key:\s*([A-Za-z0-9._-]+)", clean):
            discovered["bug_keys"].append(match.group(1))
        elif match := re.match(r"(?i)Failed criterion:\s*(.+)$", clean):
            discovered["keywords"].append(match.group(1).strip())
        elif match := re.match(r"(?i)Observed symptom:\s*(.+)$", clean):
            discovered["phrases"].append(match.group(1).strip())
        else:
            discovered["phrases"].append(clean)

    manifest_path = path.parent / "ARSENAL.json"
    manifest = None
    manifest_hash = None
    if manifest_path.is_file():
        raw = manifest_path.read_text(encoding="utf-8")
        require(0 < len(raw) <= 100_000, "invalid_manifest_size")
        manifest = normalize_manifest(json.loads(raw))
        manifest_hash = digest(canonical(manifest))

    if manifest:
        skill_id = manifest["id"]
        description = manifest["description"]
        version = manifest["version"]
        scopes = tuple(manifest["project_scope"])
        triggers = {
            key: list(dict.fromkeys(manifest["triggers"][key] + discovered[key]))
            for key in discovered
        }
        permissions = manifest["permissions"]
        risk = manifest["risk"]
        frontier_required = manifest["frontier_required"]
        validators = tuple(manifest["validators"])
        operations = tuple(manifest["operations"])
        # Manifest admission fields are descriptive/request metadata only.
        # Trust is granted separately in the local hash-bound admissions table.
        admitted = False
    else:
        skill_id = path.parent.name if ID_RE.fullmatch(path.parent.name) else digest(str(path))[:24]
        version = "unmanifested"
        scopes = ("unscoped",)
        triggers = discovered
        permissions = {}
        risk = "high"
        frontier_required = True
        validators = ()
        operations = ()
        admitted = False

    search_text = "\n".join(
        part for part in [
            name, description, *scopes, *triggers["bug_keys"],
            *triggers["phrases"], *triggers["keywords"], body[:60_000]
        ] if part
    )
    return CompiledSkill(
        skill_id, name, description[:500], version, scopes, str(path.resolve()),
        digest(text), manifest_hash, admitted, risk, frontier_required,
        validators, operations, permissions, triggers, search_text,
    )


class ArsenalRegistry:
    def __init__(self, db_path: Path):
        self.path = Path(db_path).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(self.path))
        self.db.row_factory = sqlite3.Row
        self.fts5 = False
        self._init_schema()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.db.close()

    def _init_schema(self) -> None:
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS skills(
          skill_id TEXT PRIMARY KEY,name TEXT,description TEXT,version TEXT,scope TEXT,
          skill_path TEXT,skill_hash TEXT,manifest_hash TEXT,admitted INTEGER,risk TEXT,
          frontier_required INTEGER,validators TEXT,operations TEXT,permissions TEXT,
          triggers TEXT,search_text TEXT);
        CREATE TABLE IF NOT EXISTS bug_keys(
          bug_key TEXT,skill_id TEXT,PRIMARY KEY(bug_key,skill_id));
        CREATE TABLE IF NOT EXISTS admissions(
          skill_id TEXT PRIMARY KEY,skill_hash TEXT NOT NULL,manifest_hash TEXT NOT NULL);
        """)
        try:
            self.db.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS skill_fts USING "
                "fts5(skill_id UNINDEXED,name,description,search_text)"
            )
            self.fts5 = True
        except sqlite3.OperationalError:
            self.fts5 = False
        self.db.commit()

    def index(self, skill: CompiledSkill) -> None:
        with self.db:
            self.db.execute("DELETE FROM bug_keys WHERE skill_id=?", (skill.skill_id,))
            self.db.execute(
                "INSERT OR REPLACE INTO skills VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    skill.skill_id, skill.name, skill.description, skill.version,
                    canonical(list(skill.project_scope)), skill.skill_path,
                    skill.skill_hash, skill.manifest_hash, int(skill.admitted),
                    skill.risk, int(skill.frontier_required),
                    canonical(list(skill.validators)), canonical(list(skill.operations)),
                    canonical(skill.permissions), canonical(skill.triggers),
                    skill.search_text,
                ),
            )
            for bug_key in skill.triggers["bug_keys"]:
                self.db.execute(
                    "INSERT OR IGNORE INTO bug_keys VALUES(?,?)",
                    (bug_key, skill.skill_id),
                )
            if self.fts5:
                self.db.execute("DELETE FROM skill_fts WHERE skill_id=?", (skill.skill_id,))
                self.db.execute(
                    "INSERT INTO skill_fts VALUES(?,?,?,?)",
                    (skill.skill_id, skill.name, skill.description, skill.search_text),
                )

    def scan(self, root: Path) -> dict[str, Any]:
        root = Path(root).expanduser()
        require(root.is_dir(), "skills_directory_not_found")
        paths = sorted(root.rglob("SKILL.md"))
        require(len(paths) <= 500, "skill_scan_limit_exceeded")
        indexed, errors = [], []
        for path in paths:
            try:
                skill = compile_skill(path)
                self.index(skill)
                indexed.append(skill.skill_id)
            except Exception as error:
                errors.append({"path": str(path), "error": str(error)})
        return {
            "found": len(paths), "indexed": len(indexed), "skill_ids": indexed,
            "errors": errors, "fts5": self.fts5,
        }

    def _is_admitted(self, row: sqlite3.Row) -> bool:
        if not row["manifest_hash"]:
            return False
        approval = self.db.execute(
            "SELECT skill_hash,manifest_hash FROM admissions WHERE skill_id=?",
            (row["skill_id"],),
        ).fetchone()
        return bool(
            approval
            and approval["skill_hash"] == row["skill_hash"]
            and approval["manifest_hash"] == row["manifest_hash"]
        )

    def _skill(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "skill_id": row["skill_id"], "name": row["name"],
            "description": row["description"], "version": row["version"],
            "project_scope": json.loads(row["scope"]), "skill_path": row["skill_path"],
            "skill_hash": row["skill_hash"], "manifest_hash": row["manifest_hash"],
            "admitted": self._is_admitted(row), "risk": row["risk"],
            "frontier_required": bool(row["frontier_required"]),
            "validators": json.loads(row["validators"]),
            "operations": json.loads(row["operations"]),
            "permissions": json.loads(row["permissions"]),
            "triggers": json.loads(row["triggers"]),
            "search_text": row["search_text"],
        }

    def list_skills(self) -> list[dict[str, Any]]:
        return [
            self._skill(row)
            for row in self.db.execute("SELECT * FROM skills ORDER BY skill_id")
        ]

    def admit(self, skill_id: str) -> dict[str, Any]:
        require(isinstance(skill_id, str) and ID_RE.fullmatch(skill_id), "invalid_skill_id")
        row = self.db.execute(
            "SELECT * FROM skills WHERE skill_id=?", (skill_id,)
        ).fetchone()
        require(row is not None, "unknown_skill")
        require(bool(row["manifest_hash"]), "manifest_required_for_admission")
        with self.db:
            self.db.execute(
                "INSERT OR REPLACE INTO admissions(skill_id,skill_hash,manifest_hash) VALUES(?,?,?)",
                (skill_id, row["skill_hash"], row["manifest_hash"]),
            )
        return {
            "skill_id": skill_id,
            "admitted": True,
            "skill_hash": row["skill_hash"],
            "manifest_hash": row["manifest_hash"],
        }

    def revoke(self, skill_id: str) -> dict[str, Any]:
        require(isinstance(skill_id, str) and ID_RE.fullmatch(skill_id), "invalid_skill_id")
        with self.db:
            cursor = self.db.execute(
                "DELETE FROM admissions WHERE skill_id=?", (skill_id,)
            )
        return {"skill_id": skill_id, "revoked": cursor.rowcount > 0}

    def _tokens(self, text: str) -> list[str]:
        return list(dict.fromkeys(token.lower() for token in WORD_RE.findall(text)))

    def _lexical_score(self, query: str, text: str) -> float:
        query_terms = set(self._tokens(query))
        if not query_terms:
            return 0.0
        doc_terms = set(self._tokens(text))
        score = len(query_terms & doc_terms) / len(query_terms)
        if query.lower().strip() in text.lower():
            score += 0.15
        return min(1.0, score)

    def _candidate_ids(self, task: str, limit: int) -> list[str]:
        terms = self._tokens(task)[:24]
        if not terms:
            return []
        if self.fts5:
            query = " OR ".join('"' + term.replace('"', '""') + '"' for term in terms)
            try:
                return [
                    row["skill_id"] for row in self.db.execute(
                        "SELECT skill_id FROM skill_fts WHERE skill_fts MATCH ? "
                        "ORDER BY bm25(skill_fts) LIMIT ?", (query, limit)
                    )
                ]
            except sqlite3.OperationalError:
                pass
        rows = self.db.execute("SELECT * FROM skills").fetchall()
        rows.sort(
            key=lambda row: self._lexical_score(task, row["search_text"]),
            reverse=True,
        )
        return [
            row["skill_id"] for row in rows[:limit]
            if self._lexical_score(task, row["search_text"]) > 0
        ]

    def match(
        self, task: str, *, project_scope: str | None = None,
        bug_key: str | None = None, operation: str | None = None,
        threshold: float = 0.78, top_k: int = 5,
    ) -> dict[str, Any]:
        require(isinstance(task, str) and 0 < len(task.strip()) <= 20_000, "invalid_task")
        require(0.5 <= threshold <= 1.0 and 1 <= top_k <= 20, "invalid_match_config")
        if bug_key is not None:
            require(isinstance(bug_key, str) and ID_RE.fullmatch(bug_key), "invalid_bug_key")

        exact = [] if not bug_key else [
            row["skill_id"] for row in self.db.execute(
                "SELECT skill_id FROM bug_keys WHERE bug_key=?", (bug_key,)
            )
        ]
        ids = list(dict.fromkeys(exact + self._candidate_ids(task, max(20, top_k * 4))))
        if not ids:
            return {
                "decision": "escalate_to_jev", "reason": "no_local_candidate",
                "confidence": 0.0, "matches": [],
            }

        marks = ",".join("?" for _ in ids)
        matches = []
        for row in self.db.execute(
            "SELECT * FROM skills WHERE skill_id IN (" + marks + ")", tuple(ids)
        ):
            skill = self._skill(row)
            scopes = skill["project_scope"]
            if (
                project_scope is not None
                and project_scope not in scopes
                and "global" not in scopes
            ):
                continue
            exact_bug = bool(bug_key and bug_key in skill["triggers"]["bug_keys"])
            score = 1.0 if exact_bug else self._lexical_score(task, skill["search_text"])
            if project_scope and project_scope in scopes:
                score = min(1.0, score + 0.05)
            skill.pop("search_text", None)
            skill["match"] = {
                "score": round(score, 6), "exact_bug_key": exact_bug,
            }
            matches.append(skill)

        matches.sort(
            key=lambda item: (
                item["match"]["exact_bug_key"],
                item["match"]["score"],
                item["admitted"],
            ),
            reverse=True,
        )
        matches = matches[:top_k]
        if not matches:
            return {
                "decision": "escalate_to_jev", "reason": "no_scope_candidate",
                "confidence": 0.0, "matches": [],
            }

        best = matches[0]
        confidence = best["match"]["score"]
        known = best["match"]["exact_bug_key"] or confidence >= threshold
        fast = self.fast_path(
            best, project_scope=project_scope, operation=operation,
            confidence=confidence, exact_bug=best["match"]["exact_bug_key"],
            threshold=threshold,
        )
        return {
            "decision": "known_skill" if known else "escalate_to_jev",
            "reason": (
                "exact_bug_key" if best["match"]["exact_bug_key"]
                else "local_match_above_threshold" if known
                else "local_match_below_threshold"
            ),
            "confidence": confidence,
            "skill_id": best["skill_id"] if known else None,
            "fast_path": fast,
            "matches": matches,
        }

    def fast_path(
        self, skill: dict[str, Any], *, project_scope: str | None,
        operation: str | None, confidence: float, exact_bug: bool,
        threshold: float,
    ) -> dict[str, Any]:
        reasons = []
        if not skill["admitted"]:
            reasons.append("skill_not_admitted")
        if skill["frontier_required"]:
            reasons.append("frontier_required")
        if skill["risk"] != "low":
            reasons.append("risk_not_low")
        if not skill["validators"]:
            reasons.append("deterministic_validators_required")

        scopes = skill["project_scope"]
        if project_scope is None and "global" not in scopes:
            reasons.append("project_scope_required")
        elif (
            project_scope is not None
            and project_scope not in scopes
            and "global" not in scopes
        ):
            reasons.append("project_scope_mismatch")

        if operation is None:
            reasons.append("operation_required")
        elif operation not in skill["operations"]:
            reasons.append("operation_not_preapproved")
        if not exact_bug and confidence < threshold:
            reasons.append("confidence_below_threshold")

        return {
            "eligible": not reasons, "reasons": reasons,
            "validators": skill["validators"],
            "permissions": skill["permissions"],
            "skill_hash": skill["skill_hash"],
            "manifest_hash": skill["manifest_hash"],
        }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="CIDM Arsenal local skill registry")
    parser.add_argument(
        "--db", type=Path,
        default=Path("~/.jev/arsenal/arsenal.db").expanduser(),
    )
    sub = parser.add_subparsers(dest="command", required=True)
    scan = sub.add_parser("scan")
    scan.add_argument("--skills-dir", type=Path, required=True)
    admit = sub.add_parser("admit")
    admit.add_argument("--skill-id", required=True)
    revoke = sub.add_parser("revoke")
    revoke.add_argument("--skill-id", required=True)
    match = sub.add_parser("match")
    match.add_argument("--task", required=True)
    match.add_argument("--project-scope")
    match.add_argument("--bug-key")
    match.add_argument("--operation")
    match.add_argument("--threshold", type=float, default=0.78)
    sub.add_parser("list")
    args = parser.parse_args(argv)

    with ArsenalRegistry(args.db) as registry:
        if args.command == "scan":
            result = registry.scan(args.skills_dir)
        elif args.command == "admit":
            result = registry.admit(args.skill_id)
        elif args.command == "revoke":
            result = registry.revoke(args.skill_id)
        elif args.command == "match":
            result = registry.match(
                args.task, project_scope=args.project_scope,
                bug_key=args.bug_key, operation=args.operation,
                threshold=args.threshold,
            )
        else:
            result = {"skills": registry.list_skills(), "fts5": registry.fts5}
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
