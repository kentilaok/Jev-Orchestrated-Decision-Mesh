import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from arsenal_registry import ArsenalRegistry, compile_skill
from experience_distiller import render_arsenal_manifest


SKILL = """---
name: public-protection
description: Fix public visibility of protected content.
---

# public-protection

## Trigger

- Bug key: wordpress.memberpress.logged_out_visibility
- Observed symptom: Protected product is visible while signed out.
- Failed criterion: anonymous_access_blocked

## Procedure

Use the approved protection procedure, then validate anonymously.
"""


def admitted_manifest(scope="wordpress"):
    return {
        "schema_version": 1,
        "id": "public-protection",
        "type": "recovery-skill",
        "version": 1,
        "description": "Fix public visibility of protected content.",
        "project_scope": [scope],
        "triggers": {
            "bug_keys": ["wordpress.memberpress.logged_out_visibility"],
            "phrases": ["protected content visible while logged out"],
            "keywords": ["memberpress", "woocommerce"],
        },
        "permissions": {
            "read_files": True,
            "write_files": False,
        },
        "risk": "low",
        "frontier_required": False,
        "validators": ["anonymous_browser_check"],
        "operations": ["inspect_content"],
        "admission": {
            "status": "admitted",
            "owner_approved": True,
        },
        "source": {
            "kind": "owner-reviewed",
        },
    }


class ArsenalRegistryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.skills = self.root / "skills"
        self.skills.mkdir()
        self.db = self.root / "arsenal.db"

    def write_skill(self, *, manifest=None, folder="public-protection"):
        target = self.skills / folder
        target.mkdir()
        (target / "SKILL.md").write_text(SKILL, encoding="utf-8")
        if manifest is not None:
            (target / "ARSENAL.json").write_text(
                json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
            )
        return target

    def test_unmanifested_skill_is_searchable_but_not_fast_path_authorized(self):
        self.write_skill()
        with ArsenalRegistry(self.db) as registry:
            result = registry.scan(self.skills)
            self.assertEqual((result["found"], result["indexed"]), (1, 1))
            match = registry.match(
                "protected product visible while signed out",
                bug_key="wordpress.memberpress.logged_out_visibility",
            )
        self.assertEqual(match["decision"], "known_skill")
        self.assertFalse(match["matches"][0]["admitted"])
        self.assertFalse(match["fast_path"]["eligible"])
        self.assertIn("skill_not_admitted", match["fast_path"]["reasons"])
        self.assertIn("frontier_required", match["fast_path"]["reasons"])

    def test_owner_admitted_low_risk_skill_can_qualify_for_fast_path(self):
        self.write_skill(manifest=admitted_manifest())
        with ArsenalRegistry(self.db) as registry:
            registry.scan(self.skills)
            approval = registry.admit("public-protection")
            match = registry.match(
                "protected product visible while signed out",
                project_scope="wordpress",
                bug_key="wordpress.memberpress.logged_out_visibility",
                operation="inspect_content",
            )
        self.assertTrue(approval["admitted"])
        self.assertEqual(match["decision"], "known_skill")
        self.assertTrue(match["fast_path"]["eligible"])
        self.assertEqual(
            match["fast_path"]["validators"], ["anonymous_browser_check"]
        )
        self.assertTrue(match["matches"][0]["manifest_hash"])

    def test_fast_path_requires_explicit_preapproved_operation(self):
        self.write_skill(manifest=admitted_manifest())
        with ArsenalRegistry(self.db) as registry:
            registry.scan(self.skills)
            registry.admit("public-protection")
            missing = registry.match(
                "protected product visible while signed out",
                project_scope="wordpress",
                bug_key="wordpress.memberpress.logged_out_visibility",
            )
            wrong = registry.match(
                "protected product visible while signed out",
                project_scope="wordpress",
                bug_key="wordpress.memberpress.logged_out_visibility",
                operation="delete_content",
            )
        self.assertIn("operation_required", missing["fast_path"]["reasons"])
        self.assertIn("operation_not_preapproved", wrong["fast_path"]["reasons"])

    def test_project_scope_prevents_cross_project_match(self):
        self.write_skill(manifest=admitted_manifest("wordpress"))
        with ArsenalRegistry(self.db) as registry:
            registry.scan(self.skills)
            match = registry.match(
                "protected product visible while signed out",
                project_scope="roblox",
                bug_key="wordpress.memberpress.logged_out_visibility",
                operation="inspect_content",
            )
        self.assertEqual(match["decision"], "escalate_to_jev")
        self.assertEqual(match["reason"], "no_scope_candidate")

    def test_manifest_cannot_self_admit_without_local_hash_bound_approval(self):
        self.write_skill(manifest=admitted_manifest())
        with ArsenalRegistry(self.db) as registry:
            registry.scan(self.skills)
            match = registry.match(
                "protected product visible while signed out",
                project_scope="wordpress",
                bug_key="wordpress.memberpress.logged_out_visibility",
                operation="inspect_content",
            )
        self.assertFalse(match["matches"][0]["admitted"])
        self.assertIn("skill_not_admitted", match["fast_path"]["reasons"])

    def test_skill_change_invalidates_existing_admission(self):
        target = self.write_skill(manifest=admitted_manifest())
        with ArsenalRegistry(self.db) as registry:
            registry.scan(self.skills)
            registry.admit("public-protection")
            before = registry.match(
                "protected product visible while signed out",
                project_scope="wordpress",
                bug_key="wordpress.memberpress.logged_out_visibility",
                operation="inspect_content",
            )
            self.assertTrue(before["fast_path"]["eligible"])
            with (target / "SKILL.md").open("a", encoding="utf-8") as stream:
                stream.write("\nNew owner review required after this change.\n")
            registry.scan(self.skills)
            after = registry.match(
                "protected product visible while signed out",
                project_scope="wordpress",
                bug_key="wordpress.memberpress.logged_out_visibility",
                operation="inspect_content",
            )
        self.assertFalse(after["matches"][0]["admitted"])
        self.assertIn("skill_not_admitted", after["fast_path"]["reasons"])

    def test_candidate_manifest_remains_searchable_without_fast_path_authority(self):
        manifest = admitted_manifest()
        manifest["admission"] = {"status": "candidate", "owner_approved": False}
        self.write_skill(manifest=manifest)
        with ArsenalRegistry(self.db) as registry:
            registry.scan(self.skills)
            match = registry.match(
                "protected product visible while signed out",
                project_scope="wordpress",
                bug_key="wordpress.memberpress.logged_out_visibility",
                operation="inspect_content",
            )
        self.assertEqual(match["decision"], "known_skill")
        self.assertFalse(match["fast_path"]["eligible"])
        self.assertIn("skill_not_admitted", match["fast_path"]["reasons"])

    def test_removed_skill_is_pruned_with_its_admission(self):
        target = self.write_skill(manifest=admitted_manifest())
        with ArsenalRegistry(self.db) as registry:
            registry.scan(self.skills)
            registry.admit("public-protection")
            for child in target.iterdir():
                child.unlink()
            target.rmdir()
            result = registry.scan(self.skills)
            self.assertEqual(result["pruned"], ["public-protection"])
            self.assertEqual(registry.list_skills(), [])
            with self.assertRaisesRegex(Exception, "unknown_skill"):
                registry.admit("public-protection")

    def test_invalid_manifest_is_quarantined_as_scan_error(self):
        target = self.write_skill()
        (target / "ARSENAL.json").write_text(
            json.dumps({"schema_version": 1}), encoding="utf-8"
        )
        with ArsenalRegistry(self.db) as registry:
            result = registry.scan(self.skills)
        self.assertEqual(result["indexed"], 0)
        self.assertEqual(len(result["errors"]), 1)
        self.assertIn("manifest_missing_required_fields", result["errors"][0]["error"])

    def test_compiler_merges_manifest_and_skill_trigger_evidence(self):
        target = self.write_skill(manifest=admitted_manifest())
        skill = compile_skill(target / "SKILL.md")
        self.assertIn(
            "wordpress.memberpress.logged_out_visibility",
            skill.triggers["bug_keys"],
        )
        self.assertIn(
            "Protected product is visible while signed out.",
            skill.triggers["phrases"],
        )
        self.assertFalse(skill.admitted)

    def test_verified_lesson_is_searchable_but_never_fast_path_authority(self):
        lessons = self.root / "lessons.json"
        lessons.write_text(json.dumps([{
            "lesson_id": "lesson-abc123",
            "signature": "abc123",
            "project_scope": "wordpress",
            "unit_id": "hidden1",
            "confidence": "medium",
            "verified_observations": 2,
            "bug_keys": ["wordpress.memberpress.logged_out_visibility"],
            "symptoms": ["Protected product is visible while signed out."],
            "root_causes": ["Anonymous protection did not cover the product route."],
            "failed_strategies": ["MemberPress rule alone."],
            "successful_strategies": ["Inspect public visibility and apply the verified protection path."],
            "verifications": ["Anonymous browser check passed."],
            "provenance": [{"run_id": "r1"}, {"run_id": "r2"}],
        }], indent=2) + "\n", encoding="utf-8")

        with ArsenalRegistry(self.db) as registry:
            indexed = registry.index_lessons(lessons)
            match = registry.match(
                "protected product visible while signed out",
                project_scope="wordpress",
                bug_key="wordpress.memberpress.logged_out_visibility",
                operation="inspect_content",
            )
        self.assertEqual(indexed["indexed"], 1)
        self.assertEqual(match["decision"], "escalate_to_jev")
        self.assertEqual(match["reason"], "known_experience_only")
        self.assertEqual(match["experience_matches"][0]["lesson_id"], "lesson-abc123")
        self.assertEqual(
            match["experience_matches"][0]["authority"],
            "context_only_no_fast_path",
        )

    def test_verified_lesson_respects_project_scope(self):
        lessons = self.root / "lessons.json"
        lessons.write_text(json.dumps([{
            "lesson_id": "lesson-scope1",
            "signature": "scope1",
            "project_scope": "wordpress",
            "unit_id": "hidden1",
            "confidence": "medium",
            "verified_observations": 2,
            "bug_keys": ["wordpress.memberpress.logged_out_visibility"],
            "symptoms": ["Protected product is visible while signed out."],
            "root_causes": [],
            "failed_strategies": [],
            "successful_strategies": [],
            "verifications": [],
            "provenance": [],
        }], indent=2) + "\n", encoding="utf-8")

        with ArsenalRegistry(self.db) as registry:
            registry.index_lessons(lessons)
            match = registry.match(
                "protected product visible while signed out",
                project_scope="roblox",
                bug_key="wordpress.memberpress.logged_out_visibility",
            )
        self.assertEqual(match["reason"], "no_local_candidate")
        self.assertEqual(match["experience_matches"], [])

    def test_experience_distiller_manifest_is_conservative_candidate(self):
        lesson = {
            "lesson_id": "lesson-123",
            "signature": "abc123",
            "project_scope": "wordpress",
            "unit_id": "hidden1",
            "bug_keys": ["wordpress.memberpress.logged_out_visibility"],
            "symptoms": ["Protected product is visible while signed out."],
            "failed_criteria": ["anonymous_access_blocked"],
        }
        manifest = render_arsenal_manifest(lesson)
        self.assertEqual(manifest["type"], "recovery-skill")
        self.assertEqual(manifest["risk"], "medium")
        self.assertTrue(manifest["frontier_required"])
        self.assertEqual(
            manifest["admission"],
            {"status": "candidate", "owner_approved": False},
        )
        self.assertEqual(manifest["validators"], [])
        self.assertEqual(manifest["operations"], [])


if __name__ == "__main__":
    unittest.main()
