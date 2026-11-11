# Finalize: Retrospective Document

Phase 5. Finalize the retrospective. One write: the retrospective document. This skill does not write `sprint-status.yaml` (MOADIX removed that step; see MOADIX-CHANGES.md).

## The retrospective document

This document is the run's working artifact: it is created as a skeleton once the epic is fixed and filled as each phase completes, so Phase 5 finalizes rather than writes it from scratch. It lives at `{implementation_artifacts}/epic-{{epic_number}}-retro-{date}.md`, in `{document_output_language}`, as readable markdown; ensure `{implementation_artifacts}` exists. In stories mode it lives at `{spec-folder}/RETROSPECTIVE.md` instead — a fixed name, so a resumed run finds it — and carries the same frontmatter without `epic`, which the folder already names.

Open the document with YAML frontmatter a machine can read without parsing the prose. The `verdict` is a recommendation for the operator; it approves nothing and gates nothing (MOADIX gate):

```
---
epic: {{epic_number}}
date: {date}
verdict: accepted | accepted-with-open-items | rejected
criteria: declared | profiled
headless: true | false
---
```

Keep `verdict` in sync with the Acceptance verdict section below.

Sections:

- **Epic summary** — which epic, the diff range, stories completed, any stories still unfinished (`pending_stories`) that the user accepted retro-ing over, the evidence inventory (what was available, what was missing). Unfinished stories force the machine acceptance verdict to **rejected** (see `references/acceptance-verdict.md`).
- **Findings** — grouped by aggregate view and by lens, each with its source reference and disposition (fix now / defer / accept). This is the record; do not summarize away the provenance.
- **Behavior verification** — what was exercised end to end and what was observed, or an explicit note that runtime behavior was not exercised.
- **Previous-retro follow-through** — if a prior retro exists, whether its action items landed, with evidence, and the selector the operator would need to act on each (`references/acceptance-verdict.md` specifies what to record).
- **Action items** — the routed fix-now items and process lessons, each with an owner. Note which are proposed remediation or spec reconciliations awaiting human application.
- **Acceptance verdict** — accepted / accepted-with-open-items / rejected, whether the criteria were declared or profiled, and the evidence behind the call.
- **Open questions** — what a human answer would materially change, and anything the analyses could not resolve.
- **Assumptions** — in headless runs, every choice made without the user: which epic was selected (invocation or auto-detect), the `detect-epic --epic <N>` (or unflagged) result including any non-empty `pending_stories`, a machine **rejected** verdict forced by unfinished stories or rendered with no human decision, each proposed item. Omit in interactive runs — an interactive run records the same facts where the user confirmed them, in Epic summary.

Do not state time estimates anywhere in the document.

## Sprint status and action items

Do not edit `sprint-status.yaml` or any story artifact. The proposed action items (each with an owner and a `ref` back to this document) and any status transitions the Previous-retro follow-through argues for stay in this document; the operator decides which to apply.

## Finish

Report where the document was saved, the verdict, and the action-item count. Then, if `{workflow.on_complete}` is non-empty, follow it as the final terminal instruction before exiting.

Stop here and report what you produced. The operator decides whether the phase is approved (MOADIX gate).
