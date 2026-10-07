import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from arsenal_registry import ArsenalRegistry
from arsenal_shadow import reciprocal_rank_fusion, run_shadow


SKILL = """---
name: known-fix
description: Known low-risk inspection for a verified content visibility bug.
---

# known-fix

## Trigger

- Bug key: wordpress.memberpress.logged_out_visibility
- Observed symptom: Protected content remains visible while signed out.
"""


def manifest():
    return {
        "schema_version": 1,
        "id": "known-fix",
        "type": "recovery-skill",
        "version": 1,
        "description": "Known low-risk inspection for a verified content visibility bug.",
        "project_scope": ["wordpress"],
        "triggers": {
            "bug_keys": ["wordpress.memberpress.logged_out_visibility"],
            "phrases": ["protected content visible while signed out"],
            "keywords": ["memberpress"],
        },
        "permissions": {"read_files": True, "write_files": False},
        "risk": "low",
        "frontier_required": False,
        "validators": ["anonymous_browser_check"],
        "operations": ["inspect_content"],
        "admission": {"status": "candidate", "owner_approved": False},
        "source": {"kind": "test"},
    }


class ArsenalShadowTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.skills = self.root / "skills"
        self.skills.mkdir()
        self.db = self.root / "arsenal.db"

    def create_skill(self, with_manifest=True):
        folder = self.skills / "known-fix"
        folder.mkdir()
        (folder / "SKILL.md").write_text(SKILL, encoding="utf-8")
        if with_manifest:
            (folder / "ARSENAL.json").write_text(
                json.dumps(manifest(), indent=2) + "\n", encoding="utf-8"
            )
        return folder

    def test_rrf_rewards_candidate_present_in_both_rankings(self):
        fused = reciprocal_rank_fusion(
            [{"skill_id": "a"}, {"skill_id": "b"}],
            [{"skill_id": "b"}, {"skill_id": "c"}],
        )
        self.assertEqual(fused[0]["skill_id"], "b")
        self.assertEqual(fused[0]["ranks"], {"lexical": 2, "semantic": 1})

    def test_shadow_identifies_fast_path_candidate_but_never_bypasses_frontier(self):
        self.create_skill()
        with ArsenalRegistry(self.db) as registry:
            registry.scan(self.skills)
            registry.admit("known-fix")
        result = run_shadow(
            self.db,
            "Protected content remains visible while signed out",
            project_scope="wordpress",
            bug_key="wordpress.memberpress.logged_out_visibility",
            operation="inspect_content",
        )
        self.assertEqual(result["recommendation"], "fast_path_candidate")
        self.assertTrue(result["fast_path_candidate"])
        self.assertTrue(result["would_avoid_frontier_if_fast_path_enabled"])
        self.assertFalse(result["frontier_call_avoided"])
        self.assertEqual(result["authority"], "none_shadow_observation_only")

    def test_verified_experience_can_be_loaded_before_jev_without_fast_path(self):
        lessons = self.root / "lessons.json"
        lessons.write_text(json.dumps([{
            "lesson_id": "lesson-shadow1",
            "signature": "shadow1",
            "project_scope": "wordpress",
            "unit_id": "hidden1",
            "confidence": "medium",
            "verified_observations": 2,
            "bug_keys": ["wordpress.memberpress.logged_out_visibility"],
            "symptoms": ["Protected content remains visible while signed out."],
            "root_causes": ["Anonymous route escaped the expected protection."],
            "failed_strategies": [],
            "successful_strategies": ["Use the verified anonymous protection path."],
            "verifications": ["Anonymous browser validation passed."],
            "provenance": [{"run_id": "r1"}, {"run_id": "r2"}],
        }], indent=2) + "\n", encoding="utf-8")
        with ArsenalRegistry(self.db) as registry:
            registry.index_lessons(lessons)
        result = run_shadow(
            self.db,
            "Protected content remains visible while signed out",
            project_scope="wordpress",
            bug_key="wordpress.memberpress.logged_out_visibility",
            operation="inspect_content",
        )
        self.assertEqual(result["recommendation"], "load_experience_then_jev")
        self.assertEqual(result["selected_experience_id"], "lesson-shadow1")
        self.assertFalse(result["fast_path_candidate"])
        self.assertFalse(result["frontier_call_avoided"])

    def test_unadmitted_skill_can_be_context_but_not_fast_path(self):
        self.create_skill(with_manifest=False)
        with ArsenalRegistry(self.db) as registry:
            registry.scan(self.skills)
        result = run_shadow(
            self.db,
            "Protected content remains visible while signed out",
            bug_key="wordpress.memberpress.logged_out_visibility",
        )
        self.assertEqual(result["recommendation"], "load_skill_then_jev")
        self.assertFalse(result["fast_path_candidate"])
        self.assertFalse(result["frontier_call_avoided"])


if __name__ == "__main__":
    unittest.main()
