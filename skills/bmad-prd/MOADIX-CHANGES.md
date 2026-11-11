# MOADIX changes: bmad-prd

- Upstream: https://github.com/bmad-code-org/BMAD-METHOD (tag v6.12.4)
- Commit: `bab9082c3e884e0d72c759bcd1a6d90bcc01be84`
- Path: `src/bmm-skills/plan/bmad-prd`
- Licence: MIT, `Copyright (c) 2025 BMad Code, LLC`, with the BMad trademark notice (copied as `LICENSE`).
- Also includes EARS patterns from cc-sdd (https://github.com/gotalab/cc-sdd @ `e2a0c671aef37a482404905b409ab5c27092b25b`, `tools/cc-sdd/templates/shared/settings/rules/ears-format.md`, MIT, `Copyright (c) 2025 gotalab`); its licence is `LICENSE.cc-sdd`.
- Vendored: 2026-11-11. Everything in the upstream directory was copied except `scripts/tests/` (test suites are not shipped). Files not listed below are verbatim.

## Changes

| File | Original text | Replacement | Category |
| --- | --- | --- | --- |
| (dir) | (upstream has no `scripts/tests/`) | nothing omitted | adaptation |
| (dir) | (none) | added `LICENSE.cc-sdd` (copy of cc-sdd's LICENSE) | adaptation |
| SKILL.md Finalize step 7 | "**Close.** Set `prd.md` frontmatter `status: final` and `updated` to `{date}` so future invocations distinguish this PRD from in-progress drafts. Record finalization via `… memlog.py append … --type event --text "PRD finalized"`." | "**Close.** Set `prd.md` frontmatter `updated` to `{date}`. Record the hand-back via `… memlog.py append … --type event --text "PRD ready for operator review"`." | mark-done |
| SKILL.md Finalize step 7 | "Common next: `bmad-ux`, `bmad-architecture`, `bmad-create-epics-and-stories`; invoke `bmad-help` for authoritative routing." | removed | auto-advance |
| SKILL.md Finalize | (no step 9) | new step 9: "Stop here and report what you produced. The operator decides whether the phase is approved (MOADIX gate)." | auto-advance |
| references/headless.md (General) | "`complete` = stands on its own;" | "`complete` = no open questions remain (the operator still reviews it; only the MOADIX gate approves a phase);" | self-approve |
| assets/prd-template.md §4 Features, after FR-1 "Consequences (testable)" | (none) | Added cc-sdd's EARS guidance as italic template guidance, with an HTML-comment attribution line: overview, the five primary patterns with use and example, combined patterns, subject selection, quality criteria. Text is cc-sdd's, reflowed from headings into list items so it sits inside the FR block. | adaptation |
| assets/prd-template.md (EARS block) | cc-sdd: "All acceptance criteria should be written in the target language configured for the specification (for example, `spec.json.language` / `{{LANG_CODE}}`)." | dropped (cc-sdd's spec.json localisation; the PRD is written in `{document_output_language}`) | adaptation |
| assets/prd-template.md (EARS block) | cc-sdd heading "# EARS Format Guidelines" | "*EARS format for the testable consequences (acceptance criteria).*" | adaptation |

Side effect, left as is: On Activation step 5 offers to resume prior runs whose `prd.md` `status` is not `final`. Since no run is set to `final` now, every earlier run is offered for resume.

Left as is: the misroute suggestions in the greeting (step 4) and the `bmad-party-mode` / `bmad-advanced-elicitation` mentions only point the user at other skills; the user decides, and the MOADIX phase manifest decides whether such a skill may load. `{workflow.external_handoffs}` and `{workflow.on_complete}` (empty by default) are operator configuration.

## Known dependencies

- BMad core shared scripts, referenced as `{project-root}/_bmad/scripts/...` and not bundled here (left unchanged on purpose): `memlog.py` (init, append), `resolve_customization.py`, `resolve_config.py`. Without a BMad core install these calls fail and the skill falls back to the defaults it describes.
- Validate intent opens the HTML report with `open`/`xdg-open`; in a sandbox this fails harmlessly (the reference already says to report the path instead).
- `{workflow.finalize_reviewers}` and `{workflow.doc_standards}` may name other skills (e.g. `bmad-review`); if one is not allowed in the phase, the rubric walker still runs.
