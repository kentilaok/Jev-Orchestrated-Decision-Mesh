#!/usr/bin/env python3
"""One bounded Jev decision call; Python 3.10+ standard library only.

Schemas: https://openrouter.ai/openapi.json and https://docs.typesafe.ai/api
The 28,000-byte request ceiling is a conservative local guard, not tokenization.
No retries, redirects, endpoint overrides, model fallback, or key persistence.
"""
import argparse
import getpass
import hashlib
import http.client
import json
import math
import os
from pathlib import Path
import re
import sys
import tempfile
import time
import urllib.error
import urllib.request

ENDPOINTS = {
    "openrouter": ("https://openrouter.ai/api/alpha/decisions", "OPENROUTER_API_KEY"),
    "typesafe": ("https://api.typesafe.ai/v1/systemone", "TYPESAFE_API_KEY"),
}
MAX_REQUEST_BYTES = 28_000
MAX_RESPONSE_BYTES = 1_048_576
TOLERANCE = 0.001


class Failure(Exception):
    def __init__(self, code, status=None):
        self.code, self.status = code, status
        super().__init__(code)


def require(condition, code):
    if not condition:
        raise Failure(code)


def decode_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, "duplicate_json_key")
            result[key] = value
        return result

    def constant(_):
        raise Failure("nonfinite_json_number")

    try:
        return json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)
    except (ValueError, UnicodeError, RecursionError):
        raise Failure("invalid_json") from None


def guidance(value):
    return isinstance(value, (str, dict, list)) and bool(
        value.strip() if isinstance(value, str) else value)


def bounded_json(value, depth=0):
    require(depth <= 16, "json_nesting_too_deep")
    if isinstance(value, dict):
        for key, child in value.items():
            require(isinstance(key, str), "invalid_json_key")
            bounded_json(child, depth + 1)
    elif isinstance(value, list):
        for child in value:
            bounded_json(child, depth + 1)
    elif isinstance(value, float):
        require(math.isfinite(value), "nonfinite_json_number")


