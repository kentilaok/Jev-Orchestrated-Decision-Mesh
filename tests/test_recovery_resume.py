"""Phase H: persist a paused recovery run and resume it in a new process (offline)."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'tests'))

from atomic_mesh import MeshError, fingerprint
from config import RunConfig
from native_transition_broker import PROJECT_UNITS, NativeTransitionBroker
from recovery_protocol import restore_supervisor
from test_native_transition_broker import SPEC, FakeCodex


class EvidenceGatedJev:
    """Interpret needs operator evidence (a source whose id starts with 'operator-')."""

    def __init__(self, *, repair_at=None):
        self.calls = []
        self.repair_at = repair_at

    def __call__(self, phase, options, state):
        self.calls.append(phase)
        if phase == 'authorize_unit':
            choice = 'compute' if 'compute' in options else 'luna_low'
        elif phase == 'after_worker':
            unit = state['unit']['id']
            supplied = any(e['id'].startswith('operator-') for e in state['source_manifest'])
            if unit == self.repair_at and not supplied:
                choice = 'repair'
            elif unit == 'hidden1' and not supplied and self.repair_at is None:
                choice = 'retrieve_evidence'
            else:
                choice = 'forward'
        else:
            raise AssertionError(phase)
        return {'choice': choice, 'model': 'typesafe/jev-1.13-20260917', 'live': True,
                'usage': {'input_tokens': 25, 'output_tokens': 5, 'cost': 0.000001}}


EVIDENCE = {'operator-runbook': {'title': 'Release runbook',
                                 'text': 'Rollback uses the previous tagged build; the on-call owner signs off.'}}


class ResumeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def pause(self, config=None, jev=None):
        broker = NativeTransitionBroker(FakeCodex(), jev or EvidenceGatedJev(), config or RunConfig(),
                                        self.root / 'first', gate_policy='recovery')
        result = broker.run(SPEC)
        self.assertEqual(result['status'], 'paused_recoverable')
        bundle = json.loads((self.root / 'first' / 'checkpoint.json').read_text(encoding='utf-8'))
        return result, bundle

    def resume(self, bundle, folder='second', config=None, **options):
        broker = NativeTransitionBroker(FakeCodex(), EvidenceGatedJev(), config or RunConfig(),
                                        self.root / folder, gate_policy='recovery')
        return broker.run(SPEC, resume={'bundle': bundle, **options})

    def test_paused_run_resumes_to_an_audited_completion(self):
        paused, bundle = self.pause()
        self.assertEqual(paused['checkpoint']['active_unit'], 'hidden1')
        self.assertEqual(bundle['checkpoint']['completed_units'], ['input'])
        result = self.resume(bundle, additional_sources=EVIDENCE, operator='owner')
        self.assertEqual(result['status'], 'complete', result['status'])
        self.assertTrue(result['audit']['valid'], result['audit'])
        self.assertTrue(result['native_audit']['valid'], result['native_audit'])
        self.assertEqual(result['resumed_from'], bundle['bundle_hash'])
        self.assertIn('operator-runbook', result['source_hashes'])
        kinds = [e['kind'] for e in result['events']]
        self.assertIn('recovery_resumed', kinds)
        self.assertLess(kinds.index('recovery_checkpoint'), kinds.index('recovery_resumed'))
        carried = [c for c in result['calls'] if c.get('carried_from_checkpoint')]
        self.assertEqual(len(carried), len(paused['calls']))

    def test_tampered_bundle_is_rejected(self):
        _, bundle = self.pause()
        changed = copy.deepcopy(bundle)
        changed['committed'][0]['artifact']['text'] = 'rewritten'
        self.assertEqual(self.resume(changed, folder='a', additional_sources=EVIDENCE,
                                     operator='o')['status'], 'recovery_bundle_hash_mismatch')
        # Re-signing the bundle cannot hide a changed committed artifact.
        changed['bundle_hash'] = fingerprint({k: v for k, v in changed.items() if k != 'bundle_hash'})
        self.assertEqual(self.resume(changed, folder='b', additional_sources=EVIDENCE,
                                     operator='o')['status'], 'committed_artifact_changed')

    def test_resigned_state_change_fails_state_hash_check(self):
        _, bundle = self.pause()
        changed = copy.deepcopy(bundle)
        changed['mesh']['version'] += 1
        changed['bundle_hash'] = fingerprint({k: v for k, v in changed.items() if k != 'bundle_hash'})
        self.assertEqual(self.resume(changed, additional_sources=EVIDENCE, operator='o')['status'],
                         'resume_state_hash_mismatch')

    def test_operator_is_required_to_add_evidence(self):
        _, bundle = self.pause()
        self.assertEqual(self.resume(bundle, additional_sources=EVIDENCE)['status'],
                         'operator_required_for_added_evidence')

    def test_resume_requires_the_same_task_and_configuration(self):
        _, bundle = self.pause()
        # Identity checks fail before the new run folder is created.
        with self.assertRaisesRegex(MeshError, 'resume_config_mismatch'):
            self.resume(bundle, config=RunConfig(max_jev_calls=29), additional_sources=EVIDENCE, operator='o')
        self.assertFalse((self.root / 'second').exists())
        spec = dict(SPEC, goal='A different request entirely.')
        broker = NativeTransitionBroker(FakeCodex(), EvidenceGatedJev(), RunConfig(), self.root / 'c',
                                        gate_policy='recovery')
        with self.assertRaisesRegex(MeshError, 'resume_task_mismatch'):
            broker.run(spec, resume={'bundle': bundle})

    def test_pre_checkpoint_gates_cannot_authorize_new_work(self):
        _, bundle = self.pause()
        supervisor = restore_supervisor(bundle, lambda *a: None, None, None, None, units=PROJECT_UNITS)
        mesh = supervisor.network.mesh
        old_gate = next(e for e in reversed(mesh.events) if e['kind'] == 'jev_decision')
        option = old_gate['options'][old_gate['decision']['choice']]
        with self.assertRaisesRegex(MeshError, 'gate_already_used_or_stale'):
            mesh.permit(option.get('worker_id', 'policy'), option.get('action', {}), old_gate['id'])

    def test_budget_exhausted_pause_can_resume_with_operator_reset(self):
        config = RunConfig(max_recovery_rounds=0, max_recovery_attempts=1)
        paused, bundle = self.pause(config=config, jev=EvidenceGatedJev(repair_at='hidden1'))
        self.assertEqual(paused['checkpoint']['recovery_kind'], 'recovery_budget_exhausted')
        stuck = self.resume(bundle, folder='d', config=config)
        self.assertEqual(stuck['status'], 'paused_recoverable')
        result = self.resume(bundle, folder='e', config=config, additional_sources=EVIDENCE,
                             reset_active_unit_rounds=True, operator='owner')
        self.assertEqual(result['status'], 'complete')


if __name__ == '__main__':
    unittest.main()
