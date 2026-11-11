# MOADIX changes: bmad-deep-recon

- Upstream: https://github.com/bmad-code-org/BMAD-METHOD (tag v6.12.4)
- Commit: `bab9082c3e884e0d72c759bcd1a6d90bcc01be84`
- Path: `src/core-skills/bmad-deep-recon`
- Licence: MIT, `Copyright (c) 2025 BMad Code, LLC`, with the BMad trademark notice (copied as `LICENSE`).
- Vendored: 2026-11-11. Everything in the upstream directory was copied except `scripts/tests/` (test suites are not shipped). Files not listed below are verbatim.

## Changes

| File | Original text | Replacement | Category |
| --- | --- | --- | --- |
| (dir) | `scripts/tests/test_recon_kit.py` | not copied | adaptation |
| references/synthesis.md (last paragraph) | "Update the frontmatter (`status: complete`, `updated`, and the verified/unverified counts …)" | "Update the frontmatter (`updated`, and the verified/unverified counts …)". `research.md` keeps `status: draft` from the template. | mark-done |
| references/finalize.md step 6 | "… and that Refresh/Deepen handle it. Invoke `bmad-help` to suggest the next step." | "… and that Refresh/Deepen handle it." | auto-advance |
| references/finalize.md | (no step 8) | new step 8: "Stop here and report what you produced. The operator decides whether the phase is approved (MOADIX gate)." | auto-advance |

Left as is: the headless JSON example in SKILL.md (`"status": "complete"`) is the run's report to its caller that the run finished, not an approval of the phase.

## Known dependencies

- BMad core shared scripts, referenced as `{project-root}/_bmad/scripts/...` and not bundled here (left unchanged on purpose): `memlog.py` (init, append), `resolve_customization.py`, `resolve_config.py`. Without a BMad core install these calls fail and the skill falls back to the defaults it describes.
- `scripts/recon_kit.py` (bundled; slug, tally, staleness, citations, escape-sources) needs `uv`.
- Run mode needs web access. `{workflow.external_handoffs}` and `{workflow.on_complete}` (empty by default) run operator-configured actions at finalize. Left in: operator configuration.
