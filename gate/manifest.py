"""Per-phase skill and MCP enforcement (invariant 5; increment 3).

gate/config/phase-manifest.yaml (root-owned when installed) lists, per phase,
the vendored skills, MCP servers and gate-run tools. In a MOADIX product the
PreToolUse hook denies:
  * a Skill / SlashCommand call whose skill is not in the current phase's list
    (vendored skills are invoked as moadix:<name>; a bare name or another
    plugin's skill is refused even if the name matches, because only MOADIX's
    stripped copies are allowed);
  * an MCP tool call (mcp__<server>__<tool>, or a plugin's
    mcp__plugin_<plugin>_<server>__<tool>) whose server is not listed.
The reason names the phase and what it allows. Outside a product MOADIX stays
passive. When gate state fails its integrity check the phase is unknown, so
every Skill and MCP call is refused (fail closed).
"""
import os
import re

PLUGIN = "moadix"
PATH = os.path.join(os.path.dirname(os.path.realpath(__file__)), "config", "phase-manifest.yaml")
SKILL_TOOLS = {"Skill": "skill", "SlashCommand": "command"}
MCP = re.compile(r"^mcp__(?P<server>.+?)__(?P<tool>[^_].*)$")
_CACHE: dict = {}


def load():
    if "doc" not in _CACHE:
        from .v1 import hlib
        doc = hlib.load_yaml(PATH) or {}
        if not isinstance(doc.get("phases"), list):
            raise ValueError("phase-manifest.yaml has no phases list")
        _CACHE["doc"] = doc
    return _CACHE["doc"]


def allowed(current_label):
    """(skills set, mcp set, phase names) for the current phase label ('done' after the last)."""
    doc = load()
    skills = set((doc.get("always") or {}).get("skills") or [])
    mcp = set((doc.get("always") or {}).get("mcp") or [])
    names = []
    for ph in doc["phases"]:
        lab = str(ph.get("label"))
        if lab == str(current_label) or str(current_label) in [str(x) for x in (ph.get("during") or [])]:
            skills |= set(ph.get("skills") or [])
            mcp |= set(ph.get("mcp") or [])
            names.append("%s (%s)" % (lab, ph.get("name")))
    return skills, mcp, names


def skill_name(tool, tool_input):
    """The invoked skill/command as written: 'moadix:bmad-prd', 'bmad-prd', 'other:x'."""
    raw = str((tool_input or {}).get(SKILL_TOOLS[tool]) or "").strip()
    if tool == "SlashCommand":
        raw = raw.lstrip("/").split(" ", 1)[0]
    return raw


def mcp_server(tool):
    m = MCP.match(tool)
    return m.group("server") if m else None


def _server_matches(server, name):
    return server == name or (server.startswith("plugin_") and server.endswith("_" + name))


def _phase_text(label, names):
    if label == "done":
        return "after the last phase (every phase is approved)"
    return "phase %s" % (" / ".join(names) if names else label)


def check(tool, tool_input, label):
    """None if allowed, else the deny reason. label: current phase label, or None when
    the state failed its integrity check."""
    is_skill = tool in SKILL_TOOLS
    server = mcp_server(tool) if tool.startswith("mcp__") else None
    if not is_skill and server is None:
        return None
    if label is None:
        return ("%s is refused: gate state failed its integrity check, so the current phase (and its skill and MCP "
                "manifest) is unknown; run STATUS" % tool)
    skills, mcp, names = allowed(label)
    where = _phase_text(label, names)
    if is_skill:
        name = skill_name(tool, tool_input)
        plugin, _, bare = name.rpartition(":")
        ok = plugin == PLUGIN and bare in skills
        if ok:
            return None
        allow = ", ".join("%s:%s" % (PLUGIN, s) for s in sorted(skills)) or "none"
        if plugin != PLUGIN and bare in skills:
            why = "only MOADIX's vendored copy %s:%s is allowed (it has its self-approval steps removed)" % (
                PLUGIN, bare)
        else:
            why = "it is not in the manifest for %s" % where
        return "skill %r is denied in %s: %s. Allowed now: %s (gate/config/phase-manifest.yaml)" % (
            name, where, why, allow)
    if any(_server_matches(server, n) for n in mcp):
        return None
    return "MCP tool %s (server %r) is denied in %s: that server is not in its manifest. MCP servers allowed now: " \
           "%s (gate/config/phase-manifest.yaml)" % (tool, server, where, ", ".join(sorted(mcp)) or "none")


def budget(label):
    """'skills a, b (N KB when loaded)' for STATUS: the context cost of this phase's skill set."""
    doc = load()
    skills, mcp, _names = allowed(label)
    sizes = {str(s.get("name")): int(s.get("skill_md_bytes") or 0) for s in (doc.get("skills") or [])}
    vend = sorted(s for s in skills if s in sizes)
    kb = sum(sizes[s] for s in vend) / 1024.0
    return "skills %s (%.1f KB of SKILL.md if all are loaded)%s" % (
        ", ".join("%s:%s" % (PLUGIN, s) for s in vend) or "none", kb,
        "; MCP %s" % ", ".join(sorted(mcp)) if mcp else "")
