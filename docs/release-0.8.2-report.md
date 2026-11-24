# 0.8.2: unfixed image findings accepted by APPROVE 9, scans of the images the gate builds, exempted acceptance criteria (MF-66), list items with a colon

**Source.** The first product's phase 9 on 0.8.1:

- **Images.** A High or Critical in a declared image (`images:`) failed check-trivy whether or not a fixed version existed. A vulnerability with no fix upstream could not be resolved, and high/critical findings cannot be waived, so the phase could not pass. check-trivy also scanned only the declared base images, not the images built from the product's Dockerfiles, which are what ships.
- **MF-66.** The ac-coverage-critic's check (`gate/verify.py`, the `coverage` branch of the evidence check) did not read `traceability-exemptions.yaml`. An acceptance criterion the operator had exempted, which check-traceability accepted, still failed check-verifiers as "untested acceptance criterion".
- **YAML.** The gate's reader (`hlib.parse_yaml`) read an unquoted list item that contains a colon, such as `- postgres:17` or `- repo/app@sha256:...`, as a one-key map, so `images:` entries had to be quoted.

## The fixes

**1. A High or Critical with no fixed version, accepted only by APPROVE 9** (`gate/v1/check_scanners.py`: `split_unfixed`, `approved_unfixed`, `check_unfixed`; `gate/validate.py`; `gate/validation.py`: `unfixed_of`, `unfixed_digest`, `unfixed_text`; `gate/opcmd.py`: `unfixed_approvable`, `unfixed_payload`).
- **Fixable findings are unchanged.** In an image scan (a declared image or one the gate builds), a High or Critical **with** a `FixedVersion` is a failing finding as before. It cannot be waived or accepted.
- **Evidence.** One **without** a fixed version is residual risk. It goes to `trivy-unfixed.json` (indexed with the source commit) as `{cve, severity, package, installed, image, digest, target, scan_date}`.
  - The digest is the image's first repo digest, else its image ID; for a built image, the ID the engine reports.
  - The scan date is trivy's `CreatedAt`.
