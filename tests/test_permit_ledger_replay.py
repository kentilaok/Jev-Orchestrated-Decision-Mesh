"""P0-06 slice 1: a crashed-and-resumed broker must not re-issue or reuse
old permits. The current `PermitAuthority.__init__` starts with empty
in-memory `_permits` / `_used`, so after a crash a surviving ledger file
is ignored and already-consumed permit IDs become `unknown_permit` on
retry instead of the stricter `permit_already_used`.

This slice adds ledger replay: on construction, if the ledger file
exists, replay issued/consumed events to rebuild authority state. The
hash chain integrity check is reused; a tampered or truncated ledger
raises on construction rather than silently dropping records.
"""

import importlib.util
import json
import sys
import tempfile
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

spec = importlib.util.spec_from_file_location(
    "capability_permits", ROOT / "scripts" / "capability_permits.py")
cp = importlib.util.module_from_spec(spec)
sys.modules["capability_permits"] = cp
spec.loader.exec_module(cp)


JEV_BASIS = {"kind": "jev_decision", "decision_id": "e1", "choice": "x",
             "state_hash": "a" * 64, "live": True}


class LedgerReplayRehydratesPermitsTests(unittest.TestCase):
    def test_fresh_authority_on_empty_ledger_path_is_empty(self):
        with tempfile.TemporaryDirectory() as tds:
            td = Path(tds)
            auth = cp.PermitAuthority(td / "permits.jsonl")
            self.assertEqual(len(auth._permits), 0)
            self.assertEqual(len(auth._used), 0)

    def test_authority_rebuilds_issued_permits_from_ledger(self):
        with tempfile.TemporaryDirectory() as tds:
            td = Path(tds)
            path = td / "permits.jsonl"
            auth1 = cp.PermitAuthority(path)
            scope = {"server": "s", "tool": "t", "arguments_hash": "a" * 64,
                     "access_class": "mutate", "schema_hash": "b" * 64}
            permit_id = auth1.issue("mcp.mutate", scope, JEV_BASIS)

            auth2 = cp.PermitAuthority(path)
            self.assertIn(permit_id, auth2._permits)
            self.assertEqual(auth2._permits[permit_id]["capability"], "mcp.mutate")

    def test_consumed_permit_cannot_be_consumed_after_restart(self):
        """Core P0-06 behaviour: a permit consumed before the crash must
        be refused with permit_already_used, not forgotten."""
        with tempfile.TemporaryDirectory() as tds:
            td = Path(tds)
            path = td / "permits.jsonl"
            auth1 = cp.PermitAuthority(path)
            scope = {"server": "s", "tool": "t", "arguments_hash": "a" * 64,
                     "access_class": "read", "schema_hash": "b" * 64}
            permit_id = auth1.issue("mcp.read", scope,
                                    {"kind": "operator", "operator": "ken", "reason": "test"})
            auth1.consume(permit_id, "mcp.read", scope)
            del auth1

            auth2 = cp.PermitAuthority(path)
            with self.assertRaises(cp.PermitError) as ctx:
                auth2.consume(permit_id, "mcp.read", scope)
            self.assertEqual(str(ctx.exception), "permit_already_used")

    def test_receipted_permit_stays_marked_used(self):
        with tempfile.TemporaryDirectory() as tds:
            td = Path(tds)
            path = td / "permits.jsonl"
            auth1 = cp.PermitAuthority(path)
            scope = {"server": "s", "tool": "t", "arguments_hash": "a" * 64,
                     "access_class": "read", "schema_hash": "b" * 64}
            permit_id = auth1.issue("mcp.read", scope,
                                    {"kind": "operator", "operator": "ken", "reason": "test"})
            auth1.consume(permit_id, "mcp.read", scope)
            auth1.receipt(permit_id, {"status": "ok"})

            auth2 = cp.PermitAuthority(path)
            self.assertIn(permit_id, auth2._used)

    def test_expired_permit_from_ledger_is_still_refused(self):
        """Even if the ledger says a permit was issued, its original TTL
        still binds — expired permits do not come back to life on replay."""
        with tempfile.TemporaryDirectory() as tds:
            td = Path(tds)
            path = td / "permits.jsonl"
            now = {"t": 1000.0}

            def clock():
                return now["t"]
            auth1 = cp.PermitAuthority(path, default_ttl_seconds=600, clock=clock)
            scope = {"server": "s", "tool": "t", "arguments_hash": "a" * 64,
                     "access_class": "read", "schema_hash": "b" * 64}
            permit_id = auth1.issue("mcp.read", scope,
                                    {"kind": "operator", "operator": "ken", "reason": "test"})
            del auth1

            now["t"] = 3500.0  # 2500s later → well past 600s TTL
            auth2 = cp.PermitAuthority(path, default_ttl_seconds=600, clock=clock)
            with self.assertRaises(cp.PermitError) as ctx:
                auth2.consume(permit_id, "mcp.read", scope)
            self.assertEqual(str(ctx.exception), "permit_expired")

    def test_tampered_ledger_rejected_at_construction(self):
        with tempfile.TemporaryDirectory() as tds:
            td = Path(tds)
            path = td / "permits.jsonl"
            auth1 = cp.PermitAuthority(path)
            scope = {"server": "s", "tool": "t", "arguments_hash": "a" * 64,
                     "access_class": "read", "schema_hash": "b" * 64}
            auth1.issue("mcp.read", scope,
                        {"kind": "operator", "operator": "ken", "reason": "test"})
            # Mangle the first line's event body (keep the chain-hash intact
            # at the same offset so JSON parses).
            text = path.read_text(encoding="utf-8")
            # Canonical ledger has no spaces after colons.
            path.write_text(text.replace('"operator":"ken"', '"operator":"mall"'),
                            encoding="utf-8")
            with self.assertRaises(cp.PermitError):
                cp.PermitAuthority(path)

    def test_truncated_ledger_rejected_at_construction(self):
        with tempfile.TemporaryDirectory() as tds:
            td = Path(tds)
            path = td / "permits.jsonl"
            auth1 = cp.PermitAuthority(path)
            scope = {"server": "s", "tool": "t", "arguments_hash": "a" * 64,
                     "access_class": "read", "schema_hash": "b" * 64}
            auth1.issue("mcp.read", scope,
                        {"kind": "operator", "operator": "ken", "reason": "test"})
            # Drop the last byte to corrupt the final JSON record.
            raw = path.read_bytes()
            path.write_bytes(raw[:-5])
            with self.assertRaises(cp.PermitError):
                cp.PermitAuthority(path)


if __name__ == "__main__":
    unittest.main()
