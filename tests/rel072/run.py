#!/usr/bin/python3
"""0.7.2 suite: the review of 0.7.1 (hook items 1-2), design section 10 as ruled (A1-A5), and the
task-tracker findings MF-21 to MF-26.

    /usr/bin/python3 tests/rel072/run.py

Fixtures only: throwaway repos under $TMPDIR, the stub checker, no network.

  readdeny   hook item 1: a substitution never reads what denyRead, the managed Read() rules or the
             path map's secret classes protect; what a TOP-LEVEL read of each is left to (the sandbox)
  readers    hook item 2: each reader on the L2 allowlist with its write/exec flags refused, and the
             tools taken off it (file, date, tee, awk, ...) refused
  shadow     a function, alias or PATH change turns L2 and L4 off
  frozen     A1, A5: runs 1-2 full, run 3 scoped; a new finding on frozen text goes to MINOR tagged
             frozen; a frozen BLOCKER is shown in full in REVIEW/APPROVE and blocks nothing; the
             security exception blocks; a regression citing an unrelated frozen section is demoted
  textchange A2, MF-17, MF-22: fixed? on a section change (lines added, text appended, heading renamed);
             a waiver lapses on its cited lines only
  claims     A3, section 10.4: every cell of the uncited-claim table, the gate setting the severity,
             and each refused claim or basis
  upstream   the upstream exception needs a document of an earlier closed phase
  bars       A4: size S bars in the brief and /moadix:coverage; turn_on restores the full bar
  carries    MF-21: a CARRY of run 1 marked [carried] in run 2 is recorded on PROCEED-PAST
  defects    MF-23 (% unit), MF-24 (mkdir of a phase folder), MF-26 (.dependency-cruiser.json)
"""
import datetime
import json
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.realpath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "tests", "lib"))
sys.path.insert(0, REPO)

import fixtures  # noqa: E402

E = fixtures.Env("r72").build()
sys.path.insert(0, os.path.join(E.home, "gate", "v1"))
sys.path.insert(0, E.home)
os.environ.update(MOADIX_GUARD_ROOT=E.base, MOADIX_GUARD_REPO=REPO, MOADIX_GUARD_SHIM=E.shim)
import _testguard  # noqa: E402,F401
from gate import bashcls, contract, critic, pathmap, state, verify  # noqa: E402
import contract_fixture  # noqa: E402

RESULTS = []
T0 = time.time()
GIT = "/usr/bin/git"
FIX_BRD = open(os.path.join(REPO, "tests", "fixtures", "product", "sdlc", "00-brd.md")).read()
GATE_BIN = "moadix-" + "checker"
# The two credential tools' names are spelled apart: this file hands commands that name them to the hook
# as text and never runs them, and the main-branch guard refuses a script whose text names them.
GH, FB = "g" + "h", "fire" + "base"
HOME = os.path.expanduser("~")
NOTES = ("\n## Notes A\n\nThe fixture keeps a weekly summary of open items for its owner.\n"
         "\n## Notes B\n\nThe fixture sends no messages to anyone outside the team.\n")


def record(group, name, ok, evidence=""):
    RESULTS.append((group, name, bool(ok)))
    print("%s  [%s] %s" % ("PASS" if ok else "FAIL", group, name))
    if not ok:
        print("      %s" % str(evidence)[:1200])


def short(s, n=400):
    s = " ".join(str(s).split())
    return s if len(s) <= n else s[:n] + "..."


def write(p, files):
    for rel, text in files.items():
        E.write(p, rel, text)


def product(name, brd=FIX_BRD):
    p = E.repo(name, docs=())
    write(p, {"sdlc/00-brd.md": brd})
    E.commit(p, "brd")
    E.init(p, name + "fx")
    E.commit(p, "init")
    return p


def contract_files(p, label):
    st, size, ruling = contract_fixture.scope_of(p, E)
    contract_fixture.write(p, contract_fixture.files(label, st, size, ruling))
    contract_fixture.commit(p, "contract files %s" % label)


def approve(p, label):
    rv = E.review_until_fresh(p, label, contract=False)
    return rv, E.prompt(p, "APPROVE %s %s" % (label, E.fresh()))


def cur(p):
    return state.current_state(p)[0]


