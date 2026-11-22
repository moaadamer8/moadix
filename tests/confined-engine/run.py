#!/usr/bin/python3
"""Increment-7d: the confined runner against a REAL Docker engine. Terminal only, one command:

    /usr/bin/python3 tests/confined-engine/run.py

The agent's sandbox cannot reach the Docker socket, so the operator runs this in Terminal. It uses only
throwaway fixtures and its own containers, volumes and networks, every one labelled moadix.run=es<hex>,
and removes them at the end. Safeguards (ruling 3 on increment 7d):
  * it removes only objects carrying its own run label (moadix.run=es + 10 hex digits); it has no pruning
    command of any kind and no compose "down" with volumes; tests/lib/no_prune.py checks that statically,
    here before anything starts and in tests/inc7d on every sandbox run;
  * before it starts and after its cleanup it records every container, volume, network and image that is
    not its own (names and ids); if the two records differ, the suite fails and prints the difference;
  * it never starts, stops or inspects the contents of a foreign project: it only lists names, ids, states
    and labels.

It refuses to start, and says what it found, when:
  * any RUNNING container on the machine is not its own;
  * any compose project has a running container (stopped compose projects, such as a parked stack, are
    listed as found and left untouched: the suite never reads their mounts, starts, stops or removes them);
  * an image it needs is still `status: blocked` in gate/config/confinement.yaml (the licence ruling).

What it proves, each with a hostile fixture, through gate/confined.py exactly as the gates call it:
  secrets   the host's environment and files never reach the container (a property: every variable is the
            runner's or the image's own; a deliberately unconfined control run fails it); a secret-named
            variable is refused
  host      no host path and no Docker socket inside; the root filesystem is read-only
  network   product code runs with no network at all (no interface but lo, no DNS, no connect)
  egress    the live network is internal: no route out; the install proxy refuses a host off its allowlist
  limits    fork bomb (pids), memory (OOM kill), disk (file-size cap, tmpfs cap), wall clock
  output    a forged report (symlink to a host file, a FIFO, an oversized file) is refused
  user      0.7.3 (MF-27): the run's uid (65534, nobody) has a passwd entry in every pinned image the gates
            run product code in; a uid without one (10001, the old value) is refused as UNKNOWN before a run
  smoke     0.7.3: every executing gate starts and writes its output file, with its real pinned tool, on the
            fixture product tests/fixtures/smoke, through check_exec.run_gate exactly as the gate calls it
            (installs go through the egress proxy, so the host needs internet). Images a live gate builds
            carry the suite's label and are left in place (ruling 3: nothing removes images); they are
            listed at the end and excluded from the foreign-object comparison
  rel076    0.7.6: the phase-8 blockers of the first product run, end to end on tests/fixtures/smoke-076 (strict
            CSP, a sign-in, Vitest, PostgreSQL): two proxies (MF-54), a stale gate run removed, Stryker finds
            vitest (MF-53) and scores the database code (MF-51), axe keeps the CSP (MF-49) and signs in (MF-50),
            check-traceability leaves the tree clean (MF-46)
  cleanup   nothing labelled is left; every foreign container, volume, network and image is exactly as before
            (objects an earlier real gate run left, run label x + 10 hex, are the gate's: listed, not compared)
"""
import json
import os
import re
import secrets
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.realpath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "tests", "lib"))

import env_leak  # noqa: E402
import no_prune  # noqa: E402
from gate import confined  # noqa: E402  (the repository's runner and configuration, never a fixture copy)

RESULTS = []
T0 = time.time()
NEEDED = ("node", "node-full", "python", "chromium", "zap")
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


OWN = re.compile(r"^%s[0-9a-f]{10}$" % PREFIX)


def ours(run_label):
    return bool(run_label) and bool(OWN.match(run_label))


def inspect_pinned(name, fmt):
    """The suite's only inspect: a pinned image of its own, named as in confinement.yaml (never a foreign object)."""
    return docker(["image", "inspect", "--format", fmt, confined.image(name)]).stdout


def own_images():
    """Ids of the pinned images the suite pulls (its own); every other image is foreign."""
    ids = set()
    for name in NEEDED:
        ids.update(inspect_pinned(name, "{{.Id}}").split())
    return ids


