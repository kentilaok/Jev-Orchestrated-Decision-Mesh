"""Run the preregistered benchmark (mock or live) and write events.jsonl + results.csv.

Mock (validates plumbing only; zero spend):
    python -B run_benchmark.py --mode mock --split dev --reps 2 --out <study>/runs/mock-smoke

Live (never implied by the presence of keys; every cap is explicit and required):
    python -B run_benchmark.py --mode live --split heldout --reps 3 --arms A,B,C,D \
        --max-usd 5.00 --per-run-usd 0.50 --per-request-usd 0.10 --i-accept-live-spend \
        --out <study>/runs/live-001

Attempts run serially (concurrency 1, no retries) in fresh processes and temp
workspaces. Arm order is randomised and interleaved per (task, repetition).
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import random
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
STUDY = HERE.parent
REPO = STUDY.parents[2]
sys.path.insert(0, str(HERE))
import cidm_accounting as acc  # noqa: E402

RESULT_FIELDS = ["run_id", "task_id", "family", "split", "arm_id", "repetition", "order_index", "record_kind",
                 "attempt_status", "released", "accepted", "failures", "critical_failures", "calls",
                 "wall_ms", "sum_api_ms", "host_calls", "jev_calls", "worker_calls", "checker_calls", "tool_calls",
                 "strong_model_calls", "input_tokens", "output_tokens", "io_tokens", "unknown_token_calls",
                 "charge_usd", "charge_basis", "unknown_charge_calls", "host_charge", "jev_charge",
                 "worker_charge", "checker_charge", "compressor_charge", "meta"]


def load_experiment():
    path_yaml, path_json = STUDY / "EXPERIMENT.yaml", STUDY / "EXPERIMENT.json"
    try:
        import yaml  # optional; the JSON twin is authoritative when PyYAML is absent
        data = yaml.safe_load(path_yaml.read_text(encoding="utf-8"))
    except ImportError:
        data = json.loads(path_json.read_text(encoding="utf-8"))
    return data


def resolve(spec):
    spec = dict(spec)
    if "scripts_dir" in spec:
        spec["scripts_dir"] = str((STUDY / spec["scripts_dir"]).resolve() if not spec["scripts_dir"].startswith("REPO:")
                                  else (REPO / spec["scripts_dir"][5:]).resolve())
    return spec


def summarize_run(events, run_id):
    mine = [e for e in events if e["run_id"] == run_id]
    charges = [acc.charge_for_totals(e) for e in mine if e["actor"] != "tool"]
    tokens = [acc.io_total(e) for e in mine if e["actor"] != "tool"]

    def role_charge(actor):
        vals = [acc.charge_for_totals(e)[0] for e in mine if e["actor"] == actor]
        return round(sum(vals), 12) if all(v is not None for v in vals) else None
    strong = sum(1 for e in mine if (e.get("requested_model") or "").endswith("gpt-6-sol")
                 and e.get("requested_effort") in ("high", "xhigh"))
    return {"calls": sum(e["actor"] != "tool" for e in mine),
            "sum_api_ms": round(sum(e["api_duration_ms"] or 0 for e in mine), 3),
            "host_calls": sum(e["actor"] == "host" for e in mine), "jev_calls": sum(e["actor"] == "jev" for e in mine),
            "worker_calls": sum(e["actor"] == "worker" for e in mine),
            "checker_calls": sum(e["actor"] == "checker" for e in mine),
            "tool_calls": sum(e["actor"] == "tool" for e in mine), "strong_model_calls": strong,
            "input_tokens": sum(e["input_tokens"] or 0 for e in mine if e["actor"] != "tool"),
            "output_tokens": sum(e["output_tokens"] or 0 for e in mine if e["actor"] != "tool"),
            "io_tokens": sum(t for t in tokens if t is not None) if all(t is not None for t in tokens) else None,
            "unknown_token_calls": sum(t is None for t in tokens),
            "charge_usd": round(sum(c for c, _ in charges), 12) if all(c is not None for c, _ in charges) else None,
            "charge_basis": "|".join(sorted({b for _, b in charges})) or "none",
            "unknown_charge_calls": sum(c is None for c, _ in charges),
            "host_charge": role_charge("host"), "jev_charge": role_charge("jev"), "worker_charge": role_charge("worker"),
            "checker_charge": role_charge("checker"), "compressor_charge": role_charge("compressor")}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("mock", "live"), required=True)
    parser.add_argument("--split", choices=("dev", "heldout"), required=True)
    parser.add_argument("--reps", type=int, default=1)
    parser.add_argument("--arms", default=None, help="comma list of arm keys; default: all preregistered")
    parser.add_argument("--tasks", default=None, help="comma list of task ids (smoke tests)")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--max-usd", type=float, default=0.0)
    parser.add_argument("--per-run-usd", type=float, default=0.0)
    parser.add_argument("--per-request-usd", type=float, default=0.0)
    parser.add_argument("--i-accept-live-spend", action="store_true")
    args = parser.parse_args(argv)
    experiment = load_experiment()
    seed = experiment["randomisation"]["seed"] if args.seed is None else args.seed
    if args.mode == "live":
        missing = [n for n, v in (("--max-usd", args.max_usd), ("--per-run-usd", args.per_run_usd),
                                  ("--per-request-usd", args.per_request_usd)) if not v or v <= 0]
        if missing or not args.i_accept_live_spend:
            raise SystemExit("live mode refused: explicit positive caps and --i-accept-live-spend are required "
                             "(missing: " + ", ".join(missing or ["--i-accept-live-spend"]) + ")")
        if args.max_usd > experiment["budget"]["live_study_cap_usd_ceiling"]:
            raise SystemExit("live mode refused: --max-usd exceeds the preregistered ceiling")
        if not os.environ.get("OPENROUTER_API_KEY"):
            raise SystemExit("live mode refused: OPENROUTER_API_KEY is not set")
        caps = {"total_usd": args.max_usd, "per_run_usd": args.per_run_usd, "per_request_usd": args.per_request_usd}
    else:
        caps = experiment["budget"]["mock_virtual_caps"]
    caps.update({"max_concurrency": 1, "max_retries": 0})
    if args.out.exists():
        raise SystemExit("output directory must be new: " + str(args.out))
    args.out.mkdir(parents=True)
    lock = args.out / ".lock"
    lock.write_text(str(os.getpid()))
    fixtures = STUDY / "fixtures"
    manifest = json.loads((fixtures / "MANIFEST.json").read_text(encoding="utf-8"))
    for row in manifest["tasks"]:
        for tree, key in (("tasks", "task_sha256"), ("answer-keys", "key_sha256")):
            digest = acc.sha256_bytes((fixtures / tree / row["split"] / (row["task_id"] + ".json")).read_bytes())
            if digest != row[key]:
                raise SystemExit("frozen fixture changed: " + row["task_id"] + " " + tree)
    tasks = [row for row in manifest["tasks"] if row["split"] == args.split
             and (args.tasks is None or row["task_id"] in args.tasks.split(","))]
    arm_keys = args.arms.split(",") if args.arms else list(experiment["arms"])
    rng = random.Random(seed)
    schedule = []
    for rep in range(args.reps):
        for row in tasks:
            order = list(arm_keys)
            rng.shuffle(order)
            schedule.extend((row, rep, arm) for arm in order)
    events_path = args.out / "events.jsonl"
    results_path = args.out / "results.csv"
    (args.out / "schedule.json").write_text(json.dumps([[r["task_id"], rep, a] for r, rep, a in schedule]), encoding="utf-8")
    python = [sys.executable, "-B"]
    with results_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=RESULT_FIELDS)
        writer.writeheader()
        for index, (row, rep, arm_key) in enumerate(schedule):
            spec = resolve({**experiment["arms"][arm_key], "arm_id": experiment["arms"][arm_key]["arm_id"]})
            run_id = f"{row['task_id']}.{arm_key}.r{rep}"
            cmd = python + [str(HERE / "run_one.py"), "--task", str(fixtures / "tasks" / row["split"] / (row["task_id"] + ".json")),
                            "--arm-spec", json.dumps(spec), "--run-id", run_id, "--repetition", str(rep),
                            "--mode", args.mode, "--events", str(events_path),
                            "--budget-ledger", str(args.out / "budget-ledger.jsonl"), "--caps", json.dumps(caps),
                            "--prices", str(STUDY / "pricing-snapshot.json"), "--seed", str(seed),
                            "--out", str(args.out / "candidates" / (run_id + ".json")),
                            "--repo-scripts", str(REPO / "scripts")]
            if args.mode == "mock":
                cmd += ["--keys", str(fixtures / "answer-keys"), "--accuracy", json.dumps(experiment["mock"]["accuracy"])]
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
            try:
                attempt = json.loads(proc.stdout.strip().splitlines()[-1])
            except (IndexError, json.JSONDecodeError):
                attempt = {"status": "attempt_process_failed", "released": False, "calls": None, "wall_ms": None,
                           "meta": {"stderr": proc.stderr[-800:]}, "candidate_path": None}
            candidate = Path(attempt["candidate_path"]).read_text(encoding="utf-8") if attempt.get("candidate_path") else ""
            grade = subprocess.run(python + [str(HERE / "grade.py"), "--keys", str(fixtures / "answer-keys"),
                                             "--task-id", row["task_id"], "--split", row["split"]],
                                   input=candidate, capture_output=True, text=True, timeout=120)
            verdict = json.loads(grade.stdout)
            events = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines()] if events_path.exists() else []
            writer.writerow({"run_id": run_id, "task_id": row["task_id"], "family": row["family"], "split": row["split"],
                             "arm_id": spec["arm_id"], "repetition": rep, "order_index": index,
                             "record_kind": "mock" if args.mode == "mock" else "live_evaluation",
                             "attempt_status": attempt["status"], "released": attempt.get("released"),
                             "accepted": verdict["accepted"], "failures": "|".join(verdict["failures"]),
                             "critical_failures": "|".join(verdict["critical_failures"]),
                             "wall_ms": attempt.get("wall_ms"), **summarize_run(events, run_id),
                             "meta": json.dumps(attempt.get("meta"), default=str)[:1500]})
            stream.flush()
            if attempt["status"] == "budget_refused" and args.mode == "live":
                print("stopping: budget refused", file=sys.stderr)
                break
    lock.unlink()
    print(json.dumps({"attempts": len(schedule), "events": str(events_path), "results": str(results_path)}))


if __name__ == "__main__":
    main()
