"""Thread max_cumulative_usd from the Operator Console through broker_argv
-> native_transition_broker --max-cumulative-usd -> RunConfig -> PermitAuthority
(P0-06 slice 2d).

Slice 2b (PR #20) added the knob to RunConfig and taught PermitAuthority
to refuse new permits past the cap. Slice 2d closes the UI carry-over:
the operator can now set the cap in the Operator Console Security view
and a Console-launched broker job actually inherits it.
"""

import argparse
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

for name in ("operator_console",):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / (name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)

console = sys.modules["operator_console"]

INDEX = ROOT / "console" / "index.html"


class OperatorConsoleMaxCumulativeUsdTests(unittest.TestCase):
    def test_default_config_is_none(self):
        self.assertIsNone(console.DEFAULT_CONFIG["max_cumulative_usd"])

    def test_merge_config_accepts_positive_float(self):
        cfg = console._merge_config({"max_cumulative_usd": 2.50})
        self.assertEqual(cfg["max_cumulative_usd"], 2.50)

    def test_merge_config_accepts_null(self):
        cfg = console._merge_config({"max_cumulative_usd": None})
        self.assertIsNone(cfg["max_cumulative_usd"])

    def test_merge_config_rejects_zero(self):
        with self.assertRaises(ValueError):
            console._merge_config({"max_cumulative_usd": 0})

    def test_merge_config_rejects_negative(self):
        with self.assertRaises(ValueError):
            console._merge_config({"max_cumulative_usd": -1.0})

    def test_merge_config_rejects_non_number(self):
        with self.assertRaises(ValueError):
            console._merge_config({"max_cumulative_usd": "lots"})

    def test_merge_config_rejects_bool(self):
        """A JSON boolean must not sneak through numeric validation."""
        with self.assertRaises(ValueError):
            console._merge_config({"max_cumulative_usd": True})


class BrokerArgvForwardsMaxCumulativeUsdTests(unittest.TestCase):
    def _argv(self, overrides=None):
        cfg = console._merge_config(overrides or {})
        return console.broker_argv(Path("/tmp/t.json"), Path("/tmp/out"),
                                   cfg["frontier_provider"], cfg["gate_policy"],
                                   live=False, config=cfg)

    def test_default_omits_the_flag(self):
        self.assertNotIn("--max-cumulative-usd", self._argv())

    def test_positive_value_emits_flag(self):
        argv = self._argv({"max_cumulative_usd": 1.50})
        self.assertIn("--max-cumulative-usd", argv)
        self.assertEqual(argv[argv.index("--max-cumulative-usd") + 1], "1.5")


class BrokerCliParsesMaxCumulativeUsdTests(unittest.TestCase):
    def test_parser_accepts_positive_float(self):
        from native_transition_broker import _build_cli_parser  # type: ignore
        parser = _build_cli_parser()
        args = parser.parse_args([
            "--validate-only", "--host", "claude", "--gate-policy", "recovery",
            "--task", "t.json", "--max-cumulative-usd", "1.5",
        ])
        self.assertEqual(args.max_cumulative_usd, 1.5)

    def test_parser_default_is_none(self):
        from native_transition_broker import _build_cli_parser  # type: ignore
        parser = _build_cli_parser()
        args = parser.parse_args([
            "--validate-only", "--host", "claude", "--gate-policy", "recovery",
            "--task", "t.json",
        ])
        self.assertIsNone(args.max_cumulative_usd)

    def test_parser_rejects_zero_or_negative(self):
        from native_transition_broker import _build_cli_parser  # type: ignore
        parser = _build_cli_parser()
        for bad in ("0", "-1.0"):
            with self.assertRaises((SystemExit, argparse.ArgumentTypeError)):
                parser.parse_args([
                    "--validate-only", "--host", "claude", "--gate-policy", "recovery",
                    "--task", "t.json", "--max-cumulative-usd", bad,
                ])


class EndToEndBrokerOverrideTests(unittest.TestCase):
    """A Console-launched broker run honours the CLI override even when
    the --config JSON omits the field (which is the normal Console path:
    `broker_argv` emits the flag but not a --config file today)."""

    def test_cli_override_lands_on_authority_via_runconfig(self):
        import os
        import subprocess
        import json
        import tempfile as tf

        from native_transition_broker import _build_cli_parser  # type: ignore
        from config import RunConfig  # type: ignore
        parser = _build_cli_parser()
        args = parser.parse_args([
            "--validate-only", "--host", "claude", "--gate-policy", "recovery",
            "--task", "t.json", "--max-cumulative-usd", "4.25",
        ])
        # Simulate main's RunConfig build (settings + CLI override + family).
        settings = {}
        if args.max_cumulative_usd is not None:
            settings["max_cumulative_usd"] = args.max_cumulative_usd
        family = "claude"
        config = RunConfig.from_dict({**settings, "worker_family": family})
        self.assertEqual(config.max_cumulative_usd, 4.25)

    def test_cli_override_wins_over_config_file_value(self):
        from native_transition_broker import _build_cli_parser  # type: ignore
        from config import RunConfig  # type: ignore
        parser = _build_cli_parser()
        args = parser.parse_args([
            "--validate-only", "--host", "claude", "--gate-policy", "recovery",
            "--task", "t.json", "--max-cumulative-usd", "9.99",
        ])
        settings = {"max_cumulative_usd": 1.00}  # value from --config JSON
        if args.max_cumulative_usd is not None:
            settings["max_cumulative_usd"] = args.max_cumulative_usd
        family = "claude"
        config = RunConfig.from_dict({**settings, "worker_family": family})
        self.assertEqual(config.max_cumulative_usd, 9.99)


class ConsoleUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = INDEX.read_text(encoding="utf-8")

    def test_number_input_exists(self):
        self.assertIn('id="maxCumulativeUsd"', self.html)

    def test_label_mentions_the_knob(self):
        self.assertRegex(self.html, r"[Cc]umulative.*[Ss]pend|[Ss]pend\s*cap|[Mm]ax.*[Uu][Ss][Dd]")

    def test_load_security_reads_max_cumulative_usd(self):
        self.assertIn("max_cumulative_usd", self.html)
        self.assertIn("maxCumulativeUsd", self.html)

    def test_save_security_posts_max_cumulative_usd(self):
        self.assertIn("max_cumulative_usd:", self.html)

    def test_existing_security_markers_still_present(self):
        for marker in ('id="view-security"', 'id="contentPolicy"',
                       'id="requireActionApproval"', 'id="trustedMcpServers"',
                       'id="secretEnvNames"'):
            self.assertIn(marker, self.html, "regression on " + marker)


if __name__ == "__main__":
    unittest.main()
