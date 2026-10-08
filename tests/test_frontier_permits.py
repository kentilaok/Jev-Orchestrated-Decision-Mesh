"""Arsenal Phase B: capability permits, frontier providers, and broker binding (offline)."""
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'tests'))

from capability_permits import PermitAuthority, PermitError, audit_permit_ledger
from config import RunConfig
from frontier_providers import (
    ClaudeCodeProvider, CodexProvider, PermittedAdapter, _BoundedProvider, route_coverage,
)
from native_transition_broker import NativeTransitionBroker
from test_native_transition_broker import SPEC, FakeCodex, FakeJev, FusedJev, RecoveryJev

JEV_BASIS = {'kind': 'jev_decision', 'decision_id': 'e7', 'choice': 'luna_low',
             'state_hash': 'a' * 64, 'live': True}
OPERATOR = {'kind': 'operator', 'operator': 'local-console', 'reason': 'auth smoke test'}


def scope():
    return {'provider': 'claude', 'model': 'claude-sonnet-5', 'effort': 'low',
            'workspace': '/tmp/w', 'prompt_hash': 'p', 'schema_hash': 's'}


class PermitAuthorityTests(unittest.TestCase):
    def test_permit_is_single_use_and_scope_bound(self):
        authority = PermitAuthority()
        permit = authority.issue('frontier.run', scope(), JEV_BASIS)
        with self.assertRaisesRegex(PermitError, 'permit_scope_mismatch'):
            authority.consume(permit, 'frontier.run', {**scope(), 'model': 'claude-opus-5'})
        with self.assertRaisesRegex(PermitError, 'permit_capability_mismatch'):
            authority.consume(permit, 'mcp.read', scope())
        authority.consume(permit, 'frontier.run', scope())
        with self.assertRaisesRegex(PermitError, 'permit_already_used'):
            authority.consume(permit, 'frontier.run', scope())

    def test_expired_permit_is_rejected(self):
        now = [1000.0]
        authority = PermitAuthority(clock=lambda: now[0])
        permit = authority.issue('frontier.run', scope(), JEV_BASIS, ttl_seconds=5)
        now[0] += 6
        with self.assertRaisesRegex(PermitError, 'permit_expired'):
            authority.consume(permit, 'frontier.run', scope())

    def test_strong_capabilities_need_a_jev_basis(self):
        authority = PermitAuthority()
        for capability in ('mcp.mutate', 'browser.submit_transaction', 'secret.use'):
            with self.assertRaisesRegex(PermitError, 'strong_capability_requires_jev_basis'):
                authority.issue(capability, {'x': 1}, OPERATOR)
        authority.issue('mcp.mutate', {'x': 1}, JEV_BASIS)

    def test_compiled_policy_only_authorizes_fast_path(self):
        authority = PermitAuthority()
        basis = {'kind': 'compiled_policy', 'policy_hash': 'p', 'skill_id': 's',
                 'skill_hash': 'h', 'manifest_hash': 'm'}
        with self.assertRaisesRegex(PermitError, 'compiled_policy_only_authorizes_fast_path'):
            authority.issue('frontier.run', scope(), basis)
        authority.issue('fast_path.execute', {'skill_id': 's'}, basis)

    def test_jev_basis_must_declare_live_or_simulation(self):
        basis = dict(JEV_BASIS)
        basis.pop('live')
        with self.assertRaisesRegex(PermitError, 'jev_basis_must_declare_live_or_simulation'):
            PermitAuthority().issue('frontier.run', scope(), basis)

    def test_ledger_is_hash_chained_and_tamper_evident(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'permits.jsonl'
            authority = PermitAuthority(path)
            permit = authority.issue('frontier.run', scope(), JEV_BASIS)
            authority.consume(permit, 'frontier.run', scope())
            authority.receipt(permit, {'status': 'ok'})
            events = PermitAuthority(path).events()
            self.assertEqual([e['kind'] for e in events],
                             ['permit_issued', 'permit_consumed', 'permit_receipt'])
            self.assertTrue(audit_permit_ledger(events)['valid'])
            lines = path.read_text(encoding='utf-8').splitlines()
            changed = json.loads(lines[1])
            changed['capability'] = 'mcp.mutate'
            lines[1] = json.dumps(changed)
            path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
            with self.assertRaisesRegex(PermitError, 'ledger_hash_mismatch_line_2'):
                PermitAuthority(path)

    def test_audit_detects_missing_receipt_and_foreign_basis(self):
        authority = PermitAuthority()
        basis = {'kind': 'cidm_mesh_dispatch', 'event_id': 'e9', 'gate_id': 'e8', 'action_hash': 'x'}
        permit = authority.issue('frontier.run', scope(), basis)
        authority.consume(permit, 'frontier.run', scope())
        report = audit_permit_ledger(authority.events(), [])
        self.assertFalse(report['valid'])
        self.assertIn('consumed_without_receipt:' + permit, report['issues'])
        self.assertIn('basis_not_in_journal:' + permit, report['issues'])


class FakeRunner:
    def __init__(self, outputs):
        self.outputs, self.argv = outputs, []

    def __call__(self, argv, timeout):
        self.argv.append(argv)
        key = ' '.join(argv[1:])
        stdout = self.outputs.get(key, '')
        return {'ok': key in self.outputs, 'returncode': 0 if key in self.outputs else 1,
                'stdout': stdout, 'stderr': ''}


CATALOGUE = {'models': [
    {'slug': 'gpt-6-luna', 'display_name': 'GPT-6-Luna', 'visibility': 'list',
     'supported_reasoning_levels': [{'effort': e} for e in ('low', 'medium', 'high', 'xhigh')]},
    {'slug': 'gpt-6-sol', 'display_name': 'GPT-6-Sol', 'visibility': 'list',
     'supported_reasoning_levels': [{'effort': e} for e in ('low', 'medium', 'high', 'xhigh')]},
]}
ASTRA_ONLY = {'models': [{'slug': 'gpt-6-astra', 'supported_reasoning_levels': [{'effort': 'low'}]},
                         {'slug': 'gpt-5.6-sol', 'supported_reasoning_levels': [{'effort': 'high'}]}]}


class ProviderTests(unittest.TestCase):
    def test_claude_status_is_redacted_and_flags_api_key_billing(self):
        runner = FakeRunner({'auth status --json': json.dumps({
            'loggedIn': True, 'authMethod': 'claude.ai', 'apiProvider': 'firstParty',
            'email': 'person@example.com', 'orgId': 'org-123', 'subscriptionType': 'pro'})})
        provider = ClaudeCodeProvider(PermitAuthority(), adapter=FakeCodex(), runner=runner,
                                      env={'ANTHROPIC_API_KEY': 'x'})
        status = provider.status()
        self.assertTrue(status['logged_in'])
        self.assertEqual(status['billing'], 'subscription')
        self.assertNotIn('person@example.com', json.dumps(status))
        self.assertNotIn('org-123', json.dumps(status))
        self.assertEqual(len(status['account_ref']), 12)
        self.assertTrue(status['warnings'])

    def test_codex_catalogue_is_account_derived(self):
        runner = FakeRunner({'login status': 'Logged in using ChatGPT',
                             'debug models': json.dumps(CATALOGUE)})
        provider = CodexProvider(PermitAuthority(), adapter=FakeCodex(), runner=runner)
        self.assertEqual(provider.status()['billing'], 'chatgpt_plan')
        models = provider.list_models()
        self.assertTrue(models['account_derived'])
        self.assertEqual([m['slug'] for m in models['models']], ['gpt-6-luna', 'gpt-6-sol'])
        config = RunConfig()
        covered = route_coverage(provider, list(config.worker_routes()),
                                 checker=(config.checker_model, config.checker_effort))
        self.assertEqual(covered['status'], 'covered')

    def test_missing_account_routes_fail_coverage_without_substitution(self):
        provider = CodexProvider(PermitAuthority(), adapter=FakeCodex(),
                                 runner=FakeRunner({'debug models': json.dumps(ASTRA_ONLY)}))
        config = RunConfig()
        coverage = route_coverage(provider, list(config.worker_routes()),
                                  checker=(config.checker_model, config.checker_effort))
        self.assertEqual(coverage['status'], 'unavailable')
        self.assertEqual(len(coverage['missing']), 9)
        self.assertTrue(all(m['reason'] == 'model_not_in_catalogue' for m in coverage['missing']))

    def test_claude_presets_are_never_reported_as_covered(self):
        provider = ClaudeCodeProvider(PermitAuthority(), adapter=FakeCodex(), runner=FakeRunner({}))
        config = RunConfig(worker_family='claude')
        coverage = route_coverage(provider, list(config.worker_routes()),
                                  checker=(config.checker_model, config.checker_effort))
        self.assertEqual(coverage['status'], 'unverified')
        self.assertFalse(coverage['account_derived'])

    def test_provider_run_consumes_permit_and_records_usage(self):
        authority = PermitAuthority()
        provider = ClaudeCodeProvider(authority, adapter=FakeCodex(), runner=FakeRunner({}))
        with tempfile.TemporaryDirectory() as temp:
            request = {'model': 'claude-sonnet-5', 'effort': 'low',
                       'prompt': json.dumps({'role': 'separate Sol-high checker'}),
                       'schema': {'type': 'object'}, 'workspace': temp}
            permit = authority.issue('frontier.run', provider.scope('claude', request), OPERATOR)
            response = provider.run(request, permit)
            self.assertEqual(response['permit_id'], permit)
            usage = provider.usage(response['run_id'])
            self.assertEqual(usage['usage_status'], 'reported')
            with self.assertRaisesRegex(PermitError, 'permit_already_used'):
                provider.run(request, permit)
        self.assertTrue(audit_permit_ledger(authority.events())['valid'])

    def test_cancel_stops_an_in_flight_run(self):
        started = threading.Event()

        class SlowAdapter:
            cancel_event = None

            def run(self, *args):
                started.set()
                for _ in range(200):
                    if self.cancel_event is not None and self.cancel_event.is_set():
                        raise RuntimeError('claude_cancelled')
                    threading.Event().wait(0.01)
                raise AssertionError('not cancelled')

        authority = PermitAuthority()
        provider = ClaudeCodeProvider(authority, adapter=SlowAdapter(), runner=FakeRunner({}))
        with tempfile.TemporaryDirectory() as temp:
            request = {'model': 'claude-sonnet-5', 'effort': 'low', 'prompt': 'x',
                       'schema': {'type': 'object'}, 'workspace': temp}
            permit = authority.issue('frontier.run', provider.scope('claude', request), OPERATOR)
            errors = []
            thread = threading.Thread(target=lambda: errors.append(
                self._capture(provider.run, request, permit)))
            thread.start()
            started.wait(2)
            run_id = next(iter(provider._cancel))
            self.assertTrue(provider.cancel(run_id)['cancelled'])
            thread.join(5)
        self.assertEqual(provider.usage(run_id)['status'], 'cancelled')
        self.assertEqual(provider.cancel('missing')['reason'], 'not_running')

    @staticmethod
    def _capture(fn, *args):
        try:
            return fn(*args)
        except Exception as error:
            return error


class FakeProvider(_BoundedProvider):
    provider_id = 'codex'


class BrokerPermitTests(unittest.TestCase):
    def run_broker(self, judge, gate_policy='legacy', spec=SPEC):
        authority = PermitAuthority()
        provider = FakeProvider(FakeCodex(), authority, executable='codex')
        with tempfile.TemporaryDirectory() as temp:
            broker = NativeTransitionBroker(
                PermittedAdapter(provider, authority), judge, RunConfig(), Path(temp) / 'run',
                gate_policy=gate_policy, permit_authority=authority)
            result = broker.run(spec)
        return result, authority

    def assert_bound(self, result, authority):
        self.assertEqual(result['status'], 'complete')
        self.assertTrue(result['permit_audit']['valid'], result['permit_audit'])
        frontier_calls = [c for c in result['calls'] if c['role'] in ('worker', 'checker')]
        self.assertEqual(result['permit_audit']['consumed'], len(frontier_calls))
        issued = [e for e in authority.events() if e['kind'] == 'permit_issued']
        self.assertTrue(all(e['basis']['kind'] == 'cidm_mesh_dispatch' for e in issued))

    def test_every_legacy_frontier_call_names_its_mesh_dispatch(self):
        self.assert_bound(*self.run_broker(FakeJev(check_unit='hidden2')))

    def test_fused_and_recovery_runs_are_bound(self):
        self.assert_bound(*self.run_broker(FusedJev(check_unit='hidden3'), 'fused'))
        self.assert_bound(*self.run_broker(RecoveryJev(), 'recovery'))

    def test_short_route_uses_host_classification_basis(self):
        from adaptive_run import input_snapshot_hash
        spec = json.loads(json.dumps(SPEC))
        task = {key: spec[key] for key in ('goal', 'sources', 'active_project', 'unresolved_stages')}
        spec['classification'] = {'snapshot_hash': input_snapshot_hash(task, ''),
                                  'rationale': 'One bounded independent checklist request.',
                                  'multiple_steps': False, 'broad_project': False,
                                  'ambiguous': False, 'depends_on_context': False}
        result, authority = self.run_broker(FakeJev(), spec=spec)
        self.assertEqual(result['status'], 'complete')
        issued = [e for e in authority.events() if e['kind'] == 'permit_issued']
        self.assertEqual([e['basis']['kind'] for e in issued], ['host_short_classification'])
        self.assertTrue(result['permit_audit']['valid'])

    def test_cli_route_preflight_fails_closed_before_any_call(self):
        import native_transition_broker as broker_module
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp) / 'run'
            def fake_provider(name, authority, **options):
                return CodexProvider(authority, adapter=FakeCodex(),
                                     runner=FakeRunner({'debug models': json.dumps(ASTRA_ONLY)}))
            argv = ['native_transition_broker.py', '--live', '--task',
                    str(ROOT / 'examples' / 'native-project.request.json'), '--out', str(out)]
            with patch.object(sys, 'argv', argv), patch('frontier_providers.build_provider', fake_provider), \
                    patch('sys.stdout'):
                code = broker_module.main()
            result = json.loads((out / 'result.json').read_text(encoding='utf-8'))
        self.assertEqual(code, 2)
        self.assertEqual(result['status'], 'route_preflight_failed')
        self.assertEqual(result['calls'], [])
        self.assertEqual(result['route_coverage']['status'], 'unavailable')


if __name__ == '__main__':
    unittest.main()
