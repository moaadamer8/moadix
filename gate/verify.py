"""Fresh-context verification (increment 4; DESIGN.md §5, Amendment 1).

A verifier never sees the builder's framing. The gate writes its brief, the
verifier writes evidence, and the gate decides.

Schedule   gate/config/verifiers.yaml maps each role to a phase. A role is
           scheduled when its phase is the current phase (and, for `when:
           changed`, the diff range touches its scope). Launching any other
           MOADIX verifier is refused.
Brief      built by the gate from artifacts only: the diff range (base = the
           commit the previous phase was approved on, head = HEAD), the changed
           files in the role's scope (the required evidence paths), the story
           and acceptance-criteria IDs from sdlc/02-*.md, and the knowledge.md
           sections that mention them. Never from the builder's prompt. The
           gate computes its sha256.
Launch     PreToolUse on the Agent tool (main thread): the builder's prompt is
           REPLACED by the brief (updatedInput). The prompt also carries a
           one-time receipt the builder never sees; the gate keeps only its
           sha256. Evidence counts only if it quotes the receipt, so if the
           replacement ever did not happen, no evidence can pass (fail closed).
Evidence   .sdlc/cache/verify/<phase>/<role>/evidence/findings.json, written
           with the Write tool by that verifier only (the hook allows nothing
           else to write there; the sandbox keeps every Bash process out of
           .sdlc/). gitignored, so it neither dirties the tree nor moves HEAD.
           Findings only, never a verdict.
Check      the gate checks the stamp (role, source commit = HEAD, brief hash,
           receipt), that every citation resolves (path:line exists at HEAD),
           that every required path was reviewed and, for the AC-coverage
           critic, that every acceptance criterion maps to a test. Findings at a
           failing severity fail. gate/v1/check_verifiers.py runs this as the
           phase's validator, so APPROVE refuses on missing, stale or failing
           evidence.

Gate-owned files per role (the verifier cannot write them):
  .sdlc/cache/verify/<phase>/<role>/brief.md       the brief (hashed)
  .sdlc/cache/verify/<phase>/<role>/schedule.json  base, head, brief/receipt sha256
"""
import hashlib
import json
import os
import re
import secrets
import subprocess
import time

from . import pathmap, state

CONFIG = os.path.join(os.path.dirname(os.path.realpath(__file__)), "config", "verifiers.yaml")
PLUGIN = "moadix"
AGENT_TOOLS = ("Agent", "Task")
EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
SEVERITIES = ("critical", "high", "medium", "low", "info")
EVIDENCE_NAME = "findings.json"
VERDICT_WORDS = re.compile(r"^(verdict|approved?|approval|pass(ed)?|ready|decision|status|result|outcome|lgtm|"
                           r"accept(ed)?|ship|merge)$", re.I)
TOP_KEYS = {"role", "source_commit", "brief_sha256", "receipt", "reviewed", "findings", "coverage", "buttons", "notes"}
AC_RE = re.compile(r"^\s*[-*]\s*\*\*(AC-\d+)\s*(?:\(([^)]*)\))?\s*:?\*\*", re.I)  # v1 check_traceability
CITATION = re.compile(r"^(?P<path>[^:\s][^:]*):(?P<a>\d+)(?:-(?P<b>\d+))?$")
_CACHE: dict = {}

# A verifier's tools. Everything else is refused for a verifier agent.
VERIFIER_TOOLS = {"Read", "Grep", "Glob", "Bash", "Write", "Edit", "MultiEdit", "Skill", "TodoWrite"}
# How a subagent returns its result to the agent that launched it (Claude Code
# 2.1.322). Denying it does not stop the subagent's work, it only loses the
# reply: the parent is told "no report was delivered". It carries text back to
# the parent and writes nothing, so a verifier and the probe may always call it.
# Exact name only.
HANDBACK_TOOL = "SubagentHandback"
READONLY_VERBS = {"git", "cat", "head", "tail", "sed", "grep", "egrep", "fgrep", "rg", "ls", "wc", "find", "sort",
                  "uniq", "nl", "shasum", "sha256sum", "file", "tree", "jq", "diff", "echo", "printf", "test", "true",
                  "pwd", "stat", "cut", "tr", "column", "basename", "dirname", "realpath", "["}
READONLY_GIT = {"log", "diff", "show", "rev-parse", "ls-files", "ls-tree", "blame", "status", "grep", "cat-file",
                "merge-base", "rev-list", "shortlog", "describe", "name-rev", "for-each-ref"}


# Live measurement (increment 4): does Claude Code apply a managed hook's
# updatedInput to an Agent call, and what agent_type does a plugin agent report?
# moadix:replacement-probe's prompt is always replaced by a line with a one-time
# nonce; the gate logs the nonce and the agent_type of the probe's own tool call.
# The probe produces no evidence and is never scheduled as a verifier.
PROBE = "replacement-probe"


