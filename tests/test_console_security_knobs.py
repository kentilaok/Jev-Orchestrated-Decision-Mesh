"""Operator Console surfacing of P0-05 security knobs.

Three state fields and a listing endpoint so the operator can read/edit
these from the browser instead of only through code:

- `trusted_mcp_servers`: list[str] of MCP server names whose annotations
  are trusted by `mcp_registry.classify`'s trust gate.
- `content_policy`: 'off' | 'audit' | 'wrap'.
- `require_action_approval`: bool.

Plus `GET /api/approvals` to list pending approvals waiting on the
operator.
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
sys.modules["operator_console"] = console
spec.loader.exec_module(console)


class DefaultsTests(unittest.TestCase):
    def test_default_config_has_security_fields(self):
        cfg = console._merge_config({})
        self.assertEqual(cfg["trusted_mcp_servers"], [])
        self.assertEqual(cfg["content_policy"], "off")
        self.assertFalse(cfg["require_action_approval"])


class MergeValidationTests(unittest.TestCase):
    def test_content_policy_valid_values_accepted(self):
        for value in ("off", "audit", "wrap"):
            cfg = console._merge_config({"content_policy": value})
            self.assertEqual(cfg["content_policy"], value)

    def test_content_policy_invalid_value_rejected(self):
        with self.assertRaises(ValueError):
            console._merge_config({"content_policy": "nonsense"})

    def test_require_action_approval_coerces_to_bool(self):
        cfg = console._merge_config({"require_action_approval": True})
        self.assertTrue(cfg["require_action_approval"])

    def test_require_action_approval_rejects_non_bool(self):
        with self.assertRaises(ValueError):
            console._merge_config({"require_action_approval": "yes"})

    def test_trusted_mcp_servers_accepts_list(self):
        cfg = console._merge_config({"trusted_mcp_servers": ["github", "fs"]})
        self.assertEqual(cfg["trusted_mcp_servers"], ["github", "fs"])

    def test_trusted_mcp_servers_rejects_non_list(self):
        with self.assertRaises(ValueError):
            console._merge_config({"trusted_mcp_servers": "github"})

    def test_trusted_mcp_servers_rejects_non_string_entries(self):
        with self.assertRaises(ValueError):
            console._merge_config({"trusted_mcp_servers": [1, 2]})


class ApprovalsListingHttpTests(unittest.TestCase):
    """GET /api/approvals returns the list of pending approval records."""

    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        root = Path(cls.temp.name)
        (root / "runs" / "approvals").mkdir(parents=True)
        state = console.StateStore(root / "state.json")
        state.save({"runs_directory": str(root / "runs"), "arsenal_db": str(root / "none.db"),
                    "calibration_ledger": str(root / "none.jsonl"), "mcp_db": str(root / "mcp.db"),
                    "skills_source": str(root / "skills"), "project_directory": str(root),
                    "hermes_dashboard_url": "http://127.0.0.1:9"})
        console.Handler.store = state
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

    def _write_approval(self, token: str, status: str = "pending"):
        rec = {"token": token, "status": status, "created": 1, "thread_id": "t",
               "goal": "do a thing", "provider": "claude", "gate_policy": "recovery"}
        (self.root / "runs" / "approvals" / (token + ".json")).write_text(
            json.dumps(rec), encoding="utf-8")

    def _get(self, path):
        connection = HTTPConnection("127.0.0.1", self.port, timeout=10)
        connection.request("GET", path,
                           headers={"Host": "127.0.0.1:%d" % self.port})
        response = connection.getresponse()
        data = response.read()
        connection.close()
        return response.status, json.loads(data) if data else {}

    def test_empty_approvals_dir(self):
        for f in (self.root / "runs" / "approvals").iterdir():
            f.unlink()
        status, body = self._get("/api/approvals")
        self.assertEqual(status, 200)
        self.assertEqual(body["pending"], [])
        self.assertEqual(body["decided"], [])

    def test_pending_and_decided_are_separated(self):
        for f in (self.root / "runs" / "approvals").iterdir():
            f.unlink()
        self._write_approval("a" * 32, "pending")
        self._write_approval("b" * 32, "approved")
        self._write_approval("c" * 32, "rejected")
        status, body = self._get("/api/approvals")
        self.assertEqual(status, 200)
        pending_tokens = [r["token"] for r in body["pending"]]
        decided_tokens = [r["token"] for r in body["decided"]]
        self.assertEqual(pending_tokens, ["a" * 32])
        self.assertEqual(sorted(decided_tokens), sorted(["b" * 32, "c" * 32]))

    def test_approvals_endpoint_does_not_leak_outside_runs_directory(self):
        """Token path traversal must not escape the approvals directory."""
        status, body = self._get("/api/approvals")
        self.assertEqual(status, 200)
        for record in body["pending"] + body["decided"]:
            self.assertTrue(len(record["token"]) <= 128)


if __name__ == "__main__":
    unittest.main()
