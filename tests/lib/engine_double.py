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


def mounts(args):
    m = {}
    for v in opt(args, "--mount"):
        kv = dict(x.split("=", 1) for x in v.split(",") if "=" in x)
        m[kv.get("dst")] = kv.get("src")
    return m


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
    if cmd == "volume" and a[1] == "create":
        s["volumes"][a[-1]] = label_of(a)
        vol_dir(a[-1])
    elif cmd == "volume" and a[1] == "ls":
        lab = next((x.split("label=", 1)[1] for x in a if x.startswith("label=")), None)
        print("\n".join(v for v, lb in s["volumes"].items() if lb == lab))
    elif cmd == "volume" and a[1] == "rm":
        for v in a[2:]:
            if not v.startswith("-"):
                s["volumes"].pop(v, None)
                shutil.rmtree(os.path.join(BASE, "vols", v), ignore_errors=True)
    elif cmd == "network" and a[1] == "create":
        s["networks"][a[-1]] = label_of(a)
    elif cmd == "network" and a[1] == "ls":
        lab = next((x.split("label=", 1)[1] for x in a if x.startswith("label=")), None)
        print("\n".join(n for n, lb in s["networks"].items() if lb == lab))
    elif cmd == "network" and a[1] == "rm":
        for n in a[2:]:
            s["networks"].pop(n, None)
    elif cmd == "network":
        pass
    elif cmd == "create":
        name = opt(a, "--name")[0]
        s["containers"][name] = {"label": label_of(a), "mounts": mounts(a)}
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
                s["containers"].pop(c, None)
    elif cmd == "ps":
        lab = next((x.split("label=", 1)[1] for x in a if x.startswith("label=")), None)
        nm = next((x.split("name=", 1)[1] for x in a if x.startswith("name=")), None)
        print("\n".join(c for c, v in s["containers"].items() if v.get("label") == lab and
                        (nm is None or "^/%s$" % c == nm)))
    elif cmd == "inspect":
        print("false" if len(a) > 3 else "")
    elif cmd == "build":
        sys.stdin.buffer.read()
    elif cmd == "run" and "getent" in a:
        save(s)
        return 0  # 0.7.3: the runner's passwd check (confined.Run.check_user); the double's images have the entry
    elif cmd == "run":
        name = (opt(a, "--name") or ["anon"])[0]
        m = mounts(a)
        if "-d" in a or "--rm" not in a:
            s["containers"][name] = {"label": label_of(a), "mounts": m}
        suffix = name.rsplit("-", 1)[-1]
        out_vol = m.get("/out") or m.get("/zap/wrk")
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
