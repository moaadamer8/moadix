"""Phase path map (invariant 6) and protected paths (invariants 1 and 4).

Ported from v1 harness/config/phase-paths.yaml and hlib.glob_to_re, re-rooted
at the product repo (v1's governed_root is now the repo root). Evaluation order,
first match wins:
  1. protected_exceptions  -> fall through to 3/4 (skip tier 2)
  2. protected_always      -> DENY (gate state, Claude Code config, BMAD, secrets)
  3. always_allow          -> ALLOW
  4. phase-gated           -> ALLOW only if the path belongs to a phase <= current
  5. anything else in repo -> DENY (deny by default, as v1's governed root)
Outside the repo: protected_external -> DENY, else ALLOW (sandbox still applies).
"""
import os
import re

# Each class of path has its own reason text (v1 defect: wrong-class reasons).
PROTECTED_ALWAYS = [
    (".sdlc/**", "gate-state", "is MOADIX gate state; only the gate's hooks write it"),
    (".sdlc", "gate-state", "is MOADIX gate state; only the gate's hooks write it"),
    (".claude/**", "cc-config", "is Claude Code configuration (settings, hooks, agents, commands)"),
    (".claude", "cc-config", "is Claude Code configuration (settings, hooks, agents, commands)"),
    (".mcp.json", "cc-config", "declares MCP servers for the session"),
    (".lsp.json", "cc-config", "declares LSP servers for the session"),
    (".claude-plugin/**", "cc-config", "is a plugin manifest"),
    ("_bmad/**", "bmad", "is BMAD installer-owned (wrap, don't modify)"),
    ("**/.env", "secret", "is a real environment file; only .env.example is writable"),
    ("**/.env.*", "secret", "is a real environment file; only .env.example is writable"),
    ("**/*.pem", "secret", "is key material"),
    ("**/*.key", "secret", "is key material"),
    ("**/*.p12", "secret", "is key material"),
    ("**/*.pfx", "secret", "is key material"),
    ("**/*.jks", "secret", "is key material"),
    ("**/*.keystore", "secret", "is key material"),
    ("**/id_rsa*", "secret", "is key material"),
    ("**/service-account*.json", "secret", "is a cloud credential"),
]
PROTECTED_EXCEPTIONS = ["_bmad/custom/**", "**/.env.example", "**/.env.sample", "**/.env.template"]
ALWAYS_ALLOW = ["CLAUDE.md", ".gitignore", "README.md", "docs/**"]

HOME = os.path.expanduser("~")
PROTECTED_EXTERNAL = [
    ("~/.claude/**", "cc-config", "is user-level Claude Code state (settings, plugins, transcripts)"),
    ("~/.claude", "cc-config", "is user-level Claude Code state"),
    ("~/.claude.json", "cc-config", "is Claude Code's global config"),
    ("/Library/Application Support/ClaudeCode/**", "managed", "is the managed policy and MOADIX's root-owned home"),
    ("/etc/claude-code/**", "managed", "is the Linux managed policy directory"),
    ("~/Library/Keychains/**", "keychain", "holds Keychain databases"),
    ("~/.zshrc", "shell-rc", "sets launch-time environment for Claude Code"),
    ("~/.zshenv", "shell-rc", "sets launch-time environment for Claude Code"),
    ("~/.zprofile", "shell-rc", "sets launch-time environment for Claude Code"),
    ("~/.bashrc", "shell-rc", "sets launch-time environment for Claude Code"),
    ("~/.bash_profile", "shell-rc", "sets launch-time environment for Claude Code"),
    ("~/.profile", "shell-rc", "sets launch-time environment for Claude Code"),
]

