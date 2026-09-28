"""Bounded, tool-free Claude Code CLI producer for a CIDM broker.

Runs one headless `claude -p` call with an exact model and effort, no tools, no
session persistence and a JSON Schema for the artifact. Same contract as
CodexCliAdapter.run so NativeTransitionBroker can use either host.

Accounting semantics (differ from OpenAI-style counters):
- Anthropic reports `input_tokens` EXCLUDING cache reads and cache writes. This
  adapter returns `input_tokens` as the total (uncached + cache write + cache
  read), with `cached_input_tokens` and `cache_write_input_tokens` as subsets,
  matching the rest of CIDM.
- `total_cost_usd` from the CLI is an API-list-price estimate. Under a Claude
  subscription it is not a bill; it is returned as `api_equivalent_cost_usd`.
- Served identity comes from the CLI's per-model usage report (`modelUsage`).
  Effort is never reported back, so `actual_effort` stays None.
The output field names follow Claude Code 2.1.x headless JSON; verify them on
your installed version before relying on live results.
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
import subprocess
import tempfile
import time

from codex_cli_adapter import CodexCliError, _check_schema, _matches, _strict_json

PERMITTED_MODELS = frozenset({"claude-sonnet-5", "claude-opus-5"})
PERMITTED_EFFORTS = frozenset({"low", "medium", "high", "xhigh"})


class ClaudeCliError(CodexCliError):
    """A bounded Claude Code call could not be accepted by the broker.

    `usage` holds counters the call reported before it was rejected (None if
    unknown); `ran` is True once a process was launched.
    """


def _count(value):
    if type(value) is not int or value < 0:
        raise ClaudeCliError("invalid_usage_counter")
    return value


def _usage(raw):
    if not isinstance(raw, dict):
        return None
    uncached = _count(raw.get("input_tokens", 0))
    write = _count(raw.get("cache_creation_input_tokens", 0))
    read = _count(raw.get("cache_read_input_tokens", 0))
    output = _count(raw.get("output_tokens", 0))
    if "input_tokens" not in raw or "output_tokens" not in raw:
        raise ClaudeCliError("missing_usage_counter")
    return {"input_tokens": uncached + write + read, "cached_input_tokens": read,
            "cache_write_input_tokens": write, "output_tokens": output,
            "reasoning_output_tokens": None,
            "semantics": "input_tokens = uncached + cache_write + cache_read (Anthropic reports them separately)"}


class ClaudeCliAdapter:
    """Run one schema-bounded worker or checker through the signed-in Claude Code CLI."""

    def __init__(self, *, timeout_seconds=300, max_stdout_bytes=2_097_152, max_prompt_bytes=48_000,
                 max_schema_bytes=65_536, executable="claude", secret_env_names=()):
        limits = (timeout_seconds, max_stdout_bytes, max_prompt_bytes, max_schema_bytes)
        if any(type(v) is not int or v <= 0 for v in limits) or timeout_seconds > 900:
            raise ValueError("invalid_adapter_limits")
        if not isinstance(executable, str) or not executable:
            raise ValueError("invalid_claude_executable")
        self.timeout_seconds, self.max_stdout_bytes = timeout_seconds, max_stdout_bytes
        self.max_prompt_bytes, self.max_schema_bytes = max_prompt_bytes, max_schema_bytes
        self.executable = executable
        # Claude's own credentials stay; unrelated provider keys never reach the child.
        self.secret_env_names = frozenset(n.upper() for n in secret_env_names) | {
            "OPENROUTER_API_KEY", "OPENAI_API_KEY", "CODEX_API_KEY", "GITHUB_TOKEN", "GH_TOKEN", "TYPESAFE_API_KEY"}

    def _execute(self, argv, workspace, prompt_path, stdout_path, stderr_path):
        deadline = time.monotonic() + self.timeout_seconds
        with prompt_path.open("rb") as prompt, stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
            env = {k: v for k, v in os.environ.items() if k.upper() not in self.secret_env_names}
            try:
                process = subprocess.Popen(argv, cwd=str(workspace), stdin=prompt, stdout=stdout,
                                           stderr=stderr, shell=False, env=env)
            except OSError as exc:
                raise ClaudeCliError("claude_cli_unavailable") from exc
            try:
                while process.poll() is None:
                    if os.fstat(stdout.fileno()).st_size > self.max_stdout_bytes:
                        raise ClaudeCliError("claude_output_limit")
                    if time.monotonic() >= deadline:
                        raise ClaudeCliError("claude_timeout")
                    time.sleep(0.05)
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=5)
            return process.returncode

    def run(self, model, effort, prompt, schema, workspace):
        if model not in PERMITTED_MODELS or effort not in PERMITTED_EFFORTS:
            raise ClaudeCliError("worker_route_not_permitted")
        if not isinstance(prompt, str) or not prompt.strip():
            raise ClaudeCliError("invalid_prompt")
        bounded = ("Use only the evidence in this prompt. Do not call tools, open files, or browse. "
                   "Return one JSON object that matches the output schema.\n\n" + prompt)
        if len(bounded.encode("utf-8")) > self.max_prompt_bytes:
            raise ClaudeCliError("prompt_byte_limit")
        try:
            root = Path(workspace).resolve(strict=True)
        except (OSError, TypeError, ValueError) as exc:
            raise ClaudeCliError("invalid_workspace") from exc
        if not isinstance(schema, dict) or schema.get("type") != "object":
            raise ClaudeCliError("invalid_artifact_schema")
        _check_schema(schema)
        encoded_schema = json.dumps(schema, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        if len(encoded_schema.encode("utf-8")) > self.max_schema_bytes:
            raise ClaudeCliError("schema_byte_limit")
        argv = [self.executable, "-p", "--output-format", "json", "--model", model, "--effort", effort,
                "--tools", "", "--strict-mcp-config", "--no-session-persistence",
                "--json-schema", encoded_schema]
        with tempfile.TemporaryDirectory(prefix="cidm-claude-") as temp:
            folder = Path(temp)
            prompt_path, stdout_path, stderr_path = folder / "prompt.txt", folder / "stdout.json", folder / "stderr.txt"
            prompt_path.write_text(bounded, encoding="utf-8")
            try:
                returncode = self._execute(argv, root, prompt_path, stdout_path, stderr_path)
            except ClaudeCliError as exc:
                exc.ran = str(exc) != "claude_cli_unavailable"
                raise
            raw = stdout_path.read_bytes()
        try:
            return self._parse(raw, returncode, model, effort, schema)
        except CodexCliError as exc:
            exc.ran = True
            raise

    def _parse(self, raw, returncode, model, effort, schema):
        try:
            result = _strict_json(raw.decode("utf-8"))
        except UnicodeError as exc:
            raise ClaudeCliError("invalid_output_encoding") from exc
        if not isinstance(result, dict) or result.get("type") != "result":
            raise ClaudeCliError("unexpected_claude_output")
        usage = _usage(result.get("usage"))
        try:
            if returncode != 0 or result.get("is_error") is not False or result.get("subtype") != "success":
                raise ClaudeCliError("claude_call_failed")
            served = result.get("modelUsage")
            served_models = sorted(served) if isinstance(served, dict) else []
            if served_models and not any(name == model or name.startswith(model + "-") for name in served_models):
                raise ClaudeCliError("model_identity_conflict")
            artifact = result.get("structured_output")
            if not isinstance(artifact, dict):
                artifact = _strict_json(result.get("result") or "")
            if not isinstance(artifact, dict) or not _matches(schema, artifact):
                raise ClaudeCliError("artifact_schema_mismatch")
        except CodexCliError as exc:
            exc.usage = usage
            raise
        cost = result.get("total_cost_usd")
        confirmed = [name for name in served_models if name == model or name.startswith(model + "-")]
        return {"artifact": artifact, "usage": usage,
                "requested_model": model, "requested_effort": effort,
                "actual_model": model if confirmed else None, "actual_effort": None,
                "served_models": served_models,
                "identity_verification": ("reported_match" if confirmed and len(served_models) == 1
                                          else "reported_match_with_auxiliary_models" if confirmed
                                          else "requested_only"),
                "api_equivalent_cost_usd": cost if type(cost) in (int, float) and math.isfinite(cost) else None,
                "num_turns": result.get("num_turns"), "session_id": result.get("session_id"), "events": []}