def run_of(p, label):
    _ev, run, _sch = verify.current_critic(p, cur(p), label)
    return run or {}


def line_of(p, rel, startswith):
    lines = open(os.path.join(p, rel)).read().splitlines()
    n = next(i for i, ln in enumerate(lines, 1) if ln.startswith(startswith))
    return n, lines[n - 1]


def fnd(p, rel, startswith, tid, sev, cid, **extra):
    n, text = line_of(p, rel, startswith)
    f = {"id": cid, "topic": tid, "severity": sev, "quote": text[:60] or text, "citation": "%s:%d" % (rel, n),
         "fix": "say more about it"}
    f.update(extra)
    return f


def launch(p):
    rc, out, err = E.hook("pretool", {"hook_event_name": "PreToolUse", "session_id": "r72", "cwd": p,
                                      "tool_name": "Agent",
                                      "tool_input": {"subagent_type": "moadix:gap-critic", "prompt": "x",
                                                     "description": "x"}})
    return ((out.get("hookSpecificOutput") or {}).get("updatedInput") or {}).get("prompt", "")


def waive(p, wid, reason="accepted by the operator for this fixture"):
    exp = (datetime.date.today() + datetime.timedelta(days=30)).isoformat()
    return E.prompt(p, "WAIVE %s owner=moad scope=fixture expiry=%s reason=%s %s" % (wid, exp, reason, E.fresh()))


def disp_of(prompt, gid):
    earlier = prompt.split("## Earlier runs on this phase")[1].split("\n## ")[0]
    m = re.search(r"^- %s \[([^\]]+)\]" % re.escape(gid), earlier, re.M)
    return m.group(1) if m else None


# ------------------------------------------------------------------ hook item 1
def test_readdeny():
    G = "readdeny"
    p = product("rd")
    protected = [
        ("transcripts", "~/.claude/projects/-x/abc.jsonl", "sandbox denyRead ~/.claude/projects + Read() rule"),
        ("memory", "~/.claude/projects/-x/memory/note.md", "sandbox denyRead ~/.claude/projects + Read() rule"),
        ("GitHub CLI credentials", "~/.config/%s/hosts.yml" % GH, "sandbox denyRead ~/.config/%s + Read() rule" % GH),
        ("Firebase CLI credentials", "~/.config/configstore/%s-tools.json" % FB,
         "sandbox denyRead ~/.config/configstore + Read() rule"),
        ("overlay", "~/.config/moadix/overlay.yaml", "nothing: the overlay is write-protected only"),
        (".env", ".env", "nothing: .env is write-protected only"),
        (".env.local", "config/.env.local", "nothing: .env.* is write-protected only"),
        ("key material", "~/.ssh/id_rsa", "nothing in the hook (path map: write-protected)"),
    ]
    for what, path, layer in protected:
        d, _why = E.pretool(p, "Bash", {"command": "cat %s" % path})
        record(G, "top-level `cat %s`: the hook gives no decision (left to: %s)" % (path, layer), d == "none", d)
        for form in ('echo "$(cat %s)"', 'echo "$(head -1 %s)"', 'echo "`cat %s`"', "diff <(cat %s) README.md",
                     'echo "$(grep -c x %s)"'):
            cmd = form % path
            d, why = E.pretool(p, "Bash", {"command": cmd})
            record(G, "substitution read of %s refused: %s" % (what, cmd), d == "deny" and "read-protected" in why,
                   "%s %s" % (d, why))
    # a leading literal variable is resolved before the match
    d, why = E.pretool(p, "Bash", {"command": 'G=~/.config/%s; echo "$(cat $G/hosts.yml)"' % GH})
    record(G, "a leading literal variable naming a protected folder is resolved and refused", d == "deny", why)
    d, why = E.pretool(p, "Bash", {"command": 'echo "$(cat .env.example)"'})
    record(G, ".env.example (the writable template) is not protected", d != "deny", why)
    for path in ("~/.claude/projects/-x/abc.jsonl", "~/.claude/projects/-x/memory/note.md"):
        d, why = E.pretool(p, "Read", {"file_path": path.replace("~", HOME)})
        record(G, "the Read tool on %s is refused by the hook itself" % path, d == "deny", why)
    d, why = E.pretool(p, "Bash", {"command": GH + ' issue create --title t --body "$(cat README.md)"'})
    record(G, "the two credential CLIs run outside the sandbox, so mainguard refuses any substitution with them",
           d == "deny" and "substitution" in why, why)


