"""Metered execution environment for one benchmark attempt.

Every generative action (host, Jev, worker, checker, compressor) goes through
RunEnv, which reserves worst-case spend, calls the provider, settles the budget
and appends one schema-valid event before returning. Deterministic tool runs are
logged with zero model tokens. Nothing here reads answer keys.
"""
from __future__ import annotations

import json
import math
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import budget as budget_mod
import cidm_accounting as acc

PRICE_IDS = {"typesafe/jev-1.13": "jev-1.13", "openai/gpt-6-luna": "gpt-6-luna",
             "openai/gpt-6-sol": "gpt-6-sol", "openai/gpt-6-astra": "gpt-6-astra"}


def load_prices(path):
    rows = json.loads(Path(path).read_text(encoding="utf-8"))["rows"]
    return {row["request_model"]: {k: row.get(k) for k in ("input", "output", "cache_read", "cache_write")}
            for row in rows if row["id"] in PRICE_IDS.values()}


class RunEnv:
    def __init__(self, *, meta, task, worker_provider, jev_provider, budget, prices, events_path,
                 workspace, max_output_tokens=2000, jev_output_reservation_tokens=2000):
        self.meta, self.task = dict(meta), task
        self.worker_provider, self.jev_provider = worker_provider, jev_provider
        self.budget, self.prices, self.events_path = budget, prices, Path(events_path)
        self.workspace = Path(workspace)
        self.max_output_tokens = max_output_tokens
        self.jev_output_reservation_tokens = jev_output_reservation_tokens
        self.call_index = 0
        self.events = []

    # -------------------------------------------------------------- helpers
    def _event(self, actor, purpose, parent=None):
        self.call_index += 1
        event = acc.new_event(run_id=self.meta["run_id"], task_id=self.task["task_id"],
                              task_family=self.task["family"], arm_id=self.meta["arm_id"],
                              repetition_id=self.meta["repetition_id"], policy_version=self.meta["policy_version"],
                              event_id=f"{self.meta['run_id']}:{self.call_index}", actor=actor, currency="USD",
                              record_kind=self.meta["record_kind"],
                              source_record=str(self.events_path.name))
        acc.set_field(event, "purpose", purpose, "directly_observed")
        acc.set_field(event, "parent_event_id", parent, "directly_observed", "root_or_unlinked")
        acc.set_field(event, "pricing_source_date", "2026-09-23", "derived")
        return event

    def _append(self, event):
        issues = acc.validate_event(event)
        if issues:
            event["notes"].append({"schema_issues": issues})
        with self.events_path.open("a", encoding="utf-8") as stream:
            stream.write(acc.packed(event) + "\n")
        self.events.append(event)

    def _settle_usage(self, event, result, normalize):
        provenance = "provider_reported" if result["measurement"] == "live" else "estimated"
        usage, issues = normalize(result.get("usage_raw"))
        event["usage_raw"] = result.get("usage_raw")
        for key in acc.COUNTER_FIELDS:
            acc.set_field(event, key, usage.get(key) if usage else None, provenance,
                          "usage_missing" if not usage else "not_reported")
        reported = usage.get("provider_reported_cost") if usage else None
        acc.set_field(event, "provider_reported_cost", reported if result["measurement"] == "live" else None,
                      "provider_reported", "mock_or_not_reported")
        price = self.prices.get(event["requested_model"])
        estimate, basis = acc.reconstruct_cost(event, price) if price else (None, "no_price_row")
        acc.set_field(event, "reconstructed_cost", estimate, "estimated", basis)
        if issues:
            event["notes"].append({"usage_issues": issues})
        return reported if result["measurement"] == "live" else estimate

    def _stamp(self, event, result):
        for name in ("provider_request_id", "returned_model", "started_at", "ended_at"):
            acc.set_field(event, name, result.get(name), "provider_reported" if name in ("provider_request_id", "returned_model")
                          else "directly_observed", "not_returned")
        acc.set_field(event, "returned_provider", result.get("returned_provider"), "provider_reported", "not_returned")
        acc.set_field(event, "api_duration_ms", result.get("api_duration_ms"), "directly_observed", "not_measured")
        acc.set_field(event, "status", "ok" if result["status"] == "ok" else "failed", "directly_observed")
        if result.get("error"):
            event["notes"].append({"error": result["error"]})

    # -------------------------------------------------------------- generative calls
    def model_call(self, *, actor, purpose, model, effort, messages, schema_kind="task", parent=None):
        event = self._event(actor, purpose, parent)
        acc.set_field(event, "requested_model", model, "directly_observed")
        acc.set_field(event, "requested_effort", effort, "directly_observed")
        acc.set_field(event, "confirmed_effort", None, "unavailable", "provider_response_has_no_effort_field")
        acc.set_field(event, "fallback_status", "fallbacks_disallowed", "directly_observed")
        request = {"model": model, "effort": effort, "messages": messages,
                   "max_output_tokens": self.max_output_tokens, "schema_kind": schema_kind}
        request_bytes = len(json.dumps(messages).encode())
        acc.set_field(event, "prompt_hash", acc.fingerprint(messages), "derived")
        worst = budget_mod.worst_case_usd(self.prices.get(model), max_input_tokens=request_bytes,
                                          max_output_tokens=self.max_output_tokens)
        token = self.budget.reserve(self.meta["run_id"], worst)
        result = self.worker_provider.complete(request, {**self.meta, "task": self.task, "call_index": self.call_index})
        charged = self._settle_usage(event, result, acc.normalize_openrouter_chat_usage)
        self.budget.settle(token, charged)
        acc.set_field(event, "billing_status", "billed" if result["measurement"] == "live" and charged is not None
                      else ("unbilled" if result["measurement"] == "mock" else "unknown"), "derived")
        self._stamp(event, result)
        content = result.get("content")
        acc.set_field(event, "result_hash", acc.sha256_bytes(content.encode()) if isinstance(content, str) else None,
                      "derived", "no_content")
        self._append(event)
        return (content if result["status"] == "ok" else None), event

    def jev_request(self, payload, *, phase, parent=None):
        event = self._event("jev", "gate_decision", parent)
        acc.set_field(event, "requested_model", payload["model"], "directly_observed")
        acc.set_field(event, "requested_effort", None, "unavailable", "jev_has_no_effort_setting")
        acc.set_field(event, "confirmed_effort", None, "unavailable", "not_applicable")
        acc.set_field(event, "gate_phase", phase, "directly_observed")
        criteria = payload["questions"]["next"]["criteria"]
        acc.set_field(event, "gate_options", sorted(criteria), "directly_observed")
        acc.set_field(event, "prompt_hash", acc.fingerprint(payload), "derived")
        body_bytes = len(acc.packed(payload).encode())
        worst = budget_mod.worst_case_usd(self.prices.get(payload["model"]), max_input_tokens=body_bytes,
                                          max_output_tokens=self.jev_output_reservation_tokens)
        token = self.budget.reserve(self.meta["run_id"], worst)
        result = self.jev_provider.decide(payload, {**self.meta, "task": self.task, "call_index": self.call_index,
                                                    "phase": phase})
        charged = self._settle_usage(event, result, acc.normalize_typesafe_usage)
        self.budget.settle(token, charged)
        acc.set_field(event, "billing_status", "billed" if result["measurement"] == "live" and charged is not None
                      else ("unbilled" if result["measurement"] == "mock" else "unknown"), "derived")
        self._stamp(event, result)
        answer = result.get("answer") or {}
        acc.set_field(event, "gate_action", answer.get("choice"), "provider_reported", "no_decision")
        event["notes"].append({"jev_probabilities": answer.get("probabilities"), "jev_confidence": answer.get("confidence")})
        self._append(event)
        return (answer if result["status"] == "ok" else None), event, charged

    # -------------------------------------------------------------- deterministic tools
    def tool_call(self, name, fn, *args, parent=None):
        event = self._event("tool", name, parent)
        for key in acc.COUNTER_FIELDS:
            acc.set_field(event, key, 0 if key in ("input_tokens", "output_tokens") else None,
                          "directly_observed", "no_model_involved")
        acc.set_field(event, "provider_reported_cost", 0.0, "directly_observed")
        acc.set_field(event, "billing_status", "unbilled", "derived")
        t0 = time.monotonic()
        try:
            result = fn(*args)
            acc.set_field(event, "status", "ok", "directly_observed")
        except Exception as error:  # a tool failure is recorded, not hidden
            result = None
            acc.set_field(event, "status", "failed", "directly_observed")
            event["notes"].append({"error": type(error).__name__})
        acc.set_field(event, "api_duration_ms", round((time.monotonic() - t0) * 1000, 3), "directly_observed")
        acc.set_field(event, "result_hash", acc.fingerprint(result), "derived")
        self._append(event)
        return result, event


