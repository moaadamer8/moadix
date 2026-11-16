"""Bash command analysis for the PreToolUse gate (increment 2 rewrite).

Rewritten against a corpus of read-only commands that v1 (and the interim
increment-1 classifier) wrongly denied (tests/gate2/corpus_readonly.py):
`git stash list`, a `*.pem` pattern in a read-only `find`, a bare `.`,
`tar -C`, `git checkout` in a scratch copy, and `cd` sweeps.

What changed, and why each was a false positive before:
  * cd is tracked IN ORDER, per segment, with subshells `( ... )`, pushd/popd
    and `cd -`. The interim classifier checked every write target against
    every directory the command ever cd'd into, so `cd /tmp/x && touch a;
    cd <product> && git status` denied `a` as if it were written in the product.
    A write whose directory is only known at run time (`cd "$d"`) is reported
    as such, never resolved against a guess.
  * `find -exec` / `xargs` running a READ-ONLY command are read-only. Pattern
    words (`-name '*.pem'`) are never paths.
  * cp/mv/ln/install into an existing directory (`cp a.md .`, `cp a docs/`)
    write <dir>/<basename>, not the directory: a bare `.` used to mean "the repo
    root, which contains .sdlc/".
  * tar is parsed by mode: -C is a WRITE target only when extracting; with -c
    it is where files are read from, and the archive (-f) is the write.
  * git commands that rewrite the work tree name the repository they act on
    (cwd or -C), so pretool can tell the product from a scratch copy.

Also closes the increment-1 symlink gap: `ln` sources are returned, resolved
relative to the link (for -s), so pretool can refuse a link to gate state even
when the link is created and written through in the same one-line command.

Returns, per command, a dict:
  writes   [(path, cwd)]          paths the command visibly writes; cwd None = unknown
  links    [(src, link, cwd, symbolic)]
  git      [(repo_dir, cwd, sub)] git commands that rewrite a work tree
  opaque   True when the command runs code we cannot see into
  computed True when a write target or its directory is only known at run time
  words / verbs                    for deny-lists (sudo, nested claude, ...)
"""
import os
import re
import shlex

WRAPPERS = {"env", "nohup", "time", "command", "builtin", "exec", "nice", "caffeinate", "stdbuf", "timeout",
            "gtimeout"}
KEYWORDS = {"do", "then", "else", "elif", "if", "while", "until", "!", "{", "}", "done", "fi", "esac", "in"}
WRITE_ALL_OPERANDS = {"rm", "rmdir", "touch", "mkdir", "truncate", "chmod", "chown", "chflags", "chgrp",
                      "unlink", "shred", "tee", "xattr", "setfacl"}
COPY_LIKE = {"cp", "install", "rsync", "ditto", "scp", "gcp"}
LINK_VERBS = {"ln", "gln", "link"}
OPAQUE_VERBS = {"eval", "source", ".", "parallel", "watch", "osascript", "expect", "script"}
INTERPRETERS = re.compile(r"^(?:ba|z|k|da|fi)?sh$|^python\d*(?:\.\d+)?$|^node$|^nodejs$|^deno$|^bun$|^perl\d*$|"
                          r"^ruby$|^php$|^osascript$|^lua$|^Rscript$")
# Commands that only read (for find -exec / xargs). A write flag disqualifies.
READ_ONLY = {"ls", "cat", "head", "tail", "wc", "grep", "egrep", "fgrep", "rg", "ag", "file", "stat", "du", "md5",
             "md5sum", "shasum", "sha1sum", "sha256sum", "openssl", "echo", "printf", "basename", "dirname",
             "realpath", "readlink", "test", "[", "true", "false", "less", "more", "jq", "yq", "diff", "cmp",
             "strings", "otool", "nm", "plutil", "od", "xxd", "hexdump", "sort", "uniq", "cut", "awk", "tr",
             "column", "nl", "fold", "git"}
READ_ONLY_WRITE_FLAGS = {"openssl": ("-out",), "sort": ("-o", "--output"), "awk": (), "git": ()}
REDIRECT = re.compile(r"^\d?(?:>>?|>\||&>>?)$|^<>$")
REDIRECT_ANY = re.compile(r"^\d?(?:>>?|>\||&>>?|<)$|^<>$")
GIT_GLOBAL_VALUE = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path"}
GIT_REWRITE = {"checkout", "switch", "restore", "clean", "reset", "stash", "apply", "am", "merge", "rebase", "pull",
               "cherry-pick", "revert", "worktree", "filter-branch", "filter-repo", "rm", "mv"}
