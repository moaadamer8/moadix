#!/usr/bin/env python3
"""check-surface-coverage — the shipped surface must be a subset of the designed one.

THE GAP THIS CLOSES (Gap 4, the R3 feature-creep control)

  10a verifies every PRD STORY. That is a different set from every surface the
  product SHIPS. A route nobody wrote a story for is verified by nothing and
  reported by nothing, and the diff between the two sets was uncomputable
  because the shipped set was never enumerated.

THE MEASUREMENT THAT DECIDED THE DESIGN

  Static extraction of toy-product's server and live probing through the front
  door returned THE SAME THREE routes. Neither found anything the other missed,
  so the measurement did not license building both.

  What it did surface is sharper: **probing cannot enumerate.** An HTTP server
  has no "list your routes" endpoint, so probing is a membership test over a
  GUESSED set. The ten paths probed were chosen by reading the code first, which
  makes the agreement between the two methods partly circular -- and a route at
  /admin/debug would have returned nothing, because nobody asked.

  So the roles are: **the declared enumerator enumerates; probing filters for
  reachability.** A route that is neither enumerated nor guessed is invisible to
  both, and that class is reported as UNKNOWN, never as absent.

THREE STATES, NOT TWO

  never declared     -> UNKNOWN. The check could not run. Not a pass.
  declared as `none` -> NOT-APPLICABLE, with the product's stated reason.
  declared and ran   -> a set, which may legitimately be empty, and says so.

WHAT THIS CHECK DOES NOT ESTABLISH

  That the enumerator reported everything. It is the product's own account of
  itself; under-reporting is invisible here by construction, because there is no
  independent enumeration to diff against. `cannot_see` in the config is where
  that limit is made product-specific rather than a generic disclaimer, and it
  is printed on every run.

Usage: harness/bin/check-surface-coverage.sh [--quiet] [--no-probe]
Exit 0 = clean · 1 = findings · 2 = cannot evaluate.
"""

import argparse
import contextlib
import os
import re
import ssl
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, HERE)
import hlib  # noqa: E402

# MOADIX v2 (increment 5 fix): the PRODUCT repo. The port kept v1's "two levels above
# this file", which in v2 is MOADIX's own home, so the product's .sdlc/config was never read.
ROOT = os.environ.get("HARNESS_ROOT") or (hlib.project_root() if os.environ.get("MOADIX_PRODUCT_ROOT") else
                                         os.path.realpath(os.path.join(HERE, "..", "..")))

SURFACE_RE = re.compile(r"^([A-Z]+)\s+(/\S*)\s*$")


def parse_surface_lines(text):
    """[(METHOD, path)] from an enumerator's stdout, ignoring blanks/comments."""
    out = []
    for line in (text or "").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = SURFACE_RE.match(line)
        if m:
            out.append((m.group(1).upper(), m.group(2)))
    return out


def contract_surface(path):
    """[(METHOD, path)] declared by an OpenAPI document.

    Deliberately a small reader rather than a schema validator: check-lld
    already validates the document, and this needs only its path/method pairs.
    """
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            lines = fh.read().splitlines()
    except OSError:
        return None
    out, cur, in_paths = [], None, False
    for line in lines:
        if re.match(r"^paths:\s*$", line):
            in_paths = True
            continue
        if in_paths and re.match(r"^\S", line):
            in_paths = False
        if not in_paths:
            continue
        m = re.match(r"^  (/\S*):\s*$", line)
        if m:
            cur = m.group(1)
            continue
        m = re.match(r"^    (get|post|put|patch|delete|head|options):\s*$", line)
        if m and cur:
            out.append((m.group(1).upper(), cur))
    return out