class VerifyError(Exception):
    pass


def probe_log_path():
    return os.path.join(os.path.expanduser("~"), "Library", "Logs", "moadix", "probe.log")


def probe_log(line):
    p = probe_log_path()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "a") as f:
        f.write("%s %s\n" % (time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), line))


def is_probe(agent_type):
    return bool(agent_type) and str(agent_type).rpartition(":")[2] == PROBE


def probe_launch(tool_input):
    nonce = secrets.token_hex(8)
    probe_log("launch nonce=%s given_prompt_sha256=%s" % (
        nonce, sha256(str((tool_input or {}).get("prompt") or ""))))
    new = dict(tool_input)
    new["prompt"] = ("MOADIX replacement probe. First call the Read tool once on /dev/null. Then reply with exactly "
                     "this line and nothing else:\nPROBE-REPLACED %s\n" % nonce)
    new["subagent_type"] = "%s:%s" % (PLUGIN, PROBE)
    return "replace", new


def probe_restrict(tool, tool_input, agent_type, agent_id):
    ti = tool_input or {}
    if tool == "Read" and str(ti.get("file_path")) == "/dev/null":
        r = "allow", "replacement probe: its one Read of /dev/null"
    elif tool == HANDBACK_TOOL:
        r = "allow", "replacement probe: handing its reply back"
    else:
        r = "deny", "the replacement probe has no other tools"
    extra = " file_path=%s" % ti.get("file_path") if tool == "Read" else ""
    probe_log("tool=%s agent_type=%s agent_id=%s%s decision=%s" % (
        tool, agent_type, "present" if agent_id else "absent", extra, r[0]))
    return r


# ---------------------------------------------------------------- config
def load():
    if "doc" not in _CACHE:
        from .v1 import hlib
        doc = hlib.load_yaml(CONFIG) or {}
        roles = doc.get("roles")
        if not isinstance(roles, list) or not roles:
            raise ValueError("verifiers.yaml has no roles")
        _CACHE["doc"] = doc
    return _CACHE["doc"]


def roles():
    return {str(r["agent"]): r for r in load()["roles"]}


def role_of_agent_type(agent_type):
    """The verifier role an agent type names (namespaced or bare), else None.
    Restrictions apply to both spellings: over-restricting is the safe side."""
    if not agent_type:
        return None
    plugin, _, bare = str(agent_type).rpartition(":")
    if bare in roles() and plugin in ("", PLUGIN):
        return bare
    return None


# ---------------------------------------------------------------- git
def _git(root, *args, timeout=15):
    p = subprocess.run([state.GIT, "-C", root] + list(args), capture_output=True, text=True, timeout=timeout)
    if p.returncode != 0:
        raise VerifyError("git %s failed: %s" % (" ".join(args[:2]), (p.stderr or "").strip()[:200]))
    return p.stdout


def head(root):
    return _git(root, "rev-parse", "--verify", "HEAD").strip()


def dirty(root):
    out = _git(root, "status", "--porcelain=v1", "--untracked-files=all", "--", ".", ":(exclude).sdlc",
               ":(exclude).sdlc-proposals")
    return [ln[3:] for ln in out.splitlines() if ln.strip()]


def base_commit(st, label):
    """The commit the phase before `label` was approved (or proceeded past) on;
    the empty tree when there is none, so the range covers everything."""
    labels = pathmap.LABELS
    i = labels.index(label)
    for ph in reversed(st["phases"][:i]):
        if ph.get("commit"):
            return ph["commit"]
    return EMPTY_TREE


def changed_files(root, base, hd):
    out = _git(root, "diff", "--name-only", "--no-renames", "--diff-filter=ACMRT", base, hd)
    return sorted(p for p in out.splitlines() if p.strip())


def in_scope(role, paths):
    return [p for p in paths if pathmap.any_glob(role.get("scope") or [], p)]


# ---------------------------------------------------------------- schedule
def _dir(root, label, name):
    return os.path.join(root, state.SDLC, "cache", "verify", label, name)


def evidence_dir(root, label, name):
    return os.path.join(_dir(root, label, name), "evidence")


def evidence_file(root, label, name):
    return os.path.join(evidence_dir(root, label, name), EVIDENCE_NAME)


