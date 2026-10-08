import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from arsenal_semantic import SemanticArsenal, cosine


def skill_text(name, words):
    return f"""---
name: {name}
description: {words}
---

# {name}

## Trigger

- Observed symptom: {words}
"""


class FakeEmbedding:
    def __init__(self, model_name, lazy_load=True):
        self.model_name = model_name

    def vector(self, text):
        text = text.lower()
        if "memberpress" in text or "protected" in text:
            return [1.0, 0.0]
        if "roblox" in text or "attachment" in text:
            return [0.0, 1.0]
        return [0.5, 0.5]

    def passage_embed(self, documents):
        return iter([self.vector(text) for text in documents])

    def query_embed(self, query):
        if isinstance(query, str):
            return iter([self.vector(query)])
        return iter([self.vector(text) for text in query])


class FakeReranker:
    def __init__(self, model_name):
        self.model_name = model_name

    def rerank(self, query, documents):
        query = query.lower()
        return [
            10.0 if ("memberpress" in query and "memberpress" in doc.lower()) else
            9.0 if ("roblox" in query and "roblox" in doc.lower()) else 0.0
            for doc in documents
        ]


class ArsenalSemanticTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.skills = self.root / "skills"
        self.skills.mkdir()
        left = self.skills / "memberpress-help"
        left.mkdir()
        (left / "SKILL.md").write_text(
            skill_text(
                "memberpress-help",
                "MemberPress protected product visible while signed out",
            ),
            encoding="utf-8",
        )
        right = self.skills / "roblox-attachment"
        right.mkdir()
        (right / "SKILL.md").write_text(
            skill_text(
                "roblox-attachment",
                "Roblox attachment lookup from the owning weapon root",
            ),
            encoding="utf-8",
        )
        self.db = self.root / "arsenal.db"

    def test_cosine_is_bounded_and_detects_identity(self):
        self.assertEqual(cosine([1.0, 0.0], [1.0, 0.0]), 1.0)
        self.assertEqual(cosine([1.0, 0.0], [0.0, 1.0]), 0.0)

    @patch("arsenal_semantic._fastembed", return_value=(FakeEmbedding, FakeReranker))
    def test_build_caches_skill_embeddings_by_hash(self, _):
        with SemanticArsenal(self.db) as semantic:
            semantic.registry.scan(self.skills)
            first = semantic.build("fake-embed")
            second = semantic.build("fake-embed")
        self.assertEqual(first["embedded_or_refreshed"], 2)
        self.assertEqual(second["embedded_or_refreshed"], 0)
        self.assertEqual(second["cached"], 2)

    @patch("arsenal_semantic._fastembed", return_value=(FakeEmbedding, FakeReranker))
    def test_semantic_query_ranks_relevant_skill_without_authority(self, _):
        with SemanticArsenal(self.db) as semantic:
            semantic.registry.scan(self.skills)
            semantic.build("fake-embed")
            result = semantic.query(
                "MemberPress content remains visible to logged out visitors",
                "fake-embed",
                top_k=2,
            )
        self.assertEqual(result["decision"], "ranking_evidence_only")
        self.assertEqual(result["candidates"][0]["skill_id"], "memberpress-help")
        self.assertFalse(result["fast_path_authority"])

    @patch("arsenal_semantic._fastembed", return_value=(FakeEmbedding, FakeReranker))
    def test_optional_reranker_is_explicit_and_preserves_no_authority(self, _):
        with SemanticArsenal(self.db) as semantic:
            semantic.registry.scan(self.skills)
            semantic.build("fake-embed")
            result = semantic.query(
                "Roblox attachment error",
                "fake-embed",
                reranker_model="fake-reranker",
                top_k=2,
            )
        self.assertEqual(result["candidates"][0]["skill_id"], "roblox-attachment")
        self.assertIn("rerank_score", result["candidates"][0])
        self.assertEqual(result["reranker_model"], "fake-reranker")
        self.assertFalse(result["fast_path_authority"])

    @patch("arsenal_semantic._fastembed", return_value=(FakeEmbedding, FakeReranker))
    def test_changed_skill_hash_requires_embedding_refresh(self, _):
        with SemanticArsenal(self.db) as semantic:
            semantic.registry.scan(self.skills)
            semantic.build("fake-embed")
            path = self.skills / "memberpress-help" / "SKILL.md"
            with path.open("a", encoding="utf-8") as stream:
                stream.write("\nAdditional verified context.\n")
            semantic.registry.scan(self.skills)
            result = semantic.build("fake-embed")
        self.assertEqual(result["embedded_or_refreshed"], 1)


if __name__ == "__main__":
    unittest.main()
