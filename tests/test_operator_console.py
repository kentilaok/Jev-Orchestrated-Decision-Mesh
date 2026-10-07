import importlib.util
from pathlib import Path
import tempfile
import unittest

MODULE = Path(__file__).resolve().parents[1] / "scripts" / "operator_console.py"
spec = importlib.util.spec_from_file_location("operator_console", MODULE)
console = importlib.util.module_from_spec(spec)
spec.loader.exec_module(console)


class OperatorConsoleTests(unittest.TestCase):
    def test_state_store_roundtrip_and_defaults(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "state.json"
            store = console.StateStore(path)
            config = store.load()
            self.assertEqual(config["frontier_provider"], "claude")
            config["frontier_provider"] = "codex"
            store.save(config)
            self.assertEqual(store.load()["frontier_provider"], "codex")

    def test_local_skill_discovery(self):
        with tempfile.TemporaryDirectory() as td:
            skill = Path(td) / "repo-review"
            skill.mkdir()
            (skill / "SKILL.md").write_text(
                "---\nname: repo-review\ndescription: Review a repository safely.\n---\n# Skill\n",
                encoding="utf-8",
            )
            cfg = console._merge_config({"skills_source": td})
            skills = console.local_skills(cfg)
            self.assertEqual(skills[0]["name"], "repo-review")
            self.assertIn("safely", skills[0]["description"])

    def test_route_preview_defaults_to_claude(self):
        cfg = console._merge_config({})
        original = console.merged_skills
        console.merged_skills = lambda _cfg: []
        try:
            result = console.route_preview({"task": "test"}, cfg)
        finally:
            console.merged_skills = original
        self.assertEqual(result["provider"], "claude")
        self.assertEqual(result["route"][1]["actor"], "Jev")
        self.assertEqual(result["route"][2]["actor"], "Hermes")

    def test_provider_model_patch_keeps_other_provider(self):
        base = console._merge_config({})
        raw = {**base, "providers": {"claude": {"model": "claude-opus-5-5"}}}
        merged = console._merge_config(raw)
        self.assertEqual(merged["providers"]["claude"]["model"], "claude-opus-5-5")
        self.assertIn("codex", merged["providers"])


if __name__ == "__main__":
    unittest.main()
