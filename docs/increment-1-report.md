# Increment 1: trust core, report

2026-11-11 · built per DESIGN.md sections 2–4 and Amendment 1. Nothing was installed system-wide: no managed settings, no sudo, no login-keychain items. Every Keychain experiment used throwaway keychains under `~/moadix-scratch`, and the user keychain search list was checked before and after.

## What was built

| Piece | Where | Notes |
|---|---|---|
| Plugin skeleton | `.claude-plugin/plugin.json`, `hooks/hooks.json`, `commands/request-review.md` | Both hooks have `onFailure: "block"` and an explicit timeout. Hooks run the **root-owned copy** of the gate with `/usr/bin/python3` (SIP-protected), not the plugin directory. |
| Checker | `checker/moadix-checker.c`, `checker/build.sh` | C, ad-hoc signed, hardened runtime. The only reader of the secrets. Commands: `init`, `record` (verify code → sign line → move anchor, one call), `burn`, `verify`, `anchor`, `state`, `unlock` (macOS password dialog + code). There is no standalone "sign". |
| Gate core | `gate/` (stdlib Python 3.9) | `opcmd.py` operator commands; `pretool.py` invariants 1/3/4/6; `state.py` `.sdlc/` + ledger; `pathmap.py` v1 path map re-rooted; `bashcls.py` interim Bash classifier; `sdlc_init.py` operator tool. |
| `.sdlc/` state | created by `sdlc_init.py` | `product.yaml`, `phase.yaml` (derived, compared byte for byte), `ledger.jsonl` (hash-chained, HMAC per line), `evidence/`, `knowledge.md`, `untested.yaml`. Anchor = last seq + hash, **MAC'd, in the Keychain**. |
| Managed settings | `managed/managed-settings.json` | Section 2 + Amendment 1 §5. Key names checked against the docs (see below). |
| Installer | `managed/install.sh` | Written, **not run**. Steps: preconditions (version, no MDM, no existing policy), build + sign, root-owned install, `init` with QR shown once, policy with pin, then a canary `.sdlc/` write from a sandboxed command that must fail. |
| Attack corpus | `tests/corpus/run.py` | 106 checks on fixtures (two test keychains, two fixture homes, two throwaway repos). Output: `docs/evidence/increment-1-corpus.txt`. |

## Corpus results: 106 checks, 106 passed

Run: `/usr/bin/python3 tests/corpus/run.py`. Full output: `docs/evidence/increment-1-corpus.txt`. Representative lines:

| Attack | Result (real output) |
|---|---|
| Agent-started turn `APPROVE 1 123456` | `APPROVE NOT recorded: the code is wrong. Nothing changed.` |
| Agent runs the checker / feeds the hook via Bash | `MOADIX: the agent has no command that changes gate state; operator commands are typed in chat (invariant 3)` |
| Task notification containing `APPROVE 1 <valid code>` | `ledger lines 1 -> 1`; exact reuse afterwards: `that code was already used` (burned) |
| Pasted report containing `APPROVE 1 <valid code>` | ledger unchanged; exact reuse: `already used` |
| File with APPROVE lines; Write/Edit/`>>`/`cp`/`python -c`/`git checkout -- .sdlc`/`rm -rf .sdlc` | `.sdlc/ledger.jsonl is MOADIX gate state; only the gate's hooks write it`, etc. |
| Forged line, correct chain, fake HMAC | `INTEGRITY FAILURE: line 5: signature invalid (not written by the checker); anchor mismatch` → real APPROVE then refused, agent writes refused |
| Replayed genuine line / truncation / `phase.yaml` edit | `chain broken` / `anchor mismatch: Keychain anchor says seq 4, ledger has 3 lines` / `phase.yaml differs … (drift)` |
| Expired code (90 s) / reused code | `the code is wrong` / `that code was already used` |
| 3 wrong codes, then a valid one | `that was the 3rd wrong code, so approvals are now LOCKED` → `approvals are LOCKED after 3 wrong codes`; direct checker call: `ERR locked`; `burn` cannot reset (`fails=3 locked=1`) |
| Checker without a code / unknown `sign` / re-`init` | `ERR bad-arguments` (rc 30) / `ERR unknown-command` / `ERR already-initialised` |
| Foreign process / impostor with the checker's identifier reads the secret | `status=-25293 … secret_bytes_returned=0` |
| `DYLD_INSERT_LIBRARIES` into the checker | not loaded (`checker stderr=''`; control: `INJECTED`) |
| State replaced by any process (reset lockout) | `delete rc=0, re-add rc=0 (Keychain allowed both); checker: ERR item-tampered` |
| TOTP secret swapped / all secrets re-initialised by the attacker | `ERR pin-mismatch`; STATUS: `INTEGRITY FAILURE: signature check unavailable: ERR pin-mismatch` |
| Line signed out of band (real code, not appended) | `anchor mismatch: Keychain anchor says seq 2, ledger has 1 lines` |
| Invariants 4/3/6, 40 tool calls incl. 10 ordinary ones that must pass | all as expected; `git stash list`, `git checkout -b`, `npm test 2>&1`, `docker compose up -d` are not denied |

