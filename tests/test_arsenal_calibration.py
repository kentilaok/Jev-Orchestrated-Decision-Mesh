"""Phase A2 unit and CLI tests; no live Jev/frontier calls."""
import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from arsenal_calibration import (
    CalibrationError, append_event, evaluate, main, prediction_event,
    read_events, runtime_event, verdict_event,
)

HASH = "a" * 64


def shadow(*, candidate=True, skill_id="known-fix", experience=None):
    recommendation = (
        "fast_path_candidate" if candidate else
        "load_skill_then_jev" if skill_id else
        "load_experience_then_jev" if experience else "jev_only"
    )
    item = {
        "skill_id": skill_id,
        "skill_hash": "b" * 64,
        "manifest_hash": "c" * 64,
    }
    return {
        "mode": "shadow",
        "authority": "none_shadow_observation_only",
        "frontier_call_avoided": False,
        "fast_path_candidate": candidate,
        "would_avoid_frontier_if_fast_path_enabled": candidate,
        "recommendation": recommendation,
        "project_scope": "wordpress",
        "bug_key": "wordpress.memberpress.logged_out_visibility",
        "operation": "inspect_content",
        "selected_skill_id": skill_id,
        "selected_experience_id": experience,
        "fused_candidates": [item] if skill_id else [],
        "lexical": {
            "fast_path": {"eligible": candidate},
            "matches": [{
                "skill_id": skill_id,
                "match": {"score": 1.0, "exact_bug_key": candidate},
            }] if skill_id else [],
        },
    }


def result(*, simulation=False, audited=True, missing_usage=False):
    return {
        "task_hash": HASH,
        "status": "complete" if audited else "audit_failed",
        "simulation": simulation,
        "route": "short_self_contained",
        "hard_checks": {"native_shape": audited},
        "calls": [{
            "role": "worker",
            **({} if missing_usage else {"usage": {
                "input_tokens": 100,
                "output_tokens": 50,
                "cost": 0.004,
            }}),
        }],
    }


def label(run_id, *, expected="known-fix", safe=True):
    return verdict_event(
        run_id, HASH,
        evidence_ref="fixtures/checks/run-valid.json:sha256:" + ("b" * 64),
        expected_skill_id=expected,
        expected_experience_id=None,
        fast_path_safe=safe,
        reviewer="independent-operator",
    )


class ArsenalCalibrationTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.ledger = self.root / "calibration.jsonl"

    def record(self, run_id, *, prediction=None, runtime=None, verdict=None):
        append_event(self.ledger, prediction or prediction_event(run_id, HASH, shadow()))
        append_event(self.ledger, runtime or runtime_event(run_id, result()))
        append_event(self.ledger, verdict or label(run_id))

    def test_prediction_redacts_task_and_retains_versioned_basis(self):
        s = shadow()
        s["task"] = "Private original user request, do not persist."
        p = prediction_event("r1", HASH, s)
        self.assertFalse("task" in p)
        self.assertTrue(p["fast_path_candidate"])
        self.assertEqual(p["skill_hash"], "b" * 64)
        self.assertTrue(p["exact_bug_key"])
        self.assertFalse(p["frontier_call_avoided"])

    def test_reject_shadow_claiming_realized_savings(self):
        s = shadow()
        s["frontier_call_avoided"] = True
        with self.assertRaisesRegex(CalibrationError, "shadow_must_not_claim_realised_savings"):
            prediction_event("r1", HASH, s)

    def test_reject_ungrounded_fast_path_flag(self):
        s = shadow()
        s["lexical"]["fast_path"]["eligible"] = False
        with self.assertRaisesRegex(CalibrationError, "missing_fast_path_basis"):
            prediction_event("r1", HASH, s)

    def test_append_only_rejects_duplicate_and_wrong_task_hash(self):
        p = prediction_event("r1", HASH, shadow())
        append_event(self.ledger, p)
        with self.assertRaisesRegex(CalibrationError, "duplicate_calibration_event"):
            append_event(self.ledger, p)
        altered = runtime_event("r1", result())
        altered["task_hash"] = "d" * 64
        with self.assertRaisesRegex(CalibrationError, "run_task_hash_mismatch"):
            append_event(self.ledger, altered)
        self.assertEqual(len(read_events(self.ledger)), 1)

    def test_audited_reviewed_run_is_true_positive_with_zero_realized_savings(self):
        self.record("r1")
        scored = evaluate(read_events(self.ledger))
        self.assertEqual(scored["summary"]["eligible_evaluated"], 1)
        self.assertEqual(scored["summary"]["fast_path_true_positive"], 1)
        self.assertEqual(scored["summary"]["hypothetically_avoidable_calls"], 1)
        self.assertEqual(scored["metrics"]["fast_path_precision"], 1.0)
        self.assertEqual(scored["realized_frontier_calls_avoided"], 0)
        self.assertIsNone(scored["estimated_token_savings"])

    def test_wrong_skill_prediction_is_unsafe_even_if_other_skill_was_safe(self):
        self.record("wrong", verdict=label("wrong", expected="different-skill"))
        scored = evaluate(read_events(self.ledger))
        self.assertEqual(scored["summary"]["fast_path_false_positive"], 1)
        self.assertEqual(scored["summary"]["selected_skill_correct"], 0)
        self.assertEqual(scored["summary"]["hypothetically_avoidable_calls"], 0)

    def test_false_negative_counts_safe_skill_even_without_fast_path_prediction(self):
        self.record("miss", prediction=prediction_event(
            "miss", HASH, shadow(candidate=False)))
        scored = evaluate(read_events(self.ledger))
        self.assertEqual(scored["summary"]["fast_path_false_negative"], 1)
        self.assertIsNone(scored["metrics"]["fast_path_precision"])
        self.assertEqual(scored["metrics"]["fast_path_recall"], 0.0)

    def test_experience_only_is_context_and_true_negative_if_not_fast_path_safe(self):
        self.record(
            "experience",
            prediction=prediction_event("experience", HASH, shadow(
                candidate=False, skill_id=None, experience="lesson-1")),
            verdict=verdict_event(
                "experience", HASH, evidence_ref="run-1:verified",
                expected_skill_id=None, expected_experience_id="lesson-1",
                fast_path_safe=False, reviewer="independent-operator",
            ),
        )
        scored = evaluate(read_events(self.ledger))
        self.assertEqual(scored["summary"]["selected_experience_correct"], 1)
        self.assertEqual(scored["summary"]["fast_path_true_negative"], 1)

    def test_simulated_run_is_excluded_from_quality_scores(self):
        self.record("sim", runtime=runtime_event("sim", result(simulation=True)))
        scored = evaluate(read_events(self.ledger))
        self.assertEqual(scored["summary"]["excluded_simulated"], 1)
        self.assertEqual(scored["summary"]["eligible_evaluated"], 0)
        self.assertIsNone(scored["metrics"]["fast_path_precision"])

    def test_audit_failure_is_excluded_from_quality_scores(self):
        self.record("failed", runtime=runtime_event("failed", result(audited=False)))
        scored = evaluate(read_events(self.ledger))
        self.assertEqual(scored["summary"]["excluded_unverified_runtime"], 1)
        self.assertEqual(scored["summary"]["eligible_evaluated"], 0)

    def test_missing_verdict_is_excluded(self):
        append_event(self.ledger, prediction_event("pending", HASH, shadow()))
        append_event(self.ledger, runtime_event("pending", result()))
        scored = evaluate(read_events(self.ledger))
        self.assertEqual(scored["summary"]["excluded_missing_evidence"], 1)
        self.assertEqual(scored["summary"]["eligible_evaluated"], 0)

    def test_missing_provider_usage_stays_unknown_not_zero(self):
        r = runtime_event("r1", result(missing_usage=True))
        self.assertIsNone(r["reported_tokens"])
        self.assertIsNone(r["reported_cost_usd"])

    def test_invalid_ledger_line_fails_closed(self):
        self.ledger.write_text('{"kind":"unexpected"}\n', encoding="utf-8")
        with self.assertRaisesRegex(CalibrationError, "invalid_ledger_line_1"):
            read_events(self.ledger)

    def test_cli_capture_label_and_evaluate(self):
        native_file = self.root / "result.json"
        native_result = {**result(), "arsenal_shadow": shadow()}
        native_file.write_text(json.dumps(native_result), encoding="utf-8")
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main([
                "--ledger", str(self.ledger), "capture",
                "--run-id", "r1", "--result", str(native_file),
            ]), 0)
            self.assertEqual(main([
                "--ledger", str(self.ledger), "adjudicate",
                "--run-id", "r1", "--task-hash", HASH,
                "--evidence-ref", "fixtures/checks/run-1.json",
                "--reviewer", "independent-operator",
                "--expected-skill-id", "known-fix",
                "--fast-path-safe", "yes",
            ]), 0)
            self.assertEqual(main(["--ledger", str(self.ledger), "evaluate"]), 0)
        scored = evaluate(read_events(self.ledger))
        self.assertEqual(scored["summary"]["fast_path_true_positive"], 1)
        self.assertEqual(len(read_events(self.ledger)), 3)


if __name__ == "__main__":
    unittest.main()
