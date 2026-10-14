"""Thread the trust gate through the `python scripts/mcp_registry.py refresh`
CLI subcommand so an operator who refreshes from the shell gets the same
P0-05 untrusted-by-default posture as the Operator Console path.

CLI resolution order:
  1. explicit `--trusted-servers a,b,c` on the command line
  2. operator-console.json's `trusted_mcp_servers` field (shared source of truth)
  3. empty set (strict)
"""

import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

spec = importlib.util.spec_from_file_location(
    "mcp_registry", ROOT / "scripts" / "mcp_registry.py")
mcp = importlib.util.module_from_spec(spec)
sys.modules["mcp_registry"] = mcp
spec.loader.exec_module(mcp)


class ResolveTrustedServersTests(unittest.TestCase):
    def test_cli_argument_takes_precedence(self):
        resolved = mcp._resolve_cli_trusted_servers(
            cli_value="x,y,z", state_path=None)
        self.assertEqual(resolved, {"x", "y", "z"})

    def test_cli_argument_strips_whitespace_and_drops_empty(self):
        resolved = mcp._resolve_cli_trusted_servers(
            cli_value="x,  ,  y  ,", state_path=None)
        self.assertEqual(resolved, {"x", "y"})

    def test_cli_empty_string_yields_empty_set(self):
        resolved = mcp._resolve_cli_trusted_servers(
            cli_value="", state_path=None)
        self.assertEqual(resolved, set())

    def test_falls_back_to_state_file_when_cli_absent(self):
        with tempfile.TemporaryDirectory() as tds:
            td = Path(tds)
            state = td / "operator-console.json"
            state.write_text(json.dumps(
                {"trusted_mcp_servers": ["github", "fs"]}), encoding="utf-8")
            resolved = mcp._resolve_cli_trusted_servers(
                cli_value=None, state_path=state)
            self.assertEqual(resolved, {"github", "fs"})

    def test_missing_state_file_yields_empty_strict(self):
        with tempfile.TemporaryDirectory() as tds:
            td = Path(tds)
            resolved = mcp._resolve_cli_trusted_servers(
                cli_value=None, state_path=td / "nope.json")
            self.assertEqual(resolved, set())

    def test_corrupt_state_file_yields_empty_strict(self):
        with tempfile.TemporaryDirectory() as tds:
            td = Path(tds)
            path = td / "state.json"
            path.write_text("{not json", encoding="utf-8")
            resolved = mcp._resolve_cli_trusted_servers(
                cli_value=None, state_path=path)
            self.assertEqual(resolved, set())

    def test_state_file_missing_field_yields_empty_strict(self):
        with tempfile.TemporaryDirectory() as tds:
            td = Path(tds)
            path = td / "state.json"
            path.write_text(json.dumps({"other": 1}), encoding="utf-8")
            resolved = mcp._resolve_cli_trusted_servers(
                cli_value=None, state_path=path)
            self.assertEqual(resolved, set())


class RefreshCliArgumentTests(unittest.TestCase):
    def test_parser_accepts_trusted_servers_flag(self):
        parser = mcp._build_cli_parser()
        args = parser.parse_args(
            ["refresh", "--server", "fake", "--trusted-servers", "a,b"])
        self.assertEqual(args.trusted_servers, "a,b")

    def test_trusted_servers_default_is_none(self):
        parser = mcp._build_cli_parser()
        args = parser.parse_args(["refresh", "--server", "fake"])
        self.assertIsNone(args.trusted_servers)


if __name__ == "__main__":
    unittest.main()