SMOKE_RUNS = []  # the run ids the smoke group used (each carries the suite's own es<hex> label)


def built_images():
    """Ids of images a live gate built during this suite: listed by its own run labels only (never an inspect of
    a foreign image); never removed (ruling 3)."""
    out = []
    for run_id in SMOKE_RUNS:
        out += lines(["image", "ls", "-q", "--no-trunc", "--filter", "label=moadix.run=%s" % run_id])
    return sorted(set(out))


def gates(run_label):
    """0.7.6: an object an earlier real gate run left (run label x + 10 hex digits). The gate's own sweep removes
    such objects when their run is stale, so they are listed, not compared; the suite itself never removes them."""
    return bool(run_label) and bool(confined.GATE_RUN_ID.match(run_label))


def snapshot(own_img):
    """Every container, volume, network and image that is not the suite's (nor a gate run's): names, ids (and
    container state)."""
    cs, vols, nets = inventory()
    own_img = set(own_img) | set(built_images())
    imgs = lines(["image", "ls", "-a", "--no-trunc", "--format", "{{.ID}}\t{{.Repository}}:{{.Tag}}"])

    def mine(lab):
        return ours(lab) or gates(lab)
    return {
        "containers": sorted("%s %s %s" % (c["id"], c["name"], c["state"]) for c in cs if not mine(c["run"])),
        "volumes": sorted(v.split("\t")[0] for v in vols if not mine((v.split("\t") + [""])[1])),
        "networks": sorted(" ".join(n.split("\t")[:2]) for n in nets if not mine((n.split("\t") + ["", ""])[2])),
        "images": sorted(i.replace("\t", " ") for i in imgs if i.split("\t")[0] not in own_img),
    }


def difference(a, b):
    out = []
    for k in a:
        gone, new = sorted(set(a[k]) - set(b[k])), sorted(set(b[k]) - set(a[k]))
        out += ["%s gone: %s" % (k, x) for x in gone] + ["%s new: %s" % (k, x) for x in new]
    return out


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
    # 0.7.5 (the 0.7.4 engine run): the first check asserts the property (tests/lib/env_leak.py), not an exact
    # string; 0.7.4 also required HOME to be the old /tmp/home and failed once HOME moved to /tmp. A control
    # run that deliberately lets the host in (the canary variable passed through, the canary folder mounted)
    # shows the same check then fails, so it is not weaker than before.
    G = "secrets"
    canary = "moadix-canary-" + secrets.token_hex(8)
    os.environ["MOADIX_ENGINE_CANARY"] = canary
    host_dir = tempfile.mkdtemp(prefix="moadix-es-")
    with open(os.path.join(host_dir, "canary-file"), "w") as f:
        f.write(canary)
    r = confined.Run(rid())
    runner_env = {"PATH": confined.RUN_PATH, "HOME": "/tmp", "LANG": "C.UTF-8", "CI": "1", "TZ": "UTC"}  # noqa: S108
    assert sorted(runner_env) == sorted(confined.RUN_ENV_NAMES)
    image_names = [x.split("=", 1)[0] for x in (json.loads(inspect_pinned("node", "{{json .Config.Env}}") or "null") or [])]
    try:
        rc, out, err = sh(r, node, env_leak.probe(canary))
        found = env_leak.problems(out, err, canary, runner_env, image_names)
        record(G, "the host's environment (a canary variable) and files (a canary file) are not in the container, "
                  "and every variable is the runner's (with its value) or the image's own",
               rc == 0 and image_names and not found, "; ".join(found) or out[-800:] + err[-300:])
        record(G, "only the runner's fixed environment reaches the run (no HOME of the host, no SSH agent, no tokens)",
               "SSH_AUTH_SOCK" not in out and "/Users/" not in out and "GH_TOKEN" not in out, out[-800:])
        # control: the same check over a run that is deliberately NOT confined. It is the suite's own labelled
        # container, removed with --rm and by the run's cleanup; nothing of the gate starts it.
        c = docker(["run", "--rm", "--label", r.label, "--name", "moadix-%s-control" % r.id, "--network", "none",
                    "--env", "MOADIX_ENGINE_CANARY", "--volume", "%s:/hostcanary:ro" % host_dir, node, "sh", "-c",
                    env_leak.probe(canary)])
        cfound = env_leak.problems(c.stdout, c.stderr, canary, runner_env, image_names)
        record(G, "control: on a deliberately unconfined run (the host's canary variable passed through, the canary "
                  "folder mounted) the same check fails, naming the variable and the file",
               c.returncode == 0 and any("MOADIX_ENGINE_CANARY" in x for x in cfound)
               and any("file holding the canary" in x for x in cfound), "; ".join(cfound) or c.stderr[-300:])
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


