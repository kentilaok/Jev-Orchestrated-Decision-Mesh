"""P0-07 follow-up fixes: F2 evidence over-pause, F3 retry budget, withheld short-route log. Offline."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'tests'))

from adaptive_run import input_snapshot_hash
from atomic_mesh import fingerprint
from config import RunConfig
from native_transition_broker import NativeTransitionBroker
from test_native_transition_broker import SPEC, FakeCodex
from test_recovery_resume import EvidenceGatedCodex


def decision(choice, tokens=30):
    return {'choice': choice, 'model': 'typesafe/jev-1.13-20260917', 'live': True,
            'usage': {'input_tokens': tokens - 5, 'output_tokens': 5, 'cost': 0.000001}}


class PausePreferringJev:
    """Picks retrieve_evidence whenever it is offered, as Jev did in s2-01, s2-06 and s2-21."""

    def __init__(self, *, check_unit=None):
        self.gates = []
        self.check_unit = check_unit

    def __call__(self, phase, options, state):
        self.gates.append({'phase': phase, 'unit': state['unit']['id'], 'options': set(options),
                           'hard_checks': copy.deepcopy(state.get('hard_checks'))})
        if phase == 'authorize_unit':
            return decision('compute' if 'compute' in options else 'luna_low')
        if 'retrieve_evidence' in options:
            return decision('retrieve_evidence')
        if phase == 'after_worker' and state['unit']['id'] == self.check_unit:
            return decision('check_sol_high')
        return decision('forward' if 'forward' in options else 'repair')

    def gate(self, phase, unit):
        return next(g for g in self.gates if g['phase'] == phase and g['unit'] == unit)


class EvidenceOfferTests(unittest.TestCase):
    """F2: retrieve_evidence only when a missing source is named or can be fetched."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def run_broker(self, codex, jev, **options):
        return NativeTransitionBroker(codex, jev, RunConfig(), self.root / 'run',
                                      gate_policy='recovery', **options).run(SPEC)

    def test_passing_candidate_goes_on_instead_of_pausing(self):
        jev = PausePreferringJev()
        result = self.run_broker(FakeCodex(), jev)
        self.assertEqual(result['status'], 'complete')
        passing = [g for g in jev.gates if g['phase'] == 'after_worker']
        self.assertEqual(len(passing), 5)
        for gate in passing:
            self.assertTrue(all(gate['hard_checks'].values()))
            self.assertNotIn('retrieve_evidence', gate['options'])
            self.assertIn('forward', gate['options'])

    def test_worker_caveat_alone_does_not_offer_retrieve_evidence(self):
        # s2-01 pattern: an intermediate unit passes every hard check but lists a caveat.
        jev = PausePreferringJev()
        self.run_broker(FakeCodex(unresolved_unit='hidden1'), jev)
        gate = jev.gate('after_worker', 'hidden1')
        self.assertTrue(all(gate['hard_checks'].values()))
        self.assertNotIn('retrieve_evidence', gate['options'])
        self.assertTrue({'forward', 'check_sol_high'} <= gate['options'])

    def test_failed_checks_still_offer_retrieve_evidence_and_never_forward(self):
        jev = PausePreferringJev()
        result = self.run_broker(FakeCodex(tamper_parent=True), jev)
        gate = jev.gate('after_worker', 'hidden1')
        self.assertFalse(gate['hard_checks']['parent_hashes_match'])
        self.assertIn('retrieve_evidence', gate['options'])
        self.assertNotIn('forward', gate['options'])
        self.assertEqual(result['status'], 'paused_recoverable')
        self.assertEqual([p['id'] for p in result['committed']], ['input'])

    def test_checker_that_names_missing_evidence_offers_retrieve_evidence(self):
        jev = PausePreferringJev(check_unit='hidden1')
        result = self.run_broker(EvidenceGatedCodex(), jev)
        self.assertIn('retrieve_evidence', jev.gate('after_sol_high', 'hidden1')['options'])
        self.assertEqual(result['status'], 'paused_recoverable')
        self.assertEqual(result['checkpoint']['recovery_kind'], 'retrieve_evidence')
        self.assertIsNone(result['answer'])

    def test_passing_checker_does_not_offer_retrieve_evidence(self):
        jev = PausePreferringJev(check_unit='hidden1')
        result = self.run_broker(FakeCodex(), jev)
        gate = jev.gate('after_sol_high', 'hidden1')
        self.assertNotIn('retrieve_evidence', gate['options'])
        self.assertIn('forward', gate['options'])
        self.assertEqual(result['status'], 'complete')
        self.assertTrue(result['audit']['valid'], result['audit'])

    def test_retriever_keeps_retrieve_evidence_as_a_lookup(self):
        fetched = []

        def retriever(_request):
            if fetched:
                return None
            fetched.append(True)
            return {'kb-1': {'title': 'Runbook', 'text': 'The on-call owner signs off a rollback.'}}

        class OneLookupJev(PausePreferringJev):
            def __call__(self, phase, options, state):
                if any(e['id'] == 'kb-1' for e in state['source_manifest']):
                    options = {k: v for k, v in options.items() if k != 'retrieve_evidence'}
                return super().__call__(phase, options, state)

        jev = OneLookupJev()
        result = self.run_broker(FakeCodex(), jev, evidence_retriever=retriever)
        self.assertIn('retrieve_evidence', jev.gates[1]['options'])
        self.assertTrue(all(jev.gates[1]['hard_checks'].values()))
        self.assertEqual(result['status'], 'complete')
        self.assertIn('kb-1', result['source_hashes'])


