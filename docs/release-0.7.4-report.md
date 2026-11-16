# 0.7.4: the live gates build, wait and scan (the 0.7.3 engine run)

Source: the operator's Terminal run of 0.7.3:
- mainguard 281/281, inc6 70/70, render 30/30, dry run 19/19, corpus 128/128;
- the real-engine suite 45/49, with foreign objects unchanged. The user group and nine smoke runs passed. All four live gates (schemathesis, zap, lhci, axe) failed with `ambiguous Dockerfile source: both stdin and flag correspond to Dockerfiles`.

## 1. The build: cause, reproduction, fix

**Cause.** The gate streams the app's build context to `docker build -` as a tar, and names the Dockerfile with `-f`. The engine (BuildKit through buildx, Docker 28) decides from stdin's **first 512 bytes** whether stdin is a tar context or a Dockerfile.

The context tar was copied member by member from `git archive`. git writes a PAX global header holding the commit id, and Python's tarfile carries that `comment` onto every member it reads. So every member was written with its own PAX extended header, and the tar's first block was an `x` header. A PAX header needs a second block before the first file's header can be read, so the 512-byte test failed. The engine took the stream for a Dockerfile, saw `-f` as a second one, and refused.

**Reproduction.** Done with my own commands and my own labelled objects, all removed afterwards:
- The 0.7.3 context's first header is typeflag `x` (`././@PaxHeader`), with `comment=<commit>` on the first member.
- I could not stream stdin to the real engine from here: a redirect makes the call more than "the whole docker command", and the sandbox then refuses the socket.
- The build itself, with the gate's exact flags (BuildKit, `--network none`, `--pull=false`, the build memory limit, the digest-pinned base) and the fixed context unpacked to a folder, builds.

**Fix** (`check_exec._context_tar`):
- members are written in GNU format with no PAX headers;
- user and group names are blank, and modification times are whole seconds;
- links, devices and anything outside the export are dropped, as before;
- a member with a short name goes first, so the first 512 bytes are a plain ustar header even when a path is longer than 100 characters.

A new check, `confined.stdin_context_problem`, refuses any context whose first header is not a plain one with a valid checksum, before the engine is called.

The context still comes only from `git archive HEAD`. It never comes from a host path, and it carries no secret and no SSH. The network rule is unchanged: `none` by default.

## 2. Why the sandbox suites did not catch it, and the other gaps of the same kind

**The fake engine.** `tests/lib/engine_double.py` read stdin for `build` and accepted anything. It now applies the engine's rule: with `-` as the context and `-f` given, the first 512 bytes must be a whole tar header, or the build fails with the engine's message.

**The other invocations.** Reviewing them found three more combinations the double accepted and the real engine or the pinned images refuse. Each is now refused by the double, and two were real defects:

| Combination | Real behaviour | 0.7.4 |
|---|---|---|
| `build.network: registry`: `docker build --network moadix-egress-<id>` | That network was never created, so the classic builder would fail with "not found". BuildKit refuses any named network. | **Fixed.** The run creates an internal build network and joins the allowlisting egress proxy to it, as section 3.9 of the design says. The build gets `HTTP(S)_PROXY=http://moadix-proxy:3128` (the product cannot set those build args). The double refuses an unknown network for builds and runs. |
| A live script's wait for the app, `until (echo > /dev/tcp/…)`, run under `sh -c` | `/bin/sh` is dash in every pinned image, and dash has no `/dev/tcp`, so the wait could never succeed. Every live gate would have waited 90 s and reported that the app never listened, even with the build fixed. Reproduced in the pinned python image: sh does not see an open port, bash does. bash exists in the python, zap and playwright images. | **Fixed.** Live scripts run under `bash -c`. The double fails a `/dev/tcp` wait under `sh` the way dash does. |
| `--network-alias` on `none` or `bridge` | The engine refuses it. The gate never does this, but the double now refuses it too. | Refused by the double. |

Two faults turned up while running the live tools by hand (step 4); they are not engine combinations:
- **`HOME=/tmp/home` did not exist.** The runner set it, but the run's tmpfs `/tmp` starts empty, so `zap-baseline.py` failed writing `$HOME/zap.yaml`. HOME is now `/tmp`, which always exists and is writable by any uid (mode 1777).
- **ZAP's Java reads its home from passwd** (`/home/zap/.ZAP`), and the root is read-only. The ZAP script now passes `-z '-dir /tmp/zaphome'`.

## 3. A failed build shows the engine's last lines

`start_live` used to raise with 400 characters of stderr. The smoke harness found no kept log, which is why its line ended with an empty `log:`. Now the build's stdout and stderr go to the evidence folder through `keep_logs` (bounded, redacted), and the failure reads:

`building app failed (engine exit N); container exit N; tool exit none written; last lines: …; the build log is kept at .sdlc/evidence/<phase>/exec-<gate>-run-<commit>.log`

## 4. The four live gates, run by hand

These ran on my own labelled objects, all removed afterwards. The app was built as above and run the gate's way: uid 65534, `--cap-drop ALL`, `--read-only`, tmpfs `/tmp`, an internal network, alias `sut.moadix.test`.

| Gate | Result | Run as |
|---|---|---|
| app | `/health` 200 JSON, `/` 200 HTML, fetched by a confined node client on the internal network | — |
| ZAP | exit 0, `zap.json` written (3 WARN, 0 FAIL, 59 PASS) | on the internal network, as uid 1000, with `HOME=/tmp` and `-dir /tmp/zaphome`. It failed until both fixes were in. |
| Schemathesis 4.32.7 | JUnit report written | on a second, non-internal network of mine, so pip could install. It found one real fixture defect: an undeclared `TRACE` returned 200. The fixture now answers 405 for any method but GET and HEAD. |
| Lighthouse CI 0.15.1 | exit 0, `lhr-*.json` written | uid 65534 in the pinned Chromium image |
| axe | exit 0, `axe.json` written, no violations | the gate's own `axe-run.js` with axe-core 4.14.0 and playwright 1.64.1 |

**Not verified by hand:**
- **The build through stdin.** The sandbox lets docker run only as the whole command, without a redirect, so I could not stream stdin.
- **The tools installed through the gate's egress proxy.** I installed them directly on my own network. The run sends traffic to registries only through the proxy, as installs do.
- **The `/deps` volumes and the `/out` copy-out.**
- **ZAP with the gate's rules file** (`-c zap-rules.tsv`).
- **A registry-mode build** on the classic builder.

The real-engine suite covers all of these.

## Tests

- `tests/rel074/run.py`: new suite, 32 checks:
  - context 6;
  - double 8;
  - live 9;
  - registry 5;
  - buildlog 3;
  - guard 1.
- The counts of all suites run here are in the commit message.
- The Terminal suites are unchanged by 0.7.4 except the real-engine suite (49 checks).
