"""Cumulative spend-cap state on the permit ledger (P0-06 slice 2b).

`PermitAuthority` now:
- persists `cost_usd` on every receipt event,
- sums known costs into `cumulative_cost_usd` on replay, and
- refuses `issue()` with `cumulative_cap_exceeded` once that total reaches an
  optional `max_cumulative_usd`.

`_BoundedProvider.run()` extracts `api_equivalent_cost_usd` from the adapter
usage dict (when it is a non-negative finite number) and includes it on both
success and failure outcomes, so cost reaches the ledger via `authority.receipt`.

`RunConfig.max_cumulative_usd` carries the cap through `broker --config`.
"""

import copy
import importlib.util
import json
import sys
import tempfile
import unittest
import unittest.mock as mock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


def _reload(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / (name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


class ReceiptPersistsCostTests(unittest.TestCase):
    def _authority(self, tmp):
        from capability_permits import PermitAuthority  # type: ignore
        return PermitAuthority(tmp / "permits.jsonl")

    def _basis(self):
        return {"kind": "jev_decision", "decision_id": "d1", "choice": "frontier.run",
                "state_hash": "s1", "live": True}

    def test_receipt_event_persists_cost_when_present(self):
        with tempfile.TemporaryDirectory() as tds:
            td = Path(tds)
            auth = self._authority(td)
            scope = {"workspace": str(td), "model": "m", "effort": "low"}
            pid = auth.issue("frontier.run", scope, self._basis())
            auth.consume(pid, "frontier.run", scope)
            auth.receipt(pid, {"status": "ok", "cost_usd": 0.42})
            receipt = [e for e in auth.events() if e.get("kind") == "permit_receipt"][-1]
            self.assertEqual(receipt["cost_usd"], 0.42)

    def test_receipt_event_persists_none_when_cost_missing(self):
        with tempfile.TemporaryDirectory() as tds:
            td = Path(tds)
            auth = self._authority(td)
            scope = {"workspace": str(td), "model": "m", "effort": "low"}
            pid = auth.issue("frontier.run", scope, self._basis())
            auth.consume(pid, "frontier.run", scope)
            auth.receipt(pid, {"status": "ok"})
            receipt = [e for e in auth.events() if e.get("kind") == "permit_receipt"][-1]
            self.assertIsNone(receipt["cost_usd"])

    def test_receipt_rejects_negative_cost(self):
        from capability_permits import PermitError  # type: ignore
        with tempfile.TemporaryDirectory() as tds:
            td = Path(tds)
            auth = self._authority(td)
            scope = {"workspace": str(td), "model": "m", "effort": "low"}
            pid = auth.issue("frontier.run", scope, self._basis())
            auth.consume(pid, "frontier.run", scope)
            with self.assertRaises(PermitError):
                auth.receipt(pid, {"status": "ok", "cost_usd": -0.01})

    def test_receipt_rejects_non_number_cost(self):
        from capability_permits import PermitError  # type: ignore
        with tempfile.TemporaryDirectory() as tds:
            td = Path(tds)
            auth = self._authority(td)
            scope = {"workspace": str(td), "model": "m", "effort": "low"}
            pid = auth.issue("frontier.run", scope, self._basis())
            auth.consume(pid, "frontier.run", scope)
            with self.assertRaises(PermitError):
                auth.receipt(pid, {"status": "ok", "cost_usd": "lots"})

    def test_cost_zero_is_accepted(self):
        with tempfile.TemporaryDirectory() as tds:
            td = Path(tds)
            auth = self._authority(td)
            scope = {"workspace": str(td), "model": "m", "effort": "low"}
            pid = auth.issue("frontier.run", scope, self._basis())
            auth.consume(pid, "frontier.run", scope)
            auth.receipt(pid, {"status": "ok", "cost_usd": 0.0})
            self.assertEqual(auth.cumulative_cost_usd, 0.0)


class CumulativeStateTests(unittest.TestCase):
    def _authority(self, tmp, **kw):
        from capability_permits import PermitAuthority  # type: ignore
        return PermitAuthority(tmp / "permits.jsonl", **kw)

    def _basis(self):
        return {"kind": "jev_decision", "decision_id": "d1", "choice": "frontier.run",
                "state_hash": "s1", "live": True}

    def _consume_with_cost(self, auth, workspace, cost):
        scope = {"workspace": str(workspace), "model": "m", "effort": "low"}
        pid = auth.issue("frontier.run", scope, self._basis())
        auth.consume(pid, "frontier.run", scope)
        outcome = {"status": "ok"}
        if cost is not None:
            outcome["cost_usd"] = cost
        auth.receipt(pid, outcome)

    def test_fresh_authority_has_zero_cumulative(self):
        with tempfile.TemporaryDirectory() as tds:
            td = Path(tds)
            auth = self._authority(td)
            self.assertEqual(auth.cumulative_cost_usd, 0.0)

    def test_single_receipt_adds_to_cumulative(self):
        with tempfile.TemporaryDirectory() as tds:
            td = Path(tds)
            auth = self._authority(td)
            self._consume_with_cost(auth, td, 0.5)
            self.assertAlmostEqual(auth.cumulative_cost_usd, 0.5, places=9)

    def test_multiple_receipts_accumulate(self):
        with tempfile.TemporaryDirectory() as tds:
            td = Path(tds)
            auth = self._authority(td)
            self._consume_with_cost(auth, td, 0.5)
            self._consume_with_cost(auth, td, 0.3)
            self._consume_with_cost(auth, td, 0.2)
            self.assertAlmostEqual(auth.cumulative_cost_usd, 1.0, places=9)

    def test_unknown_cost_does_not_change_cumulative(self):
        with tempfile.TemporaryDirectory() as tds:
            td = Path(tds)
            auth = self._authority(td)
            self._consume_with_cost(auth, td, 0.4)
            self._consume_with_cost(auth, td, None)
            self._consume_with_cost(auth, td, 0.1)
            self.assertAlmostEqual(auth.cumulative_cost_usd, 0.5, places=9)


class ReplaySumsCostTests(unittest.TestCase):
    def _basis(self):
        return {"kind": "jev_decision", "decision_id": "d1", "choice": "frontier.run",
                "state_hash": "s1", "live": True}

    def _consume_with_cost(self, auth, workspace, cost):
        scope = {"workspace": str(workspace), "model": "m", "effort": "low"}
        pid = auth.issue("frontier.run", scope, self._basis())
        auth.consume(pid, "frontier.run", scope)
        outcome = {"status": "ok"}
        if cost is not None:
            outcome["cost_usd"] = cost
        auth.receipt(pid, outcome)

    def test_replay_sums_known_costs(self):
        from capability_permits import PermitAuthority  # type: ignore
        with tempfile.TemporaryDirectory() as tds:
            td = Path(tds)
            ledger = td / "permits.jsonl"
            first = PermitAuthority(ledger)
            self._consume_with_cost(first, td, 0.4)
            self._consume_with_cost(first, td, 0.6)
            self._consume_with_cost(first, td, None)
            second = PermitAuthority(ledger)
            self.assertAlmostEqual(second.cumulative_cost_usd, 1.0, places=9)

    def test_replay_backward_compat_receipt_without_cost_field(self):
        """A legacy receipt line without `cost_usd` must replay as unknown (0 contribution)."""
        from capability_permits import PermitAuthority, canonical, digest  # type: ignore
        with tempfile.TemporaryDirectory() as tds:
            td = Path(tds)
            ledger = td / "permits.jsonl"
            auth = PermitAuthority(ledger)
            scope = {"workspace": str(td), "model": "m", "effort": "low"}
            pid = auth.issue("frontier.run", scope, self._basis())
            auth.consume(pid, "frontier.run", scope)
            events = json.loads(canonical(auth.events()))
            events  # just a reality check that we can read it
            prev = auth.ledger._last
            legacy = {"kind": "permit_receipt", "permit_id": pid,
                      "outcome_hash": digest({"status": "ok"}), "status": "ok",
                      "recorded_at": 0.0, "previous_event_hash": prev}
            legacy["event_hash"] = digest(legacy)
            with ledger.open("a", encoding="utf-8") as stream:
                stream.write(canonical(legacy) + "\n")
            fresh = PermitAuthority(ledger)
            self.assertEqual(fresh.cumulative_cost_usd, 0.0)


class CapEnforcementTests(unittest.TestCase):
    def _basis(self):
        return {"kind": "jev_decision", "decision_id": "d1", "choice": "frontier.run",
                "state_hash": "s1", "live": True}

    def _consume_with_cost(self, auth, workspace, cost):
        scope = {"workspace": str(workspace), "model": "m", "effort": "low"}
        pid = auth.issue("frontier.run", scope, self._basis())
        auth.consume(pid, "frontier.run", scope)
        outcome = {"status": "ok", "cost_usd": cost}
        auth.receipt(pid, outcome)

    def test_cap_none_means_no_check(self):
        from capability_permits import PermitAuthority  # type: ignore
        with tempfile.TemporaryDirectory() as tds:
            td = Path(tds)
            auth = PermitAuthority(td / "permits.jsonl", max_cumulative_usd=None)
            # Push cumulative very high; new permits still issue.
            for _ in range(5):
                self._consume_with_cost(auth, td, 100.0)
            scope = {"workspace": str(td), "model": "m", "effort": "low"}
            auth.issue("frontier.run", scope, self._basis())

    def test_cap_refuses_once_cumulative_meets_cap(self):
        from capability_permits import PermitAuthority, PermitError  # type: ignore
        with tempfile.TemporaryDirectory() as tds:
            td = Path(tds)
            auth = PermitAuthority(td / "permits.jsonl", max_cumulative_usd=1.0)
            self._consume_with_cost(auth, td, 0.6)
            scope = {"workspace": str(td), "model": "m", "effort": "low"}
            auth.issue("frontier.run", scope, self._basis())  # cumulative=0.6, still ok
            self._consume_with_cost(auth, td, 0.5)  # cumulative=1.1
            with self.assertRaises(PermitError) as caught:
                auth.issue("frontier.run", scope, self._basis())
            self.assertEqual(str(caught.exception), "cumulative_cap_exceeded")

    def test_cap_refuses_exactly_at_cap(self):
        from capability_permits import PermitAuthority, PermitError  # type: ignore
        with tempfile.TemporaryDirectory() as tds:
            td = Path(tds)
            auth = PermitAuthority(td / "permits.jsonl", max_cumulative_usd=1.0)
            self._consume_with_cost(auth, td, 1.0)
            with self.assertRaises(PermitError):
                scope = {"workspace": str(td), "model": "m", "effort": "low"}
                auth.issue("frontier.run", scope, self._basis())

    def test_cap_persists_across_restart(self):
        from capability_permits import PermitAuthority, PermitError  # type: ignore
        with tempfile.TemporaryDirectory() as tds:
            td = Path(tds)
            ledger = td / "permits.jsonl"
            first = PermitAuthority(ledger, max_cumulative_usd=1.0)
            self._consume_with_cost(first, td, 1.2)
            second = PermitAuthority(ledger, max_cumulative_usd=1.0)
            scope = {"workspace": str(td), "model": "m", "effort": "low"}
            with self.assertRaises(PermitError):
                second.issue("frontier.run", scope, self._basis())

    def test_cap_rejects_bad_values(self):
        from capability_permits import PermitAuthority, PermitError  # type: ignore
        with tempfile.TemporaryDirectory() as tds:
            td = Path(tds)
            for bad in (0, -1.0, "x", float("inf"), float("nan")):
                with self.assertRaises(PermitError):
                    PermitAuthority(td / "p.jsonl", max_cumulative_usd=bad)


class BoundedProviderThreadsCostTests(unittest.TestCase):
    """`_BoundedProvider.run()` surfaces `api_equivalent_cost_usd` into the receipt."""

    def _authority_and_adapter(self, td, *, usage=None, raise_error=False):
        from capability_permits import PermitAuthority  # type: ignore
        from frontier_providers import _BoundedProvider  # type: ignore
        auth = PermitAuthority(td / "permits.jsonl")

        class FakeAdapter:
            cancel_event = None

            def run(self, model, effort, prompt, schema, workspace):
                if raise_error:
                    raise RuntimeError("adapter_failed")
                return {"artifact": {"ok": True}, "usage": usage}

        provider = _BoundedProvider(FakeAdapter(), auth, executable="x")
        provider.provider_id = "claude"
        return auth, provider

    def _run(self, auth, provider, td):
        from capability_permits import PermitAuthority  # type: ignore
        scope = {"provider": provider.provider_id, "model": "claude-sonnet-5", "effort": "low",
                 "workspace": str(td.resolve()), "prompt_hash": "ignored", "schema_hash": "ignored"}
        # Easier path: use the real _request_scope by calling through PermittedAdapter would
        # pull in build_provider; instead we exercise _BoundedProvider.run directly.
        request = {"model": "claude-sonnet-5", "effort": "low", "prompt": "hi",
                   "schema": {"type": "object"}, "workspace": str(td.resolve())}
        from frontier_providers import _request_scope  # type: ignore
        real_scope = _request_scope(provider.provider_id, request)
        pid = auth.issue("frontier.run", real_scope,
                         {"kind": "jev_decision", "decision_id": "d", "choice": "frontier.run",
                          "state_hash": "s", "live": True})
        return provider.run(request, pid), pid

    def test_cost_from_api_equivalent_usd_reaches_receipt(self):
        with tempfile.TemporaryDirectory() as tds:
            td = Path(tds)
            auth, prov = self._authority_and_adapter(
                td, usage={"api_equivalent_cost_usd": 0.08, "input_tokens": 10, "output_tokens": 5})
            self._run(auth, prov, td)
            receipt = [e for e in auth.events() if e.get("kind") == "permit_receipt"][-1]
            self.assertAlmostEqual(receipt["cost_usd"], 0.08, places=9)
            self.assertAlmostEqual(auth.cumulative_cost_usd, 0.08, places=9)

    def test_missing_cost_leaves_receipt_none(self):
        with tempfile.TemporaryDirectory() as tds:
            td = Path(tds)
            auth, prov = self._authority_and_adapter(td, usage={"input_tokens": 10})
            self._run(auth, prov, td)
            receipt = [e for e in auth.events() if e.get("kind") == "permit_receipt"][-1]
            self.assertIsNone(receipt["cost_usd"])
            self.assertEqual(auth.cumulative_cost_usd, 0.0)

    def test_failed_run_still_receipts_with_cost_none(self):
        with tempfile.TemporaryDirectory() as tds:
            td = Path(tds)
            auth, prov = self._authority_and_adapter(td, raise_error=True)
            with self.assertRaises(RuntimeError):
                self._run(auth, prov, td)
            receipt = [e for e in auth.events() if e.get("kind") == "permit_receipt"][-1]
            self.assertIsNone(receipt["cost_usd"])
            self.assertEqual(receipt["status"], "failed")

    def test_rejects_negative_cost_from_adapter(self):
        with tempfile.TemporaryDirectory() as tds:
            td = Path(tds)
            auth, prov = self._authority_and_adapter(td, usage={"api_equivalent_cost_usd": -1.0})
            self._run(auth, prov, td)
            receipt = [e for e in auth.events() if e.get("kind") == "permit_receipt"][-1]
            self.assertIsNone(receipt["cost_usd"])


class RunConfigCumulativeFieldTests(unittest.TestCase):
    def test_default_is_none(self):
        from config import RunConfig  # type: ignore
        self.assertIsNone(RunConfig().max_cumulative_usd)

    def test_accepts_positive_float(self):
        from config import RunConfig  # type: ignore
        cfg = RunConfig.from_dict({"max_cumulative_usd": 10.0})
        self.assertEqual(cfg.max_cumulative_usd, 10.0)

    def test_rejects_zero(self):
        from config import RunConfig  # type: ignore
        with self.assertRaises(ValueError):
            RunConfig.from_dict({"max_cumulative_usd": 0})

    def test_rejects_negative(self):
        from config import RunConfig  # type: ignore
        with self.assertRaises(ValueError):
            RunConfig.from_dict({"max_cumulative_usd": -1.0})

    def test_rejects_string(self):
        from config import RunConfig  # type: ignore
        with self.assertRaises(ValueError):
            RunConfig.from_dict({"max_cumulative_usd": "lots"})


class AuditLedgerBackwardCompatTests(unittest.TestCase):
    """`audit_permit_ledger` must stay happy with both old (no cost_usd) and new (cost_usd) receipts."""

    def test_audit_passes_with_cost_fields(self):
        from capability_permits import PermitAuthority, audit_permit_ledger  # type: ignore
        with tempfile.TemporaryDirectory() as tds:
            td = Path(tds)
            auth = PermitAuthority(td / "p.jsonl")
            scope = {"workspace": str(td), "model": "m", "effort": "low"}
            basis = {"kind": "jev_decision", "decision_id": "d", "choice": "frontier.run",
                     "state_hash": "s", "live": True}
            pid = auth.issue("frontier.run", scope, basis)
            auth.consume(pid, "frontier.run", scope)
            auth.receipt(pid, {"status": "ok", "cost_usd": 0.11})
            result = audit_permit_ledger(auth.events())
            self.assertTrue(result["valid"])
            self.assertEqual(result["issues"], [])


if __name__ == "__main__":
    unittest.main()
