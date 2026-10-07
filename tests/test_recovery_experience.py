import copy
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from atomic_mesh import AtomicMesh, fingerprint, packed
from checked_network import CheckedNetwork
from network_run import DEMO, DemoPipeline, fake_check
from experience_distiller import (
    append_jsonl,
    distill_lessons,
    extract_experiences,
    load_jsonl,
    promotable,
    render_skill,
    write_promoted_skills,
)
from recovery_protocol import RecoveryJudge, RecoverySupervisor, record_recovery_note


class Unit:
    def __init__(self, uid):
        self.id = uid
        self.name = uid
        self.objective = "complete the unit"


class FakeMesh:
    def __init__(self):
        self.goal = "finish safely"
        self.events = []
        self.sources = {"base": {"text": "base evidence"}}
        self.source_hashes = {"base": fingerprint(self.sources["base"])}
        self.version = 0
        self.simulation = True
        self.last_issue = None

    def record(self, kind, **data):
        event = {
            "id": "e" + str(len(self.events) + 1),
            "kind": kind,
            **copy.deepcopy(data),
        }
        self.events.append(event)
        return event["id"]

    def state_hash(self):
        return fingerprint({
            "sources": self.source_hashes,
            "version": self.version,
            "last_issue": self.last_issue,
        })


class FakeNetwork:
    protocol_version = "fixture"
    policy_version = "p1"

    def __init__(self, outcomes):
        self.units = [Unit("u1")]
        self.committed = []
        self.checks = []
        self.final = None
        self.mesh = FakeMesh()
        self.outcomes = list(outcomes)

    def run_unit(self, unit, index):
        outcome = self.outcomes.pop(0)
        if outcome == "forwarded":
            self.committed.append({"id": unit.id, "artifact": {"text": "done"}})
        return outcome


