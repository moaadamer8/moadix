# Increment 7d: rulings on 7c, the executing gates, the engine suites (0.6.0)

Status: built and committed locally as 0.6.0; review rulings applied in 0.6.1 (section 8, which supersedes section 2's "stopped"); the operator's first real-engine run fixed in 0.6.2 (section 9); the install dry run adapted in 0.6.3 (section 10). Nothing was pushed, tagged or installed. One item stops for the operator's ruling: every image's licence scan (section 2). Until that ruling, every executing gate reports UNKNOWN, and `tests/confined-engine` refuses to start.

## 1. Rulings on increment 7c, as applied

**Ruling 1 (licences of software pulled by digest and executed).** The rule is in `docs/AMENDMENT-3.md` section 4: permissive or MPL-2.0 unmodified for what is vendored or shipped; any OSI-approved licence for what is pulled unmodified by digest from its official source and executed. Anything non-OSI or with a field-of-use restriction stops and is reported. `THIRD-PARTY.md` now has a section listing each image with its digest, source, main licence and the non-OSI identifiers found.

**Ruling 2 (0.5.3 for the partial step).** Kept.

**Ruling 3 (merged validators on onboarded products).**
- `check_merged` runs check-baseline's completeness rules on the merged view, using the phase-B registry entry. `MOADIX_BASELINE_COMPLETENESS_ONLY=1` skips the citation checks.
- check-baseline now joins every section with the same name, so a feature's additions are read.
- A feature's `sdlc/features/<id>/B-*.md` files now merge into the product's `sdlc/B-*.md` (`gate/feature.py`). The path map allows them in phases 6b, 8 and 9.
- `tests/inc6` drives a feature cycle on an onboarded product through to its merge at phase 11.

**Ruling 4 (history rewrite).**
- Preconditions held: `origin/master` (451a03a, the live remote's head too) is an ancestor of HEAD, and the tags v0.2.1, v0.3.0 and v0.4.0 all point at or before it.
- The four unpushed commits were rewritten with a tree filter. The production project id became `<production-project-id>` and the hosts became `<product-host-N>`.
- A second filter made `tests/install/render.py` check the template by the sha256 of the nine hosts, so their names are in no commit.
- The commit structure was kept: 7ba7752 (unchanged), 459da0a (7b), 24be734 (0.5.2), 32a7ba6 (0.5.3). Then `refs/original` was deleted, the reflog expired, and `gc --prune=now` run.
- Proof:
  - Every commit reachable from every local branch and tag was searched: 76 commits, 0 with the id or any of the nine hosts.
  - 0 commit messages matched.
  - 0 of the 1217 stored objects matched.
  - Every suite passed on a clean checkout of 32a7ba6.
  - Negative control: the nine hashes find 0 hits in the real template and 1 in a template with one host planted.
- Before committing 0.6.0, the files going into it were scanned the same way: 82 files, 0 matches for the id or any host hash.

**Ruling 5 (Firebase allowlist).** Confirmed as proposed; unchanged.

## 2. Stopped: every image has non-OSI identifiers (ruling 1)

The images below are pinned by digest in `gate/config/confinement.yaml`. Each was pulled from its official source. The `License:` fields of its `/usr/share/doc/*/copyright` files were read on 2026-11-14.

| Image | Main software | Non-OSI identifiers found |
|---|---|---|
| `node:24-slim` (Debian 12) | Node.js MIT, npm Artistic-2.0 | GFDL-NIV (manuals), CC-BY-3.0, public-domain, Beerware (libmd, PAM), Latex2e, the "verbatim copies only" notice on the GPL/LGPL texts |
| `node:24-bookworm` (Debian 12, for Stryker) | as above | as above, plus perl's RRA-KEEP-THIS-NOTICE, TEXT-TABS, DONT-CHANGE-THE-GPL |
| `python:3.12-slim` (Debian 13) | CPython PSF-2.0 | as node |
| `mcr.microsoft.com/playwright:v1.64.1-noble` (Ubuntu 24.04) | Playwright Apache-2.0, Chromium BSD-3-Clause | GFDL, CC-BY-3.0/4.0, CC-BY-SA-2.0/3.0/4.0 (icon and theme data), public-domain, Beerware, BSL-1 |
| `ghcr.io/zaproxy/zaproxy:20261026-stable` (Debian 12, ZAP 2.17.0) | Apache-2.0 | GFDL, CC-BY, public-domain, Beerware |
| `postgres:17-bookworm` (Debian 12) | PostgreSQL licence | GFDL, public-domain, Beerware |

No field-of-use restriction was found. What the identifiers cover:
- Documentation (GFDL manuals).
- Data and artwork (CC-BY, CC-BY-SA icon themes).
- A few small files under public-domain, Beerware, Latex2e or BSL-1.
- liblzma5's "noderivs" entry, which is the GPL/LGPL licence texts themselves ("verbatim copying of this license document").

None covers a program MOADIX calls. All of them are inside Debian's or Ubuntu's main archive, which accepts them under the DFSG. Still, they are not OSI-approved licences, and ruling 1 says anything non-OSI stops and is reported. So all six images are `status: blocked`, each with its reason. Every gate that needs one reports `UNKNOWN … is blocked by the licence ruling`. No gate can pass or fail until the operator rules.

To be precise about what already happened:
- To capture the real tool outputs (section 4) and read the copyright files, I pulled these images and ran them on this machine.
- Each run used throwaway fixtures, no product, and my own containers, which I removed afterwards.
- That is execution, not redistribution, and nothing from the images is in the repository except the captured tool outputs of the fixtures.

**Operator decision needed.** If documentation, data and artwork under these identifiers, inside an unmodified distribution image that is executed and never shipped, are acceptable, set `status: cleared` on each image in `gate/config/confinement.yaml`. One line per image; the reason line can then go. If not, say which images to replace. A distroless or Chainguard-style base would remove most of the documentation packages, but it changes the pins and needs its own scan.

## 3. What was built

**Executing gates.** `gate/v1/check_exec.py` has one entry per gate and phase in the registry, 22 in all, each `check-exec-<gate>-<phase>`:
- pytm: 4, B
- LikeC4: 3, B
- dependency-cruiser: 3, 7, B
- knip: 7, B
- ESLint: 7
- tsc: 7
- Stryker: 8, B
- test suites: 8, B
- Schemathesis: 8, 10b
- ZAP: 9
- Lighthouse CI: 10a
- axe: 6, 8, 10a

Every gate follows the same rules:
- **Applicability.** A gate runs unless its coverage topic is N/A in the phase's COVERAGE.md. The gap critic judges that N/A reason.
- **Preflight refusals.**
  - JS or TS configurations are refused for LikeC4, dependency-cruiser and Stryker; they must be JSON.
  - Missing inputs are refused: `tm/model.py`, model sources, `.dependency-cruiser.json`, `tsconfig.json`, `stryker.config.json`, and the OpenAPI description under `05-lld/`.
  - A Node product without `package-lock.json` is refused.
- **Runs.**
  - The product is exported with `git archive HEAD` into a named volume.
  - The tool is installed from the gate's own lockfile (`gate/config/locks/`, equal to `tools/`) through the egress proxy. The product's dependencies are installed with `npm ci --ignore-scripts`, apart from the adopted `install_scripts`.
  - The tool then runs with `--network none` (live gates: an internal network shared only with the app). It writes into `/out`.
- **Verdicts.**
  - The output is copied out and checked: no symlinks, no special files, under the size cap.
  - The verdict is derived from the tool's raw file, never from a summary line or exit code alone. Zero tests, skipped tests and cancelled tests all fail.
  - Mutation score: the threshold comes from the size rule (TS10) or `product-tools.yaml mutation.threshold`.
  - Lighthouse: LCP 2500 ms, CLS 0.1 and TBT 200 ms by default, overridable through `budgets:`.
  - ZAP: High fails. axe: critical or serious fails.
- **Evidence.** It is filed with `toolrun.record` under the phase.

**Runner.** `gate/confined.py`, class `Run`, does the engine calls on top of the 7c policy:
- Named volumes, loaded through `docker cp`. A capability-minimal helper chowns them.
- uid 10001, `--cap-drop ALL`, `no-new-privileges`, a read-only root, tmpfs `/tmp`.
- The tier limits:
  - cpus;
  - memory equal to memory-swap;
  - pids;
  - nofile;
  - fsize at the output cap;
  - the wall clock, which kills and removes the container.
- OOM detection.
- Every object it creates carries the label `moadix.run=<id>`, and `close()` removes them by that label.

New pieces:
- `gate/egress_proxy.py`: a CONNECT-only allowlist proxy (registry.npmjs.org, pypi.org, files.pythonhosted.org on port 443).
- `gate/exec/axe-run.js`: the gate-owned axe runner, with its lock `tools/npm/axe-runner` (Playwright 1.64.1, axe-core 4.14.0).
- Services for integration tests: Postgres from the gate's catalogue, never the product's compose file.
- The app for live gates is built from the committed Dockerfile under the 7c build rules, and answers as `sut.moadix.test`.

**Installer fix found on the way.** `managed/install.sh` never copied `gate/config/critic.schema.json` (increment 7) or the 7b tool configuration directories. It now copies:
- `gate/config/*.json`;
- the six directories (semgrep, redocly, k6, vacuum, squawk, actionlint);
- `gate/config/locks/*/`;
- `gate/exec/`.

The ownership and mode lists are updated to match.

**Test double.**
- `tests/lib/engine_double.py` is a fake `docker`. It runs nothing: named volumes are folders, and `docker run` writes canned tool output.
- It is used only by fixture gate copies, and only through `MOADIX_TEST_ENGINE`. The runner honours that only when `_testguard.py` is in the gate copy, and that file is never installed.
- Fixture copies set the images to `cleared`; the repository's configuration, which is what installs, keeps them blocked.

## 4. Real-engine findings and output provenance

The raw outputs in `tests/exec/raw/` came from running each real tool, at the pinned version in the pinned image, on throwaway fixtures. They are the real files, trimmed only where noted in the README there. `tests/exec/double/pass/` uses them where the real run passed. Where the real run had findings, it uses minimal pass variants derived from the real file, as listed in its README. The capture runs exposed these behaviours, all handled in the gates (`docs/confinement-design.md` 3.10):

- Chromium upgrades `http://app` to HTTPS (`.app` is HSTS-preloaded), so the app alias is `sut.moadix.test`.
- ZAP requires `/zap/wrk` to be a mount and runs as uid 1000, so the output volume is chowned to 1000 and mounted there.
- Stryker's command runner needs `ps`, so it runs on `node:24-bookworm`.
- `npx stryker` without the product's packages fetched an unrelated old `stryker` package, so every gate calls an explicit binary path.
- LikeC4 `export json` exits 0 with an empty model on a parse error, so the gate uses `validate` plus an element count.
- Schemathesis' JUnit file name carries a timestamp, so the gate reads the single report and refuses two.
- Postgres cannot run with a read-only data directory, and a password variable is refused by the runner's secret filter. The service therefore has a data volume, a tmpfs socket directory and trust auth, reachable only on the run's internal network.

## 5. Tests

| Suite | Result | Where |
|---|---|---|
| gate2 | 299/299 | sandbox |
| verifiers | 97/97 | sandbox |
| inc6 | 70/70 | sandbox |
| inc7 | 119/119 | sandbox |
| inc7b | 58/58 | sandbox |
| inc7c | 77/77 | sandbox |
| **inc7d (new)** | 115/115 | sandbox, engine double |
| tools | 107/107 (2 skipped, as before) | sandbox |
| skills | 43/43 | sandbox |
| release | 9/9 | sandbox |
| mainguard | 281/281 | sandbox |
| install/render | 29/29 | sandbox |
| corpus guard self-test | 18/18 | sandbox |
| **confined-engine (new)** | not run: refuses (images blocked; the sandbox cannot reach the socket) | Terminal, operator |
| corpus, install/dryrun | not run here (Terminal, as before) | Terminal, operator |

Results are in `docs/evidence/increment-7d-suite-*.txt`, and every sandbox suite was re-run on a clean checkout of the 0.6.0 commit.

`tests/inc7d` proves the following, all against the double:
- Each gate's verdict on the real raw outputs, pass and fail, for all 12 gates and every one of their 22 phase entries.
- Forged output is never believed: zero-test JUnit, a summary object in place of ESLint's report, two Schemathesis reports, "PASS" text in place of ZAP JSON, an LHR without audits, no report at all, and trailing garbage.
- N/A in COVERAGE.md runs nothing.
- Missing inputs and JS/TS configurations fail.
- The repository's configuration gives UNKNOWN with nothing run; an unreachable engine gives UNKNOWN.
- The argv the engine receives:
  - no host path, bind or socket;
  - the label on every object;
  - cap-drop and no-new-privileges;
  - `--network none` and the E-lint limits on the product-code run;
  - read-only `/src` and `/deps`;
  - installs on an internal network through the proxy, which holds the only non-internal network;
  - the live app and scanner sharing only the internal live network, with the alias `sut.moadix.test`;
  - the app image built with `--network none`;
  - the gate's axe runner mounted read-only.
- Nothing labelled is left after any gate.
- The installer copies what the gates need.
- The lock copies equal `tools/`.
- The registry has 22 entries.
- `THIRD-PARTY.md` records every digest.

The B-doc merge for onboarded products is proven end to end by `tests/inc6` (feature O1 on the onboarded product).

`tests/confined-engine/run.py` (Terminal, one command) proves the same properties against the real engine, through `confined.Run` exactly as the gates call it. It uses only its own label `moadix.run=es<hex>`, and each property has a hostile fixture:
- **Secrets.** A canary environment variable and a canary file on the host are not found inside the container. `NPM_TOKEN` is refused.
- **Host paths.** No host path appears in `/proc/mounts` and there is no Docker socket. The root filesystem is read-only. A host directory or the socket as a mount source is refused.
- **No network.** Product code gets no DNS, no connect, and no interface but `lo`.
- **No egress.** The live network has no route out, while the scanner still reaches the app. The proxy refuses example.com and a look-alike suffix and tunnels registry.npmjs.org (this one needs internet). The install network has no route out without the proxy.
- **Limits.**
  - Fork bomb against the pids limit, counted with shell builtins only.
  - Memory: an OOM kill, which the runner refuses.
  - File size: writes stop at the output cap.
  - `/tmp` full: "No space left".
  - Wall clock: lowered to 5 s and killed.
- **Forged output.** A symlink to `/etc/passwd`, a FIFO and output over the cap are refused. A "PASS" summary is not believed.
- **Cleanup.** Nothing of its own is left, and every foreign container, volume and network is exactly as before.

I could not run it: the sandbox cannot reach the Docker socket from Python, and the images are blocked. Its refusal path was checked here. The figures in its checks (pids 256, memory 2048 MiB, output 50 MiB, `/tmp` 512 MiB) are the E-lint defaults.

**Interpretation to confirm.** The instruction was "refuse to start if any running container or compose project on the machine is not its own". I read "running" as covering compose projects too. The suite therefore refuses on any running foreign container and on any compose project with a running container. It lists stopped projects as found and untouched, and never reads their mounts, starts, stops or removes them. Today this machine has three stopped projects (onlinemarket, momento, momento_frontend) and nothing running. If the rule should also refuse on stopped projects, the suite cannot run until those stacks are removed, which is the operator's call. That change is one line in `preflight()`.

## 6. Deviations and open points

- axe visits `product-tools.yaml live.paths`, not yet the URLs in LV-INVENTORY.csv and screen-states.csv (design 3.7).
- ZAP runs the baseline scan without a gate rules file.
- pytm requires a runnable model with elements and flows; the TH-/SEC- mapping stays with SEC-CONTROLS.csv (7b).
- Tools are installed per run through the proxy; there is no shared tools cache. A run therefore needs the registries to be reachable, and when they are not, the gate reports UNKNOWN, never a pass.
- `docs/AMENDMENT-4.md` stays untracked and out of the commit, as before.

## 7. What the operator must do by hand, in order

1. Rule on the image licences (section 2). If accepted, set `status: cleared` on the six images in `gate/config/confinement.yaml` and commit.
2. With Docker Desktop running and nothing else running, run `/usr/bin/python3 tests/confined-engine/run.py` in Terminal. Confirm or correct the stopped-projects reading in section 5.
3. In Terminal, run the attack corpus (`docs/INSTALL.md`, "Running the attack corpus") and `/usr/bin/python3 tests/install/dryrun.py`.
4. If not yet done, create the local overlay `~/.config/moadix/overlay.json` (`docs/INSTALL.md`, "Local overlay").
5. Reinstall in Terminal: `managed/install.sh` (it asks for your password once, shows the overlay and asks before applying it).
6. Run the live policy check: `bash tests/install/policy_live.sh`.
7. Push and tag when satisfied; nothing was pushed or tagged.

## 8. Review of 7d, rulings applied (0.6.1)

1. **Image licences.**
   - The image rule in `docs/AMENDMENT-3.md` section 4 is replaced: software that is only pulled unmodified by digest and executed is accepted under any licence that permits use without restriction. It stops only for a licence that restricts use, or for a component with no identifiable licence in a program the gate executes. Documentation, icon and data licences do not stop.
   - All six images are `status: cleared`.
   - `THIRD-PARTY.md` keeps the full inventory per image: every `License:` identifier, 148 to 510 per image, re-read on 2026-11-15.
   - In that re-read, one component has no identified licence: Blackmagic's DeckLink API headers in GStreamer's plugins-bad, in the Playwright image (`License: UNKNOWN`). The gates run only Node.js and Playwright's own Chromium, which does not load GStreamer, so under the new rule this does not stop. It is recorded there.
2. **Running the images to read their licences.** Accepted as reported.
3. **Engine-suite safeguards.**
   - Only running foreign containers or projects block the suite.
   - It removes only objects carrying its own run label (`es` plus 10 hex digits). The runner now removes a single container only after finding it by its run label and name.
   - `tests/lib/no_prune.py` fails if a pruning command, a compose `down -v`/`--volumes` or an image removal appears in the runner, the gates or the suite. The engine suite runs it first, and `tests/inc7d` runs it with planted negative controls.
   - The suite records every foreign container (id, name, state), volume, network and image before it starts and after cleanup. It fails and prints each difference.
   - It runs `inspect` only on its own pinned images and its own containers.
4. **Gaps closed.**
   - axe visits `live.paths`, every designed row of `design/screen-states.csv` and, at 10a, every `LV-INVENTORY.csv` row that is not n/a. Each row gives its address in an optional `url` column (an app-relative path), or names a path itself.
   - **My choice, which you may relax:** a row without a URL fails the gate before the engine is called, rather than being skipped. A URL that names a host or climbs out of the app is refused.
   - The paths reach the runner as a gate-written JSON file.
   - ZAP runs with the gate-owned `gate/exec/zap-rules.tsv` (`-c`). The gate applies the same file to the JSON report: High always fails, a rule set to FAIL fails at any risk, and IGNORE is counted.

## 9. The operator's real-engine run on 0.6.1, fixed in 0.6.2

The run reported 26 checks: 22 passed, 4 failed, and 5 never ran. The foreign-object record matched before and after (22 containers, 455 volumes, 9 networks, 28 images). Reproduced with throwaway containers labelled `moadix.run=es…`, all removed afterwards:

1. **test_host crashed (runner defect).** The runner refused any run whose whole argv mentioned `docker.sock`, `-v` or `--volume`, including the command run inside the container. The suite's probe `test -S /var/run/docker.sock` was refused, and so would `node -v` be. The check now covers the engine options only (`_refuse_host_mounts`). A bind mount, `-v`, `--volume=` or the socket as a mount is still refused (tests/inc7d). The suite also now reports a crashed group as one failed check, plus each of the group's checks that did not run as a failed check, so the total is always 31.
2. **"no network" (test defect).** Every network namespace has the kernel's placeholder devices (gre0, sit0, tunl0, erspan0 and others), all down with no address. The check now proves the real property: no interface other than lo has IFF_UP set; `os.networkInterfaces()` lists only lo; there is no IPv4 route; and every IPv6 route and address is on lo. As a negative control, a container on the default bridge fails this check on all three counts (eth0 is up, addressed and routed).
3. **Fork bomb (test defect).** The check expects the pids.max value (256), at most 256 processes alive, and at least one failed fork. The limit held, but dash exits with "Cannot fork" (status 2) at the first refused fork, so the counting lines never ran and only "256" was printed. The bomb now runs in a subshell, and the parent reports using builtins only. The check also requires the cgroup's own count of refused forks (`pids.events` max) to be above 0. Measured: max=256, procs=255, events=1, errors=1.
4. **Memory (runner defect).** The limit is applied: inside a run, `memory.max` is 2147483648 and `memory.swap.max` is 0. The Docker Desktop VM has 8217448448 bytes (7.65 GiB) and 10 CPUs. When the allocation ran past the limit, the cgroup recorded `oom_kill 1` and node exited with 137. The runner treated a run as OOM-killed only when `inspect` reported `OOMKilled=true`; otherwise it returned the exit 137 as a result, and the test saw no refusal (None). From this sandbox, `docker inspect` is refused for every container, so the flag could not be read here; the runner no longer depends on it. Exit 137 not caused by the wall clock, or `OOMKilled=true`, is now always a refusal: "the run exceeded its memory limit (2048 MiB) and was killed". tests/inc7d covers exit 137 with the flag false, exit 137 with inspect failing, the flag true with exit 0, and the control of an ordinary exit 1.

## 10. The Terminal-only suites on 0.6.2, and the dry run adapted in 0.6.3

The operator's run: confined-engine 31/31 with foreign objects unchanged, corpus 128/128, and the install dry run 17/18. The dry run failed on "APPROVE 0 is recorded". The operator's reading is correct. Since increment 7, phase 0 is gated by check-contract-0 (docs/AMENDMENT-3.md section 1), which needs sdlc/0/COVERAGE.md, sdlc/0/DISCOVERY.md and clean gap-critic evidence. The dry run's product, last changed before increment 7, had only the BRD. The installed gate refused correctly ("validators did not pass … check-contract-0 FAIL: coverage-lint: sdlc/0/COVERAGE.md is missing").

Changes:
- The dry run now prepares the product through `tests/lib/contract_fixture.ready`, the fixture the other suites use, against the installed gate copy (a small adapter gives it the fixture's shape). APPROVE 0 is still recorded by the installed gate with a real code.
- A new check runs first, on the product without the contract: APPROVE 0 with a real code is not recorded, and the reason names check-contract-0. A refused APPROVE spends its code (gate/opcmd.py), so the approval waits for the next 30-second code.
- "Installed gate copy matches" now also compares the files the installer has copied since 7b–7d: gate/config/*.json, the vacuum, squawk and actionlint configs, the runner's lockfiles and gate/exec. The dry run never checked these before.
- The dry run now has 19 checks. The sequence was rehearsed in the sandbox against a fixture gate copy: refused naming check-contract-0, then contract PASS, then recorded.

Tests that need Terminal, the Keychain or Docker, and whether they are current with increments 7–7d:
- tests/confined-engine/run.py: Docker. Written in 7d and fixed in 0.6.2; 31/31 on the operator's run.
- tests/corpus/run.py and tests/corpus/isolation.py: Keychain and test-built checkers. Adapted in increment 7 (7ba7752: `contract_fixture.ready` before every approval). 7b–7d added nothing to the phases it approves; 128/128 on 0.6.2.
- tests/probes/kc-probe.c: the corpus isolation guard's keychain probe. Untouched by 7–7d; nothing in it depends on them.
- tests/install/dryrun.py: Keychain. It was not adapted until now; adapted in 0.6.3 as above.
- tests/install/policy_live.sh: a live Claude Code session after install. It tests the 0.5.2 policy, and managed policy is unchanged since 0.5.2 (7b–7d changed only the files install.sh copies, which the dry run now checks); no adaptation needed.

The complete operator procedure from 0.4.0 is in `docs/INSTALL.md`, "Updating from 0.4.0 to 0.6.3".
