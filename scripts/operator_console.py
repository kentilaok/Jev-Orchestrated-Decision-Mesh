#!/usr/bin/env python3
"""Local Jev Operator Console.

A standard-library control surface for CIDM experiments. It exposes local runtime
status, Hermes skill management, frontier account/model selection, route previews,
and explicit local frontier execution. It does not fake a live Jev decision.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import threading
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib import error as urlerror
from urllib import request as urlrequest

REPO_ROOT = Path(__file__).resolve().parents[1]
CONSOLE_DIR = REPO_ROOT / "console"
DEFAULT_STATE_PATH = Path(os.environ.get("JEV_OPERATOR_STATE", "~/.jev/operator-console.json")).expanduser()
DEFAULT_HERMES_SKILLS = Path(os.environ.get("HERMES_HOME", "~/.hermes")).expanduser() / "skills"
DEFAULT_HERMES_DASHBOARD = os.environ.get("HERMES_DASHBOARD_URL", "http://127.0.0.1:9119")

DEFAULT_CONFIG = {
    "frontier_provider": "claude",
    "providers": {
        "claude": {"enabled": True, "model": "default", "models": ["default", "claude-sonnet-5-5", "claude-opus-5-5", "claude-fable-5-1"]},
        "codex": {"enabled": True, "model": "default", "models": ["default", "gpt-6.1-sol", "gpt-6-sol", "gpt-6-luna"]},
    },
    "skills_source": str(DEFAULT_HERMES_SKILLS),
    "hermes_dashboard_url": DEFAULT_HERMES_DASHBOARD,
    "project_directory": str(REPO_ROOT),
    "execution_mode": "preview",
    "decision_policy": "jev-managed",
    "evidence_policy": "required",
    "depth": "balanced",
}


def _merge_config(raw: dict | None) -> dict:
    data = json.loads(json.dumps(DEFAULT_CONFIG))
    if not isinstance(raw, dict):
        return data
    for key, value in raw.items():
        if key == "providers" and isinstance(value, dict):
            for provider, provider_cfg in value.items():
                if provider in data["providers"] and isinstance(provider_cfg, dict):
                    data["providers"][provider].update(provider_cfg)
        elif key in data:
            data[key] = value
    return data


class StateStore:
    def __init__(self, path: Path = DEFAULT_STATE_PATH):
        self.path = path
        self.lock = threading.Lock()

    def load(self) -> dict:
        with self.lock:
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                raw = None
            return _merge_config(raw)

    def save(self, config: dict) -> dict:
        merged = _merge_config(config)
        with self.lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(merged, indent=2) + "\n", encoding="utf-8")
            tmp.replace(self.path)
        return merged


def run_command(args: list[str], *, cwd: str | None = None, timeout: int = 8) -> dict:
    try:
        proc = subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=timeout, env=os.environ.copy())
    except FileNotFoundError:
        return {"ok": False, "returncode": None, "output": "command not found"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "returncode": None, "output": "status check timed out"}
    output = (proc.stdout or "") + (proc.stderr or "")
    return {"ok": proc.returncode == 0, "returncode": proc.returncode, "output": output.strip()[:4000]}


def executable_status(name: str) -> dict:
    path = shutil.which(name)
    return {"installed": bool(path), "path": path}


def claude_status() -> dict:
    base = executable_status("claude")
    if not base["installed"]:
        return {**base, "auth": "unavailable", "detail": "Claude Code CLI not found"}
    result = run_command(["claude", "auth", "status"], timeout=6)
    text = result["output"].lower()
    if result["ok"] and any(token in text for token in ("logged in", "authenticated", "subscription", "oauth")):
        auth = "signed-in"
    elif result["ok"]:
        auth = "available"
    else:
        auth = "unknown"
    return {**base, "auth": auth, "detail": result["output"] or "Use claude, then /status to verify account."}


def codex_status() -> dict:
    base = executable_status("codex")
    if not base["installed"]:
        return {**base, "auth": "unavailable", "detail": "Codex CLI not found"}
    result = run_command(["codex", "login", "status"], timeout=6)
    text = result["output"].lower()
    auth = "signed-in" if result["ok"] and "logged in" in text else "available" if result["ok"] else "unknown"
    return {**base, "auth": auth, "detail": result["output"] or "Run codex login status to verify account."}


def hermes_status(config: dict) -> dict:
    base = executable_status("hermes")
    dashboard = config.get("hermes_dashboard_url") or DEFAULT_HERMES_DASHBOARD
    api_ok = False
    try:
        req = urlrequest.Request(dashboard.rstrip("/") + "/api/skills", method="GET")
        with urlrequest.urlopen(req, timeout=1.2) as resp:
            api_ok = 200 <= resp.status < 300
    except Exception:
        pass
    return {**base, "dashboard": dashboard, "dashboard_reachable": api_ok}


def parse_skill_metadata(skill_file: Path) -> dict:
    name, description = skill_file.parent.name, ""
    try:
        text = skill_file.read_text(encoding="utf-8-sig")
    except OSError:
        return {"name": name, "description": description}
    if text.startswith("---"):
        block = text.split("---", 2)[1] if text.count("---") >= 2 else ""
        for line in block.splitlines():
            key, sep, value = line.partition(":")
            if not sep:
                continue
            key, value = key.strip().lower(), value.strip().strip("\"'")
            if key == "name" and value:
                name = value
            elif key == "description" and value:
                description = value
    if not description:
        for line in text.splitlines():
            line = line.strip()
            if line and not line.startswith(("#", "---")):
                description = line[:180]
                break
    return {"name": name, "description": description[:220]}


def local_skills(config: dict) -> list[dict]:
    source = Path(str(config.get("skills_source") or DEFAULT_HERMES_SKILLS)).expanduser()
    if not source.is_dir():
        return []
    results = []
    for skill_file in sorted(source.glob("*/SKILL.md")):
        meta = parse_skill_metadata(skill_file)
        results.append({**meta, "path": str(skill_file.parent), "enabled": None, "source": "folder"})
    return results


def hermes_api(config: dict, path: str, method: str = "GET", payload: dict | None = None):
    base = str(config.get("hermes_dashboard_url") or DEFAULT_HERMES_DASHBOARD).rstrip("/")
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urlrequest.Request(base + path, method=method, data=body, headers={"Content-Type": "application/json"} if body is not None else {})
    with urlrequest.urlopen(req, timeout=3) as resp:
        raw = resp.read().decode("utf-8")
        return json.loads(raw) if raw else {}


def merged_skills(config: dict) -> list[dict]:
    folder = {item["name"]: item for item in local_skills(config)}
    try:
        remote = hermes_api(config, "/api/skills")
        items = remote.get("skills", remote) if isinstance(remote, dict) else remote
        if isinstance(items, list):
            for item in items:
                if not isinstance(item, dict):
                    continue
                name = str(item.get("name") or "").strip()
                if not name:
                    continue
                prior = folder.get(name, {})
                folder[name] = {
                    "name": name,
                    "description": item.get("description") or prior.get("description", ""),
                    "path": prior.get("path", ""),
                    "enabled": bool(item.get("enabled", True)),
                    "category": item.get("category"),
                    "source": "hermes",
                }
    except Exception:
        pass
    return sorted(folder.values(), key=lambda item: item["name"].lower())


def open_folder(path: str) -> None:
    resolved = Path(path).expanduser().resolve()
    resolved.mkdir(parents=True, exist_ok=True)
    system = platform.system().lower()
    if system == "windows":
        os.startfile(str(resolved))  # type: ignore[attr-defined]
    elif system == "darwin":
        subprocess.Popen(["open", str(resolved)])
    else:
        subprocess.Popen(["xdg-open", str(resolved)])


def launch_login(provider: str) -> dict:
    if provider == "claude":
        command = "claude"
        guidance = "When Claude Code opens, run /login and choose your Claude subscription account."
    elif provider == "codex":
        command = "codex login"
        guidance = "Complete the browser sign-in with the same ChatGPT account you use for Codex."
    else:
        raise ValueError("unknown provider")
    system, launched = platform.system().lower(), False
    try:
        if system == "windows":
            subprocess.Popen(["powershell.exe", "-NoExit", "-Command", command], creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0))
            launched = True
        elif system == "darwin":
            subprocess.Popen(["osascript", "-e", f'tell application "Terminal" to do script "{command}"'])
            launched = True
        else:
            terminal = next((t for t in ("x-terminal-emulator", "gnome-terminal", "konsole") if shutil.which(t)), None)
            if terminal == "gnome-terminal":
                subprocess.Popen([terminal, "--", "bash", "-lc", f"{command}; exec bash"])
                launched = True
            elif terminal:
                subprocess.Popen([terminal, "-e", "bash", "-lc", f"{command}; exec bash"])
                launched = True
    except Exception:
        launched = False
    return {"launched": launched, "command": command, "guidance": guidance}


def route_preview(payload: dict, config: dict) -> dict:
    provider = payload.get("provider") or config["frontier_provider"]
    provider_cfg = config["providers"].get(provider, {})
    model = payload.get("model") or provider_cfg.get("model", "default")
    skill_names = [s["name"] for s in merged_skills(config) if s.get("enabled") is not False]
    return {
        "status": "preview",
        "provider": provider,
        "model": model,
        "route": [
            {"stage": "input", "actor": "Operator", "detail": "goal + accepted project context"},
            {"stage": "decision", "actor": "Jev", "detail": "classify scope, choose evidence/budget/route"},
            {"stage": "runtime", "actor": "Hermes", "detail": f"load enabled skills ({len(skill_names)} visible) and execute local procedure"},
            {"stage": "frontier", "actor": provider.title(), "detail": f"frontier worker model: {model}"},
            {"stage": "validation", "actor": "Validators", "detail": "tests, evidence checks, project contracts"},
            {"stage": "arbitration", "actor": "Jev", "detail": "accept, repair, retrieve, escalate, or stop"},
        ],
        "note": "Preview does not spend model usage or mutate the project.",
    }


def run_frontier(payload: dict, config: dict) -> dict:
    provider = payload.get("provider") or config["frontier_provider"]
    provider_cfg = config["providers"].get(provider, {})
    if not provider_cfg.get("enabled", False):
        raise ValueError(f"provider {provider!r} is disabled")
    model = payload.get("model") or provider_cfg.get("model", "default")
    task = str(payload.get("task") or "").strip()
    if not task:
        raise ValueError("task is required")
    cwd = str(Path(payload.get("project_directory") or config.get("project_directory") or REPO_ROOT).expanduser())

    if provider == "claude":
        command = ["claude"] + ([] if model == "default" else ["--model", model]) + ["-p", task]
    elif provider == "codex":
        command = ["codex", "exec", "--sandbox", "read-only"] + ([] if model == "default" else ["--model", model]) + [task]
    else:
        raise ValueError("unsupported frontier provider")

    result = run_command(command, cwd=cwd, timeout=int(payload.get("timeout", 120)))
    return {
        "status": "completed" if result["ok"] else "failed",
        "provider": provider,
        "model": model,
        "command": command[:-1] + ["<task>"],
        "output": result["output"],
        "returncode": result["returncode"],
    }


class Handler(SimpleHTTPRequestHandler):
    store = StateStore()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(CONSOLE_DIR), **kwargs)

    def log_message(self, fmt, *args):
        sys.stderr.write("[jev-console] " + fmt % args + "\n")

    def send_json(self, data, status=HTTPStatus.OK):
        raw = json.dumps(data, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def read_json(self):
        size = int(self.headers.get("Content-Length") or 0)
        if size > 2_000_000:
            raise ValueError("request too large")
        return json.loads((self.rfile.read(size) if size else b"{}").decode("utf-8") or "{}")

    def do_GET(self):
        config = self.store.load()
        if self.path == "/api/state":
            self.send_json({
                "config": config,
                "runtime": {
                    "hermes": hermes_status(config),
                    "claude": claude_status(),
                    "codex": codex_status(),
                    "jev": {"connected": False, "detail": "Preview mode does not fake a live Jev call."},
                },
                "skills": merged_skills(config),
            })
            return
        if self.path == "/api/skills":
            self.send_json({"skills": merged_skills(config), "source": config["skills_source"]})
            return
        super().do_GET()

    def do_POST(self):
        try:
            payload, config = self.read_json(), self.store.load()
            if self.path == "/api/config":
                updated = _merge_config({**config, **payload})
                if isinstance(payload.get("providers"), dict):
                    updated["providers"] = config["providers"]
                    for name, provider_cfg in payload["providers"].items():
                        if name in updated["providers"] and isinstance(provider_cfg, dict):
                            updated["providers"][name].update(provider_cfg)
                self.send_json({"config": self.store.save(updated)})
                return
            if self.path == "/api/skills/open":
                open_folder(str(payload.get("path") or config["skills_source"]))
                self.send_json({"ok": True})
                return
            if self.path == "/api/skills/toggle":
                name, enabled = str(payload.get("name") or "").strip(), bool(payload.get("enabled"))
                if not name:
                    raise ValueError("skill name is required")
                try:
                    result = hermes_api(config, "/api/skills/toggle", method="PUT", payload={"name": name, "enabled": enabled})
                except (OSError, urlerror.URLError, ValueError) as exc:
                    self.send_json({"ok": False, "error": "Hermes dashboard API is not reachable. Start hermes dashboard --no-open, then try again.", "detail": str(exc)}, HTTPStatus.SERVICE_UNAVAILABLE)
                    return
                self.send_json({"ok": True, "result": result})
                return
            if self.path == "/api/provider/login":
                self.send_json(launch_login(str(payload.get("provider") or "")))
                return
            if self.path == "/api/route/preview":
                self.send_json(route_preview(payload, config))
                return
            if self.path == "/api/run":
                mode = str(payload.get("execution_mode") or config.get("execution_mode") or "preview")
                if mode == "preview":
                    self.send_json(route_preview(payload, config))
                elif mode == "frontier-direct":
                    self.send_json(run_frontier(payload, config))
                else:
                    self.send_json({"status": "blocked", "message": "Hermes/Jev combined execution is intentionally not simulated. Connect the live Jev adapter and Hermes dispatch contract first."}, HTTPStatus.NOT_IMPLEMENTED)
                return
            self.send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)
        except (ValueError, json.JSONDecodeError) as exc:
            self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        except Exception as exc:
            self.send_json({"error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run the local Jev Operator Console")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE_PATH)
    parser.add_argument("--no-open", action="store_true")
    args = parser.parse_args(argv)
    Handler.store = StateStore(args.state.expanduser())
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    url = f"http://{args.host}:{args.port}"
    print(f"Jev Operator Console: {url}")
    if not args.no_open:
        threading.Timer(0.4, lambda: __import__("webbrowser").open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
