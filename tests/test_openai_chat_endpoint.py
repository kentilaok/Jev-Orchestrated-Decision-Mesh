"""Slice 1 tests: OpenAI-shaped /v1/chat/completions endpoint on the Operator Console.

Target: scripts/operator_console.py chat_completions() function + HTTP route.
Scope: non-streaming, non-live (validate-only broker path). No model calls.
"""

import importlib.util
import json
import os
import sys
import tempfile
import threading
import time
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
MODULE = ROOT / "scripts" / "operator_console.py"
spec = importlib.util.spec_from_file_location("operator_console", MODULE)
console = importlib.util.module_from_spec(spec)
spec.loader.exec_module(console)


class ChatCompletionsEndpointTests(unittest.TestCase):
    def _basic_payload(self):
        return {
            "model": "cidm-jev",
            "messages": [
                {"role": "user", "content": "Summarise what you would do for this task."}
            ],
        }

    def test_returns_openai_chat_completion_shape(self):
        cfg = console._merge_config({})
        before = int(time.time())
        response = console.chat_completions(self._basic_payload(), cfg)
        after = int(time.time())

        # Envelope
        self.assertIsInstance(response, dict)
        self.assertTrue(response.get("id", "").startswith("chatcmpl-"))
        self.assertEqual(response["object"], "chat.completion")
        self.assertTrue(before <= response["created"] <= after)
        self.assertEqual(response["model"], "cidm-jev")

        # Choices
        self.assertIsInstance(response["choices"], list)
        self.assertEqual(len(response["choices"]), 1)
        choice = response["choices"][0]
        self.assertEqual(choice["index"], 0)
        self.assertEqual(choice["message"]["role"], "assistant")
        self.assertIsInstance(choice["message"]["content"], str)
        self.assertTrue(len(choice["message"]["content"]) > 0)
        self.assertEqual(choice["finish_reason"], "stop")

        # Usage (OpenAI shape; unknown counts allowed as 0 per CIDM "unknown is not zero" rule
        # once we add real accounting; for slice 1 the broker path is validate-only so counts are 0).
        self.assertIn("usage", response)
        usage = response["usage"]
        for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
            self.assertIn(key, usage)
            self.assertIsInstance(usage[key], int)

    def test_rejects_missing_messages(self):
        cfg = console._merge_config({})
        with self.assertRaises(ValueError):
            console.chat_completions({"model": "cidm-jev"}, cfg)

    def test_rejects_empty_messages(self):
        cfg = console._merge_config({})
        with self.assertRaises(ValueError):
            console.chat_completions({"model": "cidm-jev", "messages": []}, cfg)

    def test_rejects_unknown_model(self):
        cfg = console._merge_config({})
        payload = self._basic_payload()
        payload["model"] = "gpt-6-luna"
        with self.assertRaises(ValueError):
            console.chat_completions(payload, cfg)

    def test_default_mode_is_validate_only_no_model_calls(self):
        """Slice 1 pass condition: default path must not invoke frontier workers.

        The validate-only summary is identifiable: it starts with a known marker
        so Hermes (and tests) can distinguish a plan from a live answer.
        """
        cfg = console._merge_config({})
        response = console.chat_completions(self._basic_payload(), cfg)
        content = response["choices"][0]["message"]["content"]
        self.assertTrue(
            content.startswith("[CIDM validate]"),
            f"Expected validate-only marker; got: {content[:80]!r}",
        )


