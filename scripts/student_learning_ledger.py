"""A single-writer ledger for student/teacher observations and external verdicts.

No self-training; no skill admission, no trusted promotion. Individual
append operations use the existing tamper-evident CIDM HashChainLedger.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
from capability_permits import HashChainLedger


def hash_record(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=True).encode("utf-8")).hexdigest()


class StudentLearningLedger:
    def __init__(self, path):
        self.ledger = HashChainLedger(Path(path))
        # One owner of this object in one process; never instantiate multiple
        # concurrent writers pointing to the same JSONL file.

    def record(self, *, task_id, snapshot_hash, mode, lane_results, comparison):
        if not task_id or not snapshot_hash or not isinstance(lane_results, dict):
            raise ValueError("invalid_learning_observation")
        compact = {}
        for lane, result in lane_results.items():
            if isinstance(result, dict):
                artifact = result.get("artifact")
                compact[lane] = {"status": result.get("status"),
                                 "model_identity": result.get("model_identity"),
                                 "package_hash": result.get("package_hash"),
                                 "skill_ids": result.get("skill_ids", []),
                                 "lesson_ids": result.get("lesson_ids", []),
                                 "usage": result.get("usage"),
                                 "artifact_hash": hash_record(artifact) if artifact is not None else None}
        return self.ledger.append({"kind": "student_observation", "task_id": task_id,
                                   "snapshot_hash": snapshot_hash, "mode": mode,
                                   "candidates": compact, "comparison_hash": hash_record(comparison),
                                   "agreement": comparison.get("agreement"),
                                   "authority": "untrusted_observation_not_skill"})

    def verdict(self, *, observation_event_hash, reviewer_id, evidence_ref, outcome):
        if outcome not in ("verified_success", "verified_failure", "inconclusive"):
            raise ValueError("invalid_review_outcome")
        if not all(isinstance(x, str) and x.strip() for x in (
                observation_event_hash, reviewer_id, evidence_ref)):
            raise ValueError("review_provenance_required")
        events = self.ledger.read()
        valid = any(e.get("event_hash") == observation_event_hash
                    and e.get("kind") == "student_observation" for e in events)
        if not valid:
            raise ValueError("unknown_observation")
        return self.ledger.append({"kind": "external_review_claim",
                                   "observation_event_hash": observation_event_hash,
                                   "reviewer_id": reviewer_id, "evidence_ref": evidence_ref,
                                   "outcome": outcome,
                                   "authority": "review_claim_requires_evidence_check"})

    def events(self):
        return self.ledger.read()
