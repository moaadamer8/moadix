"""Bash command analysis for the PreToolUse gate.

Interim classifier for increment 1. Increment 2 rewrites it against a fixture
corpus of read-only commands (v1 defect list). The sandbox's denyWrite is the
backstop for anything this misses; Docker and Playwright, which run outside
the sandbox (Amendment 1 §4), are covered by the signed ledger instead.

Returns, per command:
  targets  - paths the command visibly writes (redirects, write verbs)
  opaque   - True when the command runs code we cannot see into
             (eval, sh -c, python -c, node -e, find -exec, xargs, source ...)
  words    - every word, for deny-lists (sudo, nested claude, ...)
"""
import re
import shlex

WRAPPERS = {"env", "nohup", "time", "command", "builtin", "exec", "nice", "caffeinate", "stdbuf", "timeout", "gtimeout"}
WRITE_ALL_OPERANDS = {"rm", "rmdir", "touch", "mkdir", "truncate", "chmod", "chown", "chflags", "chgrp",
                      "unlink", "shred", "tee", "xattr", "setfacl"}
WRITE_LAST_OPERAND = {"cp", "install", "ln", "rsync", "ditto", "scp"}
OPAQUE_VERBS = {"eval", "source", ".", "xargs", "parallel", "watch", "osascript", "expect", "script"}
INTERPRETERS = re.compile(r"^(?:ba|z|k|da|fi)?sh$|^python\d*(?:\.\d+)?$|^node$|^nodejs$|^deno$|^bun$|^perl\d*$|^ruby$|^php$|^osascript$|^lua$|^Rscript$")


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
    """Split on ; && || | & and newlines outside quotes."""
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


def _skip_wrappers(toks):
    i = 0
    while i < len(toks):
        t = toks[i]
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", t):
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


def analyse(cmd):
    cmd = strip_heredocs(cmd)
    targets, opaque, words, verbs = [], False, [], []
    if re.search(r"\$\(|`|<\(|>\(", cmd):
        opaque = True
    cwd_changes = []
    for seg in split_segments(cmd):
        toks = tokenize(seg)
        words.extend(toks)
        # redirections
        for j, t in enumerate(toks):
            if t in (">", ">>", ">|", "&>", "&>>", "<>") or re.match(r"^\d?>>?$", t):
                if j + 1 < len(toks) and not toks[j + 1].startswith("&") and toks[j + 1] != "/dev/null":
                    targets.append(toks[j + 1])
        toks = [t for k, t in enumerate(toks)
                if not (t in (">", ">>", ">|", "&>", "&>>", "<", "<>") or re.match(r"^\d?[<>]>?$", t))
                and not (k > 0 and (toks[k - 1] in (">", ">>", ">|", "&>", "&>>", "<", "<>") or re.match(r"^\d?[<>]>?$", toks[k - 1])))]
        toks = _skip_wrappers(toks)
        if not toks:
            continue
        verb = toks[0].rsplit("/", 1)[-1]
        verbs.append(verb)
        args = toks[1:]
        operands = [a for a in args if not a.startswith("-")]
        if verb == "cd" and operands:
            cwd_changes.append(operands[0])
        if verb in OPAQUE_VERBS or INTERPRETERS.match(verb):
            if verb in OPAQUE_VERBS or any(a in ("-c", "-e", "-E", "--eval", "-p", "-r") for a in args) or not operands \
                    or verb in ("sh", "bash", "zsh"):
                opaque = True
        if verb == "find" and any(a in ("-exec", "-execdir", "-delete", "-ok", "-fprint") for a in args):
            opaque = True
            targets.extend(operands[:1] or ["."])
        if verb in WRITE_ALL_OPERANDS:
            targets.extend(operands)
        elif verb in WRITE_LAST_OPERAND and operands:
            targets.append(operands[-1])
        elif verb == "mv":
            targets.extend(operands)  # sources are deleted, destination written
        elif verb in ("sed", "gsed", "perl") and any(a.startswith("-i") or a.startswith("--in-place") for a in args):
            targets.extend(operands[1:] if verb != "perl" else operands)
        elif verb == "dd":
            targets.extend(a[3:] for a in args if a.startswith("of="))
        elif verb in ("curl", "wget"):
            for j, a in enumerate(args):
                if a in ("-o", "--output", "-O", "--output-document") and j + 1 < len(args):
                    targets.append(args[j + 1])
        elif verb in ("tar", "bsdtar", "unzip"):
            for j, a in enumerate(args):
                if a in ("-C", "--directory", "-d") and j + 1 < len(args):
                    targets.append(args[j + 1])
            if not any(a in ("-C", "--directory", "-d") for a in args) and re.search(r"(^|\s)-?[a-zA-Z]*x", " ".join(args)):
                targets.append(".")
        elif verb == "git" and args:
            sub = operands[0] if operands else ""
            rest = [o for o in operands[1:] if o != "--"]
            if sub in ("checkout", "switch") and any(a in ("-b", "-B", "-c", "-C", "--orphan") for a in args) and len(rest) <= 2:
                pass  # creating a branch at HEAD changes no files
            elif sub in ("rm", "mv", "restore") or (sub == "checkout" and "--" in args):
                targets.extend(rest or [".sdlc"])
            elif sub in ("checkout", "switch", "clean", "reset", "stash", "apply", "am", "merge", "rebase",
                         "pull", "cherry-pick", "revert", "worktree", "filter-branch", "filter-repo"):
                # Rewrites tracked files, and .sdlc/ is tracked: treat as a write to gate state.
                targets.append(".sdlc")
    return {"targets": targets, "opaque": opaque, "words": words, "verbs": verbs, "cd": cwd_changes}
