"""Verify every Console caller of `broker_argv` forwards the active config
so the P0-05 content_policy / require_action_approval knobs reach the
subprocess by default (no explicit opt-in required by the operator)."""

import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

spec = importlib.util.spec_from_file_location(
    "operator_console", ROOT / "scripts" / "operator_console.py")
console = importlib.util.module_from_spec(spec)
sys.modules["operator_console"] = console
spec.loader.exec_module(console)


class CallSiteWiringTests(unittest.TestCase):
    """Patch `broker_argv` to capture its kwargs on every call. Each entry
    point must pass `config=<the operator config>`."""

    def _patch(self):
        captured = []
        original = console.broker_argv

        def tracker(*args, **kwargs):
            captured.append({"args": args, "kwargs": kwargs})
            return original(*args, **kwargs)

        console.broker_argv = tracker
        return captured, original

    def _unpatch(self, original):
        console.broker_argv = original

    def test_validate_broker_request_forwards_config(self):
        captured, original = self._patch()
        try:
            with tempfile.TemporaryDirectory() as tds:
                td = Path(tds)
                (td / "runs").mkdir()
                cfg = console._merge_config({
                    "project_directory": str(td), "runs_directory": str(td / "runs"),
                    "content_policy": "wrap", "require_action_approval": True,
                })
                payload = {"task": "do something", "context": "",
                           "sources": [{"title": "s", "text": "fixture"}]}
                # subprocess.run is called inside; stub it so the test does
                # not actually invoke native_transition_broker.py.
                real_run = subprocess.run

                class _Proc:
                    def __init__(self):
                        self.returncode = 0
                        self.stdout = json.dumps({"status": "ok"})
                        self.stderr = ""

                def fake_run(*a, **k):
                    return _Proc()

                subprocess.run = fake_run
                try:
                    console.validate_broker_request(payload, cfg)
                finally:
                    subprocess.run = real_run
        finally:
            self._unpatch(original)
        self.assertEqual(len(captured), 1)
        call = captured[0]
        self.assertIs(call["kwargs"].get("config"), cfg)

    def test_start_broker_job_forwards_config(self):
        captured, original = self._patch()
        try:
            with tempfile.TemporaryDirectory() as tds:
                td = Path(tds)
                (td / "runs").mkdir()
                cfg = console._merge_config({
                    "project_directory": str(td), "runs_directory": str(td / "runs"),
                    "content_policy": "audit",
                })
                payload = {"task": "do something", "context": "",
                           "sources": [{"title": "s", "text": "fixture"}],
                           "confirm_live_spend": True}
                real_start = console.JOBS.start

                def fake_start(argv, run_dir, meta):
                    return {"job_id": "test", "meta": meta, "argv": list(argv)}

                console.JOBS.start = fake_start
                try:
                    console.start_broker_job(payload, cfg)
                finally:
                    console.JOBS.start = real_start
        finally:
            self._unpatch(original)
        self.assertEqual(len(captured), 1)
        self.assertIs(captured[0]["kwargs"].get("config"), cfg)


if __name__ == "__main__":
    unittest.main()