Positive controls (APPROVE, WAIVE, REOPEN, STATUS with real codes) all recorded, so each refusal above is the gate's decision and not a broken path.

**Passes with a weaker reason than the label:** the one-command `ln -s .sdlc s && echo x > s/ledger.jsonl` is denied only because `s` is unmapped. The hook checks before the symlink exists, so in a phase where the link's path is writable this one-liner gets past the hook. A symlink made in an *earlier* call is resolved and caught. The sandbox `denyWrite` is the backstop; increment 2's classifier must handle it.

## The two open Keychain measurements

**1. Another process asking for the secret gets a prompt, not the secret: YES, for reads.**
- `security find-generic-password -s moadix-totp -a operator -w <kc>` hung waiting on a Keychain dialog until an 8 s alarm (`rc=142 after 8s`), and printed no secret. Without `-w` it prints only attributes.
- Programmatic read with interaction off, from a foreign binary and from an impostor signed `--identifier com.moadix.checker`: `status=-25293 … secret_bytes_returned=0`.
- The ACL pins the checker's cdhash (`requirement: cdhash H"…"`). A copy of the checker with an appended byte outside the signed code keeps the same cdhash and can read; it is the same code.
- **But writes and deletes are not protected** (see "Design corrections", item 1).

**2. The agent's turn after an approval cannot see the secret: YES.**
- After `APPROVE 1 <code>`, the hook's output (the agent's added context) contains no form of the secret (base32, hex, raw).
- No file in the fixture repo contains it (`.sdlc/`, ledger, `phase.yaml`, git objects), and neither does the environment.
- The only code the agent sees, the one in the operator's message, is already spent (`already used`).
- A separate check showed the agent's processes cannot read it from the Keychain (measurement 1).

## Design corrections (things that turned out wrong)

1. **"Readable only by MOADIX's signed checker" is not enough: the file keychain does not stop writes or deletes.**
   - Measured: any same-user process can `security delete-generic-password` and `security add-generic-password -U` on the checker's items, with no prompt, even after the ACL's `encrypt`/`delete` entries were set to the checker's cdhash only (`dump-keychain -a` shows `delete encrypt … requirement: cdhash H"193c…"`; delete still `rc=0`).
   - In the first build an attacker swapped in its own TOTP secret and recorded `APPROVE 9` with its own code.
   - Fix built: both secrets are **pinned** by a hash in the root-owned managed-settings file (`env.MOADIX_PIN`). State and anchor values carry an HMAC under the pinned key. Swaps fail closed (`pin-mismatch`, `item-tampered`), and deletions are detected (`anchor mismatch`) or fail closed.
   - The remaining effect of Keychain tampering is denial of service. Docker containers should not be able to reach the host Keychain, because they run in a Linux VM; this was not measured. Host processes outside the sandbox (Playwright under `excludedCommands`) can reach it.
2. **The anchor directory (invariant 8) is writable by Docker** once Docker runs outside the sandbox (Amendment 1 §4). The anchor moved into the Keychain, MAC'd and written only by the checker.
3. **Plugin code is writable by Docker too**: the plugin cache, `hooks.json` and the gate's Python.
   - Hooks therefore run a root-owned copy in `/Library/Application Support/ClaudeCode/moadix` via `/usr/bin/python3`.
   - The gate finds the checker relative to its own install path, never from an env var, because project settings can set `env` and a container can write them.
   - **Residual:** the hook *definitions* still live in the plugin's `hooks.json`, which a container could delete for the next session. Proposal: put the hook definitions in managed settings.
