"""Operator Console: request guards, bounded smoke test, runs and jobs (offline)."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'tests'))
spec = importlib.util.spec_from_file_location('operator_console_under_test', ROOT / 'scripts' / 'operator_console.py')
console = importlib.util.module_from_spec(spec)
spec.loader.exec_module(console)

from capability_permits import audit_permit_ledger
from frontier_providers import ClaudeCodeProvider


class GuardTests(unittest.TestCase):
    def test_host_header_must_be_loopback_on_our_port(self):
        self.assertTrue(console.host_allowed('127.0.0.1:8765', 8765))
        self.assertTrue(console.host_allowed('localhost', 8765))
        self.assertTrue(console.host_allowed('[::1]:8765', 8765))
        self.assertFalse(console.host_allowed('attacker.example:8765', 8765))
        self.assertFalse(console.host_allowed('127.0.0.1:9999', 8765))
        self.assertFalse(console.host_allowed(None, 8765))

    def test_origin_must_be_same_loopback_origin(self):
        self.assertTrue(console.origin_allowed(None, 8765))
        self.assertTrue(console.origin_allowed('http://127.0.0.1:8765', 8765))
        self.assertFalse(console.origin_allowed('https://evil.example', 8765))
        self.assertFalse(console.origin_allowed('http://127.0.0.1:1234', 8765))


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        root = Path(cls.temp.name)
        (root / 'runs').mkdir()
        state = console.StateStore(root / 'state.json')
        state.save({'runs_directory': str(root / 'runs'), 'arsenal_db': str(root / 'none.db'),
                    'calibration_ledger': str(root / 'none.jsonl'), 'mcp_db': str(root / 'mcp.db'),
                    'skills_source': str(root / 'skills'), 'project_directory': str(root),
                    'hermes_dashboard_url': 'http://127.0.0.1:9'})
        console.Handler.store = state
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), console.Handler)
        console.Handler.port = cls.server.server_address[1]
        cls.port = cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.root = root

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.temp.cleanup()

    def request(self, method, path, body=None, headers=None):
        connection = HTTPConnection('127.0.0.1', self.port, timeout=10)
        base = {'Host': '127.0.0.1:%d' % self.port}
        if body is not None:
            base['Content-Type'] = 'application/json'
        base.update(headers or {})
        connection.request(method, path, body=json.dumps(body) if body is not None else None, headers=base)
        response = connection.getresponse()
        data = response.read()
        connection.close()
        return response.status, json.loads(data) if data and data[:1] in b'{[' else data

    def test_post_without_console_header_is_refused(self):
        status, body = self.request('POST', '/api/config', {'frontier_provider': 'codex'})
        self.assertEqual(status, 403)
        status, _ = self.request('POST', '/api/config', {'frontier_provider': 'codex'},
                                 {'X-CIDM-Console': '1', 'Origin': 'https://evil.example'})
        self.assertEqual(status, 403)

    def test_rebound_host_header_is_refused_for_reads(self):
        status, _ = self.request('GET', '/api/state', headers={'Host': 'evil.example:%d' % self.port})
        self.assertEqual(status, 403)

    def test_live_broker_run_requires_spend_confirmation(self):
        status, body = self.request('POST', '/api/run', {'execution_mode': 'cidm-broker', 'task': 'x'},
                                    {'X-CIDM-Console': '1'})
        self.assertEqual(status, 400)
        self.assertIn('confirm_live_spend', body['error'])

    def test_mcp_refresh_requires_explicit_confirmation(self):
        status, body = self.request('POST', '/api/mcp/refresh', {'server': 'x'}, {'X-CIDM-Console': '1'})
        self.assertEqual(status, 400)
        self.assertIn('confirm_start_server', body['error'])

    def test_skills_open_rejects_files(self):
        target = self.root / 'not-a-folder.txt'
        target.write_text('x', encoding='utf-8')
        status, body = self.request('POST', '/api/skills/open', {'path': str(target)}, {'X-CIDM-Console': '1'})
        self.assertEqual(status, 400)

    def test_runs_listing_and_telemetry(self):
        run = self.root / 'runs' / 'sample'
        run.mkdir()
        (run / 'result.json').write_text(json.dumps({
            'status': 'paused_recoverable', 'route': 'broad_or_uncertain', 'gate_policy': 'recovery',
            'calls': [{'role': 'jev'}], 'committed': [{'id': 'input'}], 'events': [],
            'checkpoint': {'active_unit': 'hidden1', 'recovery_kind': 'retrieve_evidence'}}), encoding='utf-8')
        (run / 'checkpoint.json').write_text('{}', encoding='utf-8')
        status, body = self.request('GET', '/api/runs')
        self.assertEqual(status, 200)
        sample = next(r for r in body['runs'] if r['name'] == 'sample')
        self.assertTrue(sample['checkpoint'])
        self.assertEqual(sample['active_unit'], 'hidden1')
        status, summary = self.request('GET', '/api/runs/sample/telemetry')
        self.assertEqual(summary['status'], 'paused_recoverable')
        status, body = self.request('GET', '/api/runs/..%2F..%2Fetc/telemetry')
        self.assertEqual(status, 400)

    def test_resume_requires_operator_and_confirmation(self):
        status, body = self.request('POST', '/api/runs/sample/resume', {'confirm_live_spend': True},
                                    {'X-CIDM-Console': '1'})
        self.assertEqual(status, 400)
        self.assertIn('operator', body['error'])

    def test_static_page_has_security_headers(self):
        connection = HTTPConnection('127.0.0.1', self.port, timeout=10)
        connection.request('GET', '/', headers={'Host': '127.0.0.1:%d' % self.port})
        response = connection.getresponse()
        response.read()
        self.assertEqual(response.status, 200)
        self.assertEqual(response.getheader('X-Frame-Options'), 'DENY')
        self.assertIn("frame-ancestors 'none'", response.getheader('Content-Security-Policy'))
        connection.close()


class FakeAdapter:
    cancel_event = None

    def run(self, model, effort, prompt, schema, workspace):
        return {'artifact': {'answer': 'Signed in and responding.', 'unresolved': []},
                'usage': {'input_tokens': 10, 'output_tokens': 5}, 'requested_model': model,
                'requested_effort': effort, 'identity_verification': 'reported_match'}


class SmokeTestTests(unittest.TestCase):
    def test_bounded_smoke_test_is_permit_bound_and_tool_free(self):
        made = {}

        def factory(provider, authority, model):
            made['authority'] = authority
            return ClaudeCodeProvider(authority, adapter=FakeAdapter(), runner=lambda argv, timeout: {})
        config = console._merge_config({})
        result = console.run_frontier({'provider': 'claude', 'model': 'claude-sonnet-5-5', 'task': 'Say hi.'},
                                      config, provider_factory=factory)
        self.assertEqual(result['status'], 'completed')
        self.assertIn('not a Jev-governed', result['note'])
        events = made['authority'].events()
        self.assertEqual(events[0]['basis']['kind'], 'operator')
        self.assertTrue(audit_permit_ledger(events)['valid'])

    def test_smoke_test_requires_an_explicit_listed_model(self):
        config = console._merge_config({})
        with self.assertRaisesRegex(ValueError, 'explicit model'):
            console.run_frontier({'provider': 'codex', 'model': 'default', 'task': 'x'}, config)
        with self.assertRaisesRegex(ValueError, 'explicit model'):
            console.run_frontier({'provider': 'claude', 'model': 'not-listed', 'task': 'x'}, config)

    def test_request_builder_enforces_broker_limits(self):
        request = console.build_request({'task': 'Plan the release.', 'context': '',
                                         'sources': [{'title': 'Policy', 'text': 'Owner signs off.'}]})
        self.assertEqual(request['sources'], {'s1': {'title': 'Policy', 'text': 'Owner signs off.'}})
        self.assertIsNone(request['classification'])
        with self.assertRaises(ValueError):
            console.build_request({'task': 'x' * 1201})
        argv = console.broker_argv(Path('t.json'), Path('out'), 'claude', 'recovery', live=True)
        self.assertIn('--live', argv)
        self.assertNotIn('--skip-route-preflight', argv)


if __name__ == '__main__':
    unittest.main()
