"""0.7.5 (the 0.7.4 engine run): what the engine suite's secrets check asserts, as a property, not a string.

The 0.7.4 check also required the literal `HOME=/tmp/home` in the output; 0.7.4 moved HOME to /tmp, so the
check failed while nothing of the host was visible. It now asserts, over a run's output:
  * the canary (a value planted in the host's environment and in a host file) appears nowhere;
  * every variable in the run's environment (and in process 1's) is one of the runner's fixed names, one
    of the image's own (`docker image inspect` Config.Env) or one the engine or shell sets in every
    container (HOSTNAME, PWD, SHLVL, _); and the runner's names carry the runner's values;
  * no value names a host home (/Users/) and no SSH agent or token variable is present.

The probe script prints its sections between markers; `problems` reads them back.
"""
import re

MARK = "@@moadix-"
SECTIONS = ("env", "pid1", "files", "grep")
ENGINE_NAMES = ("HOSTNAME", "PWD", "SHLVL", "_", "OLDPWD")
NAME = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$")


def probe(canary):
    """The script the run executes (sh): its environment, process 1's, home folders, and a search for the canary."""
    return ("echo %senv; env; echo %spid1; tr '\\0' '\\n' < /proc/1/environ 2>/dev/null; echo; "
            "echo %sfiles; ls -la /root /home /run/secrets 2>&1; "
            "echo %sgrep; grep -rls %s / --exclude-dir=proc --exclude-dir=sys 2>/dev/null | head -3; "
            "echo %send; true" % (MARK, MARK, MARK, MARK, canary, MARK))


def sections(out):
    cur, got = None, {s: [] for s in SECTIONS}
    for ln in out.splitlines():
        if ln.startswith(MARK):
            cur = ln[len(MARK):].strip()
            continue
        if cur in got:
            got[cur].append(ln)
    return got


def problems(out, err, canary, runner_env, image_env_names):
    """[] when nothing of the host is in the run, else what was found. runner_env: {name: value} the runner
    sets; image_env_names: the names the image declares itself."""
    found = []
    if canary in out or canary in err:
        found.append("the canary is visible in the run")
    got = sections(out)
    if not got["env"]:
        found.append("the probe printed no environment (the run did not execute it)")
    allowed = set(runner_env) | set(image_env_names) | set(ENGINE_NAMES)
    for sec in ("env", "pid1"):
        for ln in got[sec]:
            m = NAME.match(ln)
            if not m:
                continue  # an empty line, or the continuation of a multi-line value
            k, v = m.groups()
            if k not in allowed:
                found.append("%s: variable %s is neither the runner's nor the image's own" % (sec, k))
            elif k in runner_env and v != runner_env[k]:
                found.append("%s: %s=%s is not the runner's value %s" % (sec, k, v, runner_env[k]))
            if "/Users/" in v or re.search(r"SSH_AUTH_SOCK|TOKEN|SECRET|PASSWORD", k):
                found.append("%s: %s looks like the host's" % (sec, k))
    if any(x.strip() for x in got["grep"]):
        found.append("a file holding the canary is in the run: %s" % " ".join(x.strip() for x in got["grep"]))
    return sorted(set(found))
