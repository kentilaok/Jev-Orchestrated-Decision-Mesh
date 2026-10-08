import copy
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from arsenal_registry import digest as text_digest
from split_context_dispatch import frozen_task, build_split_context, lane_prompt
from local_lane_scheduler import run_lanes
from ollama_provider import OllamaLocalProvider
from test_local_qwen_stage1 import FakeTransport, MODEL


class DummyRegistry:
    def __init__(self, skill_a, skill_b, *, include_b=True):
        self.a, self.b, self.include_b = skill_a, skill_b, include_b
    def match(self, task, *, project_scope=None, bug_key=None, top_k=5):
        return {"matches": [self.a] if bug_key else ([self.b] if self.include_b else []),
                "experience_matches": []}
    def match_experiences(self, task, *, project_scope=None, bug_key=None, top_k=5):
        return ([{"lesson_id": "lesson-a", "signature": "failure-a",
                  "verifications": [], "failed_strategies": [], "successful_strategies": []}]
                if bug_key else [{"lesson_id": "lesson-b", "signature": "failure-b",
                                   "verifications": [], "failed_strategies": [],
                                   "successful_strategies": []}])


class SplitContextTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        def build(name, body):
            folder = root / name
            folder.mkdir()
            path = folder / "SKILL.md"
            path.write_text(body, encoding="utf-8")
            return {"skill_id": name, "skill_hash": text_digest(body),
                    "manifest_hash": "m", "version": 1, "skill_path": str(path),
                    "admitted": True, "project_scope": ["demo"], "name": name,
                    "match": {"score": 0.9, "exact_bug_key": False}}
        self.a = build("diagnose-direct", "# Diagnose\n- SOP: inspect traceback")
        self.b = build("review-regression", "# Review\n- independent test design")
        self.task = frozen_task("Diagnose a fictional traceback", project_scope="demo",
                                acceptance=["No test assertions removed"])

    def test_split_packages_have_disjoint_skills_and_independent_prompts(self):
        pkgs = build_split_context(DummyRegistry(self.a, self.b), self.task, bug_key="x")
        self.assertEqual(pkgs["A"]["status"], "prepared")
        self.assertEqual(pkgs["B"]["status"], "prepared")
        self.assertEqual([s["skill_id"] for s in pkgs["A"]["skills"]], ["diagnose-direct"])
        self.assertEqual([s["skill_id"] for s in pkgs["B"]["skills"]], ["review-regression"])
        self.assertNotEqual(pkgs["A"]["package_hash"], pkgs["B"]["package_hash"])
        self.assertNotIn("inspect traceback", lane_prompt(pkgs["B"]))
        self.assertNotIn("independent test design", lane_prompt(pkgs["A"]))

    def test_revoked_skill_is_not_used_as_authoritative_context(self):
        a = copy.deepcopy(self.a)
        a["admitted"] = False
        pkgs = build_split_context(DummyRegistry(a, self.b), self.task, bug_key="x")
        self.assertFalse(pkgs["A"]["skills"])

    def test_tampered_snapshot_aborts(self):
        altered = {**self.task, "goal": "Other task"}
        with self.assertRaisesRegex(ValueError, "task_snapshot_tampered"):
            build_split_context(DummyRegistry(self.a, self.b), altered, bug_key="x")

    def test_tampered_skill_is_not_loaded(self):
        Path(self.a["skill_path"]).write_text("changed", encoding="utf-8")
        pkgs = build_split_context(DummyRegistry(self.a, self.b), self.task, bug_key="x")
        self.assertFalse(pkgs["A"]["skills"])

    def test_two_lanes_have_distinct_permits_and_results(self):
        pkgs = build_split_context(DummyRegistry(self.a, self.b), self.task, bug_key="x")
        output = run_lanes(pkgs, model=MODEL, max_parallel=1,
                           provider_factory=lambda authority, lane:
                           OllamaLocalProvider(authority, allowed_model=MODEL, transport=FakeTransport()))
        self.assertEqual(output["physical_parallel_limit"], 1)
        self.assertTrue(output["permit_audit"]["valid"])
        self.assertEqual(output["remote_worker_calls"], 0)
        self.assertNotEqual(output["results"]["A"]["permit_id"], output["results"]["B"]["permit_id"])
        self.assertEqual(output["decision"], "unverified_pending_external_validation")

    def test_parallel_bound_and_missing_b(self):
        with self.assertRaisesRegex(ValueError, "parallel_limit"):
            run_lanes({"A": {}, "B": {}}, model=MODEL, max_parallel=3)
        pkgs = build_split_context(DummyRegistry(self.a, self.b, include_b=False),
                                   self.task, bug_key="x")
        self.assertEqual(pkgs["B"]["status"], "prepared")  # separate lesson is available
