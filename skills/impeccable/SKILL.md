---
name: impeccable
description: "Use to critique or audit a frontend: websites, landing pages, dashboards, app UI, components, native iOS/Android screens, or a design system (DESIGN.md). Produces findings; does not edit UI."
version: 4.8.2
user-invocable: true
argument-hint: "[audit|critique] [target]"
license: Apache 2.0
---
<!-- Modified by MOADIX (2026-11-11): trimmed to the critique and audit commands, launcher scripts not vendored, findings-only (no UI edits). See MOADIX-CHANGES.md. Original: https://github.com/pbakaus/impeccable@c1e0e5492fbb524f5df84d635ecfae7dc438ec45 -->

This skill gives you the tools and permission to make design that earns the name out-of-distribution craft. Work as an award-winning design director would: production-grade code, a clear POV, a deep grasp of what the client and its users need, and exceptional craft.

Core principles:
- Finish the job. No hedging, no shortcuts: the deliverable is complete, except assets the user must provide.
- Scale ambition to the surface's mode (see Modes). Persuade and Experience get full commitment: bold, distinct work with a point of view. On Operate and Read, ambition shows as precision and restraint, and patterns the visitor already knows earn their place.
- Verify by looking at the rendered result at the sizes it ships at, and batch the checks: fix what one look shows before looking again, rather than screenshotting after every tweak.

## MOADIX usage

This vendored copy carries only the `critique` and `audit` commands. Both produce findings: they do not edit UI, tokens, copy or DESIGN.md, and they do not run any other Impeccable command. The design reviewer writes findings; changes to the interface are made later, by whoever the operator assigns. Under MOADIX this skill runs in phase 6 (UX), which may write only `sdlc/06-*.md` and `design/**`, so a saved copy of a report goes under `design/reviews/`.

The `scripts/` launcher is not vendored (it downloads an engine binary on first run, which the MOADIX sandbox's network list does not allow). Every `impeccable <verb>` command named in this skill or its references is therefore unavailable: take the **Launcher unavailable** path in Setup, and report the detector as "deterministic scan unavailable (launcher not vendored)".

## Setup

1. The context launcher is not available under MOADIX (see MOADIX usage); go straight to **Launcher unavailable** below. When the project's platform is native (`ios` / `android` / `adaptive`), read [reference/ios.md](reference/ios.md) and/or [reference/android.md](reference/android.md) yourself, since the launcher would have loaded them.
2. Load the request's playbook: [reference/critique.md](reference/critique.md) for `critique`, [reference/audit.md](reference/audit.md) for `audit` (native: [reference/audit.native.md](reference/audit.native.md)). Inspect target and incumbent visual truth before assessing. When the app cannot run, start with committed visual-regression goldens or screenshot fixtures; verify target and freshness against current tokens, CSS, components, or assets, resolve conflicts, and compare theme/variant captures.

**Launcher unavailable:** On refusal or failure, send a separate message **before the next tool call**: “Context loading did not run; I’ll read the existing project context directly.” Then read existing PRODUCT.md and DESIGN.md without inventing missing context, follow step 2, and continue through permitted tools.

## Modes

The mode names what the visitor's success looks like on this surface.

- **Persuade:** the visitor decides and acts; design is the product. Landing pages, marketing, campaigns, pricing. Earn attention and action. Ship real imagery when the brief needs it; follow the committed world, not category habit.
- **Operate:** the visitor completes a task. App UI, dashboards, editors, admin, settings, tools. Scanability, consistency, native expectations, and the real usage scene outrank expression. Brand lives in precise details.
- **Read:** the visitor understands something. Docs, articles, guides, help, changelogs. Structure for comprehension, then make the reading experience worth staying in.
- **Experience:** the visitor is inside the work itself. Portfolios, galleries, showcases. Let the artifact lead from the first viewport; the interface recedes.

Choose the mode from the requested surface, not the product. A tool's landing page is still Persuade; a fashion house's documentation is still Read; a docs index is Read, not Persuade.

## Commands

| Command | Category | Description | Reference |
|---|---|---|---|
| `critique [target]` | Evaluate | UX design review with heuristic scoring | [reference/critique.md](reference/critique.md) |
| `audit [target]` | Evaluate | Technical quality checks (a11y, perf, responsive) | [reference/audit.md](reference/audit.md) · native: [reference/audit.native.md](reference/audit.native.md) |

Routing:

- **No argument:** ask the user whether they want `critique` or `audit`, and on which target; never auto-run a command.
- **Explicit or clearly implied request to run a command:** load its reference (native variant on native platforms) and follow it. Ask once if two commands fit.
- **Otherwise:** this copy only critiques and audits. Say so, and offer `critique` or `audit` of the surface in question.
