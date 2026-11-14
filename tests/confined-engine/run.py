#!/usr/bin/python3
"""Increment-7d: the confined runner against a REAL Docker engine. Terminal only, one command:

    /usr/bin/python3 tests/confined-engine/run.py

The agent's sandbox cannot reach the Docker socket, so the operator runs this in Terminal. It uses only
throwaway fixtures and its own containers, volumes and networks, every one labelled moadix.run=es<hex>,
and removes them at the end (by that label only: it never prunes, never touches anything else).

It refuses to start, and says what it found, when:
  * any RUNNING container on the machine is not its own;
  * any compose project has a running container (stopped compose projects, such as a parked stack, are
    listed as found and left untouched: the suite never reads their mounts, starts, stops or removes them);
  * an image it needs is still `status: blocked` in gate/config/confinement.yaml (the licence ruling).

What it proves, each with a hostile fixture, through gate/confined.py exactly as the gates call it:
  secrets   the host's environment and files never reach the container; a secret-named variable is refused
  host      no host path and no Docker socket inside; the root filesystem is read-only
  network   product code runs with no network at all (no interface but lo, no DNS, no connect)
  egress    the live network is internal: no route out; the install proxy refuses a host off its allowlist
  limits    fork bomb (pids), memory (OOM kill), disk (file-size cap, tmpfs cap), wall clock
  output    a forged report (symlink to a host file, a FIFO, an oversized file) is refused
  cleanup   nothing labelled is left; every foreign container, volume and network is exactly as before
"""
import json
import os
import secrets
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.realpath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, REPO)

from gate import confined  # noqa: E402  (the repository's runner and configuration, never a fixture copy)

RESULTS = []
T0 = time.time()
NEEDED = ("node", "python")
PREFIX = "es"


def record(group, name, ok, evidence=""):
    RESULTS.append((group, name, bool(ok)))
    print("%s  [%s] %s" % ("PASS" if ok else "FAIL", group, name))
    if not ok:
        print("      %s" % " ".join(str(evidence).split())[:1500])


def docker(args, timeout=120, stdin=None):
    d = confined.docker_path()
    return subprocess.run([d] + args, capture_output=True, text=True, timeout=timeout, input=stdin)


def lines(args):
    p = docker(args)
    return [x for x in p.stdout.splitlines() if x.strip()]


# ------------------------------------------------------------------ preflight: refuse unless the machine is ours
def inventory():
    """All containers (running or not), volumes and networks, with the labels that matter."""
    fmt = '{{.ID}}\t{{.Names}}\t{{.State}}\t{{.Label "moadix.run"}}\t{{.Label "com.docker.compose.project"}}'
    cs = []
    for ln in lines(["ps", "-a", "--no-trunc", "--format", fmt]):
        f = (ln.split("\t") + [""] * 5)[:5]
        cs.append({"id": f[0], "name": f[1], "state": f[2], "run": f[3], "project": f[4]})
    vols = lines(["volume", "ls", "--format", '{{.Name}}\t{{.Label "moadix.run"}}'])
    nets = lines(["network", "ls", "--no-trunc", "--format", '{{.ID}}\t{{.Name}}\t{{.Label "moadix.run"}}'])
    return cs, vols, nets


def ours(run_label):
    return bool(run_label) and run_label.startswith(PREFIX)


def preflight():
    if not confined.docker_path():
        return ["Docker is not installed in %s" % ", ".join(confined.DOCKER_DIRS)], []
    v = docker(["version", "--format", "{{.Server.Version}}"])
    if v.returncode != 0:
        return ["the Docker engine is not reachable (start Docker Desktop): %s" % v.stderr.strip()[:300]], []
    cs, _vols, _nets = inventory()
    why = []
    foreign_running = [c for c in cs if c["state"] == "running" and not ours(c["run"])]
    if foreign_running:
        why.append("running containers that are not this suite's: %s" % ", ".join(
            "%s (%s%s)" % (c["name"], c["id"][:12], ", compose project %s" % c["project"] if c["project"] else "")
            for c in foreign_running))
    projects = {}
    for c in cs:
        if c["project"]:
            projects.setdefault(c["project"], []).append(c["state"])
    live = sorted(p for p, sts in projects.items() if "running" in sts)
    if live:
        why.append("compose projects with running containers: %s" % ", ".join(live))
    for name in NEEDED:
        try:
            confined.image(name)
        except confined.Unavailable as e:
            why.append("image %s: %s" % (name, e))
    return why, sorted(p for p, sts in projects.items() if "running" not in sts)


