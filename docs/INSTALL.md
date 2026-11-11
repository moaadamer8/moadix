# Installing MOADIX on your Mac

This takes about 10 minutes. You need your macOS password once, and your phone with Microsoft Authenticator.

## Before you start

- **Close every Claude Code session.** The policy applies to the whole machine as soon as it is written.
- **Use Terminal, not Claude Code.** The installer refuses to run inside a Claude Code session.
- **Tools:** Claude Code 2.1.295 or newer (`claude --version`; this Mac has 2.1.322) and the Xcode command line tools (`clang`, `codesign`; both are present).
- **Optional:** `brew install qrencode` shows a QR code. Without it you type a 32-letter key into the app instead.
- **Know the machine-wide effects.** Once installed, they apply to every Claude Code session on this Mac, not just MOADIX projects:
  - Every Bash command runs in the sandbox. `docker` and `playwright` are excluded from it.
  - Only MOADIX's hooks run (`allowManagedHooksOnly`). Hooks from your other plugins (for example superpowers' SessionStart hook) stop running.
  - No plugin marketplace can be added (`strictKnownMarketplaces: []`). How this affects plugins you already have installed was **not measured**; check `/plugin` after installing.
  - `sudo`, nested `claude`, scheduled tasks, cross-session messages and `--dangerously-skip-permissions` are refused.
  - In repos without `.sdlc/`, MOADIX records nothing, but the points above still apply.
- **The plugin is optional for now.** The gate runs entirely from managed settings. The plugin only adds `/moadix:request-review`, and it needs this repo published on GitHub. Install without it now; to add it later, see "Updating".

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
  - `WAIVE <id> owner=<name> scope=<what it covers> expiry=YYYY-MM-DD reason=<text> <code>`: expiry at most 180 days out. A high- or critical-severity finding in `sdlc/09-security-report.md` cannot be waived.
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
