import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from local_continuity_evaluation import summarize_run, summarize_folder


class LocalPilotEvaluationTests(unittest.TestCase):
    def test_report_never_invents_verified_quality_or_cost(self):
        item = {"mode": "local_only", "task_snapshot_hash": "snapshot",
                "status": "withheld_pending_independent_validation",
                "jev_calls": 0, "remote_worker_calls": 0,
                "execution": {"results": {
                    "A": {"status": "unverified_proposal", "usage": {"input_tokens": 20, "output_tokens": 5},
                          "model_identity": {"served": "qwen"}},
                    "B": {"status": "failed", "usage": None}}},
                "comparison": {"agreement": "not_comparable"}}
        line = summarize_run(item)
        self.assertIsNone(line["verified_correctness"])
        self.assertEqual(line["lanes"]["A"]["input_tokens"], 20)
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "test" / "result.json"
            path.parent.mkdir()
            path.write_text(json.dumps(item), encoding="utf-8")
            result = summarize_folder(temp)
        self.assertEqual(result["runs"], 1)
        self.assertEqual(result["local_lane_usage_reported"], 1)
        self.assertIsNone(result["claimed_cost_savings_usd"])
        self.assertIsNone(result["verified_quality_advantage"])

    def test_foreign_result_rejected(self):
        with self.assertRaisesRegex(ValueError, "not_local_continuity_result"):
            summarize_run({"mode": "frontier_only"})
