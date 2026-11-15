# Installing MOADIX on your Mac

This takes about 10 minutes. You need your macOS password once, and your phone with Microsoft Authenticator.

## Before you start

- **Close every Claude Code session.** The policy applies to the whole machine as soon as it is written.
- **Use Terminal, not Claude Code.** The installer refuses to run inside a Claude Code session.
- **Tools:** Claude Code 2.1.295 or newer (`claude --version`; this Mac has 2.1.322) and the Xcode command line tools (`clang`, `codesign`; both are present).
- **Optional:** `brew install qrencode` shows a QR code. Without it you type a 32-letter key into the app instead.
- **Know the machine-wide effects.** Once installed, they apply to every Claude Code session on this Mac, not just MOADIX projects:
  - Every Bash command runs in the sandbox. `docker`, `playwright`, `gh` and `firebase` are excluded from it.
  - Only MOADIX's hooks run (`allowManagedHooksOnly`). Hooks from your other plugins (for example superpowers' SessionStart hook) stop running.
  - No other plugin marketplace can be added. Without `--plugin`, `strictKnownMarketplaces` is `[]`. With `--plugin <owner>/moadix` it allows exactly that repo, which serves as its own marketplace (`.claude-plugin/marketplace.json`), and `moadix@moadix` is force-enabled from it. How this affects plugins you already have installed was **not measured**; check `/plugin` after installing.
  - `sudo`, nested `claude`, scheduled tasks, cross-session messages and `--dangerously-skip-permissions` are refused.
  - In repos without `.sdlc/`, MOADIX records nothing, but the points above still apply.
- **The plugin is optional for now.** The gate runs entirely from managed settings. The plugin only adds `/moadix:request-review`. It is served from this repo's public GitHub marketplace: `managed/install.sh --plugin moaadamer8/moadix`. Install without it now; to add it later, see "Updating".

## 1. Run the installer

```
cd ~/moadix
git log --oneline -1          # note the commit you are installing
managed/install.sh
```

What happens and what it asks for:

| Step | You see | It asks for |
|---|---|---|
| 1/6 Checking this Mac | `Claude Code 2.1.322`, `no MDM profile for Claude Code`, `no other managed settings` | nothing |
| 2/6 Building the checker | `Identifier=com.moadix.checker`, `flags=0x10002(adhoc,runtime)` | nothing |
| 3/6 Installing the gate | `(sudo asks for your macOS password)` | **`Password:`** your macOS login password (nothing shows while you type) |
| 4/6 Creating the approval secret | a QR code (or the key), then `Press Enter once MOADIX shows a 6-digit code in the app...` | **scan, then Enter** (section 2) |
| 5/6 Installing managed settings | the policy path | possibly `Password:` again if sudo has timed out |
| 6/6 Checking MOADIX is in effect | `checker: OK fails=0 paused_for=0`, `installed gate denies a .sdlc/ write`, `installed gate STATUS: integrity OK`, `Claude Code canary: commands run; the sandbox and the hooks both stopped .sdlc/ writes` | nothing. It runs one short `claude -p` session on your account (about 30–60 s) |

It ends with:

```
MOADIX is installed.
  Policy:  /Library/Application Support/ClaudeCode/managed-settings.json
  Gate:    /Library/Application Support/ClaudeCode/moadix
```

If any step prints `MOADIX SETUP FAILED: …`, it stops there. Run `managed/uninstall.sh` (section 5), fix the cause it names, and run the installer again.

## 2. Add MOADIX to Microsoft Authenticator (during step 4/6)

The key is shown **once**. When you press Enter the screen and scrollback are cleared.

1. On the phone, open **Microsoft Authenticator** and tap **+** (Add account).
2. Choose **Other account (Google, Facebook, etc.)**.
3. **With a QR code:** point the camera at the code in Terminal. If it doesn't scan, make the Terminal window bigger, or zoom out with Cmd − so the whole code fits.
   **Without one:** tap **Or enter code manually**. Account name: `MOADIX operator`. Secret key: the 32 letters shown after `Secret key:`, typed exactly (capitals and digits 2–7).
4. Tap **Finish**. A **MOADIX** entry appears with a 6-digit code that changes every 30 seconds.
5. Back in Terminal, press **Enter**.

The key now exists in two places only: your login keychain, readable only by MOADIX's checker, and the app. If you lose the app entry, run uninstall + install to get a new key.

