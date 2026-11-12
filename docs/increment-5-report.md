# Increment 5: the new tools

2026-11-12. Built per DESIGN.md §5–6 and Amendment 1 (§4–5: sandbox and network allowlist). Plugin 0.3.0. Nothing was installed or pushed: the live gate still runs increment 4 until the operator reruns `managed/install.sh`.

## 1. Pinned versions

Each pin is the newest release at least 14 days old on 2026-11-11. Every download is checked against a sha256 from the upstream release's own checksum file, or from an npm/PyPI lockfile with integrity hashes. Pins are in `gate/config/tools.yaml`; `managed/fetch_tools.py` installs them.

| Tool | Version | Source | Used in |
|---|---|---|---|
| gitleaks | 8.30.1 | GitHub release + checksums.txt | 9 |
| OSV-Scanner | 2.7.0 | GitHub release + SHA256SUMS | 9 |
| Trivy | 0.76.1 | GitHub release + checksums.txt | 9 |
| Semgrep CLI | 1.182.0 | PyPI, hash-locked (`tools/py/semgrep/requirements.txt`, 67 pins), CPython 3.12 via uv | 9 |
| k6 | 2.3.0 | GitHub release + checksums.txt | 10c |
| github-mcp-server | 2.0.3 | GitHub release + checksums.txt | 11 |
| @redocly/cli | 2.71.2 | npm, lockfile | 5, 10a (Arazzo) |
| @dotenvx/dotenvx | 2.38.2 | npm, lockfile | 6b |
| release-please | 17.11.2 | npm, lockfile | 11 |
| @playwright/mcp | 0.0.83 | npm, lockfile (pulls playwright 1.64.0-alpha) | 10a |
| claude-security | not pinned by MOADIX | `claude-plugins-official` marketplace (0.12.0 at its HEAD today) | 9 |

## 2. What was built

