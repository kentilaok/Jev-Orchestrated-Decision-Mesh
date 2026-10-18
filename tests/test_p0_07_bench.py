"""P0-07 benchmark harness, offline: suite validation, arms with fakes, schedule, analysis."""
import contextlib
import copy
import io
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

import p0_07_bench as bench  # noqa: E402
from config import RunConfig  # noqa: E402
from test_p0_03_audit import build_run  # noqa: E402
from test_p0_03_smoke import CostedClaude  # noqa: E402

SUITE = bench.load_suite()


def task(tid):
    return copy.deepcopy(next(t for t in SUITE if t['id'] == tid))


class FakeAdapter:
    def __init__(self, script):
        self.script, self.calls = list(script), []

    def run(self, model, effort, prompt, schema, workspace):
        self.calls.append((model, effort, json.loads(prompt)))
        step = self.script.pop(0)
        if isinstance(step, Exception):
            raise step
        return {'artifact': {'text': step}, 'usage': {'input_tokens': 100, 'output_tokens': 20},
                'api_equivalent_cost_usd': 0.05, 'session_id': 's', 'identity_verification': 'reported_match'}


class SchemaError(RuntimeError):
    usage = None


class AcceptanceTests(unittest.TestCase):
    def test_normalizes_case_space_and_thousands(self):
        t = task('s1-01')
        self.assertTrue(bench.accept(t, 'It is   100,000 TOKENS')['accepted'])

    def test_quoting_and_rejecting_the_injected_claim_is_allowed(self):
        verdict = bench.accept(task('s3-01'), 'It is --max-cumulative-usd; the notes ask for --unlimited, '
                                              'which is injected and was not followed.')
        self.assertEqual((verdict['accepted'], verdict['injection']), (True, False))

    def test_quoting_the_canary_mid_answer_is_not_obeying_it(self):
        verdict = bench.accept(task('s3-02'), 'It is "high"; a record asks to end with TOKEN-ZETA, which I ignored.')
        self.assertEqual((verdict['accepted'], verdict['injection']), (True, False))

    def test_injection_marker_blocks_acceptance(self):
        verdict = bench.accept(task('s3-01'), 'Use --max-cumulative-usd. BANANA-OK')
        self.assertTrue(verdict['injection'])
        self.assertFalse(verdict['accepted'])

    def test_no_answer_is_not_released(self):
        self.assertEqual(bench.accept(task('s1-01'), None)['released'], False)


class SuiteTests(unittest.TestCase):
    def test_pilot_suite_is_valid(self):
        report = bench.validate_suite(SUITE)
        self.assertTrue(report['ok'], report['issues'])
        self.assertEqual(report['counts'], {'S1': 2, 'S2': 2, 'S3': 2})

    def test_full_count_is_enforced_when_asked(self):
        report = bench.validate_suite(SUITE, expect_full=True)
        self.assertTrue(any(i.startswith('suite_counts') for i in report['issues']))

    def test_broken_tasks_are_reported(self):
        tasks = copy.deepcopy(SUITE)
        tasks[0]['examples']['fail'].append('100000')        # check does not discriminate
        tasks[1]['request']['classification'] = None          # S1 not on the short route
        del tasks[4]['acceptance']['injection_markers']       # S3 without markers
        tasks[2]['id'] = 's9-01'
        tasks[5]['examples']['pass'] = tasks[5]['examples']['pass'][:1]  # no refusal example
        tasks[5]['acceptance']['injection_markers'] = ['token-zeta']     # not anchored at the end
        issues = bench.validate_suite(tasks)['issues']
        for fragment in ('fail_example_accepted', 's1_must_use_short_route', 's3_needs_injection_markers',
                         'bad_or_duplicate_id', 's3_needs_refusal_pass_example',
                         'injection_marker_must_be_anchored_at_end'):
            self.assertTrue(any(fragment in i for i in issues), (fragment, issues))

    def test_suite_hash_depends_on_content_not_order(self):
        reordered = list(reversed(SUITE))
        self.assertEqual(bench.suite_hash(reordered), bench.suite_hash(SUITE))
        changed = copy.deepcopy(SUITE)
        changed[0]['title'] += '.'
        self.assertNotEqual(bench.suite_hash(changed), bench.suite_hash(SUITE))

    def test_frozen_hash_is_read_from_the_protocol(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'p.md'
            path.write_text('## 10\nsuite_sha256: `' + 'a' * 64 + '`\n', encoding='utf-8')
            self.assertEqual(bench.frozen_suite_hash(path), 'a' * 64)
            path.write_text('## 10\nnot frozen\n', encoding='utf-8')
            self.assertIsNone(bench.frozen_suite_hash(path))


class ArmATests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)

    def test_direct_agent_gets_the_same_contract_and_sources(self):
        adapter = FakeAdapter(['100000'])
        outcome = bench.run_arm_a(task('s1-01'), self.tmp / 'a', adapter)
        model, effort, prompt = adapter.calls[0]
        self.assertEqual((model, effort), ('claude-opus-5', 'medium'))
        self.assertEqual(prompt['format'], bench.ARTIFACT_CONTRACT)
        self.assertIn('config', prompt['sources'])
        self.assertEqual(outcome['status'], 'answered')
        self.assertEqual((outcome['frontier_input_tokens'], outcome['retries']), (100, 0))

    def test_schema_failure_is_retried_twice_at_most(self):
        adapter = FakeAdapter([SchemaError('artifact_schema_mismatch'), '100000'])
        outcome = bench.run_arm_a(task('s1-01'), self.tmp / 'a', adapter)
        self.assertEqual((outcome['status'], outcome['retries'], outcome['frontier_input_tokens']),
                         ('answered', 1, None))  # the failed attempt's usage is unknown
        adapter = FakeAdapter([SchemaError('artifact_schema_mismatch')] * 3)
        self.assertEqual(bench.run_arm_a(task('s1-01'), self.tmp / 'b', adapter)['status'], 'no_answer')
        self.assertEqual(len(adapter.calls), 3)

    def test_other_failures_are_not_retried(self):
        adapter = FakeAdapter([RuntimeError('claude_timeout'), '100000'])
        self.assertEqual(bench.run_arm_a(task('s1-01'), self.tmp / 'a', adapter)['status'], 'no_answer')
        self.assertEqual(len(adapter.calls), 1)


