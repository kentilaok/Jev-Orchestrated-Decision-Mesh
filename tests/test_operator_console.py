import importlib.util
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "operator_console.py"
spec = importlib.util.spec_from_file_location("operator_console", SCRIPT)
mod = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(mod)


class OperatorConsoleTests(unittest.TestCase):
    def setUp(self):
        self.registry = mod.load_registry()

    def test_registry_defaults_are_enabled(self):
        enabled = mod.enabled_models(self.registry)
        key = (self.registry["default_provider"], self.registry["default_model"])
        self.assertIn(key, enabled)

    def test_preview_uses_jev_hermes_claude_jev_route(self):
        route = mod.build_route({"prompt": "Inspect the project"}, self.registry)
        self.assertEqual(route["route"][0]["actor"], "Jev")
        self.assertEqual(route["route"][1]["actor"], "Hermes")
        self.assertEqual(route["route"][2]["actor"], "claude-opus-5-5")
        self.assertEqual(route["route"][-1]["actor"], "Jev")

    def test_rejects_unlisted_model(self):
        with self.assertRaises(ValueError):
            mod.build_route({"prompt": "x", "model": "made-up-model"}, self.registry)

    def test_workspace_must_exist(self):
        with self.assertRaises(ValueError):
            mod.resolve_workspace("/definitely/not/a/real/jev-console-path")

    def test_hermes_command_is_not_shell_interpolated(self):
        with patch.object(mod.shutil, "which", return_value="/usr/local/bin/hermes"):
            cmd = mod.build_hermes_command("anthropic", "claude-opus-5-5", "medium", True)
        self.assertEqual(cmd[0], "/usr/local/bin/hermes")
        self.assertIn("--safe-mode", cmd)
        self.assertIn("--query-file", cmd)
        self.assertEqual(cmd[-1], "-")


if __name__ == "__main__":
    unittest.main()
