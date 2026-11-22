# 0.7.8: one app origin for every live gate

**Source.** The first product run on 0.7.7 found that axe and Lighthouse CI reached the app as `sut.localhost:<port>`, but Schemathesis (and ZAP) still sent `Host: sut.moadix.test:<port>`. A product that accepts only its own origin therefore failed one gate, whatever it configured.

## The value

`gate/confined.py`:
- `APP_HOST = "sut.localhost"`
- `app_origin(port)`, which returns `http://sut.localhost:<port>`

This is the one value every live gate reads. `check_exec.browser_url` returns it, and so do the scripts of all four live gates. `/moadix:coverage` documents it in a new paragraph, "Live gates: the app's origin", generated from the same value. A product sets `APP_ORIGIN` in its gate test stack to exactly that value.

## What each live gate does

| Gate | URL and Host | Origin |
|---|---|---|
| Schemathesis | `--url http://sut.localhost:<port>` | `-H 'Origin: <origin>'` on every request |
| ZAP | `-t http://sut.localhost:<port>` | ZAP's replacer (`replacer.full_list(0)`, REQ_HEADER `Origin`) adds it to every request |
| Lighthouse CI | `lighthouserc.json` URL | sent by the browser |
| axe | the runner's base URL | sent by the browser |

The wait for the app (bash `/dev/tcp`) uses the same host.

**Reaching the host.** The app's service gets `sut.localhost` as its network alias, and Docker's DNS answers it for Python, Java and bash. It also keeps `sut.moadix.test`, for one reason: Chromium resolves `*.localhost` to loopback itself, so the browser gates still map `sut.localhost` to that second alias (`--host-resolver-rules`, unchanged from 0.7.7). No gate sends `sut.moadix.test` in a URL, Host or Origin.

## Measured on the real engine

The fixture app ran with `APP_ORIGIN=http://sut.localhost:3000`, on my own objects labelled `moadix.run=ag078`, which were all removed afterwards.

- **Python's resolver** finds `sut.localhost` through Docker's DNS. The app answered:
  - `Host: sut.localhost:3000`: 200;
  - `Host: sut.moadix.test:3000`: 421;
  - a foreign Origin: 403.
- **Schemathesis** (the pinned 4.32.7, with the gate's exact script) found no issues. The control, the 0.7.7 invocation against `sut.moadix.test`, got 421 on every call.
- **ZAP** (the pinned image, with the gate's exact script under the gate's options) exited with run.rc 0 and FAIL 0. It scanned the site `http://sut.localhost:3000`, and its alerts (anti-CSRF on the sign-in form) show it read the real pages, not refusals.
- **Lighthouse CI and axe** used `sut.localhost` on the engine already in 0.7.7. Against the strict app they are covered by the new engine group.

## Tests

- **`tests/rel078`: new, 20 checks.** With the 0.7.7 gate restored, the fix checks fail and three groups crash.
  - origin 9;
  - service 1;
  - fixture 2;
  - gates 4;
  - doc 2;
  - engine 1;
  - guard 1.
- **`tests/fixtures/smoke-076`.** The app enforces `APP_ORIGIN` when it is set, and its `compose.yaml` sets it to the gate's origin. Every existing real-engine check on this fixture now also runs against the strict app.
- **`tests/confined-engine`.** New group rel078: Schemathesis, ZAP, Lighthouse CI and axe must each pass (no fail, no 421) against the strict app. The total is 63. `inc7d`, `rel075`, `rel076` and `rel077` check the new total.
- **`tests/rel077`.** Its wait check now expects the origin's host, which is the 0.7.8 change.
