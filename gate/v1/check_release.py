#!/usr/bin/env python3
"""check-release -- phase 11: a release-please release PR a human merged, green CI,
no open high/critical code-scanning alert (increment 5; MOADIX-native).

Release flow: release-please (pinned 17.11.2 for the agent's CLI use; in CI the
googleapis/release-please-action pinned to a commit SHA) opens a release PR;
a HUMAN merges it. The gate never merges, tags or pushes.

Local, at HEAD:
  * release-please-config.json and .release-please-manifest.json are committed
    and parse; the config names at least one package.
  * every workflow that uses googleapis/release-please-action pins it to a full
    commit SHA (a tag can be moved).

From GitHub, read by the GATE through the pinned github-mcp-server started with
--read-only (the gate is the MCP client; it refuses to read anything if the
server lists a single write tool, so a server without --read-only fails closed):
  * HEAD is a commit on GitHub;
  * HEAD is the merge commit of a release-please PR (head branch
    release-please--*), merged, and merged by a human (not a bot);
  * every workflow run for HEAD completed and none failed (at least one ran);
  * no open code-scanning alert at critical or high.
Token: a read-only GitHub token from the login Keychain (service
moadix-github-readonly, set by the operator; see docs/INSTALL.md). No token is
UNKNOWN, never a pass.

Exit 0 pass, 1 fail, 2 UNKNOWN (no token, server unreachable).
"""
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, HERE)
import hlib  # noqa: E402
import mcpclient  # noqa: E402
import toolrun  # noqa: E402

PHASE = "11"
READ_ONLY_ARGS = ["stdio", "--read-only", "--toolsets", "repos,pull_requests,actions,code_security"]
WRITE_TOOL = re.compile(r"^(create|update|delete|merge|push|fork|add|remove|request|submit|dismiss|rerun|cancel|"
                        r"run|trigger|assign|set|lock|unlock|close|reopen|mark)_|_(write|trigger|create|update|"
                        r"delete)$")
ACTION = re.compile(r"googleapis/release-please-action@(\S+)")


def show(root, rel):
    p = subprocess.run([toolrun.GIT, "-C", root, "show", "HEAD:" + rel], capture_output=True)
    return p.stdout.decode("utf-8", "replace") if p.returncode == 0 else None


def local_checks(root, errs, notes):
    for rel in ("release-please-config.json", ".release-please-manifest.json"):
        text = show(root, rel)
        if text is None:
            errs.append("%s is not committed at HEAD (release-please needs it)" % rel)
            continue
        try:
            doc = json.loads(text)
        except ValueError as e:
            errs.append("%s does not parse: %s" % (rel, e))
            continue
        if rel == "release-please-config.json" and not (doc.get("packages") or {}):
            errs.append("release-please-config.json names no packages")
        if rel == ".release-please-manifest.json":
            notes.append("release-please manifest: %s" % ", ".join("%s=%s" % kv for kv in sorted(doc.items())))
    pinned = 0
    for wf in toolrun.tracked(root, ".github/workflows/*.yml", ".github/workflows/*.yaml"):
        for m in ACTION.finditer(show(root, wf) or ""):
            ref = m.group(1)
            if not re.match(r"^[0-9a-f]{40}$", ref):
                errs.append("%s uses googleapis/release-please-action@%s: pin it to a full commit SHA" % (wf, ref))
            else:
                pinned += 1
    notes.append("release-please-action pinned by SHA in %d workflow step(s)" % pinned)


def token():
    """The operator's read-only GitHub token, read by the gate from the login Keychain
    (toolrun.github_token: never PATH, never env)."""
    return toolrun.github_token()


