"""Arsenal Phase A: permit/receipt-bound Fast Path and calibration thresholds (offline)."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'tests'))

from arsenal_calibration import (
    append_event, evaluate, prediction_event, read_events, runtime_event, threshold_report,
    verdict_event, wilson_lower_bound,
)
from arsenal_fastpath import FastPathExecutor, avoidance_summary, load_policy
from arsenal_registry import ArsenalRegistry
from capability_permits import PermitAuthority, PermitError, audit_permit_ledger
from test_arsenal_registry import SKILL, admitted_manifest

TASK = 'Protected product is visible while signed out'
BUG = 'wordpress.memberpress.logged_out_visibility'


class FastPathTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        skill_dir = root / 'skills' / 'public-protection'
        skill_dir.mkdir(parents=True)
        (skill_dir / 'SKILL.md').write_text(SKILL, encoding='utf-8')
        (skill_dir / 'ARSENAL.json').write_text(json.dumps(admitted_manifest()), encoding='utf-8')
        self.skill_dir = skill_dir
        self.registry = ArsenalRegistry(root / 'arsenal.db')
        self.registry.scan(root / 'skills')
        self.registry.admit('public-protection')
        skill = self.registry.list_skills()[0]
        self.pin = {'skill_hash': skill['skill_hash'], 'manifest_hash': skill['manifest_hash'],
                    'operations': ['inspect_content']}
        self.authority = PermitAuthority()
        self.ledger = root / 'fast-path.jsonl'

    def tearDown(self):
        self.registry.db.close()
        self.temp.cleanup()

    def policy(self, enabled=True, calibration=None, pin=None):
        return {'schema_version': 1, 'enabled': enabled, 'owner': 'owner-review',
                'approved_at': '2026-10-08', 'skills': {'public-protection': pin or self.pin},
                'calibration': calibration}

    def executor(self, *, policy='default', validator=lambda artifact, inputs: True, report=None):
        return FastPathExecutor(
            self.registry, self.authority,
            policy=self.policy() if policy == 'default' else policy,
            operations={'inspect_content': {'fn': lambda inputs: {'visible': False, 'url': inputs['url']},
                                            'required_inputs': ['url'], 'reversible': True}},
            validators={'anonymous_browser_check': validator}, calibration_report=report,
            ledger_path=self.ledger)

    def execute(self, executor, **overrides):
        args = {'project_scope': 'wordpress', 'bug_key': BUG, 'operation': 'inspect_content',
                'inputs': {'url': 'https://example.test/p'}}
        args.update(overrides)
        return executor.execute(TASK, **args)

    def test_disabled_by_default_without_a_policy(self):
        outcome = self.execute(self.executor(policy=None))
        self.assertEqual(outcome['status'], 'escalate_to_jev')
        self.assertIn('fast_path_policy_absent', outcome['decision']['reasons'])
        self.assertFalse(outcome['frontier_call_avoided'])
        self.assertEqual(self.authority.events(), [])

    def test_disabled_policy_does_not_execute(self):
        outcome = self.execute(self.executor(policy=self.policy(enabled=False)))
        self.assertIn('fast_path_policy_disabled', outcome['decision']['reasons'])
        self.assertIsNone(outcome['artifact'])

    def test_validated_run_consumes_one_permit_with_receipts(self):
        outcome = self.execute(self.executor())
        self.assertEqual(outcome['status'], 'validated_under_compiled_policy')
        self.assertTrue(outcome['commit_eligible'])
        self.assertTrue(outcome['frontier_call_avoided'])
        self.assertEqual([r['validator'] for r in outcome['receipts']], ['anonymous_browser_check'])
        events = self.authority.events()
        self.assertEqual([e['kind'] for e in events], ['permit_issued', 'permit_consumed', 'permit_receipt'])
        self.assertEqual(events[0]['basis']['kind'], 'compiled_policy')
        self.assertTrue(audit_permit_ledger(events)['valid'])

    def test_failed_validator_escalates_with_recovery_input(self):
        outcome = self.execute(self.executor(validator=lambda artifact, inputs: (False, 'still visible')))
        self.assertEqual(outcome['status'], 'escalate_to_jev')
        self.assertFalse(outcome['commit_eligible'])
        self.assertEqual(outcome['recovery_input']['failed_validators'], ['anonymous_browser_check'])

    def test_operation_error_escalates(self):
        def broken(artifact, inputs):
            raise RuntimeError('browser unavailable')
        outcome = self.execute(self.executor(validator=broken))
        self.assertEqual(outcome['reason'], 'operation_error')
        self.assertFalse(outcome['commit_eligible'])

    def test_lexical_match_without_exact_bug_key_never_executes(self):
        outcome = self.execute(self.executor(), bug_key=None)
        self.assertIn('exact_bug_key_required_for_v1_fast_path', outcome['decision']['reasons'])

    def test_missing_inputs_and_unpinned_operation_escalate(self):
        outcome = self.execute(self.executor(), inputs={})
        self.assertIn('missing_required_inputs', outcome['decision']['reasons'])
        pin = dict(self.pin, operations=['another_operation'])
        outcome = self.execute(self.executor(policy=self.policy(pin=pin)))
        self.assertIn('operation_not_in_owner_policy', outcome['decision']['reasons'])

    def test_policy_pin_must_match_admitted_hashes(self):
        pin = dict(self.pin, skill_hash='0' * 64)
        outcome = self.execute(self.executor(policy=self.policy(pin=pin)))
        self.assertIn('policy_pin_hash_mismatch', outcome['decision']['reasons'])

    def test_skill_changed_after_admission_escalates(self):
        executor = self.executor()
        (self.skill_dir / 'SKILL.md').write_text(SKILL + '\nNew unreviewed step.\n', encoding='utf-8')
        outcome = self.execute(executor)
        self.assertEqual(outcome['reason'], 'skill_changed_on_disk')
        self.assertEqual(self.authority.events(), [])

    def test_calibration_report_must_be_owner_accepted_and_meet_bar(self):
        report = threshold_report([], min_reviewed=1, min_precision_lower_bound=0.5)
        policy = self.policy(calibration={'report_hash': report['report_hash']})
        outcome = self.execute(self.executor(policy=policy, report=report))
        self.assertIn('calibration_threshold_not_met', outcome['decision']['reasons'])
        forged = dict(report, meets_operator_threshold=True)
        outcome = self.execute(self.executor(policy=policy, report=forged))
        self.assertIn('calibration_report_hash_invalid', outcome['decision']['reasons'])
        outcome = self.execute(self.executor(policy=policy, report=None))
        self.assertIn('calibration_report_required', outcome['decision']['reasons'])

    def test_avoidance_summary_counts_only_executed_validated_attempts(self):
        executor = self.executor()
        self.execute(executor)
        self.execute(executor, bug_key=None)
        summary = avoidance_summary(executor.ledger.read())
        self.assertEqual(summary['attempts'], 2)
        self.assertEqual(summary['frontier_calls_avoided'], 1)
        self.assertEqual(summary['escalated_to_jev'], 1)
        self.assertEqual(summary['by_skill'], {'public-protection': 1})

    def test_policy_schema_is_strict(self):
        with self.assertRaisesRegex(PermitError, 'fast_path_policy_schema'):
            load_policy({'enabled': True})
        with self.assertRaisesRegex(PermitError, 'policy_pin_requires_sha256'):
            load_policy(self.policy(pin={'skill_hash': 'x', 'manifest_hash': 'y', 'operations': ['a']}))


HASH = 'b' * 64


def shadow(candidate=True, skill='public-protection', recommendation=None, experience=None):
    recommendation = recommendation or ('fast_path_candidate' if candidate else
                                        'load_skill_then_jev' if skill else 'jev_only')
    match = {'skill_id': skill, 'match': {'score': 1.0, 'exact_bug_key': candidate}}
    return {'mode': 'shadow', 'authority': 'none_shadow_observation_only',
            'recommendation': recommendation, 'fast_path_candidate': candidate,
            'frontier_call_avoided': False, 'selected_skill_id': skill,
            'selected_experience_id': experience,
            'fused_candidates': [{'skill_id': skill}] if skill else [],
            'lexical': {'matches': [match] if skill else [], 'fast_path': {'eligible': candidate}}}


def runtime(status='complete'):
    return runtime_event('r', {'task_hash': HASH, 'status': status, 'simulation': False,
                               'route': 'broad_or_uncertain', 'calls': [{'role': 'jev'}],
                               'audit': {'valid': True}, 'native_audit': {'valid': True}})


class CalibrationThresholdTests(unittest.TestCase):
    def ledger(self, rows):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        path = Path(temp.name) / 'calibration.jsonl'
        for index, (prediction, expected, safe, status) in enumerate(rows):
            run_id = 'run-%d' % index
            append_event(path, prediction_event(run_id, HASH, prediction))
            event = runtime(status)
            event['run_id'] = run_id
            append_event(path, event)
            append_event(path, verdict_event(run_id, HASH, evidence_ref='ci://log/%d' % index,
                                             expected_skill_id=expected,
                                             expected_experience_id=None,
                                             fast_path_safe=safe, reviewer='reviewer'))
        return read_events(path)

    def test_wilson_lower_bound(self):
        self.assertIsNone(wilson_lower_bound(0, 0))
        self.assertAlmostEqual(wilson_lower_bound(30, 30), 0.886, places=3)
        self.assertLess(wilson_lower_bound(3, 3), 0.5)

    def test_threshold_needs_sample_size_and_zero_false_positives(self):
        events = self.ledger([(shadow(), 'public-protection', True, 'complete')] * 3)
        report = threshold_report(events, min_reviewed=3, min_precision_lower_bound=0.9)
        self.assertFalse(report['meets_operator_threshold'])
        self.assertIn('precision_lower_bound_below_owner_bar', report['reasons'])
        self.assertFalse(report['fast_path_enablement_allowed'])
        events = self.ledger([(shadow(), 'public-protection', True, 'complete')] * 40)
        report = threshold_report(events, min_reviewed=30, min_precision_lower_bound=0.9)
        self.assertTrue(report['meets_operator_threshold'])
        self.assertFalse(report['fast_path_enablement_allowed'])
        self.assertEqual(len(report['report_hash']), 64)
        events = self.ledger([(shadow(), 'public-protection', True, 'complete')] * 40
                             + [(shadow(), 'other-skill', True, 'complete')])
        report = threshold_report(events, min_reviewed=30, min_precision_lower_bound=0.5)
        self.assertIn('critical_false_positive_observed', report['reasons'])

    def test_negative_transfer_counts_misleading_context(self):
        events = self.ledger([
            (shadow(candidate=False), 'public-protection', False, 'complete'),
            (shadow(candidate=False), 'other-skill', False, 'complete'),
            (shadow(candidate=False, skill=None), None, False, 'complete'),
            (shadow(candidate=False), 'other-skill', False, 'quality_failed'),
        ])
        scored = evaluate(events)
        # The unaudited fourth run is excluded before any quality metric.
        self.assertEqual(scored['summary']['excluded_unverified_runtime'], 1)
        self.assertEqual(scored['summary']['context_loaded'], 2)
        self.assertEqual(scored['summary']['negative_transfer'], 1)
        self.assertEqual(scored['metrics']['negative_transfer_rate'], 0.5)


if __name__ == '__main__':
    unittest.main()