def scheduled(root, st, label=None):
    """{role name: (role, base, head, required paths)} the gate schedules for the
    current phase at HEAD. Raises VerifyError when git cannot answer."""
    label = label or st["current_phase"]
    if label == "done":
        return {}
    hd = head(root)
    base = base_commit(st, label)
    changed = changed_files(root, base, hd)
    out = {}
    for name, r in roles().items():
        if str(r.get("phase")) != str(label):
            continue
        req = in_scope(r, changed)
        if str(r.get("when") or "always") == "changed" and not req:
            continue
        out[name] = (r, base, hd, req)
    return out


def phase_has_verifiers(label):
    return any(str(r.get("phase")) == str(label) for r in roles().values())


# ---------------------------------------------------------------- brief
def stories(root):
    """[(story id, title, [(ac id, line)], path, line)] from sdlc/02-*.md (v1's PRD shape)."""
    sd = os.path.join(root, "sdlc")
    out = []
    if not os.path.isdir(sd):
        return out
    for fn in sorted(f for f in os.listdir(sd) if re.match(r"^02-.*\.md$", f)):
        rel = "sdlc/" + fn
        cur = None
        with open(os.path.join(sd, fn), encoding="utf-8", errors="replace") as f:
            for n, line in enumerate(f, 1):
                m = re.match(r"^#{2,4}\s+((?:US|NFR)-\d+)\s*[—:-]?\s*(.*)$", line.strip())
                if m:
                    cur = [m.group(1), m.group(2).strip(), [], rel, n]
                    out.append(cur)
                    continue
                a = AC_RE.match(line)
                if a and cur:
                    cur[2].append((a.group(1).upper(), n))
    return [tuple(s) for s in out]


def ac_ids(story_list):
    return ["%s/%s" % (sid, ac) for sid, _t, acs, _p, _n in story_list for ac, _l in acs]


# ---------------------------------------------------------------- live verifier (increment 5)
# The phase-10a live verifier drives the running app through MOADIX's pinned Playwright
# MCP (plugin.json: mcp__plugin_moadix_playwright__*). Its network-reading tools are
# withheld: they put request/response headers (cookies, bearer tokens) into the
# transcript, which is v1's 10a defect. evaluate/run_code are withheld for the same
# reason (they can read document.cookie or fetch()). Matched by name pattern, so a tool
# a later Playwright MCP adds under such a name is withheld too.
LIVE_SERVER = "plugin_%s_playwright" % PLUGIN
WITHHELD = re.compile(r"network|evaluate|run_code|cookie|storage_state|route|har\b", re.I)
BUTTON_RE = re.compile(r"<button\b(?P<attrs>[^>]*)>(?P<body>.*?)</button>|<input\b(?P<iattrs>[^>]*\btype=[\"']?"
                       r"(?:submit|button|reset)\b[^>]*)>|<(?P<tag>[a-z][\w-]*)\b(?P<rattrs>[^>]*\brole=[\"']button"
                       r"[\"'][^>]*)>", re.I | re.S)
ATTR = re.compile(r"\b(aria-label|data-testid|id|name|value|title)\s*=\s*[\"']([^\"']{1,80})[\"']", re.I)


def _button_label(attrs, body):
    found = {k.lower(): v for k, v in ATTR.findall(attrs or "")}
    for k in ("aria-label", "data-testid", "id", "name", "value", "title"):
        if found.get(k):
            return "%s=%s" % (k, found[k])
    text = " ".join(re.sub(r"<[^>]+>|\{[^}]*\}", " ", body or "").split())
    return ("text=%s" % text[:60]) if text else "(unlabelled)"


def buttons(root, hd, role):
    """[(BTN-n, label, path, line)] for every button in the role's `buttons` globs at
    commit hd, in path and line order. Deterministic: the brief hashes it."""
    globs = role.get("buttons") or []
    if not globs:
        return []
    files = [p for p in _git(root, "ls-tree", "-r", "--name-only", hd).splitlines()
             if pathmap.any_glob(globs, p)]
    out = []
    for p in sorted(files):
        try:
            text = _git(root, "show", "%s:%s" % (hd, p))
        except VerifyError:
            continue
        for m in BUTTON_RE.finditer(text):
            line = text.count("\n", 0, m.start()) + 1
            label = _button_label(m.group("attrs") or m.group("iattrs") or m.group("rattrs"), m.group("body"))
            out.append((p, line, label))
    return [("BTN-%d" % (i + 1), lab, p, ln) for i, (p, ln, lab) in enumerate(out)]


def live_base_url(root):
    from .v1 import hlib
    try:
        doc = hlib.load_yaml(os.path.join(root, state.SDLC, "config", "product-tools.yaml")) or {}
    except Exception:
        doc = {}
    return str((doc.get("live") or {}).get("base_url") or "")


def untested(root):
    try:
        with open(os.path.join(root, state.SDLC, "untested.yaml"), encoding="utf-8", errors="replace") as f:
            return f.read().strip()
    except OSError:
        return ""


