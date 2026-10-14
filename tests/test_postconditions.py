"""P0-02 slice 1: postcondition protocol.

A production task declares one or more postconditions it must satisfy before
the broker releases the candidate. Each check is a small, deterministic
evaluator that returns one of {pass, fail, unresolved} and the evidence that
justifies the status. The runner collects results and gives the broker a
single release/withhold decision.
"""

import importlib.util
import json
import sys
import tempfile
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "scripts" / "postconditions.py"
spec = importlib.util.spec_from_file_location("postconditions", MODULE)
pc = importlib.util.module_from_spec(spec)
# dataclass() looks up module globals via sys.modules; register before exec.
sys.modules["postconditions"] = pc
spec.loader.exec_module(pc)


class PostconditionResultTests(unittest.TestCase):
    def test_result_requires_status_and_evidence_and_reasoning(self):
        result = pc.PostconditionResult(status="pass", evidence={"exit": 0},
                                        reasoning="build command returned 0")
        self.assertEqual(result.status, "pass")
        self.assertEqual(result.evidence["exit"], 0)
        self.assertEqual(result.reasoning, "build command returned 0")

    def test_result_rejects_unknown_status(self):
        with self.assertRaises(ValueError):
            pc.PostconditionResult(status="maybe", evidence={}, reasoning="")

    def test_result_rejects_empty_reasoning(self):
        with self.assertRaises(ValueError):
            pc.PostconditionResult(status="pass", evidence={}, reasoning="")


class PostconditionCheckTests(unittest.TestCase):
    def _always(self, status, name="example"):
        return pc.PostconditionCheck(
            name=name, kind="synthetic", required=True,
            evaluator=lambda candidate, workspace: pc.PostconditionResult(
                status=status, evidence={}, reasoning="forced " + status))

    def test_check_has_name_kind_required_and_evaluator(self):
        check = self._always("pass")
        self.assertEqual(check.name, "example")
        self.assertEqual(check.kind, "synthetic")
        self.assertTrue(check.required)

    def test_optional_check_can_be_declared(self):
        check = pc.PostconditionCheck(name="x", kind="synthetic", required=False,
                                      evaluator=lambda c, w: pc.PostconditionResult(
                                          status="pass", evidence={}, reasoning="ok"))
        self.assertFalse(check.required)

    def test_check_name_cannot_be_empty(self):
        with self.assertRaises(ValueError):
            pc.PostconditionCheck(name="", kind="synthetic", required=True,
                                  evaluator=lambda c, w: None)


class RunnerTests(unittest.TestCase):
    def _check(self, name, status, required=True):
        return pc.PostconditionCheck(
            name=name, kind="synthetic", required=required,
            evaluator=lambda candidate, workspace: pc.PostconditionResult(
                status=status, evidence={}, reasoning="forced " + status))

    def test_runner_returns_release_when_all_required_pass(self):
        with tempfile.TemporaryDirectory() as td:
            report = pc.run_checks([self._check("a", "pass"), self._check("b", "pass")],
                                   candidate={}, workspace=Path(td))
        self.assertEqual(report.decision, "release")
        self.assertEqual(len(report.results), 2)
        self.assertEqual(report.failed, [])
        self.assertEqual(report.unresolved, [])

    def test_runner_withholds_when_any_required_fails(self):
        with tempfile.TemporaryDirectory() as td:
            report = pc.run_checks([self._check("a", "pass"),
                                    self._check("b", "fail")],
                                   candidate={}, workspace=Path(td))
        self.assertEqual(report.decision, "withhold")
        self.assertEqual(report.failed, ["b"])

    def test_runner_withholds_when_any_required_is_unresolved(self):
        with tempfile.TemporaryDirectory() as td:
            report = pc.run_checks([self._check("a", "unresolved")],
                                   candidate={}, workspace=Path(td))
        self.assertEqual(report.decision, "withhold")
        self.assertEqual(report.unresolved, ["a"])

    def test_runner_tolerates_optional_fail(self):
        """An optional check that fails must not block release, but must be
        reported in the results for audit."""
        with tempfile.TemporaryDirectory() as td:
            report = pc.run_checks([self._check("req", "pass"),
                                    self._check("opt", "fail", required=False)],
                                   candidate={}, workspace=Path(td))
        self.assertEqual(report.decision, "release")
        self.assertEqual([r.name for r in report.results if r.status == "fail"], ["opt"])

    def test_runner_captures_evaluator_exception_as_unresolved(self):
        def boom(candidate, workspace):
            raise RuntimeError("evaluator exploded")
        check = pc.PostconditionCheck(name="boom", kind="synthetic", required=True,
                                      evaluator=boom)
        with tempfile.TemporaryDirectory() as td:
            report = pc.run_checks([check], candidate={}, workspace=Path(td))
        self.assertEqual(report.decision, "withhold")
        self.assertEqual(report.unresolved, ["boom"])
        self.assertIn("evaluator exploded", report.results[0].reasoning)

    def test_report_is_json_serialisable(self):
        with tempfile.TemporaryDirectory() as td:
            report = pc.run_checks([self._check("a", "pass")],
                                   candidate={}, workspace=Path(td))
            text = json.dumps(report.as_dict())
            loaded = json.loads(text)
        self.assertEqual(loaded["decision"], "release")
        self.assertEqual(loaded["results"][0]["name"], "a")


if __name__ == "__main__":
    unittest.main()