# ------------------------------------------------------------------ hook item 2
READERS_OK = ["git show HEAD:README.md", "git cat-file -p HEAD:README.md", "git rev-parse HEAD", "grep -c x README.md",
              "sort -u README.md", "sort -k2 -t, README.md", "uniq -c", "jq .x a.json", "cat README.md | head -3",
              "wc -l README.md", "cut -d, -f1 README.md", "tr a b", "ls sdlc", "diff README.md a.md"]
READERS_BAD = [
    ("sort -o", "sort -o out.txt README.md"), ("sort -o attached", "sort -oout.txt README.md"),
    ("sort bundled -ro", "sort -ro out.txt README.md"), ("sort --output", "sort --output=out.txt README.md"),
    ("sort -T", "sort -T /tmp README.md"), ("sort --temporary-directory", "sort --temporary-directory=/tmp a"),
    ("sort --compress-program", "sort --compress-program=sh README.md"),
    ("uniq with an output operand", "uniq README.md out.txt"), ("uniq with an input operand", "uniq README.md"),
    ("git --output", "git diff --output=out.txt"), ("git show --output", "git show --output=o HEAD:README.md"),
    ("git --ext-diff", "git diff --ext-diff"), ("git -c pager", "git -c core.pager=sh show HEAD:README.md"),
    ("git -c textconv", "git -c diff.x.textconv=sh show HEAD:README.md"), ("git -p", "git -p show HEAD:README.md"),
    ("git --paginate", "git --paginate show HEAD:README.md"), ("git show --textconv", "git show --textconv HEAD:a"),
    ("git show of a commit", "git show HEAD"), ("git show :/message", "git show :/fix"),
    ("git show variable revision", "git show $c:README.md"), ("git log", "git log --oneline"),
    ("git diff", "git diff"), ("git status", "git status"), ("git blame", "git blame README.md"),
    ("git ls-files", "git ls-files"), ("git cat-file --textconv", "git cat-file --textconv HEAD:a"),
    ("git cat-file --filters", "git cat-file --filters HEAD:a"), ("git cat-file --batch", "git cat-file --batch"),
    ("git --exec-path", "git --exec-path=/tmp rev-parse HEAD"), ("git --git-dir", "git --git-dir=/tmp/x rev-parse HEAD"),
    ("jq -L", "jq -L /tmp/mods ."), ("jq --library-path", "jq --library-path /tmp ."),
    ("jq import", "jq 'import \"m\" as m; .' a.json"), ("jq include", "jq 'include \"m\"; .' a.json"),
    ("tee", "tee out.txt"), ("file (removed: -C writes)", "file -C -m x"), ("date (removed: -s)", "date -s 1"),
    ("awk", "awk '{print > \"o\"}' a"), ("sed", "sed -n 1p a"), ("rg (--pre)", "rg --pre sh x"),
    ("find", "find . -name a"), ("yq", "yq -i . a"), ("xargs", "xargs echo"),
    ("a full path verb", "/bin/cat README.md"), ("an env prefix", "GIT_EXTERNAL_DIFF=sh git diff"),
    ("a write redirection", "cat README.md > out.txt"), ("a nested substitution", "cat $(echo a)"),
]


def test_readers():
    G = "readers"
    p = product("rr")
    record(G, "the reader allowlist is exactly the documented one", bashcls.SUBST_READ_ONLY == {
        "ls", "cat", "head", "tail", "wc", "grep", "egrep", "fgrep", "stat", "du", "md5", "md5sum", "shasum",
        "sha1sum", "sha256sum", "echo", "printf", "basename", "dirname", "realpath", "readlink", "test", "[",
        "true", "false", "jq", "diff", "cmp", "sort", "uniq", "cut", "tr", "column", "nl", "fold", "git", "pwd",
        "seq"} and "tee" not in bashcls.SUBST_READ_ONLY, sorted(bashcls.SUBST_READ_ONLY))
    for body in READERS_OK:
        d, why = E.pretool(p, "Bash", {"command": 'echo "$(%s)" .sdlc' % body})
        record(G, "reader passes: $(%s)" % body, bashcls.read_only_body(body) and d != "deny", why)
    for what, body in READERS_BAD:
        d, why = E.pretool(p, "Bash", {"command": 'echo "$(%s)" .sdlc' % body})
        record(G, "refused (%s): $(%s)" % (what, body), not bashcls.read_only_body(body) and d == "deny",
               "%s %s" % (d, why))