def repo_of(root):
    r = str((toolrun.product_tools(root).get("release") or {}).get("repo") or "")
    if not r:
        p = subprocess.run([toolrun.GIT, "-C", root, "remote", "get-url", "origin"], capture_output=True, text=True)
        m = re.search(r"github\.com[:/]([^/]+)/([^/]+?)(?:\.git)?$", p.stdout.strip())
        r = "%s/%s" % m.groups() if m else ""
    return r if re.match(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", r) else None


def items(x, *keys):
    """A list from a tool result that is a list or wraps one under one of `keys`."""
    if isinstance(x, list):
        return x
    for k in keys:
        if isinstance(x, dict) and isinstance(x.get(k), list):
            return x[k]
    return []


def remote_checks(root, head, errs, notes, unknown, record):
    repo = repo_of(root)
    if not repo:
        unknown.append("no GitHub repository: set release.repo in .sdlc/config/product-tools.yaml or an origin "
                       "remote on github.com")
        return
    owner, name = repo.split("/")
    tok = token()
    if not tok:
        unknown.append("no read-only GitHub token in the login Keychain (service moadix-github-readonly); the "
                       "gate cannot read CI or code scanning, and that is UNKNOWN, not a pass")
        return
    try:
        argv, pin = toolrun.argv_for("github-mcp-server", READ_ONLY_ARGS)
    except toolrun.ToolUnavailable as e:
        unknown.append(str(e))
        return
    scratch = toolrun.mkdtemp("moadix-gh-")
    env = {"PATH": "/usr/bin:/bin", "HOME": scratch, "GITHUB_PERSONAL_ACCESS_TOKEN": tok,
           "SSL_CERT_FILE": "/etc/ssl/cert.pem"}
    c = mcpclient.Client(argv, env, cwd=scratch, timeout=90)
    try:
        c.start()
        names = sorted(t.get("name") for t in c.tools())
        writes = [n for n in names if WRITE_TOOL.search(n)]
        if writes:
            errs.append("the GitHub MCP server offers write tools (%s): it is not in --read-only mode, so the gate "
                        "reads nothing from it" % ", ".join(writes[:6]))
            return
        record["server_tools"] = names
        commit = c.tool("get_commit", {"owner": owner, "repo": name, "sha": head})
        if not commit or (isinstance(commit, dict) and str(commit.get("sha") or "")[:12] != head[:12]):
            errs.append("HEAD %s is not a commit on github.com/%s (push it, and release from the merged PR)" % (
                head[:12], repo))
            return
        prs = items(c.tool("search_pull_requests", {"query": "repo:%s is:pr is:merged %s" % (repo, head)}),
                    "items", "pull_requests")
        rel = None
        for pr in prs:
            num = pr.get("number")
            full = c.tool("pull_request_read", {"method": "get", "owner": owner, "repo": name, "pullNumber": num})
            if isinstance(full, dict) and str(full.get("merge_commit_sha") or "") == head:
                rel = full
                break
        if not rel:
            errs.append("HEAD %s is not the merge commit of a pull request: a release lands by merging the "
                        "release-please PR" % head[:12])
        else:
            branch = str(((rel.get("head") or {}).get("ref")) or "")
            mb = rel.get("merged_by") or {}
            login = str(mb.get("login") or "")
            record["release_pr"] = {"number": rel.get("number"), "branch": branch, "merged_by": login,
                                    "merged_by_type": mb.get("type")}
            if not branch.startswith("release-please--"):
                errs.append("PR #%s (branch %s) is not a release-please release PR" % (rel.get("number"), branch))
            if not rel.get("merged"):
                errs.append("PR #%s is not merged" % rel.get("number"))
            if not login or str(mb.get("type") or "") == "Bot" or login.endswith("[bot]"):
                errs.append("PR #%s was merged by %r, not by a human: the release PR is merged by a person" % (
                    rel.get("number"), login or "nobody"))
            else:
                notes.append("release PR #%s (%s) merged by %s" % (rel.get("number"), branch, login))
        # actions_list has no head_sha filter (2.0.3: actor, branch, event, status): list the
        # latest runs and keep those for HEAD.
        runs = [r for r in items(c.tool("actions_list", {"method": "list_workflow_runs", "owner": owner,
                                                         "repo": name, "perPage": 100}), "workflow_runs")
                if str(r.get("head_sha") or "") == head]
        record["workflow_runs"] = [{"name": r.get("name"), "status": r.get("status"),
                                    "conclusion": r.get("conclusion")} for r in runs]
        if not runs:
            errs.append("no CI workflow run for HEAD %s" % head[:12])
        for r in runs:
            if r.get("status") != "completed":
                errs.append("CI run %r for HEAD is %s, not completed" % (r.get("name"), r.get("status")))
            elif r.get("conclusion") not in ("success", "skipped", "neutral"):
                errs.append("CI run %r for HEAD concluded %s" % (r.get("name"), r.get("conclusion")))
        alerts = items(c.tool("list_code_scanning_alerts", {"owner": owner, "repo": name, "state": "open"}),
                       "alerts")
        bad = []
        for a in alerts:
            rule = a.get("rule") or {}
            sev = str(rule.get("security_severity_level") or rule.get("severity") or "").lower()
            if sev in ("critical", "high", "error"):
                bad.append("#%s %s (%s)" % (a.get("number"), rule.get("id") or rule.get("name"), sev))
        record["open_alerts"] = len(alerts)
        for b in bad:
            errs.append("open code-scanning alert %s" % b)
        notes.append("GitHub %s: %d CI run(s) for HEAD, %d open code-scanning alert(s), %d at high/critical "
                     "(read through github-mcp-server %s --read-only)" % (repo, len(runs), len(alerts), len(bad),
                                                                          pin["version"]))
    except mcpclient.MCPError as e:
        unknown.append("the GitHub MCP server could not answer: %s" % e)
    finally:
        c.close()


def main():
    root = hlib.project_root()
    notes, errs, unknown = [], [], []
    head = toolrun.head(root)
    record = {"head": head}
    local_checks(root, errs, notes)
    remote_checks(root, head, errs, notes, unknown, record)
    record.update({"errors": errs, "unknown": unknown})
    rel, digest = toolrun.record(root, PHASE, "github-mcp-server", "read-only", "release-check.json",
                                 json.dumps(record, indent=1, sort_keys=True), "check-release")
    notes.append("evidence %s (sha256 %s)" % (rel, digest[:12]))
    return toolrun.report("check-release (phase 11, release-please + GitHub read-only)", notes, [], errs, unknown)


if __name__ == "__main__":
    sys.exit(main())
