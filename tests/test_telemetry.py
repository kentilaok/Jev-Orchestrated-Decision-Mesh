"""Arsenal Phase G: journal-to-OpenTelemetry export (offline)."""
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'tests'))

from config import RunConfig
from native_transition_broker import NativeTransitionBroker
from telemetry import post_otlp, run_summary, to_otlp
from test_native_transition_broker import SPEC, FakeCodex, FakeJev


def attrs(span):
    out = {}
    for item in span['attributes']:
        value = item['value']
        out[item['key']] = next(iter(value.values()))
    return out


class TelemetryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with tempfile.TemporaryDirectory() as temp:
            cls.result = NativeTransitionBroker(FakeCodex(), FakeJev(check_unit='hidden2'), RunConfig(),
                                                Path(temp) / 'run').run(SPEC)

    def test_spans_cover_every_decision_and_frontier_call(self):
        payload = to_otlp(self.result, start_ns=10**18)
        spans = payload['resourceSpans'][0]['scopeSpans'][0]['spans']
        names = [s['name'] for s in spans]
        decisions = sum(e['kind'] == 'jev_decision' for e in self.result['events'])
        self.assertEqual(sum(n.startswith('jev.decision.') for n in names), decisions + 1)
        frontier = [c for c in self.result['calls'] if c['role'] in ('worker', 'checker')]
        self.assertEqual(sum(n in ('worker.call', 'checker.call') for n in names), len(frontier))
        self.assertEqual(sum(n.startswith('cidm.unit.') for n in names), 5)
        trace_ids = {s['traceId'] for s in spans}
        self.assertEqual(len(trace_ids), 1)
        root = spans[0]
        self.assertTrue(all(s.get('parentSpanId') for s in spans[1:]))
        self.assertEqual(attrs(root)['cidm.timing'], 'ordinal_not_wallclock')

    def test_spans_link_to_journal_events_and_keep_unknown_usage_unknown(self):
        result = json.loads(json.dumps(self.result))
        result['calls'][1]['usage'] = None
        spans = to_otlp(result)['resourceSpans'][0]['scopeSpans'][0]['spans']
        event_ids = {e['id'] for e in result['events']}
        linked = [attrs(s).get('cidm.event_id') for s in spans if 'cidm.event_id' in attrs(s)]
        self.assertTrue(linked and set(linked) <= event_ids)
        unknown = [attrs(s) for s in spans if attrs(s).get('cidm.usage.status') == 'unknown']
        self.assertEqual(len(unknown), 1)
        self.assertNotIn('llm.token_count.total', unknown[0])

    def test_trace_is_deterministic_for_the_same_journal(self):
        first = to_otlp(self.result, start_ns=1)
        second = to_otlp(self.result, start_ns=1)
        self.assertEqual(first, second)

    def test_summary_reports_section_14_fields(self):
        summary = run_summary(self.result)
        self.assertEqual(summary['status'], 'complete')
        self.assertEqual(summary['committed_units'], ['input', 'hidden1', 'hidden2', 'hidden3', 'output'])
        self.assertEqual(summary['calls_by_role']['checker'], 1)
        self.assertIsNone(summary['primary_agent_tokens'])

    def test_post_targets_v1_traces(self):
        seen = {}

        class Response(io.BytesIO):
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

        def opener(req, timeout=None):
            seen['url'], seen['type'] = req.full_url, req.get_header('Content-type')
            return Response(b'')
        status = post_otlp('http://127.0.0.1:6006', to_otlp(self.result), opener=opener)
        self.assertEqual(status, 200)
        self.assertEqual(seen['url'], 'http://127.0.0.1:6006/v1/traces')
        self.assertEqual(seen['type'], 'application/json')


if __name__ == '__main__':
    unittest.main()
