"""P0-05 slice 1 red tests: MCP server trust gate.

Current `classify(server, tool)` trusts any MCP server's `annotations.readOnlyHint`
to assign the 'read' access class. For an untrusted third-party server that is
unsafe — a malicious server can lie about a tool being read-only to get
read-tier permits. The production handoff §P0-05 requires that MCP
`readOnlyHint` be treated as an untrusted claim.

This slice adds an optional `trusted_servers` set. When supplied, servers not
in the set have their 'read'-via-annotation inference demoted to 'unknown'.
Destructive-hint claims are kept (more-restrictive is safer). Builtin profiles
and owner overrides take precedence.
"""

import importlib.util
import json
import sys
import tempfile
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
spec = importlib.util.spec_from_file_location("mcp_registry",
                                              ROOT / "scripts" / "mcp_registry.py")
mcp = importlib.util.module_from_spec(spec)
sys.modules["mcp_registry"] = mcp
spec.loader.exec_module(mcp)


class ClassifyTrustGateTests(unittest.TestCase):
    def _tool(self, name="mystery", annotations=None):
        return {"name": name, "annotations": annotations or {},
                "inputSchema": {"type": "object"}}

    def test_readonly_hint_from_unknown_server_is_demoted_to_unknown(self):
        access, basis = mcp.classify("mystery-server",
                                     self._tool(annotations={"readOnlyHint": True}),
                                     trusted_servers=set())
        self.assertEqual(access, "unknown")
        self.assertIn("untrusted", basis)

    def test_readonly_hint_from_trusted_server_classifies_as_read(self):
        access, basis = mcp.classify("mystery-server",
                                     self._tool(annotations={"readOnlyHint": True}),
                                     trusted_servers={"mystery-server"})
        self.assertEqual(access, "read")
        self.assertEqual(basis, "server_annotations")

    def test_destructive_hint_from_unknown_server_is_still_mutate(self):
        """Trusting a destructive hint from an untrusted server is safe — it
        can only *restrict* capability. The attack surface is a server lying
         'readOnly=true', not lying 'destructive=true'."""
        access, basis = mcp.classify("mystery-server",
                                     self._tool(annotations={"destructiveHint": True}),
                                     trusted_servers=set())
        self.assertEqual(access, "mutate")
        self.assertEqual(basis, "server_annotations")

    def test_readonly_false_from_unknown_server_is_still_mutate(self):
        """readOnlyHint=False is a stronger assertion than destructiveHint=True;
        trusting it to mean 'mutate' is also safe (restrictive)."""
        access, basis = mcp.classify("mystery-server",
                                     self._tool(annotations={"readOnlyHint": False}),
                                     trusted_servers=set())
        self.assertEqual(access, "mutate")

    def test_legacy_call_without_trusted_servers_preserves_old_behavior(self):
        """Backward compatibility: existing callers that do not pass
        trusted_servers keep the legacy trust-the-server posture."""
        access, basis = mcp.classify("mystery-server",
                                     self._tool(annotations={"readOnlyHint": True}))
        self.assertEqual(access, "read")
        self.assertEqual(basis, "server_annotations")

    def test_builtin_profile_wins_over_trust_gate(self):
        """Builtin profiles (shipped with the code, reviewed at merge time)
        are owner-vetted; they classify ahead of the trust gate even for an
        untrusted server name."""
        for key in mcp.PROFILES:
            profile = mcp.PROFILES[key]
            if not profile.get("read"):
                continue
            name = next(iter(profile["read"]))
            server = key + "-anywhere"
            access, basis = mcp.classify(server, {"name": name, "annotations": {}},
                                         trusted_servers=set())
            self.assertEqual(access, "read")
            self.assertTrue(basis.startswith("builtin_profile:"))
            break
        else:
            self.skipTest("no profile with a read-list entry to test")

    def test_unclassified_tool_on_untrusted_server_is_unknown(self):
        access, basis = mcp.classify("mystery-server",
                                     self._tool(annotations={}),
                                     trusted_servers=set())
        self.assertEqual(access, "unknown")


class CatalogIngestTrustGateTests(unittest.TestCase):
    """Ingest-level: pass trusted_servers through to classify so stored
    access_class reflects the owner's trust posture."""

    def _catalog(self, td):
        """Caller MUST close via `with` or explicit close() so Windows releases
        the sqlite file handle before the tempdir tries to rmtree."""
        return mcp.McpCatalog(Path(td) / "mcp.db")

    def _spec(self, name="mystery-server"):
        return {"name": name, "source": "test", "transport": "stdio",
                "command": "x", "args": [], "url": None, "_env": {}, "env_keys": [],
                "inherit_env": []}

    def test_ingest_demotes_untrusted_readonly_hints_to_unknown(self):
        with tempfile.TemporaryDirectory() as td:
            with self._catalog(td) as cat:
                tools = [{"name": "lookup", "annotations": {"readOnlyHint": True},
                          "inputSchema": {"type": "object"}, "description": "x"}]
                cat.ingest(self._spec(), tools, trusted_servers=set())
                access, basis = cat.access("mystery-server", "lookup")
            self.assertEqual(access, "unknown")
            self.assertIn("untrusted", basis)

    def test_ingest_keeps_trust_posture_when_server_is_trusted(self):
        with tempfile.TemporaryDirectory() as td:
            with self._catalog(td) as cat:
                tools = [{"name": "lookup", "annotations": {"readOnlyHint": True},
                          "inputSchema": {"type": "object"}, "description": "x"}]
                cat.ingest(self._spec(), tools, trusted_servers={"mystery-server"})
                access, _ = cat.access("mystery-server", "lookup")
            self.assertEqual(access, "read")

    def test_owner_override_wins_over_untrusted_demotion(self):
        with tempfile.TemporaryDirectory() as td:
            with self._catalog(td) as cat:
                tools = [{"name": "lookup", "annotations": {"readOnlyHint": True},
                          "inputSchema": {"type": "object"}, "description": "x"}]
                cat.ingest(self._spec(), tools, trusted_servers=set())
                cat.set_access("mystery-server", "lookup", "read", set_by="ken@local")
                access, basis = cat.access("mystery-server", "lookup")
            self.assertEqual(access, "read")
            self.assertIn("owner_override", basis)

    def test_ingest_backward_compat_when_trusted_servers_omitted(self):
        with tempfile.TemporaryDirectory() as td:
            with self._catalog(td) as cat:
                tools = [{"name": "lookup", "annotations": {"readOnlyHint": True},
                          "inputSchema": {"type": "object"}, "description": "x"}]
                cat.ingest(self._spec(), tools)  # no trusted_servers kwarg
                access, _ = cat.access("mystery-server", "lookup")
            self.assertEqual(access, "read")  # legacy posture


if __name__ == "__main__":
    unittest.main()
