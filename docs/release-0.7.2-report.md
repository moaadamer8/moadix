# 0.7.2: hook confirmations, critic convergence (design §10, rulings A1–A5), task-tracker MF-21 to MF-26

Sources:
- the operator's review of 0.7.1: Part 2 accepted with three hook confirmations, §10 approved with rulings A1–A5;
- `~/task-tracker/docs/moadix-findings.md` MF-21 to MF-26, read only.

0.7.2 includes 0.7.1, which was committed but not installed.

## Hook item 1: what a read inside a substitution obeys

**The hook enforces no read-deny rule on a top-level Bash read.** Every rule below that holds today is enforced by the sandbox (`denyRead` in `managed/managed-settings.json`) and, for the Read tool, by the managed `Read()` permission rules. The hook itself refuses only the Read, Grep and Glob tools on `~/.claude/projects`.

0.7.2 makes a substitution **stricter** than a top-level read. The hook refuses any `$(…)`, backtick or `<(…)` whose text names a protected path, read-only or not. It resolves leading literal variables first.

| Protected | Top-level `cat` enforced by | Substitution `$(cat …)` | Test (`tests/rel072`, readdeny) |
|---|---|---|---|
| Claude Code transcripts `~/.claude/projects/**` | sandbox `denyRead` + `Read()` rule; the hook refuses the Read tool | hook refuses, and the sandbox | 5 forms refused; Read tool refused |
| memory `~/.claude/projects/*/memory/**` | the same (it lies under transcripts) | hook refuses, and the sandbox | 5 forms; Read tool refused |
| gh credentials `~/.config/gh/**` | sandbox `denyRead` + `Read()` rule | hook refuses, and the sandbox | 5 forms, plus a variable form |
| firebase credentials `~/.config/configstore/**` | sandbox `denyRead` + `Read()` rule | hook refuses, and the sandbox | 5 forms |
| the overlay `~/.config/moadix/**` | **nothing**: write-protected only (sandbox `denyWrite`) | hook refuses | 5 forms |
| `.env`, `.env.*` | **nothing**: write-protected only (path map, secret class) | hook refuses (`.env.example`, `.sample` and `.template` stay readable) | 5 forms each for `.env` and `.env.local` |
| key material (`*.pem`, `*.key`, `id_rsa`, Keychains, …) | **nothing** in the hook or the sandbox | hook refuses | 5 forms for `~/.ssh/id_rsa` |

The test records the top-level decision for each row (the hook gives none), so a change to that layer shows up.

**Not covered by the hook.** A path the hook cannot read from the text is left to the sandbox: a glob (`~/.conf*/gh`) or a variable set outside the command.

**gh and firebase run outside the sandbox** (`excludedCommands`). The main-branch guard lets them run only as the whole command, with no substitution, pipe or compound. So every substitution runs inside the sandbox, where `denyRead` applies. This is tested: `<gh> issue create --body "$(cat README.md)"` is refused.

## Hook item 2: the reader allowlist

`bashcls.SUBST_READ_ONLY`, exactly:

