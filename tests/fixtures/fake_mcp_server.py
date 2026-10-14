"""Tiny stdio MCP server for offline tests. Tools are fictional."""
import json
import sys

TOOLS = [
    {"name": "list_roblox_studios", "description": "List connected Studio instances. Read only.",
     "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "script_read", "description": "Read one script's source by path.",
     "inputSchema": {"type": "object", "properties": {"path": {"type": "string"}},
                     "required": ["path"], "additionalProperties": False}},
    {"name": "execute_luau", "description": "Run arbitrary Luau in Studio.",
     "inputSchema": {"type": "object", "properties": {"code": {"type": "string"}}, "required": ["code"]}},
    {"name": "lookup_ticket", "description": "Look up a support ticket by id.",
     "annotations": {"readOnlyHint": True},
     "inputSchema": {"type": "object", "properties": {"id": {"type": "integer"}}, "required": ["id"]}},
    {"name": "close_ticket", "description": "Close a support ticket.",
     "annotations": {"destructiveHint": True},
     "inputSchema": {"type": "object", "properties": {"id": {"type": "integer"}}, "required": ["id"]}},
    {"name": "mystery", "description": "Does something undocumented.",
     "inputSchema": {"type": "object", "properties": {}}},
]


def reply(ident, result=None, error=None):
    message = {"jsonrpc": "2.0", "id": ident}
    message["error" if error else "result"] = error or result
    sys.stdout.write(json.dumps(message) + "\n")
    sys.stdout.flush()


def main():
    sys.stdout.write("fake server log line, not JSON\n")
    sys.stdout.flush()
    for line in sys.stdin:
        message = json.loads(line)
        method, ident = message.get("method"), message.get("id")
        if ident is None:
            continue
        if method == "initialize":
            reply(ident, {"protocolVersion": "2025-06-18", "capabilities": {"tools": {}},
                          "serverInfo": {"name": "fake", "version": "0"}})
        elif method == "tools/list":
            cursor = (message.get("params") or {}).get("cursor")
            if cursor is None:
                reply(ident, {"tools": TOOLS[:3], "nextCursor": "page-2"})
            else:
                reply(ident, {"tools": TOOLS[3:]})
        elif method == "tools/call":
            params = message["params"]
            if params["name"] == "script_read":
                text = "-- " + params["arguments"]["path"] + "\nlocal speed = 16 -- WalkSpeed constant\n"
                reply(ident, {"content": [{"type": "text", "text": text}], "isError": False})
            elif params["name"] == "lookup_ticket":
                reply(ident, {"content": [{"type": "text", "text": "x" * 5000}]})
            else:
                reply(ident, {"content": [{"type": "text", "text": "ok"}]})
        else:
            reply(ident, error={"code": -32601, "message": "method not found"})


if __name__ == "__main__":
    main()
