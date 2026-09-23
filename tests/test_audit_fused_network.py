import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from audit_fused_network import audit
from network_run import DEMO, DemoPipeline
from test_fused_checked_network import build, choose


class FusedAuditTests(unittest.TestCase):
    def test_clean_five_unit_trace_and_six_jev_calls(self):
        report = audit(build().run())
        self.assertTrue(report['valid'], report['issues'])
        self.assertEqual(report['jev_decisions'], 6)
        self.assertEqual(report['post_worker_decisions'], 5)
        self.assertEqual(report['deferred_dispatched'], 4)

    def test_checker_repair_and_early_stop_traces(self):
        def check_one(phase, options, state):
            if phase == 'after_worker_fused' and state['unit']['id'] == 'hidden1':
                return {'choice': 'check_sol_high', 'live': False, 'model': 'simulation'}
            return choose(phase, options, state)
        reviewed = build(check_one).run()
        self.assertTrue(audit(reviewed)['valid'], audit(reviewed)['issues'])
        self.assertEqual(audit(reviewed)['post_checker_decisions'], 1)

        demo = DemoPipeline(DEMO)
        attempts = {}
        def produce(unit, parents, feedback, route):
            attempts[unit.id] = attempts.get(unit.id, 0) + 1
            candidate = demo.produce(unit, parents, feedback, route)
            if unit.id == 'hidden1' and attempts[unit.id] == 1:
                candidate['data']['scale'] = 2000
            return candidate
        repaired = build(producer=produce).run()
        self.assertTrue(audit(repaired)['valid'], audit(repaired)['issues'])
        self.assertEqual(audit(repaired)['jev_decisions'], 7)

        def stop(phase, options, state):
            if phase == 'after_worker_fused' and state['unit']['id'] == 'hidden1':
                return {'choice': 'stop', 'live': False, 'model': 'simulation'}
            return choose(phase, options, state)
        stopped = build(stop).run()
        self.assertEqual(stopped['status'], 'stopped_by_jev')
        self.assertTrue(audit(stopped)['valid'], audit(stopped)['issues'])

    def test_detects_missing_jev_decision_and_changed_bindings(self):
        original = build().run()
        def missing_post(result):
            result['events'] = [e for e in result['events']
                                if not (e['kind'] == 'post_worker_decision' and e['unit_id'] == 'hidden1')]
        def changed_candidate(result):
            event = next(e for e in result['events'] if e['kind'] == 'post_worker_decision')
            event['candidate_hash'] = '0' * 64
        def changed_deferred_hash(result):
            event = next(e for e in result['events'] if e['kind'] == 'deferred_dispatch')
            event['action_hash'] = '0' * 64
        def changed_parent(result):
            event = next(e for e in result['events'] if e['kind'] == 'deferred_dispatch')
            event['action']['parents'] = [{'id': 'other', 'hash': '0' * 64}]
        def changed_release(result):
            result['answer'] = 'unreviewed answer'
        def changed_commit(result):
            result['committed'][-1]['artifact']['text'] = 'different'
        for mutate in (missing_post, changed_candidate, changed_deferred_hash,
                       changed_parent, changed_release, changed_commit):
            with self.subTest(mutate=mutate.__name__):
                changed = copy.deepcopy(original)
                mutate(changed)
                self.assertFalse(audit(changed)['valid'])

    def test_detects_duplicate_deferred_dispatch_and_changed_checker(self):
        result = build().run()
        duplicate = copy.deepcopy(result)
        event = copy.deepcopy(next(e for e in result['events'] if e['kind'] == 'deferred_dispatch'))
        event['id'] = 'e' + str(len(duplicate['events']) + 1)
        duplicate['events'].append(event)
        self.assertFalse(audit(duplicate)['valid'])

        def check_one(phase, options, state):
            if phase == 'after_worker_fused' and state['unit']['id'] == 'hidden1':
                return {'choice': 'check_sol_high', 'live': False, 'model': 'simulation'}
            return choose(phase, options, state)
        checked = build(check_one).run()
        checked['checks'][0]['result']['verdict'] = 'reject'
        self.assertFalse(audit(checked)['valid'])

    def test_false_complete_is_rejected(self):
        def stop(phase, options, state):
            if phase == 'after_worker_fused' and state['unit']['id'] == 'input':
                return {'choice': 'stop', 'live': False, 'model': 'simulation'}
            return choose(phase, options, state)
        result = build(stop).run()
        result['status'] = 'complete'
        result['answer'] = 'fabricated'
        self.assertFalse(audit(result)['valid'])


if __name__ == '__main__':
    unittest.main()
