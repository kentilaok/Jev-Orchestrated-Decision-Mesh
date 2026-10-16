#!/usr/bin/env python3
"""Local Jev Operator Console.

A standard-library control surface for CIDM. It shows frontier account and
model state, route coverage, the Arsenal (skills, lessons, calibration, Fast
Path), the MCP catalogue, recovery runs and checkpoints, and OpenTelemetry
summaries. It runs bounded account smoke tests and live CIDM broker jobs only
on explicit operator request. It never fakes a Jev decision.

Security: loopback only; every request must carry a loopback Host header
(DNS-rebinding guard); every POST needs the `X-CIDM-Console: 1` header and a
same-origin Origin when present (CSRF guard). No credential is read or returned.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import html as html_mod
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib import error as urlerror
from urllib import parse as urlparse
from urllib import request as urlrequest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
CONSOLE_DIR = REPO_ROOT / "console"
DEFAULT_STATE_PATH = Path(os.environ.get("JEV_OPERATOR_STATE", "~/.jev/operator-console.json")).expanduser()
from hermes_paths import CIDM_EXTERNAL_SKILLS, hermes_executable, hermes_home  # noqa: E402
DEFAULT_HERMES_SKILLS = hermes_home() / "skills"
DEFAULT_HERMES_DASHBOARD = os.environ.get("HERMES_DASHBOARD_URL", "http://127.0.0.1:9119")
LOOPBACK = {"127.0.0.1", "localhost", "::1"}

DEFAULT_CONFIG = {
    "frontier_provider": "claude",
    "providers": {
        "claude": {"enabled": True, "model": "claude-sonnet-5-5",
                   "models": ["claude-sonnet-5-5", "claude-opus-5-5", "claude-fable-5-1", "claude-haiku-5-5"]},
        "codex": {"enabled": True, "model": "default", "models": ["default"]},
    },
    "skills_source": str(DEFAULT_HERMES_SKILLS),
    "hermes_dashboard_url": DEFAULT_HERMES_DASHBOARD,
    "project_directory": str(REPO_ROOT),
    "runs_directory": str(REPO_ROOT / "runs"),
    "arsenal_db": str(Path("~/.jev/arsenal/arsenal.db").expanduser()),
    "calibration_ledger": str(Path("~/.jev/arsenal/calibration.jsonl").expanduser()),
    "fast_path_ledger": str(Path("~/.jev/arsenal/fast-path.jsonl").expanduser()),
    "mcp_db": str(Path("~/.jev/arsenal/mcp.db").expanduser()),
    "execution_mode": "preview",
    "gate_policy": "recovery",
    "decision_policy": "jev-managed",
    "evidence_policy": "required",
    "depth": "balanced",
    "trusted_mcp_servers": [],
    "content_policy": "off",
    "require_action_approval": False,
    "secret_env_names": [],
    "max_cumulative_usd": None,
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
        elif key == "content_policy":
            if value not in ("off", "audit", "wrap"):
                raise ValueError("content_policy must be 'off', 'audit', or 'wrap'")
            data[key] = value
        elif key == "require_action_approval":
            if not isinstance(value, bool):
                raise ValueError("require_action_approval must be a boolean")
            data[key] = value
        elif key == "trusted_mcp_servers":
            if not isinstance(value, list):
                raise ValueError("trusted_mcp_servers must be a list of strings")
            if not all(isinstance(x, str) and x for x in value):
                raise ValueError("trusted_mcp_servers entries must be non-empty strings")
            data[key] = list(value)
        elif key == "secret_env_names":
            if not isinstance(value, list):
                raise ValueError("secret_env_names must be a list of strings")
            if not all(isinstance(x, str) and x and "=" not in x for x in value):
                raise ValueError("secret_env_names entries must be non-empty strings without '='")
            data[key] = list(value)
        elif key == "max_cumulative_usd":
            if value is None:
                data[key] = None
            elif isinstance(value, bool) or type(value) not in (int, float):
                raise ValueError("max_cumulative_usd must be null or a positive number")
            else:
                import math as _math
                if not _math.isfinite(value) or value <= 0:
                    raise ValueError("max_cumulative_usd must be null or a positive number")
                data[key] = float(value)
        elif key in data:
            data[key] = value
    return data


def _trusted_mcp_servers(config: dict) -> set[str]:
    """Operator-trusted MCP server names, as a set, for the P0-05 trust gate.

    Default `trusted_mcp_servers=[]` yields an empty set, which puts the
    classifier in strict mode: a server not in the set has its
    `readOnlyHint=true` demoted to `access_class='unknown'`. This matches
    P0-05's untrusted-by-default stance; operators opt a server into the
    trusted set via `/api/config` to recover `read` classifications on it.
    """
    return set(config.get("trusted_mcp_servers") or [])


def list_approvals(config: dict) -> dict:
    """Return pending/decided approval records under runs/approvals/."""
    folder = Path(config["runs_directory"]) / "approvals"
    pending, decided = [], []
    if not folder.is_dir():
        return {"pending": pending, "decided": decided}
    for path in folder.glob("*.json"):
        if path.suffix == ".tmp":
            continue
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        bucket = pending if record.get("status") == "pending" else decided
        bucket.append(record)
    pending.sort(key=lambda r: r.get("created", 0))
    decided.sort(key=lambda r: r.get("decided_at", r.get("created", 0)))
    return {"pending": pending, "decided": decided}


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


# ---------------------------------------------------------------- request guards

def host_allowed(host_header: str | None, port: int) -> bool:
    """Accept only loopback Host headers (blocks DNS-rebinding attacks)."""
    if not host_header:
        return False
    host = host_header.strip()
    if host.startswith("["):
        name, _, rest = host[1:].partition("]")
        port_text = rest[1:] if rest.startswith(":") else ""
    else:
        name, _, port_text = host.partition(":")
    return name.lower() in LOOPBACK and (port_text == "" or port_text == str(port))


def origin_allowed(origin: str | None, port: int) -> bool:
    if origin is None:
        return True  # non-browser clients; the custom header still applies
    parts = urlparse.urlsplit(origin)
    return parts.scheme == "http" and (parts.hostname or "") in LOOPBACK and parts.port == port


# ---------------------------------------------------------------- runtime status

def executable_status(name: str) -> dict:
    path = shutil.which(name)
    return {"installed": bool(path), "path": path}


def hermes_status(config: dict) -> dict:
    path = hermes_executable()
    base = {"installed": bool(path), "path": path, "home": str(hermes_home()),
            "cidm_external_skills": str(CIDM_EXTERNAL_SKILLS)}
    dashboard = config.get("hermes_dashboard_url") or DEFAULT_HERMES_DASHBOARD
    api_ok = False
    try:
        req = urlrequest.Request(dashboard.rstrip("/") + "/api/skills", method="GET")
        with urlrequest.urlopen(req, timeout=1.2) as resp:
            api_ok = 200 <= resp.status < 300
    except Exception:
        pass
    return {**base, "dashboard": dashboard, "dashboard_reachable": api_ok}


_PROVIDER_CACHE: dict = {"at": 0.0, "value": None}
_PROVIDER_LOCK = threading.Lock()


def provider_overview(*, refresh: bool = False) -> dict:
    """Account status, model catalogue, capabilities and CIDM route coverage."""
    from capability_permits import PermitAuthority
    from config import RunConfig
    from frontier_providers import build_provider, route_coverage
    with _PROVIDER_LOCK:
        if not refresh and _PROVIDER_CACHE["value"] and time.time() - _PROVIDER_CACHE["at"] < 120:
            return copy.deepcopy(_PROVIDER_CACHE["value"])
        authority = PermitAuthority()
        overview = {}
        for name, family in (("claude", "claude"), ("codex", "gpt6")):
            provider = build_provider(name, authority)
            config = RunConfig(worker_family=family)
            try:
                status = provider.status()
            except Exception as error:
                status = {"provider": name, "installed": None, "error": type(error).__name__}
            models = provider.list_models() if status.get("installed") else {"models": [], "account_derived": False}
            coverage = route_coverage(provider, list(config.worker_routes()),
                                      checker=(config.checker_model, config.checker_effort), catalogue=models)
            overview[name] = {"status": status, "models": models, "capabilities": provider.capabilities(),
                              "cidm_route_coverage": coverage}
        overview["jev"] = {"api_key_present": bool(os.environ.get("OPENROUTER_API_KEY")),
                           "model": RunConfig().jev_model,
                           "detail": "Jev runs through OpenRouter; the key is read from the environment only."}
        _PROVIDER_CACHE.update(at=time.time(), value=overview)
        return copy.deepcopy(overview)


# ---------------------------------------------------------------- skills

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
    # Hermes nests bundled skills one category deep (skills/<category>/<name>/SKILL.md).
    for skill_file in sorted({*source.glob("*/SKILL.md"), *source.glob("*/*/SKILL.md")}):
        meta = parse_skill_metadata(skill_file)
        results.append({**meta, "path": str(skill_file.parent), "enabled": None, "source": "folder"})
    return results


def hermes_api(config: dict, path: str, method: str = "GET", payload: dict | None = None):
    base = str(config.get("hermes_dashboard_url") or DEFAULT_HERMES_DASHBOARD).rstrip("/")
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urlrequest.Request(base + path, method=method, data=body,
                             headers={"Content-Type": "application/json"} if body is not None else {})
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
                folder[name] = {"name": name, "description": item.get("description") or prior.get("description", ""),
                                "path": prior.get("path", ""), "enabled": bool(item.get("enabled", True)),
                                "category": item.get("category"), "source": "hermes"}
    except Exception:
        pass
    return sorted(folder.values(), key=lambda item: item["name"].lower())


def open_folder(path: str) -> None:
    resolved = Path(path).expanduser().resolve()
    resolved.mkdir(parents=True, exist_ok=True)
    if not resolved.is_dir():
        raise ValueError("only directories can be opened")
    system = platform.system().lower()
    if system == "windows":
        subprocess.Popen(["explorer.exe", str(resolved)])
    elif system == "darwin":
        subprocess.Popen(["open", str(resolved)])
    else:
        subprocess.Popen(["xdg-open", str(resolved)])


def launch_login(provider: str) -> dict:
    if provider == "claude":
        argv, guidance = ["claude", "auth", "login"], "Complete the browser sign-in with your Claude subscription account."
    elif provider == "codex":
        argv, guidance = ["codex", "login"], "Complete the browser sign-in with the ChatGPT account you use for Codex."
    else:
        raise ValueError("unknown provider")
    launched = False
    try:
        flags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0) if platform.system() == "Windows" else 0
        subprocess.Popen(argv, creationflags=flags)
        launched = True
    except Exception:
        launched = False
    return {"launched": launched, "command": " ".join(argv), "guidance": guidance}


# ---------------------------------------------------------------- routes and runs

def route_preview(payload: dict, config: dict) -> dict:
    provider = payload.get("provider") or config["frontier_provider"]
    provider_cfg = config["providers"].get(provider, {})
    model = payload.get("model") or provider_cfg.get("model", "default")
    skill_names = [s["name"] for s in merged_skills(config) if s.get("enabled") is not False]
    return {
        "status": "preview", "provider": provider, "model": model,
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


DIRECT_SCHEMA = {"type": "object", "properties": {
    "answer": {"type": "string", "maxLength": 4000},
    "unresolved": {"type": "array", "items": {"type": "string"}, "maxItems": 8}},
    "required": ["answer", "unresolved"], "additionalProperties": False}


def run_frontier(payload: dict, config: dict, *, provider_factory=None) -> dict:
    """One bounded, tool-free, schema-checked call: an account smoke test, not CIDM."""
    from capability_permits import PermitAuthority
    from frontier_providers import ClaudeCodeProvider, CodexProvider, _request_scope
    provider = payload.get("provider") or config["frontier_provider"]
    provider_cfg = config["providers"].get(provider, {})
    if not provider_cfg.get("enabled", False):
        raise ValueError(f"provider {provider!r} is disabled")
    model = payload.get("model") or provider_cfg.get("model", "default")
    if model == "default" or model not in provider_cfg.get("models", []):
        raise ValueError("choose an explicit model from the provider's list for a bounded run")
    task = str(payload.get("task") or "").strip()
    if not task or len(task) > 8000:
        raise ValueError("task is required (at most 8000 characters)")
    effort = payload.get("effort") or "low"
    authority = PermitAuthority()
    if provider_factory is not None:
        frontier = provider_factory(provider, authority, model)
    elif provider == "claude":
        from claude_cli_adapter import ClaudeCliAdapter
        frontier = ClaudeCodeProvider(authority, adapter=ClaudeCliAdapter(permitted_models=[model]))
    elif provider == "codex":
        from codex_cli_adapter import CodexCliAdapter
        frontier = CodexProvider(authority, adapter=CodexCliAdapter(permitted_models=[model]))
    else:
        raise ValueError("unsupported frontier provider")
    with tempfile.TemporaryDirectory(prefix="cidm-console-") as workspace:
        request = {"model": model, "effort": effort, "prompt": task, "schema": DIRECT_SCHEMA,
                   "workspace": workspace}
        basis = {"kind": "operator", "operator": "local-console", "reason": "bounded account smoke test"}
        permit = authority.issue("frontier.run", _request_scope(frontier.provider_id, request), basis)
        try:
            response = frontier.run(request, permit)
        except Exception as error:
            return {"status": "failed", "provider": provider, "model": model,
                    "error": str(error)[:300], "usage": getattr(error, "usage", None)}
    return {"status": "completed", "provider": provider, "model": model,
            "output": response["artifact"]["answer"], "unresolved": response["artifact"]["unresolved"],
            "usage": response.get("usage"), "identity_verification": response.get("identity_verification"),
            "note": "Bounded tool-free call; not a Jev-governed CIDM result."}


def _runs_root(config: dict) -> Path:
    return Path(config.get("runs_directory") or REPO_ROOT / "runs").expanduser()


def _safe_run_dir(config: dict, name: str) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,120}", name or ""):
        raise ValueError("invalid run name")
    root = _runs_root(config).resolve()
    path = (root / name).resolve()
    if not path.is_relative_to(root) or not path.is_dir():
        raise ValueError("unknown run")
    return path


def _result_path(run_dir: Path) -> Path | None:
    for candidate in (run_dir / "result.json", run_dir / "run" / "result.json"):
        if candidate.is_file():
            return candidate
    return None


def list_runs(config: dict, limit: int = 60) -> list[dict]:
    root = _runs_root(config)
    if not root.is_dir():
        return []
    runs = []
    for folder in sorted((p for p in root.iterdir() if p.is_dir()), key=lambda p: p.stat().st_mtime, reverse=True):
        result_path = _result_path(folder)
        item = {"name": folder.name, "modified": int(folder.stat().st_mtime)}
        if result_path is None:
            item["status"] = "no_result"
        else:
            try:
                result = json.loads(result_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                result = {"status": "unreadable_result"}
            checkpoint = result_path.parent / "checkpoint.json"
            item.update({"status": result.get("status"), "route": result.get("route"),
                         "gate_policy": result.get("gate_policy"), "host": result.get("host"),
                         "simulation": result.get("simulation"), "calls": len(result.get("calls") or []),
                         "committed": [p.get("id") for p in result.get("committed") or []],
                         "checkpoint": checkpoint.is_file(), "resumed_from": result.get("resumed_from"),
                         "active_unit": (result.get("checkpoint") or {}).get("active_unit"),
                         "recovery_kind": (result.get("checkpoint") or {}).get("recovery_kind")})
        runs.append(item)
        if len(runs) >= limit:
            break
    return runs


def arsenal_overview(config: dict) -> dict:
    out: dict = {"skills": [], "lessons": 0, "calibration": None, "thresholds": None, "fast_path": None}
    db = Path(config["arsenal_db"]).expanduser()
    if db.is_file():
        from arsenal_registry import ArsenalRegistry
        with ArsenalRegistry(db) as registry:
            out["skills"] = [{k: s[k] for k in ("skill_id", "name", "version", "project_scope", "admitted",
                                                "risk", "frontier_required", "validators", "operations")}
                             for s in registry.list_skills()]
            out["lessons"] = registry.db.execute("SELECT COUNT(*) FROM experience_lessons").fetchone()[0]
            out["fts5"] = registry.fts5
    ledger = Path(config["calibration_ledger"]).expanduser()
    if ledger.is_file():
        from arsenal_calibration import evaluate, read_events, threshold_report
        try:
            events = read_events(ledger)
            scored = evaluate(events)
            out["calibration"] = {"summary": scored["summary"], "metrics": scored["metrics"]}
            out["thresholds"] = threshold_report(events, min_reviewed=30, min_precision_lower_bound=0.95)
        except Exception as error:
            out["calibration"] = {"error": str(error)[:200]}
    fast = Path(config["fast_path_ledger"]).expanduser()
    if fast.is_file():
        from arsenal_fastpath import avoidance_summary
        from capability_permits import HashChainLedger
        out["fast_path"] = avoidance_summary(HashChainLedger(fast).read())
    return out


def mcp_overview(config: dict, query: str | None = None) -> dict:
    from mcp_registry import McpCatalog, discover_servers, public_spec
    out = {"servers": [public_spec(s) for s in discover_servers(project_dir=Path(config["project_directory"]))]}
    with McpCatalog(Path(config["mcp_db"])) as catalog:
        out["catalogue"] = catalog.stats()
        if query:
            out["search"] = catalog.search(query, top_k=10)
    return out


def mcp_refresh(config: dict, server: str, *, client_factory=None,
                catalog_cls=None, discover=None) -> dict:
    if client_factory is None or catalog_cls is None or discover is None:
        from mcp_registry import (McpCatalog as _McpCatalog,
                                  client_for as _client_for,
                                  discover_servers as _discover_servers)
        client_factory = client_factory or _client_for
        catalog_cls = catalog_cls or _McpCatalog
        discover = discover or _discover_servers
    spec = next((s for s in discover(project_dir=Path(config["project_directory"])) if s["name"] == server), None)
    if spec is None:
        raise ValueError("unknown configured server")
    with catalog_cls(Path(config["mcp_db"])) as catalog, client_factory(spec) as client:
        client.initialize()
        return catalog.ingest(spec, client.list_tools(),
                              trusted_servers=_trusted_mcp_servers(config))


# ---------------------------------------------------------------- live broker jobs

class JobManager:
    """One live CIDM broker subprocess at a time; output stays in its run folder."""

    def __init__(self):
        self.jobs: dict[str, dict] = {}
        self.lock = threading.Lock()

    def active(self) -> dict | None:
        with self.lock:
            return next((j for j in self.jobs.values() if j["process"].poll() is None), None)

    def start(self, argv: list[str], run_dir: Path, meta: dict) -> dict:
        if self.active() is not None:
            raise ValueError("a live broker job is already running")
        run_dir.mkdir(parents=True, exist_ok=True)
        log = (run_dir / "console-job.log").open("wb")
        process = subprocess.Popen(argv, cwd=str(REPO_ROOT), stdout=log, stderr=subprocess.STDOUT, shell=False)
        job_id = uuid.uuid4().hex[:12]
        with self.lock:
            self.jobs[job_id] = {"process": process, "log": log, "run_dir": run_dir, "meta": meta,
                                 "started": time.time()}
        return {"job_id": job_id, "run": run_dir.name, **meta}

    def status(self, job_id: str) -> dict:
        with self.lock:
            job = self.jobs.get(job_id)
        if job is None:
            raise ValueError("unknown job")
        code = job["process"].poll()
        if code is not None and not job["log"].closed:
            job["log"].close()
        out_dir = job["run_dir"] / "run"
        journal = out_dir / "journal.jsonl"
        tail = []
        if journal.is_file():
            lines = journal.read_text(encoding="utf-8", errors="replace").splitlines()[-12:]
            for line in lines:
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                tail.append({k: event.get(k) for k in ("id", "kind", "phase", "unit_id") if event.get(k)}
                            | ({"choice": event["decision"].get("choice")} if isinstance(event.get("decision"), dict) else {}))
        result = None
        result_path = out_dir / "result.json"
        if code is not None and result_path.is_file():
            data = json.loads(result_path.read_text(encoding="utf-8"))
            result = {k: data.get(k) for k in ("status", "answer", "route", "gate_policy", "host",
                                               "route_coverage", "checkpoint_bundle", "jev_api_cost_usd")}
            result["calls"] = len(data.get("calls") or [])
        log_tail = (job["run_dir"] / "console-job.log").read_text(encoding="utf-8", errors="replace")[-2000:]
        return {"job_id": job_id, "running": code is None, "exit_code": code, "run": job["run_dir"].name,
                "elapsed_seconds": round(time.time() - job["started"], 1), "journal_tail": tail,
                "result": result, "log_tail": log_tail, **job["meta"]}


JOBS = JobManager()


def build_request(payload: dict) -> dict:
    goal = str(payload.get("task") or "").strip()
    context = str(payload.get("context") or "").strip()
    if not goal or len(goal) > 1200 or len(context) > 1200:
        raise ValueError("task (1-1200 characters) and context (at most 1200) are required limits")
    sources = {}
    for index, item in enumerate(payload.get("sources") or []):
        if not isinstance(item, dict) or index >= 6:
            raise ValueError("at most six sources with title and text")
        sources["s%d" % (index + 1)] = {"title": str(item.get("title") or "Source %d" % (index + 1))[:120],
                                        "text": str(item.get("text") or "")[:1200]}
        if not sources["s%d" % (index + 1)]["text"]:
            raise ValueError("source text is required")
    return {"goal": goal, "context": context, "sources": sources, "active_project": bool(context),
            "unresolved_stages": [], "classification": None}


def broker_argv(task_path: Path, out_dir: Path, provider: str, gate_policy: str, *, live: bool,
                resume: Path | None = None, operator: str | None = None, reset_rounds: bool = False,
                config: dict | None = None) -> list[str]:
    if provider not in ("claude", "codex") or gate_policy not in ("legacy", "fused", "recovery"):
        raise ValueError("invalid provider or gate policy")
    argv = [sys.executable, str(SCRIPTS / "native_transition_broker.py"),
            "--live" if live else "--validate-only", "--host", provider, "--gate-policy", gate_policy,
            "--task", str(task_path)]
    if live:
        argv += ["--out", str(out_dir)]
    if resume is not None:
        argv += ["--resume", str(resume)]
        if operator:
            argv += ["--operator", operator]
        if reset_rounds:
            argv.append("--reset-recovery-rounds")
    if config is not None:
        policy = config.get("content_policy", "off")
        if policy != "off":
            argv += ["--content-policy", policy]
        if config.get("require_action_approval"):
            argv.append("--require-action-approval")
        names = config.get("secret_env_names") or []
        if names:
            argv += ["--secret-env-names", ",".join(names)]
        cap = config.get("max_cumulative_usd")
        if cap is not None:
            argv += ["--max-cumulative-usd", str(float(cap))]
    return argv


def start_broker_job(payload: dict, config: dict) -> dict:
    if payload.get("confirm_live_spend") is not True:
        raise ValueError("live CIDM runs spend Jev API credits and provider plan usage; confirm_live_spend is required")
    provider = payload.get("provider") or config["frontier_provider"]
    gate_policy = payload.get("gate_policy") or config.get("gate_policy", "recovery")
    request = build_request(payload)
    stamp = time.strftime("%Y%m%dT%H%M%S")
    run_dir = _runs_root(config) / ("console-%s-%s" % (stamp, uuid.uuid4().hex[:6]))
    run_dir.mkdir(parents=True)
    task_path = run_dir / "request.json"
    task_path.write_text(json.dumps(request, indent=2), encoding="utf-8")
    argv = broker_argv(task_path, run_dir / "run", provider, gate_policy, live=True, config=config)
    return JOBS.start(argv, run_dir, {"kind": "broker_run", "provider": provider, "gate_policy": gate_policy})


def validate_broker_request(payload: dict, config: dict) -> dict:
    provider = payload.get("provider") or config["frontier_provider"]
    gate_policy = payload.get("gate_policy") or config.get("gate_policy", "recovery")
    request = build_request(payload)
    with tempfile.TemporaryDirectory() as temp:
        task_path = Path(temp) / "request.json"
        task_path.write_text(json.dumps(request), encoding="utf-8")
        proc = subprocess.run(broker_argv(task_path, Path(temp) / "out", provider, gate_policy,
                                           live=False, config=config),
                              capture_output=True, text=True, timeout=60, cwd=str(REPO_ROOT))
    if proc.returncode != 0:
        raise ValueError((proc.stderr or proc.stdout).strip().splitlines()[-1][:300])
    return {"validated": json.loads(proc.stdout.strip().splitlines()[-1]), "request": request}


CHAT_MODELS = ("cidm-jev",)

STRONG_KEYWORDS = (
    "delete", "drop ", "destroy", "wipe", "remove", "truncate",
    "update ", "alter", "shutdown", "revoke", "rotate", "grant",
    "deploy", "prod", "production", "merge to main", "force-push", "force push",
    "spend", "charge", "purchase", "pay", "rm -rf",
)


def _classify_strength(goal: str, context: str, *, explicit_strong: bool = False) -> str:
    """Return 'strong' if the request looks like it would mutate production or
    spend money above the implicit cap; 'normal' otherwise. Deliberately
    conservative: a false positive forces an explicit approval (safe), a false
    negative loses the gate. The explicit_strong flag always wins."""
    if explicit_strong:
        return "strong"
    haystack = (" " + str(goal).lower() + " " + str(context).lower() + " ")
    for word in STRONG_KEYWORDS:
        if word in haystack:
            return "strong"
    return "normal"


_APPROVAL_LOCKS: dict[str, threading.Lock] = {}
_APPROVAL_LOCKS_GUARD = threading.Lock()


def _approval_lock(token: str) -> threading.Lock:
    with _APPROVAL_LOCKS_GUARD:
        lock = _APPROVAL_LOCKS.get(token)
        if lock is None:
            lock = threading.Lock()
            _APPROVAL_LOCKS[token] = lock
        return lock


def _approvals_dir(config: dict) -> Path:
    path = Path(config["runs_directory"]) / "approvals"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _create_approval_token(config: dict, thread_id: str, goal: str,
                           provider: str, gate_policy: str) -> str:
    token = uuid.uuid4().hex
    record = {"token": token, "status": "pending", "created": int(time.time()),
              "thread_id": thread_id, "goal": goal[:400],
              "provider": provider, "gate_policy": gate_policy}
    target = _approvals_dir(config) / (token + ".json")
    tmp = target.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(record, indent=2), encoding="utf-8")
    os.replace(tmp, target)
    return token


def _record_approval_decision(token: str, config: dict, *, decision: str,
                              operator: str) -> dict:
    """Operator decision on a pending approval. Once decided, further
    transitions are refused (one-shot gate). Replace the token for a new
    request rather than re-deciding an old one."""
    if decision not in ("approve", "reject"):
        raise ValueError("decision must be 'approve' or 'reject'")
    if not operator or not operator.strip():
        raise ValueError("operator id is required")
    target = _approvals_dir(config) / (token + ".json")
    with _approval_lock(token):
        if not target.is_file():
            raise ValueError("unknown approval token")
        record = json.loads(target.read_text(encoding="utf-8"))
        if record["status"] != "pending":
            raise ValueError("approval already " + record["status"] + "; token is one-shot")
        record["status"] = "approved" if decision == "approve" else "rejected"
        record["operator"] = operator.strip()
        record["decided_at"] = int(time.time())
        tmp = target.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(record, indent=2), encoding="utf-8")
        os.replace(tmp, target)
        return record


def _approval_url(token: str) -> str:
    return "http://127.0.0.1:8765/approve/" + token


def _first_user_content(messages: list) -> str:
    """Return the content of the first user message with non-empty content, or ''."""
    if not isinstance(messages, list):
        return ""
    for item in messages:
        if isinstance(item, dict) and item.get("role") == "user":
            content = str(item.get("content") or "").strip()
            if content:
                return content
    return ""


def _derive_thread_id(messages: list) -> str:
    """Stable 16-hex thread id derived from the first user message.

    OpenAI chat.completions is stateless; Hermes replays the full message array
    each turn. Hashing the first user message gives us a continuity key that
    survives follow-up turns within the same thread. Edge case: if Hermes
    compacts the context and drops the original first user message, the thread
    id will change — documented in HANDOFF-HERMES-DISPATCH-SLICE-1.md.
    """
    seed = _first_user_content(messages).encode("utf-8")
    return hashlib.sha256(seed).hexdigest()[:16]


_THREAD_LOCKS: dict[str, threading.Lock] = {}
_THREAD_LOCKS_GUARD = threading.Lock()


def _thread_lock(thread_id: str) -> threading.Lock:
    with _THREAD_LOCKS_GUARD:
        lock = _THREAD_LOCKS.get(thread_id)
        if lock is None:
            lock = threading.Lock()
            _THREAD_LOCKS[thread_id] = lock
        return lock


def _record_thread_turn(thread_id: str, config: dict, goal: str, provider: str,
                        gate_policy: str) -> tuple[Path, int]:
    """Append this turn to the thread journal; return (path, new_turn_count).

    Concurrency: serialised by a per-thread lock so two in-flight requests on
    the same thread_id cannot clobber each other's turns. The write is atomic:
    we write to a sibling '.tmp' file then os.replace onto the journal path,
    so a crash mid-write leaves the previous journal intact.
    """
    threads_dir = Path(config["runs_directory"]) / "threads"
    threads_dir.mkdir(parents=True, exist_ok=True)
    journal = threads_dir / (thread_id + ".json")
    with _thread_lock(thread_id):
        if journal.is_file():
            data = json.loads(journal.read_text(encoding="utf-8"))
        else:
            data = {"thread_id": thread_id, "created": int(time.time()), "turns": []}
        data["turns"].append({"ts": int(time.time()), "goal": goal[:400],
                              "provider": provider, "gate_policy": gate_policy})
        data["last_turn"] = data["turns"][-1]["ts"]
        tmp = journal.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        os.replace(tmp, journal)
        return journal, len(data["turns"])


def _messages_to_task(messages: list) -> tuple[str, str]:
    """Collapse OpenAI chat messages into (goal, context) for the CIDM broker.

    Last user message becomes the goal; everything before it (any role) is joined
    as context. Both are hard-capped at 1200 chars to match build_request limits.
    """
    if not isinstance(messages, list) or not messages:
        raise ValueError("messages must be a non-empty list")
    last_user_idx = None
    for idx in range(len(messages) - 1, -1, -1):
        item = messages[idx]
        if isinstance(item, dict) and item.get("role") == "user" and str(item.get("content") or "").strip():
            last_user_idx = idx
            break
    if last_user_idx is None:
        raise ValueError("messages must contain at least one user message with content")
    goal = str(messages[last_user_idx]["content"]).strip()[:1200]
    prior = messages[:last_user_idx]
    context_lines = []
    for item in prior:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "").strip()
        content = str(item.get("content") or "").strip()
        if not role or not content:
            continue
        context_lines.append("%s: %s" % (role, content))
    context = "\n".join(context_lines)[:1200]
    return goal, context


def _prepare_chat_run(payload: dict, config: dict) -> dict:
    """Validate payload and run the shared broker handshake. Returns the data
    both chat_completions() and chat_completions_stream() need to shape output."""
    if not isinstance(payload, dict):
        raise ValueError("JSON object required")
    model = str(payload.get("model") or "").strip()
    if model not in CHAT_MODELS:
        raise ValueError("unknown model: %r (expected one of %s)" % (model, ", ".join(CHAT_MODELS)))
    if "messages" not in payload:
        raise ValueError("messages field is required")
    goal, context = _messages_to_task(payload["messages"])
    broker_payload = {"task": goal, "context": context,
                      "provider": payload.get("provider") or config["frontier_provider"],
                      "gate_policy": payload.get("gate_policy") or config.get("gate_policy", "recovery")}
    validated = validate_broker_request(broker_payload, config)
    plan = validated.get("validated") or {}
    route_hint = plan.get("route") or plan.get("gate_policy") or broker_payload["gate_policy"]
    thread_id = _derive_thread_id(payload["messages"])
    journal, turn = _record_thread_turn(thread_id, config, goal,
                                        broker_payload["provider"], broker_payload["gate_policy"])
    strength = _classify_strength(goal, context,
                                  explicit_strong=bool(payload.get("cidm_strong")))
    approval_token = None
    if strength == "strong":
        approval_token = _create_approval_token(config, thread_id, goal,
                                                broker_payload["provider"],
                                                broker_payload["gate_policy"])
        summary_lines = [
            "[CIDM] Approval required before this request can proceed.",
            "Thread: %s (turn %d)" % (thread_id, turn),
            "Classification: strong (keyword or opt-in)",
            "Goal: %s" % goal[:400],
            "",
            "Approve or reject in the Operator Console:",
            _approval_url(approval_token),
        ]
    else:
        summary_lines = [
            "[CIDM validate] Request accepted; no model calls were made.",
            "Thread: %s (turn journal: %s)" % (thread_id, journal.name),
            "Provider: %s" % broker_payload["provider"],
            "Gate policy: %s" % broker_payload["gate_policy"],
            "Route hint: %s" % route_hint,
            "Goal: %s" % goal[:400],
        ]
    return {"model": model, "goal": goal, "broker_payload": broker_payload,
            "route_hint": route_hint, "thread_id": thread_id, "turn": turn,
            "strength": strength, "approval_token": approval_token,
            "final_content": "\n".join(summary_lines)}


def _cidm_envelope(prep: dict) -> dict:
    body = {"thread_id": prep["thread_id"], "turn": prep["turn"],
            "status": "pending_approval" if prep["strength"] == "strong" else "ok",
            "mode": "validate"}
    if prep["approval_token"]:
        body["approval_token"] = prep["approval_token"]
        body["approval_url"] = _approval_url(prep["approval_token"])
    return body


def chat_completions(payload: dict, config: dict) -> dict:
    """OpenAI-compatible non-streaming handler. See _prepare_chat_run docstring."""
    prep = _prepare_chat_run(payload, config)
    now = int(time.time())
    return {
        "id": "chatcmpl-" + uuid.uuid4().hex[:24],
        "object": "chat.completion",
        "created": now,
        "model": prep["model"],
        "choices": [{"index": 0, "message": {"role": "assistant", "content": prep["final_content"]},
                     "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        "cidm": _cidm_envelope(prep),
    }


def _sse(chunk: dict) -> str:
    return "data: " + json.dumps(chunk) + "\n\n"


def chat_completions_stream(payload: dict, config: dict):
    """OpenAI-compatible streaming handler.

    Emits a sequence of chat.completion.chunk events ending with a
    finish_reason=stop chunk and a [DONE] sentinel. Status chunks ("[CIDM]
    starting", "[CIDM] validating request", "[CIDM] plan ready") appear
    before the final content so Hermes shows progress while the broker runs.
    """
    prep = _prepare_chat_run(payload, config)
    stream_id = "chatcmpl-" + uuid.uuid4().hex[:24]
    created = int(time.time())

    envelope = _cidm_envelope(prep)

    def chunk(delta: dict, finish: str | None = None) -> dict:
        return {"id": stream_id, "object": "chat.completion.chunk", "created": created,
                "model": prep["model"],
                "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
                "cidm": envelope}

    yield _sse(chunk({"role": "assistant"}))
    yield _sse(chunk({"content": "[CIDM] starting (thread %s, turn %d)\n" % (
        prep["thread_id"], prep["turn"])}))
    if prep["strength"] == "strong":
        yield _sse(chunk({"content": "[CIDM] classified as STRONG; approval required\n"}))
    else:
        yield _sse(chunk({"content": "[CIDM] validating request against gate policy '%s'...\n" %
                          prep["broker_payload"]["gate_policy"]}))
        yield _sse(chunk({"content": "[CIDM] plan ready (route hint: %s)\n\n" % prep["route_hint"]}))
    yield _sse(chunk({"content": prep["final_content"]}))
    yield _sse(chunk({}, finish="stop"))
    yield "data: [DONE]\n\n"


def start_resume_job(name: str, payload: dict, config: dict) -> dict:
    if payload.get("confirm_live_spend") is not True:
        raise ValueError("resuming spends Jev API credits and provider plan usage; confirm_live_spend is required")
    operator = str(payload.get("operator") or "").strip()
    if not operator:
        raise ValueError("operator id is required to resume")
    source_dir = _safe_run_dir(config, name)
    result_path = _result_path(source_dir)
    checkpoint = result_path.parent / "checkpoint.json" if result_path else None
    task = source_dir / "request.json"
    if checkpoint is None or not checkpoint.is_file() or not task.is_file():
        raise ValueError("run has no checkpoint or request to resume")
    previous = json.loads(result_path.read_text(encoding="utf-8"))
    # The cap is part of the checkpoint's policy hash, so resume with the cap the
    # run started with, not the Console's current value (else resume_config_mismatch).
    bundle = json.loads(checkpoint.read_text(encoding="utf-8"))
    policy = bundle.get("policy") if isinstance(bundle, dict) else None
    if not isinstance(policy, dict):
        raise ValueError("checkpoint has no policy to resume with")
    try:
        cap = _merge_config({"max_cumulative_usd": policy.get("max_cumulative_usd")})["max_cumulative_usd"]
    except ValueError as error:
        raise ValueError(f"checkpoint policy: {error}") from None
    config = {**config, "max_cumulative_usd": cap}
    run_dir = _runs_root(config) / (source_dir.name + "-resume-" + uuid.uuid4().hex[:6])
    run_dir.mkdir(parents=True)
    shutil.copyfile(task, run_dir / "request.json")
    argv = broker_argv(run_dir / "request.json", run_dir / "run", previous.get("host") or "claude", "recovery",
                       live=True, resume=checkpoint, operator=operator,
                       reset_rounds=bool(payload.get("reset_recovery_rounds")), config=config)
    return JOBS.start(argv, run_dir, {"kind": "broker_resume", "resumed": name})


def run_telemetry(config: dict, name: str, otlp: bool = False) -> dict:
    from telemetry import run_summary, to_otlp
    path = _result_path(_safe_run_dir(config, name))
    if path is None:
        raise ValueError("run has no result.json")
    result = json.loads(path.read_text(encoding="utf-8"))
    return to_otlp(result, start_ns=int(path.stat().st_mtime * 1e9)) if otlp else run_summary(result)


# ---------------------------------------------------------------- HTTP

class Handler(SimpleHTTPRequestHandler):
    store = StateStore()
    port = 8765

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(CONSOLE_DIR), **kwargs)

    def log_message(self, fmt, *args):
        sys.stderr.write("[jev-console] " + fmt % args + "\n")

    def end_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy",
                         "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
                         "connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'")
        super().end_headers()

    def send_json(self, data, status=HTTPStatus.OK):
        raw = json.dumps(data, indent=2, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _send_sse(self, generator):
        """Stream SSE events to the client. Each item from the generator is a
        pre-formatted 'data: ...\\n\\n' string. Flushes after each event so
        Hermes receives status updates in real time."""
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        for event in generator:
            self.wfile.write(event.encode("utf-8"))
            self.wfile.flush()

    def read_json(self):
        size = int(self.headers.get("Content-Length") or 0)
        if size > 2_000_000:
            raise ValueError("request too large")
        value = json.loads((self.rfile.read(size) if size else b"{}").decode("utf-8") or "{}")
        if not isinstance(value, dict):
            raise ValueError("JSON object required")
        return value

    def _guard(self, post: bool) -> bool:
        if not host_allowed(self.headers.get("Host"), self.port):
            self.send_json({"error": "host not allowed"}, HTTPStatus.FORBIDDEN)
            return False
        if post:
            if self.headers.get("X-CIDM-Console") != "1" or not origin_allowed(self.headers.get("Origin"), self.port):
                self.send_json({"error": "cross-origin request refused"}, HTTPStatus.FORBIDDEN)
                return False
            if "application/json" not in (self.headers.get("Content-Type") or ""):
                self.send_json({"error": "JSON content type required"}, HTTPStatus.UNSUPPORTED_MEDIA_TYPE)
                return False
        return True

    def _openai_guard(self) -> bool:
        """OpenAI-compat endpoint guard: loopback + Bearer <CIDM_API_KEY>.

        Hermes (and other OpenAI-shape clients) do not send the X-CIDM-Console
        browser-CSRF header. Instead we require Authorization: Bearer <token>
        matched against CIDM_API_KEY in the server's environment.
        """
        if not host_allowed(self.headers.get("Host"), self.port):
            self.send_json({"error": "host not allowed"}, HTTPStatus.FORBIDDEN)
            return False
        if "application/json" not in (self.headers.get("Content-Type") or ""):
            self.send_json({"error": "JSON content type required"}, HTTPStatus.UNSUPPORTED_MEDIA_TYPE)
            return False
        expected = os.environ.get("CIDM_API_KEY", "").strip()
        if not expected:
            self.send_json({"error": {"message": "CIDM_API_KEY not configured on server", "type": "auth_error"}},
                           HTTPStatus.UNAUTHORIZED)
            return False
        auth = self.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            self.send_json({"error": {"message": "missing Authorization: Bearer header", "type": "auth_error"}},
                           HTTPStatus.UNAUTHORIZED)
            return False
        if auth[len("Bearer "):].strip() != expected:
            self.send_json({"error": {"message": "invalid API key", "type": "auth_error"}}, HTTPStatus.UNAUTHORIZED)
            return False
        return True

    def _send_html(self, html: str, status=HTTPStatus.OK):
        raw = html.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if not self._guard(post=False):
            return
        config = self.store.load()
        parsed = urlparse.urlsplit(self.path)
        query = urlparse.parse_qs(parsed.query)
        path = parsed.path
        try:
            if path.startswith("/approve/"):
                token = path[len("/approve/"):].strip("/")
                target = _approvals_dir(config) / (token + ".json")
                if not token or not target.is_file():
                    self._send_html("<h1>Approval not found</h1>", HTTPStatus.NOT_FOUND)
                    return
                record = json.loads(target.read_text(encoding="utf-8"))
                esc = html_mod.escape
                html = (
                    "<!doctype html><html><head><meta charset='utf-8'>"
                    "<title>CIDM approval " + esc(token[:8]) + "</title></head>"
                    "<body style='font-family:system-ui;margin:2em;max-width:40em'>"
                    "<h1>CIDM Strong-Permit Approval</h1>"
                    "<p><b>Token:</b> " + esc(token) + "</p>"
                    "<p><b>Status:</b> " + esc(record["status"]) + "</p>"
                    "<p><b>Thread:</b> " + esc(record["thread_id"]) + "</p>"
                    "<p><b>Provider:</b> " + esc(record["provider"]) + "</p>"
                    "<p><b>Gate policy:</b> " + esc(record["gate_policy"]) + "</p>"
                    "<p><b>Goal:</b></p><pre>" + esc(record.get("goal") or "") + "</pre>"
                    "<p>Open the Operator Console, confirm the request, and POST to "
                    "<code>/api/approvals/" + esc(token) + "</code> with "
                    "<code>{\"decision\":\"approve\",\"operator\":\"you\"}</code>.</p>"
                    "</body></html>")
                self._send_html(html)
                return
            if path == "/api/state":
                self.send_json({"config": config, "runtime": {"hermes": hermes_status(config)},
                                "skills": merged_skills(config)})
            elif path == "/api/skills":
                self.send_json({"skills": merged_skills(config), "source": config["skills_source"]})
            elif path == "/api/providers":
                self.send_json(provider_overview(refresh=query.get("refresh") == ["1"]))
            elif path == "/api/arsenal":
                self.send_json(arsenal_overview(config))
            elif path == "/api/mcp":
                self.send_json(mcp_overview(config, (query.get("q") or [None])[0]))
            elif path == "/api/runs":
                self.send_json({"runs": list_runs(config), "root": str(_runs_root(config)),
                                "active_job": (JOBS.active() or {}).get("meta")})
            elif path.startswith("/api/runs/") and path.endswith("/telemetry"):
                self.send_json(run_telemetry(config, path.split("/")[3]))
            elif path.startswith("/api/runs/") and path.endswith("/otlp"):
                self.send_json(run_telemetry(config, path.split("/")[3], otlp=True))
            elif path.startswith("/api/jobs/"):
                self.send_json(JOBS.status(path.split("/")[3]))
            elif path == "/api/approvals":
                self.send_json(list_approvals(config))
            elif path.startswith("/api/"):
                self.send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)
            else:
                super().do_GET()
        except ValueError as exc:
            self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        except Exception as exc:
            self.send_json({"error": type(exc).__name__ + ": " + str(exc)[:300]}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def do_POST(self):
        if self.path == "/v1/chat/completions":
            if not self._openai_guard():
                return
            try:
                payload = self.read_json()
                config = self.store.load()
                if payload.get("stream") is True:
                    self._send_sse(chat_completions_stream(payload, config))
                else:
                    self.send_json(chat_completions(payload, config))
            except ValueError as exc:
                self.send_json({"error": {"message": str(exc), "type": "invalid_request_error"}},
                               HTTPStatus.BAD_REQUEST)
            except Exception as exc:
                self.send_json({"error": {"message": type(exc).__name__ + ": " + str(exc)[:300],
                                          "type": "server_error"}}, HTTPStatus.INTERNAL_SERVER_ERROR)
            return
        if not self._guard(post=True):
            return
        try:
            payload, config = self.read_json(), self.store.load()
            path = self.path
            if path == "/api/config":
                updated = _merge_config({**config, **payload})
                if isinstance(payload.get("providers"), dict):
                    updated["providers"] = config["providers"]
                    for name, provider_cfg in payload["providers"].items():
                        if name in updated["providers"] and isinstance(provider_cfg, dict):
                            updated["providers"][name].update(provider_cfg)
                self.send_json({"config": self.store.save(updated)})
            elif path == "/api/skills/open":
                target = Path(str(payload.get("path") or config["skills_source"])).expanduser()
                if target.exists() and not target.is_dir():
                    raise ValueError("only directories can be opened")
                open_folder(str(target))
                self.send_json({"ok": True})
            elif path == "/api/skills/toggle":
                name, enabled = str(payload.get("name") or "").strip(), bool(payload.get("enabled"))
                if not name:
                    raise ValueError("skill name is required")
                try:
                    result = hermes_api(config, "/api/skills/toggle", method="PUT",
                                        payload={"name": name, "enabled": enabled})
                except (OSError, urlerror.URLError, ValueError) as exc:
                    self.send_json({"ok": False, "error": "Hermes dashboard API is not reachable. Start hermes "
                                    "dashboard --no-open, then try again.", "detail": str(exc)},
                                   HTTPStatus.SERVICE_UNAVAILABLE)
                    return
                self.send_json({"ok": True, "result": result})
            elif path == "/api/provider/login":
                self.send_json(launch_login(str(payload.get("provider") or "")))
            elif path == "/api/providers/models":
                # Persist an account-derived model list for the console's picker.
                overview = provider_overview(refresh=True)
                codex = [m["slug"] for m in overview["codex"]["models"].get("models", [])
                         if m.get("visibility") == "list"]
                providers = copy.deepcopy(config["providers"])
                if codex:
                    providers["codex"]["models"] = codex
                    if providers["codex"]["model"] not in codex:
                        providers["codex"]["model"] = codex[0]
                self.send_json({"config": self.store.save({**config, "providers": providers}),
                                "providers": overview})
            elif path == "/api/route/preview":
                self.send_json(route_preview(payload, config))
            elif path == "/api/run":
                mode = str(payload.get("execution_mode") or config.get("execution_mode") or "preview")
                if mode == "preview":
                    self.send_json(route_preview(payload, config))
                elif mode == "frontier-direct":
                    self.send_json(run_frontier(payload, config))
                elif mode == "cidm-broker":
                    self.send_json(start_broker_job(payload, config), HTTPStatus.ACCEPTED)
                else:
                    raise ValueError("unknown execution mode")
            elif path == "/api/broker/validate":
                self.send_json(validate_broker_request(payload, config))
            elif path.startswith("/api/runs/") and path.endswith("/resume"):
                self.send_json(start_resume_job(path.split("/")[3], payload, config), HTTPStatus.ACCEPTED)
            elif path == "/api/mcp/refresh":
                if payload.get("confirm_start_server") is not True:
                    raise ValueError("refreshing starts the configured MCP server process; confirm_start_server is required")
                self.send_json(mcp_refresh(config, str(payload.get("server") or "")))
            elif path.startswith("/api/approvals/"):
                token = path[len("/api/approvals/"):].strip("/")
                decision = str(payload.get("decision") or "").strip()
                operator = str(payload.get("operator") or "").strip()
                self.send_json(_record_approval_decision(token, config,
                                                         decision=decision, operator=operator))
            else:
                self.send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)
        except (ValueError, json.JSONDecodeError) as exc:
            self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        except Exception as exc:
            self.send_json({"error": type(exc).__name__ + ": " + str(exc)[:300]}, HTTPStatus.INTERNAL_SERVER_ERROR)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run the local Jev Operator Console")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE_PATH)
    parser.add_argument("--no-open", action="store_true")
    args = parser.parse_args(argv)
    if args.host not in LOOPBACK:
        parser.error("the console binds to loopback only (127.0.0.1, localhost, ::1)")
    Handler.store = StateStore(args.state.expanduser())
    Handler.port = args.port
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    url = f"http://{'[::1]' if args.host == '::1' else args.host}:{args.port}"
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
