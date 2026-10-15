"""Thread secret_env_names from the Operator Console through broker_argv ->
native_transition_broker.py CLI -> ClaudeCodeProvider/CodexProvider -> the CLI
adapter's `secret_env_names`, so a Console-side operator setting actually
scrubs those names from the worker subprocess environment (P0-06 slice 2a).
"""

import argparse
import importlib.util
import sys
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

for name in ("operator_console",):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / (name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)

console = sys.modules["operator_console"]


class OperatorConsoleSecretEnvNamesTests(unittest.TestCase):
    def test_default_config_has_empty_secret_env_names(self):
        self.assertEqual(console.DEFAULT_CONFIG["secret_env_names"], [])

    def test_merge_config_accepts_valid_list(self):
        cfg = console._merge_config({"secret_env_names": ["EXTRA_KEY", "OTHER"]})
        self.assertEqual(cfg["secret_env_names"], ["EXTRA_KEY", "OTHER"])

    def test_merge_config_rejects_non_list(self):
        with self.assertRaises(ValueError):
            console._merge_config({"secret_env_names": "EXTRA_KEY"})

    def test_merge_config_rejects_empty_entry(self):
        with self.assertRaises(ValueError):
            console._merge_config({"secret_env_names": [""]})

    def test_merge_config_rejects_entry_with_equals(self):
        with self.assertRaises(ValueError):
            console._merge_config({"secret_env_names": ["X=Y"]})

    def test_merge_config_rejects_non_string_entry(self):
        with self.assertRaises(ValueError):
            console._merge_config({"secret_env_names": [123]})


class BrokerArgvForwardsEnvScrubTests(unittest.TestCase):
    def _argv(self, config_overrides=None):
        cfg = console._merge_config(config_overrides or {})
        return console.broker_argv(Path("/tmp/t.json"), Path("/tmp/out"),
                                   cfg["frontier_provider"], cfg["gate_policy"],
                                   live=False, config=cfg)

    def test_default_config_omits_secret_env_names_flag(self):
        self.assertNotIn("--secret-env-names", self._argv())

    def test_empty_list_omits_flag(self):
        self.assertNotIn("--secret-env-names", self._argv({"secret_env_names": []}))

    def test_non_empty_list_adds_comma_joined_flag(self):
        argv = self._argv({"secret_env_names": ["EXTRA", "OTHER"]})
        self.assertIn("--secret-env-names", argv)
        self.assertEqual(argv[argv.index("--secret-env-names") + 1], "EXTRA,OTHER")


class BrokerCliParsesEnvScrubTests(unittest.TestCase):
    def test_parser_accepts_comma_separated_names(self):
        from native_transition_broker import _build_cli_parser  # type: ignore
        parser = _build_cli_parser()
        args = parser.parse_args([
            "--validate-only", "--host", "claude", "--gate-policy", "recovery",
            "--task", "t.json", "--secret-env-names", "EXTRA,OTHER",
        ])
        self.assertEqual(args.secret_env_names, ["EXTRA", "OTHER"])

    def test_parser_default_is_empty_list(self):
        from native_transition_broker import _build_cli_parser  # type: ignore
        parser = _build_cli_parser()
        args = parser.parse_args([
            "--validate-only", "--host", "claude", "--gate-policy", "recovery",
            "--task", "t.json",
        ])
        self.assertEqual(args.secret_env_names, [])

    def test_parser_rejects_entry_with_equals(self):
        from native_transition_broker import _build_cli_parser  # type: ignore
        parser = _build_cli_parser()
        with self.assertRaises((SystemExit, argparse.ArgumentTypeError)):
            parser.parse_args([
                "--validate-only", "--host", "claude", "--gate-policy", "recovery",
                "--task", "t.json", "--secret-env-names", "X=Y",
            ])

    def test_parser_rejects_empty_entry(self):
        from native_transition_broker import _build_cli_parser  # type: ignore
        parser = _build_cli_parser()
        with self.assertRaises((SystemExit, argparse.ArgumentTypeError)):
            parser.parse_args([
                "--validate-only", "--host", "claude", "--gate-policy", "recovery",
                "--task", "t.json", "--secret-env-names", "A,,B",
            ])


