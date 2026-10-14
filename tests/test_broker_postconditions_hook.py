"""P0-02 follow-up: `run_with_postconditions` wrapper so callers get the
postcondition gate without invoking the adapter manually. The wrapper lives
alongside `apply_postconditions` and is a thin composition over `broker.run`.
"""

import importlib.util
import sys
import tempfile
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
for name in ("postconditions", "postconditions_broker"):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / (name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)

pc = sys.modules["postconditions"]
pb = sys.modules["postconditions_broker"]


class _StubBroker:
    """Minimal stand-in for NativeTransitionBroker. `run` returns the result
    dict baked at construction, mirroring the shape the real broker produces."""
    def __init__(self, result: dict, candidate: dict | None = None):
        self._result = result
        self._candidate = candidate
        self.ran_with = None

    def run(self, spec, resume=None):
        self.ran_with = {"spec": spec, "resume": resume}
        return self._result


def _check(name, status):
    return pc.PostconditionCheck(
        name=name, kind="synthetic", required=True,
        evaluator=lambda cand, ws: pc.PostconditionResult(
            status=status, evidence={}, reasoning="forced " + status))


class RunWithPostconditionsTests(unittest.TestCase):
    def test_runs_broker_and_passes_spec_through(self):
        broker = _StubBroker({"status": "complete", "answer": "hi"})
        with tempfile.TemporaryDirectory() as td:
            pb.run_with_postconditions(broker, {"goal": "x"},
                                       postconditions=[], workspace=Path(td))
        self.assertEqual(broker.ran_with["spec"], {"goal": "x"})
        self.assertIsNone(broker.ran_with["resume"])

    def test_empty_checks_leaves_result_untouched(self):
        broker = _StubBroker({"status": "complete", "answer": "hi"})
        with tempfile.TemporaryDirectory() as td:
            result = pb.run_with_postconditions(broker, {"goal": "x"},
                                                postconditions=[], workspace=Path(td))
        self.assertEqual(result["status"], "complete")
        self.assertNotIn("postconditions", result)

    def test_passing_checks_mark_release(self):
        broker = _StubBroker({"status": "complete", "answer": "hi"},
                             candidate={"text": "hi", "data": {"unresolved": []}})
        with tempfile.TemporaryDirectory() as td:
            result = pb.run_with_postconditions(broker, {"goal": "x"},
                                                postconditions=[_check("ok", "pass")],
                                                workspace=Path(td))
        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["postconditions"]["decision"], "release")

    def test_failing_check_demotes_complete_result(self):
        broker = _StubBroker({"status": "complete", "answer": "hi"},
                             candidate={"text": "hi", "data": {"unresolved": []}})
        with tempfile.TemporaryDirectory() as td:
            result = pb.run_with_postconditions(broker, {"goal": "x"},
                                                postconditions=[_check("bad", "fail")],
                                                workspace=Path(td))
        self.assertEqual(result["status"], "postconditions_failed")
        self.assertIsNone(result["answer"])
        self.assertEqual(result["postconditions"]["failed"], ["bad"])

    def test_prior_broker_failure_is_preserved(self):
        broker = _StubBroker({"status": "quality_failed", "answer": None},
                             candidate={"text": "x", "data": {"unresolved": []}})
        with tempfile.TemporaryDirectory() as td:
            result = pb.run_with_postconditions(broker, {"goal": "x"},
                                                postconditions=[_check("bad", "fail")],
                                                workspace=Path(td))
        self.assertEqual(result["status"], "quality_failed")
        self.assertEqual(result["postconditions"]["decision"], "withhold")

    def test_resume_argument_is_forwarded(self):
        broker = _StubBroker({"status": "complete", "answer": "hi"})
        with tempfile.TemporaryDirectory() as td:
            pb.run_with_postconditions(broker, {"goal": "x"}, resume={"bundle": {}},
                                       postconditions=[], workspace=Path(td))
        self.assertEqual(broker.ran_with["resume"], {"bundle": {}})

    def test_candidate_source_is_pulled_from_broker_when_available(self):
        """If the broker exposes `last_candidate` (an attribute convention),
        the wrapper feeds that into the adapter so postconditions see the
        richer broker-shape candidate rather than a synthetic shell."""
        candidate = {"text": "with TODO inside", "data": {"unresolved": []}}
        broker = _StubBroker({"status": "complete", "answer": "with TODO inside"})
        broker.last_candidate = candidate
        from scripts import postconditions_coding  # type: ignore  # noqa: F401
        coding = sys.modules.get("postconditions_coding")
        if coding is None:
            spec = importlib.util.spec_from_file_location(
                "postconditions_coding", ROOT / "scripts" / "postconditions_coding.py")
            coding = importlib.util.module_from_spec(spec)
            sys.modules["postconditions_coding"] = coding
            spec.loader.exec_module(coding)
        with tempfile.TemporaryDirectory() as td:
            result = pb.run_with_postconditions(
                broker, {"goal": "x"},
                postconditions=[coding.no_concealed_unresolved()],
                workspace=Path(td))
        # The candidate has 'TODO' in text and no declared unresolved_stages,
        # so no_concealed_unresolved fails → status demoted.
        self.assertEqual(result["status"], "postconditions_failed")


if __name__ == "__main__":
    unittest.main()
