"""Arsenal Phase C: MCP discovery, compact catalogue, permit-bound calls (offline)."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'tests'))

from capability_permits import PermitAuthority, PermitError, audit_permit_ledger
from config import RunConfig
from mcp_registry import (
    McpCatalog, McpEvidenceRetriever, StdioMcpClient, call_tool, discover_servers, permit_scope,
    public_spec,
)
from native_transition_broker import NativeTransitionBroker
from test_native_transition_broker import SPEC, FakeCodex

FAKE = ROOT / 'tests' / 'fixtures' / 'fake_mcp_server.py'
SPEC_FAKE = {'name': 'Roblox_Studio_test', 'source': 'test', 'transport': 'stdio',
             'command': sys.executable, 'args': ['-B', str(FAKE)], 'url': None, '_env': {},
             'env_keys': [], 'inherit_env': []}
JEV = {'kind': 'jev_decision', 'decision_id': 'e1', 'choice': 'x', 'state_hash': 'a' * 64, 'live': True}


def stdio_factory(spec):
    return StdioMcpClient(spec['command'], spec['args'], timeout=20)


class DiscoveryTests(unittest.TestCase):
    def test_reads_configs_without_exposing_env_values(self):
        with tempfile.TemporaryDirectory() as temp:
            home, project = Path(temp) / 'home', Path(temp) / 'project'
            (home / '.codex').mkdir(parents=True)
            project.mkdir()
            (project / '.mcp.json').write_text(json.dumps({'mcpServers': {
                'docs': {'command': 'docs-mcp', 'args': ['--ro'], 'env': {'DOCS_TOKEN': 'secret-value'}}}}),
                encoding='utf-8')
            (home / '.claude.json').write_text(json.dumps({
                'mcpServers': {'remote': {'type': 'http', 'url': 'https://mcp.example.test/mcp'}},
                'projects': {str(project.resolve()): {'mcpServers': {'local': {'command': 'x'}}}}}),
                encoding='utf-8')
            (home / '.codex' / 'config.toml').write_text(
                '[mcp_servers.studio]\ncommand = "cmd.exe"\nargs = ["/c", "mcp.bat"]\n', encoding='utf-8')
            servers = {s['name']: s for s in discover_servers(project_dir=project, home=home)}
        try:
            import tomllib  # noqa: F401  (Python 3.11+; 3.10 skips Codex TOML configs)
            expected = {'docs', 'remote', 'local', 'studio'}
        except ModuleNotFoundError:
            expected = {'docs', 'remote', 'local'}
        self.assertEqual(set(servers), expected)
        self.assertEqual(servers['remote']['transport'], 'http')
        public = json.dumps([public_spec(s) for s in servers.values()])
        self.assertNotIn('secret-value', public)
        self.assertIn('DOCS_TOKEN', public)


class CatalogueTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.catalog = McpCatalog(Path(self.temp.name) / 'mcp.db')
        with stdio_factory(SPEC_FAKE) as client:
            client.initialize()
            self.tools = client.list_tools()
        self.report = self.catalog.ingest(SPEC_FAKE, self.tools)

    def tearDown(self):
        self.catalog.db.close()
        self.temp.cleanup()

    def test_stdio_client_paginates_and_classifies_conservatively(self):
        self.assertEqual(len(self.tools), 6)
        access = {t['name']: self.catalog.access('Roblox_Studio_test', t['name'])[0] for t in self.tools}
        self.assertEqual(access, {'list_roblox_studios': 'read', 'script_read': 'read',
                                  'execute_luau': 'mutate', 'lookup_ticket': 'read',
                                  'close_ticket': 'mutate', 'mystery': 'unknown'})

    def test_search_returns_compact_cards_and_measures_bytes_avoided(self):
        result = self.catalog.search('read script source', top_k=2)
        self.assertEqual(result['cards'][0]['tool'], 'script_read')
        self.assertNotIn('input_schema', result['cards'][0])
        budget = result['context_budget']
        self.assertEqual(budget['full_catalogue_tools'], 6)
        self.assertLess(budget['returned_bytes'], budget['full_catalogue_bytes'])
        only_read = self.catalog.search('ticket', access='read')
        self.assertEqual([c['tool'] for c in only_read['cards']], ['lookup_ticket'])

    def test_owner_override_and_block(self):
        self.catalog.set_access('Roblox_Studio_test', 'mystery', 'blocked', 'owner')
        self.assertEqual(self.catalog.access('Roblox_Studio_test', 'mystery'),
                         ('blocked', 'owner_override:owner'))
        authority = PermitAuthority()
        with self.assertRaisesRegex(Exception, 'mcp_tool_blocked_by_owner'):
            call_tool(self.catalog, SPEC_FAKE, 'mystery', {}, 'none', authority, client_factory=stdio_factory)

    def test_read_call_is_permit_bound_and_receipted(self):
        authority = PermitAuthority()
        args = {'path': 'ServerScriptService.Movement'}
        card = self.catalog.describe('Roblox_Studio_test', 'script_read')
        scope = permit_scope('Roblox_Studio_test', 'script_read', args, 'read', card['schema_hash'])
        permit = authority.issue('mcp.read', scope, {'kind': 'operator', 'operator': 'o', 'reason': 'inspect'})
        with tempfile.TemporaryDirectory() as evidence:
            outcome = call_tool(self.catalog, SPEC_FAKE, 'script_read', args, permit, authority,
                                client_factory=stdio_factory, evidence_dir=Path(evidence))
            self.assertTrue(Path(outcome['receipt']['full_result_ref']).exists())
        self.assertEqual(outcome['receipt']['status'], 'ok')
        self.assertIn('WalkSpeed', outcome['source']['text'])
        self.assertTrue(audit_permit_ledger(authority.events())['valid'])
        with self.assertRaisesRegex(PermitError, 'permit_already_used'):
            call_tool(self.catalog, SPEC_FAKE, 'script_read', args, permit, authority, client_factory=stdio_factory)

    def test_permit_cannot_be_reused_for_other_arguments(self):
        authority = PermitAuthority()
        card = self.catalog.describe('Roblox_Studio_test', 'script_read')
        scope = permit_scope('Roblox_Studio_test', 'script_read', {'path': 'A'}, 'read', card['schema_hash'])
        permit = authority.issue('mcp.read', scope, JEV)
        with self.assertRaisesRegex(PermitError, 'permit_scope_mismatch'):
            call_tool(self.catalog, SPEC_FAKE, 'script_read', {'path': 'B'}, permit, authority,
                      client_factory=stdio_factory)

    def test_mutating_and_unknown_tools_need_strong_permits(self):
        authority = PermitAuthority()
        card = self.catalog.describe('Roblox_Studio_test', 'execute_luau')
        scope = permit_scope('Roblox_Studio_test', 'execute_luau', {'code': 'x'}, 'mutate', card['schema_hash'])
        with self.assertRaisesRegex(PermitError, 'strong_capability_requires_jev_basis'):
            authority.issue('mcp.mutate', scope, {'kind': 'operator', 'operator': 'o', 'reason': 'r'})
        read_permit = authority.issue('mcp.read', scope, JEV)
        with self.assertRaisesRegex(PermitError, 'permit_capability_mismatch'):
            call_tool(self.catalog, SPEC_FAKE, 'execute_luau', {'code': 'x'}, read_permit, authority,
                      client_factory=stdio_factory)

    def test_arguments_are_checked_against_the_schema(self):
        authority = PermitAuthority()
        for args, code in (({}, 'mcp_missing_required_arguments'),
                           ({'path': 'A', 'extra': 1}, 'mcp_unexpected_arguments'),
                           ({'path': 3}, 'mcp_argument_type_mismatch')):
            with self.assertRaisesRegex(PermitError, code):
                call_tool(self.catalog, SPEC_FAKE, 'script_read', args, 'p', authority,
                          client_factory=stdio_factory)

    def test_large_results_are_truncated_into_a_bounded_source(self):
        authority = PermitAuthority()
        card = self.catalog.describe('Roblox_Studio_test', 'lookup_ticket')
        scope = permit_scope('Roblox_Studio_test', 'lookup_ticket', {'id': 7}, 'read', card['schema_hash'])
        permit = authority.issue('mcp.read', scope, JEV)
        outcome = call_tool(self.catalog, SPEC_FAKE, 'lookup_ticket', {'id': 7}, permit, authority,
                            client_factory=stdio_factory)
        self.assertTrue(outcome['receipt']['truncated'])
        self.assertLessEqual(len(outcome['source']['text']), 1200)

    def test_evidence_plan_rejects_non_read_tools(self):
        with self.assertRaisesRegex(PermitError, 'evidence_plan_requires_read_only_tool'):
            McpEvidenceRetriever(self.catalog, {'Roblox_Studio_test': SPEC_FAKE}, PermitAuthority(),
                                 [{'server': 'Roblox_Studio_test', 'tool': 'mystery', 'arguments': {}}])


class EvidenceJev:
    """Asks for evidence once at Interpret, then forwards when the new source exists."""

    def __init__(self):
        self.calls = []

    def __call__(self, phase, options, state):
        self.calls.append((phase, copy.deepcopy(options), copy.deepcopy(state)))
        if phase == 'authorize_unit':
            choice = 'compute' if 'compute' in options else 'luna_low'
        elif phase == 'after_worker':
            has_evidence = any(entry['id'].startswith('mcp-') for entry in state['source_manifest'])
            if state['unit']['id'] == 'hidden1' and not has_evidence:
                choice = 'retrieve_evidence'
            else:
                choice = 'forward'
        else:
            raise AssertionError(phase)
        return {'choice': choice, 'model': 'typesafe/jev-1.13-20260917', 'live': True,
                'usage': {'input_tokens': 25, 'output_tokens': 5, 'cost': 0.000001}}


class RecoveryEvidenceTests(unittest.TestCase):
    def test_retrieve_evidence_becomes_a_read_and_a_fresh_jev_gate(self):
        with tempfile.TemporaryDirectory() as temp:
            catalog = McpCatalog(Path(temp) / 'mcp.db')
            with stdio_factory(SPEC_FAKE) as client:
                client.initialize()
                catalog.ingest(SPEC_FAKE, client.list_tools())
            authority = PermitAuthority()
            retriever = McpEvidenceRetriever(
                catalog, {'Roblox_Studio_test': SPEC_FAKE}, authority,
                [{'server': 'Roblox_Studio_test', 'tool': 'script_read',
                  'arguments': {'path': 'ServerScriptService.Movement'}, 'title': 'Movement script'}],
                client_factory=stdio_factory)
            judge = EvidenceJev()
            codex = FakeCodex()
            broker = NativeTransitionBroker(codex, judge, RunConfig(), Path(temp) / 'run',
                                            gate_policy='recovery', evidence_retriever=retriever)
            result = broker.run(SPEC)
            catalog.db.close()
        self.assertEqual(result['status'], 'complete', result.get('status'))
        added = [e for e in result['events'] if e['kind'] == 'recovery_evidence_added']
        self.assertEqual(len(added), 1)
        new_id = added[0]['added'][0]['id']
        self.assertTrue(new_id.startswith('mcp-scriptread-'))
        self.assertIn(new_id, result['source_hashes'])
        # The worker prompt after retrieval carries the new evidence.
        later_prompts = [data for _, _, data in codex.calls if new_id in data.get('sources', {})]
        self.assertTrue(later_prompts)
        self.assertEqual(result['evidence_receipts'][0]['status'], 'ok')
        self.assertTrue(result['audit']['valid'])
        self.assertTrue(audit_permit_ledger(authority.events())['valid'])

    def test_retriever_requires_recovery_policy(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(Exception):
                NativeTransitionBroker(FakeCodex(), EvidenceJev(), RunConfig(), Path(temp) / 'r',
                                       gate_policy='legacy', evidence_retriever=lambda packet: None)


if __name__ == '__main__':
    unittest.main()