COMPUTED = re.compile(r"[$`]|^~[^/]")


def strip_heredocs(cmd, live=None):
    """Drop heredoc bodies (their text is data, not commands). When `live` is a list, the body of
    each heredoc whose tag is NOT quoted is appended to it: the shell still expands $(...) and
    backticks there (0.7.1: such a body used to be dropped unseen)."""
    out, lines, i = [], cmd.split("\n"), 0
    while i < len(lines):
        line = lines[i]
        out.append(line)
        m = re.search(r"<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)(['\"]?)", line)
        if m:
            tag, quoted = m.group(2), bool(m.group(1) or m.group(3))
            i += 1
            body = []
            while i < len(lines) and lines[i].strip() != tag:
                body.append(lines[i])
                i += 1
            if live is not None and not quoted:
                live.append("\n".join(body))
        i += 1
    return "\n".join(out)


# ---------------------------------------------------------------- 0.7.1 (task-tracker MF-5, MF-8, MF-16)
# Commands whose output, inside $(...), <(...) or backticks, is all the substitution does: they read
# and print, run nothing and write nothing. Narrower than READ_ONLY on purpose: awk (system(), print >),
# yq (-i), rg (--pre), sed (e, w), find (-exec), openssl and less/more are left out.
SUBST_READ_ONLY = {"ls", "cat", "head", "tail", "wc", "grep", "egrep", "fgrep", "stat", "du", "md5", "md5sum",
                   "shasum", "sha1sum", "sha256sum", "echo", "printf", "basename", "dirname", "realpath", "readlink",
                   "test", "[", "true", "false", "jq", "diff", "cmp", "sort", "uniq", "cut", "tr", "column", "nl",
                   "fold", "git", "pwd", "seq"}
# 0.7.2 (review of 0.7.1, hook item 2): `file` (-C compiles a magic file) and `date` (-s sets the clock)
# were removed. Flags refused for every reader; per-tool rules are in _reader_ok.
SUBST_BAD_FLAGS = ("--output", "--compress-program", "--ext-diff", "--exec-path", "--temporary-directory",
                   "--paginate", "--textconv", "--filters")
# Paths a substitution may never read (0.7.2, hook item 1): the sandbox's denyRead and the managed
# Read() rules (transcripts and memory, the gh and firebase credential stores), plus secrets the
# path map protects and the overlay. Matched on the body's text after leading literal variables are
# resolved; an indirect name (a glob, a variable from the environment) is left to the sandbox.
SUBST_READ_DENY = [
    (re.compile(r"\.claude/projects"), "Claude Code transcripts and memory (~/.claude/projects)"),
    (re.compile(r"\.config/gh(?:/|\b)"), "the gh credential store (~/.config/gh)"),
    (re.compile(r"\.config/configstore"), "the firebase credential store (~/.config/configstore)"),
    (re.compile(r"\.config/moadix"), "the operator's overlay (~/.config/moadix)"),
    (re.compile(r"(?:^|[/\s'\"=])\.env(?!\.(?:example|sample|template)\b)(?:\.[\w-]+)?(?=$|[\s'\";|&)/])"),
     "a real environment file (.env)"),
    (re.compile(r"Keychains|\.pem\b|\.p12\b|\.pfx\b|\.jks\b|\.keystore\b|\bid_rsa|\bid_ed25519|"
                r"service-account[^\s/]*\.json|\.key\b"), "key material"),
]
# Anything that can make a reader's name run something else: a function or alias definition, a
# PATH change, shell options. With one of these in the command, L2 and L4 do not apply.
SHADOWING = re.compile(r"(?:^|[\s;&|(])(?:function\s+[\w.-]+|[\w.-]+\s*\(\s*\)|alias\b|unalias\b|hash\s|enable\s|"
                       r"(?:export\s+|typeset\s+|declare\s+|readonly\s+|local\s+)?(?:PATH|BASH_ENV|ENV|"
                       r"FPATH|IFS)\+?=|setopt\b|shopt\b|set\s+[-+])")
