"""Bounded, read-only Codex CLI producer for a CIDM broker.

This adapter asks Codex for one structured artifact and accepts no tool actions.
The CLI documents requested model and effort flags, but its usual JSONL stream
does not attest the model actually served. Callers must keep that distinction.
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
import subprocess
import tempfile
import time


class CodexCliError(RuntimeError):
    """A bounded worker call could not be accepted by the broker."""


_ITEM_TYPES = frozenset({"agent_message", "reasoning"})
_EVENT_TYPES = frozenset({"thread.started", "turn.started", "turn.completed",
                          "turn.failed", "error", "item.started", "item.updated",
                          "item.completed"})
_SCHEMA_KEYS = frozenset({"type", "properties", "required", "additionalProperties",
                          "items", "enum", "minimum", "maximum", "minLength",
                          "maxLength", "minItems", "maxItems", "description", "title"})
_JSON_TYPES = frozenset({"object", "array", "string", "integer", "number", "boolean", "null"})


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise CodexCliError("duplicate_json_key")
        result[key] = value
    return result


def _strict_json(text):
    def invalid_constant(_):
        raise CodexCliError("nonfinite_json_number")
    try:
        return json.loads(text, object_pairs_hook=_unique_object,
                          parse_constant=invalid_constant)
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise CodexCliError("invalid_json") from exc


def _schema_type(value, name):
    if name == "object":
        return isinstance(value, dict)
    if name == "array":
        return isinstance(value, list)
    if name == "string":
        return isinstance(value, str)
    if name == "integer":
        return type(value) is int
    if name == "number":
        return type(value) in (int, float) and math.isfinite(value)
    if name == "boolean":
        return type(value) is bool
    return value is None


def _check_schema(schema, depth=0):
    """Accept only the schema subset this module can independently validate."""
    if depth > 16 or not isinstance(schema, dict) or not set(schema) <= _SCHEMA_KEYS:
        raise CodexCliError("unsupported_schema")
    kinds = schema.get("type")
    kinds = [kinds] if isinstance(kinds, str) else kinds
    if (not isinstance(kinds, list) or not kinds
            or any(not isinstance(k, str) or k not in _JSON_TYPES for k in kinds)):
        raise CodexCliError("unsupported_schema_type")
    if "object" in kinds:
        props = schema.get("properties")
        required = schema.get("required")
        if (not isinstance(props, dict) or not isinstance(required, list)
                or any(not isinstance(key, str) for key in props)
                or any(not isinstance(key, str) for key in required)
                or len(required) != len(set(required))
                or not set(required) <= set(props)
                or schema.get("additionalProperties") is not False):
            raise CodexCliError("unsupported_object_schema")
        for child in props.values():
            _check_schema(child, depth + 1)
    elif any(k in schema for k in ("properties", "required", "additionalProperties")):
        raise CodexCliError("unsupported_object_schema")
    if "array" in kinds:
        if not isinstance(schema.get("items"), dict):
            raise CodexCliError("unsupported_array_schema")
        _check_schema(schema["items"], depth + 1)
    elif "items" in schema:
        raise CodexCliError("unsupported_array_schema")
    for key in ("minimum", "maximum"):
        if key in schema and (type(schema[key]) not in (int, float) or not math.isfinite(schema[key])):
            raise CodexCliError("unsupported_schema_bound")
    for key in ("minLength", "maxLength", "minItems", "maxItems"):
        if key in schema and (type(schema[key]) is not int or schema[key] < 0):
            raise CodexCliError("unsupported_schema_bound")
    if "enum" in schema and (not isinstance(schema["enum"], list) or not schema["enum"]):
        raise CodexCliError("unsupported_schema_enum")
    if ((any(key in schema for key in ("minimum", "maximum"))
         and not any(kind in kinds for kind in ("integer", "number")))
            or (any(key in schema for key in ("minLength", "maxLength")) and "string" not in kinds)
            or (any(key in schema for key in ("minItems", "maxItems")) and "array" not in kinds)):
        raise CodexCliError("misplaced_schema_bound")
    for minimum, maximum in (("minimum", "maximum"), ("minLength", "maxLength"),
                             ("minItems", "maxItems")):
        if minimum in schema and maximum in schema and schema[minimum] > schema[maximum]:
            raise CodexCliError("inverted_schema_bound")


def _matches(schema, value):
    kinds = schema["type"]
    kinds = [kinds] if isinstance(kinds, str) else kinds
    if not any(_schema_type(value, kind) for kind in kinds):
        return False
    if "enum" in schema and value not in schema["enum"]:
        return False
    if isinstance(value, dict):
        props = schema["properties"]
        return (set(schema["required"]) <= set(value) and set(value) <= set(props)
                and all(_matches(props[key], child) for key, child in value.items()))
    if isinstance(value, list):
        return (len(value) >= schema.get("minItems", 0)
                and len(value) <= schema.get("maxItems", len(value))
                and all(_matches(schema["items"], child) for child in value))
    if isinstance(value, str):
        return (len(value) >= schema.get("minLength", 0)
                and len(value) <= schema.get("maxLength", len(value)))
    if type(value) in (int, float):
        return (value >= schema.get("minimum", value)
                and value <= schema.get("maximum", value))
    return True


def _counter(value):
    if type(value) is not int or value < 0:
        raise CodexCliError("invalid_usage_counter")
    return value


def _usage(value):
    if value is None:
        return None
    if not isinstance(value, dict):
        raise CodexCliError("invalid_usage")
    result = {}
    for key in ("input_tokens", "output_tokens", "cached_input_tokens", "reasoning_output_tokens"):
        result[key] = _counter(value[key]) if key in value else None
    if result["input_tokens"] is None or result["output_tokens"] is None:
        raise CodexCliError("missing_usage_counter")
    if (result["cached_input_tokens"] is not None
            and result["cached_input_tokens"] > result["input_tokens"]):
        raise CodexCliError("invalid_cached_usage")
    if (result["reasoning_output_tokens"] is not None
            and result["reasoning_output_tokens"] > result["output_tokens"]):
        raise CodexCliError("invalid_reasoning_usage")
    return result


class CodexCliAdapter:
    """Run one schema-bounded worker through the signed-in Codex CLI.

    The broker owns the workspace and prompts. No shell is used, the workspace
    is read-only, and action items in the JSONL stream invalidate the result.
    """

    def __init__(self, *, timeout_seconds=120, max_stdout_bytes=1_048_576,
                 max_stderr_bytes=65_536, max_prompt_bytes=24_000,
                 max_schema_bytes=65_536, max_events=256,
                 astra_explicitly_authorized=False, executable="codex",
                 secret_env_names=()):
        limits = (timeout_seconds, max_stdout_bytes, max_stderr_bytes,
                  max_prompt_bytes, max_schema_bytes, max_events)
        if (any(type(v) is not int or v <= 0 for v in limits)
                or timeout_seconds > 600 or max_stdout_bytes > 4_194_304
                or max_stderr_bytes > 262_144 or max_prompt_bytes > 131_072
                or max_schema_bytes > 262_144 or max_events > 1024):
            raise ValueError("invalid_adapter_limits")
        if type(astra_explicitly_authorized) is not bool:
            raise ValueError("invalid_astra_authorization")
        if not isinstance(executable, str) or not executable:
            raise ValueError("invalid_codex_executable")
        if (not isinstance(secret_env_names, (tuple, list, set, frozenset))
                or any(not isinstance(name, str) or not name or "=" in name
                       for name in secret_env_names)):
            raise ValueError("invalid_secret_env_names")
        self.timeout_seconds = timeout_seconds
        self.max_stdout_bytes = max_stdout_bytes
        self.max_stderr_bytes = max_stderr_bytes
        self.max_prompt_bytes = max_prompt_bytes
        self.max_schema_bytes = max_schema_bytes
        self.max_events = max_events
        self.astra_explicitly_authorized = astra_explicitly_authorized
        self.executable = executable
        self.secret_env_names = frozenset(name.upper() for name in secret_env_names) | {
            "OPENROUTER_API_KEY", "OPENAI_API_KEY", "CODEX_API_KEY", "GITHUB_TOKEN", "GH_TOKEN"
        }

    def _execute(self, argv, workspace, prompt_path, stdout_path, stderr_path):
        deadline = time.monotonic() + self.timeout_seconds
        with prompt_path.open("rb") as prompt, stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
            try:
                child_env = {key: value for key, value in os.environ.items()
                             if key.upper() not in self.secret_env_names}
                process = subprocess.Popen(argv, cwd=str(workspace), stdin=prompt,
                                           stdout=stdout, stderr=stderr, shell=False,
                                           env=child_env)
            except OSError as exc:
                raise CodexCliError("codex_cli_unavailable") from exc
            try:
                while process.poll() is None:
                    if (os.fstat(stdout.fileno()).st_size > self.max_stdout_bytes
                            or os.fstat(stderr.fileno()).st_size > self.max_stderr_bytes):
                        raise CodexCliError("codex_output_limit")
                    if time.monotonic() >= deadline:
                        raise CodexCliError("codex_timeout")
                    time.sleep(0.05)
                if (os.fstat(stdout.fileno()).st_size > self.max_stdout_bytes
                        or os.fstat(stderr.fileno()).st_size > self.max_stderr_bytes):
                    raise CodexCliError("codex_output_limit")
                if process.returncode != 0:
                    raise CodexCliError("codex_nonzero_exit")
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=5)

    def run(self, model, effort, prompt, schema, workspace):
        permitted = {"gpt-6-luna", "gpt-6-sol"}
        if self.astra_explicitly_authorized:
            permitted.add("gpt-6-astra")
        if (not isinstance(model, str) or not isinstance(effort, str)
                or model not in permitted or effort not in {"low", "medium", "high", "xhigh"}):
            raise CodexCliError("worker_route_not_permitted")
        if model == "gpt-6-astra" and effort != "low":
            raise CodexCliError("astra_effort_not_permitted")
        if not isinstance(prompt, str) or not prompt.strip():
            raise CodexCliError("invalid_prompt")
        bounded_prompt = ("Use only the evidence in this prompt. Do not call tools, open files, "
                          "or browse. Return one JSON object that matches the output schema.\n\n" + prompt)
        try:
            prompt_bytes = bounded_prompt.encode("utf-8")
        except UnicodeError as exc:
            raise CodexCliError("invalid_prompt_encoding") from exc
        if len(prompt_bytes) > self.max_prompt_bytes:
            raise CodexCliError("prompt_byte_limit")
        try:
            root = Path(workspace).resolve(strict=True)
        except (OSError, TypeError, ValueError) as exc:
            raise CodexCliError("invalid_workspace") from exc
        if not root.is_dir():
            raise CodexCliError("invalid_workspace")
        if not isinstance(schema, dict) or schema.get("type") != "object":
            raise CodexCliError("invalid_artifact_schema")
        _check_schema(schema)
        try:
            encoded_schema = json.dumps(schema, ensure_ascii=False, allow_nan=False,
                                        separators=(",", ":")).encode("utf-8")
        except (TypeError, ValueError, UnicodeError) as exc:
            raise CodexCliError("invalid_artifact_schema") from exc
        if len(encoded_schema) > self.max_schema_bytes:
            raise CodexCliError("schema_byte_limit")
        with tempfile.TemporaryDirectory(prefix="cidm-codex-") as temp:
            folder = Path(temp)
            schema_path = folder / "schema.json"
            prompt_path = folder / "prompt.txt"
            stdout_path = folder / "stdout.jsonl"
            stderr_path = folder / "stderr.txt"
            schema_path.write_bytes(encoded_schema)
            prompt_path.write_text(bounded_prompt, encoding="utf-8")
            argv = [self.executable, "exec", "--json", "--ephemeral", "--ignore-user-config",
                    "--skip-git-repo-check",
                    "-s", "read-only", "-m", model,
                    "-c", f"model_reasoning_effort={effort}",
                    "-C", str(root), "--output-schema", str(schema_path), "-"]
            self._execute(argv, root, prompt_path, stdout_path, stderr_path)
            raw = stdout_path.read_bytes()
        if len(raw) > self.max_stdout_bytes:
            raise CodexCliError("codex_output_limit")
        try:
            lines = raw.decode("utf-8").splitlines()
        except UnicodeError as exc:
            raise CodexCliError("invalid_jsonl_encoding") from exc
        if not lines or len(lines) > self.max_events or any(not line.strip() for line in lines):
            raise CodexCliError("invalid_jsonl_length")
        summaries = []
        phase = "expect_thread"
        artifact_text = None
        usage = None
        reported_model = None
        reported_effort = None
        for line in lines:
            event = _strict_json(line)
            if not isinstance(event, dict):
                raise CodexCliError("invalid_codex_event")
            kind = event.get("type")
            if kind not in _EVENT_TYPES or kind in {"turn.failed", "error"}:
                raise CodexCliError("unexpected_codex_event")
            if "model" in event:
                if not isinstance(event["model"], str) or event["model"] != model:
                    raise CodexCliError("model_identity_conflict")
                reported_model = event["model"]
            for key in ("effort", "model_reasoning_effort"):
                if key in event:
                    if not isinstance(event[key], str) or event[key] != effort:
                        raise CodexCliError("effort_identity_conflict")
                    reported_effort = event[key]
            if kind == "thread.started":
                if phase != "expect_thread":
                    raise CodexCliError("invalid_codex_event_order")
                phase = "expect_turn"
            elif kind == "turn.started":
                if phase != "expect_turn":
                    raise CodexCliError("invalid_codex_event_order")
                phase = "in_turn"
            elif kind.startswith("item."):
                if phase != "in_turn" or not isinstance(event.get("item"), dict):
                    raise CodexCliError("invalid_codex_event_order")
                item = event["item"]
                if item.get("type") not in _ITEM_TYPES:
                    raise CodexCliError("unexpected_codex_action")
                summaries.append({"type": kind, "item_type": item["type"]})
                if kind == "item.completed" and item["type"] == "agent_message":
                    if artifact_text is not None or not isinstance(item.get("text"), str):
                        raise CodexCliError("ambiguous_final_artifact")
                    artifact_text = item["text"]
                continue
            elif kind == "turn.completed":
                if phase != "in_turn" or artifact_text is None:
                    raise CodexCliError("incomplete_codex_turn")
                usage = _usage(event.get("usage"))
                phase = "complete"
            summaries.append({"type": kind})
        if phase != "complete":
            raise CodexCliError("missing_turn_completed")
        artifact = _strict_json(artifact_text)
        if not isinstance(artifact, dict) or not _matches(schema, artifact):
            raise CodexCliError("artifact_schema_mismatch")
        reported_match = reported_model is not None and reported_effort is not None
        return {"artifact": artifact, "usage": usage,
                "requested_model": model, "requested_effort": effort,
                "actual_model": reported_model if reported_match else None,
                "actual_effort": reported_effort if reported_match else None,
                "identity_verification": "reported_match" if reported_match else "requested_only",
                "events": summaries}
