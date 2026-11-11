# Vendored skills: policy

Every skill under `skills/` is a copy of an upstream skill at a pinned commit (DESIGN.md §6, increment 3). `skills/SOURCES.yaml` records each one's source URL, commit, path, licence and attribution. The phase manifest (`gate/config/phase-manifest.yaml`) says which phase may load which skill. The PreToolUse hook denies any other `Skill` or MCP call.

## What a vendored skill may not say

MOADIX's central property is that **the agent can never mark its own work done** (DESIGN.md goal 5). Only the operator's typed `APPROVE <phase> <code>` approves a phase, and only the gate records it. So every vendored skill has these removed:

| Category | Examples of removed text |
|---|---|
| **self-approve** | "approve the PRD", "mark the review as approved", "the reviewer approves", "verdict: APPROVED → proceed" |
| **mark-done** | "set `status: final`", "mark the story done", "flip status to complete", "check the box when finished" |
| **auto-advance** | "then invoke the next skill", "proceed to the next phase", "automatically continue with X", "Common next: …" routing lists |
| **commit / merge / ship** | "git commit", "commit the changes", "open/merge the PR", "push", "tag a release", "ship it", "deploy" |

A removed step is replaced with nothing, or with a neutral line that hands control back, for example: *"Stop here and report what you produced. The operator decides whether the phase is approved (MOADIX gate)."*

User checkpoints **inside** a skill (asking the operator a question, or waiting for their answer before continuing) are kept. That is the human deciding, not the agent.

## How each change is recorded

- `skills/<name>/MOADIX-CHANGES.md` lists every removal and modification: file, the original text (quoted), what replaced it, and its category (`self-approve`, `mark-done`, `auto-advance`, `commit`, `merge`, `ship`, or `adaptation` for path and format changes that are not about approval).
- Files from **Apache-2.0** sources also carry a change notice at the top of each modified file (Apache-2.0 §4(b)):
  `<!-- Modified by MOADIX (YYYY-MM-DD): <one line>. See MOADIX-CHANGES.md. Original: <url>@<commit> -->`
  (for a file with YAML frontmatter, the notice goes right after the closing `---`).
- Each skill directory carries its upstream licence as `LICENSE` (and `NOTICE.md` where upstream has one).

## The grep

`tests/skills/selfapproval_grep.py` scans every vendored text file. A line matches if it names approving, merging, shipping or committing, marks something done or final, or advances to a next phase or skill on its own. Every match must either be gone, or be listed in `skills/<name>/MOADIX-GREP-ALLOW.tsv` (or the global `skills/grep-allowlist.tsv`) with the reason it is not an instruction to the agent (for example, "shipping" as an e-commerce data value). The test fails on any other match. `MOADIX-CHANGES.md`, `MOADIX-GREP-ALLOW.tsv`, `LICENSE`, `NOTICE.md`, `SOURCES.yaml` and this file are not scanned: they quote the removed text on purpose.

## Upgrading a vendored skill

Upgrading is a proposal: a diff against the pinned commit, re-applying every entry in `MOADIX-CHANGES.md`, approved like any other change (DESIGN.md §6).
