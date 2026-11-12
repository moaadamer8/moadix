#!/usr/bin/python3
"""End-to-end dry run of managed/install.sh and managed/uninstall.sh, no sudo.

    /usr/bin/python3 tests/install/dryrun.py

Everything lives under ~/moadix-scratch/install-dryrun:
  root/ClaudeCode     stands in for /Library/Application Support/ClaudeCode (absent at start, as on this Mac)
  kc/standin.keychain-db  stands in for the login keychain; holds one unrelated item that must survive
  products/toy        a throwaway product repo
Checks: install works and the installed gate records a real approval; an update
keeps the secrets; uninstall leaves root/ and the keychain exactly as before;
a second uninstall is harmless; the dry-run flag refuses system paths.
"""
import base64
import hashlib
import hmac
import json
import os
import shutil
import struct
import subprocess
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BASE = os.path.expanduser("~/moadix-scratch/install-dryrun")
ROOT = os.path.join(BASE, "root")
CC = os.path.join(ROOT, "ClaudeCode")
KC = os.path.join(BASE, "kc", "standin.keychain-db")  # not "login.*": that name was added to the user search list
PROD = os.path.join(BASE, "products", "toy")
RESULTS = []


def sh(cmd, **kw):
    kw.setdefault("capture_output", True)
    kw.setdefault("text", True)
    return subprocess.run(cmd, **kw)


def check(name, ok, evidence):
    RESULTS.append(ok)
    print("%s  %s\n      %s" % ("PASS" if ok else "FAIL", name, evidence.replace("\n", "\n      ")))


def tree(path):
    out = {}
    for dp, dns, fns in os.walk(path):
        for n in dns + fns:
            p = os.path.join(dp, n)
            st = os.lstat(p)
            digest = hashlib.sha256(open(p, "rb").read()).hexdigest()[:12] if os.path.isfile(p) else "dir"
            out[os.path.relpath(p, path)] = (oct(st.st_mode), digest)
    return out


def kc_items():
    out = sh(["security", "dump-keychain", KC]).stdout
    items, cur = [], {}
    for line in out.splitlines():
        line = line.strip()
        if line.startswith("keychain:"):
            if cur:
                items.append(cur)
            cur = {}
        for k in ("svce", "acct"):
            if line.startswith('"%s"<blob>=' % k):
                cur[k] = line.split("=", 1)[1]
    if cur:
        items.append(cur)
    return sorted(json.dumps(i, sort_keys=True) for i in items)


def snapshot():
    return {"root": tree(ROOT), "keychain": kc_items(),
            "search_list": sh(["security", "list-keychains", "-d", "user"]).stdout}


