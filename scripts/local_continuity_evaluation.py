"""Offline, honest inventory of local-only Qwen pilot runs; no invented savings.

Read existing saved local results. Use an independent truth dataset and real
usage receipts before making model-quality or cost-effectiveness claims.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path


def summarize_run(result):
    if not isinstance(result, dict) or result.get("mode") != "local_only":
        raise ValueError("not_local_continuity_result")
    execution = result.get("execution") or {}
    lanes = execution.get("results") or {}
    summary = {"snapshot": result.get("task_snapshot_hash"),
               "status": result.get("status"), "lanes": {},
               "verified_correctness": None, "frontier_baseline": None,
               "jev_calls": result.get("jev_calls"), "remote_worker_calls": result.get("remote_worker_calls"),
               "comparison": (result.get("comparison") or {}).get("agreement")}
    for lane in ("A", "B"):
        r = lanes.get(lane) or {}
        usage = r.get("usage") if isinstance(r.get("usage"), dict) else {}
        summary["lanes"][lane] = {
            "status": r.get("status", "absent"), "model": (r.get("model_identity") or {}).get("served"),
            "input_tokens": usage.get("input_tokens"),
            "output_tokens": usage.get("output_tokens"),
            "usage_known": type(usage.get("input_tokens")) is int
            and type(usage.get("output_tokens")) is int,
            "package_hash": r.get("package_hash")}
    return summary


def summarize_folder(root):
    root = Path(root)
    rows, errors = [], []
    for path in sorted(root.rglob("result.json")) if root.exists() else []:
        try:
            result = json.loads(path.read_text(encoding="utf-8"))
            if result.get("mode") == "local_only":
                rows.append(summarize_run(result))
        except (ValueError, OSError, TypeError) as exc:
            errors.append({"path": str(path), "error": str(exc)[:120]})
    known = sum(1 for row in rows for lane in row["lanes"].values() if lane["usage_known"])
    unknown = sum(1 for row in rows for lane in row["lanes"].values()
                  if lane["status"] == "unverified_proposal" and not lane["usage_known"])
    return {"runs": len(rows), "local_lane_usage_reported": known,
            "local_lane_usage_unknown": unknown, "verified_correctness": None,
            "verified_quality_advantage": None, "claimed_cost_savings_usd": None,
            "errors": errors, "results": rows}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--runs", type=Path, default=Path("runs"))
    p.add_argument("--out", type=Path)
    args = p.parse_args(argv)
    report = summarize_folder(args.runs)
    if args.out:
        if args.out.exists():
            raise ValueError("evaluation_output_must_be_new")
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
