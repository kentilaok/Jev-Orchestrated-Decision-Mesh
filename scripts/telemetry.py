"""Arsenal V1 Phase G: CIDM journals as OpenTelemetry traces for Phoenix.

The CIDM journal remains the authority and audit record; traces are the
analysis plane. Every span carries `cidm.event_id` so the two link back.

Journal events carry no wall-clock timestamps (audit defect D-05), so span times
are *ordinal* (1 ms per event from the run start) and every span says so in
`cidm.timing`. Unknown usage or cost is omitted and flagged, never written as 0.

Export writes OTLP/JSON to a file, or POSTs it to an OTLP/HTTP endpoint
(`<endpoint>/v1/traces`). An OpenTelemetry Collector accepts OTLP/JSON; route
Phoenix through a collector if your Phoenix build only accepts protobuf.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from pathlib import Path
from urllib import request as urlrequest

SERVICE = "cidm"
KIND_INTERNAL, KIND_CLIENT = 1, 3


def _id(seed: str, length: int) -> str:
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:length]


def _attr(key: str, value) -> dict | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return {"key": key, "value": {"boolValue": value}}
    if isinstance(value, int):
        return {"key": key, "value": {"intValue": str(value)}}
    if isinstance(value, float):
        return {"key": key, "value": {"doubleValue": value}}
    if isinstance(value, (list, dict)):
        return {"key": key, "value": {"stringValue": json.dumps(value, sort_keys=True)[:4000]}}
    return {"key": key, "value": {"stringValue": str(value)[:4000]}}


def _attrs(values: dict) -> list[dict]:
    return [a for a in (_attr(k, v) for k, v in values.items()) if a is not None]


def _unit_of(event: dict) -> str | None:
    return (event.get("unit_id") or (event.get("action") or {}).get("unit_id")
            or ((event.get("state") or {}).get("unit") or {}).get("id"))


def _usage_attrs(call: dict | None) -> dict:
    if not call:
        return {"cidm.usage.status": "no_call_record"}
    usage = call.get("usage")
    if not isinstance(usage, dict):
        return {"cidm.usage.status": "unknown"}
    out = {"cidm.usage.status": "reported",
           "llm.token_count.prompt": usage.get("input_tokens"),
           "llm.token_count.completion": usage.get("output_tokens"),
           "cidm.usage.cached_input_tokens": usage.get("cached_input_tokens"),
           "cidm.usage.reasoning_output_tokens": usage.get("reasoning_output_tokens")}
    if isinstance(usage.get("input_tokens"), int) and isinstance(usage.get("output_tokens"), int):
        out["llm.token_count.total"] = usage["input_tokens"] + usage["output_tokens"]
    cost = usage.get("cost")
    out["cidm.cost_usd"] = float(cost) if isinstance(cost, (int, float)) and not isinstance(cost, bool) else None
    return out


def run_summary(result: dict) -> dict:
    """The per-run measurements listed in ARSENAL-V1 section 14.2; unknowns stay None."""
    calls = result.get("calls") or []
    roles = {}
    for call in calls:
        roles[call.get("role", "unknown")] = roles.get(call.get("role", "unknown"), 0) + 1
    usage_known = all(isinstance(c.get("usage"), dict) and isinstance(c["usage"].get("input_tokens"), int)
                      and isinstance(c["usage"].get("output_tokens"), int) for c in calls)
    events = result.get("events") or []
    shadow = result.get("arsenal_shadow") or {}
    return {
        "protocol_version": result.get("protocol_version"), "policy_version": result.get("policy_version"),
        "status": result.get("status"), "route": result.get("route"), "gate_policy": result.get("gate_policy"),
        "host": result.get("host"), "simulation": result.get("simulation"), "task_hash": result.get("task_hash"),
        "committed_units": [p.get("id") for p in result.get("committed") or []],
        "calls_by_role": roles,
        "reported_tokens": sum(c["usage"]["input_tokens"] + c["usage"]["output_tokens"] for c in calls)
        if calls and usage_known else None,
        "jev_api_cost_usd": result.get("jev_api_cost_usd"),
        "jev_decisions": sum(e.get("kind") == "jev_decision" for e in events),
        "recovery_events": sum(str(e.get("kind", "")).startswith("recovery_") for e in events),
        "validator_failures": sum(1 for e in events if e.get("kind") == "post_worker_decision"
                                  and not all((e.get("hard_checks") or {}).values())),
        "skills_considered": shadow.get("selected_skill_id"),
        "experience_considered": shadow.get("selected_experience_id"),
        "shadow_recommendation": shadow.get("recommendation"),
        "evidence_receipts": len(result.get("evidence_receipts") or []),
        "route_coverage": (result.get("route_coverage") or {}).get("status"),
        "primary_agent_tokens": result.get("primary_agent_tokens"),
    }


def to_otlp(result: dict, *, run_id: str | None = None, start_ns: int | None = None) -> dict:
    events = result.get("events") or []
    seed = run_id or (str(result.get("task_hash")) + ":" + str(result.get("policy_version")) + ":"
                      + hashlib.sha256(json.dumps(events, sort_keys=True, default=str).encode()).hexdigest())
    trace_id = _id("trace:" + seed, 32)
    start = start_ns if start_ns is not None else time.time_ns()
    step = 1_000_000
    end = start + (len(events) + 2) * step
    summary = run_summary(result)
    root_id = _id(seed + ":root", 16)
    common = {"cidm.timing": "ordinal_not_wallclock"}
    spans = [{"traceId": trace_id, "spanId": root_id, "name": "cidm.run", "kind": KIND_INTERNAL,
              "startTimeUnixNano": str(start), "endTimeUnixNano": str(end),
              "attributes": _attrs({**common, "openinference.span.kind": "CHAIN",
                                    **{"cidm." + k: v for k, v in summary.items()}}),
              "status": {"code": 1 if summary["status"] == "complete" else 2,
                         "message": str(summary["status"])}}]
    calls = result.get("calls") or []
    jev_calls = [c for c in calls if c.get("role") == "jev"]
    frontier_calls = [c for c in calls if c.get("role") in ("worker", "checker")]
    mesh_jev_offset = 1 if (jev_calls and jev_calls[0].get("phase") == "project_route") else 0
    if mesh_jev_offset:
        spans.append({"traceId": trace_id, "spanId": _id(seed + ":entry", 16), "parentSpanId": root_id,
                      "name": "jev.decision.project_route", "kind": KIND_CLIENT,
                      "startTimeUnixNano": str(start), "endTimeUnixNano": str(start + step // 2),
                      "attributes": _attrs({**common, "openinference.span.kind": "LLM",
                                            "llm.model_name": jev_calls[0].get("identity"),
                                            "cidm.choice": jev_calls[0].get("choice"),
                                            **_usage_attrs(jev_calls[0])})})
    unit_spans: dict[str, dict] = {}
    jev_index, frontier_index = mesh_jev_offset, 0
    for position, event in enumerate(events):
        at = start + (position + 1) * step
        unit = _unit_of(event)
        parent = root_id
        if unit:
            span = unit_spans.get(unit)
            if span is None:
                span = {"traceId": trace_id, "spanId": _id(seed + ":unit:" + unit, 16), "parentSpanId": root_id,
                        "name": "cidm.unit." + unit, "kind": KIND_INTERNAL, "startTimeUnixNano": str(at),
                        "endTimeUnixNano": str(at + step), "events": [],
                        "attributes": _attrs({**common, "openinference.span.kind": "CHAIN", "cidm.unit_id": unit})}
                unit_spans[unit] = span
                spans.append(span)
            span["endTimeUnixNano"] = str(at + step)
            parent = span["spanId"]
        kind = event.get("kind")
        if kind == "jev_decision":
            call = jev_calls[jev_index] if jev_index < len(jev_calls) else None
            jev_index += 1
            decision = event.get("decision") or {}
            spans.append({"traceId": trace_id, "spanId": _id(seed + ":" + str(event.get("id")), 16),
                          "parentSpanId": parent, "name": "jev.decision." + str(event.get("phase")),
                          "kind": KIND_CLIENT, "startTimeUnixNano": str(at), "endTimeUnixNano": str(at + step // 2),
                          "attributes": _attrs({**common, "openinference.span.kind": "LLM",
                                                "cidm.event_id": event.get("id"), "cidm.phase": event.get("phase"),
                                                "cidm.choice": decision.get("choice"),
                                                "cidm.options": sorted(event.get("options") or {}),
                                                "cidm.state_hash": event.get("state_hash"),
                                                "llm.model_name": decision.get("model"), **_usage_attrs(call)})})
        elif kind in ("dispatch", "deferred_dispatch"):
            action = event.get("action") or {}
            route = action.get("worker_route")
            role = "checker" if event.get("worker_id") == "checker" else "worker"
            if event.get("worker_id") == "policy" or (role == "worker" and route is None):
                name, attrs, kind_name = "cidm.commit_or_deterministic", {}, "TOOL"
            else:
                call = frontier_calls[frontier_index] if frontier_index < len(frontier_calls) else None
                frontier_index += 1
                name, kind_name = role + ".call", "LLM"
                attrs = {"llm.model_name": (route or {}).get("model") or (call or {}).get("requested_model"),
                         "cidm.effort": (route or {}).get("effort") or (call or {}).get("requested_effort"),
                         "cidm.identity_verification": (call or {}).get("identity_verification"),
                         **_usage_attrs(call)}
            spans.append({"traceId": trace_id, "spanId": _id(seed + ":" + str(event.get("id")), 16),
                          "parentSpanId": parent, "name": name, "kind": KIND_CLIENT,
                          "startTimeUnixNano": str(at), "endTimeUnixNano": str(at + step),
                          "attributes": _attrs({**common, "openinference.span.kind": kind_name,
                                                "cidm.event_id": event.get("id"), "cidm.gate_id": event.get("gate_id"),
                                                "cidm.action_hash": event.get("action_hash"), **attrs})})
        elif unit and kind in ("checked_commit", "post_worker_decision", "post_checker_decision",
                               "recovery_replan", "recovery_evidence_added", "recovery_checkpoint", "halt"):
            unit_spans[unit]["events"].append({
                "timeUnixNano": str(at), "name": "cidm." + kind,
                "attributes": _attrs({"cidm.event_id": event.get("id"), "cidm.choice": event.get("choice"),
                                      "cidm.hard_checks": event.get("hard_checks")})})
    return {"resourceSpans": [{
        "resource": {"attributes": _attrs({"service.name": SERVICE, "cidm.trace_seed": seed[:64]})},
        "scopeSpans": [{"scope": {"name": "cidm.telemetry", "version": "1"}, "spans": spans}]}]}


def post_otlp(endpoint: str, payload: dict, *, headers: dict | None = None, opener=None, timeout: float = 15) -> int:
    url = endpoint.rstrip("/")
    if not url.endswith("/v1/traces"):
        url += "/v1/traces"
    req = urlrequest.Request(url, data=json.dumps(payload).encode("utf-8"), method="POST",
                             headers={"Content-Type": "application/json", **(headers or {})})
    with (opener or urlrequest.urlopen)(req, timeout=timeout) as response:
        return response.status


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Export a CIDM result journal as OpenTelemetry spans")
    parser.add_argument("result", type=Path)
    parser.add_argument("--out", type=Path, help="Write OTLP/JSON here")
    parser.add_argument("--endpoint", default=os.environ.get("PHOENIX_COLLECTOR_ENDPOINT"),
                        help="OTLP/HTTP base URL (default: PHOENIX_COLLECTOR_ENDPOINT)")
    parser.add_argument("--summary", action="store_true", help="Print the run summary only")
    args = parser.parse_args(argv)
    result = json.loads(args.result.read_text(encoding="utf-8"))
    if args.summary:
        print(json.dumps(run_summary(result), indent=2, sort_keys=True))
        return 0
    payload = to_otlp(result, start_ns=int(args.result.stat().st_mtime * 1e9))
    spans = len(payload["resourceSpans"][0]["scopeSpans"][0]["spans"])
    if args.out:
        args.out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    if args.endpoint and not args.out:
        status = post_otlp(args.endpoint, payload)
        print(json.dumps({"exported_spans": spans, "endpoint_status": status}))
    else:
        print(json.dumps({"exported_spans": spans, "out": str(args.out) if args.out else None}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