## 3. Check it is in effect

Open a **new** Claude Code session in any folder and run `/status`. The `Setting sources` line must include **`Enterprise managed settings (file)`**. If it names a different managed source, MOADIX's policy is not the one in effect; uninstall and tell me.

## 4. Use it

- **Start a product:** open a Claude Code session in the product's git repo (`git init` it first if needed) and type `INIT <product-id> <code>`. The gate creates `.sdlc/` at the repo root and records ledger line 1. Each product needs its own id. The Terminal tool (`gate/sdlc_init.py`) still works, but INIT replaces it.
- **In a Claude Code session in that repo**, type messages exactly like these, alone in the message:
  - `STATUS`: the agent relays the gate's state, which should start with `INTEGRITY OK`.
  - `APPROVE 0 123456`: the phase, then the current code from the app. You do not need REVIEW first. The gate runs the phase's validators itself, on the current commit, whenever the agent's turn ends (and when the agent calls `/moadix:request-review`). APPROVE is refused, with the validators' findings, unless that result for the **current commit** passed. If it says the result is missing, still running or stale, send APPROVE again a minute later. Uncommitted changes mean the agent has to commit first. The agent relays `APPROVE 0 recorded (ledger seq 2). It rests on validator result sha256:…. Proceed to phase 1.`
  - `REVIEW 0` (optional, read-only): prints the gate's latest validator result for phase 0 and its digest. It never starts a run. For an approved phase it shows the digest of the result that APPROVE relied on.
  - `WAIVE <id> owner=<name> scope=<what it covers> expiry=YYYY-MM-DD reason=<text> <code>`: expiry at most 180 days out. A high- or critical-severity finding in `sdlc/09-security-report.md` cannot be waived. A Claude Security finding (`SF-n`) that its own panel could not confirm blocks phase 9 until the fresh-context `moadix:sf-triager` confirms or rejects it with `path:line` evidence, or until you waive it with a reason; a confirmed critical or high one cannot be waived.
  - `PROCEED-PAST <phase> <reason> <code>`: only when REVIEW shows a definite failure on the current commit (not UNKNOWN, not passing).
  - `ADOPT <code>`: adopts the product settings the agent proposed. The agent cannot write `.sdlc/`, so it writes proposals to `.sdlc-proposals/`: `product.yaml` (only the keys `platform`, `size`, `app_run`, `test_targets`, `park`) and `config/<name>.yaml` for the product config files (`product-tests.yaml`, `product-surface.yaml`, `product-app.yaml`, `concurrency.yaml`, `mobile.yaml`, `traceability-exemptions.yaml`, `hardcoded-state-exemptions.yaml`). `STATUS` lists pending proposals and says whether they are valid. ADOPT validates them, records one ledger line naming each file with its sha256 (and its content when small), copies them into `.sdlc/` and deletes the proposals. Afterwards, an adopted file edited by hand shows as `INTEGRITY FAILURE … differs from what ADOPT recorded`. This replaces editing `.sdlc/` in Terminal.
  - `PARK <code>`: stops the stack, measures the declared counts, records them and tags the repo. It runs only what `.sdlc/product.yaml` declares under `park:` (only `docker` or `podman` commands; see the example in that file). Have the agent propose the `park:` section and `ADOPT` it first.
  - Also: `REOPEN <phase> <reason> <code>`, `UNWAIVE <id> <code>`.
- Each code works once. If one is refused as `already used`, wait for the next one.
- **Wrong codes:** after 3 in a row, approvals pause for 15 minutes. Each further wrong code doubles the pause, up to 24 hours. Anything sent during a pause is refused without being checked, and does not extend it. After the pause, a valid code works and resets the count.

## Updating MOADIX

After pulling a new version, run `managed/install.sh` again, again in Terminal. It detects the existing install, asks for your password once, re-copies the gate, rewrites the policy and re-runs the checks. Your key and your ledgers are kept.

Open sessions keep the old hooks until restarted, so close every Claude Code session first. After an update, the first STATUS in each product re-derives `.sdlc/phase.yaml` from the ledger when the gate's format changed. Any cached validator results are discarded, so send REVIEW again before APPROVE.

