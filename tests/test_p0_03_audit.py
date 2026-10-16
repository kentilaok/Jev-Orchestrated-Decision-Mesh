"""P0-03 slice 3a: re-audit a saved live broker run folder offline.

Builds clean permit-backed runs with fakes (no CLI, no network) for the
recovery, fused and short routes, then tampers with copies to prove each
check fires and that legitimate run shapes are not flagged.
"""
import contextlib
import copy
import io
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

from adaptive_run import input_snapshot_hash  # noqa: E402
from capability_permits import HashChainLedger, PermitAuthority  # noqa: E402
from config import RunConfig  # noqa: E402
from frontier_providers import ClaudeCodeProvider, PermittedAdapter  # noqa: E402
from native_transition_broker import NativeTransitionBroker  # noqa: E402
from p0_03_audit import audit_run, main  # noqa: E402
from test_native_transition_broker import SPEC, FakeCodex, FusedJev, RecoveryJev  # noqa: E402

CONFIG = RunConfig(worker_family='claude')


class SessionCodex(FakeCodex):
    def run(self, *args, **kwargs):
        response = super().run(*args, **kwargs)
        return {**response, 'session_id': 'sess-%d' % len(self.calls)}


def short_spec():
    spec = copy.deepcopy(SPEC)
    task = {key: spec[key] for key in ('goal', 'sources', 'active_project', 'unresolved_stages')}
    spec['classification'] = {'snapshot_hash': input_snapshot_hash(task, spec['context']),
                              'multiple_steps': False, 'broad_project': False,
                              'ambiguous': False, 'depends_on_context': False,
                              'rationale': 'This input has one bounded independent answer.'}
    return spec


