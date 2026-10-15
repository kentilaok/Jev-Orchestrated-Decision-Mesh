"""Every OTLP span must carry the ordinal-timing caveat (P0-06 slice 5).

Journal events carry no wall-clock timestamps (audit defect D-05); span
times are ordinal (1ms per event from the run start). If any span is
emitted without `cidm.timing="ordinal_not_wallclock"`, a Phoenix consumer
could misread it as a measured p95 — exactly the mistake the P0-06
production handoff warns against.

`telemetry.to_otlp` now (a) centralises the key/value as module-level
constants and (b) runs `_assert_ordinal_caveat` across every emitted
span just before return, raising a `RuntimeError` if any span lacks the
caveat. The programmatic guard means a future dev cannot silently add a
new span type without the caveat.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))


def _attr_dict(span):
    """Flatten a span's OTLP attribute list into a dict for easy lookup."""
    out = {}
    for item in span["attributes"]:
        value = item["value"]
        out[item["key"]] = next(iter(value.values()))
    return out


class OrdinalCaveatModuleTests(unittest.TestCase):
    def test_module_exposes_ordinal_constants(self):
        import telemetry  # type: ignore
        self.assertEqual(telemetry.ORDINAL_TIMING_KEY, "cidm.timing")
        self.assertEqual(telemetry.ORDINAL_TIMING_VALUE, "ordinal_not_wallclock")

    def test_assert_guard_rejects_span_missing_the_caveat(self):
        import telemetry  # type: ignore
        bad_span = {"name": "surprise", "attributes": []}
        with self.assertRaises(RuntimeError) as caught:
            telemetry._assert_ordinal_caveat([bad_span])
        self.assertIn("ordinal_caveat_missing", str(caught.exception))
        self.assertIn("surprise", str(caught.exception))

    def test_assert_guard_rejects_span_with_wrong_value(self):
        import telemetry  # type: ignore
        wrong = {"name": "wrong", "attributes": [
            {"key": "cidm.timing", "value": {"stringValue": "measured_wallclock"}}]}
        with self.assertRaises(RuntimeError):
            telemetry._assert_ordinal_caveat([wrong])

    def test_assert_guard_accepts_correctly_tagged_span(self):
        import telemetry  # type: ignore
        good = {"name": "ok", "attributes": [
            {"key": telemetry.ORDINAL_TIMING_KEY,
             "value": {"stringValue": telemetry.ORDINAL_TIMING_VALUE}}]}
        telemetry._assert_ordinal_caveat([good])  # no raise


class EveryEmittedSpanCarriesCaveatTests(unittest.TestCase):
    """Run a real broker and verify every single span in `to_otlp` output
    carries `cidm.timing=ordinal_not_wallclock` — covers root, jev entry,
    jev decisions, unit chains, and worker/checker calls."""

    @classmethod
    def setUpClass(cls):
        from config import RunConfig  # type: ignore
        from native_transition_broker import NativeTransitionBroker  # type: ignore
        from test_native_transition_broker import SPEC, FakeCodex, FakeJev  # type: ignore
        with tempfile.TemporaryDirectory() as temp:
            cls.result = NativeTransitionBroker(
                FakeCodex(), FakeJev(check_unit="hidden2"), RunConfig(),
                Path(temp) / "run").run(SPEC)

    def test_every_span_carries_the_caveat(self):
        from telemetry import to_otlp  # type: ignore
        payload = to_otlp(self.result, start_ns=10**18)
        spans = payload["resourceSpans"][0]["scopeSpans"][0]["spans"]
        self.assertGreater(len(spans), 1, "need multiple spans to make this test meaningful")
        offenders = []
        for span in spans:
            a = _attr_dict(span)
            if a.get("cidm.timing") != "ordinal_not_wallclock":
                offenders.append(span["name"])
        self.assertEqual(offenders, [],
                         "spans missing the ordinal caveat: " + ", ".join(offenders))

    def test_caveat_value_is_the_exact_sentinel_string(self):
        """A near-miss like 'ordinal' or 'not_wallclock' must not satisfy the guard."""
        from telemetry import to_otlp  # type: ignore
        payload = to_otlp(self.result, start_ns=10**18)
        spans = payload["resourceSpans"][0]["scopeSpans"][0]["spans"]
        for span in spans:
            a = _attr_dict(span)
            # Not merely truthy or contains "ordinal" — exact sentinel.
            self.assertEqual(a["cidm.timing"], "ordinal_not_wallclock",
                             span["name"] + " has wrong caveat value: " + repr(a["cidm.timing"]))

    def test_to_otlp_itself_raises_if_a_span_lacks_the_caveat(self):
        """Monkeypatch `_attrs` so the first emitted span's attributes drop
        the caveat key, then confirm `to_otlp` raises before returning.
        This mutates only the producer side, so the guard (which still
        reads the real constants) actually fires."""
        import unittest.mock as mock
        import telemetry  # type: ignore
        original_attrs = telemetry._attrs
        seen = {"calls": 0}

        def stripped(values):
            seen["calls"] += 1
            if seen["calls"] == 1:  # strip from the first span only
                values = {k: v for k, v in values.items() if k != "cidm.timing"}
            return original_attrs(values)

        with mock.patch.object(telemetry, "_attrs", side_effect=stripped):
            with self.assertRaises(RuntimeError) as caught:
                telemetry.to_otlp(self.result, start_ns=1)
        self.assertIn("ordinal_caveat_missing", str(caught.exception))


class PreExistingAssertionStaysGreenTests(unittest.TestCase):
    """Guardrail: the single root-span assertion that lived in test_telemetry
    before this slice must still hold. If this test fails, the slice has
    unintentionally changed emitted output."""

    def test_root_span_still_carries_caveat(self):
        from config import RunConfig  # type: ignore
        from native_transition_broker import NativeTransitionBroker  # type: ignore
        from telemetry import to_otlp  # type: ignore
        from test_native_transition_broker import SPEC, FakeCodex, FakeJev  # type: ignore
        with tempfile.TemporaryDirectory() as temp:
            result = NativeTransitionBroker(
                FakeCodex(), FakeJev(check_unit="hidden2"), RunConfig(),
                Path(temp) / "run").run(SPEC)
        payload = to_otlp(result, start_ns=10**18)
        root = payload["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
        self.assertEqual(_attr_dict(root)["cidm.timing"], "ordinal_not_wallclock")


if __name__ == "__main__":
    unittest.main()
