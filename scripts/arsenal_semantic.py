"""Optional CPU semantic index/reranker for CIDM Arsenal.

This module is deliberately separate from the stdlib-only registry. It requires
FastEmbed only when invoked. Semantic/reranker scores are ranking evidence, not
Fast Path authority.
"""
from __future__ import annotations

import argparse
import json
import math
import sqlite3
from pathlib import Path
from typing import Any

from arsenal_registry import ArsenalRegistry, ArsenalError, require


def _fastembed():
    try:
        from fastembed import TextEmbedding
        from fastembed.rerank.cross_encoder import TextCrossEncoder
    except ImportError as error:
        raise ArsenalError(
            "fastembed_not_installed; install optional dependency: pip install fastembed"
        ) from error
    return TextEmbedding, TextCrossEncoder


def cosine(left: list[float], right: list[float]) -> float:
    require(len(left) == len(right) and bool(left), "embedding_dimension_mismatch")
    dot = sum(x * y for x, y in zip(left, right))
    nl = math.sqrt(sum(x * x for x in left))
    nr = math.sqrt(sum(y * y for y in right))
    if not nl or not nr:
        return 0.0
    return max(-1.0, min(1.0, dot / (nl * nr)))


class SemanticArsenal:
    def __init__(self, db_path: Path):
        self.registry = ArsenalRegistry(db_path)
        self.db = self.registry.db
        self.db.execute(
            """CREATE TABLE IF NOT EXISTS semantic_embeddings(
               skill_id TEXT NOT NULL,
               model_id TEXT NOT NULL,
               skill_hash TEXT NOT NULL,
               vector_json TEXT NOT NULL,
               PRIMARY KEY(skill_id,model_id))"""
        )
        self.db.commit()

    def close(self):
        self.registry.__exit__(None, None, None)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def build(self, model_id: str) -> dict[str, Any]:
        require(isinstance(model_id, str) and model_id.strip(), "embedding_model_required")
        TextEmbedding, _ = _fastembed()
        skills = self.registry.list_skills()
        stale = []
        for skill in skills:
            row = self.db.execute(
                "SELECT skill_hash FROM semantic_embeddings WHERE skill_id=? AND model_id=?",
                (skill["skill_id"], model_id),
            ).fetchone()
            if row is None or row["skill_hash"] != skill["skill_hash"]:
                stale.append(skill)

        if stale:
            model = TextEmbedding(model_name=model_id, lazy_load=True)
            documents = [skill["search_text"][:20_000] for skill in stale]
            vectors = list(model.passage_embed(documents))
            require(len(vectors) == len(stale), "embedding_count_mismatch")
            with self.db:
                for skill, vector in zip(stale, vectors):
                    values = [float(value) for value in vector]
                    require(
                        values and all(math.isfinite(value) for value in values),
                        "invalid_embedding",
                    )
                    self.db.execute(
                        """INSERT OR REPLACE INTO semantic_embeddings
                           (skill_id,model_id,skill_hash,vector_json)
                           VALUES(?,?,?,?)""",
                        (
                            skill["skill_id"],
                            model_id,
                            skill["skill_hash"],
                            json.dumps(values, separators=(",", ":")),
                        ),
                    )

        live_ids = {skill["skill_id"] for skill in skills}
        with self.db:
            for row in self.db.execute(
                "SELECT skill_id FROM semantic_embeddings WHERE model_id=?", (model_id,)
            ).fetchall():
                if row["skill_id"] not in live_ids:
                    self.db.execute(
                        "DELETE FROM semantic_embeddings WHERE skill_id=? AND model_id=?",
                        (row["skill_id"], model_id),
                    )
        return {
            "model_id": model_id,
            "skills": len(skills),
            "embedded_or_refreshed": len(stale),
            "cached": len(skills) - len(stale),
        }

    def query(
        self,
        task: str,
        model_id: str,
        *,
        project_scope: str | None = None,
        top_k: int = 10,
        reranker_model: str | None = None,
    ) -> dict[str, Any]:
        require(isinstance(task, str) and 0 < len(task.strip()) <= 20_000, "invalid_task")
        require(isinstance(top_k, int) and 1 <= top_k <= 50, "invalid_top_k")
        TextEmbedding, TextCrossEncoder = _fastembed()
        model = TextEmbedding(model_name=model_id, lazy_load=True)
        query_vectors = list(model.query_embed(task))
        require(len(query_vectors) == 1, "query_embedding_count_mismatch")
        query_vector = [float(value) for value in query_vectors[0]]

        skills = {skill["skill_id"]: skill for skill in self.registry.list_skills()}
        candidates = []
        for row in self.db.execute(
            "SELECT skill_id,skill_hash,vector_json FROM semantic_embeddings WHERE model_id=?",
            (model_id,),
        ):
            skill = skills.get(row["skill_id"])
            if skill is None or row["skill_hash"] != skill["skill_hash"]:
                continue
            scopes = skill["project_scope"]
            if (
                project_scope is not None
                and project_scope not in scopes
                and "global" not in scopes
            ):
                continue
            vector = [float(value) for value in json.loads(row["vector_json"])]
            candidates.append(
                {
                    "skill_id": skill["skill_id"],
                    "name": skill["name"],
                    "description": skill["description"],
                    "project_scope": scopes,
                    "admitted": skill["admitted"],
                    "risk": skill["risk"],
                    "frontier_required": skill["frontier_required"],
                    "skill_hash": skill["skill_hash"],
                    "manifest_hash": skill["manifest_hash"],
                    "semantic_similarity": round(
                        max(0.0, cosine(query_vector, vector)), 6
                    ),
                    "_document": skill["search_text"][:12_000],
                }
            )

        candidates.sort(
            key=lambda item: item["semantic_similarity"], reverse=True
        )
        shortlist = candidates[: max(top_k * 3, 20)]

        if reranker_model and shortlist:
            reranker = TextCrossEncoder(model_name=reranker_model)
            scores = list(
                reranker.rerank(task, [item["_document"] for item in shortlist])
            )
            require(len(scores) == len(shortlist), "reranker_count_mismatch")
            for item, score in zip(shortlist, scores):
                item["rerank_score"] = float(score)
            shortlist.sort(key=lambda item: item["rerank_score"], reverse=True)

        result = []
        for item in shortlist[:top_k]:
            item = dict(item)
            item.pop("_document", None)
            result.append(item)
        return {
            "decision": "ranking_evidence_only",
            "embedding_model": model_id,
            "reranker_model": reranker_model,
            "project_scope": project_scope,
            "candidates": result,
            "fast_path_authority": False,
        }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Optional FastEmbed semantic/reranker layer for CIDM Arsenal"
    )
    parser.add_argument(
        "--db", type=Path,
        default=Path("~/.jev/arsenal/arsenal.db").expanduser(),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    build = sub.add_parser("build")
    build.add_argument("--model", required=True)

    query = sub.add_parser("query")
    query.add_argument("--task", required=True)
    query.add_argument("--model", required=True)
    query.add_argument("--project-scope")
    query.add_argument("--top-k", type=int, default=10)
    query.add_argument("--reranker-model")

    args = parser.parse_args(argv)
    with SemanticArsenal(args.db) as semantic:
        if args.command == "build":
            result = semantic.build(args.model)
        else:
            result = semantic.query(
                args.task, args.model,
                project_scope=args.project_scope,
                top_k=args.top_k,
                reranker_model=args.reranker_model,
            )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
