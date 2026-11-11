#!/usr/bin/python3
"""TEST DOUBLE for the MOADIX checker. Never installed outside a test fixture.

Increment-2 tests run inside Claude Code's sandbox, where the Keychain cannot
be reached, so the real checker (checker/*.c, proven by the increment-1
corpus) cannot run there. This stub speaks the same command line and output
formats and keeps its secrets in plain files under its own directory:

  record --product P --action A --code C [--payload-b64 B]   -> ledger line JSON
  burn --code C | verify (stdin) | anchor --product P | state

Same TOTP (SHA1, 6 digits, 30 s, window -1..+1, single use via laststep),
same cooldown (3 wrong codes -> 15 min doubling to 24 h), same body format and
error strings. MOADIX_TEST_CLOCK_OFFSET shifts its clock like the test build
of the real checker. The fixture writes `stub/` next to this file at setup.
"""
import base64
import hashlib
import hmac
import json
import os
import re
import struct
import sys
import time

HERE = os.path.dirname(os.path.realpath(__file__))
D = os.path.join(HERE, "stub")
MAX_FAILS, PAUSE_BASE, PAUSE_CAP, STEP = 3, 15 * 60, 24 * 60 * 60, 30


def now():
    return int(time.time()) + int(os.environ.get("MOADIX_TEST_CLOCK_OFFSET") or 0)


def die(rc, msg):
    print("ERR " + msg)
    sys.exit(rc)


def load(name, default):
    try:
        with open(os.path.join(D, name)) as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def save(name, obj):
    tmp = os.path.join(D, name + ".tmp")
    with open(tmp, "w") as f:
        json.dump(obj, f)
    os.replace(tmp, os.path.join(D, name))


def secrets():
    s = load("secrets.json", None)
    if not s:
        die(13, "totp-secret-unreadable")
    return base64.b32decode(s["totp"]), bytes.fromhex(s["key"])


def hotp(k, step):
    h = hmac.new(k, struct.pack(">Q", step), hashlib.sha1).digest()
    o = h[19] & 15
    return (struct.unpack(">I", h[o:o + 4])[0] & 0x7FFFFFFF) % 1000000


def match_code(k, code, laststep):
    want, cur, used = int(code), now() // STEP, 0
    for d in (-1, 0, 1):
        if hotp(k, cur + d) == want:
            if cur + d > laststep:
                return cur + d
            used = -1
    return used


def arg(name):
    a = sys.argv
    for i in range(2, len(a) - 1):
        if a[i] == name:
            return a[i + 1]
    return None


def safe_id(s):
    return bool(s) and len(s) <= 64 and re.match(r"^[A-Za-z0-9_.-]+$", s) is not None


def safe_text(s, n):
    return bool(s) and len(s) <= n and all(32 <= ord(c) < 127 and c not in '"\\' for c in s)


def valid_code(s):
    return bool(s) and re.match(r"^\d{6}$", s) is not None


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    st = load("state.json", {"laststep": 0, "fails": 0, "until": 0})
    if cmd == "record":
        product, action, code = arg("--product"), arg("--action"), arg("--code")
        payload = arg("--payload-b64") or ""
        if not safe_id(product) or not safe_text(action, 512) or not valid_code(code) or \
                not re.match(r"^[A-Za-z0-9+/=]*$", payload):
            die(30, "bad-arguments")
        totp, key = secrets()
        t = now()
        if t < st["until"]:
            print("ERR paused %d" % (st["until"] - t))
            sys.exit(31)
        step = match_code(totp, code, st["laststep"])
        if step == -1:
            die(32, "code-already-used")
        if step == 0:
            st["fails"] += 1
            if st["fails"] >= MAX_FAILS:
                pause = PAUSE_BASE
                i = MAX_FAILS
                while i < st["fails"] and pause < PAUSE_CAP:
                    pause *= 2
                    i += 1
                pause = min(pause, PAUSE_CAP)
                st["until"] = t + pause
                save("state.json", st)
                print("ERR wrong-code-paused %d" % pause)
                sys.exit(33)
            save("state.json", st)
            die(33, "wrong-code")
        st.update(laststep=step, fails=0, until=0)
        save("state.json", st)
        anchors = load("anchors.json", {})
        seq, prev = (anchors[product].split() if product in anchors else (0, "GENESIS"))
        ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))
        body = '{"seq":%d,"prev":"%s","ts":"%s","product":"%s","action":"%s","payload_b64":"%s"}' % (
            int(seq) + 1, prev, ts, product, action, payload)
        hh = hashlib.sha256(body.encode()).hexdigest()
        mh = hmac.new(key, body.encode(), hashlib.sha256).hexdigest()
        anchors[product] = "%d %s" % (int(seq) + 1, hh)
        save("anchors.json", anchors)
        print('{"body":"%s","hash":"%s","hmac":"%s"}' % (body.replace('"', '\\"'), hh, mh))
        return 0
    if cmd == "burn":
        code = arg("--code")
        if valid_code(code):
            totp, _ = secrets()
            step = match_code(totp, code, st["laststep"])
            if step > 0:
                st["laststep"] = step
                save("state.json", st)
        print("OK")
        return 0
    if cmd == "verify":
        _, key = secrets()
        for line in sys.stdin:
            parts = line.strip().split(" ")
            try:
                body = bytes.fromhex(parts[0])
                ok = len(parts) == 2 and hmac.compare_digest(hmac.new(key, body, hashlib.sha256).hexdigest(), parts[1])
            except ValueError:
                ok = False
            print("ok" if ok else "bad")
        return 0
    if cmd == "anchor":
        product = arg("--product")
        if not safe_id(product):
            die(50, "bad-arguments")
        a = load("anchors.json", {}).get(product)
        print("OK %s" % a if a else "OK 0 GENESIS")
        return 0
    if cmd == "state":
        print("OK fails=%d paused_for=%d" % (st["fails"], max(0, st["until"] - now())))
        return 0
    die(2, "unknown-command")
    return 2


if __name__ == "__main__":
    sys.exit(main())
