"""Arsenal V1 Phase B: one frontier-provider contract over Claude Code and Codex.

    provider.status()        account/auth state, secret-free and redacted
    provider.list_models()   account-derived catalogue where the host exposes one
    provider.capabilities()  what the adapter can and cannot attest
    provider.run()           one bounded, tool-free, schema-checked call; needs a permit
    provider.cancel()        stop an in-flight run
    provider.usage()         reported usage for a finished run; unknown stays None

Both hosts use their own supported sign-in. This module never reads, copies,
or proxies OAuth tokens, browser cookies, or API keys. Unknown usage or cost is
reported as None, never zero, and no model is ever silently substituted.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
import subprocess
import threading
import uuid
from pathlib import Path
from typing import Any, Protocol

from capability_permits import PermitAuthority, digest, require


class FrontierProvider(Protocol):
    provider_id: str

    def status(self) -> dict: ...
    def list_models(self) -> dict: ...
    def capabilities(self) -> dict: ...
    def run(self, request: dict, permit_id: str) -> dict: ...
    def cancel(self, run_id: str) -> dict: ...
    def usage(self, run_id: str) -> dict: ...


def _run_status_command(argv: list[str], *, timeout: float = 20, runner=None) -> dict:
    """Run a read-only status command without a shell; never raise."""
    if runner is not None:
        return runner(argv, timeout)
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout,
                              encoding="utf-8", errors="replace", shell=False)
    except FileNotFoundError:
        return {"ok": False, "returncode": None, "stdout": "", "stderr": "command_not_found"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "returncode": None, "stdout": "", "stderr": "status_timeout"}
    return {"ok": proc.returncode == 0, "returncode": proc.returncode,
            "stdout": proc.stdout or "", "stderr": (proc.stderr or "")[-2000:]}


def _opaque(value: Any) -> str | None:
    """Stable non-identifying reference for an account or organisation id."""
    if not isinstance(value, str) or not value:
        return None
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


def _request_scope(provider_id: str, request: dict) -> dict:
    require(isinstance(request, dict), "invalid_frontier_request")
    require(set(request) == {"model", "effort", "prompt", "schema", "workspace"},
            "frontier_request_schema")
    require(isinstance(request["prompt"], str) and request["prompt"].strip(), "invalid_prompt")
    try:
        workspace = str(Path(request["workspace"]).resolve(strict=True))
    except (OSError, TypeError, ValueError):
        raise ValueError("invalid_workspace") from None
    return {"provider": provider_id, "model": request["model"], "effort": request["effort"],
            "workspace": workspace, "prompt_hash": digest(request["prompt"]),
            "schema_hash": digest(request["schema"])}


class _BoundedProvider:
    """Shared permit, cancellation, and usage bookkeeping for CLI providers."""

    provider_id = "base"

    def __init__(self, adapter, authority: PermitAuthority, *, executable: str, runner=None):
        self.adapter, self.authority = adapter, authority
        self.executable, self.runner = executable, runner
        self._runs: dict[str, dict] = {}
        self._cancel: dict[str, threading.Event] = {}
        self.lock = threading.Lock()

    @staticmethod
    def scope(provider_id: str, request: dict) -> dict:
        return _request_scope(provider_id, request)

    def run(self, request: dict, permit_id: str) -> dict:
        scope = _request_scope(self.provider_id, request)
        self.authority.consume(permit_id, "frontier.run", scope)
        run_id = uuid.uuid4().hex
        cancel = threading.Event()
        with self.lock:
            self._cancel[run_id] = cancel
            self._runs[run_id] = {"status": "running", "permit_id": permit_id, "usage": None}
        outcome: dict[str, Any] = {"status": "failed", "run_id": run_id}
        try:
            self.adapter.cancel_event = cancel
            response = self.adapter.run(request["model"], request["effort"], request["prompt"],
                                        request["schema"], request["workspace"])
            outcome = {"status": "ok", "run_id": run_id, "artifact_hash": digest(response["artifact"]),
                       "usage": response.get("usage"),
                       "identity_verification": response.get("identity_verification")}
            response = {**response, "run_id": run_id, "permit_id": permit_id, "provider": self.provider_id}
            return response
        except Exception as error:
            outcome = {"status": "cancelled" if cancel.is_set() else "failed", "run_id": run_id,
                       "error": str(error)[:200], "usage": getattr(error, "usage", None)}
            raise
        finally:
            self.adapter.cancel_event = None
            with self.lock:
                self._runs[run_id] = {"status": outcome["status"], "permit_id": permit_id,
                                      "usage": copy.deepcopy(outcome.get("usage"))}
                self._cancel.pop(run_id, None)
            self.authority.receipt(permit_id, outcome)

    def cancel(self, run_id: str) -> dict:
        with self.lock:
            event = self._cancel.get(run_id)
        if event is None:
            return {"run_id": run_id, "cancelled": False, "reason": "not_running"}
        event.set()
        return {"run_id": run_id, "cancelled": True}

    def usage(self, run_id: str) -> dict:
        with self.lock:
            record = copy.deepcopy(self._runs.get(run_id))
        require(record is not None, "unknown_frontier_run")
        return {"run_id": run_id, "status": record["status"], "usage": record["usage"],
                "usage_status": "reported" if isinstance(record["usage"], dict) else "unknown"}


class ClaudeCodeProvider(_BoundedProvider):
    """Claude Code headless worker. Primary V1 frontier provider."""

    provider_id = "claude"
    PRESETS = ("claude-sonnet-5", "claude-opus-5")

    def __init__(self, authority: PermitAuthority, *, adapter=None, executable="claude", runner=None,
                 env=None):
        if adapter is None:
            from claude_cli_adapter import ClaudeCliAdapter
            adapter = ClaudeCliAdapter(executable=executable)
        super().__init__(adapter, authority, executable=executable, runner=runner)
        self.env = os.environ if env is None else env

    def status(self) -> dict:
        installed = self.runner is not None or bool(shutil.which(self.executable))
        if not installed:
            return {"provider": self.provider_id, "installed": False, "logged_in": False,
                    "billing": "unknown", "detail": "Claude Code CLI not found"}
        result = _run_status_command([self.executable, "auth", "status", "--json"], runner=self.runner)
        try:
            data = json.loads(result["stdout"])
        except ValueError:
            data = None
        if not isinstance(data, dict):
            return {"provider": self.provider_id, "installed": True, "logged_in": None,
                    "billing": "unknown", "detail": "auth status output was not JSON"}
        method = data.get("authMethod")
        api_key_env = bool(self.env.get("ANTHROPIC_API_KEY"))
        billing = ("subscription" if method == "claude.ai" else
                   "api_key" if method in ("api_key", "apiKey", "console") else "unknown")
        warnings = []
        if api_key_env:
            warnings.append("ANTHROPIC_API_KEY is set; Claude Code may bill the API key instead of the subscription.")
        return {"provider": self.provider_id, "installed": True,
                "logged_in": data.get("loggedIn") is True, "auth_method": method,
                "api_provider": data.get("apiProvider"), "subscription_type": data.get("subscriptionType"),
                "billing": billing, "account_ref": _opaque(data.get("orgId")),
                "warnings": warnings}

    def list_models(self) -> dict:
        # Claude Code has no non-interactive catalogue; its /model menu is authoritative.
        return {"provider": self.provider_id, "account_derived": False,
                "source": "configured_presets_unverified",
                "models": [{"slug": slug, "efforts": ["low", "medium", "high", "xhigh"],
                            "visibility": "preset"} for slug in self.PRESETS],
                "note": "Verify availability with /model in Claude Code; presets are not an account catalogue."}

    def capabilities(self) -> dict:
        return {"provider": self.provider_id, "structured_output": True, "tools_disabled": True,
                "session_persistence": False, "usage_reporting": "cli_reported",
                "served_identity": "modelUsage_when_reported", "effort_attestation": "unavailable",
                "cost": "api_equivalent_estimate_not_a_bill", "cancel": True,
                "model_discovery": "presets_only"}


class CodexProvider(_BoundedProvider):
    """Codex CLI worker with account-derived model discovery (`codex debug models`)."""

    provider_id = "codex"

    def __init__(self, authority: PermitAuthority, *, adapter=None, executable="codex", runner=None,
                 astra_explicitly_authorized=False):
        if adapter is None:
            from codex_cli_adapter import CodexCliAdapter
            adapter = CodexCliAdapter(executable=executable,
                                      astra_explicitly_authorized=astra_explicitly_authorized)
        super().__init__(adapter, authority, executable=executable, runner=runner)

    def status(self) -> dict:
        installed = self.runner is not None or bool(shutil.which(self.executable))
        if not installed:
            return {"provider": self.provider_id, "installed": False, "logged_in": False,
                    "billing": "unknown", "detail": "Codex CLI not found"}
        result = _run_status_command([self.executable, "login", "status"], runner=self.runner)
        text = (result["stdout"] + "\n" + result["stderr"]).lower()
        logged_in = result["ok"] and "logged in" in text
        billing = ("chatgpt_plan" if logged_in and "chatgpt" in text else
                   "api_key" if logged_in and "api key" in text else "unknown")
        return {"provider": self.provider_id, "installed": True, "logged_in": logged_in,
                "billing": billing, "detail": result["stdout"].strip()[:200]}

    def list_models(self) -> dict:
        result = _run_status_command([self.executable, "debug", "models"], timeout=60, runner=self.runner)
        try:
            data = json.loads(result["stdout"]) if result["ok"] else None
        except ValueError:
            data = None
        if not isinstance(data, dict) or not isinstance(data.get("models"), list):
            return {"provider": self.provider_id, "account_derived": False, "source": "unavailable",
                    "models": [], "error": (result.get("stderr") or "catalogue_unavailable")[:200]}
        models = []
        for item in data["models"]:
            if not isinstance(item, dict) or not isinstance(item.get("slug"), str):
                continue
            levels = item.get("supported_reasoning_levels") or []
            efforts = [level.get("effort") for level in levels
                       if isinstance(level, dict) and isinstance(level.get("effort"), str)]
            models.append({"slug": item["slug"], "display_name": item.get("display_name"),
                           "visibility": item.get("visibility"), "efforts": efforts,
                           "default_effort": item.get("default_reasoning_level"),
                           "context_window": item.get("context_window")})
        return {"provider": self.provider_id, "account_derived": True, "source": "codex debug models",
                "catalogue_hash": digest(models), "models": models}

    def capabilities(self) -> dict:
        return {"provider": self.provider_id, "structured_output": True, "tools_disabled": True,
                "sandbox": "read-only", "session_persistence": False,
                "usage_reporting": "turn.completed.usage", "served_identity": "requested_only_unless_reported",
                "effort_attestation": "requested_only_unless_reported", "cost": "plan_usage_not_priced",
                "cancel": True, "model_discovery": "account_catalogue"}


def route_coverage(provider: FrontierProvider, routes: list[dict], *, checker: tuple[str, str],
                   catalogue: dict | None = None) -> dict:
    """Compare CIDM's frozen route catalogue with the provider's account catalogue.

    `covered` requires every worker route, the checker, and the short route.
    A preset (non-account) catalogue yields `unverified`, never `covered`.
    """
    catalogue = provider.list_models() if catalogue is None else catalogue
    needed = [(route["model"].split("/", 1)[-1], route["effort"], route.get("id", "")) for route in routes]
    needed.append((checker[0].split("/", 1)[-1], checker[1], "checker"))
    available = {model["slug"]: set(model.get("efforts") or []) for model in catalogue.get("models", [])}
    missing = [{"route": rid, "model": model, "effort": effort,
                "reason": "model_not_in_catalogue" if model not in available else "effort_not_supported"}
               for model, effort, rid in needed
               if model not in available or effort not in available[model]]
    if not catalogue.get("account_derived"):
        status = "unverified"
    elif not missing:
        status = "covered"
    elif len(missing) < len(needed):
        status = "partial"
    else:
        status = "unavailable"
    return {"provider": getattr(provider, "provider_id", None), "status": status,
            "account_derived": bool(catalogue.get("account_derived")),
            "source": catalogue.get("source"), "required": len(needed), "missing": missing,
            "catalogue_hash": catalogue.get("catalogue_hash")}


class PermittedAdapter:
    """Adapter shim so NativeTransitionBroker calls flow through a FrontierProvider.

    The broker calls `prepare(role, basis)` immediately before `run(...)`; the
    shim issues one `frontier.run` permit bound to that exact request and the
    caller-supplied authorization basis, then consumes it inside provider.run.
    """

    def __init__(self, provider: FrontierProvider, authority: PermitAuthority):
        self.provider, self.authority = provider, authority
        self._basis = None

    def prepare(self, basis: dict) -> None:
        self._basis = copy.deepcopy(basis)

    def run(self, model, effort, prompt, schema, workspace):
        require(self._basis is not None, "frontier_permit_basis_required")
        basis, self._basis = self._basis, None
        request = {"model": model, "effort": effort, "prompt": prompt, "schema": schema,
                   "workspace": str(workspace)}
        permit_id = self.authority.issue("frontier.run", _request_scope(self.provider.provider_id, request), basis)
        return self.provider.run(request, permit_id)


def build_provider(name: str, authority: PermitAuthority, **options) -> FrontierProvider:
    require(name in ("claude", "codex"), "unknown_frontier_provider")
    return ClaudeCodeProvider(authority, **options) if name == "claude" else CodexProvider(authority, **options)


def main(argv=None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description="Inspect CIDM frontier providers (no model calls)")
    parser.add_argument("command", choices=("status", "models", "coverage"))
    parser.add_argument("--provider", choices=("claude", "codex"), default="claude")
    parser.add_argument("--config", type=Path)
    args = parser.parse_args(argv)
    authority = PermitAuthority()
    provider = build_provider(args.provider, authority)
    if args.command == "status":
        output = provider.status()
    elif args.command == "models":
        output = provider.list_models()
    else:
        from config import RunConfig
        settings = json.loads(args.config.read_text(encoding="utf-8-sig")) if args.config else {}
        family = "claude" if args.provider == "claude" else "gpt6"
        config = RunConfig.from_dict({**settings, "worker_family": family})
        output = route_coverage(provider, list(config.worker_routes()),
                                checker=(config.checker_model, config.checker_effort))
    print(json.dumps(output, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
