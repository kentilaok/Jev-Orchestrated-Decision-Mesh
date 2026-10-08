import sys
import tempfile
from pathlib import Path
from unittest import TestCase

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from local_resource_governor import enforce_parallel_limit, free_vram_mib
from retrieval import LocalHybridIndex


def tiny_embedder(texts, kind):
    return [[float("invoice" in t.lower()), float("rollback" in t.lower()), 1.0] for t in texts]


class RetrievalScaleTests(TestCase):
    def test_bounded_dense_query_uses_only_id_shortlist(self):
        with tempfile.TemporaryDirectory() as tmp:
            index = LocalHybridIndex(Path(tmp) / "index.db")
            try:
                for name, text in (("a", "Invoices are due monthly"),
                                   ("b", "Rollback deployment on failure"),
                                   ("c", "Invoices require receipts")):
                    index.add_document("demo", name, text)
                index.build_vectors("tiny", tiny_embedder)
                sql = []
                index.db.set_trace_callback(sql.append)
                result = index.search("demo", "invoice receipts", dense_model="tiny",
                                      embedder=tiny_embedder, candidates=2)
                self.assertEqual(result["dense_strategy"], "bounded_lexical_shortlist")
                self.assertTrue(any("c.chunk_id IN (" in s for s in sql))
                self.assertTrue(len(result["results"]) <= 2)
            finally:
                index.close()

    def test_parallel_is_default_off_and_requires_actual_memory(self):
        self.assertEqual(enforce_parallel_limit(1), 1)
        with self.assertRaisesRegex(ValueError, "parallel_local_opt_in_required"):
            enforce_parallel_limit(2)
        with self.assertRaisesRegex(ValueError, "insufficient_verified_vram"):
            enforce_parallel_limit(2, consent=True, free_mib=300)
        self.assertEqual(enforce_parallel_limit(2, consent=True, free_mib=2500), 2)

    def test_gpu_query_unavailable_returns_unknown(self):
        self.assertIsNone(free_vram_mib(runner=lambda argv: "not a number"))
