"""Broker-dispatch wiring of action_reversibility.require_approval.

Finishes the P0-05 runtime story: the gate module becomes an enforced check
inside `mcp_registry.call_tool`. Default is backward-compatible (off); the
operator opts in with `require_action_approval=True` and threads an
action-bound approval record.
"""

import importlib.util
import json
import sys
import tempfile
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

for name in ("mcp_registry", "action_reversibility"):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / (name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)

mcp = sys.modules["mcp_registry"]
ar = sys.modules["action_reversibility"]


class _FakeClient:
    def __init__(self, text="ok"):
        self._text = text

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def initialize(self):
        return None

    def call_tool(self, name, arguments):
        return {"content": [{"type": "text", "text": self._text}], "isError": False}


def _factory(text="ok"):
    def f(spec):
        return _FakeClient(text)
    return f


SPEC = {"name": "test-server", "source": "test", "transport": "stdio",
        "command": "x", "args": [], "url": None, "_env": {}, "env_keys": [],
        "inherit_env": []}


def _setup(td: Path, tool_name="delete_file", *, access="mutate"):
    from capability_permits import PermitAuthority  # type: ignore
    catalog = mcp.McpCatalog(td / "mcp.db")
    annotations = ({"destructiveHint": True} if access == "mutate"
                   else {"readOnlyHint": True})
    tools = [{"name": tool_name, "annotations": annotations,
              "inputSchema": {"type": "object"}, "description": "x"}]
    catalog.ingest(SPEC, tools, trusted_servers={"test-server"})
    auth = PermitAuthority(td / "permits.jsonl")
    if access == "mutate":
        capability = "mcp.mutate"
        basis = {"kind": "jev_decision", "decision_id": "e1", "choice": "dispatch",
                 "state_hash": "a" * 64, "live": True}
    else:
        capability = "mcp.read"
        basis = {"kind": "operator", "operator": "ken", "reason": "dispatch-gate-test"}
    scope = mcp.permit_scope("test-server", tool_name, {}, access,
                             catalog.describe("test-server", tool_name)["schema_hash"])
    permit = auth.issue(capability, scope, basis)
    return catalog, auth, permit


class DispatchGateBackwardCompatTests(unittest.TestCase):
    def test_default_does_not_gate(self):
        """Backward compat: existing callers that do not opt into the gate run
        the tool regardless of reversibility classification."""
        with tempfile.TemporaryDirectory() as tds:
            td = Path(tds)
            catalog, auth, permit = _setup(td)
            try:
                outcome = mcp.call_tool(catalog, SPEC, "delete_file", {}, permit, auth,
                                        client_factory=_factory())
            finally:
                catalog.db.close()
        self.assertEqual(outcome["receipt"]["status"], "ok")
        self.assertNotIn("action_reversibility", outcome["receipt"])


class DispatchGateEnforcementTests(unittest.TestCase):
    def test_non_reversible_without_approval_is_refused(self):
        with tempfile.TemporaryDirectory() as tds:
            td = Path(tds)
            catalog, auth, permit = _setup(td)
            try:
                with self.assertRaises(Exception) as _ctx:
                    mcp.call_tool(catalog, SPEC, "delete_file", {}, permit, auth,
                                  client_factory=_factory(),
                                  require_action_approval=True)
                self.assertEqual(type(_ctx.exception).__name__, "NonReversibleActionError")
            finally:
                catalog.db.close()

    def test_non_reversible_with_matching_approval_runs(self):
        with tempfile.TemporaryDirectory() as tds:
            td = Path(tds)
            catalog, auth, permit = _setup(td)
            approval = {"status": "approved", "operator": "ken@local",
                        "action": "delete_file"}
            try:
                outcome = mcp.call_tool(catalog, SPEC, "delete_file", {}, permit, auth,
                                        client_factory=_factory(),
                                        require_action_approval=True,
                                        approval=approval)
            finally:
                catalog.db.close()
        self.assertEqual(outcome["receipt"]["status"], "ok")
        self.assertEqual(outcome["receipt"]["action_reversibility"]["classification"],
                         "non_reversible")
        self.assertEqual(outcome["receipt"]["action_reversibility"]["approved_by"],
                         "ken@local")

    def test_non_reversible_with_mismatched_approval_is_refused(self):
        with tempfile.TemporaryDirectory() as tds:
            td = Path(tds)
            catalog, auth, permit = _setup(td)
            approval = {"status": "approved", "operator": "ken@local",
                        "action": "something_else"}
            try:
                with self.assertRaises(Exception) as _ctx:
                    mcp.call_tool(catalog, SPEC, "delete_file", {}, permit, auth,
                                  client_factory=_factory(),
                                  require_action_approval=True,
                                  approval=approval)
                self.assertEqual(type(_ctx.exception).__name__, "NonReversibleActionError")
            finally:
                catalog.db.close()

    def test_reversible_tool_passes_gate_without_approval(self):
        with tempfile.TemporaryDirectory() as tds:
            td = Path(tds)
            catalog, auth, permit = _setup(td, tool_name="read_file", access="read")
            try:
                outcome = mcp.call_tool(catalog, SPEC, "read_file", {}, permit, auth,
                                        client_factory=_factory(),
                                        require_action_approval=True)
            finally:
                catalog.db.close()
        self.assertEqual(outcome["receipt"]["status"], "ok")
        self.assertEqual(outcome["receipt"]["action_reversibility"]["classification"],
                         "reversible")
        self.assertFalse(outcome["receipt"]["action_reversibility"]["approval_required"])

    def test_pending_approval_is_refused(self):
        with tempfile.TemporaryDirectory() as tds:
            td = Path(tds)
            catalog, auth, permit = _setup(td)
            approval = {"status": "pending", "operator": None, "action": "delete_file"}
            try:
                with self.assertRaises(Exception) as _ctx:
                    mcp.call_tool(catalog, SPEC, "delete_file", {}, permit, auth,
                                  client_factory=_factory(),
                                  require_action_approval=True,
                                  approval=approval)
                self.assertEqual(type(_ctx.exception).__name__, "NonReversibleActionError")
            finally:
                catalog.db.close()

    def test_gate_runs_before_the_tool_is_contacted(self):
        """The permit is consumed before the client call today; the action
        gate must sit before the client call too so a refused action never
        emits the external effect."""
        calls = []

        def tracking_factory(spec):
            calls.append(spec["name"])
            return _FakeClient()

        with tempfile.TemporaryDirectory() as tds:
            td = Path(tds)
            catalog, auth, permit = _setup(td)
            try:
                with self.assertRaises(Exception) as _ctx:
                    mcp.call_tool(catalog, SPEC, "delete_file", {}, permit, auth,
                                  client_factory=tracking_factory,
                                  require_action_approval=True)
                self.assertEqual(type(_ctx.exception).__name__, "NonReversibleActionError")
            finally:
                catalog.db.close()
        self.assertEqual(calls, [], "the client factory must not be invoked when the gate refuses")


if __name__ == "__main__":
    unittest.main()
