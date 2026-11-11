"""ISOLATION GUARD for the Keychain corpus (tests/corpus/run.py).

The corpus runs in Terminal, outside Claude Code's sandbox, with the real
Keychain service. It must only ever use what it builds itself:

  * its own throwaway test keychains   <scratch>/kc*/test.keychain-db
  * its own test-built checkers        <scratch>/home*/bin/moadix-checker,
                                       compiled with the test keychain and a
                                       scratch pin file baked in
  * its own fixture products           <scratch>/product*

and never

  * the login keychain (or any keychain under ~/Library/Keychains, or the
    user's default keychain),
  * the installed checker or gate      /Library/Application Support/ClaudeCode,
  * any real product's .sdlc/          any .sdlc/product.yaml outside <scratch>.

Three layers, all of which abort the run (IsolationError) instead of recording
a failed check:

  1. static assertions before any check: the scratch directory, each test
     keychain, each checker binary (its baked-in keychain and pin-file paths
     are read from the binary itself), each gate copy (where its checker
     resolves to) and each fixture product;
  2. argv checks on every command the corpus runs (run.py's sh()), including
     an allowlist for `security` subcommands that must name a scratch keychain;
  3. an audit hook (sys.addaudithook) on this process: any subprocess, exec or
     file write that names a forbidden resource is refused before it happens,
     even if it bypasses sh().

Gate processes started by the fixture hooks carry tests/lib/_testguard.py
(copied into each fixture gate), which logs any read or write of a real
product; run.py fails on any line in that log.

selftest() proves each layer fires; run.py runs it before anything else.
"""
import os
import subprocess
import sys
import tempfile

HOME = os.path.realpath(os.path.expanduser("~"))
INSTALLED_HOME = "/Library/Application Support/ClaudeCode"
KEYCHAIN_DIR = os.path.join(HOME, "Library", "Keychains")
LOGIN_KEYCHAINS = [os.path.join(KEYCHAIN_DIR, "login.keychain-db"), os.path.join(KEYCHAIN_DIR, "login.keychain")]
PROD_PINFILE = INSTALLED_HOME + "/managed-settings.json"
MARKER = ".moadix-corpus-scratch"
# Names a scratch directory may hold when it predates the marker (an older run).
KNOWN_LAYOUT = {"kcA", "kcB", "homeA", "homeB", "productA", "productB", "kc-probe", "impostor", "inj.c",
                "inj.dylib", "guard-violations.log", MARKER, "decoy"}
# `security` subcommands the corpus may run, all against a scratch keychain.
SECURITY_ALLOWED = {"create-keychain", "delete-keychain", "set-keychain-settings", "unlock-keychain",
                    "find-generic-password", "add-generic-password", "delete-generic-password"}


class IsolationError(Exception):
    pass


def _real(p):
    return os.path.realpath(os.path.abspath(os.path.expanduser(str(p))))


def _under(p, base):
    return p == base or p.startswith(base.rstrip("/") + "/")


def _product_above(p):
    d = p if os.path.isdir(p) else os.path.dirname(p)
    while d and d != "/":
        if os.path.isfile(os.path.join(d, ".sdlc", "product.yaml")):
            return d
        d = os.path.dirname(d)
    return None


def default_keychains():
    """The user's default and login keychains as `security` reports them (best effort:
    unavailable inside Claude Code's sandbox, where the corpus cannot run anyway)."""
    out = set(_real(k) for k in LOGIN_KEYCHAINS)
    for args in (["default-keychain", "-d", "user"], ["login-keychain", "-d", "user"]):
        try:
            r = subprocess.run(["/usr/bin/security"] + args, capture_output=True, text=True, timeout=10)
            for line in r.stdout.splitlines():
                line = line.strip().strip('"')
                if line:
                    out.add(_real(line))
        except (OSError, subprocess.SubprocessError):
            pass
    return out