IF_PROBE = ("const fs=require('fs'),os=require('os');const r={};"
            "for(const n of fs.readdirSync('/sys/class/net')){const d='/sys/class/net/'+n;"
            "if(!fs.statSync(d).isDirectory())continue;"  # bonding_masters is a file, not a device
            "r[n]={flags:fs.readFileSync(d+'/flags','utf8').trim(),oper:fs.readFileSync(d+'/operstate','utf8').trim()}}"
            "const rows=f=>fs.readFileSync(f,'utf8').trim().split('\\n').filter(Boolean);"
            "console.log(JSON.stringify({ifs:r,addr:Object.keys(os.networkInterfaces()),"
            "route4:rows('/proc/net/route').slice(1),"
            "route6:rows('/proc/net/ipv6_route').map(l=>l.trim().split(/\\s+/).pop()),"
            "if6:rows('/proc/net/if_inet6').map(l=>l.trim().split(/\\s+/).pop())}))")


def test_network(node, py):
    G = "network"
    r = confined.Run(rid())
    try:
        rc, out, err = r.execute(node, ["node", "-e", NET_PROBE % ("1.0.0.1", 80)], "E-lint", [])
        rc2, ifs, ierr = r.execute(node, ["node", "-e", IF_PROBE], "E-lint", [])
        try:
            st = json.loads(ifs.strip().splitlines()[-1])
        except (ValueError, IndexError):
            st = None
        # The kernel creates placeholder devices (gre0, sit0, tunl0, ...) in every network namespace; they are
        # down and have no address. The property: nothing but lo is up or addressed, and no route leaves lo.
        up = st and [n for n, v in st["ifs"].items() if n != "lo" and int(v["flags"], 16) & 1]
        record(G, "product code runs with no network: no DNS, no connection to an address; no interface but lo is up "
                  "or has an address, and no route exists except on lo",
               "dns=fail" in out and "ip=fail" in out and "target=fail" in out and st is not None and not up and
               st["addr"] == ["lo"] and st["if6"] in ([], ["lo"]) and st["route4"] == [] and
               all(d == "lo" for d in st["route6"]), (out, err, ifs, ierr, up))
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
        # The bomb runs in a subshell: dash exits on "Cannot fork", so the shell that reports must not be the one
        # that hits the limit. The report uses builtins only (with the pids limit full, nothing else can fork):
        # the limit, the processes alive, the cgroup's own count of refused forks (pids.events max), the errors.
        rc, out, err = sh(r, node, "read m < /sys/fs/cgroup/pids.max; echo max=$m; "
                                   "( i=0; while [ $i -lt %d ]; do sleep 20 & i=$((i+1)); done ) 2>/tmp/fork.err; "
                                   "n=0; for p in /proc/[0-9]*; do n=$((n+1)); done; echo procs=$n; "
                                   "while read k v; do [ \"$k\" = max ] && echo events=$v; done < /sys/fs/cgroup/pids.events; "
                                   "e=0; while read l; do e=$((e+1)); done < /tmp/fork.err; echo errors=$e; true"
                          % (lim["pids"] * 3))
        kv = dict(x.split("=", 1) for x in out.split() if "=" in x and x.split("=", 1)[1].isdigit())
        record(G, "fork bomb: %d processes asked, the pids limit (%d) holds: at most %d alive, the cgroup refused "
                  "forks (pids.events max > 0) and fork failed" % (lim["pids"] * 3, lim["pids"], lim["pids"]),
               kv.get("max") == str(lim["pids"]) and 0 < int(kv.get("procs", "0")) <= lim["pids"] and
               int(kv.get("events", "0")) > 0 and int(kv.get("errors", "0")) > 0, (out, err))
        try:
            r.execute(node, ["node", "--max-old-space-size=16384", "-e",
                             "const a=[];for(;;){a.push(Buffer.alloc(64<<20,1))}"], "E-lint", [])
            why = None
        except confined.Refused as e:
            why = str(e)
        record(G, "memory: allocating past %d MiB is killed (OOM) and refused, never a result" % lim["memory_mb"],
               why and "memory limit (%d MiB)" % lim["memory_mb"] in why, why)
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


