#!/usr/bin/python3
"""Fixture stand-in for github-mcp-server (increment 5): an MCP stdio server that
answers the read tools check_release calls from spec.json next to this file.

spec.json: {"tools": [extra tool names to list, e.g. "merge_pull_request"],
            "token_required": true,
            "commit": {...} | null, "prs": [...], "pr": {...},
            "runs": [...], "alerts": [...]}
argv is logged to calls.log so the suite can see --read-only was passed.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.realpath(__file__))
with open(os.path.join(HERE, "calls.log"), "a") as f:
    f.write(json.dumps({"argv": sys.argv[1:], "token": bool(os.environ.get("GITHUB_PERSONAL_ACCESS_TOKEN"))}) + "\n")
with open(os.path.join(HERE, "spec.json")) as f:
    SPEC = json.load(f)
READ = ["actions_get", "actions_list", "get_code_scanning_alert", "get_commit", "list_code_scanning_alerts",
        "pull_request_read", "search_pull_requests", "list_commits"]


def answer(name, args):
    if name == "get_commit":
        return SPEC.get("commit")
    if name == "search_pull_requests":
        return {"total_count": len(SPEC.get("prs") or []), "items": SPEC.get("prs") or []}
    if name == "pull_request_read":
        return SPEC.get("pr")
    if name == "actions_list":
        return {"total_count": len(SPEC.get("runs") or []), "workflow_runs": SPEC.get("runs") or []}
    if name == "list_code_scanning_alerts":
        return SPEC.get("alerts") or []
    return None


for line in sys.stdin:
    try:
        msg = json.loads(line)
    except ValueError:
        continue
    mid, method = msg.get("id"), msg.get("method")
    if mid is None:
        continue
    if method == "initialize":
        res = {"protocolVersion": "2025-06-18", "capabilities": {"tools": {}},
               "serverInfo": {"name": "github-mcp-stub", "version": "fixture"}}
    elif method == "tools/list":
        res = {"tools": [{"name": n, "inputSchema": {"type": "object"}} for n in READ + (SPEC.get("tools") or [])]}
    elif method == "tools/call":
        p = msg.get("params") or {}
        out = answer(p.get("name"), p.get("arguments") or {})
        res = {"content": [{"type": "text", "text": json.dumps(out)}]}
    else:
        res = {}
    sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": mid, "result": res}) + "\n")
    sys.stdout.flush()