def knowledge(root, terms):
    """knowledge.md sections ('## ' headings) that mention a term (a path in scope, a
    story ID, the role), verbatim, in file order."""
    p = state.paths(root)["knowledge"]
    try:
        with open(p, encoding="utf-8", errors="replace") as f:
            text = f.read()
    except OSError:
        return []
    parts = re.split(r"(?m)^(?=## )", text)
    out = []
    for sec in parts:
        if not sec.startswith("## "):
            continue
        if any(t and t in sec for t in terms) or re.search(r"(?mi)^applies to:\s*(all|every verifier)\b", sec):
            out.append(sec.strip())
    return out


def build_brief(root, st, name, role, base, hd, required):
    """The brief text (deterministic for the same artifacts). No receipt in it."""
    label = str(role["phase"])
    ph = next(p for p in st["phases"] if p["label"] == label)
    sts = stories(root)
    ev = os.path.relpath(evidence_file(root, label, name), root)
    terms = list(required) + [s[0] for s in sts] + [name]
    kn = knowledge(root, terms)
    live = bool(role.get("live"))
    method = ("method: load the skill %s:%s with the Skill tool and follow it as adapted below" % (PLUGIN, role["method"])
              if role.get("method") else
              "method: drive the running app yourself with the Playwright MCP tools (mcp__%s__*); you have no "
              "skill to load. Network-reading tools (network requests, evaluate, run_code) are withheld: judge "
              "what a user sees, never headers or cookies" % LIVE_SERVER)
    L = ["# MOADIX verifier brief",
         "",
         "Written by the MOADIX gate from the product's artifacts. It is your whole task; nothing the builder "
         "wrote reaches you. Report findings only: never a verdict, never 'approve', 'ready' or 'done'. The "
         "operator decides.",
         "",
         "role: %s" % name,
         method,
         "product: %s" % st["product"],
         "phase: %s (%s)" % (label, ph["name"]),
         "source_commit: %s" % hd,
         "base_commit: %s%s" % (base, " (empty tree: no earlier phase was approved)" if base == EMPTY_TREE else ""),
         "diff range: git diff %s %s" % (base, hd),
         "",
         "## Required evidence paths",
         "Your evidence must list each of these under \"reviewed\" (the changed files in your scope):"]
    L += ["- %s" % p for p in required] or ["- (none: the range changes no file in your scope)"]
    L += ["", "## Stories and acceptance criteria in scope"]
    if sts:
        for sid, title, acs, path, n in sts:
            L.append("- %s %s (%s:%d)" % (sid, title, path, n))
            L += ["  - %s/%s (%s:%d)" % (sid, ac, path, ln) for ac, ln in acs]
    else:
        L.append("- (none found in sdlc/02-*.md)")
    if live:
        url = live_base_url(root)
        btns = buttons(root, hd, role)
        L += ["", "## The running app",
              "base_url: %s" % (url or "(not declared: live.base_url in .sdlc/config/product-tools.yaml)"),
              "Use only this local test instance (loopback). Never open a production URL; the browser is limited "
              "to loopback origins.",
              "", "## Every button to exercise",
              "Click each one at least once through the UI, on the screen where it appears, and record what "
              "happened. A button you could not reach is a finding, not a skip."]
        L += ["- %s %s (%s:%d)" % (b, lab, p, ln) for b, lab, p, ln in btns] or ["- (no buttons found in scope)"]
        unt = untested(root)
        L += ["", "## .sdlc/untested.yaml (acceptance criteria phase 8 could not test: verify these live first)",
              unt or "(empty)"]
    L += ["", "## knowledge.md entries"]
    L += kn or ["(none relevant)"]
    L += ["", "## Evidence",
          "Write exactly one file with the Write tool: %s" % ev,
          "It is JSON with these keys and no others:",
          "- role: \"%s\"" % name,
          "- source_commit: \"%s\"" % hd,
          "- brief_sha256: the brief_sha256 given at the end of this prompt",
          "- receipt: the receipt given at the end of this prompt",
          "- reviewed: [repo-relative paths you reviewed]",
          "- findings: [{\"id\": \"F1\", \"severity\": one of %s, \"summary\": \"...\", "
          "\"citations\": [\"path:line\" or \"path:start-end\", ...]}]" % "/".join(SEVERITIES)]
    if role.get("coverage") and live:
        L += ["- coverage: [{\"ac\": \"US-001/AC-1\", \"observed\": \"what you did and saw\", \"artifacts\": "
              "[\"playwright/<file>\", ...]}] with one entry per acceptance criterion listed above; artifacts are "
              "paths relative to %s (the trace and video files the browser saved there); an empty artifacts list "
              "means you could not verify it" % os.path.relpath(evidence_dir(root, label, name), root),
              "- buttons: [{\"id\": \"BTN-1\", \"exercised\": true, \"observed\": \"...\", \"artifacts\": [...]}] "
              "with one entry per button listed above",
              "Recording: call browser_start_tracing and browser_start_video before the first navigation, and "
              "browser_stop_video and browser_stop_tracing at the end. The browser saves them into the evidence "
              "directory; cite them as artifacts."]
    elif role.get("coverage"):
        L.append("- coverage: [{\"ac\": \"US-001/AC-1\", \"tests\": [\"path:line\", ...]}] with one entry per "
                 "acceptance criterion listed above; an empty tests list means you found no test for it")
    L += ["- notes: optional free text",
          "Every citation must point at a line that exists in source_commit. Do not include a verdict, a pass/fail "
          "field or a recommendation to proceed. Do not write anywhere else; you cannot start other agents.",
          "In your final reply, do not repeat the receipt."]
    return "\n".join(L) + "\n"


