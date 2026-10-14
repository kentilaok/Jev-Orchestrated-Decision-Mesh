"""Arsenal V1 Phase C: MCP as the capability bus, behind a compact catalogue.

    discover   read existing MCP configs (Claude Code, Codex, project .mcp.json);
               env values are never returned, only their names
    refresh    explicitly start one configured server and list its tools
    search     FTS5/BM25 over the catalogue; returns compact tool cards instead
               of every schema, and measures the context saved
    call       one permit-bound tools/call; read-only tools need `mcp.read`,
               anything else needs `mcp.mutate` (a Jev basis)

Each call yields an evidence receipt (server, tool, argument hash, result hash,
truncation, error) and a bounded CIDM source packet, so a recovery run can turn
Jev's `retrieve_evidence` into a read-only query and a fresh Jev decision.
Tool results are evidence, not instructions.
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import queue
import re
import shutil
import sqlite3
import subprocess
import threading
from pathlib import Path
from typing import Any, Callable
from urllib import request as urlrequest

from capability_permits import PermitAuthority, canonical, digest, require

PROTOCOL_VERSION = "2025-06-18"
SOURCE_TEXT_LIMIT = 1200
ACCESS = ("read", "mutate", "unknown", "blocked")

# Built-in classification for servers named in the CIDM MCP evidence guide.
PROFILES = {
    "roblox": {
        "read": {"list_roblox_studios", "get_studio_state", "search_game_tree", "script_search",
                 "script_grep", "script_read", "inspect_instance", "get_console_output",
                 "search_asset", "wait_job_finished", "screen_capture"},
        "mutate": {"execute_luau", "multi_edit", "start_stop_play", "insert_asset", "generate_material",
                   "generate_mesh", "generate_procedural_model", "generate_texture", "segment_mesh",
                   "user_keyboard_input", "user_mouse_input", "character_navigation", "store_image",
                   "upload_image", "http_get", "subagent", "skill"},
    },
}


class McpError(RuntimeError):
    pass


# ---------------------------------------------------------------- discovery

def _toml(path: Path) -> dict:
    try:
        import tomllib
    except ModuleNotFoundError:  # Python 3.10: Codex configs are skipped, not guessed.
        return {}
    with path.open("rb") as stream:
        return tomllib.load(stream)


def _spec(name: str, raw: dict, source: str) -> dict | None:
    if not isinstance(raw, dict) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", name):
        return None
    url = raw.get("url")
    command = raw.get("command")
    if isinstance(url, str) and url.startswith(("http://", "https://")):
        transport = "http"
    elif isinstance(command, str) and command:
        transport = "stdio"
    else:
        return None
    args = raw.get("args") or []
    env = raw.get("env") or {}
    return {"name": name, "source": source, "transport": transport,
            "command": command if transport == "stdio" else None,
            "args": [str(a) for a in args] if isinstance(args, list) else [],
            "url": url if transport == "http" else None,
            "_env": {str(k): str(v) for k, v in env.items()} if isinstance(env, dict) else {},
            "env_keys": sorted(env) if isinstance(env, dict) else [],
            "inherit_env": [str(v) for v in raw.get("env_vars") or []]}


def discover_servers(*, project_dir: Path | None = None, home: Path | None = None) -> list[dict]:
    """Read MCP server definitions. Nothing is executed."""
    home = Path(home or Path.home())
    project_dir = Path(project_dir or Path.cwd()).resolve()
    found: dict[str, dict] = {}

    def add(name, raw, source):
        spec = _spec(name, raw, source)
        if spec and name not in found:
            found[name] = spec

    for raw_path, label in ((project_dir / ".mcp.json", "project .mcp.json"),):
        try:
            data = json.loads(raw_path.read_text(encoding="utf-8"))
            for name, raw in (data.get("mcpServers") or {}).items():
                add(name, raw, label)
        except (OSError, ValueError, AttributeError):
            pass
    try:
        claude = json.loads((home / ".claude.json").read_text(encoding="utf-8"))
        project = (claude.get("projects") or {}).get(str(project_dir)) or \
            (claude.get("projects") or {}).get(project_dir.as_posix()) or {}
        for name, raw in (project.get("mcpServers") or {}).items():
            add(name, raw, "claude project config")
        for name, raw in (claude.get("mcpServers") or {}).items():
            add(name, raw, "claude user config")
    except (OSError, ValueError, AttributeError):
        pass
    try:
        codex = _toml(home / ".codex" / "config.toml")
        for name, raw in (codex.get("mcp_servers") or {}).items():
            add(name, raw, "codex config")
    except (OSError, ValueError):
        pass
    return [found[name] for name in sorted(found)]


def public_spec(spec: dict) -> dict:
    return {k: v for k, v in spec.items() if not k.startswith("_")}


# ---------------------------------------------------------------- clients

class StdioMcpClient:
    """Minimal MCP client over newline-delimited JSON-RPC on a child's stdio."""

    def __init__(self, command: str, args: list[str], *, env: dict | None = None, cwd: str | None = None,
                 timeout: float = 30, max_message_bytes: int = 4_000_000):
        self.argv = [shutil.which(command) or command, *args]
        self.env, self.cwd, self.timeout, self.max_bytes = env, cwd, timeout, max_message_bytes
        self.process = None
        self.messages: queue.Queue = queue.Queue()
        self.next_id = 1

    def __enter__(self):
        try:
            self.process = subprocess.Popen(self.argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                            stderr=subprocess.DEVNULL, cwd=self.cwd, env=self.env,
                                            shell=False)
        except OSError as error:
            raise McpError("mcp_server_unavailable") from error
        threading.Thread(target=self._read, daemon=True).start()
        return self

    def _read(self):
        for line in self.process.stdout:
            if len(line) > self.max_bytes:
                self.messages.put(McpError("mcp_message_too_large"))
                return
            try:
                self.messages.put(json.loads(line))
            except ValueError:
                continue  # servers may log non-JSON lines; they are not protocol messages
        self.messages.put(McpError("mcp_server_closed"))

    def _send(self, message: dict):
        self.process.stdin.write((json.dumps(message) + "\n").encode("utf-8"))
        self.process.stdin.flush()

    def request(self, method: str, params: dict | None = None) -> dict:
        ident = self.next_id
        self.next_id += 1
        self._send({"jsonrpc": "2.0", "id": ident, "method": method, "params": params or {}})
        while True:
            try:
                message = self.messages.get(timeout=self.timeout)
            except queue.Empty:
                raise McpError("mcp_timeout") from None
            if isinstance(message, Exception):
                raise message
            if message.get("id") != ident:
                continue  # notifications and server requests are ignored by this read-only client
            if "error" in message:
                raise McpError("mcp_error:" + str((message["error"] or {}).get("message", ""))[:160])
            return message.get("result") or {}

    def notify(self, method: str, params: dict | None = None):
        self._send({"jsonrpc": "2.0", "method": method, "params": params or {}})

    def initialize(self) -> dict:
        result = self.request("initialize", {"protocolVersion": PROTOCOL_VERSION, "capabilities": {},
                                             "clientInfo": {"name": "cidm-mcp-registry", "version": "1"}})
        self.notify("notifications/initialized")
        return result

    def list_tools(self, max_pages: int = 20) -> list[dict]:
        tools, cursor = [], None
        for _ in range(max_pages):
            result = self.request("tools/list", {"cursor": cursor} if cursor else {})
            tools.extend(t for t in result.get("tools") or [] if isinstance(t, dict))
            cursor = result.get("nextCursor")
            if not cursor:
                return tools
        raise McpError("mcp_tool_pagination_limit")

    def call_tool(self, name: str, arguments: dict) -> dict:
        return self.request("tools/call", {"name": name, "arguments": arguments})

    def __exit__(self, *_):
        if self.process is not None:
            try:
                self.process.stdin.close()
            except OSError:
                pass
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=3)
            if self.process.stdout is not None:
                self.process.stdout.close()


