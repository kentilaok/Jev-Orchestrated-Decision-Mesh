"""Audit instrumentation fixes D-04, D-05, D-06 (from the inference-audit study; default on)."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'tests'))

import jev_decide
from atomic_mesh import MeshError
from codex_cli_adapter import CodexCliAdapter, CodexCliError
from config import RunConfig
from native_transition_broker import NativeTransitionBroker
from transport import Gateway
from test_native_transition_broker import SPEC, FakeCodex, FakeJev


class InstrumentationTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.folder = Path(temp.name)

    def test_jev_receipt_keeps_generation_id_and_timestamps_and_refuses_overwrite(self):
        request = {'model': 'typesafe/jev-1.13', 'state': {'x': 1},
                   'questions': {'next': {'type': 'choice', 'instructions': 'Pick.', 'criteria': {'a': 'A', 'b': 'B'}}}}
        req, out = self.folder / 'r.json', self.folder / 'o.json'
        req.write_text(json.dumps(request))
        response = {'id': 'gen-dec-42', 'model': 'typesafe/jev-1.13-20260917', 'provider': 'TypeSafe',
                    'usage': {'input_tokens': 5, 'output_tokens': 1, 'cost': 0.00000021},
                    'answers': {'next': {'type': 'choice', 'choice': 'a', 'confidence': 0.9,
                                         'probabilities': {'a': 0.95, 'b': 0.05}}}}
        with patch.object(jev_decide, 'call_api', return_value=(response, 12.0)), \
                patch.dict('os.environ', {'OPENROUTER_API_KEY': 'k'}), patch('sys.stdout'):
            self.assertEqual(jev_decide.main(['--request', str(req), '--out', str(out)]), 0)
            receipt = json.loads(out.read_text())
            self.assertEqual(receipt['provider_request_id'], 'gen-dec-42')
            self.assertTrue(receipt['started_at'].endswith('Z') and receipt['ended_at'].endswith('Z'))
            self.assertEqual(jev_decide.main(['--request', str(req), '--out', str(out)]), 2)
            self.assertEqual(json.loads(out.read_text()), receipt)

    def test_gateway_event_has_generation_id_and_timestamps(self):
        gateway = Gateway(self.folder, RunConfig())
        response = {'id': 'gen-dec-7', 'model': 'typesafe/jev-1.13-20260917', 'provider': 'TypeSafe',
                    'usage': {'input_tokens': 10, 'output_tokens': 2, 'cost': 0.00000042},
                    'answers': {'next': {'type': 'choice', 'choice': 'compute', 'confidence': 0.96,
                                         'probabilities': {'compute': 0.98, 'stop': 0.02}}}}
        with patch.object(gateway, '_request', return_value=response):
            gateway.network_judge('authorize_unit', {'compute': 'Run code.', 'stop': 'Stop.'}, {'x': 1})
        event = gateway.calls[-1]
        self.assertEqual(event['provider_request_id'], 'gen-dec-7')
        self.assertTrue(event['started_at'] and event['ended_at'])

    def test_codex_usage_survives_post_completion_rejection(self):
        class Stream(CodexCliAdapter):
            def _execute(self, argv, workspace, prompt_path, stdout_path, stderr_path):
                events = [{'type': 'thread.started'}, {'type': 'turn.started'},
                          {'type': 'item.completed', 'item': {'type': 'agent_message', 'text': '{"bad": 1}'}},
                          {'type': 'turn.completed', 'usage': {'input_tokens': 900, 'output_tokens': 80}}]
                stdout_path.write_text('\n'.join(json.dumps(e) for e in events) + '\n')
        schema = {'type': 'object', 'properties': {'answer': {'type': 'string'}}, 'required': ['answer'],
                  'additionalProperties': False}
        with self.assertRaises(CodexCliError) as caught:
            Stream().run('gpt-6-luna', 'low', 'x', schema, self.folder)
        self.assertEqual(caught.exception.usage['input_tokens'], 900)
        broker = NativeTransitionBroker(Stream(), FakeJev(), RunConfig(), self.folder / 'b')
        broker.worker_workspace = self.folder
        with self.assertRaises(MeshError):
            broker._codex('worker', 'openai/gpt-6-luna', 'low', 'x', schema)
        self.assertEqual(broker.calls[-1]['usage']['output_tokens'], 80)
        self.assertEqual(broker.calls[-1]['usage_status'], 'reported_before_rejection')

    def test_broker_reports_accounting_completeness(self):
        result = NativeTransitionBroker(FakeCodex(), FakeJev(), RunConfig(), self.folder / 'r').run(SPEC)
        self.assertEqual(result['status'], 'complete')
        self.assertFalse(result['accounting']['complete_system_accounting'])
        self.assertEqual(result['accounting']['primary_agent_usage'], 'unmetered')
        self.assertEqual(result['accounting']['frontier_calls_usage_unknown'], 0)
        self.assertEqual(result['accounting']['frontier_input_tokens'], 100 * result['accounting']['frontier_child_calls'])


if __name__ == '__main__':
    unittest.main()