# ------------------------------------------------------------------ 0.7.3: the run's user, and one smoke run per gate
def test_user(_node):
    G = "user"
    r = confined.Run(rid())
    try:
        for name in ("node", "node-full", "python", "chromium"):
            try:
                r.check_user(confined.image(name), "%d:%d" % (r.uid, r.uid))
                ok, why = True, ""
            except confined.Unavailable as e:
                ok, why = False, str(e)
            record(G, "uid %d has a passwd entry in the pinned %s image" % (r.uid, name), ok, why)
        try:
            r.check_user(confined.image("node"), "10001:10001")
            refused = ""
        except confined.Unavailable as e:
            refused = str(e)
        record(G, "a uid with no passwd entry (10001, the 0.7.2 value) is refused before any run", "no passwd entry"
               in refused, refused)
    finally:
        r.close()


SDLC = "." + "sdlc"  # the product state folder of the throwaway smoke repository
SMOKE_FIX = os.path.join(REPO, "tests", "fixtures", "smoke")
# (gate, phase, the output file the run must write, fixture variant)
SMOKE = [("pytm", "4", r"tm\.json", None), ("likec4", "3", r"model\.json", None),
         ("dependency-cruiser", "3", r"depcruise\.json", "no-src"), ("dependency-cruiser", "7", r"depcruise\.json", None),
         ("knip", "7", r"knip\.json", None), ("eslint", "7", r"eslint\.json", None), ("tsc", "7", r"tsc\.txt", None),
         ("stryker", "8", r"mutation\.json", None), ("tests", "8", r"junit\.xml", None),
         ("schemathesis", "8", r"st/junit[^ ]*\.xml", None), ("zap", "9", r"zap\.json", None),
         ("lhci", "10a", r"lhr-\d+\.json", None), ("axe", "6", r"axe\.json", None)]


def smoke_product(base, variant):
    """The fixture copied into a throwaway git repository (its own commit), product-tools.yaml in place."""
    import shutil
    p = os.path.join(base, variant or "full")
    shutil.copytree(SMOKE_FIX, p, ignore=shutil.ignore_patterns(".claude", "README.md", "product-tools.yaml"))
    if variant == "no-src":  # MF-26: phase 3 writes the rules before any code exists
        shutil.rmtree(os.path.join(p, "src"))
        shutil.rmtree(os.path.join(p, "tests"))
    git = ["/usr/bin/git", "-C", p]
    subprocess.run(git + ["init", "-q"], check=True)
    subprocess.run(git + ["add", "-A"], check=True)
    subprocess.run(git + ["-c", "user.email=smoke@example.invalid", "-c", "user.name=smoke", "commit", "-qm",
                          "smoke fixture"], check=True)
    os.makedirs(os.path.join(p, SDLC, "config"))
    with open(os.path.join(SMOKE_FIX, "product-tools.yaml")) as f, \
            open(os.path.join(p, SDLC, "config", "product-tools.yaml"), "w") as g:
        g.write(f.read())
    return p


