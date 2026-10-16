"""P0-03 slice 3a: re-audit a saved live broker run folder offline.

Builds one clean permit-backed recovery run with fakes (no CLI, no network),
then tampers with copies to prove each check fires.
"""
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

from capability_permits import PermitAuthority, HashChainLedger  # noqa: E402
from config import RunConfig  # noqa: E402
from frontier_providers import ClaudeCodeProvider, PermittedAdapter  # noqa: E402
from native_transition_broker import NativeTransitionBroker  # noqa: E402
from p0_03_audit import audit_run, main  # noqa: E402
from test_native_transition_broker import SPEC, FakeCodex, RecoveryJev  # noqa: E402


class SessionCodex(FakeCodex):
    def run(self, *args, **kwargs):
        response = super().run(*args, **kwargs)
        return {**response, 'session_id': 'sess-%d' % len(self.calls)}


def build_clean_run(folder: Path) -> Path:
    """A complete recovery run whose result.json mirrors what broker main() writes."""
    out = folder / 'run'
    authority = PermitAuthority(folder / 'permits.jsonl')
    provider = ClaudeCodeProvider(authority, adapter=SessionCodex())
    broker = NativeTransitionBroker(PermittedAdapter(provider, authority), RecoveryJev(),
                                    RunConfig(worker_family='claude'), out,
                                    gate_policy='recovery', permit_authority=authority)
    result = broker.run(SPEC)
    assert result['status'] == 'complete', result['status']
    shutil.move(str(folder / 'permits.jsonl'), str(out / 'permits.jsonl'))
    jev = [c for c in result['calls'] if c['role'] == 'jev']
    result['jev_provider_events'] = [{'usage': c['usage']} for c in jev]
    result['jev_api_cost_usd'] = sum(c['usage']['cost'] for c in jev)
    result['route_coverage'] = {'status': 'skipped'}
    (out / 'result.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    return out


class P0_03AuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.clean = build_clean_run(Path(cls._tmp.name))

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.run_dir = Path(tmp.name) / 'run'
        shutil.copytree(self.clean, self.run_dir)
        self.config = RunConfig(worker_family='claude')

    def result(self):
        return json.loads((self.run_dir / 'result.json').read_text(encoding='utf-8'))

    def save(self, result):
        (self.run_dir / 'result.json').write_text(json.dumps(result), encoding='utf-8')

    def issues(self, config=None):
        return audit_run(self.run_dir, config or self.config)['issues']

    def test_clean_run_passes_with_evidence(self):
        report = audit_run(self.run_dir, self.config)
        self.assertEqual(report['issues'], [])
        self.assertTrue(report['ok'])
        evidence = report['evidence']
        self.assertEqual(evidence['policy_hash'], self.config.policy_hash)
        self.assertEqual(evidence['permits_consumed'], 4)
        self.assertEqual([c['session_id'] for c in evidence['frontier_calls']],
                         ['sess-1', 'sess-2', 'sess-3', 'sess-4'])
        for key in ('task_hash', 'result_sha256', 'journal_sha256', 'permits_sha256'):
            self.assertTrue(evidence[key], key)

    def test_ok_call_without_permit_is_flagged(self):
        result = self.result()
        extra = dict(next(c for c in result['calls'] if c['role'] == 'worker'), permit_id='forged')
        result['calls'].append(extra)
        self.save(result)
        issues = self.issues()
        self.assertTrue(any(i.startswith('frontier_call_without_permit') for i in issues), issues)
        self.assertIn('ok_call_permit_not_consumed:forged', issues)

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

    def test_answer_without_complete_status_is_flagged(self):
        result = self.result()
        result['status'] = 'failed'
        self.save(result)
        self.assertIn('answer_released_without_complete_status', self.issues())

    def test_released_answer_with_missing_jev_decision_is_flagged(self):
        result = self.result()
        result['events'] = [e for e in result['events'] if e['kind'] != 'post_worker_decision']
        self.save(result)
        self.assertTrue(any(i.startswith(('order:', 'native:')) for i in self.issues()))

    def test_jev_spend_over_max_usd_is_flagged(self):
        result = self.result()
        result['jev_provider_events'][0]['usage']['cost'] = 5.0
        result['jev_api_cost_usd'] = sum(e['usage']['cost'] for e in result['jev_provider_events'])
        self.save(result)
        self.assertIn('jev_spend_over_max_usd', self.issues(RunConfig(worker_family='claude', max_usd=1.0)))

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

    def test_permit_issued_past_cumulative_cap_is_flagged(self):
        path = self.run_dir / 'permits.jsonl'
        events = HashChainLedger(path).read()
        first_receipt = next(e for e in events if e['kind'] == 'permit_receipt')
        # Rebuild the chain with the first receipt costing more than the cap.
        path.unlink()
        ledger = HashChainLedger(path)
        for event in events:
            record = {k: v for k, v in event.items() if k not in ('event_hash', 'previous_event_hash')}
            if event is first_receipt:
                record['cost_usd'] = 2.0
            ledger.append(record)
        cfg = RunConfig(worker_family='claude', max_cumulative_usd=1.0)
        self.assertIn('permit_issued_past_cumulative_cap', self.issues(cfg))

    def test_cli_exit_codes(self):
        self.assertEqual(main([str(self.run_dir)]), 0)
        result = self.result()
        result['status'] = 'failed'
        self.save(result)
        self.assertEqual(main([str(self.run_dir)]), 1)


if __name__ == '__main__':
    unittest.main()
