# 0.7.3: executing gates start (MF-27), run logs kept, smoke runs, read protection, one code per phase

Sources:
- the operator's review of 0.7.2, items 1–6;
- `~/task-tracker/docs/moadix-findings.md` MF-27 and MF-28, read only. There is nothing after MF-28.

0.7.3 includes 0.7.1 and 0.7.2, which were committed but not installed.

## 1. MF-27: every tool has a valid user and home

**Chosen:** the confined runner runs as uid/gid **65534 (`nobody`)** instead of 10001 (`gate/config/confinement.yaml` `uid`).

**Why this one:**
- `nobody` has a passwd entry in every pinned image, because they are all Debian or Ubuntu based: node:24-slim, node:24-bookworm, python:3.12-slim and playwright noble. `os.userInfo()` and anything else that looks up the current user then works.
- No image is modified.
- No file is mounted: Docker cannot bind a single file such as `/etc/passwd` without a host mount, which is forbidden.
- Confinement is unchanged: still non-root, `--cap-drop ALL`, `no-new-privileges`, a read-only root, no host mounts. `HOME` stays `/tmp/home` on the run's tmpfs.
- The images' own users were the alternative. They would differ per image (node 1000, and none in python), and they own files in the image.
- ZAP (1000) and the postgres service (999) keep their own users, as before.

**Guard:** before the first run in an image, `confined.Run.check_user` runs `getent passwd <uid>` in a helper container (no network, no capabilities, read-only). Without an entry the gate reports UNKNOWN, naming the image and the uid, instead of letting a tool crash.

**likec4:** a crash of `likec4 validate` with no `model.json` is reported as "likec4 validate exited N", not as a missing file.

## 2. A failing executing gate says why, and keeps its log

- **Every run's log is kept**, pass or fail, in the evidence folder: `.sdlc/evidence/<phase>/exec-<gate>-run-<commit>.log`, with an index line in `toolrun.record`. It holds:
  - the container's exit code;
  - every `*.rc` the script wrote;
  - the list of files written, with sizes;
  - every `*.log` and the container's stdout and stderr, each the last 400 lines and at most 64 KiB.
- **A failure line** names the container exit code, the tool exit codes, the last 12 lines of the tool's log and where the full log is kept. This holds for a missing output file, a refused output and a run killed for its wall clock or memory.
- **Redaction** (`check_exec.redact`) removes:
  - private-key blocks;
  - `Authorization`/`Bearer` values;
  - `key=value` pairs whose key names a secret, token, password, API key, private key, credential or `DOTENV_PRIVATE_KEY`;
  - URL credentials;
  - GitHub, OpenAI-style, Slack, AWS, Google and npm token shapes;
  - long mixed-case-and-digit strings.

## 3. Smoke runs (tests/confined-engine, Terminal)

**Group `user` (5 checks):**
- uid 65534 resolves in the node, node-full, python and chromium images;
- uid 10001 is refused before any run.

**Group `smoke` (13 checks).** One run per executing gate, through `check_exec.run_gate` as the gate calls it, with the real pinned tool, on `tests/fixtures/smoke`. Each check passes when the run writes its expected file:

| Gate | Phase | Expected file |
|---|---|---|
| pytm | 4 | `tm.json` |
| LikeC4 | 3 | `model.json` |
| dependency-cruiser | 3, without `src/` (MF-26, configuration only) | `depcruise.json` |
| dependency-cruiser | 7 | `depcruise.json` |
| knip | 7 | `knip.json` |
| ESLint | 7 | `eslint.json` |
| tsc | 7 | `tsc.txt` |
| Stryker | 8 | `mutation.json` |
| the test suite | 8 | `junit.xml` |
| Schemathesis | 8 | `st/junit*.xml` |
| ZAP | 9 | `zap.json` |
| Lighthouse CI | 10a | `lhr-*.json` |
| axe | 6 | `axe.json` |

**The fixture:**
- a tiny CommonJS app with one unit and one test;
- a page for axe and Lighthouse, and `/health` with its OpenAPI;
- a pytm model and a LikeC4 model;
- the rules file, an ESLint flat config, `tsconfig`, a Stryker JSON config;
- a digest-pinned Dockerfile and a compose file.

`package-lock.json` pins eslint 9.39.5, @eslint/js 9.39.5, typescript 5.9.3 and @stryker-mutator/core 10.1.1. The tools come from the gate's own lock files.

**What the suite leaves behind.** The suite total is 49. Each run uses the suite's label, so its containers, volumes and networks are removed by label. A live gate builds the app's image, and nothing in MOADIX may remove an image (ruling 3 on increment 7d; `tests/lib/no_prune.py`). The suite lists those images at the end and leaves them out of the foreign-object comparison. The installed live gates also leave their built image behind, as before 0.7.3.

**Not run here:** the agent cannot reach Docker. That a run passes, as opposed to starting and writing its file, depends on the fixture and is not what these checks assert.

## 4. Read protection

**The rules.** The same set is applied three ways:

| Protected | Sandbox `denyRead` | Managed rule | Hook (Read tool, any Bash word, a substitution) |
|---|---|---|---|
| dotenvx private key file | `~/**/.env.keys` | `Read(~/**/.env.keys)` | name `.env.keys` |
| private keys | `~/**/*.key`, `~/**/*.p12`, `~/**/*.pfx`, `~/**/*.jks`, `~/**/*.keystore`, `~/**/id_rsa`, `~/**/id_ed25519`, `~/**/id_ecdsa`, `~/**/id_dsa`, `~/**/*key*.pem`, `~/**/*private*.pem` | `Read(<the same>)` | names `*.key`, `*.p12`, `*.pfx`, `*.jks`, `*.keystore`, `id_rsa`, `id_ed25519`, `id_ecdsa`, `id_dsa` (not `.pub`), `*key*.pem`, `*private*.pem` |
| the overlay | `~/.config/moadix` | `Read(~/.config/moadix/**)` | path under `~/.config/moadix` |