def totp(secret, offset=0):
    k = base64.b32decode(secret + "=" * (-len(secret) % 8))
    h = hmac.new(k, struct.pack(">Q", int(time.time()) // 30 + offset), hashlib.sha1).digest()
    o = h[19] & 15
    return "%06d" % ((struct.unpack(">I", h[o:o + 4])[0] & 0x7FFFFFFF) % 1000000)


def hook(mode, payload):
    r = sh(["/usr/bin/python3", os.path.join(CC, "moadix", "gate", "hook.py"), mode], input=json.dumps(payload))
    return r.stdout


def main():
    if os.path.exists(KC):
        sh(["security", "delete-keychain", KC])
    shutil.rmtree(BASE, ignore_errors=True)
    search_list_at_start = sh(["security", "list-keychains", "-d", "user"]).stdout
    os.makedirs(ROOT)
    os.makedirs(os.path.dirname(KC))
    for c in (["create-keychain", "-p", "dryrun", KC], ["set-keychain-settings", KC], ["unlock-keychain", "-p", "dryrun", KC],
              ["add-generic-password", "-s", "unrelated-app", "-a", "someone", "-w", "keep-me", KC]):
        assert sh(["security"] + c).returncode == 0, c
    before = snapshot()
    print("BEFORE: root/ has %d entries; keychain items: %s\n" % (len(before["root"]), before["keychain"]))

    r = sh(["bash", os.path.join(REPO, "managed", "install.sh"), "--dry-run", "/Library/Application Support/ClaudeCode", KC])
    check("install.sh --dry-run refuses a system path", r.returncode != 0 and "must not point at a system path" in r.stderr,
          r.stderr.strip().splitlines()[-2] if r.stderr.strip() else "")

    r = sh(["bash", os.path.join(REPO, "managed", "install.sh"), "--dry-run", CC, KC], input="\n")
    out = r.stdout + r.stderr
    key = next((l.split(":", 1)[1].strip() for l in out.splitlines() if "Secret key:" in l), "")
    steps = [l for l in out.splitlines() if l.startswith("== ") or l.startswith("installed gate") or l.startswith("checker:")]
    check("install (fresh) exits 0 and runs all six steps", r.returncode == 0 and len([s for s in steps if s.startswith("== ")]) == 6,
          "\n".join(steps + ["rc=%d" % r.returncode]))
    pol = json.load(open(os.path.join(CC, "managed-settings.json")))
    cmd = pol["hooks"]["PreToolUse"][0]["hooks"][0]
    check("policy: hooks run the installed gate copy, fail closed, with a timeout",
          cmd["command"] == "/usr/bin/python3 -I '%s/moadix/gate/hook.py' pretool" % CC and cmd["onFailure"] == "block" and cmd["timeout"] == 15,
          json.dumps(cmd))
    check("policy: disableBypassPermissionsMode under permissions; pin set; no plugin keys without --plugin",
          pol["permissions"].get("disableBypassPermissionsMode") == "disable" and "disableBypassPermissionsMode" not in pol
          and len(pol["env"]["MOADIX_PIN"]) == 32 and "enabledPlugins" not in pol and pol["strictKnownMarketplaces"] == [],
          "permissions.disableBypassPermissionsMode=%r, pin=%s..., strictKnownMarketplaces=%r" % (
              pol["permissions"].get("disableBypassPermissionsMode"), pol["env"]["MOADIX_PIN"][:6], pol["strictKnownMarketplaces"]))
    rels = [os.path.join(d, f) for d in ("", "v1", "config") for f in os.listdir(os.path.join(REPO, "gate", d))
            if f.endswith((".py", ".yaml", ".toml", ".ini"))]
    same = all(open(os.path.join(REPO, "gate", f)).read() == open(os.path.join(CC, "moadix", "gate", f)).read()
               for f in rels) and not os.path.exists(os.path.join(CC, "moadix", "gate", "_testguard.py"))
    check("installed gate copy matches the repo's gate/", same, "files: %s" % sorted(os.listdir(os.path.join(CC, "moadix", "gate"))))

    # The installed gate works end to end with the code the operator would scan.
    os.makedirs(PROD)
    sh(["git", "-C", PROD, "init", "-q"])
    sh(["/usr/bin/python3", os.path.join(CC, "moadix", "gate", "sdlc_init.py"), PROD, "toy"])
    os.makedirs(os.path.join(PROD, "sdlc"))
    shutil.copy(os.path.join(REPO, "tests", "fixtures", "product", "sdlc", "00-brd.md"), os.path.join(PROD, "sdlc"))
    sh(["git", "-C", PROD, "add", "-A"])
    sh(["git", "-C", PROD, "-c", "user.email=dryrun@example.invalid", "-c", "user.name=dryrun", "commit", "-qm", "brd"])
    stop = pol["hooks"]["Stop"][0]["hooks"][0]
    check("policy: a Stop hook runs the installed gate copy (it starts validators; never blocks, so no onFailure)",
          stop["command"] == "/usr/bin/python3 -I '%s/moadix/gate/hook.py' stop" % CC and "onFailure" not in stop,
          json.dumps(stop))
    # increment 3 (ruling 2): the gate starts the validators when the agent's turn ends; REVIEW only reads.
    hook("stop", {"hook_event_name": "Stop", "cwd": PROD})
    for _ in range(40):
        o = hook("prompt", {"prompt": "REVIEW 0", "cwd": PROD})
        if "validators for phase 0: PASS" in o or "FAIL" in o:
            break
        time.sleep(0.5)
    check("installed gate: the Stop hook ran the ported validators; REVIEW 0 shows the result", "check-handoff-0: PASS" in o,
          o[:200])
    o = hook("prompt", {"prompt": "APPROVE 0 %s" % totp(key), "cwd": PROD})
    check("installed gate: 'APPROVE 0 <code from the shown key>' is recorded", "APPROVE 0 recorded (ledger seq 1)" in o, o[:200])
    o = hook("pretool", {"tool_name": "Edit", "tool_input": {"file_path": ".sdlc/phase.yaml", "old_string": "a", "new_string": "b"}, "cwd": PROD})
    check("installed gate: Edit of .sdlc/phase.yaml is denied", '"deny"' in o, o[:160])

    got = []
    for c in ("echo ok > docs/canary-ok.txt", "sh probe.sh", "sh -c 'echo x > .sdlc/canary-hook'"):
        o = hook("pretool", {"tool_name": "Bash", "tool_input": {"command": c}, "cwd": PROD})
        got.append("deny" if '"deny"' in o else "allow")
    check("real-mode canary probes: positive control and sandbox probe pass the hook, the .sdlc probe is denied",
          got == ["allow", "allow", "deny"], "decisions: %s" % got)

    cd1 = sh(["codesign", "-dvvv", os.path.join(CC, "moadix", "bin", "moadix-checker")]).stderr
    r = sh(["bash", os.path.join(REPO, "managed", "install.sh"), "--dry-run", CC, KC])
    cd2 = sh(["codesign", "-dvvv", os.path.join(CC, "moadix", "bin", "moadix-checker")]).stderr
    o = hook("prompt", {"prompt": "STATUS", "cwd": PROD})
    check("install again = update: exits 0, keeps the secrets (STATUS still clean, same checker cdhash)",
          r.returncode == 0 and "MOADIX is updated" in r.stdout and "INTEGRITY OK" in o
          and [l for l in cd1.splitlines() if l.startswith("CDHash")] == [l for l in cd2.splitlines() if l.startswith("CDHash")],
          "rc=%d; %s; STATUS: %s" % (r.returncode, "updated" if "MOADIX is updated" in r.stdout else r.stdout[-200:], o[60:140]))
    last = [l for l in r.stdout.splitlines() if l.strip()][-1:] or [""]
    check("increment 6 (ruling 4): a successful update's LAST line is exactly 'MOADIX is updated.', and it "
          "prints nothing on stderr (no 'Permission denied' from the cleanup)",
          last == ["MOADIX is updated."] and "Permission denied" not in r.stderr and not r.stderr.strip(),
          "last line %r; stderr %r" % (last[0], r.stderr.strip()[-200:]))

    mid = kc_items()
    r = sh(["bash", os.path.join(REPO, "managed", "uninstall.sh"), "--dry-run", CC, KC])
    check("uninstall exits 0", r.returncode == 0,
          "\n".join(l for l in r.stdout.splitlines() if l.strip()) + "\nkeychain items while installed: %d" % len(mid))
    shutil.rmtree(os.path.dirname(PROD))  # the product repo is user data; the uninstaller keeps it by design
    after = snapshot()
    check("after uninstall: stand-in root/ exactly as before", after["root"] == before["root"],
          "before %d entries, after %d entries: %s" % (len(before["root"]), len(after["root"]), sorted(after["root"]) or "empty"))
    check("after uninstall: keychain exactly as before (unrelated item kept, MOADIX items gone)", after["keychain"] == before["keychain"],
          "before %s\n after %s" % (before["keychain"], after["keychain"]))
    check("user keychain search list unchanged", after["search_list"] == before["search_list"], after["search_list"].strip())
    r = sh(["bash", os.path.join(REPO, "managed", "uninstall.sh"), "--dry-run", CC, KC])
    check("second uninstall is harmless (exits 0, changes nothing)", r.returncode == 0 and snapshot() == after,
          " / ".join(l for l in r.stdout.splitlines() if l and not l.startswith("==")))
    sh(["security", "delete-keychain", KC])
    end = sh(["security", "list-keychains", "-d", "user"]).stdout
    check("user keychain search list identical to before the test began (stand-in keychain deleted)",
          end == search_list_at_start, end.strip())
    print("\n%d checks, %d passed" % (len(RESULTS), sum(RESULTS)))
    return 0 if all(RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())
