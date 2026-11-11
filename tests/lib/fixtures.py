"""Fixtures for the increment-2 suite. Everything lives under one base directory
in $TMPDIR; nothing here touches a real product, keychain or container engine.

  base/home/gate/            a copy of this repo's gate/ (+ _testguard.py)
  base/home/bin/moadix-checker   tests/lib/stub_checker.py (+ bin/stub/ secrets)
  base/shim-bin/docker, podman   tests/lib/docker_shim.py
  base/<products>            throwaway git repos

The phone: codes come from the stub's TOTP secret at the test clock. Each
fresh() moves the shared clock offset forward one 30 s step, so every code is
new without sleeping.
"""
import base64
import hashlib
import hmac
import json
import os
import shutil
import stat
import struct
import subprocess
import tempfile
import time

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
LIB = os.path.join(REPO, "tests", "lib")
PY = "/usr/bin/python3"
GIT = "/usr/bin/git"
FIXDOCS = os.path.join(REPO, "tests", "fixtures", "product")


def sh(cmd, **kw):
    kw.setdefault("capture_output", True)
    kw.setdefault("text", True)
    return subprocess.run(cmd, **kw)


class Env(object):
    def __init__(self, tag="g2"):
        root = os.environ.get("TMPDIR") or "/tmp"
        self.base = os.path.realpath(tempfile.mkdtemp(prefix="moadix-%s-" % tag, dir=root))
        self.home = os.path.join(self.base, "home")
        self.shim = os.path.join(self.base, "shim-bin")
        self.offset = 0
        self.secret = None

    # ------------------------------------------------------------ setup
    def build(self):
        shutil.copytree(os.path.join(REPO, "gate"), os.path.join(self.home, "gate"),
                        ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copy(os.path.join(LIB, "_testguard.py"), os.path.join(self.home, "gate", "_testguard.py"))
        os.makedirs(os.path.join(self.home, "bin", "stub"))
        chk = os.path.join(self.home, "bin", "moadix-checker")
        shutil.copy(os.path.join(LIB, "stub_checker.py"), chk)
        os.chmod(chk, 0o755)
        self.secret = base64.b32encode(os.urandom(20)).decode().rstrip("=")
        with open(os.path.join(self.home, "bin", "stub", "secrets.json"), "w") as f:
            json.dump({"totp": self.secret, "key": os.urandom(32).hex()}, f)
        os.makedirs(self.shim)
        for name in ("docker", "podman"):
            p = os.path.join(self.shim, name)
            shutil.copy(os.path.join(LIB, "docker_shim.py"), p)
            os.chmod(p, 0o755)
        with open(os.path.join(self.home, "gate", "config", "trusted-bin.yaml"), "w") as f:
            f.write("# test fixture: the docker shim only\ndirs:\n  - %s\n" % self.shim)
        return self

    def remove(self):
        shutil.rmtree(self.base, ignore_errors=True)

    def env(self, **extra):
        e = dict(os.environ, MOADIX_GUARD_ROOT=self.base, MOADIX_GUARD_REPO=REPO, MOADIX_GUARD_SHIM=self.shim,
                 MOADIX_TEST_CLOCK_OFFSET=str(self.offset))
        e.update(extra)
        return e

    # ------------------------------------------------------------ the phone
    def code_at(self, step):
        k = base64.b32decode(self.secret + "=" * (-len(self.secret) % 8))
        h = hmac.new(k, struct.pack(">Q", step), hashlib.sha1).digest()
        o = h[19] & 15
        return "%06d" % ((struct.unpack(">I", h[o:o + 4])[0] & 0x7FFFFFFF) % 1000000)

    def fresh(self):
        self.offset += 30
        return self.code_at((int(time.time()) + self.offset) // 30)

    def checker(self, *args):
        return sh([os.path.join(self.home, "bin", "moadix-checker")] + list(args), env=self.env())

    # ------------------------------------------------------------ hooks
    def hook(self, mode, payload, timeout=120):
        t0 = time.time()
        r = sh([PY, "-I", os.path.join(self.home, "gate", "hook.py"), mode], input=json.dumps(payload),
               env=self.env(), timeout=timeout)
        self.last_duration = time.time() - t0
        try:
            out = json.loads(r.stdout) if r.stdout.strip() else {}
        except ValueError:
            out = {"_raw": r.stdout}
        return r.returncode, out, r.stderr

    def prompt(self, cwd, text):
        rc, out, err = self.hook("prompt", {"hook_event_name": "UserPromptSubmit", "session_id": "g2", "cwd": cwd,
                                            "prompt": text})
        ctx = (out.get("hookSpecificOutput") or {}).get("additionalContext", "")
        if rc != 0 or err.strip():
            ctx += " [rc=%d stderr=%s]" % (rc, err.strip()[-300:])
        return ctx

    def pretool(self, cwd, tool, tool_input):
        rc, out, err = self.hook("pretool", {"hook_event_name": "PreToolUse", "session_id": "g2", "cwd": cwd,
                                             "tool_name": tool, "tool_input": tool_input})
        hs = out.get("hookSpecificOutput") or {}
        return hs.get("permissionDecision", "none"), hs.get("permissionDecisionReason", "")

    # ------------------------------------------------------------ products
    def repo(self, name, docs=("00-brd.md",), commit=True):
        path = os.path.join(self.base, name)
        os.makedirs(os.path.join(path, "sdlc"))
        sh([GIT, "init", "-q", path])
        for d in docs:
            shutil.copy(os.path.join(FIXDOCS, "sdlc", d), os.path.join(path, "sdlc", d))
        with open(os.path.join(path, "README.md"), "w") as f:
            f.write("fixture %s\n" % name)
        if commit:
            self.commit(path, "fixture")
        return path

    def commit(self, path, msg="change"):
        sh([GIT, "-C", path, "add", "-A"])
        return sh([GIT, "-C", path, "-c", "user.email=fixture@example.invalid", "-c", "user.name=fixture",
                   "commit", "-qm", msg, "--allow-empty"])

    def init(self, path, pid):
        return self.prompt(path, "INIT %s %s" % (pid, self.fresh()))

    def review_until_fresh(self, path, label, tries=12):
        ctx = ""
        for _ in range(tries):
            ctx = self.prompt(path, "REVIEW %s" % label)
            if "still running" not in ctx and "have no current result" not in ctx:
                return ctx
        return ctx

    def ledger(self, path):
        p = os.path.join(path, ".sdlc", "ledger.jsonl")
        return [json.loads(l) for l in open(p).read().splitlines() if l.strip()] if os.path.exists(p) else []

    def payload(self, path, seq):
        line = self.ledger(path)[seq - 1]
        body = json.loads(line["body"])
        return body, json.loads(base64.b64decode(body["payload_b64"]).decode())

    def write(self, path, rel, text):
        full = os.path.join(path, rel)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w") as f:
            f.write(text)
        return full

    def set_counts(self, counts, fail_stop=False):
        with open(os.path.join(self.shim, "counts.json"), "w") as f:
            json.dump(counts, f)
        fs = os.path.join(self.shim, "fail-stop")
        if fail_stop:
            open(fs, "w").close()
        elif os.path.exists(fs):
            os.unlink(fs)

    def shim_calls(self):
        p = os.path.join(self.shim, "calls.log")
        return [json.loads(l) for l in open(p).read().splitlines()] if os.path.exists(p) else []

    def violations(self):
        p = os.path.join(self.base, "guard-violations.log")
        return [json.loads(l) for l in open(p).read().splitlines() if l.strip()] if os.path.exists(p) else []

    def clear_violations(self, predicate):
        p = os.path.join(self.base, "guard-violations.log")
        keep = [v for v in self.violations() if not predicate(v)]
        with open(p, "w") as f:
            f.write("".join(json.dumps(v) + "\n" for v in keep))


def executable(path):
    st = os.stat(path)
    os.chmod(path, st.st_mode | stat.S_IXUSR)
