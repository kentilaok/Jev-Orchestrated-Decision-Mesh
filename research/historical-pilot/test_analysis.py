"""Offline accounting and reporting invariants; no provider calls."""
import json
import tempfile
import unittest
from pathlib import Path

from analyze import analyze, aggregate_events, normalize_usage, paired_quality, savings_bootstrap


def fixture():
    tasks, gold, ledger, runs = [], {}, [], []
    for index in range(14):
        task_id = f"t{index:02d}"
        phase = "development" if index < 2 else "evaluation"
        stratum = ["short_direct", "noisy_retrieval", "cross_document"][(index-2)//4] if index >= 2 else "short_direct"
        tasks.append({"id": task_id, "split": phase, "stratum": stratum,
                      "query": "Return x", "documents": [{"id": "d1", "text": "x is 1"}], "answer_fields": ["x"]})
        gold[task_id] = {"id": task_id, "split": phase, "stratum": stratum,
                         "answers": {"x": 1}, "evidence": {"x": {"groups": [["d1"]], "allowed": ["d1"]}}, "status": "complete"}
        for arm in ("A", "B"):
            events = []
            for role, input_tokens, output_tokens in ([("worker", 100, 20)] if arm == "A" else [("worker", 60, 20), ("jev", 10, 5)]):
                event = {"event_id": f"{task_id}-{arm}-{role}", "task_id": task_id,
                         "replicate": 0, "arm": arm, "phase": phase, "role": role,
                         "stage": "answer" if role == "worker" else "review", "status": "ok",
                         "model_requested": "fixed-sol" if role == "worker" else "jev",
                         "model_returned": "fixed-sol" if role == "worker" else "jev", "latency_ms": 10,
                         "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens,
                                   "total_tokens": input_tokens + output_tokens,
                                   "reasoning_tokens": 2, "cached_input_tokens": 4, "cost": 0.001}}
                events.append(event)
                ledger.append(event)
            runs.append({"task_id": task_id, "replicate": 0, "arm": arm, "phase": phase,
                         "status": "complete", "released": True, "elapsed_seconds": 0.03,
                         "candidate": {"answers": {"x": 1}, "evidence": {"x": ["d1"]}, "status": "complete"},
                         "event_ids": [e["event_id"] for e in events]})
    return tasks, gold, ledger, runs


