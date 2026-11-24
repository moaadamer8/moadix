#!/usr/bin/env python3
"""The allowlisting egress proxy for the confined runner's install step and builds (docs/confinement-design.md 3.4).

Runs inside a gate-started container that sits on two networks: the run's internal install (or build)
network (no route out) and an egress network. The install container reaches the package registries only
through it. It speaks HTTP CONNECT (for HTTPS) and refuses every host not on the allowlist given on
the command line, and every port but 443. It never decrypts traffic and carries no credentials.

0.8.3: hosts after --http (a build's OS package servers) may also be fetched over plain http: a GET or HEAD
in absolute form (http://host/path, port 80 only) is sent to that host as one request (Connection: close).
Every other method, host or port is refused.

    python3 egress_proxy.py <port> <host> [<host> ...] [--http <host> ...]
"""
import contextlib
import select
import socket
import sys
import threading


def pipe(a, b):
    socks = [a, b]
    try:
        while True:
            r, _w, x = select.select(socks, [], socks, 300)
            if x or not r:
                return
            for s in r:
                data = s.recv(65536)
                if not data:
                    return
                (b if s is a else a).sendall(data)
    except OSError:
        return
    finally:
        for s in socks:
            with contextlib.suppress(OSError):
                s.close()


def plain_http(conn, head, parts, http_allowed):
    """Forward one absolute-form GET/HEAD to an --http host on port 80; False when the request is not one."""
    method, url, version = parts
    if method not in ("GET", "HEAD") or not url.lower().startswith("http://") or not version.startswith("HTTP/1."):
        return False
    hostport, _, path = url[7:].partition("/")
    host, _, port = hostport.partition(":")
    if host.lower() not in http_allowed or port not in ("", "80") or "@" in hostport:
        return False
    lines = head.split(b"\r\n\r\n", 1)[0].split(b"\r\n")[1:]
    keep = [ln for ln in lines if ln.split(b":", 1)[0].strip().lower() not in
            (b"host", b"connection", b"proxy-connection", b"proxy-authorization", b"keep-alive")]
    req = ("%s /%s %s\r\nHost: %s\r\nConnection: close\r\n" % (method, path, version, host.lower())).encode("latin-1")
    up = socket.create_connection((host, 80), timeout=30)
    up.sendall(req + b"".join(ln + b"\r\n" for ln in keep) + b"\r\n")
    try:
        while True:
            data = up.recv(65536)
            if not data:
                break
            conn.sendall(data)
    finally:
        with contextlib.suppress(OSError):
            up.close()
    return True


def handle(conn, allowed, http_allowed=frozenset()):
    try:
        conn.settimeout(30)
        head = b""
        while b"\r\n\r\n" not in head and len(head) < 8192:
            chunk = conn.recv(4096)
            if not chunk:
                return
            head += chunk
        line = head.split(b"\r\n", 1)[0].decode("latin-1")
        parts = line.split()
        if len(parts) == 3 and parts[0] != "CONNECT" and http_allowed and plain_http(conn, head, parts, http_allowed):
            return
        if len(parts) != 3 or parts[0] != "CONNECT":
            sys.stderr.write("refused %s\n" % (parts[1] if len(parts) == 3 else "a request that is not CONNECT"))
            conn.sendall(b"HTTP/1.1 403 Not on the MOADIX allowlist\r\n\r\n" if http_allowed and len(parts) == 3
                         else b"HTTP/1.1 405 Only CONNECT\r\n\r\n")
            return
        host, _, port = parts[1].rpartition(":")
        if host.lower() not in allowed or port != "443":
            sys.stderr.write("refused %s\n" % parts[1])
            conn.sendall(b"HTTP/1.1 403 Not on the MOADIX allowlist\r\n\r\n")
            return
        up = socket.create_connection((host, 443), timeout=30)
        conn.sendall(b"HTTP/1.1 200 Connection established\r\n\r\n")
        conn.settimeout(None)
        up.settimeout(None)
        pipe(conn, up)
    except OSError:
        pass
    finally:
        with contextlib.suppress(OSError):
            conn.close()


def main(argv):
    port, rest = int(argv[0]), list(argv[1:])
    cut = rest.index("--http") if "--http" in rest else len(rest)
    allowed, http_allowed = {h.lower() for h in rest[:cut]}, frozenset(h.lower() for h in rest[cut + 1:])
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("0.0.0.0", port))  # noqa: S104 (inside its container; reachable only from the run's internal network)
    srv.listen(64)
    sys.stderr.write("moadix egress proxy on %d for %s%s\n" % (port, ", ".join(sorted(allowed)), (
        "; plain http for %s" % ", ".join(sorted(http_allowed))) if http_allowed else ""))
    while True:
        c, _a = srv.accept()
        threading.Thread(target=handle, args=(c, allowed, http_allowed), daemon=True).start()


if __name__ == "__main__":
    main(sys.argv[1:])