# Commands that only read their arguments (no option of theirs runs code or writes a file the
# classifier would miss): the gate's names in their ARGUMENTS are data (`grep <gate name> a.c`).
DATA_READERS = {"ls", "cat", "head", "tail", "wc", "grep", "egrep", "fgrep", "file", "stat", "du", "md5", "md5sum",
                "shasum", "sha1sum", "sha256sum", "echo", "printf", "basename", "dirname", "realpath", "readlink",
                "diff", "cmp", "nl", "test", "[", "true", "false"}
# Names whose assignment changes how the shell resolves paths or runs commands: never resolved.
SPECIAL_VARS = {"HOME", "PWD", "OLDPWD", "CDPATH", "IFS", "PATH", "ENV", "BASH_ENV", "ZDOTDIR", "SHELLOPTS",
                "GLOBIGNORE", "BASHOPTS", "PS4", "PROMPT_COMMAND", "TMPDIR", "FPATH", "LD_PRELOAD",
                "DYLD_INSERT_LIBRARIES"}
_ASSIGN = re.compile(r"\s*([A-Za-z_][A-Za-z0-9_]*)=(?:'([^'\s*?\[$`\\]*)'|\"([^\"\s*?\[$`\\]*)\"|"
                     r"([A-Za-z0-9_./+@:,%~-]+))[ \t]*(?:;|&&|\n)")


def substitutions(text, live_bodies=()):
    """[(kind, body)] for each $(...), backtick, <(...) and >(...) the shell would run in `text`:
    outside single quotes (a '$(' or '`' there is literal, MF-5) and not escaped. Heredoc bodies with
    an unquoted tag (`live_bodies`) have no quoting at all. An unbalanced one gives body None."""
    out = []

    def scan(t, quotes):
        i, q = 0, None
        while i < len(t):
            c = t[i]
            if c == "\\" and q != "'":
                i += 2
                continue
            if quotes and c == "'" and q in (None, "'"):
                q = None if q == "'" else "'"
            elif quotes and c == '"' and q in (None, '"'):
                q = None if q == '"' else '"'
            elif q != "'":
                if c == "`":
                    j = t.find("`", i + 1)
                    out.append(("`", t[i + 1:j] if j > 0 else None))
                    i = (j if j > 0 else len(t)) + 1
                    continue
                if c in "$<>" and t[i + 1:i + 2] == "(" and not (c == "$" and t[i + 2:i + 3] == "("):
                    depth, j, qq = 1, i + 2, None
                    while j < len(t) and depth:
                        d = t[j]
                        if qq:
                            qq = None if d == qq else qq
                        elif d in "'\"":
                            qq = d
                        elif d == "(":
                            depth += 1
                        elif d == ")":
                            depth -= 1
                        j += 1
                    out.append((c + "(", t[i + 2:j - 1] if depth == 0 else None))
                    i = j
                    continue
            i += 1

    scan(text, True)
    for b in live_bodies:
        scan(b, False)
    return out


def _reader_ok(verb, args):
    """Per-tool rules for SUBST_READ_ONLY (0.7.2, hook item 2): no operand or flag may write or run."""
    if any(a in SUBST_BAD_FLAGS or a.startswith(tuple(f + "=" for f in SUBST_BAD_FLAGS if f.startswith("--")))
           for a in args):
        return False
    if verb == "sort":
        # -o FILE writes, -T DIR writes temporaries, --compress-program runs; also as -ofile / -ro / -T/tmp
        return not any(a.startswith("-") and not a.startswith("--") and ("o" in a[1:] or "T" in a[1:])
                       for a in args)
    if verb == "uniq":
        return all(a.startswith("-") for a in args)  # `uniq in out` writes out: no operand at all
    if verb == "jq":
        # modules (-L, --library-path, import/include) load code from files; jq itself writes nothing
        return not any(a.startswith(("-L", "--library-path")) or re.search(r"\b(?:import|include)\b", a)
                       for a in args)
    if verb == "git":
        return _git_reader_ok(args)
    return True