If the checker program itself changed in that version, the installer stops and says so. In that case uninstall, then install, and scan a new key. To add the plugin once this repo is on GitHub: `managed/install.sh --plugin <github-owner>/moadix`.

## Running the attack corpus (Terminal)

The corpus (`tests/corpus/run.py`) proves the real checker and the Keychain behave: approvals need a real code, forged ledgers are caught, the cooldown works, and other programs cannot read the secret. It needs the Keychain, so it runs in **Terminal**, not in Claude Code (the sandbox blocks Keychain access there).

It uses only what it builds itself: two throwaway test keychains, two checkers compiled with those keychains baked in, and two fixture products, all under `~/moadix-scratch/corpus`. It never uses your login keychain, the installed checker in `/Library/Application Support/ClaudeCode`, or any real `.sdlc/`. A guard enforces this, and it runs its own self-test before anything else.

```
cd ~/moadix
/usr/bin/python3 tests/corpus/run.py
```

It takes about 4–6 minutes and needs no password and no phone. What you see, in order:

1. **Guard self-test (18 lines).** These lines start with `PASS  [guard] self-test:`.
   - 17 of them hand the guard a real resource and must end in `-> ABORT`: the installed checker, the login keychain, a real product, `security` without a scratch keychain, and so on.
   - The 18th is a control (a scratch test build) and must end in `-> accepted`.
   - If any of the 18 does not pass, the run prints `ABORTED: the isolation guard did not fire …` and stops (exit 3) before building anything.
2. `guard: scratch /Users/<you>/moadix-scratch/corpus; forbidden keychains …/login.keychain-db; installed home /Library/Application Support/ClaudeCode`
3. The two checker builds (`Identifier=com.moadix.checker`, `flags=0x10002(adhoc,runtime)`), then `fixtures: …`.
4. **Preflight**, one line per test keychain:
   `health [preflight A] checker state: OK fails=0 paused_for=0 | get_status=0 (…) unlocked=1 readable=1 writable=1 totp_item=0 (…) | keychain file present`
   and `PASS  [preflight] both test checkers read their own test keychains right after init`.
   If a test checker cannot read its own keychain, the run **stops here** with `STOPPED after the preflight` and the health lines name the cause: a locked keychain (`unlocked=0`), a missing item, or the checker's own error. You get that one diagnosis instead of dozens of failures.
5. The checks themselves, one `PASS`/`FAIL` line each: `[operator]` 43, `[pretool]` 40, `[measure]` 4, `[cooldown]` 9, `[keychain]` 11. After each group comes a `health [after <group> A|B] …` line. The keychain group deliberately swaps and deletes secrets in test keychain B, so B's health lines then show `ERR pin-mismatch`. That is expected.
6. Two hygiene checks: your keychain search list is unchanged, and no gate process read or wrote a real product.
7. The last line: **`128 checks, 128 passed, 0 failed`** (exit 0).

If a check fails, the run prints `-- first failure: keychain health at this moment --` under it once, with both keychains' health. Send me the whole output: `/usr/bin/python3 tests/corpus/run.py 2>&1 | tee ~/moadix-scratch/corpus-run.txt`.

If the guard ever stops the run (`ABORTED by the isolation guard: …`, exit 3), nothing real was touched. The message names what would have been used.

To check only the guard, which needs no Keychain and also runs inside Claude Code: `/usr/bin/python3 tests/corpus/run.py --guard-selftest` (last line `guard self-test only: 18/18`).

## Measuring the verifier prompt replacement (once, after installing increment 4)

Verifiers rely on the gate's hook replacing the prompt the agent writes with the gate's brief. Claude Code applies that replacement (`updatedInput`) inside its own process, so only a live session can show it. The probe agent `moadix:replacement-probe` exists for this and nothing else: it produces no evidence and changes no state.

1. Open a Claude Code session in any folder and send:
   `Launch the agent moadix:replacement-probe with the prompt "Reply with exactly: NOT-REPLACED", then show me its reply verbatim.`
2. Read the reply:
   - `PROBE-REPLACED <16 hex characters>`: the replacement works.
   - `NOT-REPLACED`: the hook's replacement was not applied.
   - The launch is refused with "A settings hook changed this tool call's input…": this Claude Code version does not accept the replacement here.