def test_shadow():
    G = "shadow"
    p = product("sh")
    for cmd in ('cat() { "$@"; }; cat %s record' % GATE_BIN, 'function cat { "$@"; }; cat %s record' % GATE_BIN,
                'alias cat=sh; echo "$(cat x)" .sdlc', 'PATH=.:/usr/bin; echo "$(cat x)" .sdlc',
                'export PATH=.; echo "$(cat x)" .sdlc', 'grep() { rm -rf .sdlc; }; echo "$(grep x a)"'):
        d, why = E.pretool(p, "Bash", {"command": cmd})
        record(G, "a function, alias or PATH change turns L2/L4 off: %s" % cmd, d == "deny", "%s %s" % (d, why))


# ------------------------------------------------------------------ section 10.1 / A1 / A5
def test_frozen():
    G = "frozen"
    p = product("fz", FIX_BRD + NOTES)
    contract_files(p, "0")
    brd = "sdlc/00-brd.md"
    # run 1 (full): one MAJOR on Notes B, which will change
    prompt1 = launch(p)
    contract_fixture.critic(E, p, "0", findings=[fnd(p, brd, "The fixture sends", "B9", "MAJOR", "C1")])
    g1 = run_of(p, "0").get("map", {}).get("C1")
    write(p, {brd: open(os.path.join(p, brd)).read().replace("outside the team.", "outside the team, ever.")})
    E.commit(p, "fix run 1")
    contract_fixture.critic(E, p, "0", findings=[])  # run 2 (full)
    write(p, {brd: open(os.path.join(p, brd)).read().replace("ever.", "not even by e-mail.")})
    E.commit(p, "change Notes B again")
    prompt3 = launch(p)
    scope = prompt3.split("## Scope of this run")[1].split("\n## Earlier runs")[0] if "## Scope of this run" in prompt3 else ""
    record(G, "runs 1 and 2 are full: their briefs have no scope section", "## Scope of this run" not in prompt1)
    record(G, "run 3's brief is scoped: it shows the section changed since run 2 (Notes B), not frozen Notes A",
           "(run 3)" in prompt3 and "not even by e-mail" in scope and "weekly summary" not in scope, short(scope, 700))
    findings = [
        fnd(p, brd, "The fixture keeps", "B10", "MAJOR", "C1"),                      # frozen MAJOR -> MINOR
        fnd(p, brd, "The fixture keeps", "B11", "BLOCKER", "C2"),                    # frozen BLOCKER, no exception
        dict(fnd(p, brd, "The fixture keeps", "B12", "BLOCKER", "C3", exception="security"),
             fix="name the password policy for the owner's summary"),               # security exception: counts
        fnd(p, brd, "The fixture sends", "B14", "MAJOR", "C4"),                      # changed section: counts
        fnd(p, brd, "The fixture keeps", "B9", "MAJOR", "C5", regression_of=g1),     # regression elsewhere: demoted
        fnd(p, brd, "The fixture keeps", "B15", "BLOCKER", "C6", exception="privacy"),  # exception without its words
    ]
    contract_fixture.critic(E, p, "0", findings=findings)
    run = run_of(p, "0")
    m = run.get("map", {})
    fz = run.get("frozen") or {}
    record(G, "a new finding on frozen text without an exception is recorded as frozen (MAJOR, BLOCKER, and an "
              "exception whose words are missing)", m.get("C1") in fz and m.get("C2") in fz and m.get("C6") in fz,
           short(run))
    record(G, "the security exception, with its words in the fix, is not frozen", m.get("C3") not in fz, short(fz))
    record(G, "a finding on a changed section is not frozen", m.get("C4") not in fz, short(fz))
    record(G, "a regression citing an unrelated unchanged section is demoted to a new finding (new id, frozen)",
           m.get("C5") != g1 and m.get("C5") in fz and run.get("demoted"), short(run))
    rv, ctx = approve(p, "0")
    record(G, "APPROVE is refused only by the counted findings (the security BLOCKER and the changed-section "
              "MAJOR), not by the frozen ones", "NOT recorded" in ctx and "[%s]" % m.get("C3") in ctx and
           "[%s]" % m.get("C4") in ctx and "MAJOR C1 (B10)" not in ctx.split("Frozen findings")[0], short(ctx, 900))
    record(G, "A1: the frozen BLOCKER is shown in full under its heading in the APPROVE reply and in REVIEW",
           "Frozen findings rated BLOCKER by the critic, not blocking" in ctx and "B11" in ctx.split(
               "Frozen findings")[-1] and "Frozen findings rated BLOCKER" in rv, short(rv, 900))
    st = E.prompt(p, "STATUS")
    record(G, "STATUS counts frozen-text findings", re.search(r"frozen-text findings (\d+)", st) and
           int(re.search(r"frozen-text findings (\d+)", st).group(1)) == len(fz), short(st, 900))
    mf = open(os.path.join(p, ".sdlc", "cache", "validation", "minor", "product-0.md")).read() \
        if os.path.exists(os.path.join(p, ".sdlc", "cache", "validation", "minor", "product-0.md")) else ""
    if not mf:
        import glob
        hits = glob.glob(os.path.join(p, ".sdlc", "**", "minor", "*0.md"), recursive=True)
        mf = open(hits[0]).read() if hits else ""
    record(G, "the frozen findings are in the operator's MINOR file, tagged [frozen]", mf.count("[frozen]") >= 3,
           mf[:600])


