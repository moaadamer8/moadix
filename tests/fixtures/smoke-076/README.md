# Smoke fixture 0.7.6

The product `tests/confined-engine/run.py` (group `rel076`) runs the 0.7.6 fixes against, end to end, with
the real pinned tools:

- every HTML page sends `Content-Security-Policy: script-src 'self'` and carries an inline script that would
  retitle the page to `CSP-BYPASSED` if the policy were not enforced (MF-49);
- `/tasks` needs a session; `POST /signin` with the fixture user sets a `__Host-` Secure cookie (MF-50).
  The fixture user's sign-in values are fixture text, not credentials of anything;
- `src/tasks.js` is covered only by `tests/tasks.test.js`, against the gate's PostgreSQL service (MF-51);
- Stryker runs Vitest, whose configuration imports `vitest` (MF-53);
- `build.network: registry`, so a live gate starts the install proxy and the build proxy (MF-54);
- `design/screen-states.csv` has a designed row with no URL, declared in `axe.checked_elsewhere` (MF-50).

`package-lock.json` pins the product's tools; regenerate it with `npm install --package-lock-only` if they change.
The suite copies `product-tools.yaml` into the throwaway repository's gate configuration folder.
