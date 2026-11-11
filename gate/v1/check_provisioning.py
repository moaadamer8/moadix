#!/usr/bin/env python3
"""check-provisioning — Phase 6b validator.

Between the UX (6) and the implementation (7) there is a step every real
project takes and no gate ever asked about: deciding what the product needs
from its environment, where each of those values comes from, and who owns them.

Skipping it does not show up as a missing artifact. It shows up months later as
a secret pasted into a config file, an undocumented variable only one laptop
has, or a deploy that fails because nobody wrote down which CI secret feeds
which name.

WHAT IT CHECKS

  1. `.env.example` exists and lists every variable the provisioning document
     declares. It is the checked-in SHAPE of the environment.

  2. `.env.example` CONTAINS NO REAL VALUES. This is the point of the file and
     the thing most often got wrong: an example file with a working key in it
     is a committed secret with a reassuring name. Values must be empty or an
     obvious placeholder, and the gate's own secret patterns are run over it.

  3. Every declared variable is documented in sdlc/06b-provisioning.md with
     what it is for, WHERE THE REAL VALUE COMES FROM (a secret-manager path, a
     CI secret name -- not "ask Dave"), whether it is required, and an owner.

  4. Each required variable EXISTS in the environment.

     WITHOUT READING, PRINTING OR LOGGING ITS VALUE. Presence is tested with
     `name in os.environ`. Emptiness is tested with `len(...) == 0` and nothing
     else: the value is never rendered, never written to any artifact, never
     compared against anything, never passed to a subprocess. That is stated
     precisely rather than absolutely, because len() does touch the string, and
     a check claiming never to touch it while calling len() would be exactly
     the kind of false statement this harness exists to stop.

  5. NO REAL SECRET FILE IS TRACKED BY GIT. `.env`, `*.pem`, `*.key`,
     keystores and service-account JSON are protected_always so an agent cannot
     create one -- but protection is not persistence: a file a human already
     committed stays committed. This asks git directly.

Exit 0 = pass, non-zero = fail.
"""

import argparse
import os
import re
import sys

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, HERE)
import hlib  # noqa: E402

SECRET_FILE_RE = re.compile(
    r"(^|/)(\.env(\.[A-Za-z0-9_-]+)?|[^/]*\.(pem|key|p12|pfx|jks|keystore)"
    r"|id_rsa[^/]*|service-account[^/]*\.json)$")
SECRET_FILE_ALLOW = re.compile(r"(^|/)\.env\.(example|sample|template)$")

PLACEHOLDER_RE = re.compile(
    r"^\s*(|<.*>|\.\.\.|xxx+|changeme|placeholder|your[-_].*|replace[-_]me|"
    r"\$\{[A-Za-z0-9_]+\}|TODO)\s*$", re.I)

VAR_LINE = re.compile(r"^\s*(?:export\s+)?([A-Z][A-Z0-9_]*)\s*=(.*)$")


def read(p):
    if not os.path.exists(p):
        return None
    with open(p, "r", encoding="utf-8", errors="replace") as fh:
        return fh.read()


def parse_env_example(text):
    """{VAR: raw value text} in declaration order."""
    out = {}
    for line in (text or "").splitlines():
        if line.strip().startswith("#"):
            continue
        m = VAR_LINE.match(line)
        if m:
            out[m.group(1)] = m.group(2)
    return out