class ClaudeProviderThreadsEnvScrubTests(unittest.TestCase):
    def _authority(self, tmp):
        from capability_permits import PermitAuthority  # type: ignore
        return PermitAuthority(tmp / "permits.jsonl")

    def test_default_adapter_has_only_hardcoded_scrub_set(self):
        import tempfile
        from frontier_providers import ClaudeCodeProvider  # type: ignore
        with tempfile.TemporaryDirectory() as tds:
            provider = ClaudeCodeProvider(self._authority(Path(tds)))
            self.assertIn("OPENROUTER_API_KEY", provider.adapter.secret_env_names)
            self.assertNotIn("EXTRA_KEY", provider.adapter.secret_env_names)

    def test_passes_secret_env_names_through_to_adapter(self):
        import tempfile
        from frontier_providers import ClaudeCodeProvider  # type: ignore
        with tempfile.TemporaryDirectory() as tds:
            provider = ClaudeCodeProvider(self._authority(Path(tds)),
                                          secret_env_names=["EXTRA_KEY", "another"])
            self.assertIn("EXTRA_KEY", provider.adapter.secret_env_names)
            self.assertIn("ANOTHER", provider.adapter.secret_env_names)
            self.assertIn("OPENROUTER_API_KEY", provider.adapter.secret_env_names)

    def test_adapter_rejects_invalid_secret_env_names(self):
        from claude_cli_adapter import ClaudeCliAdapter  # type: ignore
        with self.assertRaises(ValueError):
            ClaudeCliAdapter(secret_env_names=[123])
        with self.assertRaises(ValueError):
            ClaudeCliAdapter(secret_env_names=[""])
        with self.assertRaises(ValueError):
            ClaudeCliAdapter(secret_env_names=["X=Y"])


class CodexProviderThreadsEnvScrubTests(unittest.TestCase):
    def _authority(self, tmp):
        from capability_permits import PermitAuthority  # type: ignore
        return PermitAuthority(tmp / "permits.jsonl")

    def test_default_adapter_has_only_hardcoded_scrub_set(self):
        import tempfile
        from frontier_providers import CodexProvider  # type: ignore
        with tempfile.TemporaryDirectory() as tds:
            provider = CodexProvider(self._authority(Path(tds)))
            self.assertIn("OPENROUTER_API_KEY", provider.adapter.secret_env_names)
            self.assertNotIn("EXTRA_KEY", provider.adapter.secret_env_names)

    def test_passes_secret_env_names_through_to_adapter(self):
        import tempfile
        from frontier_providers import CodexProvider  # type: ignore
        with tempfile.TemporaryDirectory() as tds:
            provider = CodexProvider(self._authority(Path(tds)),
                                     secret_env_names=["EXTRA_KEY", "another"])
            self.assertIn("EXTRA_KEY", provider.adapter.secret_env_names)
            self.assertIn("ANOTHER", provider.adapter.secret_env_names)
            self.assertIn("OPENROUTER_API_KEY", provider.adapter.secret_env_names)


class EnvScrubIntegrationTests(unittest.TestCase):
    """A name added via the Console knob is actually missing from the child env."""

    def test_scrubbed_name_absent_from_adapter_child_env(self):
        import os
        import tempfile
        import unittest.mock as mock
        from claude_cli_adapter import ClaudeCliAdapter  # type: ignore
        adapter = ClaudeCliAdapter(secret_env_names=["EXTRA_SECRET"])
        with mock.patch.dict(os.environ, {"EXTRA_SECRET": "leak", "KEEP_ME": "ok"}, clear=False):
            with tempfile.TemporaryDirectory() as tds:
                td = Path(tds)
                prompt_path = td / "prompt.txt"
                prompt_path.write_text("x", encoding="utf-8")
                stdout_path = td / "stdout.txt"
                stderr_path = td / "stderr.txt"
                captured = {}

                def fake_popen(argv, *, cwd, stdin, stdout, stderr, shell, env):
                    captured["env"] = dict(env)
                    raise OSError("sentinel-no-launch")

                with mock.patch("claude_cli_adapter.subprocess.Popen", side_effect=fake_popen):
                    try:
                        adapter._execute(["/bin/true"], td, prompt_path, stdout_path, stderr_path)
                    except Exception:
                        pass
                env = captured.get("env", {})
                self.assertNotIn("EXTRA_SECRET", env)
                self.assertNotIn("OPENROUTER_API_KEY", env)
                self.assertEqual(env.get("KEEP_ME"), "ok")


if __name__ == "__main__":
    unittest.main()
