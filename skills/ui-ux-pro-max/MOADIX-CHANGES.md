# MOADIX changes: ui-ux-pro-max

- Upstream: https://github.com/nextlevelbuilder/ui-ux-pro-max-skill
- Commit: 6ae86f61f520d6ca229d2f40e070410638c908c5
- Path: `.claude/skills/ui-ux-pro-max/` (everything except `scripts/tests/`)
- Licence: MIT, `Copyright (c) 2024 Next Level Builder` (repo root `LICENSE`, copied here as `LICENSE`)
- MOADIX phase: 6 (UX)

Not included: `scripts/tests/` (upstream test suite) and the repo's other skills. In particular the `ui-styling` sub-skill (Apache-2.0, `.claude/skills/ui-styling/`) is not vendored; no file in this directory is byte-identical to any file in it (checked by SHA-1), and no copied file references it.

All other files are verbatim. No self-approve, mark-done, auto-advance, commit, merge or ship instruction was found in the upstream text; the grep hits that remain are data values and code comments, listed in `MOADIX-GREP-ALLOW.tsv`.

## Changes

### 1. Script path (adaptation)

- File: `SKILL.md` (11 occurrences)
- Original: `python "${CLAUDE_PLUGIN_ROOT}/.claude/skills/ui-ux-pro-max/scripts/search.py" …`
- Replacement: `python "${CLAUDE_PLUGIN_ROOT}/skills/ui-ux-pro-max/scripts/search.py" …`
- Category: adaptation (MOADIX installs plugin skills under `skills/`, not `.claude/skills/`).

### 2. "MOADIX usage" block (adaptation)

- File: `SKILL.md`, inserted after the opening paragraph, before `## When to Apply`
- Original: (none; new section)
- Replacement: a `## MOADIX usage` section stating that phase 6 may write only `sdlc/06-*.md` and `design/**`, and requiring, per the operator's ruling:
  - every `--design-system` run adds `--persist --output-dir design`, so the design system lands at `design/design-system/<project-slug>/MASTER.md` (and `pages/`), not under the unwritable project root;
  - every `--domain style` and `--domain product` search adds `--rtl=full` (the `=` form, because `--rtl` is declared `nargs="?"` and would otherwise be ambiguous with the positional query); `--rtl` cannot be combined with `--design-system` or `--stack` (search.py rejects it), so the RTL searches run separately.
- Category: adaptation.