def rid():
    return PREFIX + secrets.token_hex(5)


def sh(r, img, script, tier="E-lint", mounts=(), network="none", env=None, name=None, **kw):
    return r.execute(img, ["sh", "-c", script], tier, list(mounts), network=network, env=env or {}, name=name, **kw)


# ------------------------------------------------------------------ the tests
def test_secrets(node):
    G = "secrets"
    canary = "moadix-canary-" + secrets.token_hex(8)
    os.environ["MOADIX_ENGINE_CANARY"] = canary
    host_dir = tempfile.mkdtemp(prefix="moadix-es-")
    with open(os.path.join(host_dir, "canary-file"), "w") as f:
        f.write(canary)
    r = confined.Run(rid())
    try:
        rc, out, err = sh(r, node, "env; cat /proc/1/environ 2>/dev/null | tr '\\0' '\\n'; "
                                   "ls -la /root /home /run/secrets 2>&1; "
                                   "grep -rs %s / --exclude-dir=proc --exclude-dir=sys 2>/dev/null | head -3; true" % canary)
        record(G, "the host's environment (a canary variable) and files (a canary file) are not in the container",
               rc == 0 and canary not in out + err and "HOME=/tmp/home" in out, out[-800:] + err[-300:])
        record(G, "only the runner's fixed environment reaches the run (no HOME of the host, no SSH agent, no tokens)",
               "SSH_AUTH_SOCK" not in out and "/Users/" not in out and "GH_TOKEN" not in out, out[-800:])
        try:
            sh(r, node, "true", env={"NPM_TOKEN": "x"})
            refused = None
        except confined.Refused as e:
            refused = str(e)
        record(G, "hostile: passing a secret-named variable (NPM_TOKEN) into a run is refused before the engine is called",
               refused and "NPM_TOKEN" in refused, refused)
    finally:
        r.close()
        os.environ.pop("MOADIX_ENGINE_CANARY", None)
        os.remove(os.path.join(host_dir, "canary-file"))
        os.rmdir(host_dir)
    record(G, "cleanup: nothing labelled %s is left" % r.label, not r.leftovers(), r.leftovers())


def test_host(node):
    G = "host paths"
    r = confined.Run(rid())
    try:
        rc, out, err = sh(r, node, "cat /proc/mounts; echo ---; ls /Users /host_mnt /Volumes 2>&1; "
                                   "test -S /var/run/docker.sock && echo SOCKET; test -S /run/docker.sock && echo SOCKET; "
                                   "touch /etc/x 2>&1 || echo RO-ROOT; touch /usr/local/x 2>&1 || echo RO-USR; true")
        mounts = out.split("---")[0]
        record(G, "no host path is mounted (no /Users, /host_mnt, /Volumes, no bind of a host directory)",
               rc == 0 and "/Users" not in mounts and "host_mnt" not in mounts and "/Volumes" not in mounts and
               "No such file" in out, out[-1200:])
        record(G, "no Docker socket inside", "SOCKET" not in out, out[-400:])
        record(G, "the root filesystem is read-only", "RO-ROOT" in out and "RO-USR" in out, out[-400:])
        for mounts_arg, what in (([("/Users", "/h", True)], "a host directory as a volume source"),
                                 ([("/var/run/docker.sock", "/s", True)], "the Docker socket")):
            try:
                r.execute(node, ["true"], "E-lint", mounts_arg)
                why = None
            except confined.Refused as e:
                why = str(e)
            record(G, "hostile: mounting %s is refused" % what, bool(why), why)
    finally:
        r.close()
    record(G, "cleanup: nothing labelled is left", not r.leftovers(), r.leftovers())


