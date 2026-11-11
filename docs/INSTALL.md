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

- **Start a product** (in Terminal): `/usr/bin/python3 "/Library/Application Support/ClaudeCode/moadix/gate/sdlc_init.py" ~/path/to/repo <product-id>`
- **In a Claude Code session in that repo**, type messages exactly like these, alone in the message:
  - `STATUS`: the agent relays the gate's state, which should start with `INTEGRITY OK`.
  - `REVIEW 0`: the gate's summary of phase 0.
  - `APPROVE 0 123456`: the phase, then the current code from the app. The agent relays `APPROVE 0 recorded (ledger seq 1). Proceed to phase 1.`
  - Also: `REOPEN <phase> <reason> <code>`, `WAIVE <id> owner=<x> expiry=YYYY-MM-DD reason=<text> <code>`, `UNWAIVE <id> <code>`, `PROCEED-PAST <phase> <reason> <code>`, `PARK <code>`.
- Each code works once. If one is refused as `already used`, wait for the next one.
- **Wrong codes:** after 3 in a row, approvals pause for 15 minutes. Each further wrong code doubles the pause, up to 24 hours. Anything sent during a pause is refused without being checked, and does not extend it. After the pause, a valid code works and resets the count.

## Updating MOADIX

After pulling a new version, run `managed/install.sh` again, again in Terminal. It detects the existing install, asks for your password once, re-copies the gate, rewrites the policy and re-runs the checks. Your key and your ledgers are kept.

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
