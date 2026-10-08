"""Offline checks for the one-call Sol-high comparison. No API traffic."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import urllib.error

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from atomic_mesh import MeshError
from compare_baseline import (BASELINE_SCHEMA, DEMO, RunConfig, run_baseline,
                              simulated_candidate)
from network_run import DemoPipeline
from transport import Gateway


class BaselineTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.config = RunConfig()
        self.task = json.loads(json.dumps(DEMO))
        env = patch.dict("os.environ", {"OPENROUTER_API_KEY": "sk-test-baseline-do-not-log"})
        env.start()
        self.addCleanup(env.stop)

    def response(self, candidate):
        return {
            "model": "openai/gpt-6-sol", "provider": self.config.provider_name,
            "usage": {"prompt_tokens": 150, "completion_tokens": 80,
                      "total_tokens": 230, "cost": 0.0005,
                      "prompt_tokens_details": {"cached_tokens": 20},
                      "completion_tokens_details": {"reasoning_tokens": 30}},
            "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(candidate)}}],
        }

    def stored_text(self, folder):
        return "\n".join(path.read_text(encoding="utf-8") for path in folder.iterdir()
                         if path.is_file())

    def test_live_path_makes_exactly_one_sol_high_call_and_preserves_usage(self):
        candidate = simulated_candidate(self.task, DemoPipeline(self.task))
        folder = self.root / "baseline"
        with patch.object(Gateway, "_request", return_value=self.response(candidate)) as request:
            result = run_baseline(self.task, self.config, folder, live=True)
        self.assertEqual(request.call_count, 1)
        role, payload, _ = request.call_args.args
        self.assertEqual(role, "worker")
        self.assertEqual((payload["model"], payload["reasoning"]["effort"]),
                         ("openai/gpt-6-sol", "high"))
        self.assertEqual(payload["messages"][1]["content"],
                         json.dumps({"source_id": "records", "task": self.task},
                                    sort_keys=True, separators=(",", ":"), ensure_ascii=True))
        expected_schema = json.loads(json.dumps(BASELINE_SCHEMA))
        expected_schema["properties"]["unit"]["enum"] = ["defects per 1000 production items"]
        self.assertEqual(payload["response_format"]["json_schema"]["schema"], expected_schema)
        self.assertEqual((result["status"], result["answer"], result["simulation"]),
                         ("complete", 50.0, False))
        self.assertTrue(all(result["quality_checks"].values()))
        self.assertEqual(result["usage"]["total_tokens"], 230)
        self.assertEqual(result["usage"]["cost"], 0.0005)
        self.assertTrue(result["usage"]["usage_complete"])
        self.assertEqual(result["calls"][0]["usage"]["cached_input_tokens"], 20)
        self.assertEqual(result["calls"][0]["usage"]["reasoning_tokens"], 30)
        self.assertNotIn("sk-test-baseline-do-not-log", self.stored_text(folder))

    def test_wrong_trial_scope_is_quality_failure_without_retry(self):
        candidate = simulated_candidate(self.task, DemoPipeline(self.task))
        candidate["answer"] = 100.0
        candidate["included_segments"] = ["A", "B", "T"]
        candidate["excluded_segments"] = []
        folder = self.root / "wrong-scope"
        with patch.object(Gateway, "_request", return_value=self.response(candidate)) as request:
            result = run_baseline(self.task, self.config, folder, live=True)
        self.assertEqual(request.call_count, 1)
        self.assertEqual(result["status"], "quality_failed")
        self.assertFalse(result["quality_checks"]["answer_matches_exact_reference"])
        self.assertFalse(result["quality_checks"]["excluded_segments_match_scope"])
        self.assertEqual(result["usage"]["total_tokens"], 230)
        self.assertEqual(len(result["calls"]), 1)

    def test_failed_provider_attempt_is_recorded_without_retry_or_fake_usage(self):
        folder = self.root / "provider-failure"
        with patch.object(Gateway, "_request", side_effect=urllib.error.URLError("offline")) as request:
            result = run_baseline(self.task, self.config, folder, live=True)
        self.assertEqual(request.call_count, 1)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["error_code"], "provider_call_failed")
        self.assertEqual(len(result["calls"]), 1)
        self.assertEqual(result["calls"][0]["status"], "failed")
        self.assertEqual(result["calls"][0]["error"]["code"], "network_error")
        self.assertIsNone(result["usage"]["total_tokens"])
        self.assertFalse(result["usage"]["usage_complete"])
        self.assertTrue((folder / "call-1.request.json").exists())
        self.assertTrue((folder / "call-1.event.json").exists())
        self.assertTrue((folder / "result.json").exists())
        self.assertNotIn("sk-test-baseline-do-not-log", self.stored_text(folder))

    def test_cli_offline_is_labeled_simulation_and_output_must_be_fresh(self):
        source = Path(__file__).resolve().parents[1]
        folder = self.root / "offline"
        command = [sys.executable, "-S", str(source / "scripts" / "compare_baseline.py"),
                   "--offline", "--task", str(source / "examples" / "production-records.json"),
                   "--out", str(folder)]
        proc = subprocess.run(command, capture_output=True, text=True, check=False)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        result = json.loads((folder / "result.json").read_text(encoding="utf-8"))
        self.assertEqual(result["status"], "simulated")
        self.assertTrue(result["simulation"])
        self.assertEqual(result["answer"], 50.0)
        self.assertEqual(result["calls"], [])
        self.assertIsNone(result["usage"])
        self.assertFalse((folder / "call-1.request.json").exists())
        with self.assertRaisesRegex(MeshError, "output_directory_must_be_new"):
            run_baseline(self.task, self.config, folder, live=False)


if __name__ == "__main__":
    unittest.main()