# ------------------------------------------------------------------ deployment-time checks (no keys)

def run_visible_tests(code, tests, timeout=10):
    if not isinstance(code, str) or not tests:
        return {"passed": False, "info": "no_code_or_tests"}
    with tempfile.TemporaryDirectory(prefix="cidm-visible-") as tmp:
        path = Path(tmp) / "visible_test.py"
        path.write_text(code + "\n\n" + tests, encoding="utf-8")
        try:
            proc = subprocess.run([sys.executable, "-I", "-B", str(path)], cwd=tmp, capture_output=True,
                                  timeout=timeout, text=True)
        except subprocess.TimeoutExpired:
            return {"passed": False, "info": "timeout"}
        return {"passed": proc.returncode == 0, "info": (proc.stderr.strip().splitlines() or ["ok"])[-1][:300]}


def parse_candidate(content):
    if not isinstance(content, str):
        return None
    try:
        value = json.loads(content)
    except (json.JSONDecodeError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def deploy_checks(env, task, candidate, parent=None):
    """Checks available at deployment time: contract, citation existence, visible tests."""
    checks = {"contract": isinstance(candidate, dict) and set(candidate) == {"status", "answer", "citations", "flags", "notes"}}
    if not checks["contract"]:
        return checks
    checks["status_valid"] = candidate["status"] in ("complete", "partial", "needs_evidence", "refused")
    checks["citations_exist"] = (isinstance(candidate["citations"], list)
                                 and all(c in task["sources"] for c in candidate["citations"]))
    checks["answer_object"] = isinstance(candidate["answer"], dict)
    if "visible_tests" in task:
        outcome, _ = env.tool_call("visible_tests", run_visible_tests,
                                   (candidate["answer"] or {}).get("code") if checks["answer_object"] else None,
                                   task["visible_tests"], parent=parent)
        checks["visible_tests"] = bool(outcome and outcome["passed"])
    return checks