def run_enumerator(root, groot, spec):
    """(state, surfaces, detail). state in declared|none|missing|failed."""
    if not isinstance(spec, dict):
        return "missing", [], "no declaration"
    method = str(spec.get("method") or "").strip()
    if method == "none":
        reason = str(spec.get("reason") or "").strip()
        owner = str(spec.get("owner") or "").strip()
        if not reason:
            return "failed", [], ("declared `method: none` with no reason. "
                                  "An N/A without a reason is indistinguishable "
                                  "from an omission (6.3)")
        if not owner:
            return "failed", [], (
                "declared `method: none` with no owner. `registered:` needs a "
                "named owner to put ONE surface outside the contract; declaring "
                "the WHOLE surface unenumerable is the larger claim and cannot "
                "need less. Without it a product makes its entire API invisible "
                "to this check with a sentence nobody signed")
        return "none", [], "%s (owner: %s)" % (reason, owner)
    if method != "command":
        return "missing", [], "method %r is not `command` or `none`" % method
    argv = spec.get("command")
    if not isinstance(argv, list) or not argv:
        return "failed", [], "`command` must be a non-empty argv list"
    wd = os.path.join(root, groot)
    # P27. This command is the PRODUCT'S, and it imports the product's own
    # source -- a phase-7 deliverable the agent writes. A top-level side effect
    # in it wrote into harness/status/ while this check ran, and this check
    # never saw it, because the hook governs the agent's tool calls and not a
    # subprocess a validator spawns. Confined now; the failure to confine is
    # fatal rather than degrading (3.10).
    import tempfile
    try:
        import sandbox
        with tempfile.NamedTemporaryFile("w", suffix=".sb", delete=False) as _pf:
            prof = _pf.name
        argv = sandbox.wrap(root, [str(a) for a in argv], prof)
    except RuntimeError as exc:
        return "failed", [], str(exc)
    except Exception as exc:                                    # noqa: BLE001
        return "failed", [], ("the sandbox could not be prepared (%r). The "
                              "enumerator is product code and is not run "
                              "unconfined." % (exc,))
    try:
        p = subprocess.run([str(a) for a in argv], cwd=wd, capture_output=True,
                           text=True, timeout=120)
    except Exception as exc:                                    # noqa: BLE001
        return "failed", [], "enumerator did not run: %r" % (exc,)
    finally:
        with contextlib.suppress(OSError):
            os.unlink(prof)
    if p.returncode != 0:
        return "failed", [], ("enumerator exited %d: %s"
                              % (p.returncode, (p.stderr or "").strip()[:200]))
    return "declared", parse_surface_lines(p.stdout), ""


ALLOWED_SCHEMES = ("http", "https")
LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "[::1]", "::1")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    # A redirect is not reachability, and following one would bypass the
    # loopback guard in probe(), which checks only the first URL.
    def redirect_request(self, *args, **kwargs):
        return None


def probe(url, method, path, timeout=3, host=None, cafile=None):
    """(reachable, code). A transport failure is UNKNOWN, not unreachable.

    The scheme and host are checked before opening anything. ruff flagged the
    bare urlopen (S310) and it was right: the URL comes from the front door
    config, and a file: or custom scheme there would turn a reachability probe
    into an arbitrary read. The front door already promises loopback, so this
    ASSERTS the promise rather than trusting it -- and refuses rather than
    guessing, which makes an unexpected URL UNKNOWN instead of a silent probe of
    something else.
    """
    target = url.rstrip("/") + path
    parsed = urllib.parse.urlsplit(target)
    if parsed.scheme not in ALLOWED_SCHEMES:
        return None, None
    if (parsed.hostname or "") not in LOOPBACK_HOSTS:
        return None, None
    # noqa justified by the scheme and host guards immediately above:
    # this cannot reach a file: URL or a non-loopback host.
    req = urllib.request.Request(target, method=method)  # noqa: S310
    if host:
        req.add_header("Host", host)
    if method in ("POST", "PUT", "PATCH"):
        req.add_header("content-type", "application/json")
        req.data = b"{}"
    ctx = ssl.create_default_context(cafile=os.path.expanduser(cafile)) if cafile else None
    opener = urllib.request.build_opener(_NoRedirect, urllib.request.HTTPSHandler(context=ctx))
    try:
        with opener.open(req, timeout=timeout) as r:  # noqa: S310
            return True, r.status
    except urllib.error.HTTPError as e:
        if 300 <= e.code < 400:
            return None, e.code          # redirected: UNKNOWN, not reachable
        # 404 means the process does not serve it. Any other status means it
        # does -- a 400 is the route rejecting input, which is reachability.
        return (e.code != 404), e.code
    except Exception:                                            # noqa: BLE001
        return None, None