class HttpMcpClient:
    """Streamable-HTTP MCP client (JSON or single-response SSE)."""

    def __init__(self, url: str, *, headers: dict | None = None, timeout: float = 30, opener=None):
        self.url, self.headers, self.timeout = url, dict(headers or {}), timeout
        self.opener = opener or urlrequest.urlopen
        self.session = None
        self.next_id = 1

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None

    def _post(self, message: dict) -> dict | None:
        headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream",
                   **self.headers}
        if self.session:
            headers["Mcp-Session-Id"] = self.session
        req = urlrequest.Request(self.url, data=json.dumps(message).encode("utf-8"), headers=headers,
                                 method="POST")
        with self.opener(req, timeout=self.timeout) as response:
            self.session = response.headers.get("Mcp-Session-Id") or self.session
            body = response.read(4_000_000).decode("utf-8")
            if "text/event-stream" in (response.headers.get("Content-Type") or ""):
                payloads = [line[5:].strip() for line in body.splitlines() if line.startswith("data:")]
                body = next((p for p in reversed(payloads) if p), "")
        return json.loads(body) if body.strip() else None

    def request(self, method: str, params: dict | None = None) -> dict:
        ident = self.next_id
        self.next_id += 1
        message = self._post({"jsonrpc": "2.0", "id": ident, "method": method, "params": params or {}})
        if not isinstance(message, dict):
            raise McpError("mcp_empty_response")
        if "error" in message:
            raise McpError("mcp_error:" + str((message["error"] or {}).get("message", ""))[:160])
        return message.get("result") or {}

    def notify(self, method: str, params: dict | None = None):
        self._post({"jsonrpc": "2.0", "method": method, "params": params or {}})

    initialize = StdioMcpClient.initialize
    list_tools = StdioMcpClient.list_tools
    call_tool = StdioMcpClient.call_tool


