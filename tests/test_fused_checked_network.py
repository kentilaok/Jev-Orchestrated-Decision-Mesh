"""Fused transition protocol: one Jev choice authorizes the next exact unit."""
import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from atomic_mesh import MeshError, fingerprint, packed
from checked_network import UNITS
from fused_checked_network import FusedCheckedNetwork
from network_run import DEMO, DemoPipeline, fake_check


def choose(phase, options, state):
    if phase == 'authorize_first_unit':
        choice = 'compute'
    elif phase in ('after_worker_fused', 'after_sol_high_fused'):
        choice = next((key for key in options if key.startswith('forward_')),
                      next((key for key in options if key.startswith('retry_')), 'stop'))
    else:
        raise AssertionError(phase)
    return {'choice': choice, 'live': False, 'model': 'simulation'}


def build(judge=choose, producer=None, validator=None, checker=fake_check):
    demo = DemoPipeline(DEMO)
    return FusedCheckedNetwork(DEMO['goal'], {'records': {'text': packed(DEMO)}},
                               judge, producer or demo.produce, checker,
                               validator or demo.validate,
                               policy={'version': 'fused-fixture'}, simulation=True,
                               deterministic_units=('input', 'hidden2'))


class FusedTests(unittest.TestCase):
    def test_clean_five_unit_path_uses_six_jev_decisions(self):
        result = build().run()
        self.assertEqual(result['status'], 'complete')
        self.assertEqual([p['id'] for p in result['committed']], [u.id for u in UNITS])
        self.assertEqual(len([e for e in result['events'] if e['kind'] == 'jev_decision']), 6)
        self.assertEqual(len([e for e in result['events'] if e['kind'] == 'deferred_dispatch']), 4)
        self.assertEqual(len([e for e in result['events'] if e['kind'] == 'post_worker_decision']), 5)
        self.assertEqual(result['checks'], [])
        self.assertEqual(result['answer'], result['committed'][-1]['artifact']['text'])
        self.assertEqual(result['committed'][-1]['decision_phase'], 'after_worker_fused')

    def test_first_gate_can_stop_without_any_dispatch_or_answer(self):
        def stop_first(phase, options, state):
            if phase == 'authorize_first_unit':
                return {'choice': 'stop', 'live': False, 'model': 'simulation'}
            return choose(phase, options, state)
        result = build(stop_first).run()
        self.assertEqual(result['status'], 'stopped_by_jev')
        self.assertIsNone(result['answer'])
        self.assertEqual(result['committed'], [])
        self.assertFalse(any(e['kind'] in ('dispatch', 'deferred_dispatch') for e in result['events']))

    def test_repair_route_is_fused_and_bound_to_failed_candidate(self):
        demo = DemoPipeline(DEMO)
        attempts = {}
        def produce(unit, parents, feedback, route):
            attempts[unit.id] = attempts.get(unit.id, 0) + 1
            candidate = demo.produce(unit, parents, feedback, route)
            if unit.id == 'hidden1' and attempts[unit.id] == 1:
                candidate['data']['scale'] = 2000
            return candidate
        result = build(producer=produce).run()
        self.assertEqual(result['status'], 'complete')
        self.assertEqual(attempts['hidden1'], 2)
        self.assertEqual(len([e for e in result['events'] if e['kind'] == 'jev_decision']), 7)
        self.assertEqual(len(result['checks']), 0)
        bad = [e for e in result['events'] if e['kind'] == 'post_worker_decision'
               and e['unit_id'] == 'hidden1'][0]
        self.assertFalse(all(bad['hard_checks'].values()))
        self.assertTrue(bad['choice'].startswith('retry_'))

    def test_optional_checker_returns_to_jev_and_can_stop_release(self):
        def check_one(phase, options, state):
            if phase == 'after_worker_fused' and state['unit']['id'] == 'hidden1':
                return {'choice': 'check_sol_high', 'live': False, 'model': 'simulation'}
            return choose(phase, options, state)
        result = build(check_one).run()
        self.assertEqual(result['status'], 'complete')
        self.assertEqual(len(result['checks']), 1)
        self.assertEqual(len([e for e in result['events'] if e['kind'] == 'jev_decision']), 7)
        self.assertEqual(result['committed'][1]['decision_phase'], 'after_sol_high_fused')
        self.assertTrue(result['committed'][1]['checker']['contract_valid'])
        def stop_after_check(phase, options, state):
            if phase == 'after_sol_high_fused':
                return {'choice': 'stop', 'live': False, 'model': 'simulation'}
            return check_one(phase, options, state)
        stopped = build(stop_after_check).run()
        self.assertEqual(stopped['status'], 'stopped_by_jev')
        self.assertIsNone(stopped['answer'])
        self.assertEqual([p['id'] for p in stopped['committed']], ['input'])

    def test_failed_hard_checks_never_offer_forward_or_checker(self):
        visible = []
        def inspect(phase, options, state):
            if phase == 'after_worker_fused':
                visible.append(set(options))
            return choose(phase, options, state)
        result = build(inspect, validator=lambda *_: {'semantic_check': False}).run()
        self.assertIn(result['status'], ('stopped_by_jev', 'repair_limit'))
        self.assertEqual(result['committed'], [])
        self.assertTrue(all(not any(k.startswith('forward_') for k in keys)
                            and 'check_sol_high' not in keys for keys in visible))

    def test_rejected_sol_check_never_offers_forward(self):
        seen = []
        def judge(phase, options, state):
            if phase == 'after_worker_fused':
                return {'choice': 'check_sol_high', 'live': False, 'model': 'simulation'}
            if phase == 'after_sol_high_fused':
                seen.append(set(options))
                return {'choice': 'stop', 'live': False, 'model': 'simulation'}
            return choose(phase, options, state)
        def reject(_):
            return {'verdict': 'reject', 'failed_criteria': ['evidence'],
                    'reason': 'The result is unsupported.', 'missing_evidence': []}
        result = build(judge, checker=reject).run()
        self.assertEqual(result['status'], 'stopped_by_jev')
        self.assertEqual(result['committed'], [])
        self.assertFalse(any(k.startswith('forward_') for k in seen[0]))

    def test_deferred_permit_rejects_replay_tamper_and_stale_state(self):
        def capture_network():
            net = build()
            original = net.dispatch_deferred
            retained = []
            def capture(token, action):
                retained.append((token, copy.deepcopy(action)))
                return original(token, action)
            net.dispatch_deferred = capture
            self.assertEqual(net.run()['status'], 'complete')
            return net, retained, original
        net, permits, original = capture_network()
        with self.assertRaises(MeshError):
            original(*permits[0])

        def intercept_dispatch(mutator):
            net = build()
            held = []
            def intercept(token, action):
                held.append((token, copy.deepcopy(action)))
                mutator(net, token, action)
                with self.assertRaises(MeshError):
                    FusedCheckedNetwork.dispatch_deferred(net, token, action)
                raise RuntimeError('abort_after_adversarial_test')
            net.dispatch_deferred = intercept
            self.assertEqual(net.run()['status'], 'failed')
            self.assertEqual(net._pending, {})
            with self.assertRaises(MeshError):
                FusedCheckedNetwork.dispatch_deferred(net, *held[0])
        def mutate_action(net, token, action):
            action['attempt'] = 1
        def mutate_source(net, token, action):
            net.mesh.sources['records']['text'] += ' tamper'
        def mutate_policy(net, token, action):
            net.policy['version'] = 'tamper'
        def mutate_parent(net, token, action):
            net.committed[0]['artifact']['text'] = 'tamper'
        def mutate_candidate(net, token, action):
            net._latest_candidate['text'] = 'tamper'
        def mutate_checks(net, token, action):
            net._latest_checks['artifact_schema_valid'] = False
        def mutate_gate(net, token, action):
            gate = next(e for e in net.mesh.events if e['id'] == net._pending[token]['gate_id'])
            gate['decision']['choice'] = 'stop'
        def mutate_cursor(net, token, action):
            net.mesh.record('unexpected_event')
        for mutator in (mutate_action, mutate_source, mutate_policy, mutate_parent,
                        mutate_candidate, mutate_checks, mutate_gate, mutate_cursor):
            with self.subTest(mutator=mutator.__name__):
                intercept_dispatch(mutator)

    def test_only_one_deferred_token_per_gate(self):
        net = build()
        original = net.dispatch_deferred
        seen = []
        def intercept(token, action):
            gate_id = net._pending[token]['gate_id']
            gate = next(e for e in net.mesh.events if e['id'] == gate_id)
            approved = gate['options'][gate['decision']['choice']]['action']
            with self.assertRaises(MeshError):
                net._issue_deferred(gate_id, approved, action, None)
            seen.append(gate_id)
            return original(token, action)
        net.dispatch_deferred = intercept
        self.assertEqual(net.run()['status'], 'complete')
        self.assertEqual(len(seen), 4)

    def test_valid_candidate_has_no_automatic_retry_option(self):
        choices = []
        def judge(phase, options, state):
            if phase == 'after_worker_fused' and all(state['hard_checks'].values()):
                choices.append(set(options))
            return choose(phase, options, state)
        self.assertEqual(build(judge).run()['status'], 'complete')
        self.assertTrue(all(not any(name.startswith('retry_') for name in names)
                            for names in choices))

    def test_first_gate_can_request_evidence_without_dispatch(self):
        def judge(phase, options, state):
            if phase == 'authorize_first_unit':
                return {'choice': 'retrieve_evidence', 'live': False, 'model': 'simulation'}
            return choose(phase, options, state)
        result = build(judge).run()
        self.assertEqual(result['status'], 'needs_evidence')
        self.assertEqual(result['committed'], [])
        self.assertIsNone(result['answer'])

    def test_no_release_when_last_result_is_rejected(self):
        def judge(phase, options, state):
            if phase == 'after_worker_fused' and state['unit']['id'] == 'output':
                return {'choice': 'stop', 'live': False, 'model': 'simulation'}
            return choose(phase, options, state)
        result = build(judge).run()
        self.assertEqual(result['status'], 'stopped_by_jev')
        self.assertEqual(len(result['committed']), 4)
        self.assertIsNone(result['answer'])


if __name__ == '__main__':
    unittest.main()
