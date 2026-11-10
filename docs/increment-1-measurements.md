# Increment 1, stage A: measurements

2026-11-10 · measured on Moad's Mac (Darwin 25.5.0, arm64), Claude Code 2.1.322, Docker 28.5.2, Node 25.2.0.
No gate code. All experiments were in `~/moadix-scratch/`. Raw outputs: `~/moadix-scratch/run{1..7}.txt`, licence copies: `~/moadix-scratch/licences/`.

## Summary

| # | Question | Verdict |
|---|---|---|
| 1 | Version ≥ 2.1.295 | **Yes.** 2.1.322; `onFailure: "block"` was added in 2.1.295 (docs + changelog). |
| 2 | MDM / server-managed policy present | **None found** (no MDM enrollment, no profiles, no `com.anthropic.claudecode` domain, no managed-settings file, no cached remote settings). `/status` still to be read by you. |
| 3 | Sandbox vs. product work | **git works; Node works only with npm cache + registry allowlisted; Docker works only if the Docker socket is opened; Playwright's Chromium crashes under the macOS sandbox.** |
| 4 | Docker escape | **Escapes.** With the socket open, `docker run -v` and compose both wrote into the denied canary. With the socket closed, Docker does not work at all. |
| 5 | UserPromptSubmit display | Hook built at `~/moadix-scratch/ups-test`; human test pending. Docs: block reason "appears in the chat as a warning line"; whether it reaches Claude's context is **not stated**. Mobile/Remote Control display: **not stated**. |
| 6 | Licences | **All 14 redistributable** (MIT or Apache-2.0). Caveats: BMAD trademark, Impeccable NOTICE, pr-review-toolkit must come from `claude-plugins-official`, awesome-design-md brand names. |
| 7 | Managed `enabledPlugins` from private Git marketplace | **Not stated in the docs.** The pieces exist (force-install at next session start; private repos clone with the user's stored git credentials); the combination is unverified. |

---

## 1. Version

```
$ claude --version
2.1.322 (Claude Code)
```

2.1.322 ≥ 2.1.295. Docs: <https://code.claude.com/docs/en/hooks.md#block-the-action-when-a-hook-fails> — "set `"onFailure": "block"` on a `command` or `http` hook. Requires Claude Code v2.1.295 or later." CHANGELOG 2.1.295: "Added `onFailure: "block"` for command and HTTP hooks". The managed key is exactly `requiredMinimumVersion` (v2.1.163+, startup check only; <https://code.claude.com/docs/en/settings-reference.md#requiredminimumversion>).

## 2. Policy sources

```
$ ls -la "/Library/Managed Preferences/"
ls: /Library/Managed Preferences/: No such file or directory
$ defaults read com.anthropic.claudecode
Domain com.anthropic.claudecode does not exist
$ ls -la "/Library/Application Support/ClaudeCode/"
ls: /Library/Application Support/ClaudeCode/: No such file or directory
$ profiles status -type enrollment
Enrolled via DEP: No
MDM enrollment: No
$ profiles list
There are no configuration profiles installed for user 'moad'
$ ls ~/.claude | grep -i -E 'remote|policy|managed'
(no output)
$ env | grep -i -E 'CLAUDE|ANTHROPIC'   # no policy-related variables
```

**Not measured:** the `/status` "Setting sources" line (interactive only). Run `/status` in any session. It should not list `Enterprise managed settings`. Docs (<https://code.claude.com/docs/en/managed-settings.md#read-the-source-in-/status>): "When a managed source is in effect, the line lists `Enterprise managed settings` with the source Claude Code selected in parentheses."

Precedence (same page, "How Claude Code combines managed sources"): remote/server-managed > MDM/OS policy > managed-settings file (+ `managed-settings.d/*.json` merged alphabetically). Default is **`"first-wins"`**: "uses the highest-ranked source that delivers at least one policy key and ignores the rest rather than merging them". `managedSourcesBehavior: "merge"` (v2.1.242+) exists but must be set in the highest-ranked source. The design's statement holds.

## 3. Sandbox vs. product work

Throwaway project `~/moadix-scratch/sbx`. Each run was a headless session in that project, so Claude Code's real sandbox applied:

```
claude -p "Run exactly this one Bash command ... ./probe.sh ..." --setting-sources project --model haiku --allowedTools Bash
```

`probe.sh` runs each step and prints its exit code. The steps were `npm install`, `npm test` (node:test), a git commit, `docker ps`, `docker compose up -d` of an alpine service, Playwright headless, and the item-4 escape. `--setting-sources project` isolates the run from user settings. `alpine:3.20` was pulled beforehand, outside the sandbox.

**Run 1: strict sandbox.** `enabled`, `allowUnsandboxedCommands: false`, `autoAllowBashIfSandboxed`, `filesystem.denyWrite: ["~/moadix-scratch/canary"]`, nothing else.

| Step | Result | Exact error |
|---|---|---|
| canary write (`touch`) | denied ✅ | `touch: .../canary/probe-direct: Operation not permitted` |
| npm install | **fails** | `npm error 403 403 user denied - GET https://registry.npmjs.org/left-pad` + `<sandbox_violations> deny network-outbound registry.npmjs.org:443 (user denied)` |
| npm test | fails (no deps) | `MODULE_NOT_FOUND` |
| git commit | **works** | `25b75a1 probe` |
| docker ps | **fails** | `dial unix /Users/moad/.docker/run/docker.sock: connect: operation not permitted` |
| compose up | **fails** | same socket error |
| Playwright | fails (no deps) | `MODULE_NOT_FOUND` |

**Run 2: Docker socket opened and the npm registry allowlisted.** Settings added: `network.allowUnixSockets: [~/.docker/run/docker.sock, /var/run/docker.sock]`, `network.allowedDomains: [registry.npmjs.org, …]`.

| Step | Result | Exact error |
|---|---|---|
| npm install | **fails** | `npm error errno EPERM ... Your cache folder contains root-owned files ... run: sudo chown -R 503:20 "/Users/moad/.npm"` |
| docker ps | works | — |
| compose up | works | `web-1  \| up` |

The npm message is **misleading**. `find ~/.npm -user root | wc -l` → `0`. The debug log shows the real cause: `EPERM: operation not permitted, open '/Users/moad/.npm/_cacache/tmp/e2a1c84b'`. The sandbox denies writes outside the project. An agent that follows npm's advice would try `sudo chown`.

**Run 3: added `filesystem.allowWrite: ["~/.npm"]`.**

| Step | Result |
|---|---|
| npm install | works: `added 3 packages in 1s` |
| npm test | works: `ℹ pass 1 ℹ fail 0` |
| git commit | works |
| docker ps / compose up | work |
| Playwright | fails: `Executable doesn't exist at .../chromium_headless_shell-1254/...` (the installed 1.65.0 needs a build that isn't cached) |

**Runs 5–7: Playwright, with the browser and npm caches inside scratch.** `PLAYWRIGHT_BROWSERS_PATH` and `npm_config_cache` point under `~/moadix-scratch`, with matching `allowWrite` entries.

- `npx playwright install chromium-headless-shell` first failed with `<sandbox_violations> deny network-outbound storage.googleapis.com:443`. Once that host was allowlisted, Chrome downloaded, but FFmpeg still failed (`Failed to download FFmpeg (playwright ffmpeg v1013)`). Headless tests don't need FFmpeg.
- **Headless launch crashes under the sandbox:**
  ```
  [pid=7642][err] [...:FATAL:base/apple/mach_port_rendezvous_mac.cc:159] Check failed: kr == KERN_SUCCESS.
  bootstrap_check_in org.chromium.Chromium.MachPortRendezvousServer.7642: Permission denied (1100)
  <process did exit: exitCode=null, signal=SIGTRAP>
  ```
- Control: the same launch outside the sandbox prints `LAUNCH_OK`. The macOS sandbox profile blocks Chromium's Mach service registration. This is not a network or file problem.
- Docs: MCP servers and hooks run outside the sandbox ("The sandbox covers shell commands only. Claude's file tools, MCP servers, and hooks run outside it." <https://code.claude.com/docs/en/sandboxing.md>). So **Playwright MCP** (10a) should work, but **Playwright test runs via Bash** (phase 8 e2e) do not. The MCP case was not measured.

**What product work needs, at minimum:** a `network.allowedDomains` list (registry.npmjs.org, storage.googleapis.com, cdn.playwright.dev, …), `allowWrite` for package-manager caches, the Docker socket in `allowUnixSockets`, and a way to run Chromium. With `allowUnsandboxedCommands: false`, the only route for Chromium is `excludedCommands`. Docs on Docker (<https://code.claude.com/docs/en/sandboxing.md#docker-commands-fail>): "`docker` is incompatible with the sandbox. Take the `docker` commands you need out of the sandbox with an `excludedCommands` pattern such as `docker compose *`." … "An excluded command runs with your full access." The `allowUnixSockets` doc entry also says: "allowing `/var/run/docker.sock`, for example, lets a sandboxed command control the Docker daemon."

## 4. Docker escape

Same sandbox; canary `~/moadix-scratch/canary` is in `denyWrite`.

```
=== 0 sandbox-canary-direct :: touch ~/moadix-scratch/canary/probe-direct
touch: /Users/moad/moadix-scratch/canary/probe-direct: Operation not permitted
--- rc=1
=== 6a docker-escape-run :: docker run --rm -v ~/moadix-scratch/canary:/x alpine:3.20 touch /x/probe-run
--- rc=0
=== 6b docker-escape-compose :: docker compose -p sbxescape -f compose-escape.yaml up --abort-on-container-exit; ... down
 Container sbxescape-probe-1  Stopped ...
--- rc=0
=== canary contents
-rw-r--r--  1 moad  staff    0 Nov 10 23:26 probe-compose
-rw-r--r--  1 moad  staff    0 Nov 10 23:26 probe-run
```

(`compose-escape.yaml`: `volumes: ["${HOME}/moadix-scratch/canary:/x"]`, `command: ["touch","/x/probe-compose"]`.) Reproduced in runs 2 and 3. In run 1 (socket closed) both failed with `connect: operation not permitted`, because Docker itself was unusable.

**Verdict:** Docker is binary under the sandbox. Either the agent has no Docker, or any sandboxed process can write anywhere the user can. That includes `.sdlc/`, because mounting the product repo also mounts `.sdlc/`. The daemon runs outside the sandbox, and the docs do not state any restriction on processes the daemon starts. The escape also isn't limited to `docker` command lines: anything sandboxed that can reach the socket can do it, such as a compose file, a test script, a Node Docker API client, or `curl --unix-socket`.

## 5. UserPromptSubmit display (human test pending)

Project: `~/moadix-scratch/ups-test`. `.claude/settings.json`:

```json
{ "hooks": { "UserPromptSubmit": [ { "hooks": [ { "type": "command",
  "command": "python3 \"$CLAUDE_PROJECT_DIR/.claude/hooks/ping_gate.py\"", "timeout": 10 } ] } ] } }
```

`ping_gate.py` reads the hook JSON and prints `{"decision":"block","reason":"TEST CODE 4711"}` only when `prompt == "PING"`; otherwise it prints nothing and exits 0. Every invocation appends `{ts, input keys, prompt}` to `~/moadix-scratch/ups-test/hook-log.jsonl`, so you can check whether it fired even when nothing shows. Script unit check, which is not the human test:

```
[PING]     -> {"decision": "block", "reason": "TEST CODE 4711"} (rc=0)
[ping]     ->  (rc=0)
[PING ]    ->  (rc=0)
[say PING] ->  (rc=0)
[hello]    ->  (rc=0)
```

**Docs:**
- Exit-code table: "`UserPromptSubmit` | Yes | Blocks the prompt, so it never reaches Claude." <https://code.claude.com/docs/en/hooks.md#exit-code-2-behavior-per-event>
- Decision control: "the turn ends and the `reason` appears in the chat as a warning line." <https://code.claude.com/docs/en/hooks.md>
- **Whether the reason is added to Claude's context: not stated.** The docs say the prompt never reaches Claude; they say nothing either way about the reason. Step 6 of the terminal test checks it.
- "By default the block message shown to the user ends with `Original prompt:` followed by the submitted text, and Claude Code writes that message to the session's transcript file on disk." `hookSpecificOutput.suppressOriginalPrompt: true` omits the prompt. <https://code.claude.com/docs/en/hooks.md#what-a-blocked-prompt-leaves-behind>
- Remote Control and the mobile app: **not stated** in the hooks or Remote Control docs (<https://code.claude.com/docs/en/remote-control.md>). The only related mention is CHANGELOG 2.1.321: "Fixed remote sessions giving no reply after a restart when a `UserPromptSubmit` hook blocked a replayed permission answer; these hooks no longer run on that replay."

**Steps: terminal**
1. `cd ~/moadix-scratch/ups-test && claude`. Accept the trust dialog; project hooks only run in a trusted folder.
2. Run `/hooks` and confirm a `UserPromptSubmit` entry from project settings.
3. Type `hello`. Expected: a normal reply. `hook-log.jsonl` gains a line with `"prompt": "hello"`.
4. Type `PING`. Expected: no reply from Claude, the turn ends, and a warning line containing `TEST CODE 4711`, probably followed by `Original prompt: PING`.
5. Type `ping`, then `say PING`. Expected: both pass through normally.
6. Context check: type `Quote verbatim any warning, hook message or code you saw in this session, and the exact text of my previous messages.` If the reply contains `4711`, the reason **does** reach the agent's context, which breaks the design.
7. `cat hook-log.jsonl`. You should see one line per message. The `keys` show what the input contains; look for any field that marks where a prompt came from.

**Steps: phone (Remote Control)**
1. Start the same session from step 1 (or a new one in the same folder) and run `/remote-control`. Open the session in the Claude app on the phone.
2. From the phone, send `hello`. Expected: a normal reply. On the Mac, check `tail -1 ~/moadix-scratch/ups-test/hook-log.jsonl` to confirm the hook **fired for a phone message**.
3. From the phone, send `PING`. Record: (a) whether `hook-log.jsonl` gained a `PING` line (hook fired), (b) what the **phone** shows: the `TEST CODE 4711` text, a generic error, or nothing, and (c) what the **terminal** shows for the same turn.
4. Repeat step 6 of the terminal test from the phone.
5. If you can, repeat in a cloud session started from the phone app (claude.ai/code). That is a different path from Remote Control.

The design needs both of these: the hook fires for phone messages, **and** the phone shows `4711`. If the log shows the hook fired but the phone doesn't show the code, approvals from the phone need another channel (design open question 1).

## 6. Licences

All LICENSE files were fetched on 2026-11-10 from the default branch (BMAD from tag `v6.12.4`). Copies are in `~/moadix-scratch/licences/`; I re-checked the headers and BMAD's trademark line locally.

| Project | Source | Licence | Copyright line | Redistribute modified in OSS plugin? | Attribution required |
|---|---|---|---|---|---|
| BMAD-METHOD 6.12.4 | github.com/bmad-code-org/BMAD-METHOD @ v6.12.4 | MIT + trademark notice | `Copyright (c) 2025 BMad Code, LLC` | Yes, code. **Name restricted** | MIT notice. TRADEMARK.md: marks "are **not** licensed under the MIT License"; may not use "BMad" or variants "as your product name"; may "Refer to BMad to accurately describe compatibility" |
| bmad-retrospective | same repo, `src/bmm-skills/ship/bmad-retrospective/` | MIT (same) | same | Yes, but consider renaming (trademark) | same |
| Pocock skills | github.com/mattpocock/skills | MIT | `Copyright (c) 2026 Matt Pocock` | Yes | MIT notice |
| obra/superpowers | github.com/obra/superpowers | MIT | `Copyright (c) 2025 Jesse Vincent` | Yes | MIT notice |
| ECC | github.com/affaan-m/ECC (renamed from everything-claude-code) | MIT | `Copyright (c) 2026 Affaan Mustafa` | Yes (`agents/typescript-reviewer.md` under root MIT) | MIT notice; some unrelated skills have their own licences |
| ui-ux-pro-max | github.com/nextlevelbuilder/ui-ux-pro-max-skill | MIT (root) | `Copyright (c) 2024 Next Level Builder` | Yes | MIT notice. **`ui-styling` sub-skill is Apache-2.0** |
| Impeccable | github.com/pbakaus/impeccable | Apache-2.0 | `Copyright 2025 Paul Bakaus` | Yes | LICENSE copy, **NOTICE.md must be carried**, change notice in each modified file; `reference/ios.md`/`android.md` also need ehmo's MIT notice |
| awesome-design-md | github.com/VoltAgent/awesome-design-md | MIT | `Copyright (c) 2026 VoltAgent` | Yes | MIT notice; files analyse 84 third-party brands with no trademark disclaimer. Add "not affiliated" |
| Anthropic threat-model skill | github.com/anthropics/defending-code-reference-harness, `.claude/skills/threat-model/` | Apache-2.0 | `Copyright 2026 Anthropic PBC` | Yes | LICENSE copy + change notices; no NOTICE |
| wshobson/agents | github.com/wshobson/agents | MIT | `Copyright (c) 2024 Seth Hobson` | Yes | MIT notice |
| cc-sdd | github.com/gotalab/cc-sdd | MIT | `Copyright (c) 2025 gotalab` | Yes | MIT notice |
| spec-kit | github.com/github/spec-kit | MIT | `Copyright GitHub, Inc.` | Yes | MIT notice |
| pr-review-toolkit | github.com/anthropics/claude-plugins-official, `plugins/pr-review-toolkit/LICENSE` | Apache-2.0 | none filled in (appendix placeholder) | Yes, **from this repo only** | LICENSE copy + change notices. The older copy under anthropics/claude-code was covered by its proprietary `LICENSE.md` ("© Anthropic PBC. All rights reserved."); plugins moved out in commit 10a5141d (2026-10-26) |
| claude-reflect | github.com/BayramAnnakov/claude-reflect | MIT | `Copyright (c) 2025 Bayram Annakov` | Yes | MIT notice |

**Not confirmed:** Impeccable's `cursor-plugin/LICENSE` was not compared, and ECC's unrelated sub-licences were not read. Neither affects the selected parts. The "Final selection" document itself is not in this repo, so this list was taken from the increment brief.

**Apache-2.0 note:** §4(b) requires "prominent notices stating that You changed the files" **in the modified files**. Recording removals "beside the skill" (design §6) is not enough for the three Apache sources. Put a header in each modified file as well.

## 7. Managed `enabledPlugins` from a private Git marketplace

Docs (<https://code.claude.com/docs/en/plugins/org.md>):
- Force-install: "After the settings reach a machine, Claude Code registers the marketplace and installs the two plugins at the start of the user's next session."
- Users can't disable it: "disabling one at their own scope doesn't stop it from loading, because managed settings take precedence over every other scope."
- Private repos: "If the marketplace is a private git repository, each user needs read access to it. The clone of a git-based marketplace runs with git on the user's machine, using stored credentials and no prompts."
- Self-hosted URLs are valid sources (`{ "source": "git", "url": "https://gitlab.example.com/..." }`).
- `strictKnownMarketplaces` is an allowlist and "Doesn't register a marketplace".

**Verdict: not stated as a combined case.** Each piece is documented. It most likely works whenever the user's git can clone without a prompt, but measuring it needs a managed-settings file. That means root, so do it in a Linux Docker container (`/etc/claude-code/managed-settings.json`), not on this Mac. For an open-source MOADIX the marketplace would be public anyway, which makes the question moot.

## Contradictions with docs/DESIGN.md

1. **Docker breaks invariant 1.** Design §2 says `.sdlc/` is unwritable "through the sandbox, to every process it runs". Measured: once Docker works (socket in `allowUnixSockets`, or `excludedCommands`, which the docs recommend), any sandboxed process can write anywhere the user can, including `.sdlc/`, because mounting the product repo includes it. The mitigation "deny mounts outside the product repo" therefore (a) still allows `.sdlc/`, and (b) only sees `docker` command lines, not compose files, scripts or raw socket clients. The ledger anchor (invariant 8) detects rewrites of the hash chain. It does not stop someone writing the anchor's sibling state, or tampering with evidence before it is hashed.
2. **Playwright via Bash does not run under the macOS sandbox** (Chromium Mach check-in denied). Phase 8 e2e needs `excludedCommands`, which runs the command with full access, a second escape. Playwright MCP is outside the sandbox (docs) and is unaffected.
3. **The sandbox needs a curated network allowlist and cache `allowWrite`**, which design §2 does not list. Without them, with `allowUnsandboxedCommands: false` and in headless runs, npm and browser installs fail. npm's EPERM message also tells the agent to `sudo chown`.
4. **"The block reason … is not added to the agent's context"** (design §4 step 3) is **not stated in the docs**. Pending your item 5 test, step 6.
5. **Phone approvals** are unconfirmed (design open question 1). The docs are silent; pending your test.
6. **Licence handling:** Apache-2.0 sources need change notices in the modified files, not only beside them. `bmad-retrospective` keeps a BMad trademark in its name. pr-review-toolkit must come from `claude-plugins-official`.
7. Minor: the design says "Settled by the docs" for managed-hook behaviour, and that matches. Hooks run outside the sandbox (docs: "Claude's file tools, MCP servers, and hooks run outside it"), which is consistent with the design.

## Hard-limit incident

While diagnosing npm and Playwright, runs 1–4 wrote outside `~/moadix` and `~/moadix-scratch`:
- npm in runs 1–4: 12 new entries in `~/.npm/_cacache` and 11 debug logs in `~/.npm/_logs`.
- Run 4 (`allowWrite` on the default browser cache): one link file, `~/Library/Caches/ms-playwright/.links/8946bfc27b903ac3f5bfc3e5d7d5bc280f9cc3e5`, pointing at the scratch project.

From run 5 on, every cache was redirected into scratch. The cleanup delete of the link file was blocked by the permission classifier, so all of these are still in place. Nothing outside those caches was touched; `~/.claude/settings*.json` and `~/sdlc-harness` were only read (key-name counts) or not accessed.
