"""Unit tests for the study's accounting primitives (no network)."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "harness"))
import cidm_accounting as acc  # noqa: E402


def ev(**kw):
    base = dict(event_id=kw.pop("event_id", "e"), actor=kw.pop("actor", "worker"), status="ok",
                billing_status="billed", record_kind="mock")
    base.update(kw)
    return acc.new_event(**base)


class SchemaTests(unittest.TestCase):
    def test_every_field_present_and_nulls_carry_reasons(self):
        event = acc.new_event(event_id="x", actor="jev")
        self.assertEqual(acc.validate_event(event), [])
        self.assertEqual(event["missing"]["input_tokens"], "not_supplied")
        with self.assertRaises(acc.AccountingError):
            acc.set_field(event, "input_tokens", None, "unavailable")
        acc.set_field(event, "input_tokens", 10, "provider_reported")
        self.assertNotIn("input_tokens", event["missing"])
        self.assertEqual(event["provenance"]["input_tokens"], "provider_reported")

    def test_unknown_fields_and_bad_labels_rejected(self):
        with self.assertRaises(acc.AccountingError):
            acc.new_event(tokens=5)
        with self.assertRaises(acc.AccountingError):
            acc.set_field(acc.new_event(), "input_tokens", 5, "guessed")
        bad = acc.new_event(actor="oracle")
        self.assertIn("bad_actor", acc.validate_event(bad))


class SubsetTests(unittest.TestCase):
    def test_cached_and_reasoning_are_subsets_not_additions(self):
        usage, issues = acc.normalize_openrouter_chat_usage({
            "prompt_tokens": 100, "completion_tokens": 40, "total_tokens": 140, "cost": 0.001,
            "prompt_tokens_details": {"cached_tokens": 60, "cache_write_tokens": 0},
            "completion_tokens_details": {"reasoning_tokens": 30}})
        self.assertEqual(issues, [])
        event = ev(**{k: v for k, v in usage.items()})
        self.assertEqual(acc.io_total(event), 140)

    def test_impossible_subsets_are_flagged(self):
        _, issues = acc.normalize_openrouter_chat_usage({
            "prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 99,
            "prompt_tokens_details": {"cached_tokens": 11}, "completion_tokens_details": {"reasoning_tokens": 6}})
        self.assertIn("cached_exceeds_input", issues)
        self.assertIn("reasoning_exceeds_output", issues)
        self.assertIn("provider_total_not_input_plus_output", issues)

    def test_typesafe_has_no_total_and_is_not_invented(self):
        usage, issues = acc.normalize_typesafe_usage({"input_tokens": 998, "output_tokens": 31, "cost": 4.1916e-05})
        self.assertIsNone(usage["provider_total_tokens"])
        self.assertEqual(acc.io_total(ev(**{k: v for k, v in usage.items()})), 1029)

    def test_missing_usage_is_unknown_not_zero(self):
        usage, issues = acc.normalize_codex_turn_usage(None)
        self.assertIsNone(usage)
        self.assertEqual(issues, ["usage_missing_or_not_object"])
        self.assertIsNone(acc.io_total(ev()))


class CumulativeTests(unittest.TestCase):
    def test_deltas_from_running_totals(self):
        samples = [{"total": {"input_tokens": 100, "output_tokens": 10}, "thread_started_here": True},
                   {"total": {"input_tokens": 250, "output_tokens": 30}},
                   {"total": {"input_tokens": 400, "output_tokens": 35}}]
        deltas, issues = acc.cumulative_to_deltas(samples, fields=("input_tokens", "output_tokens"))
        self.assertEqual([(d["input_tokens"], d["output_tokens"]) for d in deltas], [(100, 10), (150, 20), (150, 5)])
        self.assertEqual(issues, [])
        # summing the cumulative values would triple count
        self.assertNotEqual(sum(s["total"]["input_tokens"] for s in samples), sum(d["input_tokens"] for d in deltas))

    def test_reset_after_compaction_uses_last_or_unknown(self):
        samples = [{"total": {"input_tokens": 900, "output_tokens": 50}, "thread_started_here": True},
                   {"total": {"input_tokens": 300, "output_tokens": 60}, "last": {"input_tokens": 300, "output_tokens": 10}},
                   {"total": {"input_tokens": 100, "output_tokens": 70}}]
        deltas, issues = acc.cumulative_to_deltas(samples, fields=("input_tokens", "output_tokens"))
        self.assertTrue(deltas[1]["reset"])
        self.assertEqual(deltas[1]["input_tokens"], 300)
        self.assertEqual(deltas[1]["source"], "last_after_reset")
        self.assertIsNone(deltas[2]["input_tokens"])
        self.assertEqual(len([i for i in issues if i["issue"] == "cumulative_counter_decreased_reset"]), 2)

    def test_resumed_thread_without_baseline_is_unknown(self):
        deltas, issues = acc.cumulative_to_deltas([{"total": {"input_tokens": 5000}}], fields=("input_tokens",))
        self.assertIsNone(deltas[0]["input_tokens"])
        self.assertEqual(issues[0]["issue"], "first_sample_without_baseline")

    def test_difference_disagreeing_with_last_is_flagged(self):
        samples = [{"total": {"input_tokens": 10}, "thread_started_here": True},
                   {"total": {"input_tokens": 30}, "last": {"input_tokens": 25}}]
        _, issues = acc.cumulative_to_deltas(samples, fields=("input_tokens",))
        self.assertEqual(issues[0]["issue"], "difference_disagrees_with_last")

    def test_parent_rollup_not_double_counted(self):
        parent = {"event_id": "p", "aggregates": ["c1", "c2"], "input_tokens": 30}
        kept, issues = acc.exclude_rollups([parent, {"event_id": "c1"}, {"event_id": "c2"}])
        self.assertEqual([e["event_id"] for e in kept], ["c1", "c2"])
        kept, issues = acc.exclude_rollups([parent, {"event_id": "c1"}])
        self.assertEqual([e["event_id"] for e in kept], ["p"])
        self.assertEqual(issues[0]["missing_children"], ["c2"])


class DedupeTests(unittest.TestCase):
    def test_same_request_id_is_one_call_same_prompt_is_not(self):
        a = ev(event_id="a", provider_request_id="gen-1", prompt_hash="h", input_tokens=10, output_tokens=1,
               source_record="ledger:1")
        a_copy = ev(event_id="a", provider_request_id="gen-1", prompt_hash="h", input_tokens=10, output_tokens=1,
                    source_record="combined:1")
        b = ev(event_id="b", provider_request_id="gen-2", prompt_hash="h", input_tokens=10, output_tokens=1,
               source_record="ledger:2")
        unique, report = acc.dedupe([a, a_copy, b])
        self.assertEqual(len(unique), 2)
        self.assertEqual(len(report["representation_duplicates"]), 1)
        self.assertEqual(report["identical_prompt_distinct_billed_requests"], {"h": ["gen-1", "gen-2"]})

    def test_records_without_ids_are_never_merged(self):
        x = ev(event_id="x", prompt_hash="h", source_record="log:5")
        y = ev(event_id="y", prompt_hash="h", source_record="log:9")
        unique, report = acc.dedupe([x, y])
        self.assertEqual(len(unique), 2)
        self.assertEqual(report["unidentified_records"], ["log:5", "log:9"])

    def test_conflicting_duplicate_is_reported(self):
        a = ev(provider_request_id="g", input_tokens=10, output_tokens=1)
        b = ev(provider_request_id="g", input_tokens=11, output_tokens=1)
        _, report = acc.dedupe([a, b])
        self.assertEqual(report["representation_duplicates"][0]["conflicting_fields"], ["input_tokens"])


class CostTests(unittest.TestCase):
    PRICE = {"input": 2.0, "output": 10.0, "cache_read": 0.2, "cache_write": 2.5}

    def test_disjoint_cache_categories(self):
        event = ev(input_tokens=1000, cached_input_tokens=600, cache_write_tokens=100, output_tokens=50)
        cost, basis = acc.reconstruct_cost(event, self.PRICE)
        expected = (300 * 2.0 + 600 * 0.2 + 100 * 2.5 + 50 * 10.0) / 1e6
        self.assertAlmostEqual(cost, expected)
        self.assertEqual(basis, "complete")

    def test_missing_rate_makes_estimate_unknown(self):
        event = ev(input_tokens=1000, cached_input_tokens=600, cache_write_tokens=0, output_tokens=50)
        cost, basis = acc.reconstruct_cost(event, {"input": 2.0, "output": 10.0})
        self.assertIsNone(cost)
        self.assertEqual(basis, "missing_rate:cache_read")

    def test_matches_recorded_sol_low_charge(self):
        event = ev(input_tokens=527, cached_input_tokens=0, cache_write_tokens=0, output_tokens=82)
        cost, _ = acc.reconstruct_cost(event, self.PRICE)
        self.assertAlmostEqual(cost, 0.001874)

    def test_provider_charge_and_estimate_never_summed(self):
        event = ev(provider_reported_cost=0.01, reconstructed_cost=0.009)
        self.assertEqual(acc.charge_for_totals(event), (0.01, "provider_reported"))
        summary = acc.summarize([event])
        self.assertEqual(list(summary.values())[0]["charge"], 0.01)

    def test_unknown_member_makes_group_total_unknown(self):
        known = ev(event_id="k", input_tokens=5, output_tokens=5, provider_reported_cost=0.1)
        unknown = ev(event_id="u", status="failed", billing_status="unknown")
        summary = acc.summarize([known, unknown])["worker"]
        self.assertIsNone(summary["charge"])
        self.assertIsNone(summary["input_plus_output_tokens"])
        self.assertEqual(summary["unknown_charge_calls"], 1)

    def test_cost_per_accepted_and_negative_savings(self):
        self.assertIsNone(acc.cost_per_accepted(1.0, 0))
        self.assertEqual(acc.cost_per_accepted(1.0, 4), 0.25)
        self.assertAlmostEqual(acc.savings(0.006413654, 0.001726), 1 - 0.006413654 / 0.001726)
        self.assertLess(acc.savings(2.0, 1.0), 0)
        self.assertIsNone(acc.savings(1.0, 0))


if __name__ == "__main__":
    unittest.main()
