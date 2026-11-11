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


def strip_heredocs(cmd):
    """Drop heredoc bodies (their text is data, not commands)."""
    out, lines, i = [], cmd.split("\n"), 0
    while i < len(lines):
        line = lines[i]
        out.append(line)
        m = re.search(r"<<-?\s*['\"]?([A-Za-z_][A-Za-z0-9_]*)['\"]?", line)
        if m:
            tag = m.group(1)
            i += 1
            while i < len(lines) and lines[i].strip() != tag:
                i += 1
        i += 1
    return "\n".join(out)


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
    cmd = strip_heredocs(cmd)
    res = {"writes": [], "links": [], "git": [], "opaque": False, "opaque_why": "", "computed": False,
           "computed_why": "", "words": [], "verbs": []}

    def opaque(why):
        if not res["opaque"]:
            res["opaque"], res["opaque_why"] = True, why

    def computed(why):
        if not res["computed"]:
            res["computed"], res["computed_why"] = True, why

    def write(path, at):
        if COMPUTED.search(path):
            computed("the write target %r is only known at run time" % path)
            return
        if at is None and not os.path.isabs(os.path.expanduser(path)):
            computed("%r is written relative to a directory that is only known at run time" % path)
            return
        res["writes"].append((path, at))

    if re.search(r"\$\(|`|<\(|>\(", cmd):
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
            if verb in ("cd", "pushd"):
                dest = ops[0] if ops else "~"
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
                        or not ops or verb in ("sh", "bash", "zsh"):
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
            elif verb in ("sed", "gsed", "perl") and any(a.startswith("-i") or a.startswith("--in-place")
                                                         for a in args):
                for o in (ops[1:] if verb != "perl" else ops):
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