| # | Item | Where | What |
|---|---|---|---|
| — | Runner | `gate/v1/toolrun.py` | The gate runs tools **only** from the root-owned `tools/` folder, never PATH. A missing tool or version mismatch is UNKNOWN (exit 2). Each run gets a scratch HOME and TMPDIR, a minimal PATH and none of the user's environment; the proxy settings pass through only to a scanner's own DB download. Installed, every run is under `sandbox-exec` (writes only to scratch and the output folder; network off, loopback-only or on, per run); without confinement the installed gate refuses (UNKNOWN). Evidence goes to `.sdlc/evidence/<phase>/<name>-<commit12>.<ext>`, plus a line in `.sdlc/evidence/index.jsonl` (tool, version, path, sha256, `source_commit`, `produced_for`). |
| 1 | Phase 5 Redocly | `check_contracts` | `redocly lint` with the gate's config (`recommended`) on every OpenAPI and Arazzo description under `sdlc/05-lld/` at HEAD. Any error fails; none committed fails. The product's `redocly.yaml` and `.redocly.lint-ignore.yaml` are never read (measured: without the gate's `--config`, the product's ignore file hides the error). Arazzo is **executed** in 10a (`check-live-contracts`, `redocly respect` against the loopback base URL). |
| 2 | Phase 9 scanners | `check_scanners --tool …` ×4 | **gitleaks:** full history plus the HEAD tree; every leak is high; reports are redacted; a history scan that read 0 commits fails. **OSV:** every lockfile at HEAD, CVSS → severity, no score → unknown. **Trivy:** `fs` (vuln, misconfig, secret) plus `image` for each image in `product-tools.yaml`; DB downloaded first, scan offline. **Semgrep:** the gate's 9 local rules plus the product's `security/semgrep/*.yml`, `--metrics=off`, no registry, no account.<br>All four run on `git archive HEAD` with the product's ignore files removed and inline suppressions off. **Critical, high and unknown block.** |
| 3 | Claude Security | `gate/secscan.py`, `check_claude_security`, policy | It cannot be a MOADIX subagent: its orchestrator must be a main agent and runs its panel through Workflow. So on `/moadix:request-review` in phase 9 (never on Stop: tokens), the gate runs **one** headless `claude -p --agent claude-security:claude-security --permission-mode auto` per commit. It runs in a sparse clone of HEAD without `.sdlc/`, under `~/Library/Caches/moadix/claude-security/`; the builder's file tools are denied there.<br>Ingest: the SARIF and the revision stamp (must be `…REVISION-<HEAD12>.json`, not `-dirty`) go to evidence; results become **findings** with stable `SF-n` ids (append-only register `.sdlc/evidence/sf-register.json`).<br>Unconfirmed + LOW, or no severity → `unknown`, which blocks. Every SF-n must appear in `sdlc/09-security-report.md` at no lower a severity.<br>Policy: `anthropics/claude-plugins-official` added to `strictKnownMarketplaces` and `extraKnownMarketplaces`; **only** `claude-security@claude-plugins-official` force-enabled beside `moadix@moadix`; the 316 other plugins in `managed/official-plugins.txt` force-**disabled**. `render_policy.py` refuses any template that enables more. |
| 4 | Phase 10a live verifier | `agents/live-verifier.md`, `verify.py`, `plugin.json` | Plugin MCP server `playwright`: pinned 0.0.83, `--isolated --headless --caps devtools --storage-state .auth/storage-state.json`, loopback-only `--allowed-origins`, `--output-dir` = the verifier's evidence folder.<br>Hook: the live verifier may use only `mcp__plugin_moadix_playwright__*`. **Withheld by pattern:** `browser_network_request(s)`, `browser_evaluate`, `browser_run_code_unsafe` (cookies and tokens would reach the transcript).<br>Brief: every AC, **every button** (`BTN-n` with path:line, found in the source at HEAD), `base_url`, `.sdlc/untested.yaml`.<br>Evidence: each AC and each button mapped to artifacts that exist in the evidence folder; a video and a trace must be present; an unexercised button or an AC with no artifact blocks.<br>**v1's live probe re-enabled** as `check-surface-live` (10a): `live.base_url` must be loopback, otherwise it fails ("never a production URL"); an app that does not answer is UNKNOWN. |
| 5 | Phase 10c k6 | `check_load`, `gate/config/k6/wrapper.js` | The product's script runs through the gate's wrapper: `export *` passes through options and functions, and the gate's `handleSummary` writes the summary JSON and a JUnit file with **one test case per threshold**. The verdict is k6's exit code, cross-checked with the JUnit. **Measured: a crossed threshold exits 99.** No thresholds fails. Loopback only: `base_url` check plus `--blacklist-ip` over every non-loopback v4/v6 range (measured: a public IP is refused by k6 itself). **The product's SQL invariant check is required** (`load.invariant_check`) and must exit 0. |
| 6 | Phase 11 release | `check_release`, `gate/v1/mcpclient.py`, `plugin.json` | Local: release-please config and manifest committed; `googleapis/release-please-action` pinned to a 40-hex SHA.<br>Remote: the **gate is the MCP client** of the pinned `github-mcp-server stdio --read-only`, and reads nothing if the server lists a single write tool. It checks that HEAD is on GitHub; that HEAD is the merge of a `release-please--*` PR **merged by a human**; that every CI run for HEAD is completed and green; and that no open code-scanning alert is high or critical.<br>Token: login Keychain item `moadix-github-readonly`; none is UNKNOWN. The plugin also ships `github` (`--read-only`) for the agent in phase 11. |
| 7 | Phase 6b dotenvx | `check_env` | Required keys come from `.env.example` (or `env.required`). Each file in `env.files` (default `.env.production`) must be committed, have every required key, every value `encrypted:`, and a `DOTENV_PUBLIC_KEY*`; no `.env.keys` or `DOTENV_PRIVATE_KEY*` may be committed. A value is never captured, printed or recorded: the pattern stops at the `encrypted:` prefix, and the evidence holds key names only. |
| 8 | Waivers | `opcmd._verifier_finding` | `WAIVE <role>.<finding id>` (e.g. `code-reviewer.S1`) and `WAIVE SF-n`, with owner, scope and expiry. The severity comes from the gate-checked evidence or register, not the report. **Refused for critical, high and unknown**, and when the finding is not in the evidence. |
| — | Manifest | `phase-manifest.yaml`, `manifest.py` | Every phase's `gate_run` names its tool and validator. `moadix:<server>` matches **only** the plugin's pinned server, not a user's same-named one. `external_skills` lets the agent run `claude-security:claude-security` in phase 9 for feedback only. |
| — | Registry | `registry.yaml` | 12 new validators, with per-validator timeouts (Trivy 1800 s). |
| — | Fix (increment-2 port defect) | `check_surface_coverage`, `check_authz_matrix`, `check_size_profile` | `ROOT` resolved to MOADIX's own home, not the product, so these never read the product's `.sdlc/config`. Now the product root under the gate. |

## 3. Network allowlist entries added (managed sandbox)

| Host | For |
|---|---|
| `release-assets.githubusercontent.com` | GitHub release downloads now redirect here (measured) |
| `api.osv.dev` | OSV-Scanner queries |
| `api.deps.dev` | OSV-Scanner's package data source (its default) |
| `osv-vulnerabilities.storage.googleapis.com` | OSV offline databases |
| `mirror.gcr.io`, `ghcr.io`, `pkg-containers.githubusercontent.com` | Trivy's vulnerability DB (OCI) |
| `api.github.com` | release-please CLI |