def sha256(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=1, sort_keys=True)
    os.replace(tmp, path)


def schedule_and_brief(root, st, name):
    """Gate side of a launch: build the brief, mint a receipt, record the schedule.
    Returns the prompt that replaces the builder's. A new launch supersedes the last
    (its receipt no longer matches)."""
    sch = scheduled(root, st)
    if name not in sch:
        raise VerifyError("not scheduled")
    role, base, hd, req = sch[name]
    label = str(role["phase"])
    brief = build_brief(root, st, name, role, base, hd, req)
    bh = sha256(brief)
    receipt = secrets.token_hex(16)
    d = _dir(root, label, name)
    os.makedirs(d, exist_ok=True)
    ef = evidence_file(root, label, name)
    if os.path.exists(ef):  # superseded: the old evidence answered another brief
        os.replace(ef, ef + ".superseded")
    with open(os.path.join(d, "brief.md"), "w") as f:
        f.write(brief)
    _write_json(os.path.join(d, "schedule.json"), {
        "role": name, "phase": label, "base": base, "head": hd, "required": req, "brief_sha256": bh,
        "receipt_sha256": sha256(receipt), "scheduled_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
    os.makedirs(evidence_dir(root, label, name), exist_ok=True)
    return brief + "\n---\nbrief_sha256: %s\nreceipt: %s\n" % (bh, receipt), bh


# ---------------------------------------------------------------- hook side
def on_agent_launch(tool_input, cwd):
    """Main-thread Agent call. Returns None (not a verifier: no opinion),
    ('deny', reason) or ('replace', new tool_input)."""
    sub = str((tool_input or {}).get("subagent_type") or "")
    plugin, _, bare = sub.rpartition(":")
    if bare == PROBE and plugin == PLUGIN:
        return probe_launch(tool_input)
    root = state.find_root(cwd)
    if bare not in roles():
        return None
    if plugin != PLUGIN:
        if not root:
            return None
        return "deny", ("%r is not a MOADIX verifier; in a MOADIX product a verifier is launched as %s:%s" % (
            sub, PLUGIN, bare))
    if not root:
        return "deny", "%s runs only inside a MOADIX product (no .sdlc/ here)" % sub
    st, problems = state.current_state(root)
    if problems:
        return "deny", "gate state failed its integrity check, so no verifier is scheduled (run STATUS)"
    label = st["current_phase"]
    try:
        sch = scheduled(root, st)
    except VerifyError as e:
        return "deny", "the gate could not compute the schedule (%s)" % e
    if bare not in sch:
        now = ", ".join("%s:%s" % (PLUGIN, n) for n in sorted(sch)) or "none"
        role = roles()[bare]
        why = "it belongs to phase %s" % role["phase"] if str(role["phase"]) != str(label) else \
            "the diff range changes no file in its scope"
        return "deny", ("verifier %s is not scheduled for the current phase %s: %s. Scheduled now: %s "
                        "(gate/config/verifiers.yaml)" % (sub, label, why, now))
    dt = dirty(root)
    if dt:
        return "deny", ("commit first: a verifier reviews a commit, and the working tree has changes (%s)" %
                        ", ".join(dt[:5]))
    prompt, bh = schedule_and_brief(root, st, bare)
    new = dict(tool_input)
    new["prompt"] = prompt
    new["description"] = "MOADIX verifier %s (brief %s)" % (bare, bh[:12])
    new["subagent_type"] = "%s:%s" % (PLUGIN, bare)
    return "replace", new


def _readonly_bash(cmd, cwd):
    from . import bashcls
    a = bashcls.analyse(cmd, os.path.realpath(cwd) if cwd else None)
    if a["opaque"]:
        return "it runs code the gate cannot see into (%s)" % a["opaque_why"]
    if a["writes"] or a["links"] or a["computed"]:
        return "it writes files"
    words = a["words"]
    for v in a["verbs"]:
        b = v.rsplit("/", 1)[-1]
        if b not in READONLY_VERBS:
            return "%r is not one of a verifier's read-only commands" % b
    for j, w in enumerate(words):
        if w.rsplit("/", 1)[-1] == "git":
            k = j + 1
            while k < len(words) and words[k].startswith("-"):
                k += 2 if words[k] in ("-C", "-c") else 1
            sub = words[k] if k < len(words) else ""
            if sub not in READONLY_GIT:
                return "git %s is not read-only" % sub
        if w.rsplit("/", 1)[-1] == "sed" and any(x.startswith(("-i", "--in-place")) or x == "w" or
                                                  x.startswith("-E") and "i" in x for x in words[j + 1:j + 5]):
            return "sed in-place edits write files"
        if w.rsplit("/", 1)[-1] == "sort" and any(x.startswith("-o") or x.startswith("--output")
                                                   for x in words[j + 1:]):
            return "sort -o writes a file"
        if w.startswith("--output"):
            return "%s writes a file" % w
        if w in ("-delete", "-exec", "-execdir", "-ok", "-fprint", "-fprintf", "-fls"):
            return "find %s acts on files" % w
    return None


def restrict(tool, tool_input, cwd, role):
    """A verifier agent's own tool call. Returns ('deny', reason), ('allow', why) or None."""
    ti = tool_input or {}
    if tool == HANDBACK_TOOL:
        return "allow", "verifier %s handing its result back" % role
    if tool in AGENT_TOOLS:
        return "deny", "a verifier cannot start agents (no nesting)"
    if tool.startswith("mcp__") and roles()[role].get("live"):
        srv = tool[len("mcp__"):].split("__", 1)
        if len(srv) == 2 and srv[0] == LIVE_SERVER:
            if WITHHELD.search(srv[1]):
                return "deny", ("%s is withheld from the live verifier: network-reading tools put headers, cookies "
                                "and tokens into the transcript (v1's 10a defect)" % srv[1])
            return "allow", "live verifier %s driving the browser" % role
        return "deny", "the live verifier may use only MOADIX's pinned Playwright MCP (mcp__%s__*)" % LIVE_SERVER
    if tool.startswith("mcp__") or tool in ("WebFetch", "WebSearch"):
        return "deny", "a verifier has no network or MCP tools"
    if tool not in VERIFIER_TOOLS:
        return "deny", "%s is not in a verifier's tool set (%s)" % (tool, ", ".join(sorted(VERIFIER_TOOLS)))
    if tool == "Skill":
        if not roles()[role].get("method"):
            return "deny", "verifier %s has no method skill" % role
        want = "%s:%s" % (PLUGIN, roles()[role]["method"])
        if str(ti.get("skill") or "").strip() != want:
            return "deny", "verifier %s may load only its method skill %s" % (role, want)
        return None
    if tool in ("Write", "Edit", "MultiEdit"):
        p = ti.get("file_path") or ""
        root = state.find_root(cwd)
        if not root or not p:
            return "deny", "a verifier writes only its evidence file, inside a MOADIX product"
        st, problems = state.current_state(root)
        if problems:
            return "deny", "gate state failed its integrity check"
        label = st["current_phase"]
        ed = os.path.realpath(evidence_dir(root, label, role))
        ab = pathmap.resolve(p, cwd)
        if not os.path.isfile(os.path.join(_dir(root, label, role), "schedule.json")):
            return "deny", "verifier %s is not scheduled for phase %s" % (role, label)
        if not ab.startswith(ed + os.sep):
            return "deny", "verifier %s writes only inside its evidence directory %s" % (
                role, os.path.relpath(ed, root))
        return "allow", "verifier %s writing its evidence" % role
    if tool == "Bash":
        why = _readonly_bash(ti.get("command") or "", cwd)
        if why:
            return "deny", "a verifier's Bash is read-only, and this command is refused: %s" % why
    return None


# ---------------------------------------------------------------- evidence check
def _lines_at(root, hd, path, memo):
    if path not in memo:
        try:
            if path.startswith("/") or ".." in path.split("/"):
                raise VerifyError("not repo-relative")
            memo[path] = _git(root, "show", "%s:%s" % (hd, path)).count("\n") + 1
        except VerifyError:
            memo[path] = None
    return memo[path]


def _citation_problem(root, hd, c, memo):
    m = CITATION.match(str(c).strip())
    if not m:
        return "citation %r is not path:line" % (c,)
    n = _lines_at(root, hd, m.group("path"), memo)
    if n is None:
        return "citation %s: %s does not exist at %s" % (c, m.group("path"), hd[:12])
    a, b = int(m.group("a")), int(m.group("b") or m.group("a"))
    if a < 1 or b < a or b > n:
        return "citation %s: line %s is outside %s (%d lines)" % (c, m.group("b") or a, m.group("path"), n)
    return None


def _verdict_keys(obj, where="evidence"):
    out = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if VERDICT_WORDS.match(str(k)):
                out.append("%s.%s" % (where, k))
            out += _verdict_keys(v, "%s.%s" % (where, k))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            out += _verdict_keys(v, "%s[%d]" % (where, i))
    return out


def check_role(root, st, name, role, base, hd, required):
    """(status, problems, info). status: ok | missing | stale | failing."""
    label = str(role["phase"])
    d = _dir(root, label, name)
    try:
        with open(os.path.join(d, "schedule.json")) as f:
            sch = json.load(f)
        with open(os.path.join(d, "brief.md"), encoding="utf-8") as f:
            brief = f.read()
    except (OSError, ValueError):
        return "missing", ["%s:%s was not launched at this commit (no brief)" % (PLUGIN, name)], {}
    if sch.get("head") != hd:
        return "stale", ["the brief was for commit %s, HEAD is %s; launch %s:%s again" % (
            str(sch.get("head"))[:12], hd[:12], PLUGIN, name)], {}
    if sha256(brief) != sch.get("brief_sha256"):
        return "failing", ["the gate's brief.md no longer matches its recorded hash"], {}
    if sch.get("base") != base or sorted(sch.get("required") or []) != sorted(required):
        return "stale", ["the brief's diff range no longer matches the ledger; launch %s:%s again" % (PLUGIN, name)], {}
    ef = evidence_file(root, label, name)
    try:
        with open(ef, "rb") as f:
            raw = f.read()
    except OSError:
        return "missing", ["no evidence at %s" % os.path.relpath(ef, root)], {}
    info = {"evidence_sha256": hashlib.sha256(raw).hexdigest(), "brief_sha256": sch.get("brief_sha256")}
    try:
        ev = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return "failing", ["the evidence is not JSON"], info
    if not isinstance(ev, dict):
        return "failing", ["the evidence is not a JSON object"], info
    probs = []
    extra = sorted(set(ev) - TOP_KEYS)
    if extra:
        probs.append("unexpected keys %s (findings only, no verdict)" % ", ".join(extra))
    vk = _verdict_keys({k: v for k, v in ev.items() if k in TOP_KEYS})
    if vk:
        probs.append("verdict-like fields %s: a verifier reports findings, never a verdict" % ", ".join(vk[:5]))
    if ev.get("role") != name:
        probs.append("role %r, expected %r" % (ev.get("role"), name))
    if ev.get("source_commit") != hd:
        probs.append("source_commit %s does not match HEAD %s" % (str(ev.get("source_commit"))[:12], hd[:12]))
    if ev.get("brief_sha256") != sch.get("brief_sha256"):
        probs.append("brief_sha256 %s does not match the gate's brief %s" % (
            str(ev.get("brief_sha256"))[:12], str(sch.get("brief_sha256"))[:12]))
    if sha256(str(ev.get("receipt") or "")) != sch.get("receipt_sha256"):
        probs.append("the receipt does not match the one the gate put in the verifier's prompt (the evidence was "
                     "not written by the verifier the gate briefed)")
    if probs and any("receipt" in p or "brief_sha256" in p or "source_commit" in p for p in probs):
        return "failing", probs, info
    reviewed = ev.get("reviewed")
    if not isinstance(reviewed, list) or not all(isinstance(x, str) for x in reviewed):
        probs.append("reviewed is not a list of paths")
        reviewed = []
    miss = [p for p in required if p not in reviewed]
    if miss:
        probs.append("required paths not reviewed: %s" % ", ".join(miss[:8]))
    memo = {}
    findings = ev.get("findings")
    if not isinstance(findings, list):
        probs.append("findings is not a list")
        findings = []
    fail_sev = set(load().get("failing_severities") or [])
    blocking = []
    for i, f in enumerate(findings):
        if not isinstance(f, dict):
            probs.append("finding %d is not an object" % (i + 1))
            continue
        fid = str(f.get("id") or "#%d" % (i + 1))
        if f.get("severity") not in SEVERITIES:
            probs.append("finding %s: severity %r is not one of %s" % (fid, f.get("severity"), "/".join(SEVERITIES)))
        if not str(f.get("summary") or "").strip():
            probs.append("finding %s has no summary" % fid)
        cits = f.get("citations")
        if not isinstance(cits, list) or not cits:
            probs.append("finding %s has no citations" % fid)
            cits = []
        for c in cits:
            why = _citation_problem(root, hd, c, memo)
            if why:
                probs.append("finding %s: %s" % (fid, why))
        if f.get("severity") in fail_sev:
            blocking.append("%s (%s): %s" % (fid, f.get("severity"), str(f.get("summary"))[:120]))
    if role.get("live"):
        _check_live(root, label, name, role, hd, ev, probs, blocking, info)
    elif role.get("coverage"):
        want = ac_ids(stories(root))
        cov = ev.get("coverage")
        got = {}
        if not isinstance(cov, list):
            probs.append("coverage is not a list")
            cov = []
        for e in cov:
            if isinstance(e, dict) and isinstance(e.get("ac"), str):
                got[e["ac"]] = e.get("tests")
        for ac in want:
            tests = got.get(ac)
            if ac not in got:
                probs.append("coverage: %s is not mapped" % ac)
            elif not isinstance(tests, list) or not tests:
                blocking.append("%s has no test (untested acceptance criterion)" % ac)
            else:
                for c in tests:
                    why = _citation_problem(root, hd, c, memo)
                    if why:
                        probs.append("coverage %s: %s" % (ac, why))
        info["acs"] = len(want)
    info["findings"] = len(findings)
    if probs:
        return "failing", probs, info
    if blocking:
        return "failing", ["finding at a failing severity: %s" % b for b in blocking], info
    return "ok", [], info


def _artifact_problem(edir, a):
    a = str(a)
    if a.startswith("/") or ".." in a.split("/"):
        return "artifact %r is not a path inside the evidence directory" % a
    p = os.path.join(edir, a)
    if not os.path.exists(p) or (os.path.isfile(p) and os.path.getsize(p) == 0):
        return "artifact %s does not exist (or is empty) in the evidence directory" % a
    return None


def _check_live(root, label, name, role, hd, ev, probs, blocking, info):
    """The live verifier: every AC and every button exercised, each backed by artifacts
    the browser saved into the evidence directory, with a trace and a video present."""
    edir = evidence_dir(root, label, name)
    files = []
    for a, _d, fs in os.walk(edir):
        files += [os.path.relpath(os.path.join(a, f), edir) for f in fs]
    if not any(f.endswith(".webm") for f in files):
        probs.append("no video (.webm) in the evidence directory: start browser_start_video before navigating")
    if not any(os.path.basename(f).startswith("trace") or "/trace" in f or f.endswith(".trace") for f in files):
        probs.append("no trace in the evidence directory: start browser_start_tracing before navigating")
    for key, want, what in (("coverage", ac_ids(stories(root)), "ac"),
                            ("buttons", [b[0] for b in buttons(root, hd, role)], "id")):
        got = {}
        lst = ev.get(key)
        if not isinstance(lst, list):
            probs.append("%s is not a list" % key)
            lst = []
        for e in lst:
            if isinstance(e, dict) and isinstance(e.get(what), str):
                got[e[what]] = e
        for k in want:
            e = got.get(k)
            if e is None:
                probs.append("%s: %s is not mapped" % (key, k))
                continue
            arts = e.get("artifacts")
            if key == "buttons" and e.get("exercised") is not True:
                blocking.append("%s was not exercised" % k)
            if not isinstance(arts, list) or not arts:
                blocking.append("%s %s has no artifact (not verified live)" % ("button" if key == "buttons" else "", k))
                continue
            for a in arts:
                why = _artifact_problem(edir, a)
                if why:
                    probs.append("%s %s: %s" % (key, k, why))
        info["acs" if key == "coverage" else "buttons"] = len(want)


def check_phase(root, st, label):
    """[(role, status, problems, info)] for every verifier the phase requires."""
    out = []
    for name, (role, base, hd, req) in sorted(scheduled(root, st, label).items()):
        status, probs, info = check_role(root, st, name, role, base, hd, req)
        out.append((name, status, probs, info))
    return out


def evidence_digest(root, label):
    """sha256 over the phase's verify directory (part of the validator cache key):
    new evidence or a new launch makes a cached result stale."""
    d = os.path.join(root, state.SDLC, "cache", "verify", str(label))
    h = hashlib.sha256()
    if not os.path.isdir(d):
        return "none"
    for a, dirs, fs in os.walk(d):
        dirs.sort()
        for f in sorted(fs):
            full = os.path.join(a, f)
            h.update(os.path.relpath(full, d).encode() + b"\0")
            try:
                with open(full, "rb") as fh:
                    h.update(fh.read())
            except OSError:
                h.update(b"(unreadable)")
            h.update(b"\0")
    return h.hexdigest()