# v1 phases (id, label, name, allow globs relative to the repo root).
PHASES = [
    (0, "0", "BRD", ["sdlc/00-*.md"]),
    (1, "1", "Research", ["sdlc/01-*.md", "sdlc/decisions/**"]),
    (2, "2", "PRD", ["sdlc/02-*.md"]),
    (3, "3", "HLD", ["sdlc/03-*.md", "sdlc/adr/**"]),
    (4, "4", "Threat Model", ["sdlc/04-*.md"]),
    (5, "5", "LLD", ["sdlc/05-*.md", "sdlc/05-lld/**", "api/**", "openapi/**"]),
    (6, "6", "UX", ["sdlc/06-*.md", "design/**"]),
    (7, "6b", "Provisioning", ["sdlc/06b-*.md", ".env.example"]),
    (8, "7", "Tasks and Implementation", [
        "sdlc/07-*.md", "src/**", "public/**", "package.json", "index.html", "mobile/**",
        "docker-compose.yml", "compose/**", "Dockerfile", ".dockerignore", "scripts/**",
        "package-lock.json", "tsconfig.json", "next.config.*", "next-env.d.ts", "drizzle.config.*",
        "vitest.config.*", "playwright.config.*", "eslint.config.*", ".prettierrc*", "prettier.config.*",
        ".prettierignore", ".github/workflows/**", "tests/**"]),
    (9, "8", "Testing", ["sdlc/08-*.md", "tests/**", "ui-tests/**", "test-results/**", "pytest.ini"]),
    (10, "9", "Security Verification", ["sdlc/09-*.md", "security/**"]),
    (11, "10a", "Live Verification", ["sdlc/10a-*.md", "evidence/live/**", "evidence/live-mobile/**", "evidence/authz/**"]),
    (12, "10b", "Regression Suites", ["sdlc/10b-*.md", "e2e/**", "e2e-mobile/**", ".maestro/**", ".github/workflows/**"]),
    (13, "10c", "Concurrency and Load", ["sdlc/10c-*.md", "evidence/concurrency/**", "load/**"]),
    (14, "11", "Release", ["sdlc/11-*.md", "release/**", "sdlc/12-*.md"]),
    (15, "11b", "Store Release", ["sdlc/11b-*.md", "release/store/**", "release/assets/**"]),
]
LABELS = [p[1] for p in PHASES]

_CACHE = {}


def glob_to_re(pattern):
    """v1 hlib.glob_to_re: '*' does not cross '/', '**' does."""
    i, out = 0, ["^"]
    while i < len(pattern):
        c = pattern[i]
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif c == "*":
            out.append("[^/]*")
            i += 1
        elif c == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(c))
            i += 1
    out.append("$")
    return re.compile("".join(out))


def glob_match(pattern, path):
    rx = _CACHE.get(pattern)
    if rx is None:
        rx = _CACHE[pattern] = glob_to_re(pattern)
    return bool(rx.match(path))


def any_glob(patterns, path):
    return any(glob_match(p, path) for p in patterns)


def _expand(p):
    return HOME + p[1:] if p.startswith("~") else p


def _literal_prefix(pattern):
    head = re.split(r"[*?\[]", pattern, maxsplit=1)[0]
    return head.rstrip("/")


def resolve(path, cwd):
    """Absolute, normalised, symlinks resolved for the parts that exist."""
    p = os.path.expanduser(path)
    if not os.path.isabs(p):
        p = os.path.join(cwd or os.getcwd(), p)
    return os.path.realpath(os.path.normpath(p))


class Decision(object):
    def __init__(self, allow, reason, klass):
        self.allow, self.reason, self.klass = allow, reason, klass

    def __repr__(self):
        return "Decision(%s, %s)" % ("ALLOW" if self.allow else "DENY", self.klass)


def classify(abspath, root, current_phase_id):
    """Decision for writing `abspath`. root is the product repo (or None)."""
    for pat, klass, why in PROTECTED_EXTERNAL:
        full = _expand(pat)
        if glob_match(full, abspath) or abspath == full.rstrip("/*"):
            return Decision(False, "%s %s" % (abspath, why), klass)
    if not root:
        return Decision(True, "outside any MOADIX product", "outside")
    root = os.path.realpath(root)
    if abspath == root or not abspath.startswith(root + os.sep):
        if abspath == root:
            return Decision(False, "the repo root contains .sdlc/ (gate state)", "gate-state")
        if os.path.basename(abspath) == ".sdlc" or "/.sdlc/" in abspath + "/":
            return Decision(False, "%s is MOADIX gate state of another product" % abspath, "gate-state")
        return Decision(True, "outside the product repo", "outside")
    rel = os.path.relpath(abspath, root)
    excepted = any_glob(PROTECTED_EXCEPTIONS, rel)
    if not excepted:
        for pat, klass, why in PROTECTED_ALWAYS:
            if glob_match(pat, rel):
                return Decision(False, "%s %s" % (rel, why), klass)
        # A directory that CONTAINS protected paths is protected (v1 attack M17: rm -rf dir).
        for pat, klass, why in PROTECTED_ALWAYS:
            base = _literal_prefix(pat)
            if base and not base.startswith("**") and base.startswith(rel + "/"):
                return Decision(False, "%s contains %s, which %s" % (rel, base, why), klass)
    if any_glob(ALWAYS_ALLOW, rel):
        return Decision(True, "%s is always writable" % rel, "always-allow")
    owners = [pid for pid, _l, _n, pats in PHASES if any_glob(pats, rel)]
    if owners:
        if min(owners) <= current_phase_id:
            return Decision(True, "%s belongs to phase %s" % (rel, LABELS[min(owners)]), "phase")
        return Decision(False, "%s belongs to phase %s; the current phase is %s" % (
            rel, LABELS[min(owners)], LABELS[current_phase_id]), "phase-later")
    return Decision(False, "%s is in no phase's path map (deny by default)" % rel, "unmapped")
