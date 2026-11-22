# 0.7.6: the executing gates that stopped phase 8 (task-tracker MF-46, MF-49 to MF-54)

Source: the first full product run (task-tracker, size S) under 0.7.5, blocked in phase 8. Its findings file
(`docs/moadix-findings.md` in that product) records MF-46 and MF-49 to MF-52. MF-53, MF-54 and the stale
container come from the operator's brief for this release. Nothing else changed.

Each fix has two tests:
- a failing test written first, in `tests/rel076`, run through the engine double (no Docker) and a Playwright double (no browser);
- a real-engine case in group `rel076` of `tests/confined-engine`, on the new fixture `tests/fixtures/smoke-076`.

The fixture app sends `Content-Security-Policy: script-src 'self'`. It carries an inline canary script that would retitle a page `CSP-BYPASSED` if the policy were not enforced. It has a sign-in that sets a `__Host-` Secure cookie, a module tested only against PostgreSQL, Vitest under Stryker, and `build.network: registry`.

## MF-54: Schemathesis always ended UNKNOWN (two proxies, one name)

**Cause.** A live gate that has a tool to install starts the install proxy (`check_exec.py`, the install step). With `build.network: registry` it then starts a second proxy for the image build (`start_live`). `confined.Run.proxy` named both `moadix-<run>-proxy`, so the engine refused the second (`Conflict. The container name ... is already in use`). `_d` turned that into Unavailable, and the gate reported UNKNOWN. Every Schemathesis, LHCI and axe run of a product with a registry build hit this.

**Fix.**
- `proxy(..., purpose)` names each proxy `moadix-<run>-proxy-<purpose>` (`install`, `build`).
- The caller removes it with `Run.remove()` in a `finally` as soon as its step ends.
- `close()` removes everything left by the run's label on every other exit path. Each of its engine calls is now attempted even when an earlier one times out.
- The engine double now refuses a name in use, as the engine does.

## MF-53: Stryker could not find vitest in its sandbox