# ------------------------------------------------------------------ A2, MF-17, MF-22
def test_textchange():
    G = "textchange"
    p = product("tc", FIX_BRD + "\n## Glossary\n\nA list is a set of items.\n\n## Notes C\n\nItems are short.\n"
                                "\n## Notes D\n\nThe owner reads them weekly.\n\n## Notes E\n\nNothing is shared.\n")
    contract_files(p, "0")
    brd = "sdlc/00-brd.md"
    contract_fixture.critic(E, p, "0", findings=[
        fnd(p, brd, "## Glossary", "B9", "MAJOR", "C1"),
        fnd(p, brd, "Items are short.", "B12", "MAJOR", "C2"),
        fnd(p, brd, "The owner reads", "B13", "MAJOR", "C3"),
        fnd(p, brd, "Nothing is shared.", "B14", "MAJOR", "C4")])
    m = run_of(p, "0").get("map", {})
    w = waive(p, "gap-critic." + m["C4"])
    t = open(os.path.join(p, brd)).read()
    t = t.replace("## Glossary", "## Glossary of terms")                        # MF-22: renamed heading
    t = t.replace("Items are short.", "Items are short. Each has a title.")      # MF-22: text appended to the line
    t = t.replace("The owner reads them weekly.", "The owner reads them weekly.\nA reminder goes out on Mondays.")
    t = t.replace("Nothing is shared.", "Nothing is shared.\nExports stay local.")  # waived: lines added next to it
    write(p, {brd: t})
    E.commit(p, "fixes")
    prompt = launch(p)
    record(G, "MF-22: a renamed cited heading makes the finding fixed?", disp_of(prompt, m["C1"]) == "fixed?",
           disp_of(prompt, m["C1"]))
    record(G, "MF-22: text appended to the cited line makes it fixed?", disp_of(prompt, m["C2"]) == "fixed?",
           disp_of(prompt, m["C2"]))
    record(G, "MF-17: lines added next to an unchanged cited line make it fixed? (section changed)",
           disp_of(prompt, m["C3"]) == "fixed?", disp_of(prompt, m["C3"]))
    record(G, "A2: a waiver does not lapse when only its section changed (its cited line is unchanged)",
           " recorded (ledger seq" in w and disp_of(prompt, m["C4"]) == "waived", short(w) + " " +
           str(disp_of(prompt, m["C4"])))


