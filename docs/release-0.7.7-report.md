# 0.7.7: the four failures of the 0.7.6 engine run

Source: the operator's run of `tests/confined-engine` on 0.7.6. It ran 57 checks: 53 passed and 4 failed. The failures were rel076 MF-53 and MF-51 (Stryker), and MF-49 and MF-50 (axe). MF-46 and cleanup passed.

I reproduced each cause on the real engine myself. I used bare `docker` commands, one per call, on my own objects labelled `moadix.run=ag077`, and removed them all afterwards, including the one image I built. I then verified each fix there with the gate's exact generated script, under the gate's confinement: uid 65534, `--cap-drop ALL`, read-only root, the run's tmpfs, `/deps` read-only, and an internal network.

## 1. Stryker (MF-53, MF-51): Vite could not write beside the packages

**The cut lines.** The operator's run log (kept in the smoke product's evidence) starts with the real error:

```
ERROR Stryker ... StrykerError: Error: ENOENT (mkdir) Error: ENOENT: no such file or directory, mkdir '/tmp/work/node_modules/.vite-temp'
    at async loadConfigFromBundledFile (.../vite/dist/node/chunks/node.js)
```

**Cause.**
- Vite bundles a configuration file into `<nearest node_modules>/.vite-temp`.
- Stryker's sandbox has no `node_modules`: it makes no link when the project's own `node_modules` is a link. So the nearest one was `/tmp/work/node_modules`, the gate's link to `/deps/product/node_modules`, which is mounted read-only. `mkdir` there fails: `Read-only file system` from the shell, ENOENT from Vite's recursive mkdir.
- 0.7.6's temp-folder fix was correct (resolution worked) but not sufficient.

**Reproduced** with the gate's 0.7.6 script on the engine: the same ENOENT, and the sandbox listing showed no `node_modules`.

**Fix** (`LINK_PRODUCT`, used by stryker, tests, eslint, tsc and knip).
- The work copy's `node_modules` is now a real folder, and each of its entries, `.bin` included, links into `/deps/product/node_modules`.
- Vite can then create `.vite-temp` there, and Stryker links that folder into its sandbox.
- `/deps` stays read-only and unchanged.

**Verified on the engine** with the gate's 0.7.7 Stryker script and a PostgreSQL 17 service on an internal network: `run.rc` 0, `mutation.json` written, 30 of 30 mutants killed (28 in the database module, 2 in `sum.js`), no NoCoverage.

**The failure summary.**
- The gate's one-line summary was the log's last 12 lines: for a Node crash, the second copy of the stack trace.
- It now gives the first three error lines (`first errors: …`) before the last lines, and drops stack frames from both.
- The line is capped at 3000 characters.
- Tested with the operator's real 0.7.6 log (`tests/exec/raw/stryker-076-vite-enoent.log`).

## 2. axe sign-in (MF-49, MF-50): the operator's hypothesis, confirmed

**Probe.** I ran the pinned Playwright 1.64.1 against the fixture app on an internal network. A CDP listener recorded `Network.responseReceivedExtraInfo.blockedCookies` and the page's `isSecureContext`.

| Address and flags | Secure context | `__Host-session` | Landed on |
|---|---|---|---|
| `http://sut.moadix.test:3000`, no flag | no | refused, `InvalidPrefix` | /signin |
| same, `--unsafely-treat-insecure-origin-as-secure=<origin>` (0.7.6), headless shell | no | refused, `InvalidPrefix` | /signin |
| same flag, full Chromium (`channel: chromium`) | **yes** | refused, `InvalidPrefix` | /signin |
| `http://sut.localhost:3000`, network alias only | n/a | n/a | `ERR_CONNECTION_REFUSED` (Chromium sends `*.localhost` to loopback) |
| `http://sut.localhost:3000`, `--host-resolver-rules=MAP sut.localhost sut.moadix.test` | yes | **kept** | /tasks |

The hypothesis is confirmed: Chromium refuses the `__Host-` Secure cookie over http on `sut.moadix.test`. It is also worse than assumed. The flag fails twice:
- the headless shell that Playwright launches ignores it;
- where the flag does make a secure context (full Chromium), the cookie code still refuses the cookie, because only `localhost` and `*.localhost` count there.

**Choice: a sut host under `.localhost`**, with a resolver rule. The browser gates open the app as `http://sut.localhost:<port>`, and Chromium maps that name to the app's alias on the run's network (`confined.BROWSER_ALIAS`, `BROWSER_RULE`). Why:
- it is the only variant that kept the cookie;
- the cookie stays `Secure` and `__Host-`, and the product's code is unchanged;
- nothing leaves the run's internal network: the rule maps one name to the existing alias.

The ineffective flag is removed. The runner accepts a rule only of the form `MAP <name>.localhost <alias>` from the gate's plan.

**What a product sees.** The `Host` header is `sut.localhost:<port>` for the browser gates. Schemathesis, ZAP and the wait keep `sut.moadix.test`. A product that checks the Host header, such as task-tracker ("wrong host"), must allow `sut.localhost` in its test stack's configuration. That is configuration, not code.

**Lighthouse CI.**
- The lhci gate now uses a gate-generated `lighthouserc.json` (mounted at `/gx`) with the same URL and the rule. It is a file because the rule has spaces: Lighthouse parses `chromeFlags` with quoting, while the shell would split the rule.
- Verified on the engine with the pinned lhci and the gate's script: `run.rc` 0, an LHR for `http://sut.localhost:3000/`, no runtime error, LCP 751 ms.
- The lhci evidence now records the audited URL.

**Verified on the engine** with the gate's 0.7.7 axe script, runner and plan:
- the sign-in is ok, with 1 cookie, landing on /tasks;
- `/` and `/signin` are checked without the session, `/tasks` with it;
- every title is the page's own, so the CSP was kept (the inline canary did not run);
- 0 violations.

## Tests

- **`tests/rel077`: new, 29 checks.**
  - link 8;
  - summary 5;
  - browser 13;
  - engine 2;
  - guard 1.
- **Failing first.** With the 0.7.6 `gate/` restored, the suite fails every fix check and passes every control: 14 of 18 pass, and the browser group crashes because 0.7.6 has no browser address.
- **The Playwright double now models the measured behaviour:**
  - the cookie is kept only on `.localhost`;
  - a `.localhost` name is reachable only through a resolver rule;
  - the flag does nothing.
- **rel076's axe checks** now give the gate's plan and address. Its check that the flag is set, the 0.7.6 assumption, became a check that the resolver rule is set.
- **Real engine.**
  - The rel076 MF-53, MF-51 and MF-50 checks failed on 0.7.6, and those are the real-engine tests for this release.
  - New group rel077 (2 checks), each of which fails on 0.7.6: lhci audits `sut.localhost`, and a failed Stryker run (no database) names `DATABASE_URL is not set` among its first errors.
  - The engine suite's total is now 59.