def _git_reader_ok(args):
    """git in a substitution: only forms that run no filter, driver, pager, hook or signature check.
    Global options: only -C <dir>. Subcommands: rev-parse; cat-file -t/-s/-p/-e (no --textconv,
    --filters, --batch*); show of a blob, `<rev>:<path>` and no option ("For plain blobs, it shows the
    plain contents", git-show(1): no textconv, no diff, no signature)."""
    i = 0
    while i < len(args) and args[i].startswith("-"):
        if args[i] == "-C" and i + 1 < len(args) and not COMPUTED.search(args[i + 1]):
            i += 2
            continue
        return False
    if i >= len(args):
        return False
    sub, rest = args[i], args[i + 1:]
    if sub == "rev-parse":
        return True
    if sub == "cat-file":
        return all(not a.startswith("-") or a in ("-t", "-s", "-p", "-e") for a in rest)
    if sub == "show":
        return bool(rest) and all(re.match(r"^[A-Za-z0-9_.~^@{}/-]+:[^/\s$`]", a) and not a.startswith("-")
                                  and not COMPUTED.search(a) for a in rest)  # a literal <rev>:<path> only
    return False


def read_only_body(body):
    """True when a substitution body only reads: every segment a SUBST_READ_ONLY command called by
    bare name, passing _reader_ok, with no environment prefix, no write redirection, no nested
    substitution. Anything else stays opaque (the conservative direction)."""
    if body is None or re.search(r"\$\(|`|<\(|>\(", body) or "<<" in body or SHADOWING.search(body):
        return False
    for seg in split_segments(body):
        toks = tokenize(seg)
        for j, t in enumerate(toks):
            if REDIRECT.match(t):
                tgt = toks[j + 1] if j + 1 < len(toks) else ""
                if not (tgt.startswith("&") or tgt == "/dev/null"):
                    return False
        toks = [t for k, t in enumerate(toks)
                if not REDIRECT_ANY.match(t) and not (k > 0 and REDIRECT_ANY.match(toks[k - 1]))]
        if not toks or "=" in toks[0] or toks[0] in KEYWORDS or "(" in toks[0] or ")" in toks[0] or \
                "/" in toks[0] or COMPUTED.search(toks[0]):
            return False
        if toks[0] not in SUBST_READ_ONLY or not _reader_ok(toks[0], toks[1:]):
            return False
    return True


def subst_denied_reads(body, env):
    """What a substitution body names that it may never read (SUBST_READ_DENY), or []."""
    text = expand_vars(body or "", env)
    text = re.sub(r"(^|[\s'\"=])~(?=/)", lambda m: m.group(1) + os.path.expanduser("~"), text)
    return [what for rx, what in SUBST_READ_DENY if rx.search(text)]


def leading_assignments(text):
    """{NAME: value} for literal assignments that OPEN the command, each ended by ';', '&&' or a
    newline (`S=/tmp/x; mkdir -p "$S"`, MF-16). Only these run unconditionally, in this shell,
    before anything else. A name is resolved only when nothing else in the command can rebind it:
    its only bare occurrence in the whole text is the assignment (no `read S`, `for S in`, second
    `S=`), it is not a special variable, and its value has no expansion, space or glob."""
    found, pos = {}, 0
    while True:
        m = _ASSIGN.match(text, pos)
        if not m:
            break
        name = m.group(1)
        val = next(g for g in (m.group(2), m.group(3), m.group(4)) if g is not None)
        if "~" in val and not (m.group(4) is not None and (val == "~" or val.startswith("~/"))):
            val = None  # a quoted ~ stays literal and ~user is someone's home: refuse the guess
        found[name] = val if name not in found else None
        pos = m.end()
    out = {}
    for name, val in found.items():
        if val is None or name in SPECIAL_VARS:
            continue
        bare = re.findall(r"(?<![\w$])(?<!\$\{)%s(?![\w])" % re.escape(name), text)
        # '$S' in single quotes is the literal text $S, which shlex cannot tell from "$S": refuse
        quoted_literal = re.search(r"'[^']*\$\{?%s(?!\w)" % re.escape(name), text[pos:])
        if len(bare) == 1 and not quoted_literal:
            out[name] = val
    return out


def expand_vars(word, env):
    """`word` with each $NAME / ${NAME} of `env` replaced; any other expansion is left for COMPUTED."""
    if not env or "$" not in word:
        return word
    return re.sub(r"\$(?:\{([A-Za-z_][A-Za-z0-9_]*)\}|([A-Za-z_][A-Za-z0-9_]*)(?![\w{]))",
                  lambda m: env.get(m.group(1) or m.group(2), m.group(0)), word)


