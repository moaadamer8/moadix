"""Main-branch and production guard, part of the gate's PreToolUse check for Bash.

Operator decision 4 (option A), after 0.4.0. Under allowManagedHooksOnly and
allowManagedPermissionRulesOnly a project's own guard hooks (for example a
.claude/hooks/guard-main.py) and its own deny rules do not run, so the gate
carries one guard for every repository. The managed deny rules are a coarse
first layer of text patterns; this module parses shell words and decides.

Refused:
  * a git push whose target ref is main: explicit refspecs (main, refs/heads/main,
    HEAD:main, x:main, +main, :main, --delete main), HEAD/@ while on main, wildcard
    and matching (":") refspecs, --all/--branches/--mirror, a bare push whose
    target is main (current branch main, its upstream main, push.default=matching,
    remote.<r>.push mapping onto main), through git -C, git -c, git aliases and
    git send-pack; also inside sh -c, eval, heredocs and here-strings fed to a
    shell, echo ... | sh, $(...), xargs, find -exec, git submodule foreach,
    git rebase --exec, git bisect run, and inline interpreter code;
  * git push --no-verify and core.hooksPath changes (a project's pre-push hook stays in force);
  * gh pr merge: the PR's base is only known through a network call, which this
    guard does not make, so the base is unknown, so it is refused. Also gh api
    writes that merge a PR, merge into main, create/move/delete refs/heads/main or
    write contents to main (or to the default branch), GraphQL merge mutations,
    and gh repo sync onto main. gh aliases are expanded;
  * vercel production deploys and promotes: --prod, --production, --target
    production, promote, rollback, alias set; also through npx/bunx/pnpm/yarn/npm.

Refs are compared as whole refs after shell parsing: feature/main-menu and
main-fix pass.

Fails closed: whatever it cannot resolve is refused, including a ref computed at
run time, an unknown current branch, a git call that errors or exceeds the time
budget, and any internal error. The whole check has BUDGET seconds, well under
the hook's 15 s.

Not covered, because no hook can see them: commands inside a script file
(sh deploy.sh, npm run deploy), shell aliases and functions defined outside the
command, and code an interpreter reads from a file. The backstop is branch
protection on the server.
"""
import os
import re
import shlex
import subprocess
import time

from . import bashcls

PROTECTED = "main"
GIT = "/usr/bin/git"        # SIP-protected; never taken from PATH
BUDGET = 8.0                # seconds for one whole check (the hook's limit is 15)
CALL_TIMEOUT = 3.0          # seconds for one git call
MAX_DEPTH = 6
SUFFIX = (" The agent's work ends at a pushed feature branch; the operator merges to main and deploys "
          "to production.")

def _words(text):
    return frozenset(text.split())


SHELLS = {"sh", "bash", "zsh", "dash", "ksh", "fish"}
RUNNER_HEADS = {"npx", "bunx", "pnpx", "pnpm", "yarn", "npm", "bun"}
RUNNER_WORDS = {"dlx", "exec", "x", "--"}
GIT_BUILTINS = _words("""
add am annotate apply archive bisect blame branch bugreport bundle cat-file check-attr check-ignore
check-mailmap check-ref-format checkout checkout-index cherry cherry-pick citool clean clone column commit
commit-graph commit-tree config count-objects credential describe diagnose diff diff-files diff-index diff-tree
difftool fast-export fast-import fetch fetch-pack filter-branch fmt-merge-msg for-each-ref for-each-repo
format-patch fsck gc get-tar-commit-id grep gui hash-object help hook index-pack init instaweb
interpret-trailers log ls-files ls-remote ls-tree mailinfo mailsplit maintenance merge merge-base merge-file
merge-index merge-tree mergetool mktag mktree multi-pack-index mv name-rev notes pack-objects pack-redundant
pack-refs patch-id prune prune-packed pull push range-diff read-tree rebase reflog remote repack replace replay
request-pull rerere reset restore rev-list rev-parse revert rm scalar send-email send-pack shortlog show
show-branch show-index show-ref sparse-checkout stash status stripspace submodule switch symbolic-ref tag
unpack-file unpack-objects update-index update-ref update-server-info var verify-commit verify-pack
verify-tag version whatchanged worktree write-tree
""")
PUSH_VALUE_OPTS = {"--repo", "-o", "--push-option", "--receive-pack", "--exec"}
GH_API_VALUE_OPTS = {"-X", "--method", "-f", "-F", "--field", "--raw-field", "-H", "--header", "--input", "-q",
                     "--jq", "-t", "--template", "--hostname", "--cache", "-p", "--preview"}
GH_REPO_OPTS = {"-R", "--repo"}
# gh allowlist (operator ruling on 0.5.1). Everything else is refused, including auth token/login/refresh/
# setup-git, config, secret, variable, ssh-key, gpg-key, repo delete/edit/rename/archive/create, release,
# workflow, ruleset, alias, extension, pr merge/checkout/edit/close, and gh api with any method but GET.
GH_ALLOWED = {("pr", "create"), ("pr", "view"), ("pr", "list"), ("pr", "diff"), ("pr", "checks"), ("pr", "status"),
              ("pr", "comment"), ("run", "list"), ("run", "view"), ("run", "watch"), ("issue", "list"),
              ("issue", "view"), ("issue", "create"), ("issue", "comment"), ("repo", "view"), ("auth", "status")}
