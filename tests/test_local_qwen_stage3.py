from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from answer_comparator import compare_candidates
from student_learning_ledger import StudentLearningLedger

WRONG = {"status": "unverified_proposal", "artifact": {
    "answer": "2+2=5", "evidence_ids": [], "unresolved": []}}
RIGHT = {"status": "unverified_proposal", "artifact": {
    "answer": "2+2=4", "evidence_ids": [], "unresolved": []}}


class StudentLearningTests(unittest.TestCase):
    def test_agreement_does_not_accept_false_answer(self):
        result = compare_candidates({"A": WRONG, "B": WRONG})
        self.assertEqual(result["agreement"], "agree_unverified")
        self.assertEqual(result["release"], "withheld_unverified")

    def test_teacher_is_not_ground_truth(self):
        result = compare_candidates({"A": RIGHT, "B": RIGHT}, teacher=WRONG)
        self.assertEqual(result["agreement"], "disagree")
        self.assertFalse(result["teacher_is_ground_truth"])
        self.assertEqual(result["release"], "withheld_unverified")

    def test_fabricated_source_reference_is_flagged(self):
        bad = {"status": "unverified_proposal", "artifact": {
            "answer": "Claim", "evidence_ids": ["foreign"], "unresolved": []}}
        result = compare_candidates({"A": bad}, trusted_source_ids=["real"])
        self.assertEqual(result["candidates"]["A"]["unknown_evidence_ids"], ["foreign"])

    def test_external_validator_claim_cannot_self_release(self):
        result = compare_candidates({"A": RIGHT}, validator_receipts=[
            {"validator": "unit_test", "passed": True, "evidence_ref": "claimed"}])
        self.assertEqual(result["release"], "withheld_unverified")
        self.assertEqual(result["validators"][0]["status"], "external_claim_requires_audit")

    def test_observation_is_not_an_admitted_lesson(self):
        with tempfile.TemporaryDirectory() as temp:
            ledger = StudentLearningLedger(Path(temp) / "students.jsonl")
            report = compare_candidates({"A": WRONG, "B": WRONG})
            obs = ledger.record(task_id="t1", snapshot_hash="h", mode="dual_shadow",
                                lane_results={"A": WRONG, "B": WRONG}, comparison=report)
            self.assertEqual(obs["authority"], "untrusted_observation_not_skill")
            with self.assertRaisesRegex(ValueError, "unknown_observation"):
                ledger.verdict(observation_event_hash="invented", reviewer_id="reviewer",
                               evidence_ref="test", outcome="verified_success")
            verdict = ledger.verdict(observation_event_hash=obs["event_hash"], reviewer_id="reviewer",
                                     evidence_ref="CI run XYZ", outcome="verified_failure")
            self.assertEqual(verdict["authority"], "review_claim_requires_evidence_check")
            self.assertEqual(len(ledger.events()), 2)