def _sed_files(args, gnu):
    """The files `sed -i` edits (MF-16c): BSD `-i ''` / `-i .bak` and GNU `-i` / `-i.bak`; -e and -f
    scripts are not files; without them the first operand is the script."""
    files, script_given, i = [], False, 0
    while i < len(args):
        a = args[i]
        if a == "--":
            files += args[i + 1:]
            break
        if a in ("-e", "--expression", "-f", "--file"):
            script_given, i = True, i + 2
            continue
        if a.startswith(("--expression=", "--file=")):
            script_given = True
        elif a in ("-i", "--in-place"):
            nxt = args[i + 1] if i + 1 < len(args) else None
            if not gnu and nxt is not None and (nxt == "" or re.match(r"^\.[\w.~-]*$", nxt)):
                i += 1  # BSD: the backup suffix is the next argument
        elif a in ("-l", "--line-length"):
            i += 1
        elif re.match(r"^-[A-Za-z]*[ef]$", a) and not a.startswith("-i"):
            script_given, i = True, i + 2  # bundled -ne / -Ee: the script (or script file) follows
            continue
        elif not a.startswith("-") or a == "-":
            files.append(a)
        i += 1
    return files if script_given else files[1:]


def split_segments(cmd):
    """Split on ; && || | & and newlines outside quotes. Parentheses stay in the text."""
    segs, cur, q, i = [], [], None, 0
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
        elif c in ";\n" or c == "|" or (c == "&" and not (cur and cur[-1] in "<>")):
            if c == "&" and i + 1 < len(cmd) and cmd[i + 1] == ">":
                cur.append(c)
            else:
                segs.append("".join(cur))
                cur = []
                if c in "|&" and i + 1 < len(cmd) and cmd[i + 1] == c:
                    i += 1
        else:
            cur.append(c)
        i += 1
    segs.append("".join(cur))
    return [s.strip() for s in segs if s.strip()]


def tokenize(seg):
    try:
        lex = shlex.shlex(seg, posix=True, punctuation_chars="<>")
        lex.whitespace_split = True
        lex.commenters = ""
        return list(lex)
    except ValueError:
        return seg.split()


def _subshell_depth(seg):
    """(leading '(' count, trailing ')' count) outside quotes, and the inner text."""
    s = seg.strip()
    lead = 0
    while s.startswith("("):
        lead += 1
        s = s[1:].lstrip()
    trail = 0
    q = None
    for c in s:
        if q:
            q = None if c == q else q
        elif c in "'\"":
            q = c
    if q is None:
        while s.endswith(")") and not s.endswith("$()") and s.count("(") < s.count(")"):
            trail += 1
            s = s[:-1].rstrip()
    return lead, trail, s


def _skip_wrappers(toks):
    i = 0
    while i < len(toks):
        t = toks[i]
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", t) or t in KEYWORDS:
            i += 1
        elif t in WRAPPERS:
            i += 1
            while i < len(toks) and toks[i].startswith("-"):
                i += 1
            if t in ("timeout", "gtimeout") and i < len(toks):
                i += 1
        else:
            break
    return toks[i:]


def _join(cwd, p):
    if cwd is None:
        return None if not os.path.isabs(os.path.expanduser(p)) else os.path.expanduser(p)
    p = os.path.expanduser(p)
    return os.path.normpath(p if os.path.isabs(p) else os.path.join(cwd, p))


def _into_dir(dest, cwd):
    """True when `dest` names an existing directory (or ends with '/')."""
    if dest.endswith("/") or dest in (".", ".."):
        return True
    full = _join(cwd, dest)
    return bool(full) and os.path.isdir(full) and not os.path.islink(full)


def _operands(args, value_flags=()):
    out, skip = [], False
    for a in args:
        if skip:
            skip = False
            continue
        if a in value_flags:
            skip = True
            continue
        if a == "--":
            continue
        if a.startswith("-") and a != "-":
            continue
        out.append(a)
    return out