Nothing else was added to the network list. Two filesystem write paths were added, so the agent's own feedback runs work: `~/Library/Caches/trivy` and `~/.semgrep`. The test checks that exactly these 8 hosts were added to the network list.

## 4. Tests

| Suite | Result | Evidence |
|---|---|---|
| Increment-5 `tests/tools/run.py` (real pinned tools, fixtures) | **95/95 passed, 2 skipped** in 57 s | `docs/evidence/increment-5-suite.txt` |
| Policy `tests/install/render.py` | **11/11**, including "the rendered policy enables EXACTLY moadix and claude-security" and a negative control | `docs/evidence/increment-5-policy.txt` |
| Increment-4 suite | **97/97** (agent check now covers the live verifier) | `…/increment-4-suite-after-increment-5.txt` |
| Increment-3 suite | **43/43** | `…/increment-3-suite-after-increment-5.txt` |
| Increment-2 suite | **299/299** (registry count separates increment 5's 12) | `…/increment-2-suite-after-increment-5.txt` |
| Release check | **9/9** (0.2.1 → 0.3.0) | `docs/evidence/increment-5-release.txt` |
| ruff, mypy, shellcheck, hardcoded-state | clean (9 phase-label exemptions added, as in increment 4) | `docs/evidence/increment-5-static.txt` |
| Install dry run, attack corpus | **not run** (Keychain, `~/moadix-scratch`: Terminal only) | — |

The increment-5 suite, by group. Each tool has a clean case and a planted problem:

| Group | Checks | Clean → passes | Planted → caught (plus bypass attempts) |
|---|---|---|---|
| pins | 10 | 9 tools installed with matching stamps | a download with the wrong sha256 is refused |
| redocly | 5 | OpenAPI 3.1 + Arazzo, report indexed | path-parameter lint error; the product's `redocly.yaml` and lint-ignore cannot hide it; no contract fails |
| dotenvx | 5 | real `dotenvx encrypt` output; no value in output or evidence | unencrypted value (key named, value never shown); missing required key; `.env.keys` committed |
| gitleaks | 4 | clean history | fake AWS key **removed from the tree, still in history**; `gitleaks:allow`, `.gitleaksignore` and `.gitleaks.toml` cannot hide it; evidence redacted |
| osv | 3 | is-number 7.0.0 | **lodash 4.17.15** (high, CVSS up to 8.1); `osv-scanner.toml` cannot ignore it |
| trivy | 3 | non-root Dockerfile (real DB download) | `USER root` (DS-0002 high); `.trivyignore` and `trivy.yaml` cannot hide it |
| semgrep | 4 | clean code | shell injection; `nosemgrep` and `.semgrepignore` cannot hide it; the product's own rules add findings |
| k6 | 9 | thresholds hold, invariant passes, JSON+JUnit indexed | **broken threshold → k6 exits 99**, a failed JUnit case; no thresholds; **failing SQL invariant**; no invariant declared; non-loopback base_url; a public IP refused by the blacklist |
| claude-security | 15 | Stop starts no scan; request-review starts exactly one, in a clone without `.sdlc/`; a clean scan passes; one scan per commit | high finding; unconfirmed LOW → unknown; SF-n missing from the report; stamp for another commit; `-dirty` stamp; builder write into a scan clone; manifest |
| live | 16 | brief with every AC and button; browser tools allowed; full evidence passes | 4 withheld tools; a user's unpinned server; a skill; unexercised button; AC without artifact; no video; non-loopback probe and Arazzo URL; app not running → UNKNOWN |
| playwright-mcp | 3 | the real pinned server's 25 tools; the withheld pattern matches exactly the 4 network/script tools; the agent lists only allowed ones; plugin.json pins | — |
| release | 11 | human-merged release PR, green CI | bot-merged; failed CI; open high alert; HEAD not a PR merge; a server with write tools; no token → UNKNOWN; action pinned by tag. The **real** github-mcp-server 2.0.3: 21 tools with `--read-only`, none writes; without the flag it lists `merge_pull_request`, `push_files` and others |
| waivers | 5 | `code-reviewer.S1` (medium) and `SF-3` (medium) recorded | high verifier finding refused; unknown SF refused; nonexistent finding refused |
| worker / guard | 2 | end to end, the Stop hook runs check-contracts in the gate's worker and REVIEW shows it failing; no test touched a real product or the user's files | — |

**Skipped (2), not passed:** an Arazzo workflow passing and failing against a running local app, and the live probe confirming a route on one. This sandbox forbids binding a loopback port (EPERM). They run automatically from Terminal.

## 5. Known gaps (stated plainly)

- **Claude Security live run is unmeasured.** The suite stubs `claude`. Not measured:
  - whether a headless `claude -p --agent claude-security:claude-security --permission-mode auto` session completes a scan under the managed policy (sandbox, `CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH=1`, managed-hooks-only);
  - whether its Workflow agents count against the depth cap;
  - the exact revision-stamp contents.

  If the scan fails, phase 9 fails closed: "the scan for HEAD failed". I could not run it from here (nested `claude` is denied, invariant 4). Section 6, step 7 is the measurement.
- **`sandbox-exec` confinement of the tool runs is unmeasured**, as in increment 2: it cannot nest inside this session's sandbox. The installed gate requires it (no confinement is UNKNOWN). The fixture gate runs unconfined, and the evidence index records `confined: false` for those runs.
- **Plugin MCP details unmeasured:**
  - whether relative `--storage-state` / `--output-dir` resolve against the product root (the MCP server's cwd);
  - whether `${MOADIX_GITHUB_TOKEN}` expands in plugin `mcpServers` env.

  `plugin.json` hardcodes macOS paths (`/opt/homebrew/bin/node`, `/Library/Application Support/ClaudeCode/moadix/tools`); Linux needs its own paths.
- **The live verifier was not driven against a real page here.** No local server can be bound. Its restrictions, brief and evidence check are tested; the browser run is the toy run's (increment 6).
- **Real GitHub response shapes are untested.** check-release was exercised against a stub that returns REST-shaped JSON. The real server's tool list and argument names were checked against 2.0.3's schemas, but its answers need a token and a repo. If a shape differs, the check fails closed.
- **claude-security's version is not pinned by MOADIX.** Pinning a marketplace to a ref in `strictKnownMarketplaces` was not measured, so it was not done. `managed/official-plugins.txt` is a snapshot (commit c39087c): a plugin the marketplace adds later is **not** force-disabled until the list is regenerated.
- **Tool databases are live, not pinned:** Trivy DB, OSV data. Trivy's DB cache (`~/Library/Caches/moadix/trivy`) is user-writable. The agent's Bash sandbox cannot write it, but its file tools are not denied there: a poisoned DB is a residual risk.
- **Semgrep's rules are MOADIX's own 9-rule baseline.** The Semgrep Registry needs the network and its rules licence restricts redistribution. A file Semgrep cannot parse is skipped by Semgrep; the gate now lists such files in its notes but does not fail on them.
- **Medium and low verifier findings never blocked**, and still don't. WAIVE now records them as accepted with owner, scope and expiry; it does not change what blocks.
- **`browser_console_messages` stays available** to the live verifier. It is not network-reading, but a console log can carry a token.
- **The dotenvx check reads each env file's bytes into memory** to test the prefix. It never captures, keeps or writes a value, and never decrypts.
- **Forcing claude-security on is machine-wide**, as are the 316 force-disabled official plugins (INSTALL.md says so).

## 6. Install steps (operator, in Terminal)

1. Close every Claude Code session.
2. `cd ~/moadix && git log --oneline -1` (note the commit), then `git push`.
3. `managed/install.sh`: password once.
   - Expect `3b/6 Fetching the pinned gate-run tools`, ten `got …` lines and a `tools:` line. Playwright's Chromium installs after them.
   - The policy is rewritten: claude-security forced on, every other official plugin forced off, 8 new allowlist hosts.
4. Store a **read-only** fine-grained GitHub token for phase 11: `security add-generic-password -s moadix-github-readonly -a moadix -w`. For the agent's `github` MCP server, also `export MOADIX_GITHUB_TOKEN=…` in the shell that starts Claude Code.
5. Open Claude Code and run `/plugin marketplace update moadix`, then `/reload-plugins`.
   - `/plugin` shows moadix 0.3.0 and claude-security enabled.
   - `/mcp` lists `plugin:moadix:playwright` and `plugin:moadix:github`.
   - The agent count rises by 1 (live-verifier).
6. Optional, in Terminal (includes the 2 loopback cases skipped here):
   ```
   /usr/bin/python3 managed/fetch_tools.py ~/.cache/moadix-tools
   /usr/bin/python3 tests/tools/run.py
   ```
   Expect `97 checks, 97 passed, 0 failed, 0 skipped`.
7. Measure the Claude Security scan once, in a toy product at phase 9 with a committed tree:
   - Have the agent call `/moadix:request-review`.
   - Then `cat .sdlc/cache/verify/9/claude-security/result.json` once `scan.lock` is gone. Send me that file and `scan.log`.
