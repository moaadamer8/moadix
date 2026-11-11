"""TEST GUARD: a test that starts, reads or writes a real product or a real Docker
compose project fails the suite.

Installed as an audit hook (sys.addaudithook) in:
  * the test runner itself (tests/gate2/run.py imports it first);
  * every gate process started from a FIXTURE gate copy: the fixture copies
    this file to <fixture home>/gate/_testguard.py, and hook.py, validate.py
    and the validator launcher import `gate._testguard` when it exists. The
    installed, root-owned gate has no such file, so production never loads it
    and nothing an agent controls can switch it on.

Rules (GUARD = the fixture base directory, REPO = this repository):
  write  inside a real product, or under $HOME outside GUARD     -> violation
         (temporary files in the system temp directory are fine)
  read   inside any directory tree that holds .sdlc/product.yaml
         and is not under GUARD (a real product)                  -> violation
  read   anything under $HOME outside REPO and GUARD (other repos,
         ~/sdlc-harness, ~/moadix-scratch), except tool caches    -> violation
  exec   docker / podman / docker-compose other than the fixture
         shim                                                     -> violation, and the call is BLOCKED
  exec   with a cwd outside GUARD and REPO                        -> violation
Violations are appended to GUARD/guard-violations.log; the runner fails the
suite on any line it did not deliberately provoke (the guard self-test).
"""
import json
import os
import sys

GUARD = os.environ.get("MOADIX_GUARD_ROOT")
REPO = os.environ.get("MOADIX_GUARD_REPO")
HOME = os.path.realpath(os.path.expanduser("~"))
CACHES = [os.path.join(HOME, ".cache"), os.path.join(HOME, "Library", "Caches"),
          os.path.join(HOME, ".local", "share", "uv")]
DOCKERISH = {"docker", "podman", "docker-compose", "nerdctl"}
_busy = [False]
_product_cache = {}


def _under(p, base):
    return bool(base) and (p == base or p.startswith(base.rstrip("/") + "/"))


def _real_product(p):
    d = p if os.path.isdir(p) else os.path.dirname(p)
    seen = []
    while d and d != "/":
        if d in _product_cache:
            r = _product_cache[d]
            break
        seen.append(d)
        if os.path.isfile(os.path.join(d, ".sdlc", "product.yaml")):
            r = d
            break
        d = os.path.dirname(d)
    else:
        r = None
    for s in seen:
        _product_cache[s] = r
    return r if r and not _under(r, GUARD) else None


def violation(kind, detail):
    if not GUARD:
        return
    _busy[0] = True
    try:
        with open(os.path.join(GUARD, "guard-violations.log"), "a") as f:
            f.write(json.dumps({"pid": os.getpid(), "argv0": sys.argv[0] if sys.argv else "", "kind": kind,
                                "detail": detail}) + "\n")
    finally:
        _busy[0] = False


def _path(x):
    if isinstance(x, int):
        return None
    if isinstance(x, bytes):
        x = x.decode("utf-8", "replace")
    try:
        return os.path.realpath(os.path.abspath(str(x)))
    except (OSError, ValueError):
        return None


def _check_read(p, how):
    if p is None or _under(p, GUARD) or _under(p, REPO):
        return
    if _real_product(p):
        violation("read-real-product", "%s %s" % (how, p))
    elif _under(p, HOME) and not any(_under(p, c) for c in CACHES):
        violation("read-outside-fixture", "%s %s" % (how, p))


def _hook(event, args):
    if _busy[0] or not GUARD:
        return
    if event == "open":
        p = _path(args[0])
        if p is None or p.startswith("/dev/"):
            return
        mode, flags = args[1] or "", args[2] or 0
        writing = any(c in str(mode) for c in "wax+") or (flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT |
                                                                   os.O_APPEND | os.O_TRUNC))
        if writing and not _under(p, GUARD) and (_real_product(p) or (
                _under(p, HOME) and not any(_under(p, c) for c in CACHES))):
            violation("write-outside-fixture", p)
        elif not writing:
            _check_read(p, "open")
    elif event in ("os.listdir", "os.scandir"):
        _check_read(_path(args[0] if args and args[0] is not None else "."), event)
    elif event in ("subprocess.Popen", "os.exec", "os.posix_spawn"):
        exe = args[0]
        argv = list(args[1]) if len(args) > 1 and args[1] else []
        name = os.path.basename(str(exe if not isinstance(exe, bytes) else exe.decode()))
        names = {name} | {os.path.basename(str(a)) for a in argv[:1]}
        shim = os.environ.get("MOADIX_GUARD_SHIM") or ""
        if names & DOCKERISH and not (shim and str(exe).startswith(shim)):
            violation("exec-real-docker", "%s %s" % (exe, " ".join(str(a) for a in argv[:8])))
            raise RuntimeError("MOADIX test guard: refusing to run a real container engine (%s)" % exe)
        if event == "subprocess.Popen" and len(args) > 2 and args[2]:
            cwd = _path(args[2])
            if cwd and not (_under(cwd, GUARD) or _under(cwd, REPO)):
                violation("exec-cwd-outside-fixture", "%s in %s" % (name, cwd))


if GUARD and not getattr(sys, "_moadix_guard", False):
    sys._moadix_guard = True
    sys.addaudithook(_hook)