def parse_declared(text):
    """{VAR: {...}} from | Variable | Purpose | Source of truth | Required | Owner |."""
    out = {}
    for line in (text or "").splitlines():
        line = line.strip()
        if not line.startswith("|") or set(line) <= set("|- :"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 5 or not re.match(r"^[A-Z][A-Z0-9_]*$", cells[0]):
            continue
        out[cells[0]] = {"purpose": cells[1], "source": cells[2],
                         "required": cells[3].lower() in ("yes", "y", "true", "required"),
                         "owner": cells[4]}
    return out


def tracked_secret_files(root):
    """Secret-shaped paths git is carrying. None when git cannot answer."""
    if not hlib.git_available(root):
        return None
    ok, out = hlib._git(root, "ls-files", "-z")
    if not ok:
        return None
    return sorted(p for p in out.split("\0")
                  if p and SECRET_FILE_RE.search(p) and not SECRET_FILE_ALLOW.search(p))


def main():
    ap = argparse.ArgumentParser(prog="check-provisioning.sh", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", default=None, help="sdlc directory (default <governed_root>/sdlc)")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    root = hlib.project_root()
    try:
        groot = (hlib.load_paths_doc(root) or {}).get("governed_root") or ""
    except Exception:
        groot = ""
    governed = os.path.join(root, groot)
    d = args.dir or os.path.join(governed, "sdlc")

    errs, warns, notes = [], [], []
    try:
        doc = hlib.load_phase_doc(root) or {}
        wv = {str(w.get("path")): w for w in hlib.waivers_for(doc, "provisioning")
              if w.get("reason") and w.get("approver")}
    except Exception:
        wv = {}

    prov_path = os.path.join(d, "06b-provisioning.md")
    prov = read(prov_path)
    if prov is None:
        errs.append("provisioning document not found at %s. Phase 6b cannot be approved "
                    "without it: what the product needs from its environment is a design "
                    "decision, not a deployment surprise." % prov_path)
        prov = ""
    declared = parse_declared(prov)
    notes.append("declared variables: %d" % len(declared))

    for name, v in sorted(declared.items()):
        if not v["source"] or v["source"] in ("-", "—", "TBD", "tbd"):
            errs.append("%s names no source of truth. 'Where does the real value come from' "
                        "must be a secret-manager path or a CI secret name -- something a "
                        "second person can act on." % name)
        if not v["owner"] or v["owner"] in ("-", "—"):
            errs.append("%s has no owner." % name)

    ex_path = os.path.join(governed, ".env.example")
    ex = read(ex_path)
    if ex is None:
        errs.append("no .env.example at %s/.env.example. It is the checked-in SHAPE of the "
                    "environment: the list of names, with NEVER a real value." % (groot or "."))
        ex = ""
    example = parse_env_example(ex)

    for name in sorted(set(declared) - set(example)):
        errs.append("%s is declared in the provisioning document but missing from "
                    ".env.example." % name)
    for name in sorted(set(example) - set(declared)):
        errs.append("%s appears in .env.example but is not declared in the provisioning "
                    "document. An undocumented variable is one nobody can provision." % name)

    sys.path.insert(0, HERE)
    try:
        import check_security as csec
        patterns = csec.SECRET_PATTERNS
    except Exception:
        patterns = []
    for name, raw in sorted(example.items()):
        val = raw.strip().strip('"').strip("'")
        if PLACEHOLDER_RE.match(val):
            continue
        # Reported by NAME and SHAPE only. Echoing a suspected secret to make
        # the point would commit the error being reported.
        hit = next((n for n, rx in patterns if rx.search(raw)), None)
        errs.append(".env.example sets %s to a %s value (%d chars%s). An example file with a "
                    "working value in it is a committed secret with a reassuring name. Use an "
                    "empty value or an obvious placeholder."
                    % (name, "secret-shaped" if hit else "non-placeholder", len(val),
                       ", matches %s" % hit if hit else ""))

    for name, v in sorted(declared.items()):
        if not v["required"]:
            continue
        if name in wv:
            warns.append("%s is required and absent from the environment, WAIVED by %s."
                         % (name, wv[name].get("approver")))
            continue
        if name not in os.environ:
            errs.append("required variable %s is not set in this environment. The gate checks "
                        "PRESENCE only -- it never reads, prints or logs the value. Provision "
                        "it, or waive with `gate.sh waive provisioning --path %s`."
                        % (name, name))
        elif len(os.environ[name]) == 0:
            errs.append("required variable %s is set but empty." % name)
        else:
            notes.append("%s: present" % name)

    tracked = tracked_secret_files(root)
    if tracked is None:
        errs.append("git cannot be consulted, so whether a real secret file is committed is "
                    "UNKNOWN. This check exists to answer exactly that; unknown is not a pass.")
    elif tracked:
        for p in tracked:
            errs.append("SECRET FILE TRACKED BY GIT: %s. Remove it from history and rotate "
                        "whatever it held. protected_always stops an agent creating one; it "
                        "cannot un-commit one a human added." % p)
    else:
        notes.append("no secret-shaped file is tracked by git")

    if not args.quiet:
        print("check-provisioning: %s" % prov_path)
        for n in notes:
            print("  note  %s" % n)
        for w in warns:
            print("  WARN  %s" % w)
        for e in errs:
            print("  FAIL  %s" % e)
        if not errs:
            print("  PASS  %d variable(s) declared with a source and an owner, .env.example "
                  "carries names without values, and no secret file is tracked." % len(declared))
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
