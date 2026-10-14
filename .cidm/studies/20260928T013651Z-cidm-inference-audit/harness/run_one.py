"""Execute ONE (task, arm, repetition) attempt in a fresh process and workspace.

Invoked by run_benchmark.py. Prints one JSON line with the candidate path and
arm metadata. The task view is the only fixture this process reads; answer keys
are read only in --mode mock, by the MockOracle held inside the mock provider.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import arms as arms_mod  # noqa: E402
import budget as budget_mod  # noqa: E402
import env as env_mod  # noqa: E402
import providers  # noqa: E402


def restore_budget(ledger, caps):
    budget = budget_mod.StudyBudget(ledger=ledger, **caps)
    if Path(ledger).exists():
        for line in Path(ledger).read_text(encoding="utf-8").splitlines():
            record = json.loads(line)
            if record["event"] == "settle":
                budget.spent_total += record["charged"]
                budget.spent_by_run[record["run_id"]] = budget.spent_by_run.get(record["run_id"], 0.0) + record["charged"]
    return budget


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", type=Path, required=True)
    parser.add_argument("--arm-spec", required=True, help="JSON arm specification")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--repetition", type=int, required=True)
    parser.add_argument("--mode", choices=("mock", "live"), required=True)
    parser.add_argument("--events", type=Path, required=True)
    parser.add_argument("--budget-ledger", type=Path, required=True)
    parser.add_argument("--caps", required=True, help="JSON StudyBudget caps")
    parser.add_argument("--prices", type=Path, required=True)
    parser.add_argument("--keys", type=Path, help="answer-key tree; mock mode only")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--accuracy", default="{}", help="mock accuracy table (JSON)")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--repo-scripts", type=Path, required=True)
    args = parser.parse_args(argv)
    spec = json.loads(args.arm_spec)
    task = json.loads(args.task.read_text(encoding="utf-8"))
    if args.mode == "live":
        if args.keys is not None:
            raise SystemExit("answer keys must never be passed to a live attempt")
        worker = providers.OpenRouterChat()
        jev = providers.OpenRouterJev(args.repo_scripts)
    else:
        worker = providers.MockProvider(providers.MockOracle(args.keys), json.loads(args.accuracy), args.seed)
        jev = providers.MockJev(args.seed)
    budget = restore_budget(args.budget_ledger, json.loads(args.caps))
    prices = env_mod.load_prices(args.prices)
    started, t0 = providers.utc_now(), time.monotonic()
    with tempfile.TemporaryDirectory(prefix="cidm-attempt-") as workspace:
        env = env_mod.RunEnv(meta={"run_id": args.run_id, "arm_id": spec["arm_id"], "repetition_id": args.repetition,
                                   "policy_version": spec.get("policy_version", spec["arm_id"]),
                                   "record_kind": "mock" if args.mode == "mock" else "live_evaluation"},
                             task=task, worker_provider=worker, jev_provider=jev, budget=budget, prices=prices,
                             events_path=args.events, workspace=workspace)
        status, candidate, meta = "completed", None, {}
        try:
            candidate, meta = arms_mod.ARMS[spec["kind"]](env, task, spec)
        except budget_mod.BudgetRefused as refusal:
            status, meta = "budget_refused", {"reason": str(refusal)}
        except Exception as error:  # the attempt fails; nothing is hidden
            status, meta = "harness_or_arm_error", {"error": type(error).__name__, "detail": str(error)[:300],
                                                    "trace": traceback.format_exc()[-800:]}
    wall_ms = round((time.monotonic() - t0) * 1000, 3)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(candidate) if candidate is not None else "", encoding="utf-8")
    print(json.dumps({"run_id": args.run_id, "status": status, "candidate_path": str(args.out),
                      "released": candidate is not None, "started_at": started, "wall_ms": wall_ms,
                      "calls": env.call_index, "meta": meta}, default=str))


if __name__ == "__main__":
    main()
