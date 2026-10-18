"""P0-03 slice 3c fixes: worker artifact contract, applicable hard checks, Claude Jev token budget."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

from config import RunConfig  # noqa: E402
from native_transition_broker import ARTIFACT_CONTRACT, NativeTransitionBroker  # noqa: E402
from test_native_transition_broker import SPEC, FakeCodex, RecoveryJev  # noqa: E402
from test_p0_03_audit import short_spec  # noqa: E402

OUTPUT_ONLY = {'prior_units_resolved', 'output_has_no_unresolved'}


def run(spec, gate_policy):
    tmp = tempfile.TemporaryDirectory()
    codex = FakeCodex()
    broker = NativeTransitionBroker(codex, RecoveryJev(), RunConfig(worker_family='claude'),
                                    Path(tmp.name) / 'run', gate_policy=gate_policy)
    result = broker.run(spec)
    tmp.cleanup()
    return codex, result


class ContractTests(unittest.TestCase):
    def test_every_worker_prompt_states_the_exact_contract(self):
        for spec, policy in ((SPEC, 'recovery'), (short_spec(), 'legacy')):
            with self.subTest(policy=policy):
                codex, result = run(spec, policy)
                self.assertEqual(result['status'], 'complete')
                workers = [data for _, _, data in codex.calls if 'format' in data]
                self.assertTrue(workers)
                for data in workers:
                    self.assertEqual(data['format'], ARTIFACT_CONTRACT)
        for phrase in ('exactly required_parent_hashes', 'are not compared',
                       'assumptions and caveats in claims', 'never hide'):
            self.assertIn(phrase, ARTIFACT_CONTRACT)

    def test_resolution_checks_appear_only_on_the_output_unit(self):
        _, result = run(SPEC, 'recovery')
        decisions = [e for e in result['events'] if e.get('kind') == 'post_worker_decision']
        self.assertTrue(decisions)
        for event in decisions:
            keys = set(event['hard_checks'])
            if event['unit_id'] == 'output':
                self.assertTrue(OUTPUT_ONLY <= keys, event['hard_checks'])
            else:
                self.assertFalse(OUTPUT_ONLY & keys, event['hard_checks'])
            self.assertTrue(all(type(v) is bool for v in event['hard_checks'].values()))

    def test_short_route_keeps_resolution_checks(self):
        _, result = run(short_spec(), 'legacy')
        self.assertTrue(OUTPUT_ONLY <= set(result['hard_checks']))

    def test_unresolved_output_still_blocks_release(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        broker = NativeTransitionBroker(FakeCodex(unresolved_unit='output'), RecoveryJev(),
                                        RunConfig(worker_family='claude'), Path(tmp.name) / 'run',
                                        gate_policy='recovery')
        result = broker.run(SPEC)
        self.assertNotEqual(result['status'], 'complete')
        self.assertIsNone(result['answer'])


class ClaudeJevBudgetTests(unittest.TestCase):
    def test_claude_family_doubles_the_untouched_jev_token_default(self):
        self.assertEqual(RunConfig().max_jev_tokens, 50000)
        self.assertEqual(RunConfig(worker_family='claude').max_jev_tokens, 100000)
        self.assertEqual(RunConfig(worker_family='claude', max_jev_tokens=70000).max_jev_tokens, 70000)

    def test_round_trip_keeps_the_policy_hash(self):
        config = RunConfig(worker_family='claude')
        self.assertEqual(RunConfig.from_dict(json.loads(json.dumps(config.to_dict()))).policy_hash,
                         config.policy_hash)


if __name__ == '__main__':
    unittest.main()
