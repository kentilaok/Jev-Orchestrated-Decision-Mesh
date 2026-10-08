import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from arsenal_import_matt_pocock import import_catalogue, manifest_for, selected_skills
from arsenal_registry import ArsenalRegistry, compile_skill, normalize_manifest


class MattPocockImportTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.upstream = self.root / "upstream"
        self.upstream.mkdir()
        self.dest = self.root / "installed"
        self.catalogue = self.root / "catalogue.json"
        self.git("init", "-q")
        self.git("config", "user.email", "test@example.invalid")
        self.git("config", "user.name", "Arsenal Test")
        for name in ("diagnosing-bugs", "retro", "implement-spec"):
            folder = self.upstream / "skills" / "engineering" / name
            folder.mkdir(parents=True)
            (folder / "SKILL.md").write_text(
                "---\nname: " + name + "\ndescription: An engineering method.\n---\n"
                "## Trigger\n- Debug engineering errors.\n",
                encoding="utf-8",
            )
            (folder / "reference.md").write_text("Reference", encoding="utf-8")
        (self.upstream / "LICENSE").write_text(
            "MIT License - upstream copyright notice fixture.", encoding="utf-8"
        )
        self.git("add", ".")
        self.git("commit", "-qm", "pinned source")
        self.rev = self.git("rev-parse", "HEAD")
        self.data = {
            "schema_version": 1,
            "source_id": "matt-pocock-real-engineers",
            "upstream": "https://github.com/mattpocock/skills",
            "pinned_revision": self.rev,
            "license": "MIT",
            "default_scope": ["global"],
            "skills": [
                {"name": "diagnosing-bugs",
                 "upstream_path": "skills/engineering/diagnosing-bugs",
                 "invocation": "model", "priority": "core",
                 "purpose": "Disciplined diagnosis with red-green validation."},
                {"name": "retro", "upstream_path": "skills/engineering/retro",
                 "invocation": "user", "priority": "review",
                 "purpose": "Retrospective of a completed engineering session."},
                {"name": "implement-spec",
                 "upstream_path": "skills/engineering/implement-spec",
                 "invocation": "user", "priority": "restricted",
                 "purpose": "Task-graph implementation under separate authority."},
            ],
        }
        self.catalogue.write_text(
            json.dumps(self.data, indent=2) + "\n", encoding="utf-8"
        )

    def git(self, *args):
        return subprocess.run(
            ["git", "-C", str(self.upstream), *args],
            check=True, capture_output=True, text=True,
        ).stdout.strip()

    def stage(self, **kwargs):
        return import_catalogue(
            self.upstream, self.dest, self.catalogue, **kwargs
        )

    def test_default_selection_only_uses_core_methods(self):
        selected = selected_skills(self.data, [], False)
        self.assertEqual([item["name"] for item in selected], ["diagnosing-bugs"])

    def test_dry_run_does_not_create_skill_files(self):
        result = self.stage()
        self.assertEqual(result["status"], "dry_run")
        self.assertEqual(len(result["skills"]), 1)
        self.assertFalse(self.dest.exists())
        self.assertEqual(result["authority"], "none_owner_admission_required")

    def test_install_creates_unadmitted_manifest_and_preserves_reference(self):
        result = self.stage(install=True)
        self.assertEqual(result["status"], "staged")
        folder = self.dest / "matt-pocock-diagnosing-bugs"
        self.assertTrue((folder / "SKILL.md").exists())
        self.assertEqual(
            (folder / "reference.md").read_text(encoding="utf-8"), "Reference"
        )
        self.assertTrue((folder / "UPSTREAM_LICENSE.txt").exists())
        manifest = normalize_manifest(json.loads(
            (folder / "ARSENAL.json").read_text(encoding="utf-8")
        ))
        self.assertEqual(manifest["admission"]["status"], "candidate")
        self.assertFalse(manifest["admission"]["owner_approved"])
        self.assertEqual(manifest["validators"], [])
        self.assertEqual(manifest["operations"], [])
        self.assertTrue(manifest["frontier_required"])
        skill = compile_skill(folder / "SKILL.md")
        self.assertFalse(skill.admitted)
        with ArsenalRegistry(self.root / "arsenal.db") as registry:
            registry.scan(self.dest)
            match = registry.match("Debug engineering errors")
        self.assertEqual(match["decision"], "known_skill")
        self.assertFalse(match["fast_path"]["eligible"])

    def test_explicit_restricted_skill_remains_candidate_high_risk(self):
        result = self.stage(requested=["implement-spec"], install=True)
        manifest = json.loads(
            (self.dest / "matt-pocock-implement-spec" / "ARSENAL.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(result["skills"][0]["invocation"], "user")
        self.assertEqual(manifest["risk"], "high")
        self.assertFalse(manifest["permissions"]["spawn_subagents"])
        self.assertFalse(manifest["permissions"]["issue_tracker_write"])

    def test_missing_license_refuses_import(self):
        (self.upstream / "LICENSE").unlink()
        with self.assertRaisesRegex(ValueError, "upstream_checkout_is_dirty"):
            self.stage(install=True)
        self.assertFalse(self.dest.exists())

    def test_revision_mismatch_refuses_import(self):
        data = dict(self.data, pinned_revision="0" * 40)
        self.catalogue.write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "upstream_revision_mismatch"):
            self.stage(install=True)
        self.assertFalse(self.dest.exists())

    def test_dirty_upstream_refuses_import(self):
        file = self.upstream / "skills/engineering/diagnosing-bugs/SKILL.md"
        file.write_text("Tampered", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "upstream_checkout_is_dirty"):
            self.stage(install=True)
        self.assertFalse(self.dest.exists())

    def test_existing_destination_is_not_replaced(self):
        existing = self.dest / "matt-pocock-diagnosing-bugs"
        existing.mkdir(parents=True)
        (existing / "SKILL.md").write_text("Owner data", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "destination_skill_already_exists"):
            self.stage(install=True)
        self.assertEqual(
            (existing / "SKILL.md").read_text(encoding="utf-8"), "Owner data"
        )

    def test_rejects_unlisted_skill_request(self):
        with self.assertRaisesRegex(ValueError, "unknown_requested_skill"):
            self.stage(requested=["mystery-skill"])

    def test_review_skills_require_explicit_selection(self):
        result = self.stage(include_review=True)
        self.assertEqual(
            [x["skill_id"] for x in result["skills"]],
            ["matt-pocock-diagnosing-bugs", "matt-pocock-retro"],
        )


if __name__ == "__main__":
    unittest.main()
