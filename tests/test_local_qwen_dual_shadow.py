import sys
import tempfile
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts"))
from dual_shadow_runner import execute_teacher, run_dual_shadow
from frontier_providers import _BoundedProvider
from capability_permits import PermitAuthority
from split_context_dispatch import frozen_task

GOOD={"answer":"2+2=4","evidence_ids":[],"unresolved":[]}
WRONG={"answer":"2+2=5","evidence_ids":[],"unresolved":[]}


class FakeClaude(_BoundedProvider):
    provider_id="claude"


class FakeAdapter:
    cancel_event=None
    def run(self, model, effort, prompt, schema, workspace):
        if "Lesson A private" in prompt:
            raise AssertionError("student context leaked")
        return {"artifact":WRONG,"usage":{"input_tokens":3,"output_tokens":5}}


class DualShadowTests(unittest.TestCase):
    def test_tool_free_teacher_has_separate_authorised_call(self):
        task=frozen_task("How much is 2+2?",project_scope="demo")
        authority=PermitAuthority()
        result=execute_teacher(task,provider_name="claude",model="fake-claude",
                               authority=authority,
                               provider_factory=lambda name,auth:FakeClaude(FakeAdapter(),auth,executable="fake"))
        self.assertEqual(result["status"],"unverified_proposal")
        self.assertTrue(result["permit_audit"]["valid"])
        self.assertEqual(result["usage"]["input_tokens"],3)

    def test_concurrent_dual_comparison_refuses_wrong_teacher(self):
        with tempfile.TemporaryDirectory() as tmp:
            def fake_students(packages, task):
                return {"results":{"A":{"status":"unverified_proposal","artifact":GOOD},
                                   "B":{"status":"unverified_proposal","artifact":GOOD}}}
            def fake_teacher(task):
                return {"status":"unverified_proposal","artifact":WRONG}
            report=run_dual_shadow(registry_path=Path(tmp)/"db.sqlite",
                                   goal="How much is 2+2?",project_scope="demo",
                                   local_model="fake-qwen",teacher_provider="claude",
                                   teacher_model="fake-claude",local_runner=fake_students,
                                   teacher_runner=fake_teacher)
            self.assertEqual(report["comparison"]["agreement"],"disagree")
            self.assertEqual(report["release"],"withheld_unverified")
            self.assertFalse(report["jev_arbitration_performed"])
