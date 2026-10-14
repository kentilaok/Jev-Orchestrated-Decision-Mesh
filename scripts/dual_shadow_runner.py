"""Experimental concurrent teacher/Qwen shadow proposals. NO Jev arbitration.

Two independent read-only branches receive the same frozen task; local Qwen
uses A/B split SOP packages and the teacher sees no A/B private working
contexts or generated answers until comparison. Explicit live-spend opt-in.
"""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import tempfile

from answer_comparator import compare_candidates
from arsenal_registry import ArsenalRegistry
from capability_permits import PermitAuthority, audit_permit_ledger
from frontier_providers import _request_scope, build_provider
from local_lane_scheduler import run_lanes
from ollama_provider import READONLY_SCHEMA
from split_context_dispatch import build_split_context, frozen_task
from student_learning_ledger import StudentLearningLedger


def execute_teacher(task, *, provider_name, model, authority=None, provider_factory=None):
    if provider_name not in ("claude", "codex") or not isinstance(model, str) or not model:
        raise ValueError("explicit_teacher_route_required")
    authority = authority or PermitAuthority()
    provider = (provider_factory(provider_name, authority)
                if provider_factory else build_provider(provider_name, authority))
    with tempfile.TemporaryDirectory(prefix="cidm-shadow-teacher-") as workspace:
        prompt = ("Read-only independent assessment. Do not execute tools. "
                  "Use only the frozen task statement and supplied acceptance criteria. "
                  "Do not claim tests passed. Report unknown facts in unresolved.\n"
                  + json.dumps({"goal": task["goal"], "acceptance": task["acceptance"],
                                "project_scope": task["project_scope"],
                                "snapshot_hash": task["snapshot_hash"]}, sort_keys=True))
        request = {"model": model, "effort": "low", "prompt": prompt,
                   "schema": READONLY_SCHEMA, "workspace": workspace}
        basis = {"kind": "operator", "operator": "dual-shadow",
                 "reason": "explicitly approved tool-free frontier comparison"}
        permit = authority.issue("frontier.run", _request_scope(provider.provider_id, request), basis)
        response = provider.run(request, permit)
    audit = audit_permit_ledger(authority.events())
    if not audit["valid"]:
        raise ValueError("teacher_permit_audit_failed")
    return {"status": "unverified_proposal", "artifact": response["artifact"],
            "usage": response.get("usage"), "model_identity": response.get("identity_verification"),
            "provider": provider_name, "permit_id": permit, "permit_audit": audit}


def run_dual_shadow(*, registry_path, goal, project_scope, local_model,
                    teacher_provider, teacher_model, local_digest=None,
                    bug_key=None, local_factory=None, teacher_factory=None,
                    local_runner=None, teacher_runner=None):
    task = frozen_task(goal, project_scope=project_scope)
    with ArsenalRegistry(Path(registry_path)) as registry:
        packages = build_split_context(registry, task, bug_key=bug_key)
    def run_student():
        return (local_runner(packages, task) if local_runner else
                run_lanes(packages, model=local_model, model_digest=local_digest,
                          provider_factory=local_factory))
    def run_teacher():
        return (teacher_runner(task) if teacher_runner else
                execute_teacher(task, provider_name=teacher_provider, model=teacher_model,
                                provider_factory=teacher_factory))
    # Only the task was shared. No student draft or SOP context was put in
    # teacher's initial prompt. Each local lane has its own context package.
    with ThreadPoolExecutor(max_workers=2) as pool:
        f_student, f_teacher = pool.submit(run_student), pool.submit(run_teacher)
        try:
            student = f_student.result()
        except Exception as error:
            student = {"results": {}, "status": "failed",
                       "error": type(error).__name__ + ":" + str(error)[:120]}
        try:
            teacher = f_teacher.result()
        except Exception as error:
            teacher = {"status": "failed", "error": type(error).__name__ + ":" + str(error)[:120]}
    comparison = compare_candidates(student.get("results", {}), teacher=teacher)
    return {"status": "withheld_pending_independent_validation", "mode": "dual_shadow",
            "task_snapshot_hash": task["snapshot_hash"], "student": student,
            "teacher": teacher, "comparison": comparison, "release": "withheld_unverified",
            "jev_arbitration_performed": False, "frontier_calls_requested": 1}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--registry", type=Path, default=Path("~/.jev/arsenal/arsenal.db").expanduser())
    p.add_argument("--goal", required=True)
    p.add_argument("--project-scope", required=True)
    p.add_argument("--bug-key")
    p.add_argument("--local-model", required=True)
    p.add_argument("--local-digest")
    p.add_argument("--teacher-provider", choices=("claude", "codex"), required=True)
    p.add_argument("--teacher-model", required=True)
    p.add_argument("--live-dual", action="store_true")
    p.add_argument("--approve-frontier-spend", action="store_true")
    p.add_argument("--out", type=Path)
    args = p.parse_args(argv)
    if not args.live_dual:
        print(json.dumps({"status": "preview_only", "mode": "dual_shadow",
                          "frontier_calls": 0, "local_calls": 0}))
        return 0
    if not args.approve_frontier_spend:
        raise ValueError("explicit_frontier_spend_approval_required")
    result = run_dual_shadow(registry_path=args.registry, goal=args.goal,
                             project_scope=args.project_scope, local_model=args.local_model,
                             local_digest=args.local_digest, bug_key=args.bug_key,
                             teacher_provider=args.teacher_provider, teacher_model=args.teacher_model)
    if args.out:
        if args.out.exists():
            raise ValueError("output_file_must_be_new")
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({"status": result["status"], "mode": result["mode"],
                      "comparison": result["comparison"]["agreement"],
                      "output_file": str(args.out) if args.out else None}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
