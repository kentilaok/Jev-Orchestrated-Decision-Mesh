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
sys.path.insert(0, str(ROOT / "tests"))

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
    """Drive the real native_transition_broker.main() up to PermitAuthority
    construction and assert the cap it receives. Offline: PermitAuthority is
    patched to raise before any provider is built."""

    class _Stop(Exception):
        pass

    def _drive(self, extra, config_file=None):
        import json
        from unittest import mock
        import capability_permits  # type: ignore
        import frontier_providers  # type: ignore
        import native_transition_broker as ntb  # type: ignore
        from test_native_transition_broker import SPEC  # type: ignore
        with tempfile.TemporaryDirectory() as tds:
            td = Path(tds)
            task = td / "task.json"
            task.write_text(json.dumps(SPEC), encoding="utf-8")
            argv = ["ntb", "--live", "--host", "claude", "--gate-policy", "recovery",
                    "--task", str(task), "--out", str(td / "out"), "--skip-route-preflight", *extra]
            if config_file is not None:
                cfg = td / "cfg.json"
                cfg.write_text(json.dumps(config_file), encoding="utf-8")
                argv += ["--config", str(cfg)]
            # Fail closed if PermitAuthority stops being the first stop: never let a
            # refactor turn this offline test into a live provider or Jev call.
            with (mock.patch.object(sys, "argv", argv),
                  mock.patch.object(capability_permits, "PermitAuthority", side_effect=self._Stop) as pa,
                  mock.patch.object(frontier_providers, "build_provider",
                                    side_effect=AssertionError("live provider")),
                  mock.patch.object(ntb, "Gateway", side_effect=AssertionError("live Jev gateway"))):
                with self.assertRaises(self._Stop):
                    ntb.main()
                return pa.call_args.kwargs.get("max_cumulative_usd")

    def test_cli_flag_reaches_permit_authority(self):
        self.assertEqual(self._drive(["--max-cumulative-usd", "4.25"]), 4.25)

    def test_no_flag_no_file_means_no_cap(self):
        self.assertIsNone(self._drive([]))

    def test_config_file_value_used_without_flag(self):
        self.assertEqual(self._drive([], {"max_cumulative_usd": 1.0}), 1.0)

    def test_cli_flag_wins_over_config_file_value(self):
        self.assertEqual(self._drive(["--max-cumulative-usd", "9.99"], {"max_cumulative_usd": 1.0}), 9.99)


class ConsoleResumeKeepsOriginalCapTests(unittest.TestCase):
    """The cap is part of the checkpoint policy hash, so a Console resume must
    pass the cap the run started with, not the Console's current value."""

    def _resume_argv(self, policy):
        import json
        with tempfile.TemporaryDirectory() as tds:
            td = Path(tds)
            source = td / "runs" / "r1"
            (source / "run").mkdir(parents=True)
            (source / "request.json").write_text("{}", encoding="utf-8")
            (source / "run" / "result.json").write_text(json.dumps({"host": "claude"}), encoding="utf-8")
            (source / "run" / "checkpoint.json").write_text(json.dumps({"policy": policy}), encoding="utf-8")
            cfg = console._merge_config({"project_directory": str(td), "runs_directory": str(td / "runs"),
                                         "max_cumulative_usd": 5.0})
            real_start = console.JOBS.start
            console.JOBS.start = lambda argv, run_dir, meta: list(argv)
            try:
                return console.start_resume_job("r1", {"confirm_live_spend": True, "operator": "ken"}, cfg)
            finally:
                console.JOBS.start = real_start

    def test_resume_uses_checkpoint_cap_not_console_cap(self):
        argv = self._resume_argv({"max_cumulative_usd": 1.0})
        self.assertEqual(argv[argv.index("--max-cumulative-usd") + 1], "1.0")

    def test_resume_of_uncapped_run_omits_flag(self):
        self.assertNotIn("--max-cumulative-usd", self._resume_argv({"max_cumulative_usd": None}))

    def test_resume_of_pre_cap_checkpoint_omits_flag(self):
        self.assertNotIn("--max-cumulative-usd", self._resume_argv({}))

    def test_malformed_checkpoint_policy_is_rejected_before_mkdir(self):
        for policy in ("x", ["a"], {"max_cumulative_usd": "abc"}, {"max_cumulative_usd": True},
                       {"max_cumulative_usd": -1}):
            with self.subTest(policy=policy):
                with self.assertRaises(ValueError):
                    self._resume_argv(policy)


class ConsoleUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = INDEX.read_text(encoding="utf-8")

    def test_save_rejects_bad_cap_input_instead_of_sending_null(self):
        # Regression guard: a number input reports unparseable text as "", which
        # used to be saved as null and silently clear the cap.
        save = self.html[self.html.index("$('saveSecurity').onclick"):]
        save = save[:save.index("};")]
        self.assertIn("capEl.validity.badInput", save)
        self.assertIn("Number.isFinite(max_cumulative_usd)&&max_cumulative_usd>0", save)

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
