#!/usr/bin/python3
"""TEST DOUBLE for the Docker CLI as gate/confined.py uses it (increment 7d). Fixture gates only: the
runner uses it when tests/lib/_testguard.py is in the gate copy and MOADIX_TEST_ENGINE names it; the
installed gate never does. It runs nothing: named volumes are folders, `docker cp` extracts and copies
tars, and `docker run` writes canned tool output into the run's /out volume, chosen by the container
name's gate suffix from $MOADIX_DOUBLE_OUTPUTS/<gate>/ (default tests/exec/double/pass). Every call is
logged to calls.log so a test can check the argv the runner built (no host path, no socket, limits).
"""
import json
import os
import re
import shutil
import sys
import tarfile

HERE = os.path.dirname(os.path.realpath(__file__))
BASE = os.environ.get("MOADIX_DOUBLE_DIR") or os.path.join(HERE, "engine-double")
REPO = os.environ.get("MOADIX_GUARD_REPO") or os.path.dirname(os.path.dirname(HERE))
OUTPUTS = os.environ.get("MOADIX_DOUBLE_OUTPUTS") or os.path.join(REPO, "tests", "exec", "double", "pass")
GATES = ("pytm", "likec4", "dependencycruiser", "knip", "eslint", "tsc", "stryker", "tests", "schemathesis", "zap",
         "lhci", "axe")


def load():
    try:
        with open(os.path.join(BASE, "state.json")) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {"containers": {}, "volumes": {}, "networks": {}}


def save(s):
    os.makedirs(BASE, exist_ok=True)
    with open(os.path.join(BASE, "state.json"), "w") as f:
        json.dump(s, f)


def vol_dir(name):
    d = os.path.join(BASE, "vols", name)
    os.makedirs(d, exist_ok=True)
    return d


def opt(args, flag):
    out = []
    for i, a in enumerate(args):
        if a == flag and i + 1 < len(args):
            out.append(args[i + 1])
    return out


def label_of(args):
    for v in opt(args, "--label"):
        if v.startswith("moadix.run="):
            return v
    return None


def labels_of(args):
    """Every --label k=v of a call (0.7.6: the runner labels its objects with owner, pid and start time too)."""
    return dict(v.split("=", 1) if "=" in v else (v, "") for v in opt(args, "--label"))


def matches(labels, filters):
    """docker's label filters: label=k (present) or label=k=v, all of them."""
    for f in filters:
        if not f.startswith("label="):
            continue
        kv = f[len("label="):]
        k, v = kv.split("=", 1) if "=" in kv else (kv, None)
        if k not in labels or (v is not None and labels[k] != v):
            return False
    return True


def render(fmt, name, labels):
    """--format with {{.Names}}, {{.Name}}, {{.ID}} and {{.Label "k"}} (the forms the runner and the suite use)."""
    out = re.sub(r'\{\{\s*\.Label\s+"([^"]+)"\s*\}\}', lambda m: labels.get(m.group(1), ""), fmt)
    out = re.sub(r"\{\{\s*\.(Names|Name|ID)\s*\}\}", name, out)
    return out.replace("\\t", "\t")


def listing(objs, a):
    """ps / volume ls / network ls: filter by labels (and name), print names or the --format template."""
    filters = opt(a, "--filter")
    nm = next((x.split("name=", 1)[1] for x in filters if x.startswith("name=")), None)
    fmt = (opt(a, "--format") or [None])[0]
    rows = []
    for name, labels in objs:
        if not matches(labels, filters) or (nm is not None and "^/%s$" % name != nm):
            continue
        rows.append(render(fmt, name, labels) if fmt else name)
    print("\n".join(rows))


def mounts(args):
    m = {}
    for v in opt(args, "--mount"):
        kv = dict(x.split("=", 1) for x in v.split(",") if "=" in x)
        m[kv.get("dst")] = kv.get("src")
    return m


# 0.7.4 (the 0.7.3 engine run): the double now refuses what the real engine or the pinned images refuse, so
# the sandbox suites catch the argument combinations the 0.7.3 run met for the first time.
BUILTIN_NETWORKS = ("none", "bridge", "host", "default")
CONFLICT = 'Error response from daemon: Conflict. The container name "/%s" is already in use by container %s.'



