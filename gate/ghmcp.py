#!/usr/bin/python3
"""Launcher for the plugin's `github` MCP server (increment 6, ruling 2).

plugin.json starts the agent's read-only GitHub MCP server through this file
(root-owned, in MOADIX_HOME/gate) instead of with `${MOADIX_GITHUB_TOKEN}`:

  * the token is read here, by the gate, from the login Keychain item
    `moadix-github-readonly` (gate/v1/toolrun.github_token). The operator never
    exports it in the shell Claude Code (and so the agent's Bash) runs in;
  * it is handed to the pinned github-mcp-server process only, in that process's
    own environment, with nothing else from the user's environment;
  * the server runs `stdio --read-only` with the toolsets the phase-11 work needs.

Before a product reaches phase 11 no token is needed: without one this prints a
one-line reason to stderr and exits 1, so `/mcp` shows the server as failed. That
is expected. The manifest allows the server only in phase 11 anyway.
"""
import os
import sys

GATE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, os.path.dirname(GATE))
sys.path.insert(0, os.path.join(GATE, "v1"))

ARGS = ["stdio", "--read-only", "--toolsets", "repos,pull_requests,actions,code_security"]


def main():
    import toolrun
    try:
        argv, _pin = toolrun.argv_for("github-mcp-server", ARGS)
    except toolrun.ToolUnavailable as e:
        sys.stderr.write("MOADIX github MCP: %s\n" % e)
        return 1
    tok = toolrun.github_token()
    if not tok:
        sys.stderr.write("MOADIX github MCP: no read-only token in the login Keychain (service %s). It is needed "
                         "only once a product reaches phase 11; see docs/INSTALL.md.\n" % toolrun.GITHUB_KEYCHAIN_SERVICE)
        return 1
    env = {"PATH": "/usr/bin:/bin", "HOME": os.environ.get("HOME", "/var/empty"),
           "SSL_CERT_FILE": "/etc/ssl/cert.pem", "GITHUB_PERSONAL_ACCESS_TOKEN": tok}
    os.execve(argv[0], argv, env)
    return 1


if __name__ == "__main__":
    sys.exit(main())
