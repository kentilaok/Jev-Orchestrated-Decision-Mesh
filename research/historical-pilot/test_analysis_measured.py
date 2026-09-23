"""Synthetic regressions for the measurement correction; no evaluation data read."""
import json
import tempfile
import unittest
from pathlib import Path

from analyze_measured import analyze
from test_analysis import fixture


class MeasurementCorrectionTests(unittest.TestCase):
    def evaluate(self, mutate):
        tasks, gold, ledger, runs = fixture()
        mutate(tasks, gold, ledger, runs)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "tasks.json").write_text(json.dumps({"tasks": tasks}), encoding="utf-8")
            (root / "gold.json").write_text(json.dumps({"tasks": gold}), encoding="utf-8")
            for name, records in (("ledger", ledger), ("runs", runs)):
                (root / f"{name}.jsonl").write_text("".join(json.dumps(record)+"\n" for record in records), encoding="utf-8")
            return analyze(root / "tasks.json", root / "gold.json", root / "ledger.jsonl", root / "runs.jsonl", root / "out", bootstrap_replicates=100)

    def test_metered_failed_rejected_candidate_retains_consumption(self):
        def mutate(tasks, gold, ledger, runs):
            next(r for r in runs if r["task_id"] == "t02" and r["arm"] == "B").update(status="failed", released=False)
        result = self.evaluate(mutate)["phases"]["evaluation"]
        self.assertTrue(result["full_token_result_admissible"])
        self.assertTrue(result["full_cost_result_admissible"])
        self.assertEqual(result["token_savings"]["B_sum"], 12*95)
        self.assertEqual(result["cost_savings"]["B_sum"], 24*0.001)
        quality = result["arms"]["B"]["quality"]
        self.assertEqual(quality["served_task_passes"], 11)
        self.assertEqual(quality["raw_candidate_task_passes"], 12)
        self.assertEqual(quality["withheld_correct_candidates"], 1)
        self.assertEqual(quality["recorded_runs"], 12)
        self.assertEqual(result["paired_served_quality"]["paired_tasks"], 12)

    def test_expected_null_partial_answer_can_pass_served_and_raw(self):
        def mutate(tasks, gold, ledger, runs):
            gold["t02"]["answers"]["x"] = None
            gold["t02"]["status"] = "partial"
            for run in runs:
                if run["task_id"] == "t02":
                    run["candidate"]["answers"]["x"] = None
                    run["candidate"]["status"] = "partial"
                    run["status"] = "partial"
        result = self.evaluate(mutate)
        evaluation = result["phases"]["evaluation"]
        self.assertTrue(evaluation["full_token_result_admissible"])
        for arm in ("A", "B"):
            self.assertEqual(evaluation["arms"][arm]["quality"]["served_task_passes"], 12)
            self.assertEqual(evaluation["arms"][arm]["quality"]["partial_runs"], 1)
        for detail in result["per_task_grades"]:
            if detail["task_id"] == "t02":
                self.assertTrue(detail["served_grade"]["task_pass"])
                self.assertTrue(detail["raw_candidate_grade"]["task_pass"])

    def test_metered_early_failure_counts_only_actual_calls(self):
        def mutate(tasks, gold, ledger, runs):
            run = next(r for r in runs if r["task_id"] == "t02" and r["arm"] == "B")
            worker = next(e for e in ledger if e["task_id"] == "t02" and e["arm"] == "B" and e["role"] == "worker")
            ledger.remove(worker)
            run["event_ids"].remove(worker["event_id"])
            run.update(status="failed", candidate=None, released=False)
            next(e for e in ledger if e["event_id"] == run["event_ids"][0])["status"] = "failed"
        result = self.evaluate(mutate)["phases"]["evaluation"]
        self.assertTrue(result["full_token_result_admissible"])
        self.assertTrue(result["full_cost_result_admissible"])
        self.assertEqual(result["token_savings"]["B_sum"], 12*95-80)
        self.assertEqual(result["failed_attempts"], 1)
        self.assertEqual(result["arms"]["B"]["quality"]["served_task_passes"], 11)

    def test_unmetered_failure_still_prevents_consumption_claim(self):
        def mutate(tasks, gold, ledger, runs):
            run = next(r for r in runs if r["task_id"] == "t02" and r["arm"] == "B")
            run.update(status="failed", candidate=None, released=False)
            next(e for e in ledger if e["event_id"] == run["event_ids"][0]).update(status="failed", usage={})
        result = self.evaluate(mutate)["phases"]["evaluation"]
        self.assertFalse(result["full_token_result_admissible"])
        self.assertFalse(result["full_cost_result_admissible"])
        self.assertEqual(result["arms"]["B"]["quality"]["scheduled_runs"], 12)


if __name__ == "__main__":
    unittest.main()