def client_for(spec: dict, *, timeout: float = 30):
    if spec["transport"] == "http":
        return HttpMcpClient(spec["url"], timeout=timeout)
    env = None
    if spec.get("_env"):
        env = {**os.environ, **spec["_env"]}
    return StdioMcpClient(spec["command"], spec["args"], env=env, timeout=timeout)


# ---------------------------------------------------------------- catalogue

def classify(server: str, tool: dict) -> tuple[str, str]:
    """Return (access_class, basis). Unknown never defaults to read."""
    name = tool.get("name", "")
    for key, profile in PROFILES.items():
        if key in server.lower():
            if name in profile["read"]:
                return "read", "builtin_profile:" + key
            if name in profile["mutate"]:
                return "mutate", "builtin_profile:" + key
    hints = tool.get("annotations") or {}
    if hints.get("destructiveHint") is True or hints.get("readOnlyHint") is False:
        return "mutate", "server_annotations"
    if hints.get("readOnlyHint") is True and hints.get("openWorldHint") is not True:
        return "read", "server_annotations"
    return "unknown", "unclassified"


def _summary(text: str, limit: int = 160) -> str:
    text = " ".join((text or "").split())
    first = re.split(r"(?<=[.!?])\s", text, maxsplit=1)[0]
    return (first if len(first) <= limit else first[:limit - 1] + "…")