def _git_parts(args, cwd):
    """(repo_dir, subcommand, sub_args) for `git [-C dir] [-c k=v] sub ...`."""
    repo, i = cwd, 0
    while i < len(args):
        a = args[i]
        if a in GIT_GLOBAL_VALUE and i + 1 < len(args):
            if a == "-C":
                repo = _join(repo, args[i + 1]) if not COMPUTED.search(args[i + 1]) else None
            i += 2
            continue
        if a.startswith("--git-dir=") or a.startswith("--work-tree="):
            i += 1
            continue
        if a.startswith("-"):
            i += 1
            continue
        return repo, a, args[i + 1:]
    return repo, "", []


def _git_rewrites(sub, sargs):
    """True when a git subcommand can rewrite tracked files in the work tree."""
    ops = [o for o in sargs if not o.startswith("-")]
    if sub == "stash":
        return not (ops[:1] in (["list"], ["show"]))
    if sub in ("checkout", "switch"):
        branch_create = any(a in ("-b", "-B", "-c", "-C", "--orphan") for a in sargs)
        return not (branch_create and len([o for o in ops if o != "--"]) <= 2 and "--" not in sargs)
    if sub == "apply":
        return not any(a in ("--check", "--stat", "--summary", "--numstat") for a in sargs)
    if sub == "worktree":
        return bool(ops) and ops[0] not in ("list",)
    if sub == "reset":
        return any(a in ("--hard", "--merge", "--keep") for a in sargs)
    if sub == "clean":
        return not any(a in ("-n", "--dry-run") or (a.startswith("-") and not a.startswith("--") and "n" in a)
                       for a in sargs)
    return sub in GIT_REWRITE


def _find_parts(args):
    """(roots, exec_cmds, deletes) for find."""
    roots, i = [], 0
    while i < len(args) and not args[i].startswith(("-", "(", "!")):
        roots.append(args[i])
        i += 1
    execs, deletes = [], "-delete" in args
    while i < len(args):
        if args[i] in ("-exec", "-execdir", "-ok", "-okdir"):
            j = i + 1
            cmd = []
            while j < len(args) and args[j] not in (";", "\\;", "+"):
                cmd.append(args[j])
                j += 1
            execs.append(cmd)
            i = j
        i += 1
    return roots or ["."], execs, deletes


def _read_only(cmd):
    if not cmd:
        return False
    verb = cmd[0].rsplit("/", 1)[-1]
    if verb not in READ_ONLY:
        return False
    if verb == "git":
        _r, sub, sargs = _git_parts(cmd[1:], ".")
        return sub in ("log", "show", "status", "diff", "blame", "ls-files", "rev-parse", "cat-file") or \
            (sub == "stash" and sargs[:1] in (["list"], ["show"]))
    return not any(a in READ_ONLY_WRITE_FLAGS.get(verb, ()) or a.startswith(tuple(
        f + "=" for f in READ_ONLY_WRITE_FLAGS.get(verb, ()))) for a in cmd[1:])