GH_VALUE_FLAGS = {"-b", "--body", "-F", "--body-file", "-t", "--title", "-B", "--base", "-H", "--head", "-l", "--label",
                  "-a", "--assignee", "-r", "--reviewer", "-m", "--milestone", "-p", "--project", "-s", "--state",
                  "-L", "--limit", "-A", "--author", "-S", "--search", "-q", "--jq", "--json", "-T", "--template",
                  "-w", "--workflow", "-u", "--user", "-c", "--commit", "-e", "--event", "-j", "--job",
                  "--hostname", "-i", "--interval", "--attempt", "--created", "--status"}
# firebase allowlist (proposed in docs/mainguard.md). Remote commands need an explicit --project that
# is not in the operator's protected list; deploys refuse --force and firebase.json pre/postdeploy hooks.
FIREBASE_LOCAL = {"emulators:start", "serve"}
FIREBASE_SAFE_EMULATORS = {"auth", "firestore", "database", "hosting", "storage", "pubsub", "eventarc", "ui"}
FIREBASE_NO_PROJECT = {"projects:list", "login:list"}
FIREBASE_REMOTE = {"deploy", "hosting:channel:deploy", "hosting:channel:list", "hosting:sites:list", "apps:list",
                   "functions:list", "functions:log", "firestore:indexes"}
FIREBASE_VALUE_FLAGS = {"--only", "--except", "--message", "-m", "--expires", "--import", "--export-on-exit", "--config",
                        "-c", "--lines", "-n", "--port", "-p", "--host", "-o", "--inspect-functions", "--site"}
CRED_TOOLS = ("gh", "firebase")
OVERLAY = os.path.join(os.path.dirname(os.path.realpath(__file__)), "config", "overlay.json")
VERCEL_VALUE_OPTS = {"--scope", "-S", "--token", "-t", "--cwd", "-A", "--local-config", "-Q", "--global-config",
                     "--team", "-T", "-e", "--env", "-b", "--build-env", "-m", "--meta", "--regions", "--archive"}
INLINE_RISK = re.compile(r"\bgit\b[\s\S]{0,120}?\bpush\b|\bsend-pack\b|\bgh\b[\s\S]{0,120}?\bmerge\b|"
                         r"pulls/[^\s'\"]*/merge|mergePullRequest|enablePullRequestAutoMerge|"
                         r"\bvercel\b[\s\S]{0,200}?(?:--prod|--production|\bpromote\b|\brollback\b|production)")
HEREDOC = re.compile(r"(?<!<)<<-?(?!<)\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")
SHELL_WORD = re.compile(r"(?:^|[\s|;&(])(?:ba|z|da|k)?sh(?:\s|$)|(?:^|[\s|;&(])eval(?:\s|$)")
INTERP_WORD = re.compile(r"(?:^|[\s|;&(/])(?:python\d*(?:\.\d+)?|node|nodejs|deno|bun|ruby|perl\d*|php|"
                         r"osascript)(?:\s|$)")
UNKNOWN = object()
CRED_WORD = re.compile(r"(?<![\w.-])(gh|firebase)(?![\w.-])")
CRED_SCRIPT = re.compile(r"(?m)(?:^|[;&|(`\s])(?:gh|firebase)\s|[\"'](?:gh|firebase)[\"' ]|/bin/(?:gh|firebase)\b")


def protected_projects():
    """The production Firebase projects the operator protects, from the installed local overlay
    (managed/render_policy.py writes <gate>/config/overlay.json from ~/.config/moadix/overlay.json);
    None when no overlay is installed."""
    import json
    try:
        with open(OVERLAY) as f:
            doc = json.load(f)
    except (OSError, ValueError):
        return None
    return {str(x) for x in doc.get("protected_firebase_projects") or []}


def _repo_root(cwd):
    d = os.path.realpath(cwd) if cwd else None
    while d and d != os.path.dirname(d):
        if os.path.exists(os.path.join(d, ".git")):
            return d
        d = os.path.dirname(d)
    return None


class Refuse(Exception):
    pass


def check(cmd, cwd):
    """None when the command may run, else the reason it is refused."""
    g = _Guard(BUDGET)
    try:
        g.command(cmd or "", os.path.realpath(cwd) if cwd else None, 0)
    except Refuse as e:
        return "main-branch guard: %s.%s" % (e, SUFFIX)
    except Exception as e:  # fail closed
        return "main-branch guard: could not inspect this command (%s: %s); refused (fail closed).%s" % (
            type(e).__name__, e, SUFFIX)
    return None


# ------------------------------------------------------------------ helpers
def _computed(w):
    return bool(re.search(r"[$`]", w))


def _is_main(ref):
    r = ref.lstrip("+")
    for p in ("refs/heads/", "heads/"):
        if r.startswith(p):
            r = r[len(p):]
            break
    return r.lower() == PROTECTED


def _join(cwd, p):
    p = os.path.expanduser(p)
    if os.path.isabs(p):
        return os.path.normpath(p)
    return None if cwd is None else os.path.normpath(os.path.join(cwd, p))


def _split(cmd):
    """Simple commands with the operator that follows each: ; | || && & or None."""
    segs, cur, q, i = [], [], None, 0

    def flush(op):
        segs.append(("".join(cur).strip(), op))
        del cur[:]

    while i < len(cmd):
        c = cmd[i]
        if q:
            cur.append(c)
            if c == q:
                q = None
            elif c == "\\" and q == '"' and i + 1 < len(cmd):
                cur.append(cmd[i + 1])
                i += 1
        elif c in "'\"":
            q = c
            cur.append(c)
        elif c == "\\" and i + 1 < len(cmd):
            cur.append(c + cmd[i + 1])
            i += 1
        elif c in ";\n":
            flush(";")
        elif c == "|":
            if cmd[i + 1:i + 2] == "|":
                flush("||")
                i += 1
            else:
                flush("|")
                if cmd[i + 1:i + 2] == "&":
                    i += 1
        elif c == "&" and not (cur and cur[-1] in ("<", ">")):
            if cmd[i + 1:i + 2] == ">":
                cur.append(c)
            elif cmd[i + 1:i + 2] == "&":
                flush("&&")
                i += 1
            else:
                flush("&")
        else:
            cur.append(c)
        i += 1
    flush(None)
    return [(s, op) for s, op in segs if s]


