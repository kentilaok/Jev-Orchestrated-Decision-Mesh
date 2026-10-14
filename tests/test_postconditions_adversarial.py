"""P0-02 slice 4 adversarial corpus.

Iterate the fixtures under tests/fixtures/postconditions/ and assert the
integrated adapter + runner reaches the expected decision for each. The
corpus is where the P0-02 pass condition is proven on data, not synthetic
checks: known-wrong candidates that would pass structural validation are
refused; a transparent candidate with declared unresolved stages passes.
"""

import importlib.util
import json
import sys
import tempfile
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "postconditions"


def _load(name):
    path = ROOT / "scripts" / (name + ".py")
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


_load("postconditions")
pb = _load("postconditions_broker")
coding = _load("postconditions_coding")


CHECK_FACTORIES = {
    "no_concealed_unresolved": coding.no_concealed_unresolved,
}


def _list_fixtures():
    assert FIXTURES.is_dir(), "fixture directory missing: " + str(FIXTURES)
    return sorted(FIXTURES.glob("*.json"))


class AdversarialCorpusTests(unittest.TestCase):
    """Every fixture reaches its declared expected_decision."""

    def _run_fixture(self, fixture_path: Path) -> dict:
        fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
        checks = [CHECK_FACTORIES[name]() for name in fixture["checks"]]
        result = {"status": "complete", "answer": fixture["broker_candidate"]["text"],
                  "route": "short_self_contained", "gate_policy": "legacy", "calls": []}
        with tempfile.TemporaryDirectory() as td:
            pb.apply_postconditions(result=result,
                                    broker_candidate=fixture["broker_candidate"],
                                    declared_files=fixture.get("declared_files") or [],
                                    workspace=Path(td), checks=checks)
        return {"fixture": fixture, "result": result}

    def test_every_fixture_reaches_expected_decision(self):
        fixtures = _list_fixtures()
        self.assertTrue(fixtures, "no fixtures discovered — corpus is empty")
        for fixture_path in fixtures:
            with self.subTest(fixture=fixture_path.name):
                outcome = self._run_fixture(fixture_path)
                fx = outcome["fixture"]
                result = outcome["result"]
                self.assertEqual(result["postconditions"]["decision"],
                                 fx["expected_decision"],
                                 fx["name"] + ": decision mismatch")
                self.assertEqual(result["postconditions"]["failed"],
                                 fx["expected_failed"],
                                 fx["name"] + ": failed list mismatch")
                if fx["expected_decision"] == "withhold":
                    self.assertEqual(result["status"], "postconditions_failed")
                    self.assertIsNone(result["answer"])
                else:
                    self.assertEqual(result["status"], "complete")

    def test_corpus_contains_both_release_and_withhold_cases(self):
        """P0-02 pass condition requires the corpus itself to prove the gate
        is bidirectional: at least one known-wrong-but-schema-valid candidate
        is refused, and at least one transparent candidate is accepted."""
        decisions = set()
        for fixture_path in _list_fixtures():
            fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
            decisions.add(fixture["expected_decision"])
        self.assertIn("withhold", decisions, "corpus must include a refused case")
        self.assertIn("release", decisions, "corpus must include an accepted case")


if __name__ == "__main__":
    unittest.main()
