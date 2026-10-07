"""Distill auditable CIDM run history into verified lessons and candidate Hermes skills.

This is procedural/context memory, not model-weight training. Raw run evidence is
append-only; only lessons with a verified successful recovery are promotable.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def _failed_criteria(event: dict) -> list[str]:
    checks = event.get("hard_checks") or {}
    if isinstance(checks, dict):
        return sorted(str(name) for name, passed in checks.items() if passed is False)
    return []


def extract_experiences(result: dict, *, run_id: str | None = None) -> list[dict]:
    """Extract failure -> recovery -> verified-commit episodes from one CIDM result."""
    events = result.get("events") or []
    run_id = run_id or result.get("run_id") or digest({
        "policy": result.get("policy_version"),
        "events": [event.get("id") for event in events if isinstance(event, dict)],
        "status": result.get("status"),
    })[:16]

    commits_by_unit: dict[str, list[tuple[int, dict]]] = defaultdict(list)
    recovery_by_unit: dict[str, list[tuple[int, dict]]] = defaultdict(list)
    failures: list[tuple[int, dict]] = []

    for index, event in enumerate(events):
        if not isinstance(event, dict):
            continue
        kind = event.get("kind")
        unit_id = event.get("unit_id")
        if kind == "checked_commit" and unit_id:
            commits_by_unit[str(unit_id)].append((index, event))
        elif kind in ("recovery_replan", "recovery_evidence_added", "recovery_checkpoint"):
            if unit_id:
                recovery_by_unit[str(unit_id)].append((index, event))
        elif kind == "post_worker_decision":
            failed = _failed_criteria(event)
            choice = str(event.get("choice") or "")
            if failed or choice in ("repair", "escalate", "retrieve_evidence", "stop") or choice.startswith("retry_"):
                failures.append((index, event))
        elif kind == "post_checker_decision":
            receipt = event.get("receipt") or {}
            verdict = ((receipt.get("result") or {}).get("verdict")
                       if isinstance(receipt, dict) else None)
            choice = str(event.get("choice") or "")
            if (verdict and verdict != "pass") or choice in ("repair", "escalate", "retrieve_evidence", "stop"):
                failures.append((index, event))

    experiences = []
    for index, event in failures:
        unit_id = str(event.get("unit_id") or "unknown")
        criteria = _failed_criteria(event)
        receipt = event.get("receipt") or {}
        checker_result = receipt.get("result") if isinstance(receipt, dict) else None
        if isinstance(checker_result, dict):
            criteria = sorted(set(criteria + [str(x) for x in checker_result.get("failed_criteria", [])]))

        subsequent = [pair for pair in commits_by_unit.get(unit_id, []) if pair[0] > index]
        verified = bool(subsequent)
        commit = subsequent[0][1] if verified else None
        boundary = subsequent[0][0] if verified else 10**12
        recovery_events = [
            e for i, e in recovery_by_unit.get(unit_id, [])
            if index < i < boundary
        ]

        actions = []
        choice = str(event.get("choice") or "")
        if choice:
            actions.append(choice)
        for recovery_event in recovery_events:
            action = recovery_event.get("recovery_kind") or recovery_event.get("kind")
            if action:
                actions.append(str(action))

        signature_payload = {
            "unit_id": unit_id,
            "failed_criteria": criteria,
            "failure_kind": event.get("kind"),
        }
        experiences.append({
            "experience_id": digest({
                "run_id": run_id, "event": event.get("id"),
                "signature": signature_payload,
            })[:20],
            "run_id": run_id,
            "unit_id": unit_id,
            "failure_event_id": event.get("id"),
            "failure_kind": event.get("kind"),
            "failed_criteria": criteria,
            "decision": choice or None,
            "candidate_hash": (
                event.get("candidate_hash")
                or (receipt.get("candidate_hash") if isinstance(receipt, dict) else None)
            ),
            "recovery_actions": list(dict.fromkeys(actions)),
            "verified_recovery": verified,
            "verification_event_id": commit.get("id") if commit else None,
            "verified_artifact_hash": (
                (commit.get("packet") or {}).get("artifact_hash") if commit else None
            ),
            "signature": digest(signature_payload),
            "source": "cidm-run",
        })
    return experiences


def append_jsonl(path: Path, records: Iterable[dict]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("a", encoding="utf-8") as stream:
        for record in records:
            stream.write(canonical(record) + "\n")
            count += 1
    return count


def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def distill_lessons(records: Iterable[dict]) -> list[dict]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for record in records:
        if isinstance(record, dict) and record.get("signature"):
            groups[str(record["signature"])].append(record)

    lessons = []
    for signature, items in groups.items():
        verified = [item for item in items if item.get("verified_recovery")]
        if not verified:
            continue
        unit_id = str(verified[0].get("unit_id") or "unknown")
        criteria = sorted({
            str(c) for item in verified for c in item.get("failed_criteria", [])
        })
        actions = []
        for item in verified:
            for action in item.get("recovery_actions", []):
                if action not in actions:
                    actions.append(action)

        lessons.append({
            "lesson_id": "lesson-" + signature[:12],
            "signature": signature,
            "unit_id": unit_id,
            "failed_criteria": criteria,
            "successful_recovery_actions": actions,
            "observations": len(items),
            "verified_observations": len(verified),
            "confidence": (
                "high" if len(verified) >= 3
                else "medium" if len(verified) >= 2
                else "provisional"
            ),
            "provenance": [{
                "run_id": item.get("run_id"),
                "failure_event_id": item.get("failure_event_id"),
                "verification_event_id": item.get("verification_event_id"),
                "artifact_hash": item.get("verified_artifact_hash"),
            } for item in verified],
        })

    return sorted(
        lessons,
        key=lambda item: (-item["verified_observations"], item["lesson_id"]),
    )


def promotable(lesson: dict, *, min_verified: int = 2,
               owner_approved: bool = False) -> bool:
    return bool(
        owner_approved
        or int(lesson.get("verified_observations", 0)) >= min_verified
    )


def skill_name(lesson: dict) -> str:
    base = "cidm-" + str(lesson.get("unit_id") or "recovery").lower().replace("_", "-")
    return "".join(ch for ch in base if ch.isalnum() or ch == "-")[:64]


def render_skill(lesson: dict) -> str:
    name = skill_name(lesson)
    criteria = lesson.get("failed_criteria") or ["unspecified gate failure"]
    actions = lesson.get("successful_recovery_actions") or ["replan"]
    provenance = lesson.get("provenance") or []

    lines = [
        "---",
        f"name: {name}",
        f"description: Recovery procedure distilled from verified CIDM runs for {lesson.get('unit_id', 'a unit')} failures.",
        "---",
        "",
        f"# {name}",
        "",
        "Use this skill when the current CIDM unit matches the failure signature below.",
        "Do not use it to bypass validators, source requirements, or Jev permits.",
        "",
        "## Trigger",
        "",
    ]
    lines += [f"- Failed criterion: `{criterion}`" for criterion in criteria]
    lines += ["", "## Verified recovery pattern", ""]
    lines += [f"{i}. `{action}`" for i, action in enumerate(actions, 1)]
    lines += [
        f"{len(actions)+1}. Re-run the same hard validators.",
        f"{len(actions)+2}. Commit only when the candidate passes and Jev explicitly authorizes forwarding.",
        "",
        "## Confidence",
        "",
        f"- Verified observations: {lesson.get('verified_observations', 0)}",
        f"- Confidence: {lesson.get('confidence', 'provisional')}",
        "",
        "## Provenance",
        "",
    ]
    for item in provenance:
        lines.append(
            f"- run `{item.get('run_id')}`; failure `{item.get('failure_event_id')}`; "
            f"verification `{item.get('verification_event_id')}`; "
            f"artifact `{item.get('artifact_hash')}`"
        )
    lines += [
        "",
        "If current evidence conflicts with this skill, prefer current evidence and validators.",
        "",
    ]
    return "\n".join(lines)


def write_promoted_skills(lessons: Iterable[dict], skills_dir: Path, *,
                          min_verified: int = 2,
                          owner_approved: bool = False) -> list[Path]:
    written = []
    for lesson in lessons:
        if not promotable(
            lesson, min_verified=min_verified, owner_approved=owner_approved
        ):
            continue
        folder = skills_dir / skill_name(lesson)
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / "SKILL.md"
        path.write_text(render_skill(lesson), encoding="utf-8")
        written.append(path)
    return written


def discover_results(roots: Iterable[Path]) -> list[Path]:
    paths = []
    for root in roots:
        if not root.exists():
            continue
        paths.extend(sorted(root.rglob("result.json")))
        paths.extend(sorted(root.rglob("*.result.json")))
    return list(dict.fromkeys(path.resolve() for path in paths))


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Distill CIDM run evidence into verified lessons and optional Hermes skills"
    )
    parser.add_argument("results", nargs="*", type=Path, help="CIDM result JSON files")
    parser.add_argument(
        "--scan-dir", action="append", type=Path, default=[],
        help="Recursively scan a directory for result.json and *.result.json",
    )
    parser.add_argument(
        "--ledger", type=Path,
        default=Path("~/.jev/experience/ledger.jsonl").expanduser(),
    )
    parser.add_argument(
        "--lessons", type=Path,
        default=Path("~/.jev/experience/lessons.json").expanduser(),
    )
    parser.add_argument("--skills-dir", type=Path)
    parser.add_argument("--min-verified", type=int, default=2)
    parser.add_argument("--owner-approved", action="store_true")
    args = parser.parse_args(argv)

    paths = list(args.results) + discover_results(args.scan_dir)
    paths = list(dict.fromkeys(path.resolve() for path in paths))
    if not paths:
        parser.error("provide at least one result file or --scan-dir")

    extracted = []
    for path in paths:
        result = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(result, dict) and isinstance(result.get("events"), list):
            run_id = path.stem + "-" + digest(str(path))[:8]
            extracted.extend(extract_experiences(result, run_id=run_id))

    append_jsonl(args.ledger, extracted)
    lessons = distill_lessons(load_jsonl(args.ledger))
    args.lessons.parent.mkdir(parents=True, exist_ok=True)
    args.lessons.write_text(json.dumps(lessons, indent=2) + "\n", encoding="utf-8")

    written = (
        write_promoted_skills(
            lessons, args.skills_dir,
            min_verified=args.min_verified,
            owner_approved=args.owner_approved,
        )
        if args.skills_dir else []
    )
    print(json.dumps({
        "results_scanned": len(paths),
        "experiences_added": len(extracted),
        "lessons": len(lessons),
        "skills_written": [str(path) for path in written],
    }, indent=2))


if __name__ == "__main__":
    main()