def main():
    ap = argparse.ArgumentParser(prog="check-surface-coverage.sh",
                                 description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--no-probe", action="store_true",
                    help="skip the reachability filter (the app need not be running)")
    ap.add_argument("--live", action="store_true",
                    help="MOADIX increment 5, phase 10a: the probe is REQUIRED and runs against "
                         "live.base_url in .sdlc/config/product-tools.yaml, which must be loopback")
    args = ap.parse_args()

    try:
        paths = hlib.load_paths_doc(ROOT) or {}
    except Exception as exc:                                    # noqa: BLE001
        print("check-surface-coverage: cannot read the path map (%r). UNKNOWN "
              "about the INSTRUMENT, not a pass (3.10)." % (exc,), file=sys.stderr)
        return 2
    groot = (paths.get("governed_root") or "").strip("/")

    cfg_path = hlib.config_path(ROOT, "product-surface.yaml")
    if not os.path.exists(cfg_path):
        print("check-surface-coverage: harness/config/product-surface.yaml does "
              "not exist, so this product has NOT DECLARED how its shipped "
              "surface is enumerated.\n"
              "  This is UNKNOWN, not an empty surface, and not a pass (3.10). "
              "A product whose surface nobody enumerated has no shipped-vs-"
              "designed diff, which is the whole control.", file=sys.stderr)
        return 2
    try:
        cfg = hlib.load_yaml(cfg_path) or {}
    except Exception as exc:                                    # noqa: BLE001
        print("check-surface-coverage: product-surface.yaml does not parse "
              "(%r). UNKNOWN about the INSTRUMENT (3.10)." % (exc,), file=sys.stderr)
        return 2

    errs, notes = [], []
    unknown_errs = []
    enum = cfg.get("enumerate") or {}
    state, api, detail = run_enumerator(ROOT, groot, enum.get("api"))

    if state == "missing":
        errs.append("the `api` enumerator is not declared (%s). Never declared, "
                    "declared-as-none and ran-and-found-nothing are three "
                    "different states; this is the first and it is UNKNOWN, not "
                    "an empty surface." % detail)
    elif state == "failed":
        errs.append("the `api` enumerator is declared but did not produce a "
                    "surface: %s. A declaration that cannot run is not a control "
                    "(3.9)." % detail)
    elif state == "none":
        notes.append("api surface: NOT APPLICABLE -- %s" % detail)
    else:
        notes.append("api surface: %d route(s) enumerated by %r"
                     % (len(api), " ".join(str(a) for a in (enum.get("api") or {}).get("command") or [])))
        if not api:
            notes.append("the enumerator RAN and reported NO routes. That is a "
                         "stated empty set, not an absence of information -- "
                         "distinct from `method: none` and from no declaration "
                         "at all.")

    scr_state, _scr, scr_detail = run_enumerator(ROOT, groot, enum.get("screens"))
    if scr_state == "none":
        notes.append("screen surface: NOT APPLICABLE -- %s" % scr_detail)
    elif scr_state == "missing":
        errs.append("the `screens` enumerator is not declared (%s)." % scr_detail)
    elif scr_state == "failed":
        errs.append("the `screens` enumerator failed: %s" % scr_detail)

    # ---- the diff ---------------------------------------------------------
    if state == "declared":
        cpath = os.path.join(ROOT, groot, str(cfg.get("contract") or ""))
        declared = contract_surface(cpath)
        if declared is None:
            errs.append("the contract %r does not exist, so the shipped surface "
                        "cannot be diffed against anything. UNKNOWN about the "
                        "INSTRUMENT (3.10)." % cfg.get("contract"))
        else:
            reg = {}
            for r in (cfg.get("registered") or []):
                key = str((r or {}).get("surface") or "").strip()
                if key:
                    reg[key] = r
            notes.append("contract: %d route(s) in %s"
                         % (len(declared), cfg.get("contract")))
            for meth, path in api:
                key = "%s %s" % (meth, path)
                if (meth, path) in declared:
                    continue
                r = reg.get(key)
                if r and str(r.get("reason") or "").strip() and str(r.get("owner") or "").strip():
                    notes.append("registered outside the contract: %s (%s)"
                                 % (key, str(r.get("owner")).strip()))
                    continue
                if r:
                    errs.append("%s is registered outside the contract but its "
                                "entry lacks a reason or an owner. The escape "
                                "hatch is recorded or it is not an escape "
                                "hatch." % key)
                else:
                    errs.append(
                        "%s is SHIPPED and is not in %s, and is not registered. "
                        "A surface tracing to no contract entry is verified by "
                        "nothing and reported by nothing -- this is the R3 "
                        "feature-creep signal." % (key, cfg.get("contract")))

    # ---- reachability filter ----------------------------------------------
    # MOADIX v2: the reachability probe asked v1's harness/bin/run-product-app.sh
    # whether the app runs, then sent HTTP requests to it. v2 has not ported
    # that front door (app_run moves into .sdlc/product.yaml), and a gate run
    # must not touch the live product, so the probe is off in phase 9's gate run:
    # every declared surface is judged against the contract alone.
    # Increment 5 re-enables it in phase 10a (`--live`, registry check-surface-live):
    # the front door is live.base_url from .sdlc/config/product-tools.yaml, which
    # must be a loopback http(s) URL (the local test instance, never a production
    # URL); a non-loopback URL fails, an app that does not answer is UNKNOWN.
    live_url = None
    if args.live:
        try:
            ptools = hlib.load_yaml(os.path.join(ROOT, ".sdlc", "config", "product-tools.yaml")) or {}
        except Exception:                                       # noqa: BLE001
            ptools = {}
        live_url = str((ptools.get("live") or {}).get("base_url") or "")
        lsp = urllib.parse.urlsplit(live_url)
        if lsp.scheme not in ALLOWED_SCHEMES or (lsp.hostname or "") not in LOOPBACK_HOSTS:
            errs.append("live.base_url %r is not a loopback http(s) URL. The live probe runs only against the "
                        "local test instance, never a production URL." % live_url)
            live_url = None
        elif state != "declared" or not api:
            unknown_errs.append("the live probe has no enumerated API surface to probe (enumerator %s)" % state)
        else:
            reach, _c = probe(live_url, "GET", "/")
            if reach is None:
                unknown_errs.append("the app does not answer at %s; start the local instance (app_run) and "
                                    "the gate probes it again. UNKNOWN, not a pass." % live_url)
                live_url = None
    if state == "declared" and api and not args.no_probe and (live_url or not os.environ.get("MOADIX_GATE_RUN")):
        front = os.path.join(ROOT, "harness", "bin", "run-product-app.sh")  # v1 only; see above
        pcfg = cfg.get("probe") or {}
        # `url` exits 0 whether or not the app runs; `status` says whether it does.
        running = bool(live_url) or subprocess.run([front, "status"], capture_output=True, text=True,
                                                   cwd=ROOT).returncode == 0
        url = (live_url or str(pcfg.get("base_url") or "")) if running else ""
        if running and not url:
            # No probe block: the front door's origin, never its health path.
            out = (subprocess.run([front, "url"], capture_output=True, text=True, cwd=ROOT).stdout or "").strip().splitlines()
            sp = urllib.parse.urlsplit(out[-1] if out else "")
            url = "%s://%s" % (sp.scheme, sp.netloc) if sp.scheme else ""
        hosts = [(str((h or {}).get("prefix") or ""), str((h or {}).get("host") or ""))
                 for h in (pcfg.get("hosts") or [])]
        # probe.expected_404: routes the probe reaches whose answer is 404 by design
        # (a lookup that finds nothing for the probe's empty session). Each entry is
        # recorded with a reason and an owner, or it is not an expectation.
        expected = {}
        for e in (pcfg.get("expected_404") or []):
            key = str((e or {}).get("surface") or "").strip()
            if key and str(e.get("reason") or "").strip() and str(e.get("owner") or "").strip():
                expected[key] = e
            elif key:
                errs.append("probe.expected_404 entry %s lacks a reason or an owner. "
                            "An expected 404 is recorded or it is not expected." % key)

        def host_for(p):
            return next((h for pre, h in hosts if pre and h and p.startswith(pre)),
                        pcfg.get("default_host"))

        if not url.startswith("http"):
            notes.append("reachability filter SKIPPED: the app is not running "
                         "(`run-product-app.sh start`). Enumerated routes were "
                         "NOT confirmed reachable -- stated, not assumed.")
        else:
            unknown, unreachable = [], []
            for meth, path in api:
                ok, _code = probe(url, meth, path, host=host_for(path),
                                  cafile=pcfg.get("cafile"))
                key = "%s %s" % (meth, path)
                if ok is None:
                    unknown.append(key)
                elif not ok and key in expected:
                    e = expected[key]
                    notes.append("served, answers 404 by design: %s (%s): %s"
                                 % (key, str(e.get("owner")).strip(), " ".join(str(e.get("reason")).split())))
                elif not ok:
                    unreachable.append(key)
                elif key in expected:
                    notes.append("probe.expected_404 entry %s answered %s, not 404: "
                                 "the entry is stale; remove it." % (key, _code))
            for u in unreachable:
                errs.append("%s is enumerated but the running process does not "
                            "serve it (404). The declaration OVER-reports: a "
                            "route in the code that nothing can reach is still "
                            "a claim about the shipped surface." % u)
            for u in unknown:
                # NOT an `errs` entry. This file already exits 2 for UNKNOWN
                # about the instrument three times over, and then put "the
                # process could not be reached at all" into the same bucket as
                # "the process served a 404", which exits 1. The distinction
                # was in the PROSE and not in the exit code, so every caller
                # reading the code alone saw "ran and failed".
                unknown_errs.append(
                    "%s could not be probed at all. UNKNOWN about the "
                    "INSTRUMENT, not evidence of reachability (3.10)." % u)

    if not args.quiet:
        print("check-surface-coverage: %s" % (groot or "?"))
        for n in notes:
            print("  note  %s" % n)
        for c in (cfg.get("cannot_see") or []):
            print("  BLIND %s" % " ".join(str(c).split()))
        print("  limit this check verifies the enumerator RAN, that everything it "
              "reported is reachable, and that everything reachable is in the "
              "contract or registered. It does NOT verify the enumerator "
              "reported everything: that is the product's own account of itself, "
              "and under-reporting is invisible here.")
    for e in errs:
        print("  FAIL  %s" % e)
    for e in unknown_errs:
        print("  UNKNOWN  %s" % e)
    if errs:
        return 1
    if unknown_errs:
        # UNKNOWN outranks a clean pass and is DISTINCT from a failure: a
        # caller must be able to tell "the product is wrong" from "the
        # instrument was not there" (3.10).
        return 2
    if not args.quiet:
        print("  PASS  every enumerated surface is in the contract or registered.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
