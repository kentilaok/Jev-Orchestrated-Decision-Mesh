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
    "local_continuity": {"worker_mode": "frontier_only", "model": "",
                         "project_scope": "demo", "fallback_enabled": False,
                         "max_parallel": 1},
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


def mcp_refresh(config: dict, server: str) -> dict:
    from mcp_registry import McpCatalog, client_for, discover_servers
    spec = next((s for s in discover_servers(project_dir=Path(config["project_directory"])) if s["name"] == server), None)
    if spec is None:
        raise ValueError("unknown configured server")
    with McpCatalog(Path(config["mcp_db"])) as catalog, client_for(spec) as client:
        client.initialize()
        return catalog.ingest(spec, client.list_tools())


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


def local_continuity_preview(payload: dict, config: dict) -> dict:
    from local_continuity_policy import decide_worker_mode
    settings = config.get("local_continuity") or {}
    mode = payload.get("worker_mode") or settings.get("worker_mode", "frontier_only")
    return {"status": "preview_only", "policy": decide_worker_mode(
        mode=mode, authority_mode="limited_local_continuity",
        fallback_enabled=settings.get("fallback_enabled") is True),
        "runtime_status": "local_only_worker_available_in_prototype; dual_and_auto_not_wired",
        "jev_authorised": False}


def start_local_continuity_job(payload: dict, config: dict) -> dict:
    # Only local-only mode is executable from the console in this stage.
    if payload.get("worker_mode") != "local_only":
        raise ValueError("only local_only mode is implemented for local console execution")
    if payload.get("confirm_local_execution") is not True:
        raise ValueError("confirm_local_execution_required")
    model = str(payload.get("local_model") or "").strip()
    scope = str(payload.get("project_scope") or "").strip()
    goal = str(payload.get("task") or "").strip()
    if not model or len(model) > 120 or not re.fullmatch(r"[A-Za-z0-9_.:/+-]+", model):
        raise ValueError("valid installed local model tag required")
    if not scope or not re.fullmatch(r"[A-Za-z0-9._-]{1,80}", scope):
        raise ValueError("valid project scope required")
    if not goal or len(goal) > 1200:
        raise ValueError("goal must contain 1-1200 characters")
    run_dir = _runs_root(config) / ("local-only-%s-%s" % (
        time.strftime("%Y%m%dT%H%M%S"), uuid.uuid4().hex[:6]))
    run_dir.mkdir(parents=True)
    argv = [sys.executable, str(SCRIPTS / "local_continuity_pipeline.py"),
            "--registry", config["arsenal_db"], "--model", model,
            "--project-scope", scope, "--goal", goal,
            "--learning-ledger", str(run_dir / "student-observations.jsonl"),
            "--out", str(run_dir / "result.json"), "--live-local"]
    return JOBS.start(argv, run_dir, {"kind": "local_only_proposals",
                                       "mode": "local_only", "model": model,
                                       "governance": "operator_read_only_no_jev_commit"})


def broker_argv(task_path: Path, out_dir: Path, provider: str, gate_policy: str, *, live: bool,
                resume: Path | None = None, operator: str | None = None, reset_rounds: bool = False) -> list[str]:
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
    argv = broker_argv(task_path, run_dir / "run", provider, gate_policy, live=True)
    return JOBS.start(argv, run_dir, {"kind": "broker_run", "provider": provider, "gate_policy": gate_policy})


def validate_broker_request(payload: dict, config: dict) -> dict:
    provider = payload.get("provider") or config["frontier_provider"]
    gate_policy = payload.get("gate_policy") or config.get("gate_policy", "recovery")
    request = build_request(payload)
    with tempfile.TemporaryDirectory() as temp:
        task_path = Path(temp) / "request.json"
        task_path.write_text(json.dumps(request), encoding="utf-8")
        proc = subprocess.run(broker_argv(task_path, Path(temp) / "out", provider, gate_policy, live=False),
                              capture_output=True, text=True, timeout=60, cwd=str(REPO_ROOT))
    if proc.returncode != 0:
        raise ValueError((proc.stderr or proc.stdout).strip().splitlines()[-1][:300])
    return {"validated": json.loads(proc.stdout.strip().splitlines()[-1]), "request": request}


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
    run_dir = _runs_root(config) / (source_dir.name + "-resume-" + uuid.uuid4().hex[:6])
    run_dir.mkdir(parents=True)
    shutil.copyfile(task, run_dir / "request.json")
    argv = broker_argv(run_dir / "request.json", run_dir / "run", previous.get("host") or "claude", "recovery",
                       live=True, resume=checkpoint, operator=operator,
                       reset_rounds=bool(payload.get("reset_recovery_rounds")))
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

    def do_GET(self):
        if not self._guard(post=False):
            return
        config = self.store.load()
        parsed = urlparse.urlsplit(self.path)
        query = urlparse.parse_qs(parsed.query)
        path = parsed.path
        try:
            if path == "/api/state":
                self.send_json({"config": config, "runtime": {"hermes": hermes_status(config)},
                                "skills": merged_skills(config)})
            elif path == "/api/skills":
                self.send_json({"skills": merged_skills(config), "source": config["skills_source"]})
            elif path == "/api/providers":
                self.send_json(provider_overview(refresh=query.get("refresh") == ["1"]))
            elif path == "/api/local/models":
                from ollama_provider import LocalOllamaTransport
                try:
                    names = LocalOllamaTransport(timeout=3).request("/api/tags").get("models", [])
                    self.send_json({"available": True,
                                    "models": [{"name": m.get("name"), "digest": m.get("digest")}
                                               for m in names if isinstance(m, dict)]})
                except Exception:
                    self.send_json({"available": False, "models": []})
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
            elif path.startswith("/api/"):
                self.send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)
            else:
                super().do_GET()
        except ValueError as exc:
            self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        except Exception as exc:
            self.send_json({"error": type(exc).__name__ + ": " + str(exc)[:300]}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def do_POST(self):
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
            elif path == "/api/local/preview":
                self.send_json(local_continuity_preview(payload, config))
            elif path == "/api/local/run":
                self.send_json(start_local_continuity_job(payload, config), HTTPStatus.ACCEPTED)
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
