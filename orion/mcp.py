"""A minimal Model Context Protocol server over stdio (JSON-RPC 2.0), so Claude Code, Cursor or any MCP client
can call Orion as a tool: `orion mcp`. Implements initialize, tools/list and tools/call.
"""
from __future__ import annotations

import json
import sys

from . import __version__

TOOLS = [
    {"name": "orion_list_incidents", "description": "List the incidents Orion can investigate.",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "orion_investigate", "description": "Investigate an incident and return a verified, evidence-cited RCA.",
     "inputSchema": {"type": "object", "required": ["incident"],
                     "properties": {"incident": {"type": "string", "description": "scenario id"},
                                    "policy": {"type": "string", "default": "reference"}}}},
]


def handle(req: dict) -> dict | None:
    method, rid = req.get("method"), req.get("id")
    if method == "initialize":
        result = {"protocolVersion": "2025-03-26", "capabilities": {"tools": {}},
                  "serverInfo": {"name": "orion", "version": __version__}}
    elif method == "tools/list":
        result = {"tools": TOOLS}
    elif method == "tools/call":
        name, args = req["params"]["name"], req["params"].get("arguments", {})
        if name == "orion_list_incidents":
            from .estate.builder import list_scenarios
            text = "\n".join(list_scenarios())
        elif name == "orion_investigate":
            from .report import to_markdown
            from .runner import investigate
            text = to_markdown(investigate(args["incident"], args.get("policy", "reference")))
        else:
            return {"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": f"unknown tool {name}"}}
        result = {"content": [{"type": "text", "text": text}]}
    elif rid is None:
        return None  # notification
    else:
        return {"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": f"unknown method {method}"}}
    return {"jsonrpc": "2.0", "id": rid, "result": result}


def serve_stdio() -> None:
    for line in sys.stdin:
        if not line.strip():
            continue
        resp = handle(json.loads(line))
        if resp is not None:
            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()