class McpCatalog:
    def __init__(self, db_path: Path):
        self.path = Path(db_path).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(self.path))
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS servers(name TEXT PRIMARY KEY, source TEXT, transport TEXT,
          spec_hash TEXT, tool_count INTEGER, catalogue_hash TEXT);
        CREATE TABLE IF NOT EXISTS tools(server TEXT, name TEXT, title TEXT, description TEXT,
          input_schema TEXT, schema_hash TEXT, annotations TEXT, access_class TEXT, access_basis TEXT,
          schema_bytes INTEGER, PRIMARY KEY(server, name));
        CREATE TABLE IF NOT EXISTS overrides(server TEXT, name TEXT, access_class TEXT, set_by TEXT,
          PRIMARY KEY(server, name));
        """)
        try:
            self.db.execute("CREATE VIRTUAL TABLE IF NOT EXISTS tools_fts USING "
                            "fts5(server UNINDEXED, name, description)")
            self.fts5 = True
        except sqlite3.OperationalError:
            self.fts5 = False
        self.db.commit()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.db.close()

    def ingest(self, spec: dict, tools: list[dict]) -> dict:
        require(isinstance(tools, list) and len(tools) <= 2000, "mcp_tool_list_too_large")
        rows = []
        for tool in tools:
            name = tool.get("name")
            if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_.:/-]{1,128}", name):
                continue
            schema = tool.get("inputSchema") if isinstance(tool.get("inputSchema"), dict) else {}
            access, basis = classify(spec["name"], tool)
            rows.append((spec["name"], name, str(tool.get("title") or "")[:200],
                         str(tool.get("description") or "")[:4000], canonical(schema), digest(schema),
                         canonical(tool.get("annotations") or {}), access, basis,
                         len(canonical(tool).encode("utf-8"))))
        with self.db:
            self.db.execute("DELETE FROM tools WHERE server=?", (spec["name"],))
            if self.fts5:
                self.db.execute("DELETE FROM tools_fts WHERE server=?", (spec["name"],))
            self.db.executemany("INSERT INTO tools VALUES(?,?,?,?,?,?,?,?,?,?)", rows)
            if self.fts5:
                self.db.executemany("INSERT INTO tools_fts VALUES(?,?,?)",
                                    [(r[0], r[1], r[2] + " " + r[3]) for r in rows])
            self.db.execute("INSERT OR REPLACE INTO servers VALUES(?,?,?,?,?,?)",
                            (spec["name"], spec["source"], spec["transport"], digest(public_spec(spec)),
                             len(rows), digest([r[1] + ":" + r[5] for r in rows])))
        return {"server": spec["name"], "tools": len(rows),
                "by_access": {a: sum(r[7] == a for r in rows) for a in ACCESS if any(r[7] == a for r in rows)}}

    def set_access(self, server: str, name: str, access_class: str, set_by: str) -> dict:
        require(access_class in ACCESS, "invalid_access_class")
        require(isinstance(set_by, str) and set_by.strip(), "override_owner_required")
        require(self._row(server, name) is not None, "unknown_mcp_tool")
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO overrides VALUES(?,?,?,?)", (server, name, access_class, set_by))
        return {"server": server, "tool": name, "access_class": access_class, "set_by": set_by}

    def _row(self, server: str, name: str):
        return self.db.execute("SELECT * FROM tools WHERE server=? AND name=?", (server, name)).fetchone()

    def access(self, server: str, name: str) -> tuple[str, str]:
        override = self.db.execute("SELECT access_class,set_by FROM overrides WHERE server=? AND name=?",
                                   (server, name)).fetchone()
        if override:
            return override["access_class"], "owner_override:" + override["set_by"]
        row = self._row(server, name)
        require(row is not None, "unknown_mcp_tool")
        return row["access_class"], row["access_basis"]

    def _card(self, row) -> dict:
        schema = json.loads(row["input_schema"])
        access, basis = self.access(row["server"], row["name"])
        return {"server": row["server"], "tool": row["name"],
                "summary": _summary(row["description"] or row["title"]),
                "access_class": access, "access_basis": basis,
                "required_args": list(schema.get("required") or [])[:12], "schema_hash": row["schema_hash"]}

    def search(self, query: str, *, top_k: int = 8, access: str | None = None, server: str | None = None) -> dict:
        require(isinstance(query, str) and query.strip() and 1 <= top_k <= 50, "invalid_mcp_search")
        terms = list(dict.fromkeys(t.lower() for t in re.findall(r"[A-Za-z0-9_]{2,}", query)))[:16]
        rows = []
        if terms and self.fts5:
            match = " OR ".join('"' + t + '"' for t in terms)
            try:
                keys = self.db.execute("SELECT server,name FROM tools_fts WHERE tools_fts MATCH ? "
                                       "ORDER BY bm25(tools_fts) LIMIT 200", (match,)).fetchall()
                rows = [self._row(k["server"], k["name"]) for k in keys]
            except sqlite3.OperationalError:
                rows = []
        if not rows:
            everything = self.db.execute("SELECT * FROM tools").fetchall()
            scored = [(sum(t in (r["name"] + " " + r["description"]).lower() for t in terms), r) for r in everything]
            rows = [r for score, r in sorted(scored, key=lambda x: -x[0]) if score > 0]
        cards = []
        for row in rows:
            if row is None or (server and row["server"] != server):
                continue
            card = self._card(row)
            if access and card["access_class"] != access:
                continue
            cards.append(card)
            if len(cards) >= top_k:
                break
        total = self.db.execute("SELECT COALESCE(SUM(schema_bytes),0) AS b, COUNT(*) AS n FROM tools").fetchone()
        compact = len(canonical(cards).encode("utf-8"))
        return {"query": query, "cards": cards,
                "context_budget": {"full_catalogue_tools": total["n"], "full_catalogue_bytes": total["b"],
                                   "returned_bytes": compact,
                                   "bytes_avoided": max(0, total["b"] - compact),
                                   "note": "Bytes, not tokens; tokenizer counts differ by provider."}}

    def describe(self, server: str, name: str) -> dict:
        row = self._row(server, name)
        require(row is not None, "unknown_mcp_tool")
        return {**self._card(row), "description": row["description"], "title": row["title"],
                "input_schema": json.loads(row["input_schema"]), "annotations": json.loads(row["annotations"])}

    def stats(self) -> dict:
        servers = [dict(r) for r in self.db.execute("SELECT * FROM servers ORDER BY name")]
        access = {r["access_class"]: r["n"] for r in self.db.execute(
            "SELECT access_class, COUNT(*) AS n FROM tools GROUP BY access_class")}
        return {"servers": servers, "tools_by_access": access, "fts5": self.fts5}


def _check_arguments(schema: dict, arguments: dict) -> None:
    require(isinstance(arguments, dict) and len(canonical(arguments)) <= 20_000, "invalid_mcp_arguments")
    props = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
    missing = [k for k in schema.get("required") or [] if k not in arguments]
    require(not missing, "mcp_missing_required_arguments")
    if schema.get("additionalProperties") is False:
        require(set(arguments) <= set(props), "mcp_unexpected_arguments")
    types = {"string": str, "integer": int, "number": (int, float), "boolean": bool,
             "object": dict, "array": list}
    for key, value in arguments.items():
        expected = (props.get(key) or {}).get("type")
        if isinstance(expected, str) and expected in types:
            ok = isinstance(value, types[expected]) and not (expected in ("integer", "number")
                                                             and isinstance(value, bool))
            require(ok, "mcp_argument_type_mismatch:" + key)


def _result_text(result: dict) -> str:
    parts = []
    for item in result.get("content") or []:
        if isinstance(item, dict) and item.get("type") == "text" and isinstance(item.get("text"), str):
            parts.append(item["text"])
        elif isinstance(item, dict):
            parts.append("[" + str(item.get("type")) + " content omitted]")
    if not parts and result.get("structuredContent") is not None:
        parts.append(canonical(result["structuredContent"]))
    return "\n".join(parts)


def permit_scope(server: str, tool: str, arguments: dict, access_class: str, schema_hash: str) -> dict:
    return {"server": server, "tool": tool, "arguments_hash": digest(arguments),
            "access_class": access_class, "schema_hash": schema_hash}


def call_tool(catalog: McpCatalog, spec: dict, tool: str, arguments: dict, permit_id: str,
              authority: PermitAuthority, *, client_factory: Callable = client_for,
              evidence_dir: Path | None = None) -> dict:
    """One permit-bound tools/call; returns an evidence receipt and a bounded source."""
    card = catalog.describe(spec["name"], tool)
    access = card["access_class"]
    require(access != "blocked", "mcp_tool_blocked_by_owner")
    capability = "mcp.read" if access == "read" else "mcp.mutate"
    _check_arguments(card["input_schema"], arguments)
    scope = permit_scope(spec["name"], tool, arguments, access, card["schema_hash"])
    authority.consume(permit_id, capability, scope)
    receipt: dict[str, Any] = {"server": spec["name"], "tool": tool, "access_class": access,
                               "arguments_hash": scope["arguments_hash"], "permit_id": permit_id,
                               "status": "failed", "result_hash": None, "bytes": 0, "truncated": False}
    try:
        with client_factory(spec) as client:
            client.initialize()
            result = client.call_tool(tool, arguments)
        text = _result_text(result)
        receipt.update(status="tool_error" if result.get("isError") else "ok",
                       result_hash=digest(result), bytes=len(text.encode("utf-8")),
                       truncated=len(text) > SOURCE_TEXT_LIMIT)
        if evidence_dir is not None:
            folder = Path(evidence_dir)
            folder.mkdir(parents=True, exist_ok=True)
            (folder / (receipt["result_hash"] + ".json")).write_text(
                json.dumps({"receipt": receipt, "arguments": arguments, "result": result}, indent=2),
                encoding="utf-8")
            receipt["full_result_ref"] = str(folder / (receipt["result_hash"] + ".json"))
        source_text = text[:SOURCE_TEXT_LIMIT - 1] + "…" if receipt["truncated"] else text
        source = {"title": (spec["name"] + " " + tool)[:120], "text": source_text or "[empty tool result]"}
        return {"receipt": receipt, "source": source}
    except Exception as error:
        receipt["error"] = type(error).__name__ + ": " + str(error)[:200]
        raise McpError("mcp_call_failed") from error
    finally:
        authority.receipt(permit_id, receipt)


class McpEvidenceRetriever:
    """RecoverySupervisor evidence callback backed by a bounded read-only MCP plan.

    Each `retrieve_evidence` outcome runs the next planned read-only call and
    returns it as a new, hashed source; the unit is then re-gated by Jev.
    """

    def __init__(self, catalog: McpCatalog, servers: dict[str, dict], authority: PermitAuthority,
                 plan: list[dict], *, max_calls: int = 4, client_factory: Callable = client_for,
                 evidence_dir: Path | None = None):
        require(isinstance(plan, list) and 0 < len(plan) <= 16 and 1 <= max_calls <= 16, "invalid_evidence_plan")
        for step in plan:
            require(isinstance(step, dict) and {"server", "tool", "arguments"} <= set(step)
                    and set(step) <= {"server", "tool", "arguments", "title"}, "invalid_evidence_step")
            require(step["server"] in servers, "evidence_plan_unknown_server")
            require(catalog.access(step["server"], step["tool"])[0] == "read",
                    "evidence_plan_requires_read_only_tool")
        self.catalog, self.servers, self.authority = catalog, servers, authority
        self.plan, self.max_calls = copy.deepcopy(plan), max_calls
        self.client_factory, self.evidence_dir = client_factory, evidence_dir
        self.receipts: list[dict] = []
        self.cursor = 0

    def __call__(self, packet: dict) -> dict | None:
        if self.cursor >= len(self.plan) or len(self.receipts) >= self.max_calls:
            return None
        step = self.plan[self.cursor]
        self.cursor += 1
        events = packet.get("events") or []
        decision = next((e for e in reversed(events) if e.get("kind") == "post_worker_decision"
                         and e.get("choice") == "retrieve_evidence"), None) or \
            next((e for e in reversed(events) if e.get("kind") == "jev_decision"), {})
        basis = {"kind": "cidm_recovery_evidence", "unit_id": packet["unit"]["id"],
                 "decision_event_id": decision.get("id") or "unknown",
                 "mesh_version": (events[-1].get("version") if events else 0) or 0}
        card = self.catalog.describe(step["server"], step["tool"])
        scope = permit_scope(step["server"], step["tool"], step["arguments"], card["access_class"],
                             card["schema_hash"])
        permit = self.authority.issue("mcp.read", scope, basis)
        try:
            outcome = call_tool(self.catalog, self.servers[step["server"]], step["tool"], step["arguments"],
                                permit, self.authority, client_factory=self.client_factory,
                                evidence_dir=self.evidence_dir)
        except McpError as error:
            self.receipts.append({"step": self.cursor - 1, "status": "failed", "error": str(error)})
            return None
        self.receipts.append({"step": self.cursor - 1, **outcome["receipt"]})
        source_id = ("mcp-" + re.sub(r"[^A-Za-z0-9]", "", step["tool"])[:24] + "-"
                     + outcome["receipt"]["result_hash"][:8])
        title = step.get("title") or outcome["source"]["title"]
        return {source_id: {"title": title[:120], "text": outcome["source"]["text"]}}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="CIDM MCP capability catalogue")
    parser.add_argument("--db", type=Path, default=Path("~/.jev/arsenal/mcp.db").expanduser())
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("servers", help="List configured MCP servers (nothing is started)")
    refresh = sub.add_parser("refresh", help="Start one configured server and catalogue its tools")
    refresh.add_argument("--server", required=True)
    search = sub.add_parser("search")
    search.add_argument("--query", required=True)
    search.add_argument("--access", choices=ACCESS)
    search.add_argument("--top-k", type=int, default=8)
    describe = sub.add_parser("describe")
    describe.add_argument("--server", required=True)
    describe.add_argument("--tool", required=True)
    override = sub.add_parser("classify", help="Owner override of a tool's access class")
    override.add_argument("--server", required=True)
    override.add_argument("--tool", required=True)
    override.add_argument("--access", choices=ACCESS, required=True)
    override.add_argument("--owner", required=True)
    sub.add_parser("stats")
    args = parser.parse_args(argv)
    if args.command == "servers":
        output = {"servers": [public_spec(s) for s in discover_servers()]}
    else:
        with McpCatalog(args.db) as catalog:
            if args.command == "refresh":
                spec = next((s for s in discover_servers() if s["name"] == args.server), None)
                require(spec is not None, "unknown_configured_server")
                with client_for(spec) as client:
                    client.initialize()
                    output = catalog.ingest(spec, client.list_tools())
            elif args.command == "search":
                output = catalog.search(args.query, top_k=args.top_k, access=args.access)
            elif args.command == "describe":
                output = catalog.describe(args.server, args.tool)
            elif args.command == "classify":
                output = catalog.set_access(args.server, args.tool, args.access, args.owner)
            else:
                output = catalog.stats()
    print(json.dumps(output, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