def refuse(msg, code=1):
    sys.stderr.write(msg + "\n")
    return code


def plain_tar_head(h):
    """As the engine decides `docker build -`: a tar only when stdin's first 512 bytes are a whole header."""
    if len(h) < 512 or h[257:262] != b"ustar" or h[156:157] in (b"x", b"g", b"L", b"K"):
        return False
    try:
        want = int(h[148:156].split(b"\0", 1)[0].strip() or b"0", 8)
    except ValueError:
        return False
    return want == sum(h[:148]) + 8 * 32 + sum(h[156:])


# 0.7.5 (the 0.7.4 engine run): the runner replaces the image's PATH with its own fixed one
# (/usr/local/bin:/usr/bin:/bin). The pinned images that keep tools elsewhere, measured on the real images
# with `type -a` under the runner's PATH; every other command the gates use is in /usr/local/bin, /usr/bin
# or /bin in its image. A command named by a bare word resolves only when its directory is on the run's PATH;
# the engine-run shell then fails with 127, as bash and the postgres entrypoint did on the real engine.
OFF_PATH = {
    "zaproxy": {"zap-baseline.py": "/zap", "zap-full-scan.py": "/zap", "zap-api-scan.py": "/zap",
                "zap-x.sh": "/zap", "zap.sh": "/zap"},
    "postgres": {"postgres": "/usr/lib/postgresql/17/bin", "initdb": "/usr/lib/postgresql/17/bin",
                 "pg_ctl": "/usr/lib/postgresql/17/bin"},
}
IMAGE_PATH = {"zaproxy": "/usr/lib/jvm/java-17-openjdk-arm64/bin:/zap/:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
              "postgres": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/usr/lib/postgresql/17/bin"}
DEFAULT_PATH = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"  # Debian's, as the node and python images
# 0.8.1 (the 0.8.0 engine run): the volumes an image declares with VOLUME. A container of it gets an anonymous volume
# (no label) for each one no --mount covers; `docker rm --volumes` (-v), or a `run --rm` ending, removes it; `rm`
# without it leaves it.
IMAGE_VOLUMES = {"postgres": ["/var/lib/postgresql/data"]}
KEYWORDS = ("do", "then", "else", "until", "while", "if", "!", "{", "exec", "time")


def command_words(script):
    """The words in command position of a shell script (enough for the gates' own scripts)."""
    words = []
    for seg in re.split(r"[;&|()\n]+", re.sub(r"'[^']*'", "''", script)):
        toks = seg.split()
        while toks and (toks[0] in KEYWORDS or re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", toks[0])):
            toks.pop(0)
        if toks and not toks[0].startswith((">", "<", "2>", "[", "$")):
            words.append(toks[0])
    return words


def image_key(ref, s=None):
    """The OFF_PATH key of an image: a pinned ref names it; 0.8.0: an image the double built has its base image's."""
    for img in (s or {}).get("images") or []:
        if img.get("tag") and img["tag"] == ref:
            return img.get("base")
    return next((k for k in OFF_PATH if "/%s" % k in ref), None)


def image_path(ref, s=None):
    """0.8.0: the PATH an image declares (Config.Env), as `docker image inspect` reports it."""
    key = image_key(ref, s)
    return IMAGE_PATH.get(key, DEFAULT_PATH) if key else DEFAULT_PATH


def run_image(a, s=None):
    """The image of a `docker run`: the gate names every pinned image by digest; a built one by its tag."""
    tags = {img["tag"] for img in (s or {}).get("images") or [] if img.get("tag")}
    return next((x for x in a if "@sha256:" in x or x in tags), "")


def off_path(a, s=None):
    """None, or the bash message for the first command the run cannot find on its PATH."""
    ref = run_image(a, s)
    key = image_key(ref, s)
    if not key:
        return None
    path = next((x.split("=", 1)[1] for x in opt(a, "--env") + opt(a, "-e") if x.startswith("PATH=")), image_path(ref, s))
    dirs = {d.rstrip("/") for d in path.split(":")}
    if "-c" in a and a.index("-c") + 1 < len(a):
        cmds = command_words(a[a.index("-c") + 1])
    elif key == "postgres":
        cmds = ["initdb", "postgres"]  # the image's entrypoint runs both by name
    else:
        cmds = []
    for c in cmds:
        if "/" not in c and c in OFF_PATH[key] and OFF_PATH[key][c] not in dirs:
            if key == "postgres":
                return "/usr/local/bin/docker-entrypoint.sh: line 92: %s: command not found" % c
            return "bash: line 1: %s: command not found" % c
    return None


def build_images(data, dockerfile, build_labels, classic):
    """0.7.9: the images a build leaves, each with its labels, as the engine makes them. The classic builder
    (DOCKER_BUILDKIT=0) keeps one image per instruction after FROM and the last image of every stage (untagged);
    BuildKit keeps only the final image. `--label` reaches only the final image; a LABEL instruction reaches the
    images after it in its stage. None when the Dockerfile is not in the context."""
    import io
    try:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:*") as tf:
            text = tf.extractfile(tf.getmember(os.path.normpath(dockerfile))).read().decode("utf-8", "replace")
    except (KeyError, tarfile.TarError, AttributeError):
        return None
    with open(os.path.join(BASE, "builds.log"), "a") as f:
        f.write(json.dumps({"dockerfile": text, "labels": build_labels, "classic": classic}) + "\n")
    instrs, cur = [], ""
    for ln in text.split("\n"):
        st = ln.strip()
        if not st or st.startswith("#"):
            continue
        cur += " " + st.rstrip("\\")
        if not st.endswith("\\"):
            instrs.append(cur.strip())
            cur = ""
    images, labels, stage = [], None, []
    base, aliases = None, {}
    for ins in instrs:
        word = ins.split(None, 1)[0].upper()
        if word == "FROM":
            # 0.8.0: the final stage's base image (an earlier stage's alias followed), whose PATH the built image keeps
            f = ins.split()[1:]
            f = [x for x in f if not x.startswith("--")]
            ref = f[0] if f else ""
            base = aliases.get(ref.lower(), image_key(ref))
            if len(f) >= 3 and f[1].upper() == "AS":
                aliases[f[2].lower()] = base
            if stage:
                images.append(stage)
            labels, stage = {}, []
            continue
        if labels is None:
            continue  # ARG before the first FROM
        if word == "LABEL":
            for kv in re.findall(r"(\S+?)=(\S+)", ins[len("LABEL"):]):
                labels[kv[0]] = kv[1].strip('"')
        stage.append(dict(labels))
    if stage:
        images.append(stage)
    final = dict((images[-1][-1] if images and images[-1] else {}), **build_labels)
    if not classic:
        return [final], base
    out = [img for st in images for img in st]  # every step's image, every stage's last one among them
    return out + [final], base


def dockerfile_text(data, dockerfile):
    import io
    try:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:*") as tf:
            return tf.extractfile(tf.getmember(os.path.normpath(dockerfile))).read().decode("utf-8", "replace")
    except (KeyError, tarfile.TarError, AttributeError):
        return ""


def network_ok(s, net):
    return net in BUILTIN_NETWORKS or net in s["networks"]


def main():
    a = sys.argv[1:]
    os.makedirs(BASE, exist_ok=True)
    with open(os.path.join(BASE, "calls.log"), "a") as f:
        f.write(json.dumps(a) + "\n")
    s = load()
    if not a:
        return 2
    cmd = a[0]
    if cmd == "version":
        print("double-1.0")
        return 0
    s.setdefault("labels", {})
    if cmd == "volume" and a[1] == "create":
        s["volumes"][a[-1]] = label_of(a)
        s["labels"]["v:" + a[-1]] = labels_of(a)
        vol_dir(a[-1])
    elif cmd == "volume" and a[1] == "ls":
        listing([(v, s["labels"].get("v:" + v) or dict([lb.split("=", 1)] if lb else [])) for v, lb in s["volumes"].items()], a)
    elif cmd == "volume" and a[1] == "rm":
        for v in a[2:]:
            if not v.startswith("-"):
                s["volumes"].pop(v, None)
                s["labels"].pop("v:" + v, None)
                shutil.rmtree(os.path.join(BASE, "vols", v), ignore_errors=True)
    elif cmd == "network" and a[1] == "create":
        if a[-1] in s["networks"]:  # 0.7.9 (the 0.7.8 product run): the engine refuses a second network of a name
            return refuse("Error response from daemon: network with name %s already exists" % a[-1])
        s["networks"][a[-1]] = label_of(a)
        s["labels"]["n:" + a[-1]] = labels_of(a)
    elif cmd == "network" and a[1] == "ls":
        listing([(n, s["labels"].get("n:" + n) or dict([lb.split("=", 1)] if lb else [])) for n, lb in s["networks"].items()], a)
    elif cmd == "network" and a[1] == "rm":
        for n in a[2:]:
            users = [c for c, v in s["containers"].items() if n in (v.get("nets") or [])]
            if users:  # as the engine: a network a container is still on cannot be removed
                save(s)
                return refuse("Error response from daemon: error while removing network: network %s has active "
                              "endpoints (name:%s)" % (n, users[0]))
            s["networks"].pop(n, None)
            s["labels"].pop("n:" + n, None)
    elif cmd == "network" and a[1] == "connect":
        net = [x for x in a[2:] if not x.startswith("-") and x not in opt(a, "--alias")][0]
        if net not in s["networks"]:
            return refuse("Error response from daemon: network %s not found" % net)
        c = [x for x in a[2:] if not x.startswith("-") and x not in opt(a, "--alias")][-1]
        if c in s["containers"]:
            s["containers"][c].setdefault("nets", []).append(net)
    elif cmd == "network":
        pass
    elif cmd == "create":
        name = opt(a, "--name")[0]
        if name in s["containers"]:
            return refuse(CONFLICT % (name, name), 125)
        s["containers"][name] = {"label": label_of(a), "labels": labels_of(a), "mounts": mounts(a)}
    elif cmd == "cp":
        src, dst = a[1], a[2]
        if src == "-":
            c, path = dst.split(":", 1)
            vol = s["containers"][c]["mounts"].get(path)
            with tarfile.open(fileobj=sys.stdin.buffer, mode="r|*") as tf:
                tf.extractall(vol_dir(vol))  # noqa: S202 (test double, fixture content)
        else:
            c, path = src.split(":", 1)
            vol = s["containers"][c]["mounts"].get(path.rstrip("/.").rstrip("/") or path)
            vd = vol_dir(vol)
            os.makedirs(dst, exist_ok=True)
            for n in os.listdir(vd):
                p = os.path.join(vd, n)
                (shutil.copytree if os.path.isdir(p) else shutil.copy)(p, os.path.join(dst, n))
    elif cmd == "rm":
        for c in a[1:]:
            if not c.startswith("-"):
                gone = s["containers"].pop(c, None) or {}
                if "-v" in a[1:] or "--volumes" in a[1:]:  # 0.8.1: as the engine, with its anonymous volumes
                    for v in gone.get("anon") or []:
                        s["volumes"].pop(v, None)
    elif cmd == "ps":
        listing([(c, v.get("labels") or dict([v["label"].split("=", 1)] if v.get("label") else []))
                 for c, v in s["containers"].items()], a)
    elif cmd == "inspect":
        fmt = (opt(a, "--format") or [""])[0]
        if "State.Status" in fmt:  # 0.8.0: a service's state and exit code, as the engine reports them
            c = s["containers"].get(a[-1])
            if c is None:
                return refuse("Error: No such object: %s" % a[-1])
            print("%s %s" % (c.get("state") or "running", c.get("exit") or 0))
        else:
            print("false" if len(a) > 3 else "")
    elif cmd == "build":
        data = sys.stdin.buffer.read()
        net = (opt(a, "--network") or ["default"])[0]
        if os.environ.get("DOCKER_BUILDKIT") == "0":
            if not network_ok(s, net):
                return refuse("ERROR: network %s not found" % net)
        elif net not in ("none", "default", "host"):
            return refuse("ERROR: network mode %r not supported by buildkit" % net)
        if os.environ.get("MOADIX_DOUBLE_BUILD_FAIL"):  # a test asks for a failing build, with engine output
            sys.stdout.write("#5 [2/2] RUN npm ci\n#5 npm ERR! token=npm_" + "Q1w2E3r4T5y6" * 3 + "\n")
            return refuse("ERROR: failed to build: process \"/bin/sh -c npm ci\" did not complete successfully: exit "
                          "code: 1")
        if "-" in a[1:] and opt(a, "-f") and not plain_tar_head(data[:512]):
            return refuse("ERROR: failed to build: ambiguous Dockerfile source: both stdin and flag correspond to "
                          "Dockerfiles")
        built = build_images(data, (opt(a, "-f") or ["Dockerfile"])[0], labels_of(a), os.environ.get("DOCKER_BUILDKIT") == "0")
        if built is None:
            return refuse("ERROR: failed to build: the Dockerfile is not in the context")
        built, base = built
        tag = (opt(a, "-t") or [None])[0]
        text = dockerfile_text(data, (opt(a, "-f") or ["Dockerfile"])[0])
        for i, labels in enumerate(built):
            last = i == len(built) - 1
            s.setdefault("images", []).append({"id": "sha256:%064x" % (len(s.get("images") or []) + 1),
                                               "tag": tag if last else None, "labels": labels,
                                               "base": base, "dockerfile": text if last else None})
    elif cmd == "image" and a[1] == "inspect" and "{{.Id}}" in (opt(a, "--format") or [""])[0]:
        # 0.8.2: a built image's ID (check-trivy records the images the gate builds by it)
        img = next((x for x in s.get("images") or [] if x.get("tag") == a[-1]), None)
        if img is None:
            return refuse("Error response from daemon: No such image: %s" % a[-1])
        print(img["id"])
    elif cmd == "save":
        # 0.8.2: `docker save <tag>` to stdout: a tar holding the double's record of the image (its ID, base and
        # Dockerfile), which the fixture trivy reads in place of layers
        import io
        img = next((x for x in s.get("images") or [] if x.get("tag") == a[-1]), None)
        if img is None:
            return refuse("Error response from daemon: reference does not exist")
        raw = json.dumps({"id": img["id"], "tag": img["tag"], "base": img.get("base"),
                          "dockerfile": img.get("dockerfile") or ""}).encode()
        with tarfile.open(fileobj=sys.stdout.buffer, mode="w|") as tf:
            ti = tarfile.TarInfo("moadix-double-image.json")
            ti.size = len(raw)
            tf.addfile(ti, io.BytesIO(raw))
        sys.stdout.buffer.flush()
        with open(os.path.join(BASE, "saves.log"), "a") as f:
            f.write(json.dumps({"tag": img["tag"], "id": img["id"]}) + "\n")
    elif cmd == "image" and a[1] == "inspect":
        # 0.8.0: the image's own environment (the runner keeps its PATH); --format '{{json .Config.Env}}' only
        print(json.dumps(["PATH=%s" % image_path(a[-1], s)]))
    elif cmd == "logs":
        # 0.8.0: a service container's output (stdout, then stderr), the last --tail lines of each
        c = s["containers"].get(a[-1])
        if c is None:
            return refuse("Error response from daemon: No such container: %s" % a[-1])
        n = int((opt(a, "--tail") or ["100000"])[0])
        for stream, key in ((sys.stdout, "stdout"), (sys.stderr, "stderr")):
            ls = (c.get(key) or "").splitlines()[-n:]
            stream.write("".join(x + "\n" for x in ls))
    elif cmd == "image" and a[1] == "ls":
        imgs = [x for x in s.get("images") or [] if "-a" in a or x["tag"]]
        filters = opt(a, "--filter")
        print("\n".join(x["id"] for x in imgs if matches(x["labels"], filters)))
    elif cmd == "run" and "getent" in a:
        save(s)
        return 0  # 0.7.3: the runner's passwd check (confined.Run.check_user); the double's images have the entry
    elif cmd == "run":
        net = (opt(a, "--network") or ["bridge"])[0]
        if not network_ok(s, net):
            return refuse("docker: Error response from daemon: network %s not found" % net, 125)
        if opt(a, "--network-alias") and net in BUILTIN_NETWORKS:
            return refuse("docker: Error response from daemon: network-scoped alias is supported only for containers "
                          "in user defined networks", 125)
        if "sh" in a and "-c" in a and "/dev/tcp/" in a[a.index("-c") + 1 if a.index("-c") + 1 < len(a) else -1]:
            # the pinned images' /bin/sh is dash, which has no /dev/tcp: the wait never succeeds
            return refuse("sh: 1: cannot create /dev/tcp/sut.moadix.test/3000: Directory nonexistent", 3)
        missing = off_path(a, s)
        if missing and "-d" not in a:
            return refuse(missing, 127)
        name = (opt(a, "--name") or ["anon"])[0]
        m = mounts(a)
        if name in s["containers"]:
            # 0.7.6 (task-tracker MF-54): the engine refuses a second container with a name in use
            return refuse("docker: " + CONFLICT % (name, name), 125)
        if "-d" in a or "--rm" not in a:
            s["containers"][name] = {"label": label_of(a), "labels": labels_of(a), "mounts": m, "nets": [net]}
            anon = []
            for d in IMAGE_VOLUMES.get(image_key(run_image(a, s), s) or "", []):
                if d not in m:
                    v = "%064x" % (len(s["volumes"]) + 1 + len(s.get("anon_made") or []))
                    s.setdefault("anon_made", []).append(v)
                    s["volumes"][v] = ""
                    anon.append(v)
            s["containers"][name]["anon"] = anon
        if "-d" in a:
            # 0.8.0 (task-tracker MF-56, MF-57): as the engine, a detached run starts; a command its PATH cannot find
            # stops the container with 127 and its message. MOADIX_DOUBLE_SVC ({service: {exit, stdout, stderr}})
            # stops a service the way a test asks (a configuration error, say).
            c = s["containers"][name]
            svc = re.search(r"-svc-([a-z0-9_]+?)(-\d+)?$", name)
            want = json.loads(os.environ.get("MOADIX_DOUBLE_SVC") or "{}").get(svc.group(1) if svc else "", None)
            if missing:
                c.update(state="exited", exit=127, stderr=missing)
            elif want:
                c.update(state="exited" if want.get("exit") is not None else "running", exit=want.get("exit") or 0,
                         stdout=want.get("stdout") or "", stderr=want.get("stderr") or "")
            else:
                c.update(state="running", exit=0)
        sleep = os.environ.get("MOADIX_DOUBLE_SLEEP")
        if sleep and name.rsplit("-", 1)[-1] in GATES and "-d" not in a:
            save(s)  # a test stops the gate during this run (0.7.6: the run is still removed)
            import time
            time.sleep(float(sleep))
        suffix = name.rsplit("-", 1)[-1]
        out_vol = m.get("/out") or m.get("/zap/wrk")
        script = a[a.index("-c") + 1] if "-c" in a and a.index("-c") + 1 < len(a) else ""
        stopped = [c for c, v in s["containers"].items() if net in (v.get("nets") or []) and v.get("state") == "exited"]
        if suffix in GATES and out_vol and "-d" not in a and "/dev/tcp/" in script and stopped:
            # 0.8.0: a live stack with a stopped service never serves the app (the app needs its database, or is the
            # one that stopped): the gate's wait loop gives up, as on the engine
            with open(os.path.join(vol_dir(out_vol), "wait.log"), "w") as f:
                f.write("the app never listened on port 3000\n")
            save(s)
            return 3
        if suffix in GATES and out_vol and "-d" not in a:
            src = os.path.join(OUTPUTS, suffix)
            if os.path.isdir(src):
                for n in os.listdir(src):
                    if n == "exit":
                        continue
                    p = os.path.join(src, n)
                    (shutil.copytree if os.path.isdir(p) else shutil.copy)(p, os.path.join(vol_dir(out_vol), n))
                if os.path.exists(os.path.join(src, "exit")):
                    save(s)
                    return int(open(os.path.join(src, "exit")).read().strip() or "0")
    save(s)
    return 0


if __name__ == "__main__":
    sys.exit(main())