class Isolation(object):
    def __init__(self, base, repo, forbidden_keychains=None):
        self.base = _real(base)
        self.repo = _real(repo)
        self.forbidden_kc = set(forbidden_keychains if forbidden_keychains is not None else default_keychains())
        self.armed = False

    # ------------------------------------------------------------ layer 1
    def assert_scratch(self):
        b = self.base
        if b in ("/", HOME, self.repo) or _under(self.repo, b) or _under(b, self.repo):
            raise IsolationError("scratch %s overlaps / , your home or this repo" % b)
        for bad in (INSTALLED_HOME, KEYCHAIN_DIR, os.path.join(HOME, ".claude")):
            if _under(b, bad) or _under(bad, b):
                raise IsolationError("scratch %s overlaps %s" % (b, bad))
        prod = _product_above(os.path.dirname(b))
        if prod:
            raise IsolationError("scratch %s is inside the real product %s" % (b, prod))
        if os.path.exists(b):
            names = set(os.listdir(b))
            if MARKER not in names and not names <= KNOWN_LAYOUT:
                raise IsolationError("scratch %s exists and was not made by the corpus (unexpected: %s); "
                                     "refusing to delete it" % (b, ", ".join(sorted(names - KNOWN_LAYOUT))[:200]))
        return True

    def assert_keychain(self, kc):
        k = _real(kc)
        if not _under(k, self.base):
            raise IsolationError("keychain %s is outside the scratch directory" % k)
        if k in self.forbidden_kc or _under(k, KEYCHAIN_DIR):
            raise IsolationError("keychain %s is a real keychain (login/default or under %s)" % (k, KEYCHAIN_DIR))
        return True

    def assert_product(self, path):
        p = _real(path)
        if not _under(p, self.base):
            raise IsolationError("product %s is outside the scratch directory" % p)
        prod = _product_above(os.path.dirname(p))
        if prod and not _under(prod, self.base):
            raise IsolationError("product %s sits inside the real product %s" % (p, prod))
        return True

    def assert_checker(self, path, kc, pinfile):
        """The checker must be a TEST build made here: under the scratch dir, not the
        installed one, with the scratch keychain and pin file baked in (both are
        string literals in the binary) and without the production pin file."""
        p = _real(path)
        if not _under(p, self.base) or _under(p, INSTALLED_HOME):
            raise IsolationError("checker %s is not a scratch build" % p)
        self.assert_keychain(kc)
        try:
            with open(p, "rb") as f:
                blob = f.read()
        except OSError as e:
            raise IsolationError("checker %s cannot be read (%s)" % (p, e))
        if _real(kc).encode() not in blob and os.path.abspath(kc).encode() not in blob:
            raise IsolationError("checker %s is not pinned to the test keychain %s (a production build reads the "
                                 "login keychain)" % (p, kc))
        if os.path.abspath(pinfile).encode() not in blob and _real(pinfile).encode() not in blob:
            raise IsolationError("checker %s is not pinned to the scratch pin file %s" % (p, pinfile))
        if PROD_PINFILE.encode() in blob:
            raise IsolationError("checker %s reads the production pin file" % p)
        return True

    def assert_gate_home(self, home, checker):
        """A gate copy finds its checker at <home>/bin/moadix-checker (state.checker_path);
        that must resolve to this run's test build."""
        h = _real(home)
        if not _under(h, self.base):
            raise IsolationError("gate home %s is outside the scratch directory" % h)
        resolved = _real(os.path.join(h, "gate", "..", "bin", "moadix-checker"))
        if resolved != _real(checker):
            raise IsolationError("gate in %s would run %s, not the test checker %s" % (h, resolved, checker))
        if os.path.exists(os.path.join(h, "gate")) and not os.path.isfile(os.path.join(h, "gate", "_testguard.py")):
            raise IsolationError("gate copy in %s has no test guard" % h)
        return True

    # ------------------------------------------------------------ layer 2
    def check_argv(self, argv, cwd=None):
        argv = [a.decode() if isinstance(a, bytes) else str(a) for a in (argv if isinstance(argv, (list, tuple))
                                                                        else [argv])]
        joined = " ".join(argv)
        if INSTALLED_HOME in joined:
            raise IsolationError("command names the installed MOADIX home: %s" % joined[:200])
        if KEYCHAIN_DIR in joined or any(k in joined for k in self.forbidden_kc):
            raise IsolationError("command names a real keychain: %s" % joined[:200])
        if argv and os.path.basename(argv[0]) == "security":
            sub = argv[1] if len(argv) > 1 else ""
            if sub == "list-keychains" and argv[2:] == ["-d", "user"]:
                pass  # read-only: the hygiene check compares the search list before/after
            elif sub not in SECURITY_ALLOWED:
                raise IsolationError("security %s is not on the corpus allowlist" % sub)
            else:
                kcs = [a for a in argv[2:] if a.endswith((".keychain-db", ".keychain"))]
                if len(kcs) != 1 or argv[-1] != kcs[0]:
                    raise IsolationError("security %s must name exactly one scratch keychain as its last "
                                         "argument (otherwise it acts on the default keychain): %s" % (sub, joined))
                self.assert_keychain(kcs[0])
        if cwd is not None:
            c = _real(cwd)
            if not (_under(c, self.base) or _under(c, self.repo)):
                raise IsolationError("command runs in %s, outside the scratch directory and this repo" % c)
        return True

    def check_payload(self, payload):
        cwd = payload.get("cwd")
        if not cwd or not _under(_real(cwd), self.base):
            raise IsolationError("hook payload cwd %s is outside the scratch directory" % cwd)
        prod = _product_above(_real(cwd))
        if prod and not _under(prod, self.base):
            raise IsolationError("hook payload cwd %s is in the real product %s" % (cwd, prod))
        return True

    # ------------------------------------------------------------ layer 3
    def _audit(self, event, args):
        if not self.armed:
            return
        if event == "subprocess.Popen":
            exe, argv = args[0], args[1]
            argv = list(argv) if isinstance(argv, (list, tuple)) else ([argv] if argv else [])
            exe = exe or (argv[0] if argv else "")
            self.check_argv([exe] + argv[1:], args[2] if len(args) > 2 else None)
        elif event in ("os.exec", "os.posix_spawn"):
            self.check_argv([args[0]] + list(args[1] or [])[1:])
        elif event == "open":
            p, mode, flags = args[0], args[1] or "", args[2] or 0
            if isinstance(p, int) or p is None:
                return
            ab = _real(p.decode() if isinstance(p, bytes) else p)
            writing = any(c in str(mode) for c in "wax+") or (
                flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC))
            if _under(ab, INSTALLED_HOME) and writing:
                raise IsolationError("write into the installed MOADIX home: %s" % ab)
            if _under(ab, KEYCHAIN_DIR) or ab in self.forbidden_kc:
                raise IsolationError("open of a real keychain file: %s" % ab)
            if "/.sdlc/" in ab + "/" and not _under(ab, self.base):
                prod = _product_above(ab)
                if prod and not _under(prod, self.base) and not _under(ab, self.repo):
                    raise IsolationError("open of a real product's gate state: %s" % ab)

    def arm(self):
        if not getattr(sys, "_moadix_isolation", None):
            sys._moadix_isolation = self
            sys.addaudithook(lambda e, a: getattr(sys, "_moadix_isolation", None) and
                             sys._moadix_isolation._audit(e, a))
        sys._moadix_isolation = self
        self.armed = True