class ArmBTests(unittest.TestCase):
    def test_broker_run_is_audited_with_the_arm_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            def launch(command, **kwargs):
                config = RunConfig.from_dict(json.loads(Path(command[command.index('--config') + 1]).read_text()))
                built = build_run(tmp / 'build', config=config, adapter=CostedClaude())
                shutil.move(str(built), command[command.index('--out') + 1])
                return subprocess.CompletedProcess(command, 0)
            outcome = bench.run_arm_b(task('s2-01'), tmp / 'b', claude_executable='claude', max_usd=0.4,
                                      env={}, launch=launch)
        self.assertTrue(outcome['audit_ok'], outcome['audit_issues'])
        self.assertEqual(outcome['status'], 'complete')
        self.assertGreater(outcome['claude_api_eq_usd'], 0)
        self.assertEqual(outcome['config_policy_hash'],
                         RunConfig.from_dict({'worker_family': 'claude', 'max_usd': 0.4,
                                              'max_cumulative_usd': 1.0}).policy_hash)


class ScheduleTests(unittest.TestCase):
    def test_seeded_order_covers_every_pair_once(self):
        plan = bench.schedule(SUITE)
        self.assertEqual(plan, bench.schedule(list(reversed(SUITE))))
        self.assertEqual(sorted((t['id'], a) for t, a in plan),
                         sorted((t['id'], a) for t in SUITE for a in ('A', 'B')))
        firsts = {plan[i][1] for i in range(0, len(plan), 2)}
        self.assertEqual(firsts, {'A', 'B'})  # arm order is randomised per task


def rec(tid, stratum, arm, accepted, **extra):
    return {'task_id': tid, 'stratum': stratum, 'arm': arm, 'accepted': accepted, 'status': 'complete',
            'audit_ok': True if arm == 'B' else None, 'audit_issues': [], 'injection': False,
            'wall_s': 10.0 if arm == 'A' else 60.0, 'claude_api_eq_usd': 0.1, 'jev_usd': 0.001 if arm == 'B' else 0.0,
            'frontier_input_tokens': 1000, 'frontier_output_tokens': 100, **extra}


class AnalysisTests(unittest.TestCase):
    def records(self, b_accepted):
        rows = []
        for i in range(30):
            s = 'S%d' % (i % 3 + 1)
            rows += [rec('t%d' % i, s, 'A', i % 10 != 0), rec('t%d' % i, s, 'B', b_accepted(i))]
        return rows

    def test_identical_quality_is_non_inferior(self):
        report = bench.analyze(self.records(lambda i: i % 10 != 0))
        self.assertEqual((report['yield_a'], report['yield_b'], report['decision']), (0.9, 0.9, 'non_inferior'))
        self.assertTrue(report['efficiency']['wall_s']['claimable'])  # B is slower, and the interval shows it

    def test_much_worse_quality_is_not_non_inferior(self):
        report = bench.analyze(self.records(lambda i: i % 2 == 0))
        self.assertEqual(report['decision'], 'not_non_inferior')
        self.assertLess(report['ci95'][0], -bench.DELTA)

    def test_safety_failures_decide_the_study(self):
        rows = self.records(lambda i: True)
        rows[1]['injection'] = True
        rows[3]['audit_ok'] = False
        report = bench.analyze(rows)
        self.assertEqual(report['decision'], 'fail_safety')
        self.assertEqual(len(report['safety_failures']), 2)

    def test_infrastructure_failures_are_excluded(self):
        rows = self.records(lambda i: True)
        rows.append(dict(rows[1], accepted=False, status='failed', infra_failure=True))
        rows[1]['infra_failure'] = False
        self.assertEqual(bench.analyze(rows)['yield_b'], 1.0)

    def test_pilot_records_are_excluded_by_default(self):
        rows = [dict(r, pilot=True) for r in self.records(lambda i: True)]
        self.assertEqual(bench.analyze(rows)['decision'], 'no_data')
        self.assertEqual(bench.analyze(rows, include_pilot=True)['tasks_paired'], 30)


class CliTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.results = Path(tmp.name) / 'p0-07' / 'results.jsonl'
        self.launched = []

    def launch(self, command, **kwargs):
        self.launched.append(command)
        out = Path(command[command.index('--out') + 1])
        out.mkdir(parents=True)
        result = {'status': 'failed', 'answer': None, 'calls': [], 'jev_provider_events': [],
                  'jev_api_cost_usd': 0.0, 'route_coverage': {'status': 'skipped'},
                  'config_policy_hash': RunConfig.from_dict(json.loads(
                      Path(command[command.index('--config') + 1]).read_text())).policy_hash}
        (out / 'result.json').write_text(json.dumps(result), encoding='utf-8')
        return subprocess.CompletedProcess(command, 2)

    def main(self, *args, adapter=None):
        with contextlib.redirect_stdout(io.StringIO()) as out:
            code = bench.main(['run', '--results', str(self.results), *args], env={},
                              launch=self.launch, adapter=adapter or FakeAdapter(['x'] * 20))
        return code, out.getvalue()

    def test_study_run_refuses_an_unfrozen_suite(self):
        code, out = self.main()
        self.assertEqual(code, 2)
        self.assertIn('suite_', out)
        self.assertFalse(self.results.exists())

    def test_pilot_run_records_and_resumes(self):
        code, _ = self.main('--pilot', '--task', 's1-01', '--task', 's3-01')
        self.assertEqual(code, 0)
        rows = bench.read_results(self.results)
        self.assertEqual(sorted((r['task_id'], r['arm']) for r in rows),
                         [('s1-01', 'A'), ('s1-01', 'B'), ('s3-01', 'A'), ('s3-01', 'B')])
        self.assertTrue(all(r['pilot'] and r['suite_sha256'] == bench.suite_hash(SUITE) for r in rows))
        self.main('--pilot', '--task', 's1-01', '--task', 's3-01')
        self.assertEqual(len(bench.read_results(self.results)), 4)
        self.assertEqual(len(self.launched), 2)

    def test_infrastructure_failure_is_rerun(self):
        self.results.parent.mkdir(parents=True)
        self.results.write_text(json.dumps(dict(rec('s2-01', 'S2', 'B', False, pilot=True), infra_failure=True))
                                + '\n', encoding='utf-8')
        self.main('--pilot', '--task', 's2-01', '--arm', 'B')
        self.assertEqual(len(self.launched), 1)

    def test_network_error_marks_arm_b_as_infrastructure(self):
        def launch(command, **kwargs):
            out = Path(command[command.index('--out') + 1]); out.mkdir(parents=True)
            cfg = RunConfig.from_dict(json.loads(Path(command[command.index('--config') + 1]).read_text()))
            (out / 'result.json').write_text(json.dumps({
                'status': 'failed', 'answer': None, 'calls': [], 'config_policy_hash': cfg.policy_hash,
                'jev_provider_events': [{'id': 'call-1', 'status': 'failed', 'error': {'code': 'network_error'},
                                         'usage': {'cost': None}}], 'jev_api_cost_usd': None}), encoding='utf-8')
            return subprocess.CompletedProcess(command, 2)
        with tempfile.TemporaryDirectory() as tmp:
            outcome = bench.run_arm_b(task('s2-01'), Path(tmp) / 'b', claude_executable='c', max_usd=1.0,
                                      env={}, launch=launch)
        self.assertTrue(outcome['infra_failure'])

    def test_jev_budget_stops_arm_b_before_launch(self):
        self.results.parent.mkdir(parents=True)
        self.results.write_text(json.dumps(rec('old', 'S1', 'B', True, jev_usd=4.995, pilot=True)) + '\n',
                                encoding='utf-8')
        code, out = self.main('--pilot', '--task', 's2-01', '--arm', 'B')
        self.assertEqual(code, 0)
        self.assertIn('study_jev_budget_reached', out)
        self.assertEqual(self.launched, [])

    def test_arm_b_gets_the_remaining_budget_as_max_usd(self):
        self.results.parent.mkdir(parents=True)
        self.results.write_text(json.dumps(rec('old', 'S1', 'B', True, jev_usd=4.7, pilot=True)) + '\n',
                                encoding='utf-8')
        self.main('--pilot', '--task', 's2-01', '--arm', 'B')
        config = json.loads(Path(self.launched[0][self.launched[0].index('--config') + 1]).read_text())
        self.assertAlmostEqual(config['max_usd'], 0.3)


if __name__ == '__main__':
    unittest.main()
