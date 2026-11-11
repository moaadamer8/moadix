# MOADIX changes: impeccable

- Upstream: https://github.com/pbakaus/impeccable
- Commit: c1e0e5492fbb524f5df84d635ecfae7dc438ec45
- Path: `.claude/skills/impeccable/` (the built Claude skill)
- Licence: Apache-2.0, `Copyright 2025 Paul Bakaus` (repo root `LICENSE` copied as `LICENSE`; repo root `NOTICE.md` copied as `NOTICE.md`, which credits ehmo's MIT `platform-design-skills` for `reference/ios.md` and `reference/android.md`)
- MOADIX phase: 6 (UX)

Every modified file carries the Apache-2.0 §4(b) change notice at its top (after the frontmatter for `SKILL.md`). `reference/ios.md` and `reference/android.md` are verbatim.

## Changes

### 1. Trimmed to CRITIQUE and AUDIT (adaptation)

- File: whole skill
- Kept: `SKILL.md` (trimmed, below), `reference/critique.md`, `reference/audit.md`, `reference/audit.native.md`, and the files they link to: `reference/ios.md`, `reference/android.md` (linked from `audit.native.md` and from the adapted Setup).
- Dropped files: `reference/` adapt, adapt.native, animate, bolder, clarify, colorize, component-review, craft, craft-floor, delight, distill, doctor, document, extract, generate, harden, hooks, init, layout, live, live-setup, mode-operate, mode-persuade, mode-read, new-work, onboard, operate, optimize, overdrive, polish, quieter, region-map, routing, shape, typeset, visualize, `reference/degraded/*` (asset-producer, documenter, finish-reviewer, manual-edit-applier); all of `scripts/` (see change 2).
- Dropped from `SKILL.md`:
  - frontmatter `description` "Use to design, redesign, critique, audit, polish or animate a frontend: …" → "Use to critique or audit a frontend: … Produces findings; does not edit UI."; `argument-hint` "[shape · audit|critique · animate|bolder|… · init|document|extract|live|generate] [target]" → "[audit|critique] [target]".
  - Setup step 1 ("Run `<skill-base-dir>/scripts/impeccable context` once per session … downloaded once on first run …") → go straight to "Launcher unavailable"; read ios.md / android.md directly on native platforms.
  - Setup step 2 "Load the request's playbook: its Commands-table reference … or reference/new-work.md for a new surface … Inspect target and incumbent visual truth before editing." → load critique.md / audit.md / audit.native.md; "before assessing".
  - Setup step 3 "read reference/craft-floor.md immediately before any UI edit …" (removed: critique and audit do not edit UI).
  - "Launcher unavailable": "follow applicable steps 2–3, including reading reference/craft-floor.md immediately before any UI edit, and continue through permitted tools. This applies to planning and editing; …" → "follow step 2, and continue through permitted tools."
  - Section "How to design" (brief wins; refinement vs redesign "choose a replacement world in new-work and replace DESIGN.md"; loaded symbols; visual authority).
  - Modes: "…and persist it only in that surface brief." and "See new-work.md for new surfaces and operate.md for deeper Operate/Read guidance."
  - Commands table rows craft, shape, init, document, extract, polish, bolder, quieter, distill, harden, onboard, animate, colorize, typeset, layout, delight, overdrive, clarify, adapt, optimize, live, generate.
  - Routing: "No argument: read routing.md and present its context-aware menu" → ask critique or audit and which target, never auto-run; "Workflow or command-selection question" bullet; "Otherwise: treat the request as general design work … through init, then new-work …" → say this copy only critiques and audits; the `teach`/`craft`/`shape` alias bullet; "After init writes PRODUCT.md, resume …"; **Pin / Unpin**; **Hooks** ("auto-runs the detector after UI file edits"); **Doctor** ("reports and repairs drift"); "Never repair drift as a side effect …".
- Added to `SKILL.md`: a `## MOADIX usage` section: critique and audit produce findings only and do not edit UI, tokens, copy or DESIGN.md (the design reviewer writes findings); phase 6 writes only `sdlc/06-*.md` and `design/**`, so saved reports go to `design/reviews/`; the launcher is not vendored, so every `impeccable <verb>` is unavailable and the detector is reported as unavailable.
- Category: adaptation.

### 2. Launcher scripts not vendored (adaptation)

- Files: `scripts/impeccable`, `scripts/impeccable.cmd`, `scripts/engine-checksums.txt`, `scripts/VERSION`, `scripts/command-metadata.json`, `scripts/data/font-index*.json`, `scripts/live-browser*.js`, `scripts/modern-screenshot.umd.js`.
- Why: critique and audit call the launcher for `context`, `critique-storage slug|write|trend`, `audit-storage write`, `detect` and `live-server`. The launcher has no engine next to it and downloads a native binary (`impeccable-<os>-<arch>`, engine 0.1.22) from `https://github.com/pbakaus/impeccable/releases/download` on first run. Under MOADIX the sandbox allows only a fixed network list, so that download would fail, and running an unvetted downloaded binary is outside what a vendored skill should do. The storage helpers also write to `.impeccable/`, which phase 6 may not write. The skill already documents a "Launcher unavailable" fallback and critique.md already allows a missing detector ("unless `impeccable detect` is missing"), so critique and audit run in that mode.
- Category: adaptation.

### 3. Launcher-dependent steps in the references (adaptation)

- `reference/critique.md`, Setup step 2: "**Confirm the target slugs cleanly**: … `impeccable critique-storage slug "<resolved-path-or-url>"` … never hand-write a slug. If this exits non-zero, skip persistence and trend …" → hand-derive a short kebab-case slug, used only for the saved copy's filename.
- `reference/critique.md`, Assessment B: added a **MOADIX** paragraph: `impeccable detect` and `live-server` are missing; report "deterministic scan unavailable (launcher not vendored)", skip CLI scan and overlay injection, continue with screenshots and manual review.
- `reference/critique.md`, Deliver the Report: "If the report exists only in `.impeccable/critique/` …" → "`design/reviews/`"; "continues with the trend line and the close" → "the saved-path line and the close".
- `reference/critique.md`, Persist the Snapshot: steps 1–5 ("write it to `.impeccable/critique/` … so `/impeccable polish` can pick up …", temp file, `IMPECCABLE_CRITIQUE_META=… impeccable critique-storage write …`, delete temp file, `critique-storage trend`, "Trend for `<slug>` …" line) → write the copy to `design/reviews/critique-<slug>-<YYYY-MM-DD>.md` with a short score header, then one "Wrote design/reviews/<filename>." line; step 6 "Close the run" kept, minus "…and leaves `/impeccable polish` with no priorities to inherit"; "Do not show the user the helper's JSON output; only the human-readable trend line and the written path." → "Show the user only the written path."
- `reference/audit.md`, Implementation Integrity: added a **MOADIX** paragraph: `impeccable detect` (incl. `--cdp`) is missing; say so and score from source review and screenshots.
- `reference/audit.md` and `reference/audit.native.md`, Save the Report: "…to a temp file, then run `.claude/skills/impeccable/scripts/impeccable audit-storage write "<resolved target, or . …>" <temp-file>` and delete the temp file. The helper prints the path … `REPORTS OFF:` …" → write it to `design/reviews/audit-<slug>-<YYYY-MM-DD>.md` and mention the path.
- Category: adaptation.

### 4. Release verdict in the score bands (ship)

- File: `reference/critique.md`, Heuristics Score Summary table
- Original: `| 36–40 | Excellent | Minor polish only; ship it |`
- Replacement: `| 36–40 | Excellent | Minor polish only |`
- Category: ship.

### 5. Offer to run the fixing commands after the report (auto-advance)

- Files: `reference/critique.md` (Recommended Actions), `reference/audit.md` and `reference/audit.native.md` (Recommended Actions)
- Original: "After presenting the summary, tell the user: > You can ask me to run these one at a time, all at once, or in any order you prefer. > Re-run `/impeccable critique` [`/impeccable audit`] after fixes to see your score improve."
- Replacement: "After presenting the summary, stop here and report what you produced. These are recommendations for the operator: do not run them or edit the UI yourself. The operator decides what happens next (MOADIX gate)."
- Why: the follow-up hands the agent on to commands that edit UI (not vendored; under MOADIX, findings only).
- Category: auto-advance.

Kept on purpose: the "Ask the User" questions in critique.md (a user checkpoint), the recommended-command lists (recommendations for the operator, not invoked), and audit's "Implementation Integrity Verdict" / "Platform Conformance Verdict" (a pass/fail finding about the code, not an approval of the phase).
