"""One-call GPT-6 Sol-high baseline for the checked production-record fixture.

Concept and evaluation method: Kenneth Vic A. Caber. This program makes one
worker call in live mode. Offline mode is a labeled arithmetic simulation and
must never be counted as an inference result.
"""
import argparse
import copy
import json
import math
from pathlib import Path
import re

from atomic_mesh import MeshError, fingerprint, require
from config import RunConfig
from network_run import DEMO, DemoPipeline
from transport import Gateway


BASELINE_ROUTE = {"id": "sol_high", "model": "openai/gpt-6-sol", "effort": "high"}
BASELINE_SCHEMA = {
    "type": "object",
    "properties": {
        "text": {"type": "string"},
        "answer": {"type": "number"},
        "unit": {"type": "string"},
        "included_segments": {"type": "array", "items": {"type": "string"}},
        "excluded_segments": {"type": "array", "items": {"type": "string"}},
        "source_ids": {"type": "array", "items": {"type": "string", "enum": ["records"]},
                       "minItems": 1, "maxItems": 1},
    },
    "required": ["text", "answer", "unit", "included_segments", "excluded_segments", "source_ids"],
    "additionalProperties": False,
}

BASELINE_INSTRUCTIONS = (
    "Answer the task using only the supplied original records. Include only rows whose kind equals "
    "include_kind in the totals; trial rows are excluded. Compute total defects divided by total items "
    "for the included rows, then multiply by scale. Return one concise final answer in text with the "
    "literal citation [records] and state that trial rows were excluded. Return exactly the requested "
    "JSON fields: text, numeric answer, unit, included_segments, excluded_segments, and source_ids "
    "([\"records\"]). Preserve segment order. Do not provide hidden reasoning or add unsupported sources."
)


def validate_baseline(task, pipeline, candidate):
    """Independent deterministic checks; the model does not receive expected values."""
    contract = (type(candidate) is dict and set(candidate) == set(BASELINE_SCHEMA["required"])
                and type(candidate.get("text")) is str and type(candidate.get("unit")) is str
                and type(candidate.get("answer")) in (int, float)
                and math.isfinite(candidate["answer"])
                and all(type(candidate.get(name)) is list
                        and all(type(item) is str for item in candidate[name])
                        for name in ("included_segments", "excluded_segments", "source_ids")))
    checks = {"response_contract": bool(contract)}
    if not contract:
        return checks
    included = [row["segment"] for row in task["records"] if row["kind"] == task["include_kind"]]
    excluded = [row["segment"] for row in task["records"] if row["kind"] != task["include_kind"]]
    text = candidate["text"]
    checks.update({
        "answer_matches_exact_reference": candidate["answer"] == float(pipeline.expected),
        "included_segments_match_scope": candidate["included_segments"] == included,
        "excluded_segments_match_scope": candidate["excluded_segments"] == excluded,
        "unit_matches_task": candidate["unit"] == f"defects per {task['scale']} production items",
        "source_ids_match_evidence": candidate["source_ids"] == ["records"],
        "answer_cites_records": "[records]" in text,
        "trial_exclusion_explained": (
            not any(row["kind"] == "trial" for row in task["records"])
            or (re.search(r"\btrial\b", text, re.I) is not None
                and re.search(r"\bexclud(?:e|ed|ing)?\b", text, re.I) is not None)),
    })
    return checks


def simulated_candidate(task, pipeline):
    """Deterministic expected output for CLI plumbing tests, not a model prediction."""
    return {
        "text": (f"{float(pipeline.expected)} defects per {task['scale']} production items; "
                 "trial records excluded. [records]"),
        "answer": float(pipeline.expected),
        "unit": f"defects per {task['scale']} production items",
        "included_segments": [r["segment"] for r in task["records"]
                              if r["kind"] == task["include_kind"]],
        "excluded_segments": [r["segment"] for r in task["records"]
                              if r["kind"] != task["include_kind"]],
        "source_ids": ["records"],
    }


