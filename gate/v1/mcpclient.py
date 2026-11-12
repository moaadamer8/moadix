"""mcpclient -- a minimal MCP stdio client for the gate (increment 5; MOADIX-native).

The gate speaks MCP itself to read GitHub through the pinned github-mcp-server in
--read-only mode (phase 11), and the tests use it to list the tools a pinned
server exposes. JSON-RPC 2.0 over newline-delimited stdio, protocol 2025-06-18.
Stdlib only.
"""
import json
import os
import select
import subprocess
import time

PROTOCOL = "2025-06-18"


class MCPError(Exception):
    pass


class Client(object):
    def __init__(self, argv, env, cwd=None, timeout=60):
        self.timeout = timeout
        self.p = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                  env=env, cwd=cwd)
        self.n = 0
        self.buf = b""

    def _send(self, msg):
        self.p.stdin.write((json.dumps(msg) + "\n").encode())
        self.p.stdin.flush()

    def _read(self, want_id):
        deadline = time.time() + self.timeout
        while True:
            while b"\n" in self.buf:
                line, self.buf = self.buf.split(b"\n", 1)
                if not line.strip():
                    continue
                try:
                    msg = json.loads(line.decode("utf-8"))
                except ValueError:
                    continue
                if msg.get("id") == want_id:
                    if "error" in msg:
                        raise MCPError(str(msg["error"])[:300])
                    return msg.get("result")
            left = deadline - time.time()
            if left <= 0:
                raise MCPError("timed out waiting for the server")
            r, _, _ = select.select([self.p.stdout], [], [], left)
            if not r:
                continue
            chunk = os.read(self.p.stdout.fileno(), 65536)
            if not chunk:
                err = self.p.stderr.read().decode(errors="replace")[-400:] if self.p.poll() is not None else ""
                raise MCPError("the server closed its output (exit %s): %s" % (self.p.poll(), err))
            self.buf += chunk

    def call(self, method, params=None):
        self.n += 1
        self._send({"jsonrpc": "2.0", "id": self.n, "method": method, "params": params or {}})
        return self._read(self.n)

    def start(self):
        info = self.call("initialize", {"protocolVersion": PROTOCOL, "capabilities": {},
                                        "clientInfo": {"name": "moadix-gate", "version": "1"}})
        self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        return info

    def tools(self):
        out, cursor = [], None
        while True:
            r = self.call("tools/list", {"cursor": cursor} if cursor else {})
            out += r.get("tools") or []
            cursor = r.get("nextCursor")
            if not cursor:
                return out

    def tool(self, name, args):
        r = self.call("tools/call", {"name": name, "arguments": args or {}})
        if r.get("isError"):
            raise MCPError("%s: %s" % (name, json.dumps(r.get("content"))[:300]))
        texts = [c.get("text") for c in (r.get("content") or []) if c.get("type") == "text"]
        if r.get("structuredContent") is not None:
            return r["structuredContent"]
        try:
            return json.loads("".join(texts))
        except ValueError:
            return "".join(texts)

    def close(self):
        try:
            self.p.stdin.close()
            self.p.terminate()
            self.p.wait(timeout=5)
        except Exception:
            self.p.kill()
