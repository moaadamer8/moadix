# MOADIX changes: verification-before-completion

- Upstream: https://github.com/obra/superpowers
- Commit: 22f0b463e7a5e579904dd6211a520321035526f7
- Path: skills/verification-before-completion
- Licence: MIT, Copyright (c) 2025 Jesse Vincent (root LICENSE, copied here as `LICENSE`)
- Vendored: 2026-11-11, for MOADIX phase 7

Files copied: `SKILL.md`. No test suite upstream.

## Changes

### 1. SKILL.md frontmatter `description`
- Original: "Use when about to claim work is complete, fixed, or passing, before committing or creating PRs - requires …"
- Replacement: "Use when about to claim work is complete, fixed, or passing, before reporting results or requesting review - requires …"
- Category: commit

### 2. SKILL.md, The Iron Law: what a claim is (added)
- Original: (none; after "If you haven't run the verification command in this message, you cannot claim it passes.")
- Replacement: "A claim here is a report to the operator with its evidence. It never closes a task or a phase: the operator decides that (MOADIX gate)."
- Category: mark-done

### 3. SKILL.md, Red Flags
- Original: "- About to commit/push/PR without verification"
- Replacement: "- About to report results or request review without verification"
- Category: commit

### 4. SKILL.md, When To Apply
- Original: "- Committing, PR creation, task completion"
- Replacement: "- Reporting results, requesting review, describing a task's state"
- Category: commit

Kept verbatim: the evidence-before-claims core, the ❌ example "Tests pass, phase complete" (shown as the wrong pattern), and "Moving to next task" (verification required before it; not an instruction to advance a phase).

## Grep allowlist
None needed.
