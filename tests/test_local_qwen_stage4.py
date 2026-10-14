import sys
import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts"))
from local_continuity_policy import decide_worker_mode
import operator_console


class ContinuityPolicyTests(TestCase):
    def test_manual_modes(self):
        self.assertEqual(decide_worker_mode(mode="local_only")["route"],"local")
        self.assertEqual(decide_worker_mode(mode="frontier_only")["route"],"frontier")
        self.assertEqual(decide_worker_mode(mode="dual_shadow")["release"],
                         "withheld_until_independent_validation")
        self.assertEqual(decide_worker_mode(mode="local_only")["frontier_worker_calls_allowed"],0)

    def test_automatic_fallback_needs_trusted_quota_and_verified_checkpoint(self):
        good={"error_class":"quota_exhausted","trusted_adapter_classification":True}
        base=dict(mode="auto_fallback",fallback_enabled=True,snapshot_hash="hash",
                  checkpoint_verified=True)
        self.assertTrue(decide_worker_mode(**base,frontier_error=good)["fallback"])
        for faulty in (
            {"error_class":"quota_exhausted"},
            {"error_class":"safety_denial","trusted_adapter_classification":True},
            {"error_class":"invalid_credentials","trusted_adapter_classification":True},
        ):
            self.assertEqual(decide_worker_mode(**base,frontier_error=faulty)["route"],"halt")
        self.assertEqual(decide_worker_mode(**{**base,"checkpoint_verified":False},
                         frontier_error=good)["route"],"halt")

    def test_local_mutations_never_authorized(self):
        with self.assertRaisesRegex(ValueError,"mutation_prohibited"):
            decide_worker_mode(mode="local_only",operation="write")

    def test_console_rejects_nonlocal_modes_and_missing_confirmation(self):
        config={"arsenal_db":"/tmp/index.db","runs_directory":"/tmp"}
        with self.assertRaisesRegex(ValueError,"only local_only"):
            operator_console.start_local_continuity_job(
                {"worker_mode":"auto_fallback"},config)
        with self.assertRaisesRegex(ValueError,"confirm_local_execution"):
            operator_console.start_local_continuity_job(
                {"worker_mode":"local_only"},config)

    def test_console_local_job_uses_local_script_only(self):
        with tempfile.TemporaryDirectory() as temp:
            cfg={"arsenal_db":str(Path(temp)/"arsenal.db"),"runs_directory":temp}
            args={"worker_mode":"local_only","local_model":"qwen3:4b-q4",
                  "project_scope":"demo","task":"fictional bug",
                  "confirm_local_execution":True}
            with patch.object(operator_console.JOBS,"start",return_value={"job_id":"fake"}) as start:
                result=operator_console.start_local_continuity_job(args,cfg)
            self.assertEqual(result["job_id"],"fake")
            argv=start.call_args.args[0]
            self.assertIn("local_continuity_pipeline.py"," ".join(argv))
            self.assertNotIn("native_transition_broker.py"," ".join(argv))
            self.assertIn("--live-local",argv)
