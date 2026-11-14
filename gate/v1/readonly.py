"""Shared helpers for the increment-7b read-only gates (MOADIX-native, not a v1 port).

These gates read the committed files of HEAD (an export of `git archive HEAD`) and never
execute or load product code or product tool configuration: each tool gets the gate's own
config, the product's config files are removed from the export, and every tool runs
confined by toolrun (sandbox-exec, writes only into the gate's scratch folder, no network).
"""
import csv
import io
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, HERE)
import toolrun  # noqa: E402
from check_scanners import export_head  # noqa: E402

# Product files that would configure a tool the gate runs: never read (removed from the export).
PRODUCT_TOOL_CONFIG = {".squawk.toml", "zizmor.yml", "zizmor.yaml", "actionlint.yaml", "actionlint.yml",
                       ".vacuum.conf.yaml", "vacuum.conf.yaml", ".spectral.yaml", ".spectral.yml", ".spectral.json",
                       "oasdiff.yaml", "oasdiff-err-ignore.txt"}


def export(root, dest):
    """export_head, then remove the product's own tool configuration. Returns removed paths."""
    removed = export_head(root, dest)
    for d, _dirs, fs in os.walk(dest):
        for f in fs:
            if f in PRODUCT_TOOL_CONFIG:
                p = os.path.join(d, f)
                removed.append(os.path.relpath(p, dest))
                os.unlink(p)
    return removed


def doc_dir():
    """The scope's document folder: sdlc/, or sdlc/features/<id>/ in a feature cycle (MOADIX_FEATURE)."""
    f = os.environ.get("MOADIX_FEATURE") or ""
    return "sdlc/features/%s" % f if f else "sdlc"


def state(root):
    sys.path.insert(0, os.path.dirname(toolrun.GATE))
    from gate import state as st_mod
    st, problems = st_mod.current_state(root)
    if problems:
        raise toolrun.ToolUnavailable("gate state failed its integrity check: %s" % "; ".join(problems))
    return st


def read_csv(path, want_cols):
    """(rows as dicts with lower-case keys, problems). The header must hold want_cols (any order)."""
    try:
        with open(path, encoding="utf-8", newline="") as f:
            text = f.read()
    except OSError:
        return None, ["%s is missing" % path]
    rows = list(csv.reader(io.StringIO(text)))
    rows = [r for r in rows if any(c.strip() for c in r)]
    if not rows:
        return [], ["%s is empty" % path]
    head = [c.strip().lower() for c in rows[0]]
    miss = [c for c in want_cols if c not in head]
    if miss:
        return [], ["%s: header %s lacks column(s) %s" % (path, ",".join(rows[0]), ", ".join(miss))]
    out = []
    for n, r in enumerate(rows[1:], 2):
        d = {head[i]: (r[i].strip() if i < len(r) else "") for i in range(len(head))}
        d["_line"] = n
        out.append(d)
    return out, []


def tracked_at_head(root, rel):
    p = subprocess.run([toolrun.GIT, "-C", root, "cat-file", "-e", "HEAD:%s" % rel], capture_output=True)
    return p.returncode == 0


def git_show(root, commit, rel):
    p = subprocess.run([toolrun.GIT, "-C", root, "show", "%s:%s" % (commit, rel)], capture_output=True)
    return p.stdout if p.returncode == 0 else None


ID_HEAD = re.compile(r"^#{2,4}\s+\**((?:SEC|TH)-\d+)\b", re.M)
ID_LIST = re.compile(r"^\s*[-*]\s+\*\*((?:SEC|TH)-\d+)\b", re.M)


def defined_ids(texts, prefix):
    out = set()
    for t in texts:
        for rx in (ID_HEAD, ID_LIST):
            out |= {m for m in rx.findall(t) if m.startswith(prefix + "-")}
    return out
