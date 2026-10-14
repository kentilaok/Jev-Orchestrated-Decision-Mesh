"""Opt-in local-only split-context pipeline; no Jev approval or automatic writes.

Uses existing admitted Arsenal skills; produces two separate proposals,
independent comparison, and optionally a single-writer observation entry.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path

from arsenal_registry import ArsenalRegistry
from answer_comparator import compare_candidates
from local_lane_scheduler import run_lanes
from split_context_dispatch import frozen_task, build_split_context
from student_learning_ledger import StudentLearningLedger


def run_local_pipeline(*, registry_path, goal, project_scope, model, model_digest=None,
                       bug_key=None, acceptance=None, parallel=1, learning_ledger=None,
                       provider_factory=None, parallel_opt_in=False):
    task = frozen_task(goal, project_scope=project_scope, acceptance=acceptance)
    with ArsenalRegistry(Path(registry_path)) as registry:
        packages = build_split_context(registry, task, bug_key=bug_key)
    execution = run_lanes(packages, model=model, model_digest=model_digest,
                          max_parallel=parallel, provider_factory=provider_factory,
                          parallel_opt_in=parallel_opt_in)
    comparison = compare_candidates(execution["results"])
    result = {"status": "withheld_pending_independent_validation",
              "task_snapshot_hash": task["snapshot_hash"], "authority": "not_jev_authorised",
              "mode": "local_only", "packages": packages, "execution": execution,
              "comparison": comparison, "remote_worker_calls": 0, "jev_calls": 0}
    if learning_ledger:
        ledger = StudentLearningLedger(Path(learning_ledger))
        event = ledger.record(task_id=task["snapshot_hash"][:16],
                              snapshot_hash=task["snapshot_hash"],
                              mode="local_only", lane_results=execution["results"],
                              comparison=comparison)
        result["learning_event_hash"] = event["event_hash"]
    return result


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--registry", type=Path, default=Path("~/.jev/arsenal/arsenal.db").expanduser())
    p.add_argument("--goal", required=True)
    p.add_argument("--project-scope", required=True)
    p.add_argument("--bug-key")
    p.add_argument("--model", required=True)
    p.add_argument("--digest")
    p.add_argument("--learning-ledger", type=Path)
    p.add_argument("--out", type=Path, help="optional local-only JSON result file; contains SOP context")
    p.add_argument("--parallel", type=int, choices=(1, 2), default=1)
    p.add_argument("--allow-parallel-local", action="store_true", help="opt in to physical GPU parallelism after VRAM guard")
    p.add_argument("--live-local", action="store_true")
    args = p.parse_args(argv)
    if not args.live_local:
        print(json.dumps({"status": "preview_only", "remote_worker_calls": 0,
                          "jev_calls": 0, "mode": "local_only"}))
        return 0
    result = run_local_pipeline(registry_path=args.registry, goal=args.goal,
                                project_scope=args.project_scope, model=args.model,
                                model_digest=args.digest, bug_key=args.bug_key,
                                parallel=args.parallel, learning_ledger=args.learning_ledger,
                                parallel_opt_in=args.allow_parallel_local)
    if args.out is not None:
        if args.out.exists():
            raise ValueError("output_file_must_be_new")
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({"status": result["status"], "mode": result["mode"],
                      "task_snapshot_hash": result["task_snapshot_hash"],
                      "learning_event_hash": result.get("learning_event_hash"),
                      "output_file": str(args.out) if args.out else None,
                      "remote_worker_calls": 0, "jev_calls": 0}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