def _substitutions(cmd):
    """Texts of $(...), <(...), >(...) and `...` outside single quotes."""
    out, i, q = [], 0, None
    while i < len(cmd):
        c = cmd[i]
        if q == "'":
            if c == "'":
                q = None
        elif c == "\\":
            i += 1
        elif c == "'" and q is None:
            q = "'"
        elif c == '"':
            q = None if q == '"' else '"'
        elif c in "$<>" and cmd[i + 1:i + 2] == "(" and not (c == "$" and cmd[i + 2:i + 3] == "("):
            depth, j = 1, i + 2
            while j < len(cmd) and depth:
                if cmd[j] == "(":
                    depth += 1
                elif cmd[j] == ")":
                    depth -= 1
                j += 1
            out.append(cmd[i + 2:j - 1])
            i = j
            continue
        elif c == "`":
            j = cmd.find("`", i + 1)
            j = len(cmd) if j < 0 else j
            out.append(cmd[i + 1:j])
            i = j + 1
            continue
        i += 1
    return out


def _heredocs(cmd):
    """(command without heredoc bodies, [(kind, body)]) where kind is 'shell' or 'interp'
    for a body fed to a shell or an interpreter; other bodies are data and are dropped."""
    lines, out, bodies, i = cmd.split("\n"), [], [], 0
    while i < len(lines):
        line = lines[i]
        out.append(line)
        tags = [m.group(2) for m in HEREDOC.finditer(line)]
        i += 1
        for tag in tags:
            body = []
            while i < len(lines) and lines[i].strip() != tag:
                body.append(lines[i])
                i += 1
            i += 1
            kind = "shell" if SHELL_WORD.search(line) else "interp" if INTERP_WORD.search(line) else None
            if kind:
                bodies.append((kind, "\n".join(body)))
    return "\n".join(out), bodies


def _prefix(toks):
    """({VAR: value} assignments, the words from the command name on)."""
    env, i = {}, 0
    while i < len(toks):
        t = toks[i]
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$", t, re.S)
        if m:
            env[m.group(1)] = m.group(2)
            i += 1
        elif t == "function":
            i += 2
        elif t in bashcls.KEYWORDS or re.match(r"^[A-Za-z_][\w.:-]*\(\)\{?$", t) or t in ("sudo", "doas"):
            i += 1
        elif t in bashcls.WRAPPERS:
            i += 1
            while i < len(toks) and toks[i].startswith("-"):
                i += 1
            if t in ("timeout", "gtimeout") and i < len(toks):
                i += 1
        else:
            break
    return env, toks[i:]


def _shell_script(args):
    """The script of `sh [-opts] -c SCRIPT`, else None."""
    has_c, i = False, 0
    while i < len(args):
        a = args[i]
        if a == "--":
            i += 1
            break
        if a.startswith("-") and not a.startswith("--") and len(a) > 1:
            if "c" in a[1:]:
                has_c = True
            if a in ("-o", "+o") and i + 1 < len(args):
                i += 1
            i += 1
            continue
        if a.startswith("--"):
            i += 2 if a in ("--rcfile", "--init-file") else 1
            continue
        break
    return args[i] if has_c and i < len(args) else None


def _xargs_cmd(args):
    rest = list(args)
    while rest and rest[0].startswith("-"):
        rest = rest[2:] if rest[0] in ("-I", "-J", "-n", "-P", "-L", "-s", "-E", "-d", "-R", "-S") else rest[1:]
    return rest