def test_smoke(_node):
    G = "smoke"
    sys.path.insert(0, os.path.join(REPO, "gate", "v1"))
    import check_exec
    base = tempfile.mkdtemp(prefix="moadix-smoke-")
    products = {}
    for gate, label, want, variant in SMOKE:
        root = products.get(variant) or products.setdefault(variant, smoke_product(base, variant))
        st = {"current_phase": label, "feature": None, "mode": "greenfield"}
        try:
            run_id = rid()
            SMOKE_RUNS.append(run_id)
            f, n, _data, _dest = check_exec.run_gate(root, st, gate, label, run_id=run_id)
            err = ""
        except (confined.Refused, confined.Unavailable) as e:
            f, n, err = [], [], "%s: %s" % (type(e).__name__, e)
        logrel = next((x[len("run log "):] for x in n if x.startswith("run log ")), None)
        if not logrel:
            m = re.search(r"kept at (\S+)", err)
            logrel = m.group(1) if m else None
        log = open(os.path.join(root, logrel)).read() if logrel and os.path.exists(os.path.join(root, logrel)) else ""
        written = next((ln for ln in log.splitlines() if ln.startswith("files written:")), "")
        got = re.search(r"(?:^|, |: )%s \(\d+ bytes\)" % want, written) is not None
        extra = True
        if variant == "no-src":
            extra = any("configuration only" in x for x in n)
        record(G, "%s (phase %s%s) starts and writes %s" % (gate, label, ", " + variant if variant else "",
                                                           want.replace("\\", "")),
               got and extra and not err, "%s | fails %s | notes %s | %s | log:\n%s" % (
                   err, f[:3], n[:4], written, log[-1500:]))


# ------------------------------------------------------------------ 0.7.6: the phase-8 blockers, end to end
FIX76 = os.path.join(REPO, "tests", "fixtures", "smoke-076")  # strict CSP, a sign-in, vitest, pg (smoke-076/README.md)


def smoke076_product(base):
    import shutil
    p = os.path.join(base, "r076")
    shutil.copytree(FIX76, p, ignore=shutil.ignore_patterns(".claude", "README.md", "product-tools.yaml"))
    git = ["/usr/bin/git", "-C", p]
    subprocess.run(git + ["init", "-q"], check=True)
    subprocess.run(git + ["add", "-A"], check=True)
    subprocess.run(git + ["-c", "user.email=smoke@example.invalid", "-c", "user.name=smoke", "commit", "-qm",
                          "smoke-076 fixture"], check=True)
    os.makedirs(os.path.join(p, SDLC, "config"))
    with open(os.path.join(FIX76, "product-tools.yaml")) as f, \
            open(os.path.join(p, SDLC, "config", "product-tools.yaml"), "w") as g:
        g.write(f.read())
    return p


def run_logged(check_exec, root, gate, label):
    """run_gate as the gate calls it, under one of the suite's run ids; (fails, notes, data, error, log, run id)."""
    st = {"current_phase": label, "feature": None, "mode": "greenfield"}
    run_id = rid()
    SMOKE_RUNS.append(run_id)
    try:
        f, n, data, _dest = check_exec.run_gate(root, st, gate, label, run_id=run_id)
        err = ""
    except (confined.Refused, confined.Unavailable) as e:
        f, n, data, err = [], [], {}, "%s: %s" % (type(e).__name__, e)
    logrel = next((x[len("run log "):] for x in n if x.startswith("run log ")), None)
    if not logrel:
        m = re.search(r"kept at (\S+)", err)
        logrel = m.group(1) if m else None
    log = open(os.path.join(root, logrel)).read() if logrel and os.path.exists(os.path.join(root, logrel)) else ""
    return f, n, data or {}, err, log, run_id


def labelled(run_id):
    lab = "label=moadix.run=%s" % run_id
    return lines(["ps", "-aq", "--filter", lab]) + lines(["network", "ls", "-q", "--filter", lab]) + \
        lines(["volume", "ls", "-q", "--filter", lab])