NET_PROBE = ("const net=require('net'),dns=require('dns');let n=0;const done=(k,v)=>{console.log(k+'='+v);if(++n==3)process.exit(0)};"
             "dns.lookup('registry.npmjs.org',(e)=>done('dns',e?'fail':'ok'));"
             "const s=net.connect({host:'1.1.1.1',port:443,timeout:4000},()=>done('ip','ok'));"
             "s.on('error',()=>done('ip','fail'));s.on('timeout',()=>{s.destroy();done('ip','fail')});"
             "const t=net.connect({host:'%s',port:%d,timeout:4000},()=>done('target','ok'));"
             "t.on('error',()=>done('target','fail'));t.on('timeout',()=>{t.destroy();done('target','fail')});")


def test_network(node, py):
    G = "network"
    r = confined.Run(rid())
    try:
        rc, out, err = r.execute(node, ["node", "-e", NET_PROBE % ("1.0.0.1", 80)], "E-lint", [])
        rc2, ifs, _ = sh(r, node, "ls /sys/class/net")
        record(G, "product code runs with no network: no DNS, no connection to an address, no interface but lo",
               "dns=fail" in out and "ip=fail" in out and "target=fail" in out and ifs.split() == ["lo"], (out, err, ifs))
        live = r.network("live")
        app_vol = r.volume("app")
        r.own(app_vol, node)
        r.execute(node, ["node", "-e", "require('http').createServer((q,s)=>s.end('ok')).listen(3000)"], "L", [],
                  network=live, aliases=[confined.SUT_ALIAS], name="moadix-%s-svc-app" % r.id, detach=True)
        time.sleep(2)
        rc, out, err = r.execute(node, ["node", "-e", NET_PROBE % (confined.SUT_ALIAS, 3000)], "L", [], network=live)
        record(G, "control: on the live network the scanner reaches the app (sut.moadix.test:3000)", "target=ok" in out,
               (out, err))
        record(G, "the live network is internal: no route out (no DNS for a public name, no connection to 1.1.1.1:443)",
               "dns=fail" in out and "ip=fail" in out, (out, err))
        inet, enet = r.network("install"), r.network("egress", internal=False)
        pvol = r.volume("proxy")
        tmp = tempfile.mkdtemp(prefix="moadix-es-")
        try:
            import tarfile
            tp = os.path.join(tmp, "p.tar")
            with tarfile.open(tp, "w") as tf:
                tf.add(os.path.join(REPO, "gate", "egress_proxy.py"), arcname="egress_proxy.py")
            r.load(pvol, tp, py)
        finally:
            for f in os.listdir(tmp):
                os.remove(os.path.join(tmp, f))
            os.rmdir(tmp)
        r.proxy(inet, enet, pvol)
        time.sleep(2)
        probe = ("const net=require('net');function c(h){return new Promise(ok=>{const s=net.connect(3128,'%s',()=>"
                 "s.write('CONNECT '+h+':443 HTTP/1.1\\r\\nHost: '+h+'\\r\\n\\r\\n'));s.setTimeout(8000);"
                 "s.on('data',d=>{ok(h+' '+d.toString().split('\\r\\n')[0]);s.destroy()});"
                 "s.on('error',e=>ok(h+' error '+e.code));s.on('timeout',()=>{ok(h+' timeout');s.destroy()})})}"
                 "(async()=>{console.log(await c('example.com'));console.log(await c('registry.npmjs.org'));"
                 "console.log(await c('registry.npmjs.org.evil.example'))})()") % confined.PROXY_ALIAS
        rc, out, err = r.execute(node, ["node", "-e", probe], "install", [], network=inet)
        rc2, out2, _ = r.execute(node, ["node", "-e", NET_PROBE % ("1.0.0.1", 80)], "install", [], network=inet)
        record(G, "install network: the proxy refuses a host off its allowlist (example.com, a look-alike suffix)",
               "example.com HTTP/1.1 403" in out and "evil.example HTTP/1.1 403" in out, (out, err))
        record(G, "install network: the proxy tunnels the registry (registry.npmjs.org 200; needs internet on the host)",
               "registry.npmjs.org HTTP/1.1 200" in out, (out, err))
        record(G, "install network: without the proxy there is no route out", "ip=fail" in out2 and "dns=fail" in out2, out2)
    finally:
        r.close()
    record(G, "cleanup: nothing labelled is left", not r.leftovers(), r.leftovers())