def validate_request(request, provider):
    require(isinstance(request, dict), "request_must_be_object")
    require(set(request) == {"model", "state", "questions"}, "invalid_request_fields")
    model = request["model"]
    prefix = r"~?typesafe/" if provider == "openrouter" else ""
    require(isinstance(model, str) and re.fullmatch(prefix + r"jev-[A-Za-z0-9._-]+", model),
            "explicit_provider_jev_model_required")
    require(guidance(request["state"]), "state_must_be_nonempty")
    questions = request["questions"]
    require(isinstance(questions, dict) and 1 <= len(questions) <= 32, "invalid_questions")
    for name, question in questions.items():
        require(isinstance(name, str) and 1 <= len(name.strip()) <= 128, "invalid_question_id")
        require(isinstance(question, dict) and set(question) <= {"type", "instructions", "criteria"},
                "invalid_question_fields")
        kind, criteria = question.get("type"), question.get("criteria")
        require(kind in ("choice", "score", "noul"), "invalid_question_type")
        require(guidance(question.get("instructions")), "instructions_must_be_nonempty")
        if kind == "choice":
            require(isinstance(criteria, dict) and 2 <= len(criteria) <= 255, "invalid_choice_criteria")
            require(all(isinstance(k, str) and k.strip() and len(k) <= 128 and
                        (v is None or guidance(v)) for k, v in criteria.items()), "invalid_choice_option")
        elif kind == "score":
            require(isinstance(criteria, list) and 2 <= len(criteria) <= 10 and
                    all(guidance(v) for v in criteria), "invalid_score_criteria")
        elif "criteria" in question:
            require(isinstance(criteria, dict) and set(criteria) == {"true", "false"} and
                    all(guidance(v) for v in criteria.values()), "invalid_noul_criteria")
    bounded_json(request)
    try:
        body = json.dumps(request, sort_keys=True, ensure_ascii=True,
                          separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (ValueError, TypeError, UnicodeError):
        raise Failure("invalid_json") from None
    require(len(body) <= MAX_REQUEST_BYTES, "request_exceeds_28000_byte_guard")
    return body


def number(value, low, high):
    return (type(value) is int or (type(value) is float and math.isfinite(value))) and low <= value <= high


def distribution(value, keys, warnings, question_id):
    require(isinstance(value, dict) and set(value) == set(keys), "invalid_probability_options")
    require(all(number(p, 0, 1) for p in value.values()), "invalid_probability_value")
    total = sum(value.values())
    difference, allowed = abs(total - 1), min(0.02, 0.005 * len(keys))
    # Independent two-decimal rounding is a local compatibility assumption, not an API promise.
    require(difference <= allowed + 1e-12, "invalid_probability_sum")
    if difference > TOLERANCE:
        warnings.append({"code": "probability_sum_rounding", "question_id": question_id,
                         "returned_sum": round(total, 12), "absolute_difference": round(difference, 12),
                         "allowed_difference": allowed, "assumption": "independent_2_decimal_rounding"})


def validate_usage(response):
    usage = response.get("usage")
    require(usage is None or isinstance(usage, dict), "invalid_usage")
    bounded_json(usage)
    counters = {key: (usage or {}).get(key) for key in ("input_tokens", "output_tokens", "total_tokens")}
    require(all(v is None or (type(v) is int and v >= 0) for v in counters.values()), "invalid_usage_counter")
    cost = (usage or {}).get("cost")
    require(cost is None or number(cost, 0, float("inf")), "invalid_usage_cost")
    return counters


def validate_response(response, request, warnings=None):
    warnings = [] if warnings is None else warnings
    require(isinstance(response, dict) and "error" not in response, "invalid_response")
    counters = validate_usage(response)
    bounded_json(response)
    require(isinstance(response.get("model"), str) and response["model"].strip(), "missing_response_model")
    requested = request["model"].removeprefix("~").removeprefix("typesafe/")
    returned = response["model"].removeprefix("typesafe/")
    require(re.fullmatch(r"jev-[A-Za-z0-9._-]+", returned) and
            (requested == "jev-latest" or returned == requested or
             returned.startswith((requested + ".", requested + "-"))), "response_model_mismatch")
    answers = response.get("answers")
    require(isinstance(answers, dict) and set(answers) == set(request["questions"]), "answer_keys_mismatch")
    for name, question in request["questions"].items():
        answer, kind = answers[name], question["type"]
        require(isinstance(answer, dict) and answer.get("type") == kind, "answer_type_mismatch")
        if kind == "noul":
            require(number(answer.get("noul"), 0, 1), "invalid_noul_value")
            continue
        require(number(answer.get("confidence"), 0, 1), "invalid_confidence")
        keys = question["criteria"] if kind == "choice" else [str(i) for i in range(len(question["criteria"]))]
        probabilities = answer.get("probabilities")
        distribution(probabilities, keys, warnings, name)
        if kind == "choice":
            choice = answer.get("choice")
            require(isinstance(choice, str) and choice in keys, "invalid_choice_value")
            require(probabilities[choice] + TOLERANCE >= max(probabilities.values()), "choice_not_most_probable")
        else:
            require(number(answer.get("score"), 0, len(keys) - 1), "invalid_score_value")
            require(isinstance(answer.get("legend"), dict) and set(answer["legend"]) == set(keys), "invalid_score_legend")
            require(all(answer["legend"][str(i)] == v for i, v in enumerate(question["criteria"])), "score_legend_mismatch")
            expected = sum(int(k) * p for k, p in probabilities.items())
            difference = abs(answer["score"] - expected)
            # Quantization bound assumes score and each probability were rounded independently.
            allowed = 0.005 * (1 + sum(range(len(keys))))
            require(difference <= allowed + 1e-12, "score_distribution_mismatch")
            if difference > TOLERANCE * len(keys):
                warnings.append({"code": "score_rounding_difference", "question_id": name,
                                 "returned_score": answer["score"], "weighted_score": round(expected, 12),
                                 "absolute_difference": round(difference, 12), "allowed_difference": allowed,
                                 "assumption": "independent_2_decimal_rounding"})
    return counters


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def call_api(provider, body, key, timeout):
    require(isinstance(key, str) and 1 <= len(key) <= 4096 and key.isascii() and
            not any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in key), "invalid_or_missing_api_key")
    request = urllib.request.Request(ENDPOINTS[provider][0], data=body, method="POST", headers={
        "Authorization": "Bearer " + key, "Content-Type": "application/json", "Accept": "application/json"})
    started = time.monotonic()
    try:
        with urllib.request.build_opener(NoRedirect()).open(request, timeout=timeout) as response:
            require(response.status == 200, "unexpected_http_status")
            raw = response.read(MAX_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as error:
        raise Failure("http_error", error.code) from None
    except (urllib.error.URLError, TimeoutError, OSError, ValueError, http.client.HTTPException):
        raise Failure("network_error") from None
    require(len(raw) <= MAX_RESPONSE_BYTES, "response_too_large")
    return decode_json(raw), round((time.monotonic() - started) * 1000, 3)


def write_result(path, result):
    encoded = json.dumps(result, ensure_ascii=True, indent=2, allow_nan=False) + "\n"
    temp = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=".jev-", suffix=".tmp", delete=False) as stream:
            temp = Path(stream.name)
            stream.write(encoded)
        os.replace(temp, path)
    finally:
        if temp is not None and temp.exists():
            temp.unlink()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", required=True, type=Path, help="UTF-8 JSON: model, state, questions")
    parser.add_argument("--out", required=True, type=Path, help="JSON result path; parent directory must exist")
    parser.add_argument("--provider", choices=ENDPOINTS, default="openrouter")
    parser.add_argument("--dry-run", action="store_true", help="validate offline; no key or network needed")
    parser.add_argument("--key-stdin", action="store_true", help="read transient key from stdin (hidden prompt in a terminal)")
    parser.add_argument("--timeout", type=float, default=30, help="network timeout seconds, 1-120 (default 30)")
    args = parser.parse_args(argv)
    result = {"status": "failed", "provider": args.provider}
    safe_output = False
    try:
        require(args.request.resolve() != args.out.resolve(), "output_must_differ_from_request")
        safe_output = True
        require(number(args.timeout, 1, 120), "invalid_timeout")
        with args.request.open("rb") as stream:
            raw = stream.read(256_001)
        require(len(raw) <= 256_000, "request_file_too_large")
        request = decode_json(raw.decode("utf-8-sig"))
        body = validate_request(request, args.provider)
        result.update(requested_model=request["model"], returned_model=None,
                      request_sha256=hashlib.sha256(body).hexdigest(), request_bytes=len(body),
                      answers=None, usage={"input_tokens": None, "output_tokens": None, "total_tokens": None},
                      usage_raw=None, latency_ms=None, warnings=[])
        if args.dry_run:
            result["status"] = "dry_run"
        else:
            key = (getpass.getpass("API key: ") if sys.stdin.isatty() else sys.stdin.readline(4098).strip()) if args.key_stdin else os.environ.get(ENDPOINTS[args.provider][1], "")
            response, latency = call_api(args.provider, body, key, args.timeout)
            del key
            result["latency_ms"] = latency
            require(isinstance(response, dict), "invalid_response")
            result.update(returned_model=response.get("model") if isinstance(response.get("model"), str) else None,
                          upstream_provider=response.get("provider") if isinstance(response.get("provider"), str) else None)
            result["usage"] = validate_usage(response)
            result["usage_raw"] = response.get("usage")
            counters = validate_response(response, request, result["warnings"])
            result.update(status="ok", answers=response["answers"], usage=counters)
    except Failure as error:
        result["error"] = {"code": error.code, "http_status": error.status}
    except (OSError, ValueError, UnicodeError, RecursionError):
        result["error"] = {"code": "local_io_or_json_error", "http_status": None}
    if safe_output:
        try:
            write_result(args.out, result)
        except (OSError, ValueError, TypeError):
            result = {"status": "failed", "error": {"code": "output_write_failed", "http_status": None}}
    print(json.dumps({k: result[k] for k in ("status", "error") if k in result}))
    return 0 if result["status"] in ("ok", "dry_run") else 2


if __name__ == "__main__":
    sys.exit(main())