4. **"3 wrong codes lock approvals until a code is entered at the Mac"**: nothing a same-user process does is "at the Mac". `unlock` therefore requires a macOS authorization dialog (the operator's password) plus a code; Keychain "presence" items can be replaced (item 1).
   - The unlock positive path is **not tested**: it needs a human at the dialog.
   - Any process can deliberately type wrong codes and lock approvals (denial of service, fails safe).
5. **The approval code is no longer bound to the action or the source commit** (the original design bound them; TOTP cannot).
   - The hook spends ("burns") every 6-digit token in any message that does not become a recorded action, including refused and malformed commands, so a code that reaches the agent's context is already spent.
   - Whoever holds a live code holds operator authority. A line signed out of band is caught by STATUS (anchor mismatch).
6. **"Never blocks" vs "fail closed"**: both hold, in different layers.
   - The script never emits a block; any error inside it becomes added context ("Nothing was recorded") and the message's codes are burned.
   - `onFailure: "block"` remains for crashes or timeouts of the interpreter itself. On the phone such a block is silent, which is accepted, because letting an unburned code through to the agent would be worse.
7. **Validators on APPROVE, the high-severity unwaivable rule, and PARK's stop-and-measure** are not in this increment. APPROVE checks only that the phase is current, and PARK only records. That belongs to increment 2.
8. **Managed-settings keys** (verified against the docs):
   - `disableBypassPermissionsMode` lives under `permissions`, not at the top level.
   - `crossSessionInbound: "refuse"`, `disableSideloadFlags`, `CLAUDE_CODE_DISABLE_CRON` and `CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH` exist.
   - Whether the settings `env` block reaches hook processes is **not documented**, which is why nothing depends on it.
   - Sandbox paths in managed settings: only `/` and `~/` forms are documented. `~/**/.sdlc` relies on macOS glob support and must be proven by the installer's canary.
9. **Sandbox `denyWrite` for every product's `.sdlc/`** is the backstop for classifier gaps. It is unmeasured until the installer runs, because no managed policy is installed.
10. **Typed commands in other repos**: in repos without `.sdlc/` commands are ignored, but codes are still burned (machine-wide checker).

## Not done / still open

- `install.sh` has never run; the policy-in-effect check and the canary are untested.
- The unlock positive path (dialog) is untested.
- The Bash classifier is interim. Gaps: one-line symlink tricks, compose files, and opaque scripts that don't name protected paths. Increment 2 rewrites it.
- `/moadix:init` is an operator terminal tool (`sdlc_init.py`), not a typed command.
- Skill/MCP manifest enforcement is increment 3.

## Rulings applied (2026-11-11, later the same day)

These supersede the lockout, `unlock` and `hooks.json` statements above.

- **Cooldown instead of lockout.** After 3 wrong codes, approvals pause for 15 minutes, doubling with each further wrong code, up to 24 hours. Attempts during a pause are refused unevaluated, never extend it, and the codes in them are burned. A valid code after the pause resets the count. The state is signed. `unlock` and the password dialog are removed. The corpus `[cooldown]` group checks this, including a flood of 580 attempts from the hook and from direct checker calls.
- **Hooks moved into managed settings** (`managed/managed-settings.json`, rendered by `managed/render_policy.py`), pointing at the root-owned gate copy. The plugin ships no `hooks.json`. Updates go through `install.sh`, which needs the operator's password once.
- **Fix found while applying the cooldown:** a valid code refused by the checker (for example during a pause) was not burned, so it stayed live for up to 90 s while visible to the agent. Every refusal now burns every code in the message.
- **`managed/uninstall.sh`** removes the policy (only if it carries MOADIX's pin), the gate copy, the managed directory (if install created it and it is empty), every MOADIX Keychain item, and in real mode the plugin and marketplace entries.
- **Install and uninstall were dry-run end to end** (`tests/install/dryrun.py`, 15/15; output in `docs/evidence/increment-1-install-dryrun.txt`). The dry run used a stand-in directory and a stand-in keychain, with no sudo.
- **Real-mode canary strengthened:** a positive control must succeed, and a script the hook cannot see into must be stopped by the sandbox. Not run; it needs the real policy.
- **Measured in passing:** creating a keychain file named `login.keychain-db` (in any directory) added it to the user's keychain search list; deleting it removed the entry. The stand-in keychain is now named `standin.keychain-db`, which does not touch the list.
