"""P0-03 slice 3b: capped smoke runner, offline.

A fake `claude` executable answers `auth status` only; any model call through it
writes a marker and fails. The low-budget negative launches the real broker as a
subprocess with a dummy key and a dead proxy, so nothing can reach the network.
"""
import contextlib
import datetime
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

from p0_03_smoke import SMOKE_CEILING_USD, main  # noqa: E402
from test_p0_03_audit import SessionCodex, build_run  # noqa: E402


class CostedClaude(SessionCodex):
    """Reports a cost like ClaudeCliAdapter, so a capped ledger stays verifiable."""

    def run(self, *args, **kwargs):
        return {**super().run(*args, **kwargs), 'api_equivalent_cost_usd': 0.01}

FAKE_CLAUDE = r'''
import json, sys
from pathlib import Path
if sys.argv[1:4] == ["auth", "status", "--json"]:
    print(json.dumps({"loggedIn": True, "authMethod": "claude.ai", "subscriptionType": "max"}))
    sys.exit(0)
Path(__file__).with_name("MODEL_CALLED").write_text(" ".join(sys.argv[1:3]), encoding="utf-8")
sys.exit(3)
'''

FIXED_CLOCK = lambda: datetime.datetime(2026, 10, 17, 1, 2, 3, tzinfo=datetime.timezone.utc)  # noqa: E731


def make_fake_claude(folder: Path) -> Path:
    script = folder / "fake_claude.py"
    script.write_text(FAKE_CLAUDE, encoding="utf-8")
    if sys.platform == "win32":
        wrapper = folder / "claude.cmd"
        wrapper.write_text('@"%s" "%s" %%*\r\n' % (sys.executable, script), encoding="utf-8")
    else:
        wrapper = folder / "claude"
        wrapper.write_text("#!/bin/sh\nexec '%s' '%s' \"$@\"\n" % (sys.executable, script), encoding="utf-8")
        wrapper.chmod(0o755)
    return wrapper


class SmokeRunnerTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.claude = make_fake_claude(self.tmp)
        self.out_root = self.tmp / "smoke"
        # Hermetic: no real keys and no variables of a Claude Code session running the suite.
        self.env = {k: v for k, v in os.environ.items()
                    if k.upper() not in ("OPENROUTER_API_KEY", "ANTHROPIC_API_KEY", "ANTHROPIC_BASE_URL")
                    and not k.upper().startswith("CLAUDE")}
        self.env.update(OPENROUTER_API_KEY="sk-test-smoke-do-not-log",
                        HTTPS_PROXY="http://127.0.0.1:9", HTTP_PROXY="http://127.0.0.1:9",
                        NO_PROXY="")
        self.launched = []

    def no_launch(self, command, **kwargs):
        self.launched.append(command)
        raise AssertionError("broker must not launch")

    def run_main(self, *args, env=None, launch=None):
        argv = ["--out-root", str(self.out_root), "--claude-executable", str(self.claude), *args]
        with contextlib.redirect_stdout(io.StringIO()) as out:
            code = main(argv, env=self.env if env is None else env,
                        launch=launch or self.no_launch, clock=FIXED_CLOCK)
        return code, out.getvalue()

    def report(self, mode):
        return json.loads((self.out_root / ("20261017T010203Z-" + mode) / "smoke-report.json")
                          .read_text(encoding="utf-8"))

    def assert_no_model_call(self):
        self.assertFalse((self.tmp / "MODEL_CALLED").exists())

    # Dry run and preflight.

    def test_dry_run_passes_preflight_and_launches_nothing(self):
        code, out = self.run_main("--dry-run")
        self.assertEqual(code, 0, out)
        plan = json.loads(out)
        self.assertTrue(plan["preflight"]["ok"])
        command = plan["command"]
        for flag in ("--live", "--host", "--max-cumulative-usd", "--claude-executable"):
            self.assertIn(flag, command)
        self.assertEqual(command[command.index("--max-cumulative-usd") + 1], repr(SMOKE_CEILING_USD))
        self.assertEqual(command[command.index("--gate-policy") + 1], "recovery")
        self.assertFalse(self.out_root.exists())
        self.assertNotIn("sk-test-smoke-do-not-log", out)
        self.assertEqual(self.launched, [])
        self.assert_no_model_call()

    def test_missing_openrouter_key_refuses_live_run(self):
        env = dict(self.env)
        del env["OPENROUTER_API_KEY"]
        code, _ = self.run_main("--live", env=env)
        self.assertEqual(code, 2)
        report = self.report("smoke")
        self.assertEqual(report["status"], "refused_before_launch")
        self.assertEqual(report["refused_checks"], ["openrouter_key"])
        self.assertEqual(self.launched, [])

    def test_caps_above_the_ceiling_are_refused(self):
        for flag in ("--max-usd", "--max-cumulative-usd"):
            with self.subTest(flag=flag):
                code, out = self.run_main("--dry-run", flag, "1.5")
                self.assertEqual(code, 2)
                failed = [k for k, v in json.loads(out)["preflight"]["checks"].items() if not v["ok"]]
                self.assertEqual(failed, ["jev_cap" if flag == "--max-usd" else "cumulative_cap"])

    def test_non_claude_worker_family_is_refused(self):
        config = self.tmp / "config.json"
        config.write_text(json.dumps({"worker_family": "gpt6"}), encoding="utf-8")
        code, out = self.run_main("--dry-run", "--config", str(config))
        self.assertEqual(code, 2)
        self.assertIn("smoke_requires_claude_worker_family", out)

    def test_claude_session_variables_are_removed_before_preflight_and_broker(self):
        env = dict(self.env, CLAUDECODE="1", CLAUDE_CODE_ENTRYPOINT="desktop", CLAUDE_PID="7",
                   ANTHROPIC_BASE_URL="http://127.0.0.1:9/host-proxy")
        seen = []
        def launch(command, **kwargs):
            seen.append(kwargs["env"])
            return self.fake_broker()(command, **kwargs)
        code, _ = self.run_main("--live", env=env, launch=launch)
        self.assertEqual(code, 0)
        removed = ["ANTHROPIC_BASE_URL", "CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "CLAUDE_PID"]
        self.assertEqual(self.report("smoke")["session_env_removed"], removed)
        for name in removed:
            self.assertNotIn(name, seen[0])
        self.assertIn("OPENROUTER_API_KEY", seen[0])

    def test_base_url_set_outside_a_session_is_kept(self):
        from p0_03_smoke import run_env
        kept, removed = run_env({"ANTHROPIC_BASE_URL": "https://example.test", "PATH": "x"})
        self.assertEqual(removed, [])
        self.assertIn("ANTHROPIC_BASE_URL", kept)

    # Negatives that the preflight must refuse.

    def test_provider_unavailable_is_refused_before_launch(self):
        code, _ = self.run_main("--live", "--negative", "provider-unavailable")
        self.assertEqual(code, 0)
        report = self.report("provider-unavailable")
        self.assertEqual(report["refused_checks"], ["claude_cli"])
        self.assertTrue(report["expectation"]["met"])
        self.assertFalse(report["preflight"]["checks"]["claude_cli"]["installed"])
        self.assertEqual(self.launched, [])

    def test_wrong_model_is_refused_before_launch(self):
        code, _ = self.run_main("--live", "--negative", "wrong-model")
        self.assertEqual(code, 0)
        report = self.report("wrong-model")
        self.assertEqual(report["refused_checks"], ["models_pinned"])
        self.assertTrue(report["expectation"]["met"])
        self.assertEqual(self.launched, [])

    # Low budget: the real broker runs and the gateway refuses the first Jev call.

    def test_low_budget_stops_before_any_paid_call(self):
        code, out = self.run_main("--live", "--negative", "low-budget", launch=subprocess.run)
        report = self.report("low-budget")
        self.assertEqual(code, 0, json.dumps(report, indent=2)[:4000])
        self.assertEqual(report["result_status"], "failed")  # the recovery network halts
        self.assertTrue(report["audit"]["ok"], report["audit"]["issues"])
        self.assertEqual(report["audit"]["evidence"]["jev_calls"], 0)
        self.assertEqual(report["audit"]["evidence"]["permits_consumed"], 0)
        self.assertEqual(report["jev_api_cost_usd"], 0)
        run = self.out_root / "20261017T010203Z-low-budget"
        result = json.loads((run / "broker" / "result.json").read_text(encoding="utf-8"))
        # The only call is the Jev decision the gateway refused at admission.
        self.assertEqual([(c["role"], c["status"], c["usage"]) for c in result["calls"]],
                         [("jev", "failed", None)])
        self.assertFalse((run / "broker" / "usage.jsonl").exists())
        self.assertNotIn("sk-test-smoke-do-not-log",
                         (run / "broker.stdout.txt").read_text(encoding="utf-8", errors="replace")
                         + (run / "broker.stderr.txt").read_text(encoding="utf-8", errors="replace"))
        self.assert_no_model_call()

    def test_broker_refuses_claude_executable_for_codex_host(self):
        out = self.tmp / "codex-out"
        proc = subprocess.run([sys.executable, str(ROOT / "scripts" / "native_transition_broker.py"),
                               "--task", str(ROOT / "examples" / "native-project.request.json"),
                               "--out", str(out), "--host", "codex",
                               "--claude-executable", str(self.claude), "--live"],
                              cwd=str(ROOT), env=self.env, capture_output=True, text=True, timeout=120)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("claude_executable_requires_claude_host", proc.stderr)
        self.assertFalse(out.exists())

    # Positive path, with the broker replaced by a fake that writes a clean run.

    def fake_broker(self, tamper=None):
        def launch(command, **kwargs):
            self.launched.append(command)
            out = Path(command[command.index("--out") + 1])
            config = json.loads(Path(command[command.index("--config") + 1]).read_text(encoding="utf-8"))
            from config import RunConfig
            built = build_run(self.tmp / ("build-%d" % len(self.launched)),
                              config=RunConfig.from_dict(config), adapter=CostedClaude())
            shutil.move(str(built), str(out))
            if tamper:
                tamper(out)
            return subprocess.CompletedProcess(command, 0)
        return launch

    def test_clean_live_run_meets_expectation(self):
        code, _ = self.run_main("--live", launch=self.fake_broker())
        self.assertEqual(code, 0)
        report = self.report("smoke")
        self.assertEqual(report["result_status"], "complete")
        self.assertTrue(report["expectation"]["met"], report["expectation"])
        self.assertEqual(len(self.launched), 1)

    def test_live_run_with_audit_issue_fails(self):
        def tamper(out):
            path = out / "result.json"
            result = json.loads(path.read_text(encoding="utf-8"))
            result["jev_api_cost_usd"] = 0.0
            path.write_text(json.dumps(result), encoding="utf-8")
        code, _ = self.run_main("--live", launch=self.fake_broker(tamper))
        self.assertEqual(code, 1)
        self.assertEqual(self.report("smoke")["expectation"]["reasons"], ["audit_failed"])

    def test_existing_run_folder_is_never_reused(self):
        self.run_main("--live", launch=self.fake_broker())
        with self.assertRaises(FileExistsError):
            self.run_main("--live", launch=self.fake_broker())


if __name__ == "__main__":
    unittest.main()
