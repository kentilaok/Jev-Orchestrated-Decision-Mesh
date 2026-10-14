"""P0-02 slice 3: wiring postconditions into the broker's acceptance step.

The integration surface is a thin adapter module that:
- maps the broker's internal candidate shape to the generic postconditions
  candidate shape (output / files_changed / unresolved_stages);
- runs the declared checks via postconditions.run_checks;
- mutates the broker's result dict in place: adds a 'postconditions' entry
  (serialised report) and, on withhold, demotes 'status' and clears 'answer'.

Keeping the integration out of NativeTransitionBroker itself avoids editing
the complex invariant-heavy class and keeps the broker tree-shakable: a
caller that does not want postconditions simply does not import this module.
"""

import importlib.util
import json
import sys
import tempfile
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


def _load(name):
    path = ROOT / "scripts" / (name + ".py")
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


pc = _load("postconditions")
pb = _load("postconditions_broker")


class ExtractCandidateFieldsTests(unittest.TestCase):
    """Adapter: broker-style candidate -> generic postconditions candidate."""

    def test_extracts_text_as_output(self):
        broker_candidate = {
            "text": "Done. Build passes.",
            "data": {"summary": "ok", "claims": ["builds"], "unresolved": [],
                     "parent_hashes": [], "source_hashes": []},
            "source_ids": ["s1"], "five_scores": [3, 3, 3, 3, 3], "self_probability": 0.7,
        }
        fields = pb.extract_candidate_fields(broker_candidate, declared_files=["a.py"])
        self.assertEqual(fields["output"], "Done. Build passes.")
        self.assertEqual(fields["files_changed"], ["a.py"])

    def test_maps_data_unresolved_to_unresolved_stages(self):
        broker_candidate = {
            "text": "x", "data": {"summary": "x", "claims": [], "unresolved": ["parser incomplete"],
                                   "parent_hashes": [], "source_hashes": []},
            "source_ids": ["s1"], "five_scores": [3]*5, "self_probability": None,
        }
        fields = pb.extract_candidate_fields(broker_candidate, declared_files=[])
        self.assertEqual(fields["unresolved_stages"], ["parser incomplete"])

    def test_empty_broker_candidate_yields_safe_defaults(self):
        fields = pb.extract_candidate_fields({}, declared_files=[])
        self.assertEqual(fields["output"], "")
        self.assertEqual(fields["files_changed"], [])
        self.assertEqual(fields["unresolved_stages"], [])


class ApplyPostconditionsTests(unittest.TestCase):
    """Core integration: a broker result is mutated based on run_checks()."""

    def _always(self, name, status):
        return pc.PostconditionCheck(
            name=name, kind="synthetic", required=True,
            evaluator=lambda cand, ws: pc.PostconditionResult(
                status=status, evidence={}, reasoning="forced " + status))

    def _broker_result(self, status="complete", answer="hi"):
        return {"status": status, "answer": answer,
                "route": "short_self_contained", "gate_policy": "legacy",
                "calls": []}

    def test_release_leaves_result_unchanged_but_records_report(self):
        with tempfile.TemporaryDirectory() as td:
            result = self._broker_result()
            new = pb.apply_postconditions(result=result, broker_candidate={},
                                          declared_files=[], workspace=Path(td),
                                          checks=[self._always("ok", "pass")])
        self.assertIs(new, result)
        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["answer"], "hi")
        self.assertEqual(result["postconditions"]["decision"], "release")

    def test_withhold_demotes_status_and_clears_answer(self):
        """The P0-02 pass-condition surface: a candidate that was structurally
        valid (status=complete) MUST be demoted when postconditions withhold."""
        with tempfile.TemporaryDirectory() as td:
            result = self._broker_result()
            pb.apply_postconditions(result=result, broker_candidate={},
                                    declared_files=[], workspace=Path(td),
                                    checks=[self._always("bad", "fail")])
        self.assertEqual(result["status"], "postconditions_failed")
        self.assertIsNone(result["answer"])
        self.assertEqual(result["postconditions"]["decision"], "withhold")
        self.assertEqual(result["postconditions"]["failed"], ["bad"])

    def test_empty_checks_list_is_a_noop(self):
        with tempfile.TemporaryDirectory() as td:
            result = self._broker_result()
            pb.apply_postconditions(result=result, broker_candidate={},
                                    declared_files=[], workspace=Path(td), checks=[])
        self.assertEqual(result["status"], "complete")
        self.assertNotIn("postconditions", result)

    def test_withhold_does_not_overwrite_non_complete_status(self):
        """If the broker already failed structurally, keep its diagnosis."""
        with tempfile.TemporaryDirectory() as td:
            result = self._broker_result(status="quality_failed", answer=None)
            pb.apply_postconditions(result=result, broker_candidate={},
                                    declared_files=[], workspace=Path(td),
                                    checks=[self._always("bad", "fail")])
        # Status stays quality_failed; postconditions report is still recorded
        # so operators see both failure modes.
        self.assertEqual(result["status"], "quality_failed")
        self.assertEqual(result["postconditions"]["decision"], "withhold")

    def test_report_is_json_serialisable(self):
        with tempfile.TemporaryDirectory() as td:
            result = self._broker_result()
            pb.apply_postconditions(result=result, broker_candidate={},
                                    declared_files=[], workspace=Path(td),
                                    checks=[self._always("ok", "pass")])
            text = json.dumps(result["postconditions"])
        self.assertIn("release", text)


class PassConditionTests(unittest.TestCase):
    """P0-02 pass condition at the shape layer: a known-wrong yet schema-
    valid candidate (TODO in output, no unresolved_stages declared) is
    refused by the integrated path."""

    def test_schema_valid_candidate_with_concealed_todo_is_refused(self):
        from scripts import postconditions_coding  # noqa: E402
        coding = sys.modules["postconditions_coding"] = _load("postconditions_coding")
        check = coding.no_concealed_unresolved()
        broker_candidate = {
            "text": "All green. TODO: finish the parser later.",
            "data": {"summary": "ok", "claims": ["builds"], "unresolved": [],
                     "parent_hashes": [], "source_hashes": []},
            "source_ids": ["s1"], "five_scores": [4]*5, "self_probability": 0.8,
        }
        with tempfile.TemporaryDirectory() as td:
            result = {"status": "complete", "answer": broker_candidate["text"]}
            pb.apply_postconditions(result=result, broker_candidate=broker_candidate,
                                    declared_files=[], workspace=Path(td),
                                    checks=[check])
        self.assertEqual(result["status"], "postconditions_failed")
        self.assertIsNone(result["answer"])
        self.assertEqual(result["postconditions"]["failed"], ["no_concealed_unresolved"])


if __name__ == "__main__":
    unittest.main()
