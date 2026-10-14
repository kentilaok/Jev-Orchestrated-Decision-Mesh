"""Thread the Operator Console's security knobs into actual callers.

Specifically: `mcp_refresh(config, server)` must pass
`trusted_servers=set(config['trusted_mcp_servers'])` into `catalog.ingest`
so stored access-class classifications reflect the operator's trust posture.
Default empty list means strict (demote every unknown server's
`readOnlyHint=true` to `access_class='unknown'`), which matches P0-05's
untrusted-by-default stance.

`content_policy` and `require_action_approval` do not apply at the Console
layer directly: tool calls happen inside the broker subprocess spawned by
`start_broker_job`, and threading them there is a separate slice because
it changes the task-JSON contract.
"""

import importlib.util
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


class TrustedServersHelperTests(unittest.TestCase):
    def test_default_empty_list_yields_empty_set(self):
        cfg = console._merge_config({})
        self.assertEqual(console._trusted_mcp_servers(cfg), set())

    def test_list_entries_become_a_set(self):
        cfg = console._merge_config({"trusted_mcp_servers": ["github", "fs"]})
        self.assertEqual(console._trusted_mcp_servers(cfg), {"github", "fs"})

    def test_duplicates_collapse(self):
        cfg = console._merge_config({"trusted_mcp_servers": ["x", "x", "y"]})
        self.assertEqual(console._trusted_mcp_servers(cfg), {"x", "y"})


class McpRefreshThreadsTrustedServersTests(unittest.TestCase):
    """`mcp_refresh` must forward the operator's trust set into
    `McpCatalog.ingest`. We stub `client_for` and `McpCatalog` so this
    tests only the wiring, not real sqlite/network behaviour."""

    def _stubs(self, cfg_server_name="unknown-server"):
        captured = {}

        class _StubClient:
            def __enter__(self_inner):
                return self_inner

            def __exit__(self_inner, *_):
                return False

            def initialize(self_inner):
                return None

            def list_tools(self_inner):
                return [{"name": "lookup",
                         "annotations": {"readOnlyHint": True},
                         "inputSchema": {"type": "object"}, "description": "x"}]

        def _stub_client_for(spec):
            captured["spec"] = spec
            return _StubClient()

        class _StubCatalog:
            def __init__(self, path):
                self.path = path

            def __enter__(self_inner):
                return self_inner

            def __exit__(self_inner, *_):
                return False

            def ingest(self_inner, spec, tools, *, trusted_servers=None):
                captured["ingest_spec"] = spec
                captured["ingest_tools"] = tools
                captured["ingest_trusted"] = trusted_servers
                return {"server": spec["name"], "tools": len(tools), "by_access": {}}

        def _stub_discover(*, project_dir=None, home=None):
            return [{"name": cfg_server_name, "source": "stub", "transport": "stdio",
                     "command": "x", "args": [], "url": None, "_env": {},
                     "env_keys": [], "inherit_env": []}]

        return captured, _stub_client_for, _StubCatalog, _stub_discover

    def test_empty_trust_set_passes_through_as_strict(self):
        captured, cf, cat, dsc = self._stubs()
        with tempfile.TemporaryDirectory() as td:
            cfg = console._merge_config({"mcp_db": str(Path(td) / "mcp.db")})
            console.mcp_refresh(cfg, "unknown-server",
                                client_factory=cf, catalog_cls=cat, discover=dsc)
        self.assertEqual(captured["ingest_trusted"], set())

    def test_configured_trust_set_is_forwarded(self):
        captured, cf, cat, dsc = self._stubs()
        with tempfile.TemporaryDirectory() as td:
            cfg = console._merge_config({
                "mcp_db": str(Path(td) / "mcp.db"),
                "trusted_mcp_servers": ["unknown-server", "another"],
            })
            console.mcp_refresh(cfg, "unknown-server",
                                client_factory=cf, catalog_cls=cat, discover=dsc)
        self.assertEqual(captured["ingest_trusted"], {"unknown-server", "another"})


if __name__ == "__main__":
    unittest.main()
