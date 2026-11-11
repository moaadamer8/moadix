# MOADIX changes: typescript-reviewer

- Upstream: https://github.com/affaan-m/ECC
- Commit: d2ef2680594f9a17526a6e1a2e18b3d242c5d17b
- Paths: `agents/typescript-reviewer.md` (vendored as `SKILL.md`); `rules/typescript/{coding-style,hooks,patterns,security,testing}.md` (vendored as `rules/*.md`)
- Licence: MIT, `Copyright (c) 2026 Affaan Mustafa` (repo-root LICENSE copied as `LICENSE`; `rules/typescript/` has no separate licence file)
- Vendored: 2026-11-11. MOADIX phase 7 (TypeScript reviewer).

## Changes

| # | File | Original (quoted) | Replacement | Category |
|---|---|---|---|---|
| 1 | SKILL.md | file `agents/typescript-reviewer.md` (a Claude Code agent definition) | `skills/typescript-reviewer/SKILL.md`; the agent prompt is the skill body, unchanged except as below | adaptation |
| 2 | SKILL.md (frontmatter) | `tools: Read, Grep, Glob, Bash` / `model: sonnet` | removed (agent-only keys; `name` and `description` kept verbatim) | adaptation |
| 3 | SKILL.md | "## Approval Criteria / - **Approve**: No CRITICAL or HIGH issues / - **Warning**: MEDIUM issues only (can merge with caution) / - **Block**: CRITICAL or HIGH issues found" | "## Findings Summary / - List every finding with its severity (CRITICAL, HIGH, MEDIUM), file and line, and a count per severity. / - Give no overall verdict and no recommendation on whether the change may go ahead (no verdict; the operator decides, MOADIX gate)." | self-approve, merge |
| 4 | SKILL.md ("Reference") | "For detailed TypeScript and JavaScript patterns, use the `typescript-patterns` skill, plus `coding-standards` and `frontend-patterns` or `backend-patterns` based on the code being reviewed." | "Apply the TypeScript/JavaScript rules in `rules/` next to this file (`coding-style.md`, `patterns.md`, `security.md`, `testing.md`, `hooks.md`) alongside the priorities above, and report violations as findings." (the named skills are not vendored; the phase manifest would deny them) | adaptation |
| 5 | SKILL.md ("MEDIUM -- React / Next.js") | "> **For React-specific review, prefer `react-reviewer` via `/react-review`.** This block remains as a fallback only — when the diff contains `.tsx`/`.jsx` files, both agents should be invoked. See `agents/react-reviewer.md` …" | "> **MOADIX:** the upstream `react-reviewer` agent is not vendored; apply this block to `.tsx`/`.jsx` files in the diff." (verifiers have no Agent tool; the agent is not vendored) | adaptation |
| 6 | SKILL.md | (none) | HTML comment after the closing `---` naming the change and the upstream commit | adaptation |
| 7 | rules/*.md | (none) | copied verbatim from `rules/typescript/`. Their links to `../common/*.md`, mentions of `security-reviewer` / `e2e-runner`, and the `~/.claude/settings.json` hook suggestions in hooks.md are upstream context and are not vendored | adaptation |

Kept on purpose: workflow step 2 (inspect PR merge readiness / CI state and stop if not green) reads state and stops; it never merges. The closing mindset line "Would this code pass review at a top TypeScript shop…" is a quality bar, not a verdict.

## Grep allowlist

See `MOADIX-GREP-ALLOW.tsv`: 5 rows (git merge-base for the diff range; three lines of the merge-readiness precondition that stop and report; "Merging untrusted objects" as the prototype-pollution vulnerability class).