def test_rel076(node):
    """Each 0.7.6 fix, end to end on the real engine with the real pinned tools, on the smoke-076 fixture."""
    G = "rel076"
    sys.path.insert(0, os.path.join(REPO, "gate", "v1"))
    import check_exec
    from gate import verify
    base = tempfile.mkdtemp(prefix="moadix-smoke076-")
    root = smoke076_product(base)
    # stale: an earlier gate run that was killed before its cleanup (its process is gone); the suite's own run id,
    # so the suite's accounting still owns it, with the labels a 0.7.6 gate run puts on everything it creates
    p = subprocess.Popen(["/usr/bin/true"])
    p.wait()
    sid = rid()
    labels = ["--label", "moadix.run=%s" % sid, "--label", "moadix.owner=gate", "--label", "moadix.pid=%d" % p.pid,
              "--label", "moadix.started=%d" % int(time.time() - 120)]
    seeded = [docker(["create", "--name", "moadix-%s-svc-postgres" % sid] + labels + ["--network", "none", node, "true"]),
              docker(["network", "create", "--internal"] + labels + ["moadix-%s-svc" % sid]),
              docker(["volume", "create"] + labels + ["moadix-%s-out" % sid])]
    # MF-54: schemathesis with build.network: registry starts the install proxy and the build proxy
    f, n, _data, err, log, run_id = run_logged(check_exec, root, "schemathesis", "8")
    written = next((ln for ln in log.splitlines() if ln.startswith("files written:")), "")
    record(G, "MF-54: schemathesis (build.network: registry, two proxies) runs to its report, and nothing of its run "
              "is left", not err and re.search(r"st/junit[^ ]*\.xml", written) and not labelled(run_id),
           "%s | fails %s | %s | left %s | log:\n%s" % (err, f[:3], written, labelled(run_id), log[-1200:]))
    record(G, "stale: the run removed what a killed gate run left (labelled as the gate's, moadix.pid of a process "
              "that is gone)", all(x.returncode == 0 for x in seeded) and not labelled(sid) and
           any(sid in x for x in n), ([x.stderr[-200:] for x in seeded], labelled(sid), n[:3]))
    # MF-53 and MF-51: Stryker runs Vitest, with the gate's PostgreSQL service
    f, n, data, err, log, _r = run_logged(check_exec, root, "stryker", "8")
    written = next((ln for ln in log.splitlines() if ln.startswith("files written:")), "")
    record(G, "MF-53: Stryker's sandbox finds vitest (no ERR_MODULE_NOT_FOUND) and writes mutation.json",
           not err and "mutation.json" in written and "ERR_MODULE_NOT_FOUND" not in log,
           "%s | fails %s | %s | log:\n%s" % (err, f[:3], written, log[-1500:]))
    counts = data.get("counts") or {}
    record(G, "MF-51: the database-backed module is scored with the gate's PostgreSQL service (no NoCoverage mutant, "
              "some killed)", not err and counts and counts.get("NoCoverage", 0) == 0 and counts.get("Killed", 0) > 0,
           "%s | counts %s | fails %s | log:\n%s" % (err, counts, f[:3], log[-800:]))
    # MF-49 and MF-50: axe on the strict-CSP app, with the declared sign-in
    f, n, data, err, log, _r = run_logged(check_exec, root, "axe", "8")
    res = data.get("results") or []
    record(G, "MF-49: axe checks every page of the strict-CSP app, the policy kept (the inline canary never ran: no "
              "title CSP-BYPASSED)", not err and not f and len(res) == 3 and not any(r.get("error") for r in res) and
           all(r.get("title") not in (None, "CSP-BYPASSED") for r in res), "%s | fails %s | results %s | log:\n%s" % (
               err, f[:4], res, log[-1200:]))
    tasks = next((r for r in res if r.get("path") == "/tasks"), {})
    record(G, "MF-50: axe signs in (a __Host- Secure cookie over the internal http), checks /tasks with the session, "
              "and names the row checked elsewhere", data.get("signin") and tasks.get("session") and
           tasks.get("final") == "/tasks" and tasks.get("title") == "Tasks" and
           any("Edit task" in x and "checked elsewhere" in x for x in n), "%s | %s | %s | notes %s" % (
               err, data.get("signin"), tasks, n[:4]))
    # MF-46: the phase-8 validator, with no test results yet (as after REOPEN 7), leaves the tree clean
    t = subprocess.run([sys.executable, "-I", os.path.join(REPO, "gate", "v1", "check_traceability.py")], cwd=root,
                       capture_output=True, text=True, timeout=120, env=dict(os.environ, MOADIX_PRODUCT_ROOT=root))
    record(G, "MF-46: check-traceability writes its matrix to the gate's cache; the tree stays clean, so a verifier "
              "may launch", os.path.exists(os.path.join(root, SDLC, "cache", "08-traceability.md")) and
           not os.path.exists(os.path.join(root, "sdlc", "08-traceability.md")) and not verify.dirty(root),
           (t.stdout[-400:], verify.dirty(root)))


