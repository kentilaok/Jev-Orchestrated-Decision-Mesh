"""Arsenal V1 Phase F: isolated code execution behind a provider-neutral contract.

    provider.create(spec, snapshot, permit)        sandbox.create
    provider.exec(id, argv, permit, ...)           sandbox.exec (+ secret.use for secrets)
    provider.export_artifacts(id, globs, permit)   sandbox.import_artifacts (strong)
    provider.destroy(id) / reap_expired()

CIDM controls whether a sandbox may exist, the project snapshot, CPU/RAM/PID
limits, egress (V1 Docker supports `none` only; an allowlist needs a proxying
provider), the TTL, and which artifacts may come back. Secrets are capability
references resolved at exec time into the Docker CLI's environment and passed by
name (`-e NAME`), so values never appear in argv, ledgers, or prompts, and are
redacted from captured output. The sandbox never receives commit authority.
"""
from __future__ import annotations

import fnmatch
import hashlib
import io
import os
import re
import subprocess
import tarfile
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Callable

from capability_permits import PermitAuthority, digest, require

OUTPUT_LIMIT = 65_536
SNAPSHOT_EXCLUDES = {".git", "node_modules", "__pycache__", ".venv", "venv", "runs", ".pytest_cache"}


@dataclass(frozen=True)
class SandboxSpec:
    image: str
    cpu_limit: float = 1.0
    memory_mb: int = 1024
    pids_limit: int = 256
    network: str = "none"
    ttl_seconds: int = 900
    workdir: str = "/workspace"
    user: str | None = None

    def __post_init__(self):
        require(isinstance(self.image, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/:@-]{0,199}", self.image),
                "invalid_sandbox_image")
        require(type(self.cpu_limit) in (int, float) and 0.1 <= self.cpu_limit <= 16, "invalid_cpu_limit")
        require(type(self.memory_mb) is int and 64 <= self.memory_mb <= 65_536, "invalid_memory_limit")
        require(type(self.pids_limit) is int and 16 <= self.pids_limit <= 4096, "invalid_pids_limit")
        require(self.network in ("none", "allowlist"), "invalid_network_policy")
        require(type(self.ttl_seconds) is int and 30 <= self.ttl_seconds <= 86_400, "invalid_sandbox_ttl")
        require(re.fullmatch(r"/[A-Za-z0-9._/-]{1,120}", self.workdir) and ".." not in self.workdir,
                "invalid_sandbox_workdir")
        require(self.user is None or re.fullmatch(r"[A-Za-z0-9_:-]{1,64}", self.user), "invalid_sandbox_user")


class SecretBroker:
    """Owner-registered secret references -> environment variable names.

    `secret://env/NAME` resolves only when the owner registered that reference.
    The broker returns values solely to the subprocess environment it builds.
    """

    REF = re.compile(r"secret://env/([A-Z][A-Z0-9_]{0,63})")

    def __init__(self, allowed_refs: list[str], *, env=None):
        for ref in allowed_refs:
            require(isinstance(ref, str) and self.REF.fullmatch(ref), "invalid_secret_reference")
        self.allowed, self.env = set(allowed_refs), os.environ if env is None else env

    def resolve(self, refs: list[str]) -> dict[str, str]:
        values = {}
        for ref in refs:
            require(ref in self.allowed, "secret_reference_not_registered")
            name = self.REF.fullmatch(ref).group(1)
            require(name in self.env and self.env[name], "secret_not_available")
            values[name] = self.env[name]
        return values


def _default_runner(argv, *, input_bytes=None, timeout=120, env=None):
    try:
        proc = subprocess.run(argv, input=input_bytes, capture_output=True, timeout=timeout, env=env, shell=False)
    except FileNotFoundError:
        return 127, b"", b"docker_not_found"
    except subprocess.TimeoutExpired:
        return 124, b"", b"sandbox_command_timeout"
    return proc.returncode, proc.stdout, proc.stderr


def build_snapshot(root: Path, *, max_files: int = 5000, max_bytes: int = 50_000_000) -> tuple[bytes, str, int]:
    """Deterministic tar of a project directory (regular files only, no symlinks)."""
    root = Path(root).resolve(strict=True)
    require(root.is_dir(), "snapshot_root_must_be_directory")
    files = []
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root)
        if any(part in SNAPSHOT_EXCLUDES for part in rel.parts) or path.is_symlink() or not path.is_file():
            continue
        files.append((rel.as_posix(), path))
        require(len(files) <= max_files, "snapshot_file_limit_exceeded")
    buffer, manifest, total = io.BytesIO(), [], 0
    with tarfile.open(fileobj=buffer, mode="w", format=tarfile.PAX_FORMAT) as archive:
        for rel, path in files:
            data = path.read_bytes()
            total += len(data)
            require(total <= max_bytes, "snapshot_size_limit_exceeded")
            info = tarfile.TarInfo(rel)
            info.size, info.mtime, info.mode = len(data), 0, 0o644
            archive.addfile(info, io.BytesIO(data))
            manifest.append((rel, hashlib.sha256(data).hexdigest()))
    return buffer.getvalue(), digest(manifest), len(files)