# ---------------------------------------------------------------- self-test

def selftest(repo):
    """[(name, fired, detail)]. Every case must fire: each hands the guard a real
    resource (or a stand-in that looks exactly like one) and expects an abort.
    Runs without the Keychain, so it also runs inside Claude Code's sandbox."""
    out = []
    tmp = _real(tempfile.mkdtemp(prefix="moadix-isolation-selftest-"))
    base = os.path.join(tmp, "scratch")
    os.makedirs(os.path.join(base, "kcA"))
    kc = os.path.join(base, "kcA", "test.keychain-db")
    pin = os.path.join(base, "kcA", "managed-settings.json")
    iso = Isolation(base, repo, forbidden_keychains=set(_real(k) for k in LOGIN_KEYCHAINS))
    decoy = os.path.join(tmp, "realproduct")  # a product OUTSIDE the scratch dir = a real product
    os.makedirs(os.path.join(decoy, ".sdlc"))
    with open(os.path.join(decoy, ".sdlc", "product.yaml"), "w") as f:
        f.write("product: decoy\n")

    def case(name, fn):
        try:
            fn()
            out.append((name, False, "no abort"))
        except IsolationError as e:
            out.append((name, True, str(e)[:160]))
        except Exception as e:  # anything else means the guard did not stop it
            out.append((name, False, "not stopped by the guard: %r" % (e,)))

    installed = INSTALLED_HOME + "/moadix/bin/moadix-checker"
    case("the installed checker as a fixture checker", lambda: iso.assert_checker(installed, kc, pin))
    case("the login keychain as the test keychain", lambda: iso.assert_keychain(LOGIN_KEYCHAINS[0]))
    case("a keychain outside the scratch dir", lambda: iso.assert_keychain(os.path.join(tmp, "x.keychain-db")))
    prodbuild = os.path.join(base, "homeP", "bin", "moadix-checker")
    os.makedirs(os.path.dirname(prodbuild))
    with open(prodbuild, "wb") as f:  # stand-in for a production build: no test keychain path inside
        f.write(b"\xcf\xfa\xed\xfe" + PROD_PINFILE.encode() + b"\0SecKeychainCopyDefault\0")
    case("a checker built without the test keychain (a production build)",
         lambda: iso.assert_checker(prodbuild, kc, pin))
    testbuild = os.path.join(base, "homeT", "bin", "moadix-checker")
    os.makedirs(os.path.dirname(testbuild))
    with open(testbuild, "wb") as f:  # stand-in for a test build pinned to the scratch keychain
        f.write(b"\xcf\xfa\xed\xfe" + kc.encode() + b"\0" + pin.encode() + b"\0")
    os.makedirs(os.path.join(base, "homeT", "gate"))
    with open(os.path.join(base, "homeT", "gate", "_testguard.py"), "w") as f:
        f.write("")
    ok_static = True
    try:
        iso.assert_checker(testbuild, kc, pin)
        iso.assert_gate_home(os.path.join(base, "homeT"), testbuild)
    except IsolationError as e:
        ok_static = False
        out.append(("control: a scratch test build passes the guard", False, str(e)))
    if ok_static:
        out.append(("control: a scratch test build passes the guard", True, "accepted"))
    os.makedirs(os.path.join(base, "homeL", "gate"))
    os.makedirs(os.path.join(base, "homeL", "bin"))
    os.symlink(installed, os.path.join(base, "homeL", "bin", "moadix-checker"))
    case("a gate copy whose checker resolves to the installed one",
         lambda: iso.assert_gate_home(os.path.join(base, "homeL"), testbuild))
    case("a fixture product outside the scratch dir (a real .sdlc/)", lambda: iso.assert_product(decoy))
    case("a hook payload whose cwd is a real product", lambda: iso.check_payload({"cwd": decoy}))
    case("a command running the installed checker", lambda: iso.check_argv([installed, "state"]))
    case("security without a keychain argument (acts on the login keychain)",
         lambda: iso.check_argv(["security", "find-generic-password", "-s", "moadix-totp", "-a", "operator"]))
    case("security naming the login keychain",
         lambda: iso.check_argv(["security", "unlock-keychain", "-p", "x", LOGIN_KEYCHAINS[0]]))
    case("security subcommand off the allowlist (dump-keychain)",
         lambda: iso.check_argv(["security", "dump-keychain", kc]))
    case("a command whose cwd is a real product", lambda: iso.check_argv(["git", "status"], cwd=decoy))
    case("a scratch dir inside a real product",
         lambda: Isolation(os.path.join(decoy, "scratch"), repo, set()).assert_scratch())
    os.makedirs(os.path.join(tmp, "notours"))
    with open(os.path.join(tmp, "notours", "thesis.tex"), "w") as f:
        f.write("x")
    case("an existing scratch dir the corpus did not make (would be deleted)",
         lambda: Isolation(os.path.join(tmp, "notours"), repo, set()).assert_scratch())

    # Layer 3: armed audit hook, bypassing sh() entirely. The exec cases use
    # stand-ins that trip exactly the same rules but would do nothing if the
    # guard failed: a path under the installed home that does not exist, and
    # /usr/bin/true with the login keychain as an argument.
    iso.arm()
    try:
        case("audit hook: subprocess.run of a program in the installed MOADIX home, bypassing sh()",
             lambda: subprocess.run([INSTALLED_HOME + "/moadix/bin/selftest-never-exists", "state"],
                                    capture_output=True))
        case("audit hook: os.posix_spawn naming the login keychain, bypassing sh()",
             lambda: os.posix_spawn("/usr/bin/true", ["true", LOGIN_KEYCHAINS[0]], dict(os.environ)))
        case("audit hook: opening a real product's ledger", lambda: open(os.path.join(decoy, ".sdlc",
                                                                                      "product.yaml")).read())
    finally:
        iso.armed = False
    import shutil
    shutil.rmtree(tmp, ignore_errors=True)
    return out


if __name__ == "__main__":
    here = os.path.dirname(os.path.realpath(__file__))
    res = selftest(os.path.dirname(os.path.dirname(here)))
    for name, fired, detail in res:
        print("%s  [guard] %s\n      %s" % ("PASS" if fired else "FAIL", name, detail))
    bad = [r for r in res if not r[1]]
    print("\nguard self-test: %d/%d fired" % (len(res) - len(bad), len(res)))
    sys.exit(1 if bad else 0)
