"""Observable decisions and dispatch in the Codex-native broker; no live calls."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from atomic_mesh import MeshError, fingerprint
from codex_cli_adapter import CodexCliAdapter
from config import RunConfig
from native_transition_broker import NativeTransitionBroker, validate_spec


SPEC = {
    'goal': 'Write a source-supported release checklist for the service.',
    'context': '',
    'sources': {'policy': {'title': 'Release policy',
                           'text': 'Each release needs tests, rollback instructions, and an owner.'}},
    'active_project': False,
    'unresolved_stages': [],
    'classification': None,
}


class FakeCodex:
    def __init__(self, *, tamper_parent=False, tamper_source=False, fail=False,
                 unresolved_unit=None, invalid_scores=False):
        self.calls = []
        self.tamper_parent = tamper_parent
        self.tamper_source = tamper_source
        self.fail = fail
        self.unresolved_unit = unresolved_unit
        self.invalid_scores = invalid_scores

    def run(self, model, effort, prompt, schema, workspace):
        if self.fail:
            raise RuntimeError('provider unavailable')
        data = json.loads(prompt)
        self.calls.append((model, effort, data))
        if data.get('role') == 'separate Sol-high checker':
            artifact = {'verdict': 'pass', 'failed_criteria': [], 'reason': 'No defect found.',
                        'missing_evidence': []}
        else:
            parent_hashes = data['required_parent_hashes']
            source_hashes = data['required_source_hashes']
            if self.tamper_parent:
                parent_hashes = ['changed']
            if self.tamper_source:
                source_hashes = {'request': 'changed'}
            artifact = {'text': 'Supported project result.',
                        'data': {'summary': 'A bounded stage result.', 'claims': ['Source considered.'],
                                 'unresolved': (['Missing evidence'] if self.unresolved_unit is not None
                                                and data.get('unit', {}).get('id') == self.unresolved_unit
                                                else []),
                                 'parent_hashes': parent_hashes,
                                 'source_hashes': source_hashes},
                        'source_ids': list(data['sources']),
                        'five_scores': [0, 4, 4, 4, 4] if self.invalid_scores else [4, 4, 4, 4, 4],
                        'self_probability': None}
        return {'artifact': artifact, 'usage': {'input_tokens': 100, 'output_tokens': 50,
                                                'cached_input_tokens': 0,
                                                'reasoning_output_tokens': 10},
                'requested_model': model, 'requested_effort': effort,
                'actual_model': None, 'actual_effort': None,
                'identity_verification': 'requested_only', 'events': []}


class FakeJev:
    def __init__(self, *, check_unit=None):
        self.calls = []
        self.check_unit = check_unit

    def __call__(self, phase, options, state):
        self.calls.append((phase, copy.deepcopy(options), copy.deepcopy(state)))
        if phase == 'project_route':
            choice = 'five_unit'
        elif phase == 'authorize_unit':
            choice = 'compute' if 'compute' in options else 'luna_low'
        elif phase == 'after_worker':
            choice = ('check_sol_high' if self.check_unit == state['unit']['id']
                      and 'check_sol_high' in options else 'forward')
        elif phase == 'after_sol_high':
            choice = 'forward'
        else:
            raise AssertionError(phase)
        return {'choice': choice, 'model': 'typesafe/jev-1.13-20260917',
                'live': True, 'usage': {'input_tokens': 25, 'output_tokens': 5,
                                        'cost': 0.000001}}


class StubCodexCli(CodexCliAdapter):
    """Exercise the real adapter parser without launching a process."""
    def _execute(self, argv, workspace, prompt_path, stdout_path, stderr_path):
        payload = json.loads(prompt_path.read_text(encoding='utf-8').split('\n\n', 1)[1])
        artifact = {'text': 'Supported project result.',
                    'data': {'summary': 'A bounded stage result.', 'claims': [], 'unresolved': [],
                             'parent_hashes': payload['required_parent_hashes'],
                             'source_hashes': payload['required_source_hashes']},
                    'source_ids': list(payload['sources']), 'five_scores': [4, 4, 4, 4, 4],
                    'self_probability': None}
        events = [{'type': 'thread.started', 'thread_id': 'stub'},
                  {'type': 'turn.started'},
                  {'type': 'item.completed', 'item': {'id': 'final', 'type': 'agent_message',
                                                      'text': json.dumps(artifact)}},
                  {'type': 'turn.completed', 'usage': {'input_tokens': 100,
                                                      'cached_input_tokens': 0,
                                                      'output_tokens': 50,
                                                      'reasoning_output_tokens': 10}}]
        stdout_path.write_text('\n'.join(json.dumps(event) for event in events) + '\n',
                               encoding='utf-8')


class WrongRouteCodex(FakeCodex):
    def run(self, model, effort, prompt, schema, workspace):
        response = super().run(model, effort, prompt, schema, workspace)
        response['requested_model'] = 'gpt-6-sol' if model == 'gpt-6-luna' else 'gpt-6-luna'
        return response


class InvalidJev:
    def __init__(self, bad_phase):
        self.bad_phase = bad_phase

    def __call__(self, phase, options, state):
        if phase == self.bad_phase:
            return {'choice': 'direct_luna_low', 'model': 'typesafe/jev-1.13', 'live': True}
        return FakeJev()(phase, options, state)


class NativeTransitionBrokerTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.folder = Path(temporary.name)

    def broker(self, adapter=None, judge=None, name='run'):
        return NativeTransitionBroker(adapter or FakeCodex(), judge or FakeJev(),
                                      RunConfig(), self.folder / name)

    def short_spec(self):
        spec = copy.deepcopy(SPEC)
        task = {key: spec[key] for key in
                ('goal', 'sources', 'active_project', 'unresolved_stages')}
        from adaptive_run import input_snapshot_hash
        spec['classification'] = {'snapshot_hash': input_snapshot_hash(task, spec['context']),
                                  'multiple_steps': False, 'broad_project': False,
                                  'ambiguous': False, 'depends_on_context': False,
                                  'rationale': 'This input has one bounded independent answer.'}
        return spec

    def test_broad_default_has_five_jev_governed_units_and_four_codex_calls(self):
        codex, jev = FakeCodex(), FakeJev()
        result = self.broker(codex, jev).run(SPEC)
        self.assertEqual((result['status'], result['route']), ('complete', 'broad_or_uncertain'))
        self.assertEqual(len(result['committed']), 5)
        self.assertEqual(result['audit']['post_worker_jev_decisions'], 5)
        self.assertTrue(result['audit']['valid'])
        self.assertEqual(len(codex.calls), 4)
        self.assertEqual(len(jev.calls), 11)
        self.assertEqual([call['role'] for call in result['calls']].count('worker'), 4)
        self.assertEqual([call['role'] for call in result['calls']].count('jev'), 11)
        self.assertIsNone(result['primary_agent_tokens'])
        self.assertIsNone(result['codex_cost_usd'])
        self.assertEqual(result['answer'], 'Supported project result.')

    def test_full_broker_uses_real_cli_parser_contract_without_paid_calls(self):
        result = self.broker(StubCodexCli(), FakeJev(), 'cli-stub').run(SPEC)
        self.assertEqual(result['status'], 'complete')
        self.assertTrue(result['audit']['valid'])
        self.assertEqual(len([call for call in result['calls'] if call['role'] == 'worker']), 4)
        self.assertTrue(all(call['identity_verification'] == 'requested_only'
                            for call in result['calls'] if call['role'] == 'worker'))

    def test_short_uses_one_luna_low_and_reclassifies_next_input(self):
        codex, jev = FakeCodex(), FakeJev()
        first = self.broker(codex, jev, 'short').run(self.short_spec())
        self.assertEqual((first['status'], first['route']), ('complete', 'short_self_contained'))
        self.assertEqual([(call[0], call[1]) for call in codex.calls], [('gpt-6-luna', 'low')])
        self.assertEqual(jev.calls, [])
        next_spec = copy.deepcopy(SPEC)
        next_spec['context'] = 'The release project remains active.'
        next_spec['active_project'] = True
        second = self.broker(name='next').run(next_spec)
        self.assertEqual(second['route'], 'broad_or_uncertain')
        self.assertEqual(len(second['committed']), 5)
        stale = self.short_spec()
        stale['context'] = 'A changed accepted context.'
        with self.assertRaisesRegex(MeshError, 'stale_native_classification'):
            self.broker(name='stale').run(stale)
        self.assertFalse((self.folder / 'stale').exists())

    def test_active_project_cannot_use_a_short_assertion(self):
        spec = self.short_spec()
        spec['active_project'] = True
        task = {key: spec[key] for key in
                ('goal', 'sources', 'active_project', 'unresolved_stages')}
        from adaptive_run import input_snapshot_hash
        spec['classification']['snapshot_hash'] = input_snapshot_hash(task, spec['context'])
        self.assertEqual(validate_spec(spec)['classification']['scope'], 'broad_or_uncertain')

    def test_outstanding_project_stages_are_preserved_as_source_evidence(self):
        spec = copy.deepcopy(SPEC)
        spec['active_project'] = True
        spec['unresolved_stages'] = ['Define recovery checks', 'Review accessibility']
        codex = FakeCodex()
        result = self.broker(codex).run(spec)
        self.assertEqual(result['status'], 'complete')
        self.assertIn('outstanding', result['source_hashes'])
        self.assertIn('Define recovery checks', codex.calls[0][2]['sources']['outstanding']['text'])

    def test_short_path_rejects_invalid_worker_packet_without_jev(self):
        codex, jev = FakeCodex(invalid_scores=True), FakeJev()
        result = self.broker(codex, jev).run(self.short_spec())
        self.assertEqual(result['status'], 'quality_failed')
        self.assertIsNone(result['answer'])
        self.assertEqual(jev.calls, [])

    def test_jev_requested_sol_high_returns_to_jev_before_commit(self):
        codex, jev = FakeCodex(), FakeJev(check_unit='hidden1')
        result = self.broker(codex, jev).run(SPEC)
        self.assertEqual(result['status'], 'complete')
        self.assertEqual(result['audit']['post_checker_jev_decisions'], 1)
        self.assertEqual([(m, e) for m, e, p in codex.calls if p.get('role')],
                         [('gpt-6-sol', 'high')])
        self.assertEqual(result['calls'][result['calls'].index(next(c for c in result['calls']
                               if c['role'] == 'checker')) + 1]['role'], 'jev')

    def test_parent_or_source_tamper_cannot_release_answer(self):
        for label, adapter in [('parent', FakeCodex(tamper_parent=True)),
                               ('source', FakeCodex(tamper_source=True))]:
            with self.subTest(label=label):
                result = self.broker(adapter, FakeJev(), label).run(SPEC)
                self.assertEqual(result['status'], 'failed')
                self.assertIsNone(result['answer'])
                self.assertEqual(len(result['committed']), 1)

    def test_cli_failure_withholds_answer_and_preserves_failed_call(self):
        result = self.broker(FakeCodex(fail=True), FakeJev()).run(SPEC)
        self.assertEqual(result['status'], 'failed')
        self.assertIsNone(result['answer'])
        self.assertEqual([c['status'] for c in result['calls'] if c['role'] == 'worker'],
                         ['failed'])

    def test_mismatched_return_is_counted_as_failed_billed_call(self):
        result = self.broker(WrongRouteCodex(), FakeJev()).run(SPEC)
        self.assertEqual(result['status'], 'failed')
        self.assertIsNone(result['answer'])
        failed = [call for call in result['calls'] if call['role'] == 'worker']
        self.assertEqual(len(failed), 1)
        self.assertEqual(failed[0]['status'], 'failed')
        self.assertEqual(failed[0]['usage']['input_tokens'], 100)

    def test_invalid_jev_choice_cannot_bypass_five_units_or_release(self):
        result = self.broker(FakeCodex(), InvalidJev('project_route')).run(SPEC)
        self.assertEqual(result['status'], 'jev_call_failed')
        self.assertIsNone(result['answer'])
        self.assertEqual(result['calls'][0]['status'], 'failed')
        self.assertEqual([c for c in result['calls'] if c['role'] == 'worker'], [])

    def test_post_worker_jev_failure_withholds_candidate(self):
        result = self.broker(FakeCodex(), InvalidJev('after_worker')).run(SPEC)
        self.assertEqual(result['status'], 'failed')
        self.assertIsNone(result['answer'])
        self.assertEqual(result['committed'], [])
        self.assertTrue(any(c['role'] == 'jev' and c['status'] == 'failed'
                            for c in result['calls']))

    def test_output_cannot_drop_unresolved_reconciliation_issue(self):
        result = self.broker(FakeCodex(unresolved_unit='hidden3'), FakeJev()).run(SPEC)
        self.assertEqual(result['status'], 'failed')
        self.assertIsNone(result['answer'])
        self.assertEqual([p['id'] for p in result['committed']],
                         ['input', 'hidden1', 'hidden2', 'hidden3'])

    def test_output_cannot_drop_earlier_unresolved_issue(self):
        result = self.broker(FakeCodex(unresolved_unit='hidden1'), FakeJev()).run(SPEC)
        self.assertEqual(result['status'], 'failed')
        self.assertIsNone(result['answer'])
        self.assertEqual([p['id'] for p in result['committed']],
                         ['input', 'hidden1', 'hidden2', 'hidden3'])

    def test_native_audit_detects_missing_post_worker_jev_call(self):
        broker = self.broker()
        result = broker.run(SPEC)
        self.assertEqual(result['status'], 'complete')
        index = next(i for i, call in enumerate(broker.calls) if call['role'] == 'worker')
        broker.calls[index + 1]['phase'] = 'authorize_unit'
        finding = broker.audit_native_calls(result)
        self.assertFalse(finding['valid'])
        self.assertIn('native_return_without_jev_worker', finding['issues'])


if __name__ == '__main__':
    unittest.main()