def analyse(cmd, cwd=None):
    """See module docstring. `cwd` is the directory the command starts in."""
    live = []
    cmd = strip_heredocs(cmd, live)
    env = leading_assignments(cmd)
    res = {"writes": [], "links": [], "git": [], "opaque": False, "opaque_why": "", "computed": False,
           "computed_why": "", "words": [], "verbs": [], "exec_text": [], "stripped": cmd, "resolved": dict(env)}

    def opaque(why):
        if not res["opaque"]:
            res["opaque"], res["opaque_why"] = True, why

    def computed(why):
        if not res["computed"]:
            res["computed"], res["computed_why"] = True, why

    def write(path, at):
        path = expand_vars(path, env)
        if COMPUTED.search(path):
            computed("the write target %r is only known at run time" % path)
            return
        if at is None and not os.path.isabs(os.path.expanduser(path)):
            computed("%r is written relative to a directory that is only known at run time" % path)
            return
        res["writes"].append((path, at))

    shadowed = bool(SHADOWING.search(cmd))
    res["shadowed"] = shadowed
    res["subst_denied"] = []
    for kind, body in substitutions(cmd, live):
        # 0.7.1: a substitution that only reads (`$(git show HEAD:a)`) runs nothing the gate cannot see;
        # >(...) feeds a process and stays opaque, as does any body with a writer, an interpreter or a nest.
        # 0.7.2: never when the command can shadow a reader; and a read of a denied path is refused outright.
        res["subst_denied"] += subst_denied_reads(body, env)
        if kind == ">(" or shadowed or not read_only_body(body):
            opaque("command substitution")
    start = cwd
    cur, prev, stack = start, start, []
    for seg in split_segments(cmd):
        lead, trail, inner = _subshell_depth(seg)
        for _ in range(lead):
            stack.append(cur)
        toks = tokenize(inner)
        res["words"].extend(toks)
        # redirections
        for j, t in enumerate(toks):
            if REDIRECT.match(t) and j + 1 < len(toks):
                tgt = toks[j + 1]
                if not tgt.startswith("&") and tgt not in ("/dev/null", "/dev/stdout", "/dev/stderr", "/dev/tty"):
                    write(tgt, cur)
        toks = [t for k, t in enumerate(toks)
                if not REDIRECT_ANY.match(t) and not (k > 0 and REDIRECT_ANY.match(toks[k - 1]))]
        toks = _skip_wrappers(toks)
        if toks:
            verb = toks[0].rsplit("/", 1)[-1]
            res["verbs"].append(verb)
            args = toks[1:]
            ops = _operands(args)
            if COMPUTED.search(toks[0]):
                opaque("the command name %r is only known at run time" % toks[0])  # 0.7.1: `X=rm; $X ...`
            if verb not in DATA_READERS or "/" in toks[0] or shadowed:
                res["exec_text"].append(inner)
            if verb in ("cd", "pushd"):
                dest = expand_vars(ops[0], env) if ops else "~"
                if verb == "pushd":
                    stack.append(cur)
                if dest == "-":
                    cur, prev = prev, cur
                elif COMPUTED.search(dest):
                    prev, cur = cur, None
                else:
                    prev, cur = cur, _join(cur, dest)
            elif verb == "popd":
                cur = stack.pop() if stack else None
            elif verb in OPAQUE_VERBS or INTERPRETERS.match(verb):
                if verb in OPAQUE_VERBS or any(a in ("-c", "-e", "-E", "--eval", "-p", "-r") for a in args) \
                        or not ops or ops[0] in ("-", "/dev/stdin", "/dev/fd/0") or verb in ("sh", "bash", "zsh"):
                    opaque("%s runs code given inline or from stdin" % verb)
            elif verb == "xargs":
                rest = args
                while rest and rest[0].startswith("-"):
                    rest = rest[2:] if rest[0] in ("-I", "-n", "-P", "-L", "-s", "-E", "-d") else rest[1:]
                if not _read_only(rest):
                    if rest and rest[0].rsplit("/", 1)[-1] in WRITE_ALL_OPERANDS | COPY_LIKE | {"mv"} | LINK_VERBS:
                        computed("xargs feeds run-time paths to %s" % rest[0])
                    else:
                        opaque("xargs runs %s" % (rest[0] if rest else "echo"))
            elif verb == "find":
                roots, execs, deletes = _find_parts(args)
                for ex in execs:
                    if _read_only(ex):
                        continue
                    if ex and ex[0].rsplit("/", 1)[-1] in WRITE_ALL_OPERANDS | COPY_LIKE | {"mv"}:
                        for r in roots:
                            write(r, cur)
                    else:
                        opaque("find -exec runs %s" % (ex[0] if ex else "nothing"))
                if deletes or "-fprint" in args:
                    for r in roots:
                        write(r, cur)
            elif verb in WRITE_ALL_OPERANDS:
                for o in ops:
                    write(o, cur)
            elif verb in COPY_LIKE or verb == "mv":
                vflags = ("-t", "--target-directory", "-m", "-o", "-g", "-S", "-e", "--exclude", "--include",
                          "--link-dest", "-f", "--files-from") if verb != "mv" else ("-t",)
                ops = _operands(args, vflags if verb != "cp" else ())
                hard = verb == "cp" and any(a in ("-l", "--link") or (a.startswith("-") and not a.startswith("--")
                                                                      and "l" in a[1:]) for a in args)
                if len(ops) >= 2:
                    dest, srcs = ops[-1], ops[:-1]
                    if verb == "mv":
                        for s in srcs:
                            write(s, cur)  # a move deletes its source
                    if hard:
                        for s in srcs:
                            res["links"].append((s, dest, cur, False))
                    if _into_dir(dest, cur) and not COMPUTED.search(dest):
                        for s in srcs:
                            write(os.path.join(dest, os.path.basename(s.rstrip("/")) or s), cur)
                    else:
                        write(dest, cur)
            elif verb in LINK_VERBS:
                symbolic = any(a == "-s" or a == "--symbolic" or (a.startswith("-") and not a.startswith("--")
                                                                 and "s" in a[1:]) for a in args)
                ops = _operands(args, ("-t", "--target-directory"))
                if len(ops) == 1:
                    ops = ops + ["."]
                if len(ops) >= 2:
                    dest, srcs = ops[-1], ops[:-1]
                    many = len(srcs) > 1 or _into_dir(dest, cur)
                    for s in srcs:
                        link = os.path.join(dest, os.path.basename(s.rstrip("/"))) if many else dest
                        res["links"].append((s, link, cur, symbolic))
                        write(link, cur)
            elif verb in ("sed", "gsed") and any(re.match(r"^-[A-Za-z]*i", a) or a.startswith("--in-place")
                                                 for a in args):
                for o in _sed_files(args, gnu=verb == "gsed"):
                    write(o, cur)
            elif verb == "dd":
                for a in args:
                    if a.startswith("of="):
                        write(a[3:], cur)
            elif verb in ("curl", "wget"):
                for j, a in enumerate(args):
                    if a in ("-o", "--output", "-O", "--output-document") and j + 1 < len(args):
                        write(args[j + 1], cur)
            elif verb in ("tar", "bsdtar", "gtar"):
                _tar(args, cur, write)
            elif verb == "unzip":
                d = next((args[j + 1] for j, a in enumerate(args) if a == "-d" and j + 1 < len(args)), ".")
                if "-l" not in args and "-t" not in args and "-Z" not in args:
                    write(d, cur)
            elif verb == "git":
                repo, sub, sargs = _git_parts(args, cur)
                if sub in ("rm", "mv", "restore") or (sub == "checkout" and "--" in sargs):
                    paths = list(sargs[sargs.index("--") + 1:]) if "--" in sargs else \
                        [o for o in sargs if not o.startswith("-")]
                    for path in paths or ["."]:
                        if repo is None:
                            computed("git -C with a directory only known at run time")
                        else:
                            write(path, repo)
                elif _git_rewrites(sub, sargs):
                    res["git"].append((repo, cur, sub))
                elif sub == "clone":
                    ops2 = [o for o in sargs if not o.startswith("-")]
                    if len(ops2) >= 2:
                        write(ops2[1], cur)
        for _ in range(trail):
            cur = stack.pop() if stack else cur
    return res


