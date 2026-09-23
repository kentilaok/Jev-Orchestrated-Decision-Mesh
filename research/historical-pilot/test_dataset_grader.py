"""Meaningful regression tests for data freezing and blinded scoring."""
import copy
import json
import unittest

import dataset
import grader


def perfect(task_gold):
    return {
        'answers': copy.deepcopy(task_gold['answers']),
        'evidence': {field: list(dict.fromkeys(group[0] for group in spec['groups'])) for field, spec in task_gold['evidence'].items()},
        'status': task_gold['status'],
    }


class DatasetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tasks, cls.gold = dataset.generate()

    def test_reproducible_and_valid(self):
        again = dataset.generate()
        self.assertEqual(dataset.serialized(self.tasks), dataset.serialized(again[0]))
        self.assertEqual(dataset.serialized(self.gold), dataset.serialized(again[1]))
        dataset.validate_dataset(self.tasks, self.gold)

    def test_gold_never_embedded_in_tasks(self):
        for task in self.tasks['tasks']:
            self.assertNotIn('answers', task)
            self.assertNotIn('evidence', task)
            self.assertNotIn('features', task)

    def test_long_complete_dependency_case_needs_every_document(self):
        task = next(t for t in self.tasks['tasks'] if t['id'] == 'E-C04')
        gold = self.gold['tasks'][task['id']]
        cited = {s for spec in gold['evidence'].values() for group in spec['groups'] for s in group}
        self.assertEqual(cited, {d['id'] for d in task['documents']})
        self.assertEqual(len(cited), 16)
        self.assertEqual(gold['answers']['known_subtotal_credits'], 345)
        self.assertEqual(gold['answers']['total_units'], 108)


class GraderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tasks, cls.gold = dataset.generate()

    def case(self, task_id='E-C01'):
        gold = self.gold['tasks'][task_id]
        return gold, perfect(gold)

    def test_every_perfect_response_passes(self):
        for task_id, gold in self.gold['tasks'].items():
            with self.subTest(task=task_id):
                score = grader.grade_response(gold, json.dumps(perfect(gold)))
                self.assertTrue(score['task_pass'], score)
                self.assertEqual(score['joint_field_accuracy'], 1)

    def test_omitted_region_cap_caveat_fails(self):
        gold, response = self.case()
        response['answers'].update(effective_workers=14, execution_slots=42, cap_applied='no')
        score = grader.grade_response(gold, response)
        self.assertFalse(score['task_pass'])
        self.assertEqual(score['answer_accuracy'], 0.25)

    def test_correct_number_without_cap_source_fails(self):
        gold, response = self.case()
        response['evidence']['effective_workers'].pop(2)
        score = grader.grade_response(gold, response)
        self.assertTrue(score['fields']['effective_workers']['answer_correct'])
        self.assertFalse(score['fields']['effective_workers']['evidence_correct'])
        self.assertFalse(score['task_pass'])

    def test_unrelated_citation_fails_even_with_all_support(self):
        gold, response = self.case()
        response['evidence']['effective_workers'].append('D-NOT-A-SOURCE')
        score = grader.grade_response(gold, response)
        self.assertFalse(score['fields']['effective_workers']['evidence_correct'])

    def test_legitimate_extra_support_is_allowed(self):
        gold, response = self.case('E-N03')
        response['evidence']['selected_revision'] = gold['evidence']['selected_revision']['allowed']
        self.assertTrue(grader.grade_response(gold, response)['task_pass'])
        gold, response = self.case('E-C04')
        response['evidence']['known_subtotal_credits'] = gold['evidence']['known_subtotal_credits']['allowed']
        self.assertTrue(grader.grade_response(gold, response)['task_pass'])

    def test_missing_field_fails_and_is_not_null_credit(self):
        gold, response = self.case('E-C03')
        del response['answers']['endpoint']
        score = grader.grade_response(gold, response)
        self.assertFalse(score['schema_valid'])
        self.assertFalse(score['fields']['endpoint']['answer_correct'])

    def test_numeric_string_and_boolean_fail(self):
        gold, response = self.case()
        for wrong in ['12', True]:
            response['answers']['effective_workers'] = wrong
            score = grader.grade_response(gold, response)
            self.assertFalse(score['fields']['effective_workers']['answer_correct'])
            self.assertFalse(score['schema_valid'])

    def test_equivalent_json_number_is_accepted(self):
        gold, response = self.case()
        response['answers']['effective_workers'] = 12.0
        self.assertTrue(grader.grade_response(gold, response)['task_pass'])

    def test_contradiction_requires_both_sheets_and_null(self):
        gold, response = self.case('E-C03')
        response['answers']['endpoint'] = 'cedar'
        response['status'] = 'complete'
        self.assertFalse(grader.grade_response(gold, response)['task_pass'])
        response = perfect(gold)
        response['evidence']['endpoint'].pop()
        self.assertFalse(grader.grade_response(gold, response)['task_pass'])

    def test_missing_price_cannot_be_zero_or_historical_guess(self):
        gold, response = self.case('E-C04')
        for guessed_total in [345, 506]:
            response['answers']['full_total_credits'] = guessed_total
            response['status'] = 'complete'
            score = grader.grade_response(gold, response)
            self.assertFalse(score['fields']['full_total_credits']['answer_correct'])
            self.assertFalse(score['task_pass'])

    def test_wrong_status_duplicate_citation_and_extra_field_fail(self):
        gold, response = self.case()
        response['status'] = 'partial'
        self.assertFalse(grader.grade_response(gold, response)['task_pass'])
        response = perfect(gold)
        response['evidence']['effective_workers'] *= 2
        self.assertFalse(grader.grade_response(gold, response)['schema_valid'])
        response = perfect(gold)
        response['answers']['bonus'] = 'shotgun'
        self.assertFalse(grader.grade_response(gold, response)['schema_valid'])

    def test_or_groups_are_alternatives_and_groups_are_conjunctive(self):
        gold = {'answers': {'x': 2}, 'evidence': {'x': {'groups': [['A', 'B'], ['C']], 'allowed': ['A', 'B', 'C']}}, 'status': 'complete'}
        response = {'answers': {'x': 2}, 'evidence': {'x': ['B', 'C']}, 'status': 'complete'}
        self.assertTrue(grader.grade_response(gold, response)['task_pass'])
        response['evidence']['x'] = ['A', 'B']
        self.assertFalse(grader.grade_response(gold, response)['task_pass'])

    def test_malformed_json_nonfinite_and_duplicate_key_rejected(self):
        gold, _ = self.case()
        for response in ['not json', '```json\n{}\n```', '{"answers": {}, "answers": {}}', '{"x": NaN}', None, []]:
            self.assertFalse(grader.grade_response(gold, response)['task_pass'])

    def test_grader_is_invariant_to_arm_and_metadata(self):
        gold, response = self.case()
        score = grader.grade_response(gold, response)
        response.update(arm='CIDM', cost=999, internal_notes='irrelevant')
        self.assertEqual(score, grader.grade_response(gold, response))
        left = {'task_id': gold['id'], 'run_id': 'opaque-01', 'response': response, 'arm': 'CIDM', 'usage': {'tokens': 10}}
        right = dict(left, arm='Sol', usage={'tokens': 100000})
        self.assertEqual(grader.grade_jsonl(self.gold, json.dumps(left)), grader.grade_jsonl(self.gold, json.dumps(right)))
        self.assertNotIn('arm', grader.grade_jsonl(self.gold, json.dumps(left))['results'][0])


if __name__ == '__main__':
    unittest.main()
