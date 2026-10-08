"""Resource-capped independent local Qwen lane scheduling.

Each lane gets an independent provider instance, request scope and permit.
Serial inference is the default; parallel=2 is opt-in, not a speed guarantee.
"""
from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor
import tempfile
from pathlib import Path

from capability_permits import PermitAuthority, audit_permit_ledger
from frontier_providers import _request_scope
from ollama_provider import OllamaLocalProvider, READONLY_SCHEMA
from split_context_dispatch import lane_prompt
from local_resource_governor import enforce_parallel_limit


def run_lanes(packages, *, model, model_digest=None, max_parallel=1,
              provider_factory=None, authority=None, context_tokens=4096,
              parallel_opt_in=False, gpu_free_mib=None):
    if type(max_parallel) is not int or max_parallel not in (1, 2):
        raise ValueError("parallel_limit_must_be_1_or_2")
    enforce_parallel_limit(max_parallel, consent=parallel_opt_in, free_mib=gpu_free_mib)
    if not isinstance(packages, dict) or "A" not in packages or "B" not in packages:
        raise ValueError("two_lane_packages_required")
    prepared = [(lane, packages[lane]) for lane in ("A", "B")
                if packages[lane].get("status") == "prepared"]
    if len({package["snapshot_hash"] for _, package in prepared}) > 1:
        raise ValueError("lane_snapshot_mismatch")
    authority = authority or PermitAuthority()
    results = {}

    def execute(lane, package):
        with tempfile.TemporaryDirectory(prefix="cidm-" + lane.lower() + "-") as workspace:
            provider = (provider_factory(authority, lane) if provider_factory
                        else OllamaLocalProvider(authority, allowed_model=model,
                                                 model_digest=model_digest,
                                                 context_tokens=context_tokens))
            request = {"model": model, "effort": "low", "prompt": lane_prompt(package),
                       "schema": READONLY_SCHEMA, "workspace": workspace}
            basis = {"kind": "operator", "operator": "split-context-pilot",
                     "reason": "bounded local read-only lane " + lane}
            permit = authority.issue("frontier.run",
                                     _request_scope(provider.provider_id, request), basis)
            response = provider.run(request, permit)
            return {"lane": lane, "status": "unverified_proposal",
                    "package_hash": package["package_hash"], "snapshot_hash": package["snapshot_hash"],
                    "skill_ids": [s["skill_id"] for s in package["skills"]],
                    "lesson_ids": [l["lesson_id"] for l in package["lessons"]],
                    "artifact": response["artifact"], "usage": response.get("usage"),
                    "model_identity": response.get("identity_verification"), "permit_id": permit}

    with ThreadPoolExecutor(max_workers=max_parallel) as pool:
        pending = [(lane, pool.submit(execute, lane, package)) for lane, package in prepared]
        for lane, future in pending:
            try:
                results[lane] = future.result()
            except Exception as exc:
                results[lane] = {"lane": lane, "status": "failed",
                                 "error": type(exc).__name__ + ":" + str(exc)[:120],
                                 "snapshot_hash": packages[lane]["snapshot_hash"]}
    for lane in ("A", "B"):
        if lane not in results:
            results[lane] = {"lane": lane, "status": packages[lane].get("status", "skipped")}
    audit = audit_permit_ledger(authority.events())
    if not audit["valid"]:
        raise ValueError("parallel_lane_permit_audit_failed")
    return {"mode": "local_only", "results": results, "permit_audit": audit,
            "physical_parallel_limit": max_parallel, "remote_worker_calls": 0,
            "decision": "unverified_pending_external_validation"}