def _tar(args, cur, write):
    """tar: -C is a write target only in extract mode; in create mode the archive is."""
    flags, rest = "", list(args)
    if rest and not rest[0].startswith("-") and re.match(r"^[A-Za-z]+$", rest[0]):
        flags, rest = rest[0], rest[1:]  # bundled old-style: tar czf out.tgz dir
    for a in rest:
        if a.startswith("-") and not a.startswith("--"):
            flags += a[1:]
    longs = {a.split("=", 1)[0] for a in rest if a.startswith("--")}
    extract = "x" in flags or "--extract" in longs or "--get" in longs
    create = "c" in flags or "r" in flags or "u" in flags or {"--create", "--append", "--update"} & longs
    archive = None
    for j, a in enumerate(rest):
        if a in ("-f", "--file") and j + 1 < len(rest):
            archive = rest[j + 1]
        elif a.startswith("--file="):
            archive = a.split("=", 1)[1]
        elif a.startswith("-") and not a.startswith("--") and a.endswith("f") and j + 1 < len(rest):
            archive = rest[j + 1]
    if archive is None and flags and "f" in flags and not args[0].startswith("-") and rest:
        archive = rest[0]
    cdir = None
    for j, a in enumerate(rest):
        if a in ("-C", "--directory") and j + 1 < len(rest):
            cdir = rest[j + 1]
        elif a.startswith("--directory="):
            cdir = a.split("=", 1)[1]
    if extract:
        write(cdir or ".", cur)
    elif create and archive and archive != "-":
        write(archive, cur)
