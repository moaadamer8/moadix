# 0.7.5: the secrets check as a property, and commands on the run's PATH (the 0.7.4 engine run)

Source: the operator's run of `tests/confined-engine` on 0.7.4: 49 checks, 47 passed, 2 failed, foreign objects unchanged. Every smoke run passed except ZAP.

## 1. Failure 1: `[secrets]` — the test, not a leak

**The assertion that failed.** The first secrets check was:

```
rc == 0 and canary not in out + err and "HOME=/tmp/home" in out
```

The run's output (in the operator's report) shows `rc == 0`, and the canary is in neither the environment nor any file. The third term failed: 0.7.4 moved HOME to `/tmp`, so the output holds `HOME=/tmp` and the literal `HOME=/tmp/home` is absent. Nothing of the host was visible:
- every variable in that output is either one the runner sets (`PATH HOME LANG CI TZ`), one of the node image's own (`NODE_VERSION YARN_VERSION`), or one the engine or shell sets (`HOSTNAME PWD`);
- `/run/secrets` does not exist;
- `/home` holds only the image's `node` folder;
- `/root` is unreadable to uid 65534.

The output is printed twice because the probe prints the shell's environment and then process 1's, and both are the same shell.

**The fix** (`tests/lib/env_leak.py`, used by `tests/confined-engine`). The check now asserts the property, not a string. It fails when:
- the canary appears anywhere in the run's output;
- a variable in the run's or process 1's environment is not one of the runner's fixed names (`confined.RUN_ENV_NAMES`), one of the image's own (`docker image inspect` Config.Env of the pinned image), or `HOSTNAME`/`PWD`/`SHLVL`/`_`;
- a runner name carries a value other than the runner's own (a host HOME, say);
- a value names `/Users/`, or an SSH agent or token variable is present;
- a file holding the canary is found under `/` (outside `/proc` and `/sys`);
- the probe printed no environment at all, so a run that did not execute cannot pass.

**The control** (a new check, so the engine suite has 50). The suite starts a deliberately unconfined container of its own: labelled, `--rm`, on network `none`, with the canary variable passed through from the host (`--env MOADIX_ENGINE_CANARY`) and the canary folder mounted (`--volume <host folder>:/hostcanary:ro`). The same check must fail on it, naming both the variable and the file.

`tests/rel075` runs the property check over the 0.7.4 run's output, which passes, and over five hostile variants, each of which fails and is named:
- a host variable;
- a variable that is neither the runner's nor the image's;
- a host value under a runner name;
- an SSH agent;
- a file holding the canary.

**Why `HOME=/tmp` is safe.**
- `/tmp` is the run's own tmpfs: `--tmpfs /tmp:rw,nosuid,nodev,size=<tier tmp_mb>,uid=<run uid>`. The engine creates it empty with each container and discards it when the container is removed (every run is removed). It is never a volume, never shared between containers, and never copied out as a whole. Only named report files go to `/out` (the lhci script copies `lhr-*.json`).
- A later run therefore cannot read it. What does persist between steps of one gate run is only the named volumes: `/deps`, written by the install step and mounted read-only afterwards; `/out`, the reports; and the read-only `/src`. All are removed with the run.
- Nothing a tool could store there is a credential. No secret enters a run: secret-named variables are refused before the engine is called, and the install steps get only the proxy address.
- What tools do write under `$HOME`:
  - npm's cache (`/tmp/.npm`, in install steps);
  - ZAP's `zap.yaml` and its home (`/tmp/zaphome`);
  - LHCI's `.lighthouseci`;
  - Stryker's temp folder.
  pip runs with `--no-cache-dir`.
- The size cap is fail-closed. A tool that fills `/tmp` gets ENOSPC and the gate reports the failure. tmpfs pages also count against the run's memory limit, so filling it can instead end as the memory kill, which the gate reports as a refusal, never as a pass.

## 2. Failure 2: `[smoke] zap` — `zap-baseline.py: command not found`

**Cause.** The runner replaces the image's PATH with its own fixed `/usr/local/bin:/usr/bin:/bin`. The ZAP image keeps its scripts in `/zap`, which only the image's own PATH adds. My 0.7.4 hand run used the image's PATH, so it differed from the gate's invocation.

**Reproduced on the real engine.** I used the gate's exact run options (uid 65534, `--cap-drop ALL`, read-only root, the tmpfs, tier L limits, the runner's environment), on my own labelled objects, all removed afterwards. The result was exit 127, `bash: line 1: zap-baseline.py: command not found`.

**Fix** (`check_exec.live_script`):
- `/zap/zap-baseline.py` is named by its absolute path. It starts ZAP as `/zap/zap-x.sh`, and `java`, `python` and `Xvfb` are in `/usr/bin`, so nothing else needs `/zap` on PATH.
- The script runs from `/tmp`, because zap-baseline writes `zap.out` to its working directory and `/zap` is on the read-only root.
- The Java heap is set to half the run's memory (`-Xmx`, through `-z`). ZAP's start script sizes the heap from the host's `/proc/meminfo`, not from the run's limit.

**Verified on the real engine.** The gate's exact 0.7.5 script ran with the gate's options. It was loaded as a file because the sandbox does not let me pass an inline script with redirects to docker. Results:
- `run.rc` 0;
- `zap.json` written;
- the gate's `zap-rules.tsv` read;
- 59 PASS, 3 WARN, 0 FAIL.

**A further ZAP defect found on the way.** The wait for the app wrote its note to `/out/wait.log`. A ZAP run has no `/out` (its output folder is `/zap/wrk`), and the root is read-only, so the write failed and `&& exit 3` never ran. With an app that never listened, ZAP would have looped until the wall clock. The note now goes to the gate's own output folder, and the exit no longer depends on writing it.

**The same kind of gap elsewhere.** I checked every pinned image's own PATH:
- node, node-full, python and chromium keep everything the gates use in `/usr/local/bin`, `/usr/bin` or `/bin`.
- postgres keeps `postgres`, `initdb` and `pg_ctl` in `/usr/lib/postgresql/17/bin`. Started the gate's way (uid 999, read-only root, the runner's PATH), the test service failed on the real engine: `docker-entrypoint.sh: line 92: initdb: command not found`, exit 127.
- **Fix:** the gate's service configuration now carries the image's tool directory (`confinement.yaml` `services.postgres.path`). The runner takes it only from there, checks it is a list of absolute directories before the engine is called, and never takes it from the product. Re-run the gate's way, postgres accepted connections and answered a query as `moadix` on `test`.

**The fake docker** (`tests/lib/engine_double.py`). It now resolves every bare command word of a run's script against the run's PATH, using a table of the pinned images' off-PATH tools, measured with `type -a` on the real images. A word whose directory is missing fails with 127, as bash and the postgres entrypoint did. It also does this for the postgres entrypoint, which has no script.

## Tests

- `tests/rel075/run.py`: new suite, 28 checks:
  - secrets 10;
  - path 9;
  - wait 3;
  - services 5;
  - guard 1.
- `tests/inc7d`: the engine suite's fixed total is now 50. The suite still inspects only its own pinned images, through one helper.
- The counts of all suites run here are in the commit message.
- The Terminal suites are unchanged except the real-engine suite (50 checks).