class RecoveryTests(unittest.TestCase):
    def test_recovery_judge_hides_stop_when_progress_exists(self):
        seen = []

        def judge(_phase, options, _state):
            seen.append(set(options))
            return {"choice": "repair", "live": False, "model": "simulation"}

        wrapped = RecoveryJudge(judge)
        offered = wrapped.filter_options(
            "after_worker",
            {"repair": {}, "retrieve_evidence": {}, "stop": {}},
            {},
        )
        result = wrapped("after_worker", offered, {})
        self.assertEqual(result["choice"], "repair")
        self.assertNotIn("stop", offered)
        self.assertNotIn("stop", seen[0])

    def test_mesh_journals_exact_filtered_options(self):
        seen = []
        def judge(_phase, options, _state):
            seen.append(set(options))
            return {"choice": "repair", "live": False, "model": "simulation"}
        wrapped = RecoveryJudge(judge)
        mesh = AtomicMesh(
            "goal",
            {"s": {"text": "evidence"}},
            {"policy": object()},
            wrapped,
            simulation=True,
        )
        choice, event_id = mesh.gate(
            "after_worker",
            {"repair": {}, "retrieve_evidence": {}, "stop": {}},
            mesh.context(["s"]),
        )
        event = next(event for event in mesh.events if event["id"] == event_id)
        self.assertEqual(choice, "repair")
        self.assertNotIn("stop", event["options"])
        self.assertEqual(set(event["options"]), seen[0])

    def test_operator_abort_restores_stop(self):
        def judge(_phase, options, _state):
            self.assertIn("stop", options)
            return {"choice": "stop", "live": False, "model": "simulation"}

        wrapped = RecoveryJudge(judge, abort_requested=lambda: True)
        offered = wrapped.filter_options(
            "after_worker", {"repair": {}, "retrieve_evidence": {}, "stop": {}}, {}
        )
        result = wrapped("after_worker", offered, {})
        self.assertEqual(result["choice"], "stop")

    def test_recovery_note_is_provisional_structured_evidence(self):
        network = FakeNetwork(["forwarded"])
        event_id = record_recovery_note(network, "u1", {
            "bug_key": "lookup.root",
            "symptom": "Expected object was not found.",
            "root_cause": "Lookup started below the actual owner.",
            "successful_strategy": "Resolve from the owning root.",
            "verification": "Runtime validator passed.",
        })
        event = next(e for e in network.mesh.events if e["id"] == event_id)
        self.assertEqual(event["kind"], "recovery_note")
        self.assertEqual(event["note"]["bug_key"], "lookup.root")

    def test_repair_limit_replans_same_unit_instead_of_ending_project(self):
        network = FakeNetwork(["repair_limit", "forwarded"])
        result = RecoverySupervisor(network, max_recovery_rounds=2).run()
        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["recovery_rounds"], {"u1": 1})
        self.assertTrue(
            any(event["kind"] == "recovery_replan" for event in result["events"])
        )

    def test_missing_evidence_can_be_added_and_unit_resumed(self):
        network = FakeNetwork(["needs_evidence", "forwarded"])
        supervisor = RecoverySupervisor(
            network,
            evidence_retriever=lambda _state: {
                "extra": {"text": "new original evidence"}
            },
        )
        result = supervisor.run()
        self.assertEqual(result["status"], "complete")
        self.assertIn("extra", network.mesh.sources)
        self.assertTrue(
            any(
                event["kind"] == "recovery_evidence_added"
                for event in result["events"]
            )
        )

    def test_no_retriever_returns_recoverable_checkpoint(self):
        network = FakeNetwork(["needs_evidence"])
        result = RecoverySupervisor(network).run()
        self.assertEqual(result["status"], "paused_recoverable")
        self.assertEqual(
            result["checkpoint"]["recovery_kind"], "retrieve_evidence"
        )

    def test_checked_network_can_opt_into_third_local_attempt(self):
        demo = DemoPipeline(DEMO)
        attempts = {}

        def producer(unit, parents, feedback, route):
            candidate = demo.produce(unit, parents, feedback, route)
            attempts[unit.id] = attempts.get(unit.id, 0) + 1
            if unit.id == "hidden1" and attempts[unit.id] < 3:
                candidate["data"]["scale"] = 2000
            return candidate

        def judge(phase, options, state):
            if phase == "authorize_unit":
                choice = "compute" if "compute" in options else next(
                    key for key in options if key != "stop"
                )
            elif phase == "after_worker":
                choice = "forward" if "forward" in options else "repair"
            elif phase == "after_sol_high":
                choice = "forward" if "forward" in options else "repair"
            else:
                raise AssertionError(phase)
            return {"choice": choice, "live": False, "model": "simulation"}

        network = CheckedNetwork(
            DEMO["goal"],
            {"records": {"text": packed(DEMO)}},
            judge,
            producer,
            fake_check,
            demo.validate,
            policy={"version": "recovery-attempt-test", "max_recovery_attempts": 3},
            simulation=True,
        )
        result = network.run()
        self.assertEqual(result["status"], "complete")
        self.assertEqual(attempts["hidden1"], 3)


