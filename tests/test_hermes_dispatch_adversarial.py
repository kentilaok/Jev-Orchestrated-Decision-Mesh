"""Slice 6: adversarial pass tests for P0-04 Hermes dispatch adapter.

Pass condition (production handoff P0-04): prove the gate holds end-to-end.
These tests exercise the bypass paths an attacker (or a buggy caller) would
try and assert that CIDM refuses them.
"""

import importlib.util
import json
import os
import sys
import tempfile
import threading
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


class HermesDispatchAdversarialTests(unittest.TestCase):
    """A live Handler on an ephemeral port; each test probes a bypass vector."""

    API_KEY = "test-key-adversarial"

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
        cls._prior = os.environ.get("CIDM_API_KEY")
        os.environ["CIDM_API_KEY"] = cls.API_KEY
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), console.Handler)
        console.Handler.port = cls.server.server_address[1]
        cls.port = cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.root = root

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.temp.cleanup()
        if cls._prior is None:
            os.environ.pop("CIDM_API_KEY", None)
        else:
            os.environ["CIDM_API_KEY"] = cls._prior

    def _request(self, method, path, body=None, headers=None):
        connection = HTTPConnection("127.0.0.1", self.port, timeout=15)
        hdrs = {"Host": "127.0.0.1:%d" % self.port}
        if body is not None:
            hdrs["Content-Type"] = "application/json"
        hdrs.update(headers or {})
        connection.request(method, path, body=(json.dumps(body) if body is not None else None),
                           headers=hdrs)
        response = connection.getresponse()
        data = response.read()
        connection.close()
        return response, data

    def _good_body(self, user="hello"):
        return {"model": "cidm-jev", "messages": [{"role": "user", "content": user}]}

    # --------------------------------------------------------------------
    # Vector A: a Hermes client that forgets the bearer token.
    # --------------------------------------------------------------------
    def test_a_no_bearer_token_cannot_dispatch(self):
        response, _ = self._request("POST", "/v1/chat/completions", self._good_body())
        self.assertEqual(response.status, 401)

    def test_a_wrong_bearer_token_cannot_dispatch(self):
        response, _ = self._request("POST", "/v1/chat/completions", self._good_body(),
                                    {"Authorization": "Bearer wrong"})
        self.assertEqual(response.status, 401)

    # --------------------------------------------------------------------
    # Vector B: cross-origin / DNS-rebinding attempts to reach the broker.
    # --------------------------------------------------------------------
    def test_b_rebinding_host_header_refused(self):
        response, _ = self._request("POST", "/v1/chat/completions", self._good_body(),
                                    {"Authorization": "Bearer " + self.API_KEY,
                                     "Host": "attacker.example:%d" % self.port})
        self.assertEqual(response.status, 403)

    # --------------------------------------------------------------------
    # Vector C: Hermes dashboard (or any browser-side script) tries to call
    # the broker from a web page. Browsers would need the console-CSRF
    # header to bypass defense-in-depth; the OpenAI route doesn't accept it
    # as auth, so even if the header is forged the bearer is still required.
    # --------------------------------------------------------------------
    def test_c_console_csrf_header_alone_does_not_dispatch(self):
        response, _ = self._request("POST", "/v1/chat/completions", self._good_body(),
                                    {"X-CIDM-Console": "1"})
        self.assertEqual(response.status, 401)

    # --------------------------------------------------------------------
    # Vector D: unknown model id tries to piggyback on the authenticated route.
    # --------------------------------------------------------------------
    def test_d_unknown_model_is_rejected_as_invalid_request(self):
        response, data = self._request("POST", "/v1/chat/completions",
                                       {"model": "gpt-5", "messages": [{"role": "user", "content": "x"}]},
                                       {"Authorization": "Bearer " + self.API_KEY})
        self.assertEqual(response.status, 400)
        body = json.loads(data)
        self.assertEqual(body["error"]["type"], "invalid_request_error")

    # --------------------------------------------------------------------
    # Vector E: a strong request is not allowed to run as a normal request.
    # The handler MUST return approval metadata; it MUST NOT emit a plan
    # summary that pretends to have executed.
    # --------------------------------------------------------------------
    def test_e_strong_request_cannot_execute_without_approval(self):
        response, data = self._request("POST", "/v1/chat/completions",
                                       {"model": "cidm-jev",
                                        "messages": [{"role": "user",
                                                      "content": "drop the production users table"}]},
                                       {"Authorization": "Bearer " + self.API_KEY})
        self.assertEqual(response.status, 200)
        body = json.loads(data)
        self.assertEqual(body["cidm"]["status"], "pending_approval")
        self.assertTrue(body["cidm"]["approval_token"])
        self.assertNotIn("[CIDM validate] Request accepted",
                         body["choices"][0]["message"]["content"])
        # Token must exist on disk with pending status (not pre-approved).
        token = body["cidm"]["approval_token"]
        record_path = self.root / "runs" / "approvals" / (token + ".json")
        self.assertTrue(record_path.is_file())
        record = json.loads(record_path.read_text(encoding="utf-8"))
        self.assertEqual(record["status"], "pending")

    # --------------------------------------------------------------------
    # Vector F: approval endpoint cannot be driven from a browser without
    # the Console-CSRF header. Prevents a hostile page from auto-approving
    # strong permits via a cross-origin POST.
    # --------------------------------------------------------------------
    def test_f_approvals_post_refuses_without_console_csrf_header(self):
        strong_response, strong_data = self._request(
            "POST", "/v1/chat/completions",
            {"model": "cidm-jev",
             "messages": [{"role": "user", "content": "delete all logs"}]},
            {"Authorization": "Bearer " + self.API_KEY})
        token = json.loads(strong_data)["cidm"]["approval_token"]
        response, _ = self._request("POST", "/api/approvals/" + token,
                                    {"decision": "approve", "operator": "attacker"})
        self.assertEqual(response.status, 403)
        # Record is still pending.
        record = json.loads((self.root / "runs" / "approvals" / (token + ".json"))
                            .read_text(encoding="utf-8"))
        self.assertEqual(record["status"], "pending")

    # --------------------------------------------------------------------
    # Vector G: once a token is decided it cannot be re-approved. Prevents
    # a race where an attacker approves after a reject.
    # --------------------------------------------------------------------
    def test_g_decided_token_is_one_shot(self):
        strong_response, strong_data = self._request(
            "POST", "/v1/chat/completions",
            {"model": "cidm-jev",
             "messages": [{"role": "user", "content": "destroy the archive"}]},
            {"Authorization": "Bearer " + self.API_KEY})
        token = json.loads(strong_data)["cidm"]["approval_token"]
        self._request("POST", "/api/approvals/" + token,
                      {"decision": "reject", "operator": "ken"},
                      {"X-CIDM-Console": "1"})
        response, data = self._request("POST", "/api/approvals/" + token,
                                       {"decision": "approve", "operator": "ken"},
                                       {"X-CIDM-Console": "1"})
        self.assertEqual(response.status, 400)
        body = json.loads(data)
        self.assertIn("already rejected", body["error"])

    # --------------------------------------------------------------------
    # Vector H: method confusion — GET on the OpenAI route must not run the
    # dispatch logic. The server returns a static page for the Console UI
    # instead; the key requirement is that no CIDM run folder gets created.
    # --------------------------------------------------------------------
    def test_h_get_on_dispatch_path_does_not_run_broker(self):
        before = list((self.root / "runs").glob("*"))
        response, _ = self._request("GET", "/v1/chat/completions")
        self.assertNotEqual(response.status, 500)
        after = list((self.root / "runs").glob("*"))
        # No new run directory was created by the GET.
        self.assertEqual(len(before), len(after))


if __name__ == "__main__":
    unittest.main()