**Cause.** The gate links `node_modules` to `/deps/product/node_modules` in `/tmp/work`. Stryker copies the project into `<tempDirName>/sandbox-*` and makes no `node_modules` link of its own when `node_modules` is itself a link (the engine run's log shows none). 0.7.5 set `--tempDirName /tmp/stryker-tmp`, outside the work folder, so walking up from the sandbox never reached a `node_modules`. Vitest's bundled configuration then failed on `import 'vitest'`.

**Reproduced here** with the fixture's real Vitest 5.1.0:
- from a copy under `/…/tmp/stryker-tmp/sandbox-a`: `Cannot find package 'vitest' imported from …vitest.config.mjs.timestamp-….mjs`, the task-tracker error;
- from a copy under `/…/tmp/work/.stryker-tmp/sandbox-b`: `Tests 1 passed`.

Stryker itself cannot run in the agent's sandbox, which blocks its worker port.

**Fix.** `--tempDirName .stryker-tmp`, inside the work folder. Node then finds the work folder's `node_modules` link by walking up, and Stryker leaves its own temporary folder out of the copy.

## MF-51: Stryker had no database

**Fix.** The stryker gate gets the same gate-started services (`tests.services`, the PostgreSQL service on an internal network) and the same `DATABASE_URL` as the tests gate (`SERVICE_GATES`). Without services nothing changes: no network, no service.

## MF-49: axe was injected as an inline script

**Cause.** `page.addScriptTag({content})` adds an inline `<script>`, which `script-src 'self'` refuses on every page.

**Fix.** The runner evaluates axe-core with `page.evaluate(axeSource)`. That is a DevTools evaluation: Playwright evaluates through the inspector, which is exempt from the page's policy for the duration of the call, and axe-core 4.14.0 uses no `eval` or `new Function` (checked) that could fail later. The policy is not bypassed (no `bypassCSP`), so the page is checked as served. The runner checks that `window.axe` exists before it runs.

Not verified in a browser here: Chromium cannot start in the agent's sandbox. The real-engine case does verify it. The fixture's canary must not have run (no page titled `CSP-BYPASSED`), and every page must be checked.

## MF-50: axe had no session and could not address ID-bound screens

**New `product-tools.yaml` keys** (adopted with ADOPT):

```yaml
axe:
  public: ["/signin", "/signup", "/privacy", "/terms"]   # visited without the session
  signin:
    steps:                         # at most 20; the first is a goto
      - goto: /signin
      - fill: "#email"
        value: axe@example.test    # fixture text for the gate's throwaway stack, never a credential
      - fill: "#password"
        value: a-fixture-password
      - click: "button[type=submit]"
      - wait_url: /tasks
  checked_elsewhere:               # designed screen-states rows with no url
    - screen: Edit task
      state: default
      how: "its address holds a random task id; the product's own signed-in axe test opens it"
```

**How the gate uses them.**
- It validates the steps before the engine is called. The allowed actions are goto, fill with value, click and wait_url. Paths must be app-relative. A selector or value must be one line of at most 200 characters, and a value that looks like a secret or token is refused.
- The runner signs in once in its own browser context and visits every path that is not in `axe.public` with that session.
- A failed sign-in fails the gate, and so does a session page that lands on the sign-in page. The evidence never holds a cookie value.
- Chromium is launched with `--unsafely-treat-insecure-origin-as-secure=<app origin>`. It then keeps a Secure `__Host-` cookie over the internal network's plain http, as it does for `http://localhost`. That is the MF-50 cookie problem on `sut.moadix.test`. The real-engine case is the proof: the fixture's cookie is `__Host-` and Secure.
- The runner counts the app's cookies from `context.cookies()` and matches the host itself. Playwright's `cookies(<url>)` leaves a Secure cookie out for any non-localhost http URL (its `filterCookies`, read in the pinned 1.64.1), so asking for the app's URL would have reported "no cookie" even with the session kept. The Playwright double models that filter, and a test caught it.

**Rows with no URL.** A designed `design/screen-states.csv` row with no `url` is named in a note instead of failing when `axe.checked_elsewhere` declares its screen and state with a `how` of four words or more. An undeclared row still fails. A declaration that matches no URL-less designed row fails too.

**For task-tracker.** The product must provide a sign-in user in its `tests/gate/` stack, either seeded or created by the steps through sign-up. Its rows with no URL need entries in `checked_elsewhere`: the edit and delete confirmations, and the error states no plain GET produces.

## MF-46: the gate's own `sdlc/08-traceability.md` blocked verifiers

**Fix.**
- check-traceability writes its generated matrix to `.sdlc/cache/08-traceability.md`, the gate's cache, which no clean-tree check counts. It never writes into a phase's path. If the cache cannot be written, as in a feedback run, the verdict still stands.
- A leftover 0.7.5 copy at `sdlc/08-traceability.md` is ignored by the clean-tree checks (`validation.changed_paths`: tree state, verifier launch, security scan). It is ignored only while it is untracked and still starts with the gate's generated header. Any other file at that path, or any other change, still blocks.

## The stale gate container

**Fix.**
- Every object a gate run creates now also carries `moadix.owner=gate`, `moadix.pid=<gate process>` and `moadix.started=<time>`.
- At the start of each run, `Run.sweep_stale()` removes, by run label, every run whose gate process is gone or that started more than 6 hours ago. It also removes any pre-0.7.6 gate run (run label `x` + 10 hex digits, no owner label).
- It never touches the engine suite's runs, compose projects or unlabelled objects. The gate names the runs it removed in its notes.
- A gate stopped with SIGTERM now runs its cleanup and reports UNKNOWN.

**Engine suite.** The suite lists objects of earlier real gate runs and leaves them out of its foreign-object comparison, because the gate's sweep may remove them. The suite itself still removes only its own.

## Tests

- `tests/rel076`: new, 54 checks: proxy 6, stryker 5, axe 21, trace 5, stale 6, engine 10, guard 1. On 0.7.5 the same suite fails 29 of its first 37 checks (the rest are controls); three groups crash outright.
- `tests/confined-engine`: new group rel076 (7 checks); the fixed total is 57. `tests/inc7d` and `tests/rel075` check the new total.
- The engine double refuses a container name in use and answers label filters and `--format` with labels. It can also hold a run open (`MOADIX_DOUBLE_SLEEP`) so a test can stop the gate.
- Counts of every suite run here are in the commit message.