3. In Terminal: `tail -5 ~/Library/Logs/moadix/probe.log`. Expect a `launch nonce=<hex>` line whose nonce matches the reply, a `tool=Read agent_type=<name> agent_id=present file_path=/dev/null decision=allow` line, and a `tool=SubagentHandback … decision=allow` line (the probe handing its reply back). A `decision=deny` on SubagentHandback means the reply was lost before it reached you. The name shows how Claude Code reports plugin agents (`moadix:replacement-probe` or `replacement-probe`; the gate handles both).

If the result is anything but `PROBE-REPLACED` with a matching nonce, stop and report it. Nothing unsafe follows: every verifier's evidence must quote a receipt that exists only in the gate's replacement prompt, so without the replacement no evidence can pass and APPROVE of phases 6, 7 and 8 refuses.

## Increment 5: the gate-run tools (once, when updating to 0.3.0)

The installer now also fetches ten pinned tools into `/Library/Application Support/ClaudeCode/moadix/tools` (root-owned), checking every download against its sha256 pin. The list is in `gate/config/tools.yaml`. It takes a few minutes and needs the network: github.com and its release CDN, registry.npmjs.org, pypi.org and files.pythonhosted.org, and python-build-standalone for semgrep's Python. It then installs Playwright's Chromium into `~/Library/Caches/ms-playwright`.