ls, cat, head, tail, wc, grep, egrep, fgrep, stat, du, md5, md5sum, shasum, sha1sum, sha256sum, echo, printf, basename, dirname, realpath, readlink, test, [, true, false, jq, diff, cmp, sort, uniq, cut, tr, column, nl, fold, git, pwd, seq.

**Removed from the 0.7.1 list:**

- `file`: `-C` compiles a magic file and writes it.
- `date`: `-s` sets the clock.

`tee` was never on the list. A test asserts the exact set.

**Rules for every reader:**

- called by bare name, never a path (`/bin/cat` is refused);
- no environment prefix;
- no write redirection;
- no nesting;
- none of `--output`, `--compress-program`, `--ext-diff`, `--exec-path`, `--temporary-directory`, `--paginate`, `--textconv` or `--filters`;
- no function, alias, `PATH=`, `BASH_ENV=`, `IFS=`, `setopt` or `shopt` anywhere in the command. This one is new: a function such as `cat() { "$@"; }` can shadow a reader. It turns L2 and L4 off.

| Tool | What could write or execute | How it is closed | Refused tests |
|---|---|---|---|
| sort | `-o FILE` (also `-ofile`, bundled `-ro`), `--output`, `-T`/`--temporary-directory` (temporary files), `--compress-program` (runs a program) | any short-option cluster containing `o` or `T`, and the long options | 7 |
| uniq | `uniq IN OUT` writes OUT | no operand at all (stdin only) | 2 |
| jq | writes nothing; modules load code from files | `-L`, `--library-path`, and `import` or `include` in the program are refused | 4 |
| git | `--output`, `--ext-diff`, `-c` (pager, textconv, external diff), `-p`/`--paginate`, textconv on show of a commit, fsmonitor and hooks on status, signature checks (`gpg.program`) on log | Global options: only `-C <dir>`. Subcommands: `rev-parse`; `cat-file` with `-t`, `-s`, `-p` or `-e` only; `show` only of a literal `<rev>:<path>` blob, with no option. git-show(1) says "For plain blobs, it shows the plain contents": no diff, no textconv, no signature. log, diff, status, blame and ls-files are no longer readers | 21 |
| diff, cmp | no write or exec option in BSD or GNU | the generic long-option list | — |
| cat, head, tail, wc, grep, egrep, fgrep, stat, du, md5, md5sum, shasum, sha*sum, ls, cut, tr, column, nl, fold, echo, printf, basename, dirname, realpath, readlink, test, [, true, false, pwd, seq | none of their options writes a file or runs a program (grep's `-f` and wc's `--files0-from` only read) | — | — |

The suite also refuses tee, file, date, awk, sed, rg (`--pre`), find, yq and xargs, plus the path, env-prefix, redirection and nesting forms. That makes 47 refused bodies, each checked twice: `read_only_body` is false, and the hook refuses `echo "$(…)" .sdlc`. Fourteen reader forms pass.

**What this takes back from 0.7.1.** `git show $c:path` with a variable revision is refused again, because `$c` could be `:/message`, which shows a whole commit. MF-16d's exact loop form is therefore refused. The literal form, `$(git show HEAD:path)`, still passes.

## Hook item 3: the comparison

The 1,692 command strings from the corpus, gate2, mainguard, inc6, inc7d and verifier suites went through the 0.7.0 hook and the 0.7.2 hook (`pretool.check_bash`, outside a product):

- **0 changed decision.**
- On the classifier's own fields, 3 differ, the same three as in 0.7.1:
  - the sed case (L6);
  - `python3 - <<'EOF'` is now opaque;
  - `<gh> … "$(cat ~/.ssh/id_rsa)"` is no longer opaque, but the main-branch guard refuses it. In 0.7.2 the new read-deny rule also refuses it as key material.

## Built: design §10 as ruled

| Ruling | What the gate does | Where |
|---|---|---|
| A1, A5 | Runs 1 and 2 are full. From run 3 the brief adds "Scope of this run": the frozen rule and every section changed since run n-1, in full. A new finding on a section unchanged at run n-2, run n-1 and the reviewed commit needs a BLOCKER with `exception` `security`, `privacy` or `tenant` (whose words must appear in its quote or fix), or `upstream` with a citation in an earlier APPROVED or PROCEED-PAST phase. Without one it goes to the MINOR file tagged `[frozen]` and blocks nothing; PROCEED-PAST does not list it as passed. One the critic rated BLOCKER is shown in full in REVIEW and in the APPROVE reply, recorded or refused, under "Frozen findings rated BLOCKER by the critic, not blocking". STATUS counts frozen-text findings. A `regression_of` that cites another section, unchanged since the original's run, gets a new id as a new finding | `gate/critic.py` ingest, `brief_sections`; `gate/contract.py` critic_check; `gate/v1/check_verifiers.py`, `gate/validate.py`, `gate/validation.py`, `gate/opcmd.py` |
| A2 | `fixed?` when the cited lines are gone **or** the section changed (MF-17, MF-22). A waiver still lapses only on its cited lines | `gate/critic.py` dispositions, fingerprint |
| A3 | `kind: uncited` with `claim_class` and `decision`. The gate checks that the decision id exists (a Q-n heading, an ADR file, a decides rule) and records the table's severity, noting it in the MINOR file. A quote naming security, privacy or tenant terms must be class `security`. Catalogue texts updated: D1.3, D1.B, phase 1 blockers, global BLOCKER, `agents/gap-critic.md` | `gate/critic.py` claim_rule, `gate/config/coverage-topics.yaml`, `gate/config/critic.schema.json` |
| §10.4 | The brief: "You have no network; judge support only from quoted text". `uncited` on a line with a URL and a date (or a dated footnote) is refused. `kind: support` needs `basis`; `quote-*` needs a quote in the cited section; `no-quote` only for a decision-bearing legal, cost, security or feasibility claim (MAJOR) | `gate/critic.py` claim_rule, `gate/verify.py` brief |
| A4 | `sizes.S.bars`: R2 "2 to 3 real products", B13 "at least 2 competitors". They are shown in the brief's topic list and in `/moadix:coverage`; `turn_on` restores the full bar | `gate/config/coverage-topics.yaml`, `gate/contract.py` bars, `gate/verify.py` |

§10.9 of the design says where the build differs from the text: section bodies are compared instead of mapping diff hunks; a file without headings is one section; and which problems fail the evidence.

## Built: task-tracker findings after MF-20

| Finding | Change |
|---|---|
| MF-21 | On APPROVE and PROCEED-PAST, the carries are collected from every run of the phase: the current run's CARRY findings, plus each earlier one whose disposition is still `carried`, with its text and commit from that run. The archive now keeps each finding's `fix` and `ac` for this. |
| MF-22 | Covered by A2: an appended sentence or a renamed heading changes the section, so the finding is `fixed?`. |
| MF-23 | ears-lint: `UNIT` ends with `(?!\w)` instead of `\b`, so `100% of` is a number with a unit. |
| MF-24 | A directory belongs to the phase that owns exactly `<dir>/**`, so `mkdir -p sdlc/2` works in phase 2. A parent such as `sdlc` still belongs to no phase. |
| MF-26 | Where the file goes: `.dependency-cruiser.json` sits at the repository root, where dependency-cruiser and the gate read it. Phase 3 writes it (H20), phase 7 may refine it (I6), and onboarding phase B writes it (BL3). Phases 4–6 see it frozen. How the gate runs it: when none of the configured scan paths (`depcruise.paths`, default `src`) has a tracked file at HEAD, the gate cruises an empty folder with the rules. A malformed configuration still fails, and the note says "configuration only; no source in src yet". Once `src/` exists, the gate cruises it. |
| MF-25 | Data only, the same pattern as MF-12 and MF-18; addressed by A1. |

## Tests

- `tests/rel072/run.py`: new suite, 175 checks:
  - readdeny 53;
  - readers 62;
  - shadow 6;
  - frozen 10;
  - textchange 4;
  - claims 18;
  - upstream 4;
  - bars 5;
  - carries 2;
  - defects 10;
  - guard 1.
- `tests/rel071` changed one test, to the literal revision.
- Passing here:
  - gate2 299;
  - inc7 141, inc7b 58, inc7c 78, inc7d 150, inc8 72;
  - verifiers 97, release 9, skills 43;
  - tools 107 (2 skipped: loopback);
  - rel071 61, rel072 175.
- **Not run here:**
  - `tests/mainguard/run.py` and `tests/inc6/run.py`: the installed 0.7.0 main-branch guard refuses any script whose text names the gh or firebase CLI. In 0.7.1 I ran inc6 through a `for` loop with the path in a variable, which hid it from that scan. This time I did not.
  - corpus, install dry run and confined-engine: they need the Keychain or Docker.
  - All five are steps 2–5 of "Updating from 0.7.0 to 0.7.2" in `docs/INSTALL.md`.
- **Not verified on a real engine:** that dependency-cruiser exits 0 on an empty folder with a valid rules file. That is step 5 of the same procedure.
