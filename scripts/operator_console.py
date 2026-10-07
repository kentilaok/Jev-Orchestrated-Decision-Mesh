#!/usr/bin/env python3
"""Local web console for Jev + Hermes + frontier-model execution.

The server intentionally uses only Python's standard library. It binds to localhost
by default and never stores credentials. Hermes owns model authentication.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
CONSOLE_DIR = REPO_ROOT / "console"
MODEL_REGISTRY_PATH = CONSOLE_DIR / "frontier-models.json"
MAX_PROMPT_CHARS = 100_000
VALID_EFFORTS = {"none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra"}


def load_registry() -> dict[str, Any]:
    with MODEL_REGISTRY_PATH.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def enabled_models(registry: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    out: dict[tuple[str, str], dict[str, Any]] = {}
    for provider in registry.get("providers", []):
        if not provider.get("enabled"):
            continue
        for model in provider.get("models", []):
            out[(provider["id"], model["id"])] = model
    return out


def validate_selection(provider: str, model: str, effort: str, registry: dict[str, Any]) -> None:
    if (provider, model) not in enabled_models(registry):
        raise ValueError("Provider/model is not enabled in console/frontier-models.json")
    if effort not in VALID_EFFORTS:
        raise ValueError(f"Unsupported reasoning effort: {effort}")


def resolve_workspace(raw: str | None) -> Path:
    if not raw:
        return REPO_ROOT
    path = Path(raw).expanduser().resolve()
    if not path.is_dir():
        raise ValueError("Workspace must be an existing directory")
    return path


def hermes_version(binary: str | None) -> str | None:
    if not binary:
        return None
    try:
        proc = subprocess.run([binary, "--version"], text=True, capture_output=True, timeout=5, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    value = (proc.stdout or proc.stderr).strip().splitlines()
    return value[0][:120] if value else None


def runtime_status() -> dict[str, Any]:
    binary = shutil.which("hermes")
    anthropic_env = bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_TOKEN"))
    hermes_home = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))
    hermes_auth = (hermes_home / "auth.json").exists()
    claude_code_auth = (Path.home() / ".claude").exists()
    return {
        "hermes": {"available": bool(binary), "binary": binary, "version": hermes_version(binary)},
        "anthropic": {
            "configured": anthropic_env or hermes_auth or claude_code_auth,
            "detected_via": "environment" if anthropic_env else "Hermes/Claude credential store" if (hermes_auth or claude_code_auth) else None,
            "note": "Hermes performs the authoritative auth check at execution time."
        },
        "jev": {
            "configured": bool(os.environ.get("OPENROUTER_API_KEY")),
            "transport": "existing CIDM OpenRouter/TypeSafe gateway",
            "note": "The v1 console exposes readiness and route contracts; direct Hermes execution does not bypass CIDM acceptance rules."
        },
        "bind_default": "127.0.0.1"
    }


def build_route(body: dict[str, Any], registry: dict[str, Any]) -> dict[str, Any]:
    prompt = str(body.get("prompt", "")).strip()
    if not prompt:
        raise ValueError("prompt is required")
    if len(prompt) > MAX_PROMPT_CHARS:
        raise ValueError(f"prompt exceeds {MAX_PROMPT_CHARS} characters")
    provider = str(body.get("provider") or registry["default_provider"])
    model = str(body.get("model") or registry["default_model"])
    effort = str(body.get("reasoning_effort") or "medium")
    validate_selection(provider, model, effort, registry)
    workspace = resolve_workspace(body.get("workspace"))
    return {
        "mode": "preview",
        "task": prompt,
        "workspace": str(workspace),
        "selection": {"provider": provider, "model": model, "reasoning_effort": effort},
        "route": [
            {"stage": 1, "actor": "Jev", "purpose": "Classify scope, risk, evidence and budget; choose a bounded operation."},
            {"stage": 2, "actor": "Hermes", "purpose": "Load project rules/skills/memory and execute the bounded operation with tools."},
            {"stage": 3, "actor": model, "purpose": "Provide frontier reasoning for the Hermes worker."},
            {"stage": 4, "actor": "Validators", "purpose": "Run deterministic checks, tests and evidence validation."},
            {"stage": 5, "actor": "Jev", "purpose": "Accept, repair, retrieve evidence, escalate or stop."}
        ],
        "runtime_boundary": "The Run button invokes only the bounded Hermes worker. CIDM/Jev acceptance remains a separate control-plane step until the Hermes GenerativeAdapter is wired into CheckedNetwork.",
        "safe_mode": True
    }


def build_hermes_command(provider: str, model: str, effort: str, safe_mode: bool) -> list[str]:
    binary = shutil.which("hermes")
    if not binary:
        raise RuntimeError("Hermes CLI was not found in PATH")
    cmd = [binary, "chat", "--oneshot", "--provider", provider, "--model", model, "--reasoning", effort, "--query-file", "-"]
    if safe_mode:
        cmd.insert(1, "--safe-mode")
    return cmd


def execute_hermes(body: dict[str, Any], registry: dict[str, Any]) -> dict[str, Any]:
    route = build_route(body, registry)
    provider = route["selection"]["provider"]
    model = route["selection"]["model"]
    effort = route["selection"]["reasoning_effort"]
    workspace = Path(route["workspace"])
    safe_mode = bool(body.get("safe_mode", True))
    cmd = build_hermes_command(provider, model, effort, safe_mode)
    prompt = (
        "You are the bounded operational worker inside the Jev-Orchestrated Decision Mesh. "
        "Work only on the user's stated task. Respect repository rules and existing skills. "
        "Use tools when needed, report concrete evidence and test results, and do not claim final CIDM acceptance; "
        "your output returns to the control plane for validation and arbitration.\n\nTASK:\n" + route["task"]
    )
    timeout = int(os.environ.get("JEV_CONSOLE_RUN_TIMEOUT", "1800"))
    proc = subprocess.run(
        cmd,
        input=prompt,
        cwd=str(workspace),
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
        env=os.environ.copy(),
    )
    return {
        "ok": proc.returncode == 0,
        "returncode": proc.returncode,
        "output": (proc.stdout or proc.stderr or "").strip(),
        "stderr": proc.stderr.strip() if proc.stderr else "",
        "selection": route["selection"],
        "workspace": str(workspace),
        "control_plane_status": "worker_complete_pending_validation" if proc.returncode == 0 else "worker_failed",
    }


class ConsoleHandler(SimpleHTTPRequestHandler):
    registry = load_registry()

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, directory=str(CONSOLE_DIR), **kwargs)

    def _json(self, payload: Any, status: int = 200) -> None:
        raw = json.dumps(payload, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def _body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length > 2_000_000:
            raise ValueError("request body too large")
        raw = self.rfile.read(length) if length else b"{}"
        data = json.loads(raw.decode("utf-8"))
        if not isinstance(data, dict):
            raise ValueError("JSON body must be an object")
        return data

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/api/models":
            self._json(self.registry)
            return
        if self.path == "/api/status":
            self._json(runtime_status())
            return
        super().do_GET()

    def do_POST(self) -> None:  # noqa: N802
        try:
            body = self._body()
            if self.path == "/api/preview":
                self._json(build_route(body, self.registry))
                return
            if self.path == "/api/run":
                result = execute_hermes(body, self.registry)
                self._json(result, 200 if result["ok"] else 502)
                return
            self._json({"error": "not found"}, 404)
        except (ValueError, json.JSONDecodeError) as exc:
            self._json({"error": str(exc)}, 400)
        except subprocess.TimeoutExpired:
            self._json({"error": "Hermes run timed out"}, 504)
        except Exception as exc:
            self._json({"error": str(exc)}, 500)

    def log_message(self, fmt: str, *args: Any) -> None:
        sys.stderr.write("[jev-console] " + (fmt % args) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Serve the local Jev Operator Console")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host (default: localhost only)")
    parser.add_argument("--port", type=int, default=8765, help="Bind port")
    args = parser.parse_args()
    if not CONSOLE_DIR.is_dir():
        parser.error(f"console directory not found: {CONSOLE_DIR}")
    server = ThreadingHTTPServer((args.host, args.port), ConsoleHandler)
    print(f"Jev Operator Console: http://{args.host}:{server.server_port}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping console.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