New machine-wide effects:
- **Claude Security is force-enabled**: `claude-security@claude-plugins-official`, from Anthropic's official marketplace. That marketplace is now allowed and registered, but **every other plugin it lists is force-disabled**: 316 names, from `managed/official-plugins.txt`. If you use another official plugin today, it stops working. A plugin the marketplace adds later is not on that list until the file is regenerated.
- The sandbox allowlist gains `release-assets.githubusercontent.com`, `api.osv.dev`, `api.deps.dev`, `osv-vulnerabilities.storage.googleapis.com`, `mirror.gcr.io`, `ghcr.io`, `pkg-containers.githubusercontent.com` and `api.github.com`. The sandbox may also write `~/Library/Caches/trivy` and `~/.semgrep`, so the agent's own feedback runs of Trivy and Semgrep work.
- The plugin ships two MCP servers with pinned commands: `playwright` (the live verifier's browser) and `github` (`--read-only`).

Steps, in Terminal:
1. Close every Claude Code session.
2. `cd ~/moadix && git push` (the plugin, its agents and its MCP servers install from GitHub).
3. `managed/install.sh`: password once. Expect `3b/6 Fetching the pinned gate-run tools`, ten `got …` lines and a `tools:` line.
4. **No GitHub token now.** It is needed only once a product reaches phase 11 (see "GitHub token, at phase 11" below).
5. Open Claude Code and run `/plugin marketplace update moadix`, `/reload-plugins`. Check `/plugin` shows `moadix` and `claude-security` enabled, and `/mcp` lists `plugin:moadix:playwright`. `plugin:moadix:github` shows as **failed** until you store the token at phase 11; that is expected.
6. For phase 10a: the live verifier's browser loads the session from `.auth/storage-state.json` in the product (gitignored). Create it once by logging in to the local instance with Playwright's codegen: `npx playwright codegen --save-storage=.auth/storage-state.json http://127.0.0.1:<port>`.
7. Optional: `/usr/bin/python3 managed/fetch_tools.py ~/.cache/moadix-tools` and then `/usr/bin/python3 tests/tools/run.py`. Run this from Terminal to include the loopback-server cases that the Claude Code sandbox skips.

### GitHub token, at phase 11 (not before)

Nothing asks for a GitHub token until a product reaches phase 11 (Release). Then, once, in **Terminal** (not in Claude Code):

```
security add-generic-password -s moadix-github-readonly -a moadix -w
```

It asks for the token twice. Use a **read-only** fine-grained token (Contents, Pull requests, Actions and Code scanning alerts, all read-only). The gate reads it from the Keychain itself, both for its own phase-11 check and to start the plugin's `github` MCP server (`gate/ghmcp.py` passes it to that one process only). **Never** `export` it in the shell you start Claude Code from: that shell's environment reaches the agent's commands. After storing it, run `/mcp` in the session and reconnect `plugin:moadix:github`.

Without the token, phase 11's check-release reports UNKNOWN ("no read-only GitHub token in the login Keychain"), which APPROVE 11 refuses. No other phase needs it.

Product settings the new checks read go in `.sdlc/config/product-tools.yaml` (the agent proposes it in `.sdlc-proposals/config/`, you `ADOPT` it):

```
images: [shop-api:1.4.0]                   # phase 9: trivy image (optional)
env: {files: [.env.production]}            # phase 6b (default .env.production; keys from .env.example)
live: {base_url: http://127.0.0.1:4173}    # phase 10a: loopback only
load:                                      # phase 10c
  base_url: http://127.0.0.1:4173          # loopback only
  scripts: [load/checkout.js]
  invariant_check: [python3, load/invariants.py]   # the product's own SQL invariant check, required
release: {repo: owner/name}                # phase 11 (default: the origin remote)
claude_security: {effort: medium}          # phase 9: low | medium | high
```

## Increment 6: feature cycles and onboarding (once, when updating to 0.4.0)

The checker did not change, so this is an ordinary update: no new QR code, no GitHub token.

1. Close every Claude Code session.
2. `cd ~/moadix && git push`, then `git tag v0.4.0 && git push origin v0.4.0`.
3. `managed/install.sh`: password once. A successful run prints **no** "Permission denied" lines, and its **last line is `MOADIX is updated.`** Anything else is a failure; send me the output.
   - The policy gains a `SessionStart` hook. The gate copy gains `gate/bmad/` (BMad core's scripts, which the gate installs into each product's `_bmad/`).
4. Open Claude Code and run `/plugin marketplace update moadix`, then `/reload-plugins`. `/plugin` shows moadix **0.4.0**; the agent count rises by 2 (`sf-triager`, `baseline-verifier`), and `/moadix:feature` and `/moadix:baseline` exist. `plugin:moadix:github` stays failed until a product reaches phase 11 (see "GitHub token, at phase 11").
5. In any session, the first message should carry **no** `PLUGIN DRIFT` line. If one appears, it names the plugin and the settings file that enabled it; tell me.
6. Optional, in Terminal: `/usr/bin/python3 tests/inc6/run.py` (last line `68 checks, 68 passed, 0 failed`) and `/usr/bin/python3 tests/install/dryrun.py` (now also checks the update's last line).

New commands, typed alone with a code, like the others:

- `FEATURE <feature-id> <code>`: starts a feature cycle on a product whose baseline is approved (released at phase 11, or onboarded at B). One at a time; a second is refused while one is active. Its 16 phases are approved with the usual `APPROVE <phase> <code>`; approving its phase 11 merges its documents into the product's and commits the merge. STATUS shows the active feature and the finished ones.
- `COLLAPSE <phase> <code>`: records the size profile's collapse of the current phase (size S only: phases 1, 6b and 10c), with the reason and the checks that will not run. It is refused for any other phase or size.
- `INIT <product-id> <code>` on a repository that already has code (any tracked file other than documentation) starts **onboarding at phase B**: the agent documents the product as it is, citing the code, and `APPROVE B <code>` approves the baseline. To start a new product the normal way, INIT it before any code is committed.

## Main-branch guard, gh and firebase allowlists, local overlay (0.5.2)

The policy (`managed/managed-settings.json`), the installer and the gate (`gate/mainguard.py`, called from `gate/pretool.py`) changed. The checker did not, so this is an ordinary update. The design and the operator's decisions are in `docs/mainguard.md`.

Machine-wide effects:
- `gh` and `firebase` run **outside** the sandbox (`excludedCommands`), with your own `gh` and `firebase` logins. They are therefore **allowlisted** by the gate:
  - only the listed subcommands run;
  - only when typed directly as the whole command;
  - everything else is refused, including every wrapper, pipe, compound command, substitution, redirection or script around them.
  The lists are in `docs/mainguard.md`.
- **Pushes and deploys** are refused for every repository: any push whose target is main, every PR merge, and Vercel production deploys. That includes `git -C`, aliases, `sh -c`, `eval`, `xargs` and the other forms listed in `docs/mainguard.md`.
- **Coarse deny rules.** Managed `permissions.deny` keeps the coarse text patterns as a first layer: pushes to main, `gh pr merge`, Vercel production, `gh auth token`, `gh api` merges and ref writes, and `firebase firestore:delete`. `*main*` also refuses branch names containing "main" (an accepted limit of that layer).
- **Nothing product-specific is in the public repository.** Production Firebase projects and product network hosts come from your **local overlay**.

### Local overlay

A file on your Mac, outside the repository: `~/.config/moadix/overlay.json`. Set `MOADIX_OVERLAY` to read it from another path.

- **Writable only by you.** The sandbox denies writes there, and the gate denies the agent's Write and Edit tools there.
- **Applied by the installer.** It shows the file and asks before applying it. It renders it into the managed policy and installs a root-owned copy for the guard.
- **Changing it.** Edit the file, then rerun `managed/install.sh`.

```json
{
  "version": 1,
  "protected_firebase_projects": ["<your-production-project-id>"],
  "extra_network_hosts": ["<api.example.com>", "<*.example.com>"]
}
```

- `protected_firebase_projects` lists Firebase project ids that no `firebase` command may target. The guard also resolves `.firebaserc` aliases. Each one also adds a managed deny rule `Bash(firebase*<id>*)`. Without an overlay, every `firebase` command that names a project is refused.
- `extra_network_hosts` lists hosts added to the sandbox network allowlist. Each must be a plain host name: no `https://`, path, port or Markdown link. A leading `*.` is allowed, but not a whole top-level domain such as `*.com`.
- No other key is accepted.

Every allowed host can also be used to send data out of the sandbox (`docs/mainguard.md`, accepted risk). List only what your products need.

Steps:
1. Optional: create `~/.config/moadix/overlay.json` (format above) in Terminal.
2. Close every Claude Code session.
3. In Terminal: `cd ~/moadix && managed/install.sh`. Confirm the overlay when asked. The last line is `MOADIX is updated.`
4. In a new Claude Code session in `~/moadix`, run the live check below, one Bash tool call per line.

| # | Bash call | Expect |
|---|---|---|
| 1 | `bash tests/install/policy_live.sh` | `0 failed`: the overlay's hosts reachable, example.com refused, gh logged in |
| 2 | `cd "$TMPDIR" && rm -rf pp && mkdir pp && cd pp && git init -q --bare remote.git && git init -q -b main work && cd work && git commit -q --allow-empty -m x && git branch feature-x && git remote add origin ../remote.git` | runs (setup) |
| 3 | `git -C "$TMPDIR/pp/work" push origin main` | refused, `MOADIX: main-branch guard` |
| 4 | `cd "$TMPDIR/pp/work" && git push origin feature-x` | **succeeds** (positive control) |
| 5 | `gh pr list --limit 1` | runs (allowlisted) |
| 6 | `gh pr merge 1` | refused |
| 7 | `gh api -X PUT repos/o/r/pulls/1/merge` | refused (only GET) |
| 8 | `gh auth token` | refused |
| 9 | `sh -c 'gh pr list'` | refused (not typed directly) |
| 10 | `vercel --yes --prod` | refused, `MOADIX: main-branch guard` |
| 11 | `firebase deploy --project <your-production-project-id>` | refused (protected) |
| 12 | `firebase projects:list` | runs |

## Updating from 0.4.0 to 0.6.1: the complete procedure

This takes you from the installed 0.4.0 to 0.6.1 (main-branch guard and local overlay from 0.5.2, the contract and tool gates from 0.5.x, the confined executing gates from 0.6.x). The checker program has not changed since 0.4.0, so this is an ordinary update: your Authenticator entry, Keychain secrets and ledgers are kept. Run every command in **Terminal** unless the step says otherwise. Do the steps in order and stop at the first one whose last line differs.

**1. Confirm the version you are about to install.** Docker Desktop: not needed. Claude Code sessions: may stay open.

```
cd ~/moadix && git log --oneline -1
```

Expected last line: `<commit> 0.6.1: …` (the 0.6.1 commit; `cat .claude-plugin/plugin.json` shows `"version": "0.6.1"`).

**2. Create the local overlay.** Docker Desktop: not needed. Claude Code sessions: may stay open. The format is in "Local overlay" above. Put in your production Firebase project id and the hosts your products need. Skip the file entirely if you want no protected project and no extra hosts (then every `firebase` command that names a project is refused).

```
mkdir -p ~/.config/moadix && chmod 700 ~/.config/moadix
nano ~/.config/moadix/overlay.json
/usr/bin/python3 -c 'import json,os; d=json.load(open(os.path.expanduser("~/.config/moadix/overlay.json"))); assert d.get("version") == 1; print("overlay OK:", len(d.get("protected_firebase_projects") or []), "project(s),", len(d.get("extra_network_hosts") or []), "host(s)")'
```

Expected last line: `overlay OK: 1 project(s), N host(s)`. The installer validates the hosts fully at step 6 and refuses a URL, path, port or whole top-level domain.

**3. Run the real-engine suite of the confined gates.** Docker Desktop: **must be running**, with no other container running (stopped stacks are fine and stay untouched). Claude Code sessions: may stay open, but none may start a container during the run (the suite would report the difference and fail). It needs internet once to pull two pinned images and for one proxy check.

```
cd ~/moadix && /usr/bin/python3 tests/confined-engine/run.py
```

Expected last line: `31 checks, 31 passed, 0 failed (<seconds> s)`. If it starts with `REFUSED:` it names what is running; stop that, or wait for it, and run again. It removes only what carries its own label `moadix.run=es…`. It records every other container, volume, network and image before and after, and prints `DIFFERENCE …` lines if anything changed.

**4. Run the attack corpus.** Docker Desktop: not needed. Claude Code sessions: may stay open (it uses its own scratch keychains and checkers under `~/moadix-scratch/corpus`). About 4–6 minutes. See "Running the attack corpus" above for what scrolls past.

```
cd ~/moadix && /usr/bin/python3 tests/corpus/run.py
```

Expected last line: `128 checks, 128 passed, 0 failed`.

**5. Run the install dry run.** Docker Desktop: not needed. Claude Code sessions: may stay open (it installs into a stand-in root and keychain under `~/moadix-scratch/install-dryrun`, never the real ones).

```
cd ~/moadix && /usr/bin/python3 tests/install/dryrun.py
```

Expected last line: `18 checks, 18 passed`.

**6. Reinstall.** Docker Desktop: not needed. Claude Code sessions: **must all be closed** (the policy changes for the whole machine; open sessions would keep the old hooks). It asks for your macOS password once, shows the overlay and asks `Apply this overlay? [y/N]`: answer `y`.

```
cd ~/moadix && managed/install.sh
```

Expected last line: `MOADIX is updated.` If it prints `MOADIX SETUP FAILED: …` instead, nothing further was changed; fix what it names and run it again.

**7. Run the live policy check.** Docker Desktop: not needed. Claude Code sessions: open **one new** session in `~/moadix` after step 6 and type each line there as its own Bash tool call (not in Terminal: it tests the sandbox and the guard).

```
bash tests/install/policy_live.sh
```

Expected last line: `Now run the GitHub CLI checks in docs/INSTALL.md as separate Bash calls (typed directly).`, with `0 failed` on the line before it. Then run checks 2–12 of the table in "Local overlay" above, one Bash call each. Expected: 3, 6, 7, 8, 9, 10 and 11 are refused; 2, 4, 5 and 12 run.

**8. Push and tag.** Docker Desktop: not needed. Claude Code sessions: may stay open; do this in **Terminal** (the guard refuses a push to the main branch from Claude Code).

```
cd ~/moadix && git push origin master
git tag -a v0.6.1 -m "MOADIX 0.6.1"
git push origin v0.6.1
```

Expected last line of the first command: `   451a03a..<0.6.1 commit>  master -> master`. The tag command prints nothing. Expected last line of the third: ` * [new tag]         v0.6.1 -> v0.6.1`.

## 5. Uninstall

```
cd ~/moadix
managed/uninstall.sh
```

It asks for your macOS password once and prints four steps:

```
== 1/4 Managed settings      removed /Library/Application Support/ClaudeCode/managed-settings.json
== 2/4 Gate copy and checker removed /Library/Application Support/ClaudeCode/moadix
                             removed /Library/Application Support/ClaudeCode (install.sh had created it)
== 3/4 Keychain items        deleted moadix-totp / moadix-ledger-key / moadix-state / N moadix-anchor item(s)
== 4/4 Claude Code plugin    plugin moadix@moadix not installed / marketplace moadix not configured
```

- Product repos keep their `.sdlc/`: those are your records.
- Delete the MOADIX entry in Microsoft Authenticator by hand.
- Running the uninstaller twice is harmless.

The uninstaller only removes a `managed-settings.json` that carries MOADIX's pin. It also removes `/Library/Application Support/ClaudeCode` itself, but only when the installer created it and it is now empty.