**The hook's scope.**
- The hook matches anywhere; the policy rules cover `~/**`, where products live.
- A Bash word that is a find, grep or rg pattern (`-name '*.key'`) is not a file.
- A word with a space in it (a commit message) is not a file either.

**What stays readable:**
- an encrypted `.env`, and `.env.*` files: dotenvx encrypts the values, and the key lives in `.env.keys`;
- `.env.example`;
- `*.pub` files;
- public certificates.

**Certificates: conflict, not built.** `*.pem`, `*.crt` and `*.cer` include the CA bundles TLS clients read: certifi's `cacert.pem` in every Python environment, plus node's and curl's. The sandbox's `denyRead` has no exceptions, so a certificate rule would break pip, npm and curl inside the sandbox. Private keys stored as `.pem` are covered by name (`*key*.pem`, `*private*.pem`). Public certificates need your ruling, for example: a fixed list of certificate folders (`~/**/certs/`, `~/**/tls/`), or no rule.

**The 0.7.2 rule changed.** A substitution reading `.env` was refused; it is now allowed, since an encrypted `.env` stays readable. `.env.keys` is refused instead.

**What a product's own tests need, so they do not break inside the sandbox:**
- **No real key in the repository or under the home folder.** A test that needs a key or a certificate pair generates one at run time, in memory (`crypto.generateKeyPairSync`) or in `os.tmpdir()`. The sandbox's temp folder is not under `~`, so the rules do not cover it.
- **No `.env.keys` at test time.** Tests that need configuration read an unencrypted `.env.test` with non-secret values. They do not decrypt `.env`.
- **The gate's own runs are unaffected.** The confined runs receive only the committed tree (`git archive HEAD`), and `.env.keys` is never committed.

**Live policy check.** Rows 13–29 in "Local overlay" of `docs/INSTALL.md`:
- the hook refusing by name (13) and by the Read tool (14);
- one sandbox row per new rule, the name hidden behind `?` or a variable so that only `denyRead` can stop it (15–27);
- two positive controls: an encrypted `.env` and a certificate stay readable (28, 29).

## 5. One code per phase

**Proposals file.** The agent writes `.sdlc-proposals/waivers.yaml`: `waivers:` entries with `id` and `reason`, optionally `owner`, `scope` and `expiry`. ADOPT ignores this file.

**REVIEW** lists each proposal, judged now, with the file's sha256 and the command that records them.

**`APPROVE <phase> WITH-WAIVERS <code>`** writes one ledger line under one code, carrying:
- the approval;
- exactly the proposed waivers, each with its finding's fingerprint (they lapse as before);
- `waivers_file_sha256`.

Replay turns the line into the waivers. The file is removed afterwards, as ADOPT removes what it adopted.

**It is accepted only when:**
- every proposal passes the WAIVE checks: no BLOCKER, no high or critical security finding, no protected carry;
- every id is one the gate knows: a verifier finding, `gap-critic.GC-…`, SF-n in Claude Security's result, SEC-n in the phase-9 report, or `CARRY-…`;
- every validator that failed judges verifier evidence (`check-verifiers-*`), and that evidence passes when the gate judges it again with the proposed waivers in force.

Any other failure refuses the whole command, and nothing is recorded.

**Plain `APPROVE <phase> <code>`** is refused while a MAJOR is unwaived, as before.

**WAIVE defaults.** In every WAIVE form, `owner`, `scope` and `expiry` are optional:
- `owner` defaults to `operator`;
- `expiry` defaults to 30 days from today;
- `scope` defaults to the finding's document: for a gap-critic finding its cited path; for another verifier's, its first citation; for a carry, its citation; for SF-n, its file. A multi-id WAIVE records one scope per id.

## 6. MF-28

By design. `/moadix:coverage` now says that a `docker` command reaches the engine only as the whole command, and shows docker's own flags in place of `cd`:
- `--project-directory`/`-f` for compose;
- `build -f <dir>/Dockerfile <dir>`;
- `run -w` and `exec -w`;
- `--env-file`.

## INSTALL

"Updating from 0.7.0 to 0.7.2" is replaced by "Updating from 0.7.0 to 0.7.3", in step-by-step form. Its order:
1. the version;
2. every Terminal-only suite: mainguard, inc6, `tests/install/render.py` (also stopped by the hook), the corpus, the dry run, the real-engine suite at 49;
3. the reinstall and the read fixtures;
4. the product-string check (`tests/install/no_product_strings.py`, new) and the push of master and v0.7.3;
5. the refresh;
6. the live check with the new rows.

**Push before refresh in the older sections:**
- "Updating from 0.6.3 to 0.7.0" refreshed before pushing;
- "Updating from 0.4.0 to 0.7.0" pushed last and never refreshed.

Both now push, then refresh. "Updating MOADIX" says so too. Increments 5 and 6 already pushed first.

## Tests

- `tests/rel073/run.py`: new suite, 75 checks:
  - user 3;
  - logs 13;
  - reads 41;
  - waivers 12;
  - docs 5;
  - guard 1.
- `tests/rel072` was updated for item 4.
- `tests/inc7c` and `tests/inc7d` were updated for the new uid and the passwd check; `tests/gate2`, because `scope` is now optional.
- The counts of all suites run here are in the commit message.
- **Not run here** (Terminal: steps 2–7 of the procedure): mainguard, inc6 and render, which the installed guard stops; corpus, the dry run and the real-engine suite (Keychain or Docker).