def test_limits(node):
    G = "limits"
    lim = confined.limits("E-lint")
    r = confined.Run(rid())
    try:
        # shell builtins only after the loop: with the pids limit full, nothing else can fork
        rc, out, err = sh(r, node, "cat /sys/fs/cgroup/pids.max; i=0; while [ $i -lt %d ]; do sleep 20 & i=$((i+1)); done "
                                   "2>/tmp/fork.err; n=0; for p in /proc/[0-9]*; do n=$((n+1)); done; echo $n; "
                                   "e=0; while read l; do e=$((e+1)); done < /tmp/fork.err; echo $e; true" % (lim["pids"] * 3))
        nums = [x for x in out.split() if x.isdigit()]
        record(G, "fork bomb: %d processes asked, the pids limit (%d) holds and fork fails" % (lim["pids"] * 3, lim["pids"]),
               len(nums) == 3 and nums[0] == str(lim["pids"]) and int(nums[1]) <= lim["pids"] and int(nums[2]) > 0,
               (out, err))
        try:
            r.execute(node, ["node", "--max-old-space-size=16384", "-e",
                             "const a=[];for(;;){a.push(Buffer.alloc(64<<20,1))}"], "E-lint", [])
            why = None
        except confined.Refused as e:
            why = str(e)
        record(G, "memory: allocating past %d MiB is killed (OOM) and refused, never a result" % lim["memory_mb"],
               why and "memory limit" in why, why)
        out_vol = r.volume("out")
        r.own(out_vol, node)
        rc, out, err = sh(r, node, "dd if=/dev/zero of=/out/big bs=1M count=%d 2>&1; ls -ln /out/big; "
                                   "i=0; while [ $i -lt %d ]; do dd if=/dev/zero of=/tmp/fill$i bs=1M count=40 2>&1 | "
                                   "grep -i 'no space' ; i=$((i+1)); done; true"
                          % (lim["out_mb"] + 20, lim["tmp_mb"] // 40 + 3), mounts=[(out_vol, "/out", False)])
        size = next((int(x.split()[4]) for x in out.splitlines() if x.endswith("/out/big") and len(x.split()) > 4), -1)
        record(G, "disk: a file written past the %d MiB file-size cap stops at the cap (RLIMIT_FSIZE)" % lim["out_mb"],
               0 < size <= lim["out_mb"] << 20, out[-800:])
        record(G, "disk: /tmp past its %d MiB tmpfs is refused (No space left)" % lim["tmp_mb"],
               "no space" in out.lower(), out[-800:])
    finally:
        r.close()
    r = confined.Run(rid(), {"limits": {"E-lint": {"wall_s": 5}}})
    try:
        t = time.time()
        try:
            r.execute(node, ["sleep", "600"], "E-lint", [])
            why = None
        except confined.Refused as e:
            why = str(e)
        record(G, "wall clock: a run past its wall clock (5 s here) is killed, removed and refused",
               why and "wall clock" in why and time.time() - t < 120 and not [c for c in r.leftovers() if c], why)
    finally:
        r.close()
    record(G, "cleanup: nothing labelled is left", not r.leftovers(), r.leftovers())


def test_output(node):
    G = "forged output"
    r = confined.Run(rid())
    tmp = tempfile.mkdtemp(prefix="moadix-es-")
    try:
        out_vol = r.volume("out")
        r.own(out_vol, node)
        for script, want, what in (
                ("ln -s /etc/passwd /out/eslint.json", "symbolic link", "a symlink to a file outside the output"),
                ("mkfifo /out/eslint.json", "not a regular file", "a FIFO in place of the report"),
                ("i=0; while [ $i -lt 6 ]; do dd if=/dev/zero of=/out/f$i bs=1M count=45 2>/dev/null; i=$((i+1)); done",
                 "above the", "files that together exceed the output cap")):
            sh(r, node, "rm -rf /out/* ; " + script, mounts=[(out_vol, "/out", False)])
            dest = os.path.join(tmp, "o%d" % len(os.listdir(tmp)))
            r.copy_out(out_vol, dest, node)
            probs = confined.check_output(dest, confined.limits("E-lint")["out_mb"] << 20)
            record(G, "hostile: %s is refused" % what, any(want in p for p in probs), probs)
        sh(r, node, "rm -rf /out/*; printf 'PASS eslint: 0 errors\\n' > /out/summary.txt; echo '{\"result\":\"PASS\"}' > "
                    "/out/eslint.json", mounts=[(out_vol, "/out", False)])
        dest = os.path.join(tmp, "forged")
        r.copy_out(out_vol, dest, node)
        sys.path.insert(0, os.path.join(REPO, "gate", "v1"))
        import check_exec
        try:
            f, n, _d = check_exec.verdict("eslint", dest, {}, None, None)
            ok = bool(f)
        except Exception as e:  # the gate reports UNKNOWN for anything it cannot parse: never a pass
            f, ok = [repr(e)], True
        record(G, "hostile: a summary line claiming PASS and a report that is not ESLint's are never believed", ok, f)
    finally:
        r.close()
        subprocess.run(["/bin/rm", "-rf", tmp], check=False)
    record(G, "cleanup: nothing labelled is left", not r.leftovers(), r.leftovers())


def main():
    print("MOADIX confined-engine suite (Terminal only). It never touches anything not labelled moadix.run=%s*." % PREFIX)
    why, stopped = preflight()
    if why:
        print("REFUSED: the suite starts only on a machine where nothing else runs and the images are cleared:")
        for w in why:
            print("  - %s" % w)
        if stopped:
            print("  (stopped compose projects found, left untouched: %s)" % ", ".join(stopped))
        return 2
    if stopped:
        print("found stopped compose projects (left untouched, never started, read or removed): %s" % ", ".join(stopped))
    # remove what an earlier, interrupted run of this suite left (its own label only)
    cs, vols, nets = inventory()
    for c in cs:
        if ours(c["run"]):
            docker(["rm", "-f", c["id"]])
    for ln in nets:
        f = (ln.split("\t") + ["", ""])[:3]
        if ours(f[2]):
            docker(["network", "rm", f[0]])
    for ln in vols:
        f = (ln.split("\t") + [""])[:2]
        if ours(f[1]):
            docker(["volume", "rm", "-f", f[0]])
    before = inventory()
    foreign_before = ({c["id"]: c["state"] for c in before[0] if not ours(c["run"])},
                      sorted(v for v in before[1] if not ours((v.split("\t") + [""])[1])),
                      sorted(n for n in before[2] if not ours((n.split("\t") + ["", ""])[2])))
    node, py = confined.image("node"), confined.image("python")
    for img in (node, py):
        p = docker(["pull", "-q", img], timeout=900)
        if p.returncode != 0:
            print("REFUSED: pulling %s failed: %s" % (img, p.stderr.strip()[:300]))
            return 2
    for t, a in ((test_secrets, (node,)), (test_host, (node,)), (test_network, (node, py)), (test_limits, (node,)),
                 (test_output, (node,))):
        try:
            t(*a)
        except Exception as e:
            import traceback
            record(t.__name__, "group ran to the end", False, "%s: %s\n%s" % (type(e).__name__, e,
                                                                             traceback.format_exc()[-1500:]))
    after = inventory()
    mine = [c["name"] for c in after[0] if ours(c["run"])] + [v for v in after[1] if ours((v.split("\t") + [""])[1])] + \
           [n for n in after[2] if ours((n.split("\t") + ["", ""])[2])]
    record("cleanup", "nothing this suite created is left (containers, volumes, networks)", not mine, mine)
    foreign_after = ({c["id"]: c["state"] for c in after[0] if not ours(c["run"])},
                     sorted(v for v in after[1] if not ours((v.split("\t") + [""])[1])),
                     sorted(n for n in after[2] if not ours((n.split("\t") + ["", ""])[2])))
    record("cleanup", "every container, volume and network that is not the suite's is exactly as before (%d, %d, %d)" % (
        len(foreign_before[0]), len(foreign_before[1]), len(foreign_before[2])), foreign_before == foreign_after,
        json.dumps([foreign_before, foreign_after])[:1500])
    n = len(RESULTS)
    bad = [r for r in RESULTS if not r[2]]
    for g, name, _ok in bad:
        print("FAILED [%s] %s" % (g, name))
    print("\n%d checks, %d passed, %d failed (%d s)" % (n, n - len(bad), len(bad), time.time() - T0))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
