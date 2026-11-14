# Main-branch guard, and the gh and firebase allowlists

0.5.2 · `gate/mainguard.py`, called from the gate's PreToolUse check for Bash (`gate/pretool.py`) in every repository.

## 1. What the operator asked for

**Source of this record.** The request was made in chat on 2026-11-14, before increment 7. MOADIX's own policy denies the agent read access to Claude Code transcripts (`~/.claude/projects`), so the agent could not re-read the original messages. What follows is the record kept during that session. Quoted phrases are the operator's own words; the rest restates his items without changing them.

### The change request

1. **Sandbox network.** Add nine product hosts (the Firestore, Firebase and Google API endpoints, Sentry and the Vercel API; their names now live only in the operator's local overlay).
2. **Unsandboxed tools.** Add `excludedCommands` `"gh *"` and `"firebase *"`, so they run with the operator's own logins.
3. **Managed deny rules.** `Bash(git push*main*)`, `Bash(git push*HEAD:main*)`, `Bash(git push --all*)`, `Bash(git push --mirror*)`, `Bash(gh pr merge*)`, `Bash(vercel promote*)`, `Bash(vercel --prod*)`, `Bash(vercel deploy --prod*)`.
4. **Project guards.** Propose, without choosing, how project PreToolUse guards (which `allowManagedHooksOnly` switches off) should run.
5. **Delivery.** Show the diff and tests first; the operator runs the reinstall himself.

### The operator's four decisions

1. **gh outside the sandbox is approved,** with extra deny rules: `Bash(gh auth token*)`, `Bash(gh api*merge*)`, `Bash(gh api*-X PUT*)`, `Bash(gh api*--method PUT*)`, `Bash(gh api*-X PATCH*refs*)`, `Bash(gh api*--method PATCH*refs*)`.
2. **firebase outside the sandbox is approved,** with deny rules for the production project and `firestore:delete`. "Staging deploys stay allowed."
3. **Text patterns are a coarse first layer;** their limits are accepted.
4. **Option A:** a guard in the gate, for every repository.
   - It refuses any push whose target is main, in any form.
   - It refuses any `gh pr merge`, and any `gh api` merge of a PR whose base is main.
   - It refuses Vercel production deploys and promotes.
   - It parses shell words, with no false positives on names like `feature/main-menu`.
   - It fails closed on any error or timeout and stays under the 15 s hook limit.

### Restructuring ordered after the increment-7b review (0.5.2)

- **Allowlists.** gh and firebase run outside the sandbox with the operator's credentials, so "a deny-list is not acceptable". Both are now allowlists in the guard, failing closed.
- **Nothing product-specific in the public repository.** The production project id and the product hosts moved to the operator's local overlay (`docs/INSTALL.md`, "Local overlay").

## 2. What the guard refuses (every repository)

1. **Pushes to main.**
   - Refspecs: `main`, `refs/heads/main`, `HEAD:main`, `x:main`, `+main`, `:main`, `--delete main`.
   - `HEAD`/`@` while on main.
   - Wildcard and matching refspecs, `--all`, `--branches`, `--mirror`.
   - A bare push on main, tracking main, under `push.default=matching`, or with `remote.<r>.push` onto main.
   - The same through `git -C`, `git -c`, aliases, `send-pack`, `sh -c`, `eval`, heredocs, `$(...)`, `xargs`, `find -exec`, `submodule foreach`, `rebase --exec` and `bisect run`.
   - `--no-verify` and `core.hooksPath` changes.
2. **Merges.** Every `gh pr merge`, and every gh write (section 3).
3. **Production deploys.** Vercel `--prod`, `--production`, `--target production`, `promote`, `rollback` and `alias set`, also through npx, bunx, pnpm, yarn and npm. Firebase deploys to a protected project (section 4).
4. **gh and firebase in any form but the direct one.** Both may run only when typed directly as the whole command. Refused around them:
   - a shell wrapper (`sh -c`, `bash -lc`), `eval`;
   - an `env` or `VAR=` prefix; `command`, `exec`, `time` or `nohup`;
   - an alias or hash entry naming them;
   - `xargs`, `find -exec`, `npx`/`pnpm`/`yarn`/`bun` runners;
   - a full or relative path to the binary;
   - a pipe in or out, a compound command (`&&`, `;`, `||`), background `&`, a subshell;
   - `$(...)`, backticks or a variable in an argument;
   - any redirection or here-string.
5. **Scripts that call gh or firebase.**
   - The guard reads and refuses shell scripts (`sh x.sh`, `./x.sh`, `source`), interpreter files (`node x.js`, `python x.py`) and package scripts (`npm run`, `npm test`, `yarn` and similar) whose text invokes gh or firebase.
   - Separately, a script never gets the operator's credentials. `excludedCommands` takes only a command that *starts with* `gh ` or `firebase ` out of the sandbox; a script runs inside it, where the Keychain and the CLIs' credential files (`~/.config/gh`, `~/.config/configstore`, read-denied since 0.5.2) are out of reach.
6. **Anything it cannot resolve** is refused: a value computed at run time, an unknown branch, a git error or timeout, nesting deeper than 6, an internal error.

## 3. gh allowlist

**Allowed:**

| Area | Commands |
|---|---|
| pr | `create`, `view`, `list`, `diff`, `checks`, `status`, `comment` |
| run | `list`, `view`, `watch` |
| issue | `list`, `view`, `create`, `comment` |
| repo | `view` |
| auth | `status` (without `-t`/`--show-token`) |
| other | `gh api` with GET only; `--help`, `--version` |

**Conditions on the allowed commands:**

- `--body-file`/`-F` and `--template` must name a file inside the current repository, not a dotfile path and not stdin. Outside the sandbox gh could read any file, so only repository files may be sent.
- `gh api`:
  - the method is GET (default or explicit);
  - fields or `--input` without an explicit `-X GET` are refused, because gh would send a POST;
  - `graphql` is refused (a POST that can carry mutations);
  - unknown options are refused.

**Refused**, in every form (not on the list):

- `auth token`, `auth status -t`/`--show-token`, `auth login`, `auth refresh`, `auth setup-git`;
- `config`, `secret`, `variable`, `ssh-key`, `gpg-key`;
- `repo delete`, `edit`, `rename`, `archive`, `create`, `sync`;
- `release`, `workflow` (run, enable, disable), `ruleset`;
- `pr merge`, `checkout`, `edit`, `close`;
- `alias`, `extension`, and any alias or extension name;
- `api` with POST, PUT, PATCH or DELETE;
- everything else.

## 4. firebase allowlist (proposed from what the operator needs)

| Use | Allowed | Conditions |
|---|---|---|
| Emulators | `emulators:start` | `--only` must list only emulators that run no product code: `auth`, `firestore`, `database`, `hosting`, `storage`, `pubsub`, `eventarc`, `ui`. The functions emulator, and the default set that includes it, would run product code outside the sandbox. `serve` is held to the same rule. |
| Deploy to non-production | `deploy`, `hosting:channel:deploy` | An explicit `--project`/`-P` that is neither a protected project nor a `.firebaserc` alias of one. No `--force` (it deletes what the source no longer has). No `predeploy`/`postdeploy` hooks in `firebase.json` (firebase runs them as shell commands outside the sandbox). |
| Read-only | `projects:list`, `login:list`; `apps:list`, `functions:list`, `functions:log`, `firestore:indexes`, `hosting:channel:list`, `hosting:sites:list` | Commands that name a project need an explicit non-protected `--project`. |
| Always | `--version`, `help`, `<command> --help` | |

**Refused:**

- every destructive or credential command: `firestore:delete`, `database:remove`, `database:set`, `database:update`, `database:push`, `functions:delete`, `hosting:disable`, `auth:import`, `auth:export`;
- `functions:config:*`, `functions:secrets:*`;
- `login`, `login:ci`, `logout`, `use`, `init`, `emulators:exec`, `ext:*`;
- `--token`;
- any command that names no project when it needs one (the `.firebaserc` default may be production);
- every command, when no local overlay is installed and the command names a project.

## 5. Accepted risks

1. **Allowed hosts can carry data out.**
   - Every host on the sandbox network allowlist (the overlay's product hosts, the registries, `api.github.com`…) can receive data the agent sends. The sandbox limits *where* traffic goes, not *what* it carries.
   - gh and firebase, outside the sandbox, can likewise send repository content to GitHub (an issue or PR body) and to non-production Firebase projects.
   - Mitigations: secrets stay out of reach (Keychain, the CLIs' credential files read-denied, `.env` files protected, the phase-11 token never in the agent's shell), and the host list stays short. The risk is not removed.
2. **Acting as the operator.** Allowlisted gh commands act on GitHub with the operator's identity: opening PRs and issues, commenting. Operator decision 1 accepted this.
3. **Text patterns.** The managed deny rules match the typed command only; `*main*` also catches `feature/main-menu`. The guard is the real check.
4. **What the guard cannot see.** Shell aliases and functions defined outside the command, and an interpreter reading code from a file the guard is not shown. These run inside the sandbox, without the CLIs' credentials. Branch protection on the server remains the backstop for pushes.
5. **Local moves of main.** Commit, merge or reset on main, `branch -f`, `update-ref` are not refused. They reach GitHub only through a push, which is refused.