class RepairOnceJev:
    """Repairs the first hidden1 candidate, then forwards; every call reports `tokens`."""

    def __init__(self, tokens):
        self.tokens = tokens
        self.repaired = False

    def __call__(self, phase, options, state):
        if phase == 'authorize_unit':
            return decision('compute' if 'compute' in options else 'luna_low', self.tokens)
        if state['unit']['id'] == 'hidden1' and not self.repaired:
            self.repaired = True
            return decision('repair', self.tokens)
        return decision('forward', self.tokens)


class RetryBudgetTests(unittest.TestCase):
    """F3: a unit retry needs Jev budget for itself and for every later unit."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def run_broker(self, config):
        return NativeTransitionBroker(FakeCodex(), RepairOnceJev(1000), config, self.root / 'run',
                                      gate_policy='recovery').run(SPEC)

    def test_retry_fails_fast_when_budget_cannot_cover_later_units(self):
        # After 4 calls of 1,000 tokens, 7,000 remain; the retry plus 3 later units need 8 calls.
        result = self.run_broker(RunConfig(max_jev_tokens=11000))
        self.assertEqual((result['status'], result['error']), ('failed', 'jev_budget_too_low_for_retry'))
        self.assertIsNone(result['answer'])
        jev_calls = [c for c in result['calls'] if c['role'] == 'jev']
        self.assertEqual(len(jev_calls), 4)
        self.assertTrue(all(c['status'] == 'ok' for c in result['calls']))
        self.assertEqual(result['accounting']['frontier_child_calls'], 1)

    def test_retry_proceeds_when_budget_covers_it(self):
        result = self.run_broker(RunConfig(max_jev_tokens=50000))
        self.assertEqual(result['status'], 'complete')
        self.assertEqual(result['accounting']['frontier_child_calls'], 5)
        self.assertTrue(result['audit']['valid'], result['audit'])

    def test_first_try_of_a_unit_is_not_held_back(self):
        # 9,000 tokens cannot cover a retry at hidden1, but no retry is asked for here.
        result = NativeTransitionBroker(FakeCodex(), PausePreferringJev(), RunConfig(max_jev_tokens=9000),
                                        self.root / 'first', gate_policy='recovery').run(SPEC)
        self.assertEqual(result['status'], 'complete')


class CaveatCodex(FakeCodex):
    """s1-20 pattern: the short-route worker lists an open caveat."""

    def run(self, model, effort, prompt, schema, workspace):
        response = super().run(model, effort, prompt, schema, workspace)
        response['artifact']['data']['unresolved'] = ['The excerpt does not show the default.']
        return response


class WithheldCandidateLogTests(unittest.TestCase):
    """Logging gap: a withheld short-route candidate is kept, labelled, and never released."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name) / 'run'

    def tearDown(self):
        self.temp.cleanup()

    def run_short(self, codex):
        spec = copy.deepcopy(SPEC)
        task = {key: spec[key] for key in ('goal', 'sources', 'active_project', 'unresolved_stages')}
        spec['classification'] = {'snapshot_hash': input_snapshot_hash(task, spec['context']),
                                  'multiple_steps': False, 'broad_project': False,
                                  'ambiguous': False, 'depends_on_context': False,
                                  'rationale': 'This input has one bounded independent answer.'}
        return NativeTransitionBroker(codex, PausePreferringJev(), RunConfig(), self.folder).run(spec)

    def test_withheld_candidate_is_stored_and_labelled_not_released(self):
        result = self.run_short(CaveatCodex())
        self.assertEqual(result['status'], 'quality_failed')
        self.assertIsNone(result['answer'])
        self.assertFalse(result['hard_checks']['output_has_no_unresolved'])
        record = json.loads((self.folder / 'withheld_candidate.json').read_text(encoding='utf-8'))
        self.assertIs(record['released'], False)
        self.assertTrue(record['notice'].startswith('NOT RELEASED'))
        self.assertEqual(record['candidate']['text'], 'Supported project result.')
        self.assertEqual(fingerprint(record['candidate']), result['candidate_hash'])
        self.assertEqual(record['candidate_hash'], result['candidate_hash'])
        self.assertEqual(result['withheld_candidate'],
                         {'file': 'withheld_candidate.json', 'candidate_hash': result['candidate_hash'],
                          'released': False})
        # The text stays out of the result and the journal; both keep only the hash.
        saved = (self.folder / 'result.json').read_text(encoding='utf-8')
        self.assertNotIn('Supported project result.', saved)
        journal = [json.loads(line) for line in
                   (self.folder / 'journal.jsonl').read_text(encoding='utf-8').splitlines()]
        self.assertEqual(journal[-1], {'kind': 'short_result', 'candidate_hash': result['candidate_hash'],
                                       'hard_checks': result['hard_checks'], 'released': False})

    def test_invalid_shape_candidate_is_stored(self):
        # s1-04 pattern: native_shape failed.
        result = self.run_short(FakeCodex(invalid_scores=True))
        self.assertEqual(result['status'], 'quality_failed')
        record = json.loads((self.folder / 'withheld_candidate.json').read_text(encoding='utf-8'))
        self.assertEqual(record['hard_checks'], {'native_shape': False})
        self.assertEqual(fingerprint(record['candidate']), result['candidate_hash'])

    def test_released_answer_writes_no_withheld_file(self):
        result = self.run_short(FakeCodex())
        self.assertEqual((result['status'], result['answer']), ('complete', 'Supported project result.'))
        self.assertNotIn('withheld_candidate', result)
        self.assertFalse((self.folder / 'withheld_candidate.json').exists())


if __name__ == '__main__':
    unittest.main()