def usage_summary(calls):
    """Unknown usage stays unknown; cached/reasoning subsets are not added twice."""
    if not calls:
        return None
    values = [event.get("usage", {}) for event in calls]
    def total(field):
        pieces = [usage.get(field) for usage in values]
        return sum(pieces) if all(type(v) in (int, float) for v in pieces) else None
    return {"input_tokens": total("input_tokens"), "output_tokens": total("output_tokens"),
            "total_tokens": total("total_tokens"), "cost": total("cost"),
            "usage_complete": all(all(type(usage.get(field)) in (int, float)
                                      for field in ("input_tokens", "output_tokens", "total_tokens", "cost"))
                                  for usage in values)}


def run_baseline(task, config, folder, *, live):
    """Create a fresh run directory and write a result even for an admitted failed call."""
    require(isinstance(config, RunConfig), "validated_run_config_required")
    pipeline = DemoPipeline(task)
    folder = Path(folder)
    require(not folder.exists(), "output_directory_must_be_new")
    folder.mkdir(parents=True, exist_ok=False)
    gateway = Gateway(folder, config) if live else None
    candidate, error_code = None, None
    if live:
        try:
            unit = f"defects per {task['scale']} production items"
            schema = copy.deepcopy(BASELINE_SCHEMA)
            schema["properties"]["unit"]["enum"] = [unit]
            candidate = gateway.ask("worker", BASELINE_INSTRUCTIONS + " The unit field must be exactly: " + unit + ".",
                                    {"source_id": "records", "task": task},
                                    schema, worker_route=BASELINE_ROUTE)
        except MeshError as error:
            # Only these local contract codes may reach the result file. Gateway
            # writes a separate sanitized event for the actual failed attempt.
            error_code = str(error) if str(error) in {
                "provider_call_failed", "worker_json_invalid", "call_or_cost_budget_exhausted",
                "request_byte_limit", "configuration_changed_during_run"} else "baseline_call_failed"
    else:
        candidate = simulated_candidate(task, pipeline)
    checks = validate_baseline(task, pipeline, candidate) if candidate is not None else {}
    status = ("simulated" if not live else
              "failed" if error_code is not None else
              "complete" if all(checks.values()) else "quality_failed")
    result = {
        "status": status, "mode": "live" if live else "offline_simulation",
        "simulation": not live, "method": "single_gpt_6_sol_high_call",
        "task_hash": fingerprint(task), "model": BASELINE_ROUTE["model"],
        "effort": BASELINE_ROUTE["effort"], "configuration": config.to_dict(),
        "candidate": gateway._safe(candidate) if gateway else candidate,
        "answer": candidate.get("answer") if type(candidate) is dict
                  and type(candidate.get("answer")) in (int, float)
                  and math.isfinite(candidate["answer"]) else None,
        "reference_answer": float(pipeline.expected),
        "quality_checks": checks, "error_code": error_code,
        "calls": gateway.calls if gateway else [],
        "usage": usage_summary(gateway.calls) if gateway else None,
        "reported_cost": gateway.spent if gateway else None,
        "training_performed": False,
    }
    (folder / "result.json").write_text(json.dumps(result, indent=2, allow_nan=False), encoding="utf-8")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--offline", action="store_true", help="Arithmetic simulation; no API call")
    mode.add_argument("--live", action="store_true", help="One billable GPT-6 Sol-high API call")
    parser.add_argument("--config", type=Path)
    parser.add_argument("--task", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    config = RunConfig.from_dict(json.loads(args.config.read_text(encoding="utf-8-sig"))
                                 if args.config else {})
    task = json.loads(args.task.read_text(encoding="utf-8-sig")) if args.task else DEMO
    result = run_baseline(task, config, args.out, live=args.live)
    print(json.dumps({"status": result["status"], "answer": result["answer"],
                      "calls": len(result["calls"]), "usage": result["usage"],
                      "simulation": result["simulation"]}, allow_nan=False))
    return 0 if result["status"] in ("complete", "simulated") else 2


if __name__ == "__main__":
    raise SystemExit(main())
