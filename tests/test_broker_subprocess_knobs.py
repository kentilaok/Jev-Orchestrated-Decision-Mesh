"""Thread content_policy and require_action_approval from the Console
through broker_argv -> native_transition_broker.py CLI -> McpEvidenceRetriever
-> call_tool, so a Console-side operator setting actually enforces inside
the broker subprocess spawned by `start_broker_job`.
"""

import importlib.util
import json
import sys
import tempfile
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

for name in ("mcp_registry", "operator_console"):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / (name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)

mcp = sys.modules["mcp_registry"]
console = sys.modules["operator_console"]


class BrokerArgvForwardsKnobsTests(unittest.TestCase):
    def _argv(self, config_overrides=None):
        cfg = console._merge_config(config_overrides or {})
        return console.broker_argv(Path("/tmp/t.json"), Path("/tmp/out"),
                                   cfg["frontier_provider"], cfg["gate_policy"],
                                   live=False, config=cfg)

    def test_default_config_omits_content_policy_and_approval_flags(self):
        argv = self._argv()
        self.assertNotIn("--content-policy", argv)
        self.assertNotIn("--require-action-approval", argv)

    def test_content_policy_wrap_adds_flag(self):
        argv = self._argv({"content_policy": "wrap"})
        self.assertIn("--content-policy", argv)
        idx = argv.index("--content-policy")
        self.assertEqual(argv[idx + 1], "wrap")

    def test_require_action_approval_adds_boolean_flag(self):
        argv = self._argv({"require_action_approval": True})
        self.assertIn("--require-action-approval", argv)


class BrokerCliParsesKnobsTests(unittest.TestCase):
    """native_transition_broker.py main() must accept the new flags."""

    def test_parser_accepts_both_flags(self):
        from native_transition_broker import _build_cli_parser  # type: ignore
        parser = _build_cli_parser()
        args = parser.parse_args([
            "--validate-only", "--host", "claude", "--gate-policy", "recovery",
            "--task", "t.json", "--content-policy", "audit",
            "--require-action-approval",
        ])
        self.assertEqual(args.content_policy, "audit")
        self.assertTrue(args.require_action_approval)

    def test_defaults_match_backward_compat(self):
        from native_transition_broker import _build_cli_parser  # type: ignore
        parser = _build_cli_parser()
        args = parser.parse_args([
            "--validate-only", "--host", "claude", "--gate-policy", "recovery",
            "--task", "t.json",
        ])
        self.assertEqual(args.content_policy, "off")
        self.assertFalse(args.require_action_approval)


class McpEvidenceRetrieverThreadsKnobsTests(unittest.TestCase):
    """`McpEvidenceRetriever` must forward `content_policy` and
    `require_action_approval` into each `call_tool` invocation."""

    def _setup(self, td: Path):
        from capability_permits import PermitAuthority  # type: ignore
        catalog = mcp.McpCatalog(td / "mcp.db")
        spec = {"name": "test-server", "source": "test", "transport": "stdio",
                "command": "x", "args": [], "url": None, "_env": {}, "env_keys": [],
                "inherit_env": []}
        tools = [{"name": "read_doc", "annotations": {"readOnlyHint": True},
                  "inputSchema": {"type": "object"}, "description": "x"}]
        catalog.ingest(spec, tools, trusted_servers={"test-server"})
        auth = PermitAuthority(td / "permits.jsonl")
        return catalog, auth, spec

    def test_retriever_stores_knobs(self):
        with tempfile.TemporaryDirectory() as tds:
            td = Path(tds)
            catalog, auth, spec = self._setup(td)
            try:
                retriever = mcp.McpEvidenceRetriever(
                    catalog, {"test-server": spec}, auth,
                    plan=[{"server": "test-server", "tool": "read_doc", "arguments": {}}],
                    content_policy="wrap", require_action_approval=True)
                self.assertEqual(retriever.content_policy, "wrap")
                self.assertTrue(retriever.require_action_approval)
            finally:
                catalog.db.close()

    def test_retriever_default_is_backward_compat(self):
        with tempfile.TemporaryDirectory() as tds:
            td = Path(tds)
            catalog, auth, spec = self._setup(td)
            try:
                retriever = mcp.McpEvidenceRetriever(
                    catalog, {"test-server": spec}, auth,
                    plan=[{"server": "test-server", "tool": "read_doc", "arguments": {}}])
                self.assertEqual(retriever.content_policy, "off")
                self.assertFalse(retriever.require_action_approval)
            finally:
                catalog.db.close()

    def test_retriever_rejects_invalid_policy_at_construction(self):
        with tempfile.TemporaryDirectory() as tds:
            td = Path(tds)
            catalog, auth, spec = self._setup(td)
            try:
                with self.assertRaises(ValueError):
                    mcp.McpEvidenceRetriever(
                        catalog, {"test-server": spec}, auth,
                        plan=[{"server": "test-server", "tool": "read_doc", "arguments": {}}],
                        content_policy="nonsense")
            finally:
                catalog.db.close()


if __name__ == "__main__":
    unittest.main()