class DistillationTests(unittest.TestCase):
    def fixture(self, run_id):
        return {
            "status": "complete",
            "events": [
                {
                    "id": "e1",
                    "kind": "post_worker_decision",
                    "unit_id": "hidden1",
                    "choice": "repair",
                    "candidate_hash": "bad",
                    "hard_checks": {"semantic": False},
                },
                {
                    "id": "e2",
                    "kind": "recovery_replan",
                    "unit_id": "hidden1",
                    "recovery_kind": "replan",
                },
                {
                    "id": "e2b",
                    "kind": "recovery_note",
                    "unit_id": "hidden1",
                    "note": {
                        "bug_key": "scale-mismatch",
                        "symptom": "Semantic validator rejects the candidate scale.",
                        "root_cause": "The worker reused an unchecked scale assumption.",
                        "failed_strategy": "Retrying without explicit scale feedback.",
                        "successful_strategy": "Use the checked production scale from the validated evidence.",
                        "verification": "The same semantic validator passed before checked commit.",
                    },
                },
                {
                    "id": "e3",
                    "kind": "checked_commit",
                    "unit_id": "hidden1",
                    "packet": {"artifact_hash": "good-" + run_id},
                },
            ],
        }

    def test_only_verified_recoveries_become_lessons(self):
        unresolved = {
            "events": [{
                "id": "e1",
                "kind": "post_worker_decision",
                "unit_id": "hidden1",
                "choice": "repair",
                "hard_checks": {"semantic": False},
            }]
        }
        records = extract_experiences(unresolved, run_id="unresolved")
        self.assertEqual(distill_lessons(records), [])

    def test_repeated_verified_experience_is_promotable(self):
        records = []
        records += extract_experiences(self.fixture("r1"), run_id="r1")
        records += extract_experiences(self.fixture("r2"), run_id="r2")
        lessons = distill_lessons(records)
        self.assertEqual(len(lessons), 1)
        self.assertTrue(promotable(lessons[0], min_verified=2))
        rendered = render_skill(lessons[0])
        self.assertIn("Re-run the same hard validators", rendered)
        self.assertIn("Use the checked production scale", rendered)
        self.assertIn("unchecked scale assumption", rendered)

    def test_multiple_failures_in_one_run_do_not_self_promote(self):
        run = self.fixture("r1")
        run["events"].insert(1, {
            "id": "e1b",
            "kind": "post_worker_decision",
            "unit_id": "hidden1",
            "choice": "repair",
            "candidate_hash": "bad2",
            "hard_checks": {"semantic": False},
        })
        records = extract_experiences(run, run_id="r1")
        lesson = distill_lessons(records)[0]
        self.assertEqual(lesson["verified_observations"], 1)
        self.assertFalse(promotable(lesson, min_verified=2))

    def test_skill_promotion_writes_hermes_shape(self):
        records = extract_experiences(self.fixture("r1"), run_id="r1")
        lesson = distill_lessons(records)[0]
        with tempfile.TemporaryDirectory() as td:
            written = write_promoted_skills(
                [lesson], Path(td), owner_approved=True
            )
            self.assertEqual(len(written), 1)
            text = written[0].read_text(encoding="utf-8")
            self.assertIn("name: cidm-unscoped-hidden1-", text)
            self.assertIn("Failure signature:", text)
            self.assertIn("## Provenance", text)

    def test_project_scope_separates_otherwise_identical_lessons(self):
        left = extract_experiences(
            self.fixture("r1"), run_id="r1", project_scope="riftforge"
        )
        right = extract_experiences(
            self.fixture("r2"), run_id="r2", project_scope="se-knowledge"
        )
        lessons = distill_lessons(left + right)
        self.assertEqual(len(lessons), 2)
        self.assertEqual(
            {lesson["project_scope"] for lesson in lessons},
            {"riftforge", "se-knowledge"},
        )

    def test_automatic_skill_promotion_requires_project_scope(self):
        records = []
        records += extract_experiences(self.fixture("r1"), run_id="r1")
        records += extract_experiences(self.fixture("r2"), run_id="r2")
        lesson = distill_lessons(records)[0]
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaisesRegex(
                ValueError, "project_scope_required_for_skill_promotion"
            ):
                write_promoted_skills([lesson], Path(td), min_verified=2)

    def test_existing_nonmatching_skill_is_not_overwritten(self):
        records = []
        records += extract_experiences(
            self.fixture("r1"), run_id="r1", project_scope="riftforge"
        )
        records += extract_experiences(
            self.fixture("r2"), run_id="r2", project_scope="riftforge"
        )
        lesson = distill_lessons(records)[0]
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            written = write_promoted_skills([lesson], root, min_verified=2)
            self.assertEqual(len(written), 1)
            written[0].write_text(
                "---\nname: custom\ndescription: manually maintained\n---\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                ValueError, "refusing_to_overwrite_nonmatching_skill"
            ):
                write_promoted_skills([lesson], root, min_verified=2)

    def test_ledger_deduplicates_same_experience_id(self):
        record = extract_experiences(self.fixture("r1"), run_id="r1")[0]
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "ledger.jsonl"
            self.assertEqual(append_jsonl(path, [record]), 1)
            self.assertEqual(append_jsonl(path, [record]), 0)
            self.assertEqual(len(load_jsonl(path)), 1)


if __name__ == "__main__":
    unittest.main()