class ThreadBindingTests(unittest.TestCase):
    """Slice 2: same Hermes thread (same first user message) -> same thread_id and journal."""

    def _cfg(self, root: Path):
        return console._merge_config({"runs_directory": str(root / "runs")})

    def test_same_first_user_message_yields_stable_thread_id(self):
        msgs_a = [{"role": "user", "content": "Plan the refactor"}]
        msgs_b = [{"role": "user", "content": "Plan the refactor"},
                  {"role": "assistant", "content": "..."},
                  {"role": "user", "content": "Now estimate cost"}]
        self.assertEqual(console._derive_thread_id(msgs_a), console._derive_thread_id(msgs_b))

    def test_different_first_user_message_yields_different_thread_id(self):
        msgs_a = [{"role": "user", "content": "Plan the refactor"}]
        msgs_b = [{"role": "user", "content": "Write a haiku"}]
        self.assertNotEqual(console._derive_thread_id(msgs_a), console._derive_thread_id(msgs_b))

    def test_system_prompt_does_not_change_thread_id(self):
        msgs_a = [{"role": "user", "content": "Hi"}]
        msgs_b = [{"role": "system", "content": "You are helpful"},
                  {"role": "user", "content": "Hi"}]
        self.assertEqual(console._derive_thread_id(msgs_a), console._derive_thread_id(msgs_b))

    def test_chat_completions_includes_thread_id_in_response(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = self._cfg(Path(td))
            response = console.chat_completions(
                {"model": "cidm-jev", "messages": [{"role": "user", "content": "x"}]}, cfg)
            self.assertIn("cidm", response)
            self.assertIn("thread_id", response["cidm"])
            self.assertEqual(response["cidm"]["thread_id"],
                             console._derive_thread_id([{"role": "user", "content": "x"}]))

    def test_journal_is_appended_across_same_thread_calls(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = self._cfg(Path(td))
            msgs_first = [{"role": "user", "content": "Design the adapter"}]
            msgs_follow = [{"role": "user", "content": "Design the adapter"},
                           {"role": "assistant", "content": "[CIDM validate] ..."},
                           {"role": "user", "content": "Now show the slice plan"}]
            r1 = console.chat_completions({"model": "cidm-jev", "messages": msgs_first}, cfg)
            r2 = console.chat_completions({"model": "cidm-jev", "messages": msgs_follow}, cfg)
            self.assertEqual(r1["cidm"]["thread_id"], r2["cidm"]["thread_id"])

            journal_path = Path(cfg["runs_directory"]) / "threads" / (r1["cidm"]["thread_id"] + ".json")
            self.assertTrue(journal_path.is_file())
            data = json.loads(journal_path.read_text(encoding="utf-8"))
            self.assertEqual(data["thread_id"], r1["cidm"]["thread_id"])
            self.assertEqual(len(data["turns"]), 2)
            self.assertEqual(data["turns"][0]["goal"], "Design the adapter")
            self.assertEqual(data["turns"][1]["goal"], "Now show the slice plan")

    def test_different_threads_write_different_journals(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = self._cfg(Path(td))
            r1 = console.chat_completions(
                {"model": "cidm-jev", "messages": [{"role": "user", "content": "A"}]}, cfg)
            r2 = console.chat_completions(
                {"model": "cidm-jev", "messages": [{"role": "user", "content": "B"}]}, cfg)
            self.assertNotEqual(r1["cidm"]["thread_id"], r2["cidm"]["thread_id"])
            threads_dir = Path(cfg["runs_directory"]) / "threads"
            self.assertEqual(len(list(threads_dir.glob("*.json"))), 2)


class ChatCompletionsHttpTests(unittest.TestCase):
    """End-to-end HTTP tests: Hermes-shaped request → OpenAI response via the real Handler."""

    API_KEY = "test-key-slice1-only"

    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        root = Path(cls.temp.name)
        (root / "runs").mkdir()
        state = console.StateStore(root / "state.json")
        state.save({"runs_directory": str(root / "runs"), "arsenal_db": str(root / "none.db"),
                    "calibration_ledger": str(root / "none.jsonl"), "mcp_db": str(root / "mcp.db"),
                    "skills_source": str(root / "skills"), "project_directory": str(root),
                    "hermes_dashboard_url": "http://127.0.0.1:9"})
        console.Handler.store = state
        cls._prior_api_key = os.environ.get("CIDM_API_KEY")
        os.environ["CIDM_API_KEY"] = cls.API_KEY
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), console.Handler)
        console.Handler.port = cls.server.server_address[1]
        cls.port = cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.temp.cleanup()
        if cls._prior_api_key is None:
            os.environ.pop("CIDM_API_KEY", None)
        else:
            os.environ["CIDM_API_KEY"] = cls._prior_api_key

    def _post(self, path, body, headers=None):
        connection = HTTPConnection("127.0.0.1", self.port, timeout=15)
        hdrs = {"Host": "127.0.0.1:%d" % self.port, "Content-Type": "application/json"}
        hdrs.update(headers or {})
        connection.request("POST", path, body=json.dumps(body), headers=hdrs)
        response = connection.getresponse()
        data = response.read()
        connection.close()
        parsed = json.loads(data) if data and data[:1] in b"{[" else data
        return response.status, parsed

    def _good_body(self):
        return {"model": "cidm-jev", "messages": [{"role": "user", "content": "hello"}]}

    def test_requires_authorization_header(self):
        status, body = self._post("/v1/chat/completions", self._good_body())
        self.assertEqual(status, 401)
        self.assertEqual(body["error"]["type"], "auth_error")

    def test_rejects_wrong_bearer_token(self):
        status, body = self._post("/v1/chat/completions", self._good_body(),
                                  {"Authorization": "Bearer wrong-token"})
        self.assertEqual(status, 401)

    def test_rejects_cross_origin_host(self):
        status, _ = self._post("/v1/chat/completions", self._good_body(),
                               {"Authorization": "Bearer " + self.API_KEY,
                                "Host": "attacker.example:%d" % self.port})
        self.assertEqual(status, 403)

    def test_accepts_valid_bearer_returns_openai_shape(self):
        status, body = self._post("/v1/chat/completions", self._good_body(),
                                  {"Authorization": "Bearer " + self.API_KEY})
        self.assertEqual(status, 200)
        self.assertEqual(body["object"], "chat.completion")
        self.assertEqual(body["choices"][0]["message"]["role"], "assistant")
        self.assertTrue(body["choices"][0]["message"]["content"].startswith("[CIDM validate]"))

    def test_bad_payload_returns_400(self):
        status, body = self._post("/v1/chat/completions", {"model": "cidm-jev"},
                                  {"Authorization": "Bearer " + self.API_KEY})
        self.assertEqual(status, 400)
        self.assertEqual(body["error"]["type"], "invalid_request_error")

    def test_browser_csrf_header_not_required_for_openai_route(self):
        """OpenAI clients don't send X-CIDM-Console. The guard must not require it here."""
        status, _ = self._post("/v1/chat/completions", self._good_body(),
                               {"Authorization": "Bearer " + self.API_KEY})
        self.assertEqual(status, 200)

    def test_browser_csrf_header_still_required_on_existing_api(self):
        """Regression: /api/* POSTs must still enforce the browser-CSRF header."""
        status, _ = self._post("/api/config", {"frontier_provider": "codex"},
                               {"Authorization": "Bearer " + self.API_KEY})
        self.assertEqual(status, 403)


if __name__ == "__main__":
    unittest.main()
