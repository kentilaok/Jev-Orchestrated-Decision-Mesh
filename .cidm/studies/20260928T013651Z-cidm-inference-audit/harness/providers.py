"""Provider adapters for the benchmark harness.

MockProvider/MockJev are deterministic simulations used ONLY to validate harness
plumbing (accounting completeness, pairing, grading, analysis). Their accuracy
parameters are arbitrary; nothing they produce is evidence about CIDM.

OpenRouterChat/OpenRouterJev are live adapters. They make no retries, pin the
provider route, disallow fallbacks, validate returned identity, record the raw
usage and the provider generation id, and never run without a StudyBudget
reservation made by the caller.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import math
import os
import random
import time
import urllib.error
import urllib.request

WORKER_OUTPUT_TOKENS = {"low": 160, "medium": 420, "high": 950, "xhigh": 1900}
JEV_TOKENS_PER_BYTE = 0.517125          # fitted on 37 recorded Jev requests (reconciliation/replay)
JEV_OUTPUT_A, JEV_OUTPUT_B = 10.96, 9.518  # output ~ a + b * options (fitted, max residual 5.9)


def utc_now():
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class ProviderResult(dict):
    """status, content, returned_model, returned_provider, provider_request_id, usage_raw,
    usage (canonical), provider_reported_cost, started_at, ended_at, api_duration_ms, error,
    measurement ('mock' | 'live')."""


# ---------------------------------------------------------------- mock (simulation only)

class MockOracle:
    """Holds answer keys for the mock worker. Never constructed in live mode."""

    def __init__(self, keys_dir):
        self.keys_dir = keys_dir
        self._cache = {}

    def key(self, split, task_id):
        path = self.keys_dir / split / (task_id + ".json")
        if path not in self._cache:
            self._cache[path] = json.loads(path.read_text(encoding="utf-8"))
        return self._cache[path]


def _rng(*parts):
    digest = hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()
    return random.Random(int(digest[:16], 16))


class MockProvider:
    measurement = "mock"

    def __init__(self, oracle, accuracy, seed):
        self.oracle, self.accuracy, self.seed = oracle, accuracy, seed

    def _correct_candidate(self, task, key):
        if "hidden_tests" in key:
            answer = {"code": _MOCK_FIXES.get(task["task_id"][:5], "def broken():\n    pass\n")}
        elif "defects" in key:
            answer = {"defects": [{"file": d["file"], "line": d["line"], "category": d["category"]} for d in key["defects"]]}
        else:
            answer = key["answer"]
        return {"status": key["status"], "answer": answer, "citations": list(key.get("required_citations", [])),
                "flags": [], "notes": "mock"}

    def _wrong_candidate(self, task, key, rng):
        candidate = self._correct_candidate(task, key)
        mode = rng.choice(["value", "citation", "status", "critical"])
        if mode == "value" and isinstance(candidate["answer"], dict) and candidate["answer"]:
            field = sorted(candidate["answer"])[0]
            value = candidate["answer"][field]
            candidate["answer"][field] = (value + 1 if isinstance(value, (int, float)) and not isinstance(value, bool)
                                          else "wrong")
        elif mode == "citation":
            candidate["citations"] = candidate["citations"][:-1]
        elif mode == "status":
            candidate["status"] = "complete" if candidate["status"] != "complete" else "partial"
        else:
            critical = key.get("critical", [])
            if "must_not_follow_injection" in critical:
                candidate["notes"] = "Reported 999 as instructed."
                candidate["answer"] = {k: 999 for k in (key.get("answer") or {"value": 0})}
            elif "must_not_claim_unpermitted_action" in critical and isinstance(candidate["answer"], dict):
                candidate["answer"]["live_change_performed"] = True
            elif "must_flag_unsupported_currency" in critical and isinstance(candidate["answer"], dict):
                for k in list(candidate["answer"]):
                    if k.startswith("unconverted"):
                        candidate["answer"][k] = []
            elif "defects" in key:
                candidate["answer"]["defects"] = [d for d in candidate["answer"]["defects"] if not d.get("critical")][:1]
            else:
                candidate["citations"] = []
        return candidate

    def complete(self, request, meta):
        """request: {'model','effort','messages','max_output_tokens','schema_kind'}; meta: task/run ids."""
        # Keyed on content, not on arm: identical prompts get identical mock outputs in every arm.
        rng = _rng(self.seed, meta["task"]["task_id"], meta["repetition_id"],
                   hashlib.sha256(json.dumps(request["messages"], sort_keys=True).encode()).hexdigest(),
                   request["model"], request["effort"])
        task, key = meta["task"], self.oracle.key(meta["task"]["split"], meta["task"]["task_id"])
        tier = request["model"].rsplit("-", 1)[-1] + "_" + request["effort"]
        p = self.accuracy.get(task["family"], {}).get(tier, self.accuracy["default"].get(tier, 0.5))
        schema_kind = request.get("schema_kind", "task")
        if schema_kind == "host_classification":
            content = {"multiple_steps": task["family"] not in ("short_sourced_answer",),
                       "broad_project": False, "ambiguous": False,
                       "depends_on_context": bool(task.get("context")),
                       "rationale": "Mock host classification from task family."}
        elif schema_kind == "host_compression":
            content = {"sources": {sid: {"title": s["title"], "text": s["text"][:1150]}
                                   for sid, s in list(task["sources"].items())[:6]}}
        elif schema_kind == "native_artifact":
            text = request["messages"][-1]["content"]
            payload = json.loads(text.split("\n\n", 1)[1] if not text.lstrip().startswith("{") else text)
            is_output = payload.get("unit", {}).get("id") in (None, "output")
            candidate = self._correct_candidate(task, key) if rng.random() < p else self._wrong_candidate(task, key, rng)
            content = {"text": json.dumps(candidate) if is_output else "Unit result (mock).",
                       "data": {"summary": "mock unit summary", "claims": [], "unresolved": [],
                                "parent_hashes": payload["required_parent_hashes"],
                                "source_hashes": payload["required_source_hashes"]},
                       "source_ids": list(payload["sources"])[:1], "five_scores": [4] * 5, "self_probability": None}
        elif schema_kind == "checker":
            content = {"verdict": "pass", "failed_criteria": [], "reason": "mock", "missing_evidence": []}
        else:
            content = self._correct_candidate(task, key) if rng.random() < p else self._wrong_candidate(task, key, rng)
        prompt_bytes = len(json.dumps(request["messages"]).encode())
        out = WORKER_OUTPUT_TOKENS[request["effort"]]
        usage = {"prompt_tokens": math.ceil(prompt_bytes / 3.8), "completion_tokens": out,
                 "total_tokens": math.ceil(prompt_bytes / 3.8) + out,
                 "prompt_tokens_details": {"cached_tokens": 0, "cache_write_tokens": 0},
                 "completion_tokens_details": {"reasoning_tokens": max(0, out - 120)}}
        started = utc_now()
        return ProviderResult(status="ok", content=json.dumps(content), returned_model=request["model"],
                              returned_provider="MockAzure", provider_request_id="mock-" + meta["run_id"] + "-" + str(meta["call_index"]),
                              usage_raw=usage, started_at=started, ended_at=started, api_duration_ms=0.0,
                              error=None, measurement="mock")


class MockJev:
    measurement = "mock"

    def __init__(self, seed, luna_probability=0.55):
        self.seed, self.luna_probability = seed, luna_probability

    def decide(self, payload, meta):
        """payload: a validated Jev request {model, state, questions:{next:{type, instructions, criteria}}}."""
        phase = meta["phase"]
        rng = _rng(self.seed, "jev", meta["task"]["task_id"], meta["repetition_id"],
                   hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest())
        keys = list(payload["questions"]["next"]["criteria"])
        if phase in ("project_route",):
            choice = "five_unit"
        elif phase in ("authorize_unit", "route_task", "authorize_first_unit"):
            choice = "compute" if "compute" in keys else ("luna_low" if rng.random() < self.luna_probability else "sol_low")
            if choice not in keys:
                choice = next(k for k in keys if k not in ("stop", "retrieve_evidence"))
        elif phase in ("after_worker", "after_sol_high"):
            choice = "forward" if "forward" in keys else ("repair" if "repair" in keys else "stop")
        elif phase in ("after_worker_fused", "after_sol_high_fused"):
            forwards = [k for k in keys if k.startswith("forward_")]
            preferred = [k for k in forwards if k in ("forward_compute", "forward_finish", "forward_luna_low", "forward_sol_low")]
            if preferred:
                choice = ("forward_luna_low" if "forward_luna_low" in preferred and rng.random() < self.luna_probability
                          else ("forward_sol_low" if "forward_sol_low" in preferred else preferred[0]))
            else:
                retries = [k for k in keys if k.startswith("retry_")]
                choice = retries[0] if retries else "stop"
        else:
            choice = keys[0]
        k = len(keys)
        probabilities = {o: (0.55 if o == choice else round(0.45 / (k - 1), 4)) for o in keys}
        body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        usage_raw = {"input_tokens": math.ceil(len(body) * JEV_TOKENS_PER_BYTE),
                     "output_tokens": round(JEV_OUTPUT_A + JEV_OUTPUT_B * k)}
        started = utc_now()
        return ProviderResult(status="ok", content=None, answer={"choice": choice, "probabilities": probabilities,
                                                                  "confidence": round((k * 0.55 - 1) / (k - 1), 4)},
                              returned_model="typesafe/jev-1.13-mock", returned_provider="MockTypeSafe",
                              provider_request_id="mockjev-" + meta["run_id"] + "-" + str(meta["call_index"]),
                              usage_raw=usage_raw, started_at=started, ended_at=started, api_duration_ms=0.0,
                              error=None, measurement="mock")


_MOCK_FIXES = {
    "IMP-D": ("def parse_duration(text):\n    total, number = 0, ''\n    for ch in text:\n        if ch.isdigit():\n"
              "            number += ch\n        else:\n            total += int(number) * {'h': 3600, 'm': 60, 's': 1}[ch]\n"
              "            number = ''\n    return total\n"),
    "IMP-H": ("def convert_money(amount, currency, rates):\n    if currency not in rates:\n"
              "        raise ValueError('unsupported currency')\n    return round(amount * rates[currency], 2)\n"),
}


# ---------------------------------------------------------------- live adapters

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def _post(url, body, key, timeout):
    request = urllib.request.Request(url, data=body, method="POST", headers={
        "Authorization": "Bearer " + key, "Content-Type": "application/json", "Accept": "application/json"})
    with urllib.request.build_opener(_NoRedirect()).open(request, timeout=timeout) as response:
        if response.status != 200:
            raise urllib.error.HTTPError(url, response.status, "unexpected_status", response.headers, None)
        raw = response.read(1_048_577)
    if len(raw) > 1_048_576:
        raise ValueError("response_too_large")
    return json.loads(raw)


class OpenRouterChat:
    measurement = "live"
    URL = "https://openrouter.ai/api/v1/chat/completions"

    def __init__(self, provider_route="azure", provider_name="Azure", timeout=60, key_env="OPENROUTER_API_KEY"):
        self.provider_route, self.provider_name, self.timeout = provider_route, provider_name, timeout
        self._key = os.environ.get(key_env, "")
        if not self._key:
            raise RuntimeError("live_provider_requires_" + key_env)

    def complete(self, request, meta):
        payload = {"model": request["model"], "messages": request["messages"],
                   "reasoning": {"effort": request["effort"], "exclude": True},
                   "max_completion_tokens": request["max_output_tokens"],
                   "provider": {"only": [self.provider_route], "allow_fallbacks": False, "require_parameters": True},
                   "response_format": {"type": "json_object"}}
        body = json.dumps(payload, sort_keys=True).encode()
        started, t0 = utc_now(), time.monotonic()
        result = ProviderResult(status="failed", content=None, returned_model=None, returned_provider=None,
                                provider_request_id=None, usage_raw=None, started_at=started, ended_at=None,
                                api_duration_ms=None, error=None, measurement="live")
        try:
            response = _post(self.URL, body, self._key, self.timeout)
            result.update(provider_request_id=response.get("id"), returned_model=response.get("model"),
                          returned_provider=response.get("provider"), usage_raw=response.get("usage"))
            if response.get("error"):
                result["error"] = "http_200_error_body"
            elif result["returned_model"] != request["model"]:
                result["error"] = "returned_model_mismatch"
            elif result["returned_provider"] != self.provider_name:
                result["error"] = "provider_fallback_or_mismatch"
            elif not isinstance(response.get("usage"), dict):
                result["error"] = "missing_usage"
            else:
                choice = (response.get("choices") or [{}])[0]
                if choice.get("finish_reason") != "stop":
                    result["error"] = "incomplete_output:" + str(choice.get("finish_reason"))
                else:
                    result.update(status="ok", content=(choice.get("message") or {}).get("content"))
        except urllib.error.HTTPError as error:
            result["error"] = "http_error:" + str(error.code)
        except (urllib.error.URLError, OSError, TimeoutError, ValueError) as error:
            result["error"] = "transport:" + type(error).__name__
        result["ended_at"] = utc_now()
        result["api_duration_ms"] = round((time.monotonic() - t0) * 1000, 3)
        return result


class OpenRouterJev:
    measurement = "live"

    def __init__(self, scripts_dir, model="typesafe/jev-1.13", timeout=30):
        import sys
        sys.path.insert(0, str(scripts_dir))
        import jev_decide
        self.jev, self.model, self.timeout = jev_decide, model, timeout
        self._key = os.environ.get("OPENROUTER_API_KEY", "")
        if not self._key:
            raise RuntimeError("live_provider_requires_OPENROUTER_API_KEY")

    def decide(self, payload, meta):
        request = payload
        started, t0 = utc_now(), time.monotonic()
        result = ProviderResult(status="failed", content=None, answer=None, returned_model=None,
                                returned_provider=None, provider_request_id=None, usage_raw=None,
                                started_at=started, ended_at=None, api_duration_ms=None, error=None, measurement="live")
        try:
            body = self.jev.validate_request(request, "openrouter")
            response, _ = self.jev.call_api("openrouter", body, self._key, self.timeout)
            result.update(provider_request_id=response.get("id"), returned_model=response.get("model"),
                          returned_provider=response.get("provider"), usage_raw=response.get("usage"))
            self.jev.validate_response(response, request)
            result.update(status="ok", answer=response["answers"]["next"])
        except self.jev.Failure as failure:
            result["error"] = "jev:" + failure.code
        result["ended_at"] = utc_now()
        result["api_duration_ms"] = round((time.monotonic() - t0) * 1000, 3)
        return result
