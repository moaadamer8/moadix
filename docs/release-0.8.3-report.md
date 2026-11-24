# 0.8.3: OS packages in the builds the gate runs (package servers for builds, pinned installs, no fallback)

**Source.** A product whose Dockerfile installs OS packages (`apk add`, `apt-get install`) could not be built by the gate: a `build.network: registry` build reached only npm and PyPI. Allowing the package servers alone would make each build install whatever the server has that day, so the same commit could build a different image tomorrow and an unfixed finding (0.8.2) could change under an APPROVE 9. 0.8.3 opens the package servers to builds only, and requires every OS package to be pinned.

## The fixes

**1. The Alpine and Debian package servers, during builds only** (`gate/confined.py`: `OS_PACKAGE_HOSTS`, `proxy_hosts`; `gate/egress_proxy.py`).
- A build under `build.network: registry` may reach `dl-cdn.alpinelinux.org`, `deb.debian.org` and `security.debian.org`, as well as `registry.npmjs.org`, `pypi.org` and `files.pythonhosted.org`.
- Only the build's proxy gets them: `Run.proxy(..., "build")` passes `proxy_hosts("build")`, and the gate starts a build proxy only in `check_exec.build_image`. The install step's proxy still passes the three registries only. Runtime containers keep `--network none` or the run's internal network, and a build without `build.network` keeps `--network none`.
- **Plain http.** Debian's images name their sources as `http://deb.debian.org/...`, and a slim image has no CA bundle to switch to https. The proxy now takes `--http <host>...`. For those hosts only, it forwards a GET or HEAD in absolute form (`http://host/path`, port 80, no user info) as one origin-form request with `Connection: close`, and drops the proxy headers. Every other method, host or port gets 403. The install proxy has no `--http` list and still answers 405 Only CONNECT.
- Alpine's images name https sources, so apk goes through CONNECT on port 443 as npm does.
- **Accepted risk** (added to `docs/confinement-design.md` 3.9): plain http can be read or altered on the way. apk and apt refuse an index whose signature fails and a package whose hash differs from the signed index, so the risk is a stale or withheld package, not a forged one.

**2. A linter for OS package installs** (`gate/confined.py`: `os_package_problems`, called from `dockerfile_problems`, so it runs on every Dockerfile the gate builds: the live gates' builds and check-trivy's, before any engine call).
- **Read like the engine reads it.** `dockerfile_instructions` joins continuation lines (comment lines inside one are skipped), honours the `escape` directive, and appends a `RUN` heredoc's body. Each `RUN` is read as shell (exec form and `["sh", "-c", ...]` too, and `RUN --mount=...` flags are skipped). It is split into top-level commands at `&&`, `||`, `;`, `|`, `&` and parentheses, and redirections (`2>/dev/null`) are dropped. Leading `VAR=value`, `sudo`, `env`, `command`, `exec` and `then`/`do`/`else` are skipped. `$VAR` and `${VAR}` are filled from the Dockerfile's `ARG`/`ENV` values and the adopted `build.args`.
- **Installs.** `apk add`, `apt-get install`/`reinstall` (also `apt` and `aptitude`): every package must be `name=version`, with a version of letters, digits and `.+:~_-` only. `curl`, `curl~8.14`, `jq>=1.6`, `bash/bookworm`, `tzdata=2024*`, a `.deb`/`.apk` path and a version that is still a variable are refused. Option values (`--virtual .deps`, `-t`, `-X`, `-o Dpkg::...`) are not read as packages.
- **Upgrades.** `apk upgrade`, and `upgrade`, `dist-upgrade`, `full-upgrade` and `safe-upgrade` of `apt-get`/`apt`/`aptitude`, are refused.
- **No fallback.** A pinned version the server no longer has makes apk and apt exit non-zero. The linter refuses anything in the `RUN` that would let that pass: `||` anywhere after the install (`|| apk add curl`, `&& ... || true`), a pipe or `&` right after it, a `;` after it with no `set -e` (or `set -o errexit`) before it, an `if`/`elif`/`while`/`until`/`!` test of it, and `apt-get -m`/`--ignore-missing`/`--fix-missing`.
- **Line numbers.** Each problem starts with the line its `RUN` starts on, then the command, then the reason: `line 4: apk add --no-cache curl: curl is not pinned to an exact version (write curl=<version>)`. A `RUN` with unbalanced quotes that mentions a package tool is refused as unreadable.

**3. A missing pinned version fails loudly** (`confined.missing_pins`, `check_exec.build_image`). When a build fails, its output is searched for apk's `unable to select packages` and `breaks:`/`required by: world[...]` lines, and apt's `E: Version '...' for '...' was not found` and `E: Unable to locate package`. The error then reads `building <name> failed (engine exit n): a pinned OS package version is not on the package server (the gate never falls back to another version; pin one that exists): <the lines>`. check-trivy reports it as "could not be built, so it was not scanned", which fails.