class DockerSandboxProvider:
    provider_id = "docker"

    def __init__(self, authority: PermitAuthority, *, runner: Callable | None = None, docker: str = "docker",
                 secrets: SecretBroker | None = None, clock=time.time):
        self.authority, self.runner, self.docker = authority, runner or _default_runner, docker
        self.secrets, self.clock = secrets, clock
        self.sandboxes: dict[str, dict] = {}

    def _docker(self, *args, input_bytes=None, timeout=120, env=None):
        return self.runner([self.docker, *args], input_bytes=input_bytes, timeout=timeout, env=env)

    def status(self) -> dict:
        code, out, err = self._docker("info", "--format", "{{.ServerVersion}}", timeout=20)
        return {"provider": self.provider_id, "available": code == 0,
                "server_version": out.decode("utf-8", "replace").strip() if code == 0 else None,
                "egress_policies": ["none"], "detail": None if code == 0 else err.decode("utf-8", "replace")[:200]}

    @staticmethod
    def create_scope(spec: SandboxSpec, snapshot_hash: str | None) -> dict:
        return {"spec": asdict(spec), "snapshot_hash": snapshot_hash}

    def create(self, spec: SandboxSpec, snapshot: Path | None, permit_id: str) -> dict:
        require(isinstance(spec, SandboxSpec), "sandbox_spec_required")
        require(spec.network == "none", "egress_allowlist_requires_proxy_provider")
        archive, snapshot_hash, files = (build_snapshot(snapshot) if snapshot is not None else (None, None, 0))
        self.authority.consume(permit_id, "sandbox.create", self.create_scope(spec, snapshot_hash))
        sandbox_id = "cidm-" + uuid.uuid4().hex[:12]
        expires = int(self.clock() + spec.ttl_seconds)
        args = ["create", "--name", sandbox_id, "--label", "cidm.sandbox=1", "--label", "cidm.expires=%d" % expires,
                "--network", "none", "--cpus", str(spec.cpu_limit), "--memory", "%dm" % spec.memory_mb,
                "--pids-limit", str(spec.pids_limit), "--security-opt", "no-new-privileges",
                "--cap-drop", "ALL", "-w", spec.workdir]
        if spec.user:
            args += ["--user", spec.user]
        # `sleep TTL` as PID 1 makes the container stop itself when the TTL ends.
        args += [spec.image, "sleep", str(spec.ttl_seconds)]
        outcome = {"status": "failed", "sandbox_id": sandbox_id}
        try:
            code, _, err = self._docker(*args)
            require(code == 0, "sandbox_create_failed:" + err.decode("utf-8", "replace")[:120])
            code, _, err = self._docker("start", sandbox_id)
            require(code == 0, "sandbox_start_failed")
            if archive is not None:
                code, _, err = self._docker("exec", sandbox_id, "mkdir", "-p", spec.workdir)
                require(code == 0, "sandbox_workdir_failed")
                code, _, err = self._docker("cp", "-", sandbox_id + ":" + spec.workdir, input_bytes=archive)
                require(code == 0, "sandbox_snapshot_copy_failed")
            record = {"sandbox_id": sandbox_id, "spec": asdict(spec), "snapshot_hash": snapshot_hash,
                      "snapshot_files": files, "expires_at": expires, "state": "running"}
            self.sandboxes[sandbox_id] = record
            outcome = {"status": "ok", **record}
            return dict(record)
        except Exception:
            self._docker("rm", "-f", sandbox_id, timeout=60)
            raise
        finally:
            self.authority.receipt(permit_id, outcome)

    def _live(self, sandbox_id: str) -> dict:
        record = self.sandboxes.get(sandbox_id)
        require(record is not None and record["state"] == "running", "unknown_or_stopped_sandbox")
        require(self.clock() < record["expires_at"], "sandbox_ttl_expired")
        return record

    @staticmethod
    def exec_scope(sandbox_id: str, argv: list[str], secret_refs: list[str]) -> dict:
        return {"sandbox_id": sandbox_id, "argv_hash": digest(argv), "secret_refs": sorted(secret_refs)}

    def exec(self, sandbox_id: str, argv: list[str], permit_id: str, *, timeout: int = 120,
             secret_refs: list[str] = (), secret_permit_id: str | None = None) -> dict:
        record = self._live(sandbox_id)
        require(isinstance(argv, list) and argv and all(isinstance(a, str) and "\x00" not in a for a in argv),
                "invalid_sandbox_argv")
        secret_refs = list(secret_refs)
        scope = self.exec_scope(sandbox_id, argv, secret_refs)
        self.authority.consume(permit_id, "sandbox.exec", scope)
        env, names = None, []
        if secret_refs:
            require(self.secrets is not None and secret_permit_id is not None, "secret_use_permit_required")
            self.authority.consume(secret_permit_id, "secret.use", scope)
            values = self.secrets.resolve(secret_refs)
            names = sorted(values)
            env = {**os.environ, **values}
        outcome = {"status": "failed", "sandbox_id": sandbox_id}
        try:
            args = ["exec", "-w", record["spec"]["workdir"]]
            for name in names:
                args += ["-e", name]  # value read from the CLI environment, never from argv
            started = time.monotonic()
            code, out, err = self._docker(*args, sandbox_id, *argv, timeout=timeout, env=env)
            stdout = out[:OUTPUT_LIMIT].decode("utf-8", "replace")
            stderr = err[:OUTPUT_LIMIT].decode("utf-8", "replace")
            for name in names:
                secret = env[name]
                stdout, stderr = stdout.replace(secret, "***"), stderr.replace(secret, "***")
            outcome = {"status": "ok" if code == 0 else "nonzero_exit", "sandbox_id": sandbox_id,
                       "exit_code": code, "stdout": stdout, "stderr": stderr,
                       "stdout_truncated": len(out) > OUTPUT_LIMIT, "stderr_truncated": len(err) > OUTPUT_LIMIT,
                       "duration_seconds": round(time.monotonic() - started, 3), "secret_names": names}
            return outcome
        finally:
            self.authority.receipt(permit_id, {k: v for k, v in outcome.items() if k not in ("stdout", "stderr")}
                                   | {"stdout_hash": digest(outcome.get("stdout", "")),
                                      "stderr_hash": digest(outcome.get("stderr", ""))})
            if secret_permit_id is not None and secret_refs:
                self.authority.receipt(secret_permit_id, {"status": outcome["status"], "secret_names": names})

    @staticmethod
    def export_scope(sandbox_id: str, patterns: list[str], dest: Path) -> dict:
        return {"sandbox_id": sandbox_id, "patterns": sorted(patterns), "dest": str(Path(dest).resolve())}

    def export_artifacts(self, sandbox_id: str, patterns: list[str], dest: Path, permit_id: str, *,
                         max_bytes: int = 20_000_000) -> dict:
        record = self._live(sandbox_id)
        require(isinstance(patterns, list) and patterns and all(isinstance(p, str) and p for p in patterns),
                "artifact_patterns_required")
        dest = Path(dest)
        self.authority.consume(permit_id, "sandbox.import_artifacts", self.export_scope(sandbox_id, patterns, dest))
        outcome = {"status": "failed", "sandbox_id": sandbox_id, "artifacts": []}
        try:
            code, out, err = self._docker("cp", sandbox_id + ":" + record["spec"]["workdir"] + "/.", "-",
                                          timeout=300)
            require(code == 0, "artifact_export_failed")
            total, artifacts = 0, []
            dest.mkdir(parents=True, exist_ok=True)
            root = dest.resolve()
            with tarfile.open(fileobj=io.BytesIO(out), mode="r:") as archive:
                for member in archive.getmembers():
                    name = PurePosixPath(member.name)
                    parts = [p for p in name.parts if p not in (".", "")]
                    if not member.isfile() or not parts or name.is_absolute() or ".." in parts:
                        continue
                    rel = "/".join(parts)
                    if not any(fnmatch.fnmatch(rel, pattern) for pattern in patterns):
                        continue
                    total += member.size
                    require(total <= max_bytes, "artifact_size_limit_exceeded")
                    data = archive.extractfile(member).read()
                    target = (root / rel).resolve()
                    require(target.is_relative_to(root), "artifact_path_escape")
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(data)
                    artifacts.append({"path": rel, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)})
            outcome = {"status": "ok", "sandbox_id": sandbox_id, "artifacts": artifacts}
            return outcome
        finally:
            self.authority.receipt(permit_id, outcome)

    def destroy(self, sandbox_id: str) -> dict:
        code, _, _ = self._docker("rm", "-f", sandbox_id, timeout=60)
        if sandbox_id in self.sandboxes:
            self.sandboxes[sandbox_id]["state"] = "destroyed"
        return {"sandbox_id": sandbox_id, "destroyed": code == 0}

    def reap_expired(self) -> dict:
        code, out, _ = self._docker("ps", "-a", "--filter", "label=cidm.sandbox=1",
                                    "--format", '{{.Names}} {{.Label "cidm.expires"}}', timeout=60)
        removed = []
        if code == 0:
            now = self.clock()
            for line in out.decode("utf-8", "replace").splitlines():
                name, _, expires = line.partition(" ")
                if expires.strip().isdigit() and int(expires) <= now:
                    if self._docker("rm", "-f", name, timeout=60)[0] == 0:
                        removed.append(name)
        return {"removed": removed}
