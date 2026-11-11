# MOADIX changes: templates/DESIGN.md

- Upstream: https://github.com/VoltAgent/awesome-design-md
- Commit: fcc70284932276d085f01ef9f83edde90b1258cb
- Path: `design-md/notion/DESIGN.md` → `templates/DESIGN.md`
- Licence: MIT, `Copyright (c) 2026 VoltAgent` (repo root `LICENSE`, copied as `templates/LICENSE.awesome-design-md`)
- Use: the example DESIGN.md that MOADIX phase 6 (UX) starts from. Every value in it describes Notion's public marketing site and is meant to be replaced with the project's own.

Not affiliated with, endorsed by or sponsored by Notion. Notion and its marks belong to their owner.

## Why this file

Candidates read: `linear.app`, `vercel`, `stripe`, `notion`. All four share the same skeleton (YAML token frontmatter: `colors`, `typography`, `rounded`, `spacing`, `components`; then Overview, Colors, Typography, Layout, Elevation & Depth, Shapes, Components, Do's and Don'ts, Responsive Behavior). Notion was chosen because, for a product web app:

- it covers the most app-like components: text inputs with focus state, search, pill and segmented tabs, badges and status chips, tables, plus buttons, cards and navigation;
- it is light-mode first with a full text ramp (ink to muted) and explicit Success / Warning / Error semantic colors;
- it ends with both an **Iteration Guide** and a **Known Gaps** section (dark-mode tokens, motion timings, validation success state), which tells the author what the template does not settle;
- it contains no ship / deploy / approve wording (vercel has 10 such hits, linear 2, stripe 0 but no Known Gaps, and stripe's frontmatter names a parody brand, "Stripi").

`linear.app` is dark-only marketing; `vercel` is the longest and leans on a developer-marketing gradient vocabulary.

## Changes

### 1. Header comment (adaptation)

- File: `DESIGN.md`, inserted right after the closing `---` of the YAML frontmatter (placed there, not on line 1, so the frontmatter still parses)
- Original: (none)
- Replacement: one HTML comment naming the source, commit, licence, and "Not affiliated with, endorsed by or sponsored by Notion. Notion and its marks belong to their owner; the values below describe that brand's public site and are an example to replace."
- Category: adaptation.

Everything else is verbatim. Note for the operator: the upstream Iteration Guide step "Run `npx @google/design.md lint DESIGN.md` after edits" was kept verbatim; it fetches an npm package, which the MOADIX sandbox network list may not allow.