## Tests

- **`tests/rel083`, new, 35 checks.** The control runs 0.8.2's `gate/confined.py` (`git show 70ad949:...`).
  - **lint (17):**
    - An unpinned `apk add` fails, naming line and package; 0.8.2 passed it.
    - `apk upgrade` (in a continued `RUN`, named by the line it starts on), `apt-get upgrade`, `apt-get dist-upgrade` and `apt full-upgrade` fail.
    - A pinned `apk add` passes. A pinned `apt-get install` with `-o` values, an environment prefix, a redirection and a comment line passes.
    - Unpinned, wildcard, release and range installs fail, one line each. A version from an `ARG` with a value, or from `build.args`, is read; an unset variable fails. Exec form, heredoc and `RUN --mount` are read.
    - `||` after the install, a pipe, `;` with no `set -e`, an `if` test and `apt-get --ignore-missing` (`-m` in a bundle) each fail; `set -eux; apk add ...; rm ...` passes.
    - Through the gate (check-trivy, the engine double): an unpinned `apk add` is refused with its line and no engine build; a pinned one is built and scanned; a build whose engine output says the pinned version is gone fails with the new message, quoting apk. `missing_pins` reads apt's refusal too.
  - **proxy (10):**
    - `proxy_hosts("build")` tunnels the registries and the three package servers and forwards plain http to the package servers only; `proxy_hosts("install")` is the three registries, as before; only `build_image` starts a build proxy.
    - Through the gate: a `build.network: registry` build starts one proxy with exactly those arguments and passes.
    - `egress_proxy.handle`, in process over socket pairs (no network; `socket.create_connection` replaced): a host off the list is refused during a build (`example.com`, a look-alike suffix and prefix): 403, nothing dialled. Plain http to an off-list host, to port 8080, with POST, with user info, or to a registry: 403, nothing dialled. A listed package server over plain http gets one origin-form request on port 80 with `Host`, `Connection: close` and no proxy headers, and its answer comes back. CONNECT to a listed package server: 200. The install proxy refuses the package servers (403) and plain http (405). A build without `build.network` has `--network none`.
  - **engine (3):** the engine suite's rel083 group (2) and total (79), and what it does.
  - **docs (4)** and the fixture guard.
- **`tests/confined-engine`, new group rel083, 2 checks.** It needs internet on the host.
  - A tiny Alpine image (`alpine:3.22@sha256:4934...`, pulled with the gate's images before the foreign-object record, and counted as the suite's own) with `apk add --no-cache tini=<the version the Alpine index has now>`, built by `check_exec.build_image` under `build.network: registry`. The linter passes it, the build succeeds through the build proxy, the image has exactly that version (`apk info -v`, `tini --version`, run confined), and nothing labelled is left. The version is read at run time so the check does not rot when Alpine moves the package on.
  - A probe build whose `RUN` fetches from an Alpine package server over plain http (the control, must succeed), from `https://example.com/` and `http://example.com/` (must fail, with the proxy's 403), and from `1.1.1.1` without the proxy (must fail), then exits 1 so its output comes back with the error.
  - The total is now 79: `inc7d` and `rel075`–`rel082` check the new total.
- **The engine double:** `MOADIX_DOUBLE_BUILD_LOG` makes a build fail with the output a test gives.
- **rel082:** its "build proxy unchanged" check now compares 0.8.1 with 0.8.2 (`git diff 867970f 70ad949`), which is what it claimed; 0.8.3 changes the proxy on purpose.

**Results here:**
- **Passed:** rel083 35, rel082 58, rel081 44 (1 skipped: real sandbox-exec), rel080 37, rel079 22, rel078 20, rel077 29, rel076 54, rel075 28, rel074 32, rel073 75, rel072 176, rel071 61, verifiers 97, release 9, skills 43, gate2 299, inc6 70, inc7 141, inc7b 58, inc7c 78, inc7d 150, inc8 72, tools 107 (2 skipped: loopback binding), mainguard 281.
- **Changed expectations:** inc7d and rel075–rel082 expect an engine-suite total of 79; rel082's proxy check compares 0.8.1 with 0.8.2.
- **Caught on the way:** inc7d's safeguard (the engine suite has one `inspect`, on its own pinned images) failed on a second inspect for the Alpine image; it now goes through `inspect_pinned`.
- **check-static:** clean, with uv's folders in the sandbox.

**Not verified here.**
- The real-engine suite, including its new rel083 group, because the sandbox cannot reach Docker. It is the only check that apk really goes through the build proxy (CONNECT), and that busybox wget in a real build gets the proxy's 403.
- The Debian plain-http path against a real `deb.debian.org` and real apt. It is covered by the in-process proxy test (request rewriting, refusals) only; no engine case builds a Debian image.