class _Guard(object):
    def __init__(self, budget):
        self.deadline = time.monotonic() + budget
        self.branch = {}      # repo dir -> branch switched to earlier in this command ("?" = unknown, "" = detached)
        self.dirty = set()    # repos whose git config changed earlier in this command
        self.cfg = {}

    def left(self):
        r = self.deadline - time.monotonic()
        if r <= 0:
            raise Refuse("ran out of time inspecting this command; refused (fail closed)")
        return r

    def run(self, argv, cwd, env):
        """(returncode, stdout) of a local git call; Refuse on a timeout."""
        if cwd is None or not os.path.isdir(cwd):
            return 128, ""
        e = dict(os.environ)
        for k, v in env.items():
            if k.startswith("GIT_"):
                if _computed(v):
                    raise Refuse("%s is only known at run time" % k)
                e[k] = v
        e.update(GIT_TERMINAL_PROMPT="0", GIT_OPTIONAL_LOCKS="0")
        try:
            r = subprocess.run(argv, cwd=cwd, env=e, stdin=subprocess.DEVNULL, capture_output=True, text=True,
                               timeout=min(CALL_TIMEOUT, self.left()))
        except subprocess.TimeoutExpired:
            raise Refuse("a git call timed out; refused (fail closed)") from None
        return r.returncode, r.stdout

    # -------------------------------------------------------------- shell level
    def command(self, cmd, cwd, depth):
        if depth > MAX_DEPTH:
            raise Refuse("commands nested too deep to inspect; refused (fail closed)")
        self.left()
        text, bodies = _heredocs(cmd)
        for kind, body in bodies:
            if kind == "shell":
                self.command(body, cwd, depth + 1)
            else:
                self.inline(body)
        for inner in _substitutions(text):
            self.command(inner, cwd, depth + 1)
        cur, prev_dir, stack, prev = cwd, cwd, [], None
        segs = _split(text)
        sole = depth == 0 and len(segs) == 1 and segs[0][1] is None and not bodies and not list(_substitutions(text)) and \
            not re.search(r"(?<![\\])[`]|\$\(|<\(|>\(", text)
        for seg, op in segs:
            lead, trail, inner = bashcls._subshell_depth(seg)
            stack.extend([cur] * lead)
            toks, clean, herestr, k = bashcls.tokenize(inner), [], None, 0
            redirected = False
            while k < len(toks):
                t = toks[k]
                if t == "<<<":
                    herestr = toks[k + 1] if k + 1 < len(toks) else ""
                    redirected = True
                    k += 2
                elif t in ("<<", "<<-") or bashcls.REDIRECT_ANY.match(t):
                    redirected = True
                    k += 2
                else:
                    clean.append(t)
                    k += 1
            env, words = _prefix(clean)
            if words:
                verb = words[0].rsplit("/", 1)[-1]
                if verb in ("cd", "pushd"):
                    ops = [a for a in words[1:] if not a.startswith("-") or a == "-"]
                    dest = ops[0] if ops else "~"
                    if verb == "pushd":
                        stack.append(cur)
                    if dest == "-":
                        cur, prev_dir = prev_dir, cur
                    else:
                        prev_dir, cur = cur, (None if _computed(dest) else _join(cur, dest))
                elif verb == "popd":
                    cur = stack.pop() if stack else None
                else:
                    stdin_from = prev[0] if prev is not None and prev[1] == "|" else None
                    direct = sole and not lead and not trail and not redirected and not env and clean[:1] == words[:1]
                    self.simple(words, cur, env, depth, herestr=herestr, stdin_from=stdin_from, direct=direct)
            prev = (words, op)
            for _ in range(trail):
                cur = stack.pop() if stack else cur

    def scripts(self, verb, words, args, cwd, depth):
        """A script that calls gh or firebase would run them in a form the guard cannot check (and, run from
        a script, inside the sandbox without credentials). Refuse running one: shell scripts (sh x.sh,
        ./x.sh, source), interpreter files (node x.js, python x.py), and package scripts (npm/yarn/pnpm/bun
        run) are read and checked."""
        files = []
        if verb in SHELLS and _shell_script(args) is None:
            files = [a for a in args if not a.startswith("-")][:1]
        elif verb in ("source", "."):
            files = args[:1]
        elif bashcls.INTERPRETERS.match(verb):
            files = [a for a in args if not a.startswith("-")][:1]
        elif "/" in words[0] and verb not in CRED_TOOLS:
            files = [words[0]]
        for f in files:
            if _computed(f):
                continue
            p = _join(cwd, f)
            if p and os.path.isfile(p):
                try:
                    with open(p, encoding="utf-8", errors="replace") as fh:
                        text = fh.read(1 << 20)
                except OSError:
                    continue
                if CRED_SCRIPT.search(text):
                    raise Refuse("%s calls gh or firebase; run those directly so the guard can check them" % f)
        if verb in ("npm", "yarn", "pnpm", "bun") and cwd:
            name = None
            rest = [a for a in args if not a.startswith("-")]
            if rest[:1] in (["run"], ["run-script"]) and len(rest) > 1:
                name = rest[1]
            elif rest[:1] in (["test"], ["start"]) or (
                    verb != "npm" and rest and rest[0] not in ("install", "add", "remove", "exec", "dlx", "x", "ci")):
                name = rest[0]
            if name:
                pj = os.path.join(_repo_root(cwd) or cwd, "package.json")
                try:
                    import json
                    with open(pj) as fh:
                        sc = (json.load(fh).get("scripts") or {})
                except (OSError, ValueError, AttributeError):
                    sc = {}
                body = sc.get(name)
                if isinstance(body, str):
                    for k in ("pre" + name, name, "post" + name):
                        if isinstance(sc.get(k), str):
                            self.command(sc[k], cwd, depth + 1)

    def inline(self, code):
        if INLINE_RISK.search(code or ""):
            raise Refuse("inline interpreter code names a git push, a merge or a production deploy; run it as a "
                         "plain command so it can be checked")

    def simple(self, words, cwd, env, depth, herestr=None, stdin_from=None, open_args=False, direct=False):
        verb, args = words[0].rsplit("/", 1)[-1], words[1:]
        if verb in CRED_TOOLS or verb.startswith(("gh@", "firebase-tools")):
            self.cred_tool(verb, args, cwd, direct and words[0] == verb and not open_args)
            return
        if verb in RUNNER_HEADS and any(a.rsplit("/", 1)[-1].split("@", 1)[0] in CRED_TOOLS + ("firebase-tools",)
                                         for a in args[:4]):
            raise Refuse("%s would run gh or firebase in a form the guard cannot check; type it directly" % verb)
        if verb in ("alias", "hash", "function") and CRED_WORD.search(" ".join(args)):
            raise Refuse("an alias or hash entry for gh or firebase would run it in a form the guard cannot check")
        self.scripts(verb, words, args, cwd, depth)
        if verb in SHELLS:
            script = _shell_script(args)
            if script is not None:
                self.command(script, cwd, depth + 1)
            elif herestr is not None:
                self.command(herestr, cwd, depth + 1)
            elif not [a for a in args if not a.startswith("-")] and stdin_from and \
                    stdin_from[0].rsplit("/", 1)[-1] in ("echo", "printf"):
                self.command(" ".join(a for a in stdin_from[1:] if not a.startswith("-")), cwd, depth + 1)
            return
        if verb == "eval":
            self.command(" ".join(args), cwd, depth + 1)
            return
        if verb == "xargs":
            rest = _xargs_cmd(args)
            if rest:
                e2, w2 = _prefix(rest)
                if w2:
                    self.simple(w2, cwd, e2, depth + 1, open_args=True)
            return
        if verb == "find":
            for ex in bashcls._find_parts(args)[1]:
                e2, w2 = _prefix(ex)
                if w2:
                    self.simple(w2, cwd, e2, depth + 1, open_args=True)
            return
        if bashcls.INTERPRETERS.match(verb):
            for j, a in enumerate(args):
                if a in ("-c", "-e", "-E", "--eval", "-p", "-r") and j + 1 < len(args):
                    self.inline(args[j + 1])
            if herestr is not None:
                self.inline(herestr)
            return
        if verb == "git":
            self.git(args, cwd, env, depth, open_args, [])
        else:
            self.vercel(words, open_args)

    # -------------------------------------------------------------- git
    def git_config(self, repo, gargs, env):
        if repo is None:
            raise Refuse("git acts on a directory that is only known at run time")
        key = (repo, tuple(gargs), tuple(sorted(env.items())))
        if key not in self.cfg:
            rc, out = self.run([GIT] + gargs + ["config", "-z", "--list"], repo, env)
            if rc != 0:
                raise Refuse("could not read the git configuration in %s" % repo)
            d = {}
            for item in out.split("\0"):
                if item:
                    k, _, v = item.partition("\n")
                    d.setdefault(k, []).append(v)
            self.cfg[key] = d
        return self.cfg[key]

    def current_branch(self, repo, gargs, env):
        """Branch name, "" when detached, "?" when unknown."""
        if repo is None:
            return "?"
        if repo in self.branch:
            return self.branch[repo]
        rc, out = self.run([GIT] + gargs + ["symbolic-ref", "-q", "--short", "HEAD"], repo, env)
        return out.strip() if rc == 0 else "" if rc == 1 else "?"

    def _branch_exists(self, repo, gargs, env, name):
        rc, _ = self.run([GIT] + gargs + ["rev-parse", "--verify", "--quiet", "refs/heads/" + name], repo, env)
        if rc == 0:
            return True
        rc, out = self.run([GIT] + gargs + ["for-each-ref", "--format=%(refname)", "refs/remotes/*/" + name],
                           repo, env)
        return rc == 0 and bool(out.strip())

    def git(self, args, cwd, env, depth, open_args, gargs):
        repo, gargs, gcomp, i = cwd, list(gargs), False, 0
        while i < len(args):
            a = args[i]
            if a == "-C" and i + 1 < len(args):
                v = args[i + 1]
                repo = None if _computed(v) else _join(repo, v)
                i += 2
                continue
            if a == "-c" and i + 1 < len(args):
                v = args[i + 1]
                if "hookspath" in v.lower():
                    raise Refuse("git -c core.hooksPath=... would bypass the repository's pre-push hook")
                gcomp = gcomp or _computed(v)
                gargs += ["-c", v]
                i += 2
                continue
            if a in ("--git-dir", "--work-tree", "--namespace", "--config-env") and i + 1 < len(args):
                gargs += [a, args[i + 1]]
                gcomp = gcomp or _computed(args[i + 1])
                i += 2
                continue
            if a.startswith(("--git-dir=", "--work-tree=", "--namespace=", "--config-env=")):
                gargs.append(a)
                gcomp = gcomp or _computed(a)
                i += 1
                continue
            if a.startswith("-"):
                i += 1
                continue
            break
        if i >= len(args):
            return
        sub, sargs = args[i], args[i + 1:]
        if _computed(sub):
            raise Refuse("the git subcommand is only known at run time")
        if sub == "config":
            reads = {"--get", "--get-all", "--get-regexp", "-l", "--list", "--show-origin", "--get-urlmatch",
                     "--show-scope", "--name-only"}
            pos = [a for a in sargs if not a.startswith("-")]
            write = (len(pos) >= 2 or any(a in ("--unset", "--unset-all", "--add", "--replace-all", "--rename-section",
                                                "--remove-section", "-e", "--edit") for a in sargs)) \
                and not any(a in reads for a in sargs)
            if pos[:1] and pos[0] in ("set", "unset", "rename-section", "remove-section", "edit"):
                write = True
            if write:
                if any("hookspath" in a.lower() for a in sargs):
                    raise Refuse("changing core.hooksPath would disable the repository's pre-push hook")
                self.dirty.add(repo)
            return
        if sub == "remote" and sargs[:1] and sargs[0] not in ("-v", "--verbose", "show", "get-url"):
            self.dirty.add(repo)
        if sub == "branch":
            if any(a.startswith(("--set-upstream", "-u", "--track", "-t", "--unset-upstream")) for a in sargs):
                self.dirty.add(repo)
            if any(a in ("-m", "-M", "--move", "-c", "-C", "--copy") for a in sargs):
                self.branch[repo] = "?"
            return
        if sub in ("checkout", "switch"):
            self._switch(repo, gargs, env, sargs)
            return
        if sub == "push":
            if gcomp:
                raise Refuse("git push with a git option only known at run time")
            self.push(repo, gargs, env, sargs, open_args)
            return
        if sub == "send-pack":
            if open_args or any(_computed(a) for a in sargs):
                raise Refuse("git send-pack with refs only known at run time")
            if any(a in ("--all", "--mirror") for a in sargs) or any(_is_main(a.partition(":")[2] or a)
                                                                      for a in sargs if not a.startswith("-")):
                raise Refuse("git send-pack would update main")
            return
        if sub == "submodule" and "foreach" in sargs:
            rest = [a for a in sargs[sargs.index("foreach") + 1:] if a not in ("--recursive", "-q", "--quiet")]
            self.command(" ".join(rest), repo, depth + 1)
            return
        if sub == "rebase":
            for j, a in enumerate(sargs):
                if a in ("-x", "--exec") and j + 1 < len(sargs):
                    self.command(sargs[j + 1], repo, depth + 1)
                elif a.startswith("--exec="):
                    self.command(a.split("=", 1)[1], repo, depth + 1)
            return
        if sub == "bisect" and sargs[:1] == ["run"]:
            self.command(" ".join(shlex.quote(a) for a in sargs[1:]), repo, depth + 1)
            return
        if sub not in GIT_BUILTINS:
            if repo in self.dirty:
                raise Refuse("git %s may be an alias defined earlier in this command" % sub)
            alias = (self.git_config(repo, gargs, env).get("alias." + sub.lower()) or [None])[-1]
            if alias is None:
                return  # an external git-<sub> command, not an alias
            if gcomp:
                raise Refuse("a git alias with a git option only known at run time")
            if alias.startswith("!"):
                self.command(alias[1:] + "".join(" " + shlex.quote(a) for a in sargs), repo, depth + 1)
            else:
                self.git(shlex.split(alias) + sargs, repo, env, depth + 1, open_args, gargs)

    def _switch(self, repo, gargs, env, sargs):
        if "--" in sargs or repo is None:
            return  # a path checkout (no branch change), or a repository only known at run time
        new, j = None, 0
        while j < len(sargs):
            a = sargs[j]
            if a in ("-b", "-B", "-c", "-C", "--orphan", "--create", "--force-create") and j + 1 < len(sargs):
                new = sargs[j + 1]
                break
            if a.startswith(("--orphan=", "--create=", "--force-create=")):
                new = a.split("=", 1)[1]
                break
            j += 1
        if new is None:
            if "-" in sargs or any(a in ("-t", "--track") for a in sargs):
                new = "?"
            elif any(a in ("--detach", "-d") for a in sargs):
                new = ""
            else:
                pos = [a for a in sargs if not a.startswith("-")]
                if not pos:
                    return
                new = pos[0]
                if _computed(new) or not self._branch_exists(repo, gargs, env, new):
                    new = "?"
        self.branch[repo] = "?" if _computed(new) else new

    def push(self, repo, gargs, env, sargs, open_args):
        if open_args:
            raise Refuse("xargs or find -exec adds arguments to git push at run time")
        flags, pos, remote_opt, i = [], [], None, 0
        while i < len(sargs):
            a = sargs[i]
            if a == "--":
                pos.extend(sargs[i + 1:])
                break
            if a in PUSH_VALUE_OPTS and i + 1 < len(sargs):
                if a == "--repo":
                    remote_opt = sargs[i + 1]
                i += 2
                continue
            if a.startswith("--repo="):
                remote_opt = a.split("=", 1)[1]
            elif a.startswith("-"):
                flags.append(a)
            else:
                pos.append(a)
            i += 1
        for f in flags:
            name = f.split("=", 1)[0]
            if name in ("--all", "--branches", "--mirror"):
                raise Refuse("git push %s can update main" % name)
            if name == "--no-verify":
                raise Refuse("git push --no-verify skips the repository's pre-push hook")
        remote = pos[0] if pos else remote_opt
        refspecs = pos[1:]
        for w in ([remote] if remote else []) + refspecs:
            if _computed(w):
                raise Refuse("the push target %r is only known at run time" % w)
        if refspecs:
            for r in refspecs:
                self.refspec(r, repo, gargs, env)
            if remote and any(":" not in r for r in refspecs):
                for m in self.git_config(repo, gargs, env).get("remote.%s.push" % remote, []):
                    self.refspec(m, repo, gargs, env)
            return
        if "--tags" in flags:
            return  # tags only
        if repo in self.dirty:
            raise Refuse("the push configuration changed earlier in this command, so a bare git push cannot be checked")
        cfg = self.git_config(repo, gargs, env)
        br = self.current_branch(repo, gargs, env)
        if br == "?":
            raise Refuse("cannot tell which branch a bare git push would push here")
        last = lambda k, d=None: (cfg.get(k) or [d])[-1]  # noqa: E731
        if not remote:
            remote = last("branch.%s.pushremote" % br) or last("remote.pushdefault") or \
                last("branch.%s.remote" % br) or "origin"
        mapped = cfg.get("remote.%s.push" % remote)
        if mapped:
            for m in mapped:
                self.refspec(m, repo, gargs, env)
            return
        mode = (last("push.default", "simple") or "simple").lower()
        if mode == "matching":
            raise Refuse("push.default=matching: a bare git push pushes every matching branch, main included")
        if mode == "nothing" or br == "":
            return
        if br.lower() == PROTECTED:
            raise Refuse("a bare git push here pushes main (the current branch is main)")
        merge = last("branch.%s.merge" % br, "") or ""
        if mode in ("simple", "upstream", "tracking") and merge and _is_main(merge):
            raise Refuse("a bare git push here pushes to main (branch %s tracks %s)" % (br, merge))

    def refspec(self, r, repo, gargs, env):
        s = r.lstrip("+")
        if s == ":" or s == "":
            raise Refuse("git push %r pushes every matching branch, main included" % r)
        if "*" in s:
            raise Refuse("the wildcard refspec %r can match main" % r)
        src, sep, dst = s.partition(":")
        if not sep:
            dst = src
        if _is_main(dst):
            raise Refuse("git push ... %s targets main" % r)
        if dst in ("HEAD", "@"):
            br = self.current_branch(repo, gargs, env)
            if br == "?" or br.lower() == PROTECTED:
                raise Refuse("git push ... %s pushes the current branch, which is main%s" % (
                    r, " or unknown" if br == "?" else ""))

    # -------------------------------------------------------------- gh
    # -------------------------------------------------------------- gh and firebase (allowlists)
    # Both run OUTSIDE the sandbox with the operator's credentials (excludedCommands "gh *" and
    # "firebase *"), so they are allowlisted, never deny-listed: a subcommand or flag not listed
    # here is refused. They may only be typed directly as the whole command (`direct`): every
    # other form (sh -c, eval, an assignment or wrapper prefix, an alias, xargs, find -exec, a
    # full path, a pipe, a compound command, a substitution, a redirection, a script) is refused.
    def cred_tool(self, verb, args, cwd, direct):
        if not direct:
            raise Refuse("%s runs outside the sandbox with your credentials, so it may only be typed directly as "
                         "the whole command (no shell wrapper, eval, env or assignment prefix, alias, xargs, find "
                         "-exec, full path, pipe, compound command, substitution, redirection or script)" % verb)
        for a in args:
            if _computed(a):
                raise Refuse("%s arguments must be literal (a value is only known at run time)" % verb)
        if verb == "gh":
            self.gh(args, cwd)
        else:
            self.firebase(args, cwd)

    def _in_repo_file(self, path, cwd, what):
        if path == "-":
            raise Refuse("%s from stdin is refused (only a file inside this repository)" % what)
        root = _repo_root(cwd)
        full = os.path.realpath(_join(cwd, path) or "")
        if not root or not full.startswith(root + os.sep) or "/." in full[len(root):]:
            raise Refuse("%s %s is not a file inside this repository (outside the sandbox gh can read any file, so "
                         "only repository files may be sent)" % (what, path))

    def gh(self, args, cwd):
        pos, flags, i = [], [], 0
        while i < len(args):
            a = args[i]
            if a in GH_REPO_OPTS:
                i += 2
                continue
            if a.startswith("-"):
                flags.append(a)
                if a in GH_VALUE_FLAGS and i + 1 < len(args):
                    flags.append(args[i + 1])
                    i += 2
                    continue
            else:
                pos.append(a)
            i += 1
        if not pos:
            if all(f in ("--version", "--help", "-h") for f in flags) and flags:
                return
            raise Refuse("gh with no command")
        if pos[0] == "help" or "--help" in flags or "-h" in flags and pos[0] != "api":
            return
        if pos[0] == "api":
            self.gh_api(args[args.index("api") + 1:])
            return
        pair = tuple(pos[:2])
        if pair not in GH_ALLOWED:
            raise Refuse("gh %s is not on the allowlist (allowed: %s, and gh api with GET)" % (
                " ".join(pos[:2]), ", ".join(" ".join(x) for x in sorted(GH_ALLOWED))))
        if pair == ("auth", "status") and any(f in ("-t", "--show-token") or f.startswith("--show-token=")
                                              for f in flags):
            raise Refuse("gh auth status --show-token prints your token")
        for j, a in enumerate(args):
            if a in ("-F", "--body-file") and j + 1 < len(args):
                self._in_repo_file(args[j + 1], cwd, "gh %s" % a)
            elif a.startswith("--body-file="):
                self._in_repo_file(a.split("=", 1)[1], cwd, "gh --body-file")
            elif a in ("-T", "--template") and j + 1 < len(args) and os.sep in args[j + 1]:
                self._in_repo_file(args[j + 1], cwd, "gh --template")

    def gh_api(self, args):
        method, endpoint, i = None, None, 0
        has_body = False
        while i < len(args):
            a = args[i]
            if a.startswith("-X") and len(a) > 2:
                method = a[2:]
            elif a.startswith("--method="):
                method = a.split("=", 1)[1]
            elif a.startswith(("--field=", "--raw-field=", "--input=")) or a in ("--input",):
                has_body = True
                if a == "--input":
                    i += 1
            elif a in GH_API_VALUE_OPTS and i + 1 < len(args):
                if a in ("-X", "--method"):
                    method = args[i + 1]
                elif a in ("-f", "-F", "--field", "--raw-field"):
                    has_body = True
                i += 2
                continue
            elif a in ("--paginate", "--slurp", "-i", "--include", "--silent", "--verbose", "--cache") or \
                    a.startswith(("--jq=", "-q", "--template=", "-t", "--cache=", "--hostname=", "-H", "--header=",
                                  "-p", "--preview=")):
                pass
            elif a.startswith("-"):
                raise Refuse("gh api option %s is not on the allowlist" % a)
            elif endpoint is None:
                endpoint = a
            i += 1
        if endpoint is None:
            raise Refuse("gh api with no endpoint")
        ep = re.sub(r"^https?://[^/]+/", "", endpoint).lstrip("/").split("?")[0]
        if ep == "graphql":
            raise Refuse("gh api graphql is a POST and can carry mutations; only REST GET is allowed")
        m = (method or "GET").upper()
        if m != "GET":
            raise Refuse("gh api %s: only GET is allowed" % m)
        if has_body and method is None:
            raise Refuse("gh api with fields or --input sends a POST unless -X GET is given; only GET is allowed")

    def firebase(self, args, cwd):
        flags, pos, project, i = [], [], None, 0
        while i < len(args):
            a = args[i]
            if a in ("--project", "-P"):
                project = args[i + 1] if i + 1 < len(args) else ""
                i += 2
                continue
            if a.startswith("--project="):
                project = a.split("=", 1)[1]
            elif a.startswith("-"):
                flags.append(a)
                if a in FIREBASE_VALUE_FLAGS and i + 1 < len(args):
                    flags.append(args[i + 1])
                    i += 2
                    continue
            else:
                pos.append(a)
            i += 1
        for f in flags:
            if f in ("--token", "-T") or f.startswith("--token="):
                raise Refuse("firebase --token passes a credential on the command line")
        if not pos:
            if flags and all(f in ("--version", "-V", "--help", "-h") for f in flags):
                return
            raise Refuse("firebase with no command")
        cmd = pos[0]
        if cmd == "help" or "--help" in flags or "-h" in flags:
            return
        if cmd in FIREBASE_LOCAL:
            only = None
            for j, f in enumerate(flags):
                if f == "--only" and j + 1 < len(flags):
                    only = flags[j + 1]
                elif f.startswith("--only="):
                    only = f.split("=", 1)[1]
            parts = {x.split(":", 1)[0] for x in (only or "").split(",") if x}
            if not parts or not parts <= FIREBASE_SAFE_EMULATORS:
                raise Refuse("firebase %s must name --only from %s: the functions emulator (and the default, which "
                             "includes it) runs product code outside the sandbox" % (
                                 cmd, ",".join(sorted(FIREBASE_SAFE_EMULATORS))))
            if project is not None:
                self._fb_project(project, cwd, cmd)
            return
        if cmd in FIREBASE_NO_PROJECT:
            return
        if cmd not in FIREBASE_REMOTE:
            raise Refuse("firebase %s is not on the allowlist (allowed: %s; %s; %s with an explicit non-production "
                         "--project)" % (cmd, ", ".join(sorted(FIREBASE_LOCAL)), ", ".join(sorted(FIREBASE_NO_PROJECT)),
                                         ", ".join(sorted(FIREBASE_REMOTE))))
        if project is None:
            raise Refuse("firebase %s needs an explicit --project: the default in .firebaserc may be production" % cmd)
        self._fb_project(project, cwd, cmd)
        if cmd in ("deploy", "hosting:channel:deploy"):
            if "--force" in flags or "-f" in flags:
                raise Refuse("firebase deploy --force deletes what the source no longer has")
            hooks = self._fb_hooks(cwd)
            if hooks:
                raise Refuse("firebase.json has %s hooks, which firebase runs as shell commands outside the sandbox; "
                             "remove them and build before deploying" % ", ".join(hooks))

    def _fb_project(self, project, cwd, cmd):
        prot = protected_projects()
        if prot is None:
            raise Refuse("no protected-project list is installed (the operator's local overlay), so firebase %s "
                         "against a project is refused" % cmd)
        ids = {project}
        root = _repo_root(cwd) or cwd
        rc = os.path.join(root or "", ".firebaserc")
        if root and os.path.isfile(rc):
            import json
            try:
                with open(rc) as f:
                    aliases = (json.load(f).get("projects") or {})
            except (OSError, ValueError, AttributeError):
                raise Refuse(".firebaserc could not be read, so the project alias %r is unknown" % project) from None
            if project in aliases:
                ids.add(str(aliases[project]))
        hit = sorted(ids & prot)
        if hit or not re.match(r"^[a-z][a-z0-9-]{3,62}$", project):
            raise Refuse("firebase %s against %s: a protected production project (or not a plain project id/alias)" % (
                cmd, ", ".join(hit) or project))

    @staticmethod
    def _fb_hooks(cwd):
        import json
        root = _repo_root(cwd) or cwd
        p = os.path.join(root or "", "firebase.json")
        if not root or not os.path.isfile(p):
            return []
        try:
            with open(p) as f:
                text = f.read()
            json.loads(text)
        except (OSError, ValueError):
            raise Refuse("firebase.json could not be read, so its deploy hooks are unknown") from None
        return sorted(set(re.findall(r'"((?:pre|post)deploy)"', text)))

    # -------------------------------------------------------------- vercel
    def vercel(self, words, open_args):
        idx = None
        for j, t in enumerate(words[:8]):
            b = t.rsplit("/", 1)[-1]
            if b == "vercel" or b.startswith("vercel@"):
                idx = j
                break
            if j == 0 and b not in RUNNER_HEADS:
                return
            if j > 0 and not (t.startswith("-") or t in RUNNER_WORDS):
                return
        if idx is None:
            return
        args = words[idx + 1:]
        if open_args:
            raise Refuse("xargs or find -exec adds arguments to vercel at run time")
        pos, i = [], 0
        while i < len(args):
            a = args[i]
            if _computed(a):
                raise Refuse("a vercel argument (%s) is only known at run time" % a)
            name, eq, val = a.partition("=")
            if name in ("--prod", "--production"):
                if not eq or val.lower() not in ("false", "0"):
                    raise Refuse("vercel %s deploys to production" % a)
            elif name == "--target":
                v = val if eq else (args[i + 1] if i + 1 < len(args) else "")
                if v.lower() == "production" or _computed(v):
                    raise Refuse("vercel --target %s deploys to production" % v)
                i += 1 if eq else 2
                continue
            elif a in VERCEL_VALUE_OPTS:
                i += 2
                continue
            elif not a.startswith("-"):
                pos.append(a)
            i += 1
        if pos[:1] and pos[0] in ("promote", "rollback"):
            raise Refuse("vercel %s changes what production serves" % pos[0])
        if pos[:1] == ["alias"] and len(pos) >= 2 and pos[1] not in ("ls", "list", "help"):
            raise Refuse("vercel alias %s changes which deployment a domain serves" % pos[1])
