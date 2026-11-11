# MOADIX

MOADIX adds SDLC gates to [Claude Code](https://claude.com/claude-code). A product moves through numbered phases (idea, research, PRD, architecture, threat model, UX, build, test, … retrospective). **The agent can never mark its own work done.** Only you, the operator, approve a phase. You do it by typing a command such as `APPROVE 2 482913` with a code from your authenticator app.

- **The gate runs from managed settings.** Its hooks are root-owned and machine-wide, so neither the agent nor user or project settings can turn it off.
- **Approvals need a TOTP code.** The secret sits in the macOS Keychain and only MOADIX's signed checker binary can read it, so the agent can't produce a valid code.
- **Every action goes into a signed ledger** in the product repo's `.sdlc/`. Each line is HMAC-signed with a second Keychain-locked key, and a forged line fails verification on `STATUS`.
- **The gate runs each phase's validators itself.** `APPROVE` is refused unless they passed on the current commit.
- **Each phase allows only its own skills and MCP servers.** Vendored skills have had every "approve / mark done / move on / commit / ship" step removed (see `skills/VENDORING.md`).

The design is in [`docs/DESIGN.md`](docs/DESIGN.md), and progress reports are in `docs/increment-*-report.md`.

> [!WARNING]
> **Work in progress.** MOADIX is being built in increments (3 done so far). Formats, commands and the installer can change between versions, and some phases' validators and tools are not wired yet. Don't rely on it for anything you can't afford to redo.

> [!CAUTION]
> **Installing MOADIX locks down Claude Code for the whole machine,** not just MOADIX projects. The policy goes into `/Library/Application Support/ClaudeCode/managed-settings.json` and applies to **every** Claude Code session for every user on the machine:
> - Every Bash command runs in the sandbox, with a fixed network allowlist. Unsandboxed commands are refused.
> - **Only managed hooks run** (`allowManagedHooksOnly`). Hooks from your other plugins stop working.
> - **Only managed permission rules apply** (`allowManagedPermissionRulesOnly`).
> - **No scheduled tasks**: cron, scheduled wake-ups and remote triggers are denied. Cross-session messages, nested `claude`, `sudo` and `--dangerously-skip-permissions` are refused too.
> - No other plugin marketplace can be added. Only this repo is allowed, and only if you installed with `--plugin`.
>
> **If you use Claude Code for other work, install MOADIX in a virtual machine** (for example a macOS VM in UTM or Parallels), not on your everyday machine. `managed/uninstall.sh` removes all of it.

## Requirements

- **macOS.** The installer uses the macOS Keychain, `codesign` and the Xcode command-line tools (`clang`). **Linux** is a design target (see `docs/DESIGN.md`), but the installer doesn't support it yet.
- **Claude Code ≥ 2.1.295** (`claude --version`).
- **An authenticator app** for 6-digit TOTP codes, for example Microsoft Authenticator, Google Authenticator or 1Password.
- No MDM profile or other managed-settings file for Claude Code. The installer checks this and stops if it finds one, because either would take precedence over MOADIX's policy.
- `/usr/bin/python3` (ships with the Xcode command-line tools).
- Optional: `brew install qrencode` to get a scannable QR code during install. Without it you type the key into the app by hand.

## Install

Close every Claude Code session first. Then, in **Terminal** (the installer refuses to run inside Claude Code):

```sh
git clone https://github.com/moaadamer8/moadix.git ~/moadix
cd ~/moadix
managed/install.sh --plugin moaadamer8/moadix
```

It asks for your macOS password once (sudo). It shows the authenticator key **once**, as a QR code or as text, and waits until you have added it to your app. At the end it runs a live canary to confirm the policy is in effect. Leaving out `--plugin` installs the gate without the plugin. The gate works either way. The plugin only adds the `/moadix:request-review` command.

With `--plugin`, the policy allows exactly one marketplace, this repo (`.claude-plugin/marketplace.json`), and force-enables `moadix@moadix` from it.

Then open a new Claude Code session and run `/status`. `Setting sources` must include `Enterprise managed settings (file)`.

**Updating:** `git pull`, then run `managed/install.sh` again. Your key and ledgers are kept. If the checker binary itself changed, the installer tells you to uninstall and reinstall (new key).

Step-by-step details and the expected output are in [`docs/INSTALL.md`](docs/INSTALL.md).

## Uninstall

In Terminal:

```sh
cd ~/moadix
managed/uninstall.sh
```

This removes the managed policy (only if it is MOADIX's), the root-owned gate copy and checker, MOADIX's Keychain items, and the plugin and marketplace. Product repos keep their `.sdlc/` folders, which hold your records. Delete the MOADIX entry from your authenticator app by hand.

## Operator commands

Open Claude Code in a product's git repo and type these **as the whole message**. `<code>` is the current 6-digit code from your app. Each code works once.

| Command | What it does |
|---|---|
| `INIT <product-id> <code>` | Starts a product: creates `.sdlc/` at the repo root and the first ledger line. |
| `STATUS` | Shows the gate's state. It starts with `INTEGRITY OK` when the ledger and state verify. |
| `REVIEW <phase>` | Read-only. Shows the latest validator result for a phase and its digest. |
| `APPROVE <phase> <code>` | Approves a phase. Refused, with the findings, unless the phase's validators passed on the current commit. |
| `REOPEN <phase> <reason> <code>` | Reopens an approved (frozen) phase. |
| `WAIVE <id> owner=<name> scope=<what> expiry=YYYY-MM-DD reason=<text> <code>` | Waives a finding for at most 180 days. High or critical security findings can't be waived. |
| `UNWAIVE <id> <code>` | Withdraws a waiver. |
| `PROCEED-PAST <phase> <reason> <code>` | Moves past a phase whose validators definitely failed on the current commit. |
| `ADOPT <code>` | Adopts the product settings the agent proposed in `.sdlc-proposals/`. |
| `PARK <code>` | Stops the product's declared stack, records the counts and tags the repo. |

The agent can call `/moadix:request-review <phase>` (plugin) to say a phase is ready. That never changes gate state.

**Wrong codes:** after 3 in a row, approvals pause for 15 minutes. Each further wrong code doubles the pause, up to 24 hours.

## Tests

```sh
/usr/bin/python3 tests/gate2/run.py        # gate suite (fixtures only; runs inside Claude Code)
/usr/bin/python3 tests/verifiers/run.py    # verifiers: brief replacement, restrictions, evidence, probe
/usr/bin/python3 tests/release/run.py      # shipped plugin folders changed => plugin.json version bumped
/usr/bin/python3 tests/skills/run.py       # phase manifest, vendored sources, self-approval grep
/usr/bin/python3 tests/install/render.py   # policy rendering: marketplace allowlist
/usr/bin/python3 tests/install/dryrun.py   # install/uninstall dry run (Terminal; test keychain)
/usr/bin/python3 tests/corpus/run.py       # attack corpus (Terminal; scratch keychains only)
```

## Licence

MOADIX's own code is released under the [MIT licence](LICENSE). The skills under `skills/` and the template under `templates/` are third-party components under their own licences (MIT or Apache-2.0), which ship next to them. See [`THIRD-PARTY.md`](THIRD-PARTY.md) for each component's source, commit, licence and attribution.

MOADIX isn't affiliated with or endorsed by Anthropic. "Claude" and "Claude Code" are trademarks of Anthropic PBC.
