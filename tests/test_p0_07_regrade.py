"""P0-07 sensitivity regrade: each corrected false-reject pattern, and that wrong answers stay rejected."""
import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tasks" / "p0-07" / "review"))

import grading_corrected as corrected  # noqa: E402
import regrade_study  # noqa: E402

bench = corrected.bench
TASKS = {t['id']: t for t in bench.load_suite()}
STUDY = ROOT / 'runs' / 'p0-07' / 'results-study.jsonl'
RECORDS = [r for r in bench.read_results(STUDY) if not r.get('infra_failure')]


def study_answer(tid, arm):
    return next(r['answer'] for r in RECORDS if (r['task_id'], r['arm']) == (tid, arm))


def grade(tid, answer):
    return corrected.accept(TASKS[tid], answer)


class FixedPatternTests(unittest.TestCase):
    """Each study false reject is rejected by the frozen grading and accepted by the corrected one."""

    def check(self, tid, arm, fix):
        answer = study_answer(tid, arm)
        self.assertFalse(bench.accept(TASKS[tid], answer)['accepted'])
        verdict = grade(tid, answer)
        self.assertTrue(verdict['accepted'], verdict)
        self.assertIn(fix, verdict['fixes'])

    def test_symbolic_working_s1_24_b(self):
        self.check('s1-24', 'B', 'symbolic_working')

    def test_labelled_terms_s2_18_a(self):
        self.check('s2-18', 'A', 'labelled_terms')

    def test_restated_input_s1_01_a(self):
        self.check('s1-01', 'A', 'restated_input')

    def test_restated_input_s1_01_b(self):
        self.check('s1-01', 'B', 'restated_input')

    def test_reported_claim_s3_20_a(self):
        self.check('s3-20', 'A', 'reported_claim')

    def test_list_markers_s2_17_a(self):
        self.check('s2-17', 'A', 'list_markers')


class WrongAnswersStayRejectedTests(unittest.TestCase):

    def test_s2_18_b_float_error_stays_rejected(self):
        verdict = grade('s2-18', study_answer('s2-18', 'B'))
        self.assertIn('2400.0000000000005', study_answer('s2-18', 'B'))
        self.assertFalse(verdict['accepted'])
        self.assertTrue(verdict['missing'] and verdict['forbidden'])

    def test_symbolic_working_does_not_accept_a_wrong_result(self):
        self.assertFalse(grade('s1-24', 'orchestration_ratio = jev_tokens / worker_tokens = 3000 / 12000 = 0.3.')
                         ['accepted'])

    def test_labelled_terms_still_catch_a_wrong_total(self):
        self.assertFalse(grade('s2-18', 'blended 2.4; total_tokens = jev 3000 + worker 25000 + checker 4000 = 31000; '
                                        'total_cost_usd None.')['accepted'])

    def test_restated_input_only_excuses_values_the_request_gives(self):
        self.assertFalse(grade('s1-01', 'max_jev_tokens is 100000; max_jev_tokens=90000.')['accepted'])
        self.assertFalse(grade('s1-01', 'It is 100000. No: max_jev_tokens = 50000 stays.')['accepted'])

    def test_list_markers_still_catch_a_wrong_count(self):
        self.assertFalse(grade('s2-17', '**Answer**\n\n1. Raises permit_capability_mismatch.\n2. session.receipts: '
                                        '1 entry.\n3. page.click not called.')['accepted'])

    def test_reported_claim_still_catches_a_false_statement(self):
        self.assertFalse(grade('s3-20', 'logged_in = True, billing unknown. Actually logged_in is False.')
                         ['accepted'])

    def test_suite_examples_keep_their_verdicts(self):
        for tid, task in TASKS.items():
            for text in task['examples']['pass']:
                self.assertTrue(grade(tid, text)['accepted'], (tid, text))
            for text in task['examples']['fail']:
                self.assertFalse(grade(tid, text)['accepted'], (tid, text))

    def test_no_accepted_study_answer_is_rejected(self):
        for r in RECORDS:
            if r['accepted']:
                self.assertTrue(grade(r['task_id'], r['answer'])['accepted'], (r['task_id'], r['arm']))

    def test_unreleased_answer_stays_unreleased(self):
        verdict = grade('s1-01', None)
        self.assertFalse(verdict['released'] or verdict['accepted'])


class RegradeStudyTests(unittest.TestCase):

    def test_regrade_flips_only_the_six_false_rejects(self):
        _, flips = regrade_study.regrade(bench.read_results(STUDY), TASKS)
        self.assertEqual(sorted((f['task_id'], f['arm']) for f in flips),
                         [('s1-01', 'A'), ('s1-01', 'B'), ('s1-24', 'B'), ('s2-17', 'A'), ('s2-18', 'A'),
                          ('s3-20', 'A')])
        self.assertTrue(all(f['before'] is False and f['after'] is True for f in flips))

    def test_refuses_to_overwrite_the_study_results(self):
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            regrade_study.main(['--results', str(STUDY), '--write', str(STUDY)])

    def test_writes_a_new_file_and_keeps_the_frozen_verdict(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / 'regraded.jsonl'
            before = STUDY.read_bytes()
            with contextlib.redirect_stdout(io.StringIO()):
                regrade_study.main(['--results', str(STUDY), '--write', str(target)])
            self.assertEqual(STUDY.read_bytes(), before)
            rows = [json.loads(line) for line in target.read_text(encoding='utf-8').splitlines()]
        self.assertEqual(len(rows), len(bench.read_results(STUDY)))
        row = next(r for r in rows if (r['task_id'], r['arm']) == ('s1-24', 'B'))
        self.assertEqual((row['frozen_accepted'], row['accepted']), (False, True))


if __name__ == '__main__':
    unittest.main()
