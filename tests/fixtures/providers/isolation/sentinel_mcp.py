"""Harmless sentinel MCP stdio server.

Invoked as: python -I sentinel_mcp.py MARKER_FILE TOOL_NAME
Records that it started and advertises one inert tool whose name is a sentinel.
"""
import json
import sys

marker, tool_name = sys.argv[1], sys.argv[2]
with open(marker, "a", encoding="utf-8") as fh:
    fh.write(tool_name + "\n")
for line in sys.stdin:
    try:
        msg = json.loads(line)
    except ValueError:
        continue
    if "id" not in msg:
        continue
    method = msg.get("method")
    if method == "initialize":
        result = {
            "protocolVersion": msg.get("params", {}).get("protocolVersion", "2024-11-05"),
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "recalith-sentinel", "version": "1"},
        }
    elif method == "tools/list":
        result = {"tools": [{"name": tool_name, "description": "Inert sentinel tool.", "inputSchema": {"type": "object", "properties": {}}}]}
    elif method == "tools/call":
        result = {"content": [{"type": "text", "text": "inert"}]}
    else:
        result = {}
    sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": msg["id"], "result": result}) + "\n")
    sys.stdout.flush()