class AccountingTests(unittest.TestCase):
    def test_reasoning_and_cache_are_not_counted_twice(self):
        event = {"usage": {"input_tokens": 100, "output_tokens": 30,
                           "reasoning_tokens": 20, "cached_input_tokens": 50}}
        usage = normalize_usage(event)
        self.assertEqual(usage["total_tokens"], 130)
        self.assertEqual(usage["total_source"], "input_plus_output")
        self.assertIsNone(usage["cost"])

    def test_authoritative_total_takes_precedence(self):
        self.assertEqual(normalize_usage({"usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 17}})["total_tokens"], 17)

    def test_unknown_jev_output_is_unknown_not_zero(self):
        event = {"role": "jev", "usage": {"input_tokens": 15, "output_tokens": None, "total_tokens": None}}
        usage = aggregate_events([event])
        self.assertFalse(usage["total_tokens"]["complete"])
        self.assertEqual(usage["total_tokens"]["unknown_events"], 1)
        self.assertEqual(usage["input_tokens"]["known_sum"], 15)

    def test_invalid_numeric_usage_is_not_known(self):
        usage = normalize_usage({"usage": {"input_tokens": True, "output_tokens": -1, "total_tokens": "10", "cost": float("nan")}})
        self.assertTrue(all(usage[k] is None for k in ("input_tokens", "output_tokens", "total_tokens", "cost")))

    def test_zero_billing_is_distinct_from_missing_billing(self):
        self.assertTrue(aggregate_events([{"usage": {"cost": 0}}])["cost"]["complete"])
        self.assertFalse(aggregate_events([{"usage": {"cost": None}}])["cost"]["complete"])

    def test_all_success_quality_retains_uncertainty(self):
        result = paired_quality([(True, True)] * 12)
        self.assertEqual(result["difference_B_minus_A"], 0)
        self.assertLess(result["ci95"][0], 0)
        self.assertGreater(result["ci95"][1], 0)

    def test_paired_quality_counts_direction_correctly(self):
        result = paired_quality([(False, True), (False, True), (True, False), (True, True)])
        self.assertEqual(result["A_fail_B_pass"], 2)
        self.assertEqual(result["A_pass_B_fail"], 1)
        self.assertEqual(result["difference_B_minus_A"], 0.25)
        self.assertLessEqual(result["ci95"][0], 0.25)
        self.assertGreaterEqual(result["ci95"][1], 0.25)

    def test_bootstrap_respects_seed_and_strata(self):
        rows = [{"stratum": str(index // 4), "A": {"tokens": 100 + index}, "B": {"tokens": 40 + 2*index}} for index in range(12)]
        first = savings_bootstrap(rows, "tokens", draws=100)
        self.assertEqual(first, savings_bootstrap(rows, "tokens", draws=100))
        self.assertEqual(first["strata"], {"0": 4, "1": 4, "2": 4})
        self.assertAlmostEqual(first["savings_rate"], 1-sum(40+2*i for i in range(12))/sum(100+i for i in range(12)))


class IntegrationTests(unittest.TestCase):
    def run_analysis(self, mutate=None):
        tasks, gold, ledger, runs = fixture()
        if mutate:
            mutate(tasks, gold, ledger, runs)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "tasks.json").write_text(json.dumps({"tasks": tasks}), encoding="utf-8")
            (root / "gold.json").write_text(json.dumps({"tasks": gold}), encoding="utf-8")
            for name, records in (("ledger", ledger), ("runs", runs)):
                (root / f"{name}.jsonl").write_text("".join(json.dumps(record)+"\n" for record in records), encoding="utf-8")
            result = analyze(root / "tasks.json", root / "gold.json", root / "ledger.jsonl", root / "runs.jsonl", root / "out", bootstrap_replicates=100)
            self.assertTrue((root / "out" / "results.json").is_file())
            self.assertTrue((root / "out" / "task_results.csv").is_file())
            self.assertIn("unmetered", (root / "out" / "summary.md").read_text(encoding="utf-8"))
            return result

    def test_complete_paired_accounting(self):
        result = self.run_analysis()
        evaluation = result["phases"]["evaluation"]
        self.assertEqual(evaluation["issues"], [])
        self.assertTrue(evaluation["full_token_result_admissible"])
        self.assertTrue(evaluation["full_cost_result_admissible"])
        self.assertEqual(evaluation["token_savings"]["A_sum"], 12*120)
        self.assertEqual(evaluation["token_savings"]["B_sum"], 12*95)
        self.assertEqual(result["phases"]["development"]["token_savings"]["A_sum"], 2*120)
        self.assertEqual(evaluation["arms"]["A"]["quality"]["served_task_passes"], 12)

    def test_rejected_correct_candidate_has_zero_served_credit(self):
        def mutate(tasks, gold, ledger, runs):
            next(r for r in runs if r["task_id"] == "t02" and r["arm"] == "B")["released"] = False
        result = self.run_analysis(mutate)["phases"]["evaluation"]
        quality = result["arms"]["B"]["quality"]
        self.assertEqual(quality["served_task_passes"], 11)
        self.assertEqual(quality["raw_candidate_task_passes"], 12)
        self.assertEqual(quality["withheld_correct_candidates"], 1)
        self.assertTrue(result["full_token_result_admissible"])

    def test_unknown_jev_output_prevents_full_result(self):
        def mutate(tasks, gold, ledger, runs):
            event = next(e for e in ledger if e["task_id"] == "t02" and e["role"] == "jev")
            event["usage"]["output_tokens"] = None
            event["usage"]["total_tokens"] = None
        result = self.run_analysis(mutate)["phases"]["evaluation"]
        self.assertFalse(result["full_token_result_admissible"])
        self.assertIsNone(result["token_savings"])
        self.assertEqual(result["arms"]["B"]["accounting"]["total_tokens"]["unknown_events"], 1)

    def test_auth_failure_stays_in_denominator(self):
        def mutate(tasks, gold, ledger, runs):
            run = next(r for r in runs if r["task_id"] == "t02" and r["arm"] == "A")
            run.update(status="failed", released=False, candidate=None)
            event = next(e for e in ledger if e["event_id"] == run["event_ids"][0])
            event.update(status="failed", error="HTTP 401", usage={})
        result = self.run_analysis(mutate)["phases"]["evaluation"]
        self.assertFalse(result["full_token_result_admissible"])
        self.assertFalse(result["full_cost_result_admissible"])
        self.assertEqual(result["failed_attempts"], 1)
        self.assertEqual(result["arms"]["A"]["quality"]["scheduled_runs"], 12)
        self.assertEqual(result["arms"]["A"]["quality"]["served_task_passes"], 11)

    def test_missing_linkage_prevents_full_result(self):
        def mutate(tasks, gold, ledger, runs):
            next(r for r in runs if r["task_id"] == "t02" and r["arm"] == "B")["event_ids"].pop()
        result = self.run_analysis(mutate)["phases"]["evaluation"]
        self.assertFalse(result["full_token_result_admissible"])
        self.assertTrue(any("coverage differs" in issue for issue in result["issues"]))

    def test_missing_billing_only_invalidates_cost(self):
        def mutate(tasks, gold, ledger, runs):
            next(e for e in ledger if e["phase"] == "evaluation")["usage"]["cost"] = None
        result = self.run_analysis(mutate)["phases"]["evaluation"]
        self.assertTrue(result["full_token_result_admissible"])
        self.assertFalse(result["full_cost_result_admissible"])
        self.assertIsNone(result["cost_savings"])

    def test_ambiguous_duplicate_events_invalidate_accounting(self):
        def mutate(tasks, gold, ledger, runs):
            ledger.append(dict(next(e for e in ledger if e["phase"] == "evaluation")))
        result = self.run_analysis(mutate)["phases"]["evaluation"]
        self.assertFalse(result["full_token_result_admissible"])
        self.assertTrue(any("duplicate" in issue for issue in result["issues"]))

    def test_known_failed_retry_is_counted(self):
        def mutate(tasks, gold, ledger, runs):
            run = next(r for r in runs if r["task_id"] == "t02" and r["arm"] == "A")
            event = dict(next(e for e in ledger if e["event_id"] == run["event_ids"][0]))
            event.update(event_id="retry-failed", status="failed")
            ledger.append(event)
            run["event_ids"].append(event["event_id"])
        result = self.run_analysis(mutate)["phases"]["evaluation"]
        self.assertTrue(result["full_token_result_admissible"])
        self.assertEqual(result["token_savings"]["A_sum"], 13*120)
        self.assertEqual(result["failed_attempts"], 1)


if __name__ == "__main__":
    unittest.main()
