"""Claude (Sonnet/Opus) worker family through Claude Code; no live calls."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from atomic_mesh import MeshError  # noqa: E402
from claude_cli_adapter import ClaudeCliAdapter, ClaudeCliError  # noqa: E402
from config import RunConfig  # noqa: E402
from native_transition_broker import NativeTransitionBroker  # noqa: E402
from transport import Gateway  # noqa: E402

SCHEMA = {'type': 'object', 'properties': {'answer': {'type': 'string'}},
          'required': ['answer'], 'additionalProperties': False}
SPEC = {'goal': 'Write a source-supported release checklist for the service.', 'context': '',
        'sources': {'policy': {'title': 'Release policy', 'text': 'Each release needs tests, rollback and an owner.'}},
        'active_project': False, 'unresolved_stages': [], 'classification': None}


def cli_result(structured=None, *, model='claude-sonnet-5', extra_models=(), is_error=False, subtype='success'):
    usage = {'input_tokens': 120, 'cache_creation_input_tokens': 300, 'cache_read_input_tokens': 900,
             'output_tokens': 55}
    model_usage = {model: {'inputTokens': 120, 'outputTokens': 55}}
    model_usage.update({m: {'inputTokens': 5, 'outputTokens': 1} for m in extra_models})
    return {'type': 'result', 'subtype': subtype, 'is_error': is_error, 'num_turns': 1,
            'result': json.dumps(structured if structured is not None else {'answer': 'ok'}),
            'structured_output': structured if structured is not None else {'answer': 'ok'},
            'session_id': 's-1', 'total_cost_usd': 0.0042, 'usage': usage, 'modelUsage': model_usage}


class StubCli(ClaudeCliAdapter):
    def __init__(self, payload, returncode=0):
        super().__init__()
        self.payload, self.returncode, self.argv = payload, returncode, None

    def _execute(self, argv, workspace, prompt_path, stdout_path, stderr_path):
        self.argv = argv
        stdout_path.write_text(json.dumps(self.payload), encoding='utf-8')
        return self.returncode


class Base(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.folder = Path(tmp.name)


class ConfigTests(unittest.TestCase):
    def test_claude_family_catalog_checker_and_short_route(self):
        config = RunConfig(worker_family='claude')
        self.assertEqual({r['model'] for r in config.worker_routes()},
                         {'anthropic/claude-sonnet-5', 'anthropic/claude-opus-5'})
        self.assertEqual({r['effort'] for r in config.worker_routes()}, {'low', 'medium', 'high', 'xhigh'})
        self.assertEqual((config.checker_model, config.checker_effort), ('anthropic/claude-opus-5', 'high'))
        self.assertEqual(config.short_route()['id'], 'sonnet_low')
        self.assertEqual(RunConfig.from_dict(config.to_dict()), config)

    def test_default_family_is_unchanged_gpt6(self):
        config = RunConfig()
        self.assertEqual(config.worker_family, 'gpt6')
        self.assertEqual(config.short_route()['id'], 'luna_low')

    def test_family_mismatches_rejected(self):
        for bad in ({'worker_family': 'claude', 'worker_model': 'openai/gpt-6-luna'},
                    {'worker_family': 'claude', 'checker_model': 'anthropic/claude-sonnet-5'},
                    {'worker_family': 'claude', 'astra_explicitly_authorized': True},
                    {'worker_model': 'anthropic/claude-opus-5'}, {'worker_family': 'mixed'}):
            with self.assertRaises(ValueError):
                RunConfig.from_dict(bad)

    def test_opus_reservation_uses_opus_rates(self):
        config = RunConfig(worker_family='claude')
        self.assertAlmostEqual(config.reserve_usd('checker', 1000), (1000 * 5.0 + 2000 * 25.0) / 1e6)
        self.assertAlmostEqual(config.reserve_usd('worker', 1000, 'anthropic/claude-sonnet-5'),
                               (1000 * 2.0 + 2000 * 10.0) / 1e6)

    def test_openrouter_gateway_refuses_claude_workers(self):
        with tempfile.TemporaryDirectory() as tmp:
            gateway = Gateway(Path(tmp), RunConfig(worker_family='claude'))
            with self.assertRaises(MeshError):
                gateway.ask('worker', 'x', {'a': 1}, worker_route=RunConfig(worker_family='claude').short_route())


class AdapterTests(Base):
    def test_exact_route_no_tools_no_persistence(self):
        adapter = StubCli(cli_result(model='claude-opus-5'))
        result = adapter.run('claude-opus-5', 'xhigh', 'Summarise.', SCHEMA, self.folder)
        argv = adapter.argv
        self.assertEqual(argv[argv.index('--model') + 1], 'claude-opus-5')
        self.assertEqual(argv[argv.index('--effort') + 1], 'xhigh')
        self.assertEqual(argv[argv.index('--tools') + 1], '')
        self.assertIn('--no-session-persistence', argv)
        self.assertIn('--strict-mcp-config', argv)
        self.assertEqual(json.loads(argv[argv.index('--json-schema') + 1]), SCHEMA)
        self.assertEqual(result['artifact'], {'answer': 'ok'})
        self.assertIsNone(result['actual_effort'])

    def test_usage_normalised_to_cidm_subset_semantics(self):
        usage = StubCli(cli_result()).run('claude-sonnet-5', 'low', 'x', SCHEMA, self.folder)['usage']
        self.assertEqual(usage['input_tokens'], 120 + 300 + 900)
        self.assertEqual(usage['cached_input_tokens'], 900)
        self.assertEqual(usage['cache_write_input_tokens'], 300)
        self.assertEqual(usage['output_tokens'], 55)

    def test_served_identity_confirmed_or_conflict(self):
        ok = StubCli(cli_result()).run('claude-sonnet-5', 'low', 'x', SCHEMA, self.folder)
        self.assertEqual((ok['actual_model'], ok['identity_verification']), ('claude-sonnet-5', 'reported_match'))
        aux = StubCli(cli_result(extra_models=('claude-haiku-4-5',))).run('claude-sonnet-5', 'low', 'x', SCHEMA, self.folder)
        self.assertEqual(aux['identity_verification'], 'reported_match_with_auxiliary_models')
        with self.assertRaises(ClaudeCliError) as caught:
            StubCli(cli_result(model='claude-opus-5')).run('claude-sonnet-5', 'low', 'x', SCHEMA, self.folder)
        self.assertEqual(str(caught.exception), 'model_identity_conflict')
        self.assertEqual(caught.exception.usage['output_tokens'], 55)

    def test_cost_is_labelled_api_equivalent_not_a_bill(self):
        result = StubCli(cli_result()).run('claude-sonnet-5', 'low', 'x', SCHEMA, self.folder)
        self.assertEqual(result['api_equivalent_cost_usd'], 0.0042)
        self.assertNotIn('cost', result['usage'])

    def test_rejections_keep_reported_usage(self):
        for payload, code in ((cli_result({'unexpected': 1}), 'artifact_schema_mismatch'),
                              (cli_result(is_error=True, subtype='error_max_turns'), 'claude_call_failed')):
            with self.assertRaises(ClaudeCliError) as caught:
                StubCli(payload).run('claude-sonnet-5', 'low', 'x', SCHEMA, self.folder)
            self.assertEqual(str(caught.exception), code)
            self.assertTrue(caught.exception.ran)
            self.assertEqual(caught.exception.usage['input_tokens'], 1320)

    def test_unlisted_route_rejected_before_launch(self):
        adapter = StubCli(cli_result())
        for model, effort in (('claude-fable-5-1', 'low'), ('claude-sonnet-5', 'max'), ('gpt-6-sol', 'low')):
            with self.assertRaises(ClaudeCliError):
                adapter.run(model, effort, 'x', SCHEMA, self.folder)
        self.assertIsNone(adapter.argv)


class ClaudeBroker:
    """Fake Claude adapter that echoes required hashes like FakeCodex."""
    def __init__(self):
        self.calls = []

    def run(self, model, effort, prompt, schema, workspace):
        data = json.loads(prompt)
        self.calls.append((model, effort))
        if data.get('role') == 'separate Sol-high checker':
            artifact = {'verdict': 'pass', 'failed_criteria': [], 'reason': 'ok', 'missing_evidence': []}
        else:
            artifact = {'text': 'Result.', 'data': {'summary': 'x', 'claims': [], 'unresolved': [],
                                                    'parent_hashes': data['required_parent_hashes'],
                                                    'source_hashes': data['required_source_hashes']},
                        'source_ids': list(data['sources']), 'five_scores': [4] * 5, 'self_probability': None}
        return {'artifact': artifact, 'usage': {'input_tokens': 10, 'output_tokens': 5}, 'requested_model': model,
                'requested_effort': effort, 'actual_model': model, 'actual_effort': None,
                'identity_verification': 'reported_match', 'events': []}


def jev(check_unit=None):
    def decide(phase, options, state):
        if phase == 'project_route':
            choice = 'five_unit'
        elif phase == 'authorize_unit':
            choice = 'compute' if 'compute' in options else 'opus_high'
        elif phase == 'after_worker':
            choice = ('check_sol_high' if state['unit']['id'] == check_unit and 'check_sol_high' in options
                      else 'forward')
        else:
            choice = 'forward'
        return {'choice': choice, 'model': 'typesafe/jev-1.13-20260917', 'live': True,
                'usage': {'input_tokens': 10, 'output_tokens': 1, 'cost': 0.0000004}}
    return decide


class BrokerTests(Base):
    def test_five_units_route_to_claude_models_and_opus_checker(self):
        adapter = ClaudeBroker()
        result = NativeTransitionBroker(adapter, jev(check_unit='hidden2'), RunConfig(worker_family='claude'),
                                        self.folder / 'r').run(SPEC)
        self.assertEqual(result['status'], 'complete')
        self.assertTrue(result['native_audit']['valid'], result['native_audit'])
        self.assertIn(('claude-opus-5', 'high'), adapter.calls)
        self.assertTrue(all(m.startswith('claude-') for m, _ in adapter.calls))

    def test_short_route_is_one_sonnet_low_call(self):
        from adaptive_run import input_snapshot_hash
        spec = copy.deepcopy(SPEC)
        task = {k: spec[k] for k in ('goal', 'sources', 'active_project', 'unresolved_stages')}
        spec['classification'] = {'snapshot_hash': input_snapshot_hash(task, ''), 'multiple_steps': False,
                                  'broad_project': False, 'ambiguous': False, 'depends_on_context': False,
                                  'rationale': 'One bounded, independent answer.'}
        adapter = ClaudeBroker()
        result = NativeTransitionBroker(adapter, jev(), RunConfig(worker_family='claude'), self.folder / 's').run(spec)
        self.assertEqual(result['status'], 'complete')
        self.assertEqual(adapter.calls, [('claude-sonnet-5', 'low')])


if __name__ == '__main__':
    unittest.main()