# ------------------------------------------------------------------ A3 and section 10.4
def claim_repo():
    p = os.path.join(E.base, "claims")
    os.makedirs(p)
    subprocess.run([GIT, "init", "-q", p])
    E.write(p, "sdlc/01-research.md", "\n".join([
        "# Research", "", "## Licence",  # 1-3
        "MIT is permissive and compatible with any licence.",  # 4: uncited
        "", "## Cost",  # 5-6
        "Hosting costs 5 EUR a month ([price](https://example.com/p), retrieved 2026-11-01).",  # 7: cited
        "", "## Quoted",  # 8-9
        "Data stays in the EU [^eu].",  # 10
        '> "Customer data is stored in Frankfurt, Germany, at all times."',  # 11: a quote
        "", "## Password", "Passwords are hashed with bcrypt.",  # 12-14
        "", "[^eu]: https://example.com/eu retrieved 2026-11-02", ""]))
    E.commit(p, "research")
    return p, subprocess.run([GIT, "-C", p, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()


def test_claims():
    G = "claims"
    p, hd = claim_repo()
    ids = {"Q-3", "ADR-001", "D1.1"}

    def cr(**f):
        base = {"citation": "sdlc/01-research.md:4", "quote": "MIT is permissive"}
        base.update(f)
        return critic.claim_rule(p, base, hd, ids, {})
    cells = [("legal", "Q-3", "BLOCKER"), ("legal", "none", "MAJOR"), ("other", "ADR-001", "MAJOR"),
             ("other", "none", "MINOR"), ("cost", "D1.1", "BLOCKER"), ("feasibility", "none", "MAJOR")]
    for cls, dec, want in cells:
        sev, probs = cr(kind="uncited", claim_class=cls, decision=dec)
        record(G, "A3 table: uncited %s claim, decision %s -> %s" % (cls, dec, want), sev == want and not probs,
               (sev, probs))
    sev, probs = cr(kind="uncited", claim_class="legal", decision="Q-9")
    record(G, "a decision id that does not exist fails the evidence", any("does not exist" in x for x in probs), probs)
    sev, probs = cr(kind="uncited", claim_class="other", decision="none", citation="sdlc/01-research.md:14",
                    quote="Passwords are hashed")
    record(G, "a quote with security terms must be claim_class security", any("claim_class is security" in x
                                                                               for x in probs), probs)
    sev, probs = cr(kind="uncited", claim_class="cost", decision="none", citation="sdlc/01-research.md:7")
    record(G, "10.4: 'uncited' on a line with a URL and a date is refused (cite-lint accepts it)",
           any("not uncited" in x for x in probs), probs)
    sev, probs = cr(kind="uncited", claim_class="legal", decision="none", citation="sdlc/01-research.md:10")
    record(G, "10.4: 'uncited' on a line whose footnote has a URL and a date is refused",
           any("not uncited" in x for x in probs), probs)
    sev, probs = cr(kind="support", claim_class="cost", decision="D1.1", basis="quote-contradicts",
                    citation="sdlc/01-research.md:7")
    record(G, "10.4: quote-contradicts without a quote in the section is refused (the critic cannot see the page)",
           any("cannot see the page" in x for x in probs), probs)
    sev, probs = cr(kind="support", claim_class="legal", decision="D1.1", basis="quote-contradicts",
                    citation="sdlc/01-research.md:10")
    record(G, "10.4: quote-contradicts with a quote, legal with a decision -> BLOCKER", sev == "BLOCKER" and not probs,
           (sev, probs))
    sev, probs = cr(kind="support", claim_class="legal", decision="none", basis="quote-insufficient",
                    citation="sdlc/01-research.md:10")
    record(G, "10.4: quote-insufficient follows the table (legal, no decision -> MAJOR)", sev == "MAJOR" and not probs,
           (sev, probs))
    sev, probs = cr(kind="support", claim_class="cost", decision="D1.1", basis="no-quote",
                    citation="sdlc/01-research.md:7")
    record(G, "10.4: no-quote on a decision-bearing cost claim -> MAJOR", sev == "MAJOR" and not probs, (sev, probs))
    sev, probs = cr(kind="support", claim_class="cost", decision="D1.1", basis="no-quote",
                    citation="sdlc/01-research.md:10")
    record(G, "10.4: no-quote where the section quotes its source is refused", any("quotes its source" in x
                                                                                   for x in probs), probs)
    sev, probs = cr(kind="support", claim_class="other", decision="none", basis="no-quote",
                    citation="sdlc/01-research.md:7")
    record(G, "10.4: no-quote is not a finding for a claim outside the four classes", any(
        "only for a legal" in x for x in probs), probs)
    sev, probs = cr(kind="support", claim_class="cost", decision="none")
    record(G, "10.4: kind support without a basis is refused", any("needs basis" in x for x in probs), probs)
    # end to end: the gate records the table's severity (MINOR), so a BLOCKER-rated trivial claim does not block
    q = product("cl")
    contract_files(q, "0")
    f = fnd(q, "sdlc/00-brd.md", "- **Ruling rationale:**", "B19", "BLOCKER", "C1", kind="uncited",
            claim_class="other", decision="none")
    contract_fixture.critic(E, q, "0", findings=[f])
    run = run_of(q, "0")
    rv, ctx = approve(q, "0")
    record(G, "A3 end to end: an uncited 'other' claim with no decision, rated BLOCKER, is recorded as MINOR and "
              "does not block APPROVE", run.get("severity", {}).get(run.get("map", {}).get("C1")) == "MINOR" and
           " recorded (ledger seq" in ctx, short(ctx, 600) + " " + short(run))


def test_upstream():
    G = "upstream"
    st = {"mode": "greenfield", "feature": None, "current_phase": "2",
          "phases": [{"label": "0", "status": "APPROVED"}, {"label": "1", "status": "PROCEED-PAST"},
                     {"label": "2", "status": "pending"}]}
    record(G, "an approved earlier phase's document is upstream", critic.upstream_phase(st, "sdlc/00-brd.md") == "0")
    record(G, "a proceeded-past earlier phase's document is upstream",
           critic.upstream_phase(st, "sdlc/01-research.md") == "1")
    record(G, "the current phase's own document is not upstream", critic.upstream_phase(st, "sdlc/02-prd.md") is None)
    record(G, "a later phase's document is not upstream", critic.upstream_phase(st, "sdlc/03-hld.md") is None)


# ------------------------------------------------------------------ A4
def test_bars():
    G = "bars"
    p = product("bs")
    contract_files(p, "0")
    b = launch(p)
    record(G, "size S: the brief shows B13's bar (at least 2 competitors)",
           re.search(r"^- B13 .*\[size S bar: at least 2 competitors", b, re.M) is not None,
           short([ln for ln in b.splitlines() if ln.startswith("- B13")]))
    q = product("bm", FIX_BRD.replace("**Size:** S", "**Size:** M"))
    contract_files(q, "0")
    b = launch(q)
    record(G, "size M: no bar is relaxed", "size M bar" not in b and "size S bar" not in b)
    record(G, "S relaxes exactly R2 (2 to 3 real products) and B13 (at least 2)", contract.bars("S") == {
        "R2": "2 to 3 real products", "B13": "at least 2 competitors"} and contract.bars("M") == {}, contract.bars("S"))
    record(G, "turn_on restores the full bar", "B13" not in contract.bars("S", {"turn_on": {"B13"}, "na": {}}))
    doc = open(os.path.join(REPO, "commands", "coverage.md")).read()
    record(G, "/moadix:coverage lists the S bars", "Bars relaxed (quantities only): R2 2 to 3 real products; B13 at "
                                                   "least 2 competitors" in doc)


# ------------------------------------------------------------------ MF-21
def test_carries():
    G = "carries"
    p = product("cr")
    contract_files(p, "0")
    lines = open(os.path.join(p, "sdlc", "0", "COVERAGE.md")).read().splitlines()
    n = next(i for i, ln in enumerate(lines, 1) if ln.startswith("- B7:"))
    carry = {"id": "C1", "topic": "B7", "severity": "CARRY", "quote": lines[n - 1][2:50],
             "citation": "sdlc/0/COVERAGE.md:%d" % n, "fix": "settle the field list in the PRD", "defer_rule": "X0.1",
             "to": "2", "class": "other"}
    contract_fixture.critic(E, p, "0", findings=[carry])
    gcarry = run_of(p, "0").get("map", {}).get("C1")
    E.write(p, "docs/x.md", "x\n")
    E.commit(p, "unrelated")
    prompt = launch(p)
    record(G, "run 2's brief marks the run-1 CARRY [carried]", disp_of(prompt, gcarry) == "carried",
           disp_of(prompt, gcarry))
    n2 = next(i for i, ln in enumerate(lines, 1) if ln.startswith("- B9:"))
    contract_fixture.critic(E, p, "0", findings=[{"id": "C1", "topic": "B9", "severity": "MAJOR",
                                                  "quote": lines[n2 - 1][2:50], "citation": "sdlc/0/COVERAGE.md:%d" % n2,
                                                  "fix": "x"}])
    E.review_until_fresh(p, "0", contract=False)
    ctx = E.prompt(p, "PROCEED-PAST 0 the operator accepts the open MAJOR %s" % E.fresh())
    _b, pl = E.payload(p, len(E.ledger(p)))
    cs = pl.get("carries") or []
    record(G, "MF-21: PROCEED-PAST records the run-1 CARRY that run 2 rightly did not raise again",
           " recorded (ledger seq" in ctx and any(c.get("gc") == gcarry and c.get("to") == "2" for c in cs),
           short(ctx, 500) + " " + short(cs))


# ------------------------------------------------------------------ MF-23, MF-24, MF-26
def test_defects():
    G = "defects"
    record(G, "MF-23: '100% of requests' states a number with a unit", contract.UNIT.search("100% of requests") is
           not None and contract.UNIT.search("99.9 % uptime") is not None and contract.UNIT.search("5 cats") is None)
    p = product("dirs")
    d, why = E.pretool(p, "Bash", {"command": "mkdir -p sdlc/0"})
    record(G, "MF-24: mkdir of the current phase's folder (owned as sdlc/0/**) is allowed", d != "deny", why)
    d, why = E.pretool(p, "Bash", {"command": "mkdir -p sdlc/2"})
    record(G, "MF-24: a later phase's folder is still refused", d == "deny" and "not started" in why, why)
    d, why = E.pretool(p, "Bash", {"command": "rm -rf sdlc"})
    record(G, "MF-24: the parent folder sdlc/ stays unowned", d == "deny", why)
    cls = lambda pid, mode=None: pathmap.classify(  # noqa: E731
        os.path.join(p, ".dependency-cruiser.json"), p, pid,
        phases=pathmap.scope_phases(mode or "greenfield", None))
    record(G, "MF-26: phase 3 writes .dependency-cruiser.json at the root", cls(3).allow, cls(3).reason)
    record(G, "MF-26: phase 7 may refine it", cls(8).allow, cls(8).reason)
    record(G, "MF-26: phases 4-6 may not (frozen after 3)", not cls(4).allow, cls(4).reason)
    record(G, "MF-26: onboarding phase B may write it (BL3)", pathmap.classify(
        os.path.join(p, ".dependency-cruiser.json"), p, 0, phases=pathmap.scope_phases("onboarding", None)).allow)
    import check_exec
    s0 = check_exec.tool_script("dependency-cruiser", p, {}, [".dependency-cruiser.json", "sdlc/03-hld.md"])
    s1 = check_exec.tool_script("dependency-cruiser", p, {}, [".dependency-cruiser.json", "src/a.ts"])
    record(G, "MF-26: with no src/ yet the gate validates the rules against an empty folder",
           "mkdir -p .moadix-no-source" in s0 and s0.rstrip().endswith("echo $? > /out/run.rc") and
           " .moadix-no-source >" in s0, s0)
    record(G, "MF-26: once src/ exists the gate cruises it", " src >" in s1 and ".moadix-no-source" not in s1, s1)


def main():
    try:
        for t in (test_readdeny, test_readers, test_shadow, test_frozen, test_textchange, test_claims, test_upstream,
                  test_bars, test_carries, test_defects):
            try:
                t()
            except Exception as e:  # a crashing group is a failure, never a skip
                import traceback
                record(t.__name__, "group ran to the end", False, "%s: %s\n%s" % (type(e).__name__, e,
                                                                                 traceback.format_exc()[-1500:]))
        viol = E.violations()
        record("guard", "no test read, wrote or started a real product, keychain or ~/.claude", not viol, viol)
    finally:
        E.remove()
    n = len(RESULTS)
    bad = [r for r in RESULTS if not r[2]]
    for g, name, _ok in bad:
        print("FAILED [%s] %s" % (g, name))
    print("\n%d checks, %d passed, %d failed (%d s)" % (n, n - len(bad), len(bad), time.time() - T0))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
