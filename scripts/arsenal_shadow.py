"""Shadow-mode local Arsenal routing.

This module measures what the local cognitive substrate would select without
actually bypassing Jev/frontier execution. It is the calibration path before
enabling CIDM Fast Path.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from arsenal_registry import ArsenalRegistry, canonical


def reciprocal_rank_fusion(
    lexical: list[dict[str, Any]],
    semantic: list[dict[str, Any]],
    *,
    k: int = 60,
) -> list[dict[str, Any]]:
    require_ids = {}
    for source, items in (("lexical", lexical), ("semantic", semantic)):
        for rank, item in enumerate(items, 1):
            skill_id = item["skill_id"]
            entry = require_ids.setdefault(
                skill_id,
                {"skill_id": skill_id, "rrf_score": 0.0, "ranks": {}},
            )
            entry["rrf_score"] += 1.0 / (k + rank)
            entry["ranks"][source] = rank
            for key in (
                "name", "description", "project_scope", "admitted", "risk",
                "frontier_required", "skill_hash", "manifest_hash",
            ):
                if key in item:
                    entry[key] = item[key]
    result = list(require_ids.values())
    result.sort(key=lambda item: item["rrf_score"], reverse=True)
    for item in result:
        item["rrf_score"] = round(item["rrf_score"], 8)
    return result


def run_shadow(
    db_path: Path,
    task: str,
    *,
    project_scope: str | None = None,
    bug_key: str | None = None,
    operation: str | None = None,
    semantic_model: str | None = None,
    reranker_model: str | None = None,
    top_k: int = 10,
) -> dict[str, Any]:
    with ArsenalRegistry(db_path) as registry:
        lexical = registry.match(
            task,
            project_scope=project_scope,
            bug_key=bug_key,
            operation=operation,
            top_k=top_k,
        )

    semantic_result = None
    semantic_candidates: list[dict[str, Any]] = []
    if semantic_model:
        from arsenal_semantic import SemanticArsenal
        with SemanticArsenal(db_path) as semantic:
            semantic_result = semantic.query(
                task,
                semantic_model,
                project_scope=project_scope,
                top_k=top_k,
                reranker_model=reranker_model,
            )
        semantic_candidates = semantic_result["candidates"]

    fused = reciprocal_rank_fusion(
        lexical.get("matches", []), semantic_candidates
    )
    selected = fused[0] if fused else None
    lexical_fast = lexical.get("fast_path") or {}
    lexical_skill = lexical.get("skill_id")
    fast_candidate = bool(
        selected
        and lexical_skill == selected["skill_id"]
        and lexical_fast.get("eligible") is True
    )

    recommendation = (
        "fast_path_candidate"
        if fast_candidate
        else "load_skill_then_jev"
        if selected
        else "jev_only"
    )
    return {
        "mode": "shadow",
        "task": task,
        "project_scope": project_scope,
        "bug_key": bug_key,
        "operation": operation,
        "lexical": lexical,
        "semantic": semantic_result,
        "fused_candidates": fused[:top_k],
        "selected_skill_id": selected["skill_id"] if selected else None,
        "recommendation": recommendation,
        "fast_path_candidate": fast_candidate,
        "frontier_call_avoided": False,
        "would_avoid_frontier_if_fast_path_enabled": fast_candidate,
        "authority": "none_shadow_observation_only",
    }


def append_ledger(path: Path, record: dict[str, Any]) -> None:
    path = Path(path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    event = dict(record)
    event["recorded_at"] = (
        datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    )
    with path.open("a", encoding="utf-8") as stream:
        stream.write(canonical(event) + "\n")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Measure local Arsenal routing without bypassing Jev"
    )
    parser.add_argument(
        "--db", type=Path,
        default=Path("~/.jev/arsenal/arsenal.db").expanduser(),
    )
    parser.add_argument("--task", required=True)
    parser.add_argument("--project-scope")
    parser.add_argument("--bug-key")
    parser.add_argument("--operation")
    parser.add_argument("--semantic-model")
    parser.add_argument("--reranker-model")
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument(
        "--ledger", type=Path,
        default=Path("~/.jev/arsenal/shadow.jsonl").expanduser(),
    )
    args = parser.parse_args(argv)

    result = run_shadow(
        args.db,
        args.task,
        project_scope=args.project_scope,
        bug_key=args.bug_key,
        operation=args.operation,
        semantic_model=args.semantic_model,
        reranker_model=args.reranker_model,
        top_k=args.top_k,
    )
    append_ledger(args.ledger, result)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