# The checks each group records (the total is always TOTAL: a crash is one failed check, and the group's checks
# that never ran are reported as failed, not dropped).
PLAN = {"test_secrets": ("secrets", 5), "test_host": ("host paths", 6), "test_network": ("network", 7),
        "test_limits": ("limits", 6), "test_output": ("forged output", 5), "test_user": ("user", 5),
        "test_smoke": ("smoke", 13), "test_rel076": ("rel076", 7)}
TOTAL = 1 + sum(n for _g, n in PLAN.values()) + 2  # the static check, the groups, the two cleanup checks


def run_group(t, a):
    group, planned = PLAN[t.__name__]
    start = len(RESULTS)
    try:
        t(*a)
    except Exception as e:
        import traceback
        record(group, "the group crashed (%s); the rest of it did not run" % type(e).__name__, False,
               "%s: %s\n%s" % (type(e).__name__, e, traceback.format_exc()[-1500:]))
        done = len(RESULTS) - start
        for i in range(done, planned):
            record(group, "check %d of %d did not run (the group crashed)" % (i + 1, planned), False, "")
    if len(RESULTS) - start != planned and not [x for x in RESULTS[start:] if not x[2]]:
        record(group, "the group recorded %d checks, expected %d" % (len(RESULTS) - start, planned), False, "")


def main():
    print("MOADIX confined-engine suite (Terminal only). It never touches anything not labelled moadix.run=%s*." % PREFIX)
    hits = no_prune.scan(REPO)
    record("safeguards", "static: no pruning and no compose down with volumes in the runner, the gates or this suite",
           not hits, hits)
    if hits:
        print("REFUSED: a forbidden removal command is present (above)")
        return 2
    why, stopped = preflight()
    if why:
        print("REFUSED: the suite starts only when no foreign container or compose project is running and the "
              "images are cleared:")
        for w in why:
            print("  - %s" % w)
        if stopped:
            print("  (stopped compose projects found, left untouched: %s)" % ", ".join(stopped))
        return 2
    if stopped:
        print("found stopped compose projects (they do not block; left untouched, never started, stopped or "
              "inspected): %s" % ", ".join(stopped))
    node, py = confined.image("node"), confined.image("python")
    for img in [confined.image(x) for x in NEEDED]:
        p = docker(["pull", "-q", img], timeout=900)
        if p.returncode != 0:
            print("REFUSED: pulling %s failed: %s" % (img, p.stderr.strip()[:300]))
            return 2
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
    own_img = own_images()
    before = snapshot(own_img)
    print("recorded before: %s" % ", ".join("%d %s" % (len(v), k) for k, v in before.items()))
    for t, a in ((test_secrets, (node,)), (test_host, (node,)), (test_network, (node, py)), (test_limits, (node,)),
                 (test_output, (node,)), (test_user, (node,)), (test_smoke, (node,)), (test_rel076, (node,))):
        run_group(t, a)
    left = built_images()
    if left:
        print("images built by the live smoke runs, labelled moadix.run=%s*, left in place (nothing here removes an "
              "image): %s" % (PREFIX, ", ".join(i[:19] for i in left)))
    cs, vols, nets = inventory()
    mine = [c["name"] for c in cs if ours(c["run"])] + [v for v in vols if ours((v.split("\t") + [""])[1])] + \
           [n for n in nets if ours((n.split("\t") + ["", ""])[2])]
    record("cleanup", "nothing this suite created is left (containers, volumes, networks)", not mine, mine)
    after = snapshot(own_img)
    diff = difference(before, after)
    record("cleanup", "every container, volume, network and image that is not the suite's is exactly as before "
                      "(%s)" % ", ".join("%d %s" % (len(v), k) for k, v in before.items()), not diff, "")
    for d in diff:
        print("      DIFFERENCE %s" % d)
    n = len(RESULTS)
    bad = [r for r in RESULTS if not r[2]]
    for g, name, _ok in bad:
        print("FAILED [%s] %s" % (g, name))
    print("\n%d checks, %d passed, %d failed (%d s)" % (n, n - len(bad), len(bad), time.time() - T0))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
