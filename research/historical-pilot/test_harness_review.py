"""Offline review regressions; never instantiate the credential-reading constructor."""
import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('reviewed_benchmark', ROOT / 'run_benchmark.py')
benchmark = importlib.util.module_from_spec(spec)
spec.loader.exec_module(benchmark)

TASK = {'id': 'offline', 'stratum': 'offline', 'query': 'Return value',
        'answer_fields': ['value'], 'documents': [{'id': 'source', 'text': 'value=1'}]}
PACKET = {'answers': {'value': 1}, 'evidence': {'value': ['source']}, 'status': 'complete'}


class ReviewHarness(benchmark.Harness):
    def __init__(self):
        self.out = ROOT
        self.phase = 'offline'
        self.events = []
        self.worker_count = 0

    def worker(self, *args, **kwargs):
        self.worker_count += 1
        return PACKET, 'worker-' + str(self.worker_count)

    def call(self, task, arm, role, stage, payload, parent=None):
        if stage == 'intake':
            return {'answers': {'operation': {'choice': 'use_all'}}}, 'intake'
        answers = {name: {'score': 4} for name in
                   ['correctness', 'evidence_support', 'completeness', 'constraint_compliance', 'usefulness']}
        answers.update(release={'choice': 'accept'}, supported={'noul': .1})
        return {'answers': answers}, 'review'


class OfflineReviewTests(unittest.TestCase):
    def test_rejected_accept_does_not_authorize_revision(self):
        harness = ReviewHarness()
        with patch.object(benchmark, 'append'):
            harness.run_arm(TASK, 'B')
        self.assertEqual(harness.worker_count, 1,
                         'A failed hard acceptance gate is not a Jev choice authorizing revise')

    def test_extra_packet_keys_are_rejected(self):
        self.assertFalse(benchmark.check_candidate({**PACKET, 'unexpected': True}, TASK))

    def test_truncated_worker_artifact_is_not_erased(self):
        harness = object.__new__(benchmark.Harness)
        response = {'choices': [{'finish_reason': 'length', 'message': {'content': '{"answers":'}}]}
        with patch.object(harness, 'call', return_value=(response, 'offline-worker')):
            packet, _ = harness.worker(TASK, 'B', TASK['documents'], 0)
        self.assertIsNotNone(packet,
                             'Jev must receive the actual partial artifact and its parse/finish status')


if __name__ == '__main__':
    unittest.main()