- **What check-trivy checks.** It reads the verified ledger and takes the `unfixed_accepted` set of the last APPROVE 9.
  - An unfixed finding passes only when its acceptance key (`validation.unfixed_key`) is in that set: `RESIDUAL [...] ... accepted by APPROVE 9 (ledger seq n)`.
    - **A declared image** (`images:`): CVE, package and the image's pinned digest, which is stable.
    - **An image the gate builds:** CVE, package, installed version and Dockerfile path (the image's role), never its image ID. Every build carries its run's label (`moadix.run=<id>`) in the image config, so the ID (Docker's and trivy's) changes on every gate run. A new installed version is a new finding. The ID stays in the evidence (`digest`) for tracing.
  - Any other unfixed finding fails, saying the operator accepts it only with APPROVE 9.
  - A ledger that fails its check is UNKNOWN.
  - It prints one `UNFIXED {json}` line per unfixed finding (with `accepted_seq`), and `UNFIXED-ONLY` when those are its only failures.
- **REVIEW 9.** The validator worker stores the set and its sha256 in the result (`unfixed`, `unfixed_sha256`, `unfixed_only`). REVIEW 9 lists every one: "Unfixed High/Critical image vulnerabilities (no fixed version; residual risk) (n, set sha256 ...): CVE [severity] package@version in image (digest) NOT YET ACCEPTED | ...".
- **APPROVE 9.** It is recorded on a result whose only failures are check-trivy's unaccepted unfixed findings (`UNFIXED-ONLY`).
  - Any other failing validator, a fixable finding or an UNKNOWN refuses it as before.
  - WITH-WAIVERS also lets such a check-trivy failure through, beside the check-verifiers failures its waivers cover.
  - The ledger line records `unfixed_accepted: {sha256, findings: [{cve, severity, package, installed, image, digest, dockerfile (built images), scan_date}]}` (the sha256 is over the sorted acceptance keys) whenever the result has unfixed findings. When the result itself failed, it also records `validation.passed_with_unfixed_accepted: true`.
  - Its reply names each finding it accepts.
- **The report.** The security report's `## Residual risk` lines are documentation. check-trivy notes a line naming the CVE and the package ("documented in ...:n", "documentation only, not acceptance"), and never counts it as acceptance.
- **Every scan reads the fresh result.** A new unfixed finding fails until the next APPROVE 9: the same CVE in another declared image digest, or, in a built image, a new installed version or another Dockerfile. An accepted finding that gets a fixed version fails at once.
- **Scope.** The filesystem scan (`trivy fs`) is unchanged, and Medium and lower are reported as before.

**2. MF-66: exemptions in the AC coverage check** (`gate/verify.py` `ac_exemptions`, `gate/v1/check_verifiers.py`).
- The check reads the adopted `.sdlc/config/traceability-exemptions.yaml`, the file check-traceability reads.
  - `kind: untested-story` (`story`, `reason`) exempts every acceptance criterion of that story.
  - A new `kind: untested-ac` (`ac: US-001/AC-2`, `reason`) exempts one criterion; check-traceability ignores it.
  - An entry without a reason exempts nothing.
- An exempted criterion may have an empty `tests` list or be left out of `coverage`. A test it does cite is still checked.
- check-verifiers prints `OK moadix:ac-coverage-critic: untested and exempt in traceability-exemptions.yaml: <AC> (<reason>)`.
- The brief is unchanged, so a running critic's evidence stays current.

**3. The images the gate builds** (`check_scanners.built_targets`, `trivy_prepare`, `scan_built`; `check_exec.build_image`, `compose_build`).
- **Targets**, at HEAD, each once:
  - the root `Dockerfile` (the shipped image);
  - each `build:` of the compose file named by `live.compose`;
  - each Dockerfile under `tests/gate/` (`Dockerfile`, `Dockerfile.*`, `*.Dockerfile`), built with the repository root as context.

  Dockerfiles elsewhere are not built; `trivy fs` still reads them.
- **The build** runs in one confined run, through `check_exec.build_image`: the live gates' build step, moved out of `start_live` unchanged. Same limits, same `FROM`-pinned-by-digest rule, same build network (none, or `registry` through the allowlisting proxy), and the run's labels on every stage.
- **The scan.** Each image is read with `docker image inspect --format {{.Id}}` and `docker save`, and trivy scans the tar with `--input`. That scan runs offline, with the DB already downloaded by `trivy_prepare`. All of this happens before `Run.close()`.
- **The evidence.** Each image's report is `trivy-built-<n>.json`. `trivy-built.json` lists every built image with its Dockerfile, context, digest (image ID), scan date and report.
- **Findings.** Fix 1 applies to built images.
  - Declaring a base under `images:` never exempts what is built on it.
  - A Dockerfile the gate cannot build is a failing finding ("... could not be built, so it was not scanned").
  - No engine means UNKNOWN, as for the live gates.
- `images:` (bases) is still scanned as before. check-trivy's timeout is now 4800 s, because it builds before it scans.
- `scan_built` takes an optional run id, so the real-engine suite labels its run with its own id.

**4. The build proxy is unchanged.** `gate/egress_proxy.py` and `confinement.yaml` (its allowed hosts) are as in 0.8.1; rel082 checks it.

**5. YAML list items with a colon** (`gate/v1/hlib.py` `_is_map_entry`). A list item starts a map only when it begins with a key followed by `: ` or by `:` at the end of the line, as in YAML. `- postgres:17`, `- repo/app@sha256:<hex>` and `- http://host/x` stay strings. `- id: 0`, `- "a b": c` and `- k: a:b` are maps as before.

## Tests

- **`tests/rel082`, new, 58 checks.** Controls run 0.8.1's files (`git show 867970f:...`).
  - **trivy** (a fake pinned trivy that writes canned JSON):
    - A fixable High or Critical fails, and an acceptance line in the report does not help. High and critical stay unwaivable.
    - An unfixed High with no APPROVE 9 fails, and prints its `UNFIXED` line and `UNFIXED-ONLY`.
    - **Corpus:** an agent-written `Accepted by <name> <date>` line under Residual risk, with no APPROVE 9, does not pass, whatever the name. The line is noted as documentation only.
    - The evidence carries CVE, package, image, digest and scan date. A fixable High beside it means no `UNFIXED-ONLY`.
    - Once fixed, it is an ordinary failure. An unfixed Medium is unchanged, as are `trivy fs` and the section parser.
    - YAML: `- postgres:17` and `- repo@sha256:...` are strings and real map items stay maps; the 0.8.1 reader made the item a map.
    - The 0.8.1 control has no unfixed set.
  - **built** (the engine double and the fake trivy):
    - A built image with a fixable High fails even though its base is declared and clean.
    - It was built with `--network none` and the run's labels, and saved after the build and before the run's cleanup.
    - `trivy-built.json` records it by the double's image ID, and trivy scanned that saved image offline.
    - A built image without the High passes. An unfixed High in a built image fails without an APPROVE 9, even with an `Accepted by` line, and its `UNFIXED` line names the built image's digest.
    - The root Dockerfile, a compose build (with no repeat of the root one) and `tests/gate/Dockerfile.e2e` are built; `docs/example/Dockerfile` is not.
    - An unpinned `FROM` fails as not scanned. The 0.8.1 control does not see the built image's High. The proxy files are unchanged.
  - **approve:** end to end through the hook, the stub checker and the validator worker, with the fixture gate's phase 9 narrowed to check-trivy and check-sec-verification-9.
    - REVIEW 9 lists the unfixed High: CVE, package, image digest, NOT YET ACCEPTED, and the set's sha256.
    - **Corpus:** the committed `Accepted by` line with no APPROVE 9 does not pass.
    - APPROVE 9 is refused while check-sec-verification-9 also fails.
    - With only the unfixed finding failing, APPROVE 9 is recorded and names what it accepts. Its ledger line holds the set, its sha256 (equal to `unfixed_digest` of the set) and `passed_with_unfixed_accepted`.
    - The next check-trivy passes the accepted finding, naming the ledger seq.
    - A new unfixed Critical fails while the accepted High still passes, and the same CVE in another image digest fails.
    - **Built images:** APPROVE 9 on a built image's unfixed High records its Dockerfile path and installed version, with that build's ID.
      - The next gate run builds the same Dockerfile under a new image ID, and the accepted finding still passes.
      - A new installed version of the package fails.
      - The same CVE in an image built from another Dockerfile (`tests/gate/Dockerfile.e2e`) fails, while the root one still passes.
    - Once a fix exists, the accepted finding fails.
  - **ac:**
    - `untested-ac` and `untested-story` exemptions pass with no test, and are printed with their reasons. An exempted AC may be unmapped.
    - A non-exempted untested or unmapped AC still fails, and so does a dead citation on an exempted AC.
    - An entry without a reason exempts nothing, and so does no file.
    - The 0.8.1 control fails the exempted AC.
  - **engine:** the engine suite has the rel082 group (4) and a total of 77, and the group uses the gate's own `trivy_prepare` and `scan_built` with its run id.
- **`tests/confined-engine`, new group rel082, 4 checks.** It runs the real engine and the real pinned trivy from `~/.cache/moadix-tools`.
  - The gate's `build_image` builds a tiny image (`FROM` the pinned python image, `USER 65534`), and `trivy-built.json` records the image ID the engine reports.
  - trivy's report for the saved image (`docker save`, `trivy image --input`, offline) names the same image ID.
  - The scan ran before the run's cleanup and left nothing labelled.
  - A second build of the same Dockerfile, in a second run, gets a different image ID. The set the first run's APPROVE 9 would record (`opcmd.unfixed_payload`) still accepts every finding of the second (`check_unfixed`). The tiny image may have no unfixed High, so here every vulnerability trivy reports is treated as one: what is checked is the binding.

  The images are labelled with the suite's run and left in place, as the suite leaves the images its live runs build. The total is now 77: `inc7d` and `rel075`–`rel081` check the new total.
- **The engine double:**
  - `image inspect --format {{.Id}}` prints a built image's ID.
  - `save <tag>` writes a tar holding the double's record of the image (ID, base, Dockerfile), and every save is logged.
  - A built image keeps its Dockerfile text.
- **`tests/tools`:** the three trivy cases put their Dockerfile in `docker/`. It is still read by `trivy fs` for DS-0002, but it is not an image the gate builds, so they keep testing the filesystem scan with the real trivy.
- **`/moadix:coverage`:** the image, acceptance and exemption text is in its generator (`gate/contract.py coverage_doc`), and `commands/coverage.md` is regenerated.

**Results here:**
- **Passed:** rel082 54 (first commit), rel081 44, rel080 37, rel079 22, rel078 20, rel077 29, rel076 54, rel075 28, rel074 32, rel073 75, rel072 176, rel071 61, verifiers 97, release 9, skills 43, gate2 299, inc6 70, inc7 141, inc7b 58, inc7c 78, inc7d 150, inc8 72, tools 107, mainguard 281. All passed. After the amendments: rel082 (58), tools, inc7d, rel075–rel081, release, gate2 and inc7 rerun, all passed.
- **Skipped here:** 1 check in rel081 (real sandbox-exec) and 2 in tools (loopback binding).
- **Changed expectations:** inc7d and rel075–rel081 now expect an engine-suite total of 77.
- **check-static:** clean, with uv's folders in the sandbox.

**After the first Terminal run** (on the first 0.8.2 commit; amended):
- **rel082 counted 47, not 54, with 3 failures.** These were fixture errors, not gate errors.
  - The fake trivy appended a `scans.log` to its own tools folder. Under the real sandbox-exec, toolrun lets a tool write only to its output and cache folders, so the write was denied (`PermissionError`) and every built scan failed. In this sandbox, where sandbox-exec cannot nest, the tool runs unconfined, so the error did not show here.
  - The group then crashed reading the missing log. Its harness counts a crash as one failure and drops the group's remaining checks: 4 checks recorded, then the crash, and the remaining 8 never ran (54 − 8 + 1 = 47).
  - The fake trivy now records what it was handed (`FixtureScan`: the image ID and the proxy) inside its own report, the one file it may write. The test reads that from the evidence.
- **tools: the live probe on a running local app failed.** Neither 0.8.1 nor 0.8.2 caused it. The fixture's `product-surface.yaml` has used `enumerate: {method, command}` since increment 5 (`bd6f9aa`). The check, since the v1 port (`71112c1`), reads `enumerate.api` and `enumerate.screens`. The case runs only where a loopback port can be bound, so it was always skipped inside Claude Code. The fixture now declares `api` (a command) and `screens` (`method: none`, with a reason and an owner). Here the declaration is accepted (the screens line is noted as not applicable); the enumerator itself then needs real sandbox-exec, so the rest of the case runs only in Terminal.
- **confined-engine rel082, "its report names the same image ID": a test error, not a gate error.** The scan worked (real findings from the saved tar).
  - The test required trivy's `Metadata.ImageID` to equal the engine's image ID.
  - trivy's ImageID is the image's config digest. `docker image inspect {{.Id}}` gives that same digest with the classic image store, but the image's index digest with the containerd image store (Docker Desktop's default). The engine double, like the classic store, gives one ID, so the fixture suites could not see the difference.
  - The test now saves the engine's ID again with `docker save` and reads the tar's `manifest.json` and OCI `index.json`. It requires trivy's ImageID to be the config the tar names, and the engine's ID to be that config or an index/manifest the tar names. On failure it prints all of them.
  - The gate is unchanged. `trivy-built.json` keeps the engine's ID as `digest`: the ID `docker image ls` and the run's labels show, and the one the unfixed set (REVIEW 9, APPROVE 9) is keyed on. trivy's config digest stays in each `trivy-built-<n>.json` it points to (`report`).
- **A built image's ID changes on every gate run: acceptance rebound (a gate change).** The gate writes `LABEL moadix.run=<run id>` into every stage of a Dockerfile it builds (0.7.9). The label is in the image config, so both IDs (Docker's and trivy's) are new on every run. As first committed, an unfixed finding in a built image that APPROVE 9 accepted (bound to the ID) would have failed on the next rescan. Acceptance for built images is now bound to CVE, package, installed version and Dockerfile path (fix 1 above), and `images:` keeps its digest binding. rel082 adds 4 cases, and the engine suite adds 1 (two real builds, two IDs, acceptance holds): totals 58 and 77.
- **confined-engine: one failure, and no log to read.** The suite now writes its output to `~/.cache/moadix-engine-suite/last-run.log` and takes `--only <group>[,<group>]`. The rel082 group now removes its temporary repository and saved tar.

**Not verified here.**
- The real-engine suite, including its new rel082 group, because the sandbox cannot reach Docker. That group is the check of `docker save` and `trivy image --input` against a real engine and the real pinned trivy.
- APPROVE 9 WITH-WAIVERS with an unfixed finding is covered by the shared code (`_with_waivers_gate` accepts a check-trivy failure listed in `unfixed_only`), but no end-to-end case was added for it.
