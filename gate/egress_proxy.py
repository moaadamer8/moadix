#!/usr/bin/env python3
"""The allowlisting egress proxy for the confined runner's install step (docs/confinement-design.md 3.4).

Runs inside a gate-started container that sits on two networks: the run's internal install network
(no route out) and an egress network. The install container reaches the package registries only
through it. It speaks HTTP CONNECT (for HTTPS) and refuses every host not on the allowlist given on
the command line, and every port but 443. It never decrypts traffic and carries no credentials.

    python3 egress_proxy.py <port> <host> [<host> ...]
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


def handle(conn, allowed):
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
        if len(parts) != 3 or parts[0] != "CONNECT":
            conn.sendall(b"HTTP/1.1 405 Only CONNECT\r\n\r\n")
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
    port, allowed = int(argv[0]), {h.lower() for h in argv[1:]}
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("0.0.0.0", port))  # noqa: S104 (inside its container; reachable only from the run's internal network)
    srv.listen(64)
    sys.stderr.write("moadix egress proxy on %d for %s\n" % (port, ", ".join(sorted(allowed))))
    while True:
        c, _a = srv.accept()
        threading.Thread(target=handle, args=(c, allowed), daemon=True).start()


if __name__ == "__main__":
    main(sys.argv[1:])