def build_run(folder: Path, *, judge=None, gate_policy='recovery', spec=SPEC) -> Path:
    """A complete run whose result.json mirrors what broker main() writes."""
    out = folder / 'run'
    authority = PermitAuthority(folder / 'permits.jsonl')
    provider = ClaudeCodeProvider(authority, adapter=SessionCodex())
    broker = NativeTransitionBroker(PermittedAdapter(provider, authority), judge or RecoveryJev(),
                                    CONFIG, out, gate_policy=gate_policy, permit_authority=authority)
    result = broker.run(spec)
    assert result['status'] == 'complete', result['status']
    shutil.move(str(folder / 'permits.jsonl'), str(out / 'permits.jsonl'))
    jev = [c for c in result['calls'] if c['role'] == 'jev']
    result['jev_provider_events'] = [{'usage': c['usage']} for c in jev]
    result['jev_api_cost_usd'] = sum(c['usage']['cost'] for c in jev) if jev else None
    result['route_coverage'] = {'status': 'skipped'}
    result['config_policy_hash'] = CONFIG.policy_hash
    (out / 'result.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    return out


def rewrite_ledger(path: Path, transform):
    """Rebuild the hash chain after transforming the event list (simulates a broker bug)."""
    events = [{k: v for k, v in e.items() if k not in ('event_hash', 'previous_event_hash', 'recorded_at')}
              for e in HashChainLedger(path).read()]
    path.unlink()
    ledger = HashChainLedger(path)
    for event in transform(events):
        ledger.append(event)


class Base(unittest.TestCase):
    clean = None

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.run_dir = Path(tmp.name) / 'run'
        shutil.copytree(self.clean, self.run_dir)

    def result(self):
        return json.loads((self.run_dir / 'result.json').read_text(encoding='utf-8'))

    def save(self, result):
        (self.run_dir / 'result.json').write_text(json.dumps(result), encoding='utf-8')

    def issues(self, config=CONFIG):
        return audit_run(self.run_dir, config)['issues']


def _build_once(cls, **kwargs):
    cls._tmp = tempfile.TemporaryDirectory()
    cls.clean = build_run(Path(cls._tmp.name), **kwargs)


class RecoveryRunTests(Base):
    @classmethod
    def setUpClass(cls):
        _build_once(cls)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def capped(self, cap):
        """Config of a run launched with this cap; the saved result names its hash."""
        config = RunConfig(worker_family='claude', max_cumulative_usd=cap)
        result = self.result()
        result['config_policy_hash'] = config.policy_hash
        self.save(result)
        return config

    def set_receipt_costs(self, costs):
        def transform(events):
            receipts = iter(costs)
            for event in events:
                if event['kind'] == 'permit_receipt':
                    event['cost_usd'] = next(receipts)
            return events
        rewrite_ledger(self.run_dir / 'permits.jsonl', transform)

    # Clean shapes pass.

    def test_clean_run_passes_with_evidence(self):
        report = audit_run(self.run_dir, CONFIG)
        self.assertEqual(report['issues'], [])
        evidence = report['evidence']
        self.assertEqual(evidence['run_config_policy_hash'], CONFIG.policy_hash)
        self.assertEqual(evidence['permits_consumed'], 4)
        self.assertEqual([c['session_id'] for c in evidence['frontier_calls']],
                         ['sess-1', 'sess-2', 'sess-3', 'sess-4'])
        for key in ('task_hash', 'result_sha256', 'journal_sha256', 'permits_sha256'):
            self.assertTrue(evidence[key], key)

    def test_call_refused_at_issue_is_not_flagged(self):
        result = self.result()
        result['calls'].append({'role': 'worker', 'status': 'failed', 'usage': None,
                                'usage_status': 'not_launched', 'error_type': 'PermitError'})
        result['accounting']['frontier_calls_usage_unknown'] += 1
        result['accounting']['frontier_input_tokens'] = None
        result['accounting']['frontier_output_tokens'] = None
        result['answer'], result['status'] = None, 'failed'
        self.save(result)
        self.assertEqual(self.issues(), [])

    def test_non_frontier_permit_on_same_ledger_is_not_counted(self):
        def transform(events):
            extra = {'kind': 'permit_issued', 'permit_id': 'r1', 'capability': 'retrieval.read',
                     'scope_hash': 'x', 'basis': {'kind': 'jev_decision'}}
            return events + [extra, {'kind': 'permit_consumed', 'permit_id': 'r1', 'scope_hash': 'x'},
                             {'kind': 'permit_receipt', 'permit_id': 'r1', 'status': 'ok', 'cost_usd': None}]
        rewrite_ledger(self.run_dir / 'permits.jsonl', transform)
        self.assertEqual(self.issues(), [])

    def test_carried_calls_of_a_resumed_run_are_not_bound_to_this_ledger(self):
        result = self.result()
        carried = dict(next(c for c in result['calls'] if c['role'] == 'worker'),
                       permit_id='from-source-run', carried_from_checkpoint=True)
        result['calls'].insert(0, carried)
        result['accounting']['frontier_input_tokens'] += carried['usage']['input_tokens']
        result['accounting']['frontier_output_tokens'] += carried['usage']['output_tokens']
        result['answer'], result['status'] = None, 'failed'
        self.save(result)
        report = audit_run(self.run_dir, CONFIG)
        self.assertEqual(report['issues'], [])
        self.assertEqual(report['evidence']['resumed_calls_carried'], 1)

    def test_route_preflight_failed_result_is_not_flagged(self):
        self.save({'status': 'route_preflight_failed', 'route': 'broad_or_uncertain', 'answer': None,
                   'calls': [], 'config_policy_hash': CONFIG.policy_hash})
        (self.run_dir / 'permits.jsonl').unlink()
        (self.run_dir / 'journal.jsonl').unlink()
        self.assertEqual(self.issues(), [])

    # Config binding.

    def test_config_mismatch_is_flagged(self):
        self.assertIn('config_mismatch', self.issues(RunConfig(worker_family='claude', max_usd=0.5)))

    def test_missing_config_hash_is_flagged(self):
        result = self.result()
        del result['config_policy_hash']
        self.save(result)
        self.assertIn('config_policy_hash_missing', self.issues())

    def test_cli_max_cumulative_usd_flag_reaches_config(self):
        self.set_receipt_costs([2.0, 0.1, 0.1, 0.1])
        self.capped(1.0)
        with contextlib.redirect_stdout(io.StringIO()) as out:
            code = main([str(self.run_dir), '--max-cumulative-usd', '1.0'])
        self.assertEqual(code, 1)
        self.assertIn('permit_issued_past_cumulative_cap', out.getvalue())

    # Permits.

    def test_ok_call_without_permit_is_flagged(self):
        result = self.result()
        result['calls'].append(dict(next(c for c in result['calls'] if c['role'] == 'worker'),
                                    permit_id='forged'))
        self.save(result)
        issues = self.issues()
        self.assertTrue(any(i.startswith('frontier_call_without_permit') for i in issues), issues)
        self.assertIn('ok_call_permit_not_consumed:forged', issues)

    def test_reused_permit_id_is_flagged(self):
        result = self.result()
        workers = [c for c in result['calls'] if c['role'] == 'worker']
        workers[1]['permit_id'] = workers[0]['permit_id']
        self.save(result)
        self.assertIn('permit_id_reused_across_calls', self.issues())

    def test_extra_frontier_consumption_is_flagged(self):
        def transform(events):
            issued = dict(next(e for e in events if e['kind'] == 'permit_issued'), permit_id='extra')
            consumed = dict(next(e for e in events if e['kind'] == 'permit_consumed'), permit_id='extra')
            return events + [issued, consumed]
        rewrite_ledger(self.run_dir / 'permits.jsonl', transform)
        self.assertTrue(any(i.startswith('permit_without_frontier_call') for i in self.issues()))

    def test_double_consumption_is_flagged(self):
        def transform(events):
            return events + [dict(next(e for e in events if e['kind'] == 'permit_consumed'))]
        rewrite_ledger(self.run_dir / 'permits.jsonl', transform)
        self.assertTrue(any(i.startswith('permit:double_consumption') for i in self.issues()))

    def test_missing_receipt_is_flagged(self):
        def transform(events):
            first = next(i for i, e in enumerate(events) if e['kind'] == 'permit_receipt')
            return events[:first] + events[first + 1:]
        rewrite_ledger(self.run_dir / 'permits.jsonl', transform)
        self.assertTrue(any(i.startswith('permit:') for i in self.issues()))

    def test_missing_permit_ledger_is_flagged(self):
        (self.run_dir / 'permits.jsonl').unlink()
        self.assertIn('frontier_calls_without_permit_ledger', self.issues())

    def test_tampered_permit_ledger_is_flagged(self):
        path = self.run_dir / 'permits.jsonl'
        lines = path.read_text(encoding='utf-8').splitlines()
        event = json.loads(lines[0])
        event['capability'] = 'tampered'
        lines[0] = json.dumps(event)
        path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
        self.assertTrue(any(i.startswith('permit_ledger_unreadable') for i in self.issues()))

    # Cumulative cap.

    def test_run_that_stops_after_crossing_the_cap_passes(self):
        self.set_receipt_costs([0.1, 0.1, 0.1, 2.0])
        self.assertEqual(self.issues(self.capped(1.0)), [])

    def test_permit_issued_after_receipt_equal_to_cap_is_flagged(self):
        self.set_receipt_costs([1.0, 0.0, 0.0, 0.0])  # total stays exactly at the cap
        self.assertIn('permit_issued_past_cumulative_cap', self.issues(self.capped(1.0)))

    def test_receipt_without_cost_makes_cap_unverifiable(self):
        self.assertIn('cumulative_cap_unverifiable:receipt_without_cost', self.issues(self.capped(1.0)))

    # Release audits.

    def test_answer_without_complete_status_is_flagged(self):
        result = self.result()
        result['status'] = 'failed'
        self.save(result)
        self.assertIn('answer_released_without_complete_status', self.issues())

    def test_released_answer_with_missing_jev_decision_is_flagged(self):
        result = self.result()
        result['events'] = [e for e in result['events'] if e['kind'] != 'post_worker_decision']
        self.save(result)
        self.assertTrue(any(i.startswith('order:') for i in self.issues()))

    def test_native_audit_tamper_is_flagged(self):
        result = self.result()
        next(c for c in result['calls'] if c['role'] == 'worker')['artifact_hash'] = 'changed'
        self.save(result)
        self.assertTrue(any(i.startswith('native:') for i in self.issues()))

    def test_journal_that_differs_from_result_events_is_flagged(self):
        result = self.result()
        result['events'] = result['events'][:-1]
        self.save(result)
        self.assertIn('journal_differs_from_result_events', self.issues())

    def test_missing_result_is_flagged_and_ledger_still_audited(self):
        (self.run_dir / 'result.json').unlink()
        report = audit_run(self.run_dir, CONFIG)
        self.assertIn('result_missing', report['issues'])
        self.assertEqual(report['evidence']['permits_consumed'], 4)

    # Spend and usage.

    def test_jev_spend_over_max_usd_is_flagged(self):
        result = self.result()
        result['jev_provider_events'][0]['usage']['cost'] = 5.0
        result['jev_api_cost_usd'] = sum(e['usage']['cost'] for e in result['jev_provider_events'])
        self.save(result)
        self.assertIn('jev_spend_over_max_usd', self.issues())

    def test_jev_overspend_is_not_hidden_by_unknown_usage(self):
        result = self.result()
        result['jev_provider_events'][0]['usage']['cost'] = 5.0
        result['jev_provider_events'][1]['usage'] = None
        result['jev_api_cost_usd'] = None
        self.save(result)
        self.assertIn('jev_spend_over_max_usd', self.issues())

    def test_jev_cost_mismatch_is_flagged(self):
        result = self.result()
        result['jev_api_cost_usd'] = 0.0
        self.save(result)
        self.assertIn('jev_cost_mismatch', self.issues())

    def test_unknown_jev_usage_must_not_report_a_cost(self):
        result = self.result()
        result['jev_provider_events'][0]['usage'] = None
        self.save(result)
        self.assertIn('jev_cost_reported_despite_unknown_usage', self.issues())

    def test_unknown_frontier_usage_must_not_be_summed(self):
        result = self.result()
        next(c for c in result['calls'] if c['role'] == 'worker')['usage'] = None
        self.save(result)
        issues = self.issues()
        self.assertIn('unknown_usage_count_mismatch', issues)
        self.assertIn('unknown_usage_summed_as_known', issues)

    def test_known_token_totals_are_recomputed(self):
        result = self.result()
        result['accounting']['frontier_input_tokens'] = 0
        self.save(result)
        self.assertIn('frontier_token_totals_mismatch', self.issues())

    def test_cli_exit_codes(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main([str(self.run_dir)]), 0)
            result = self.result()
            result['status'] = 'failed'
            self.save(result)
            self.assertEqual(main([str(self.run_dir)]), 1)


class FusedRunTests(Base):
    @classmethod
    def setUpClass(cls):
        _build_once(cls, judge=FusedJev(), gate_policy='fused')

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_clean_fused_run_passes(self):
        self.assertEqual(self.issues(), [])

    def test_fused_missing_decision_is_flagged(self):
        result = self.result()
        decisions = [i for i, e in enumerate(result['events']) if e['kind'] == 'jev_decision']
        del result['events'][decisions[-1]]
        self.save(result)
        self.assertTrue(any(i.startswith(('order:', 'native:')) for i in self.issues()))


class ShortRouteTests(Base):
    @classmethod
    def setUpClass(cls):
        _build_once(cls, spec=short_spec(), gate_policy='legacy')

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_clean_short_run_passes(self):
        report = audit_run(self.run_dir, CONFIG)
        self.assertEqual(report['issues'], [])
        self.assertEqual(report['evidence']['route'], 'short_self_contained')

    def test_short_run_with_failed_hard_check_is_flagged(self):
        result = self.result()
        key = next(iter(result['hard_checks']))
        result['hard_checks'][key] = False
        self.save(result)
        self.assertIn('short_route_hard_checks_not_passed', self.issues())

    def test_short_run_with_wrong_model_is_flagged(self):
        result = self.result()
        result['calls'][0]['requested_model'] = 'claude-opus-5'
        self.save(result)
        self.assertIn('short_route_call_mismatch', self.issues())


if __name__ == '__main__':
    unittest.main()
