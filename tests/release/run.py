#!/usr/bin/python3
"""Release check: a change to what the plugin ships needs a new plugin version.

    /usr/bin/python3 tests/release/run.py

Claude Code installs and caches a plugin by its version, so a change under a
shipped folder without a version bump never reaches an existing install (the
0.2.0 lesson: agents/ was added and installs did not pick it up).

The check FAILS when any file under SHIPPED differs between the last release and
the working tree (committed, staged, unstaged or untracked) while
.claude-plugin/plugin.json's "version" is the same as at that release.

The last release is the most recent tag reachable from HEAD. When the repository
has no tag yet, it is the last commit that changed plugin.json's version, and
the output says so; tag each release (git tag v<version>) to make the baseline
explicit.

Also runs a self-test of the rule on throwaway repositories under $TMPDIR.
gate2/run.py runs this check as its "release" group.
"""
import json
import os
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
GIT = "/usr/bin/git"
MANIFEST = ".claude-plugin/plugin.json"
# Everything the plugin loads from this repo (marketplace source "./"). The gate
# itself (gate/, managed/, checker/) ships through managed/install.sh, not the plugin.
SHIPPED = ("agents", "commands", "skills", "templates", "hooks", ".claude-plugin/marketplace.json")


def _git(repo, *args):
    r = subprocess.run([GIT, "-C", repo] + list(args), capture_output=True, text=True)
    return r.returncode, r.stdout.strip()


def _version_at(repo, rev):
    rc, out = _git(repo, "show", "%s:%s" % (rev, MANIFEST))
    return json.loads(out).get("version") if rc == 0 and out else None


def baseline(repo):
    """(rev, how) of the last release, or (None, why)."""
    rc, tag = _git(repo, "describe", "--tags", "--abbrev=0")
    if rc == 0 and tag:
        return tag, "tag %s" % tag
    _rc, revs = _git(repo, "log", "--format=%H", "--", MANIFEST)
    for rev in revs.split():
        prev = _version_at(repo, rev + "^")
        if prev != _version_at(repo, rev):
            return rev, "no tag yet; the last version change, %s (%s)" % (rev[:12], _version_at(repo, rev))
    return None, "no tag and no commit of %s" % MANIFEST


def check(repo):
    """(ok, message)."""
    base, how = baseline(repo)
    if base is None:
        return False, "no release baseline: %s" % how
    _rc, diffed = _git(repo, "diff", "--name-only", base, "--", *SHIPPED)
    _rc, untracked = _git(repo, "ls-files", "--others", "--exclude-standard", "--", *SHIPPED)
    changed = sorted(set(diffed.split("\n") + untracked.split("\n")) - {""})
    try:
        with open(os.path.join(repo, MANIFEST)) as f:
            now = json.load(f).get("version")
    except (OSError, ValueError) as e:
        return False, "%s unreadable: %s" % (MANIFEST, e)
    then = _version_at(repo, base)
    if changed and now == then:
        return False, ("%d shipped file(s) changed since the last release (%s) but %s is still version %s; bump it. "
                       "Changed: %s" % (len(changed), how, MANIFEST, now, ", ".join(changed[:10]) +
                                        (" ..." if len(changed) > 10 else "")))
    return True, "baseline %s; version %s -> %s; %d shipped file(s) changed" % (how, then, now, len(changed))


# ------------------------------------------------------------------ self-test
def _scratch(tags=True):
    d = tempfile.mkdtemp(prefix="moadix-release-")
    env = ["-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c", "commit.gpgsign=false",
           "-c", "tag.gpgsign=false"]

    def w(path, text):
        p = os.path.join(d, path)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as f:
            f.write(text)

    def commit(msg):
        subprocess.run([GIT, "-C", d] + env + ["add", "-A"], check=True, capture_output=True)
        subprocess.run([GIT, "-C", d] + env + ["commit", "-qm", msg], check=True, capture_output=True)

    subprocess.run([GIT, "init", "-q", d], check=True, capture_output=True)
    w(MANIFEST, json.dumps({"name": "x", "version": "0.1.0"}))
    w("agents/a.md", "a\n")
    w("docs/n.md", "n\n")
    commit("release 0.1.0")
    if tags:
        subprocess.run([GIT, "-C", d] + env + ["tag", "v0.1.0"], check=True, capture_output=True)
    return d, w, commit


def selftest():
    out = []
    import shutil
    d, w, commit = _scratch()
    try:
        out.append(("control: nothing changed since the tag -> pass", check(d)[0]))
        w("docs/n.md", "changed docs\n")
        commit("docs")
        out.append(("a change outside the shipped folders -> pass", check(d)[0]))
        w("agents/a.md", "changed\n")
        out.append(("an uncommitted change under agents/ without a bump -> FAIL", not check(d)[0]))
        commit("agent change")
        out.append(("a committed change under agents/ without a bump -> FAIL", not check(d)[0]))
        subprocess.run([GIT, "-C", d, "reset", "-q", "--hard", "v0.1.0"], check=True)
        w("skills/new/SKILL.md", "x\n")
        out.append(("an untracked new file under skills/ without a bump -> FAIL", not check(d)[0]))
        w(MANIFEST, json.dumps({"name": "x", "version": "0.1.1"}))
        out.append(("the same change with the version bumped -> pass", check(d)[0]))
    finally:
        shutil.rmtree(d, ignore_errors=True)
    d, w, commit = _scratch(tags=False)
    try:
        w(MANIFEST, json.dumps({"name": "x", "version": "0.1.1"}))
        commit("bump")
        ok, msg = check(d)
        out.append(("no tag: the baseline is the last version change; nothing since -> pass",
                    ok and "no tag yet" in msg))
        w("commands/c.md", "c\n")
        out.append(("no tag: a shipped change after the last version change -> FAIL", not check(d)[0]))
    finally:
        shutil.rmtree(d, ignore_errors=True)
    return out


def results():
    """[(name, ok, evidence)] for a suite runner."""
    r = [("self-test: " + n, ok, "") for n, ok in selftest()]
    ok, msg = check(REPO)
    r.append(("this repo: shipped folders unchanged since the last release, or plugin.json's version bumped", ok, msg))
    return r


def main():
    rows = results()
    for name, ok, ev in rows:
        print("%s  [release] %s%s" % ("PASS" if ok else "FAIL", name, ("\n      " + ev) if ev else ""))
    failed = [n for n, ok, _ in rows if not ok]
    print("%d checks, %d passed, %d failed" % (len(rows), len(rows) - len(failed), len(failed)))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
