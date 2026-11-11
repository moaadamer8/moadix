---
description: Tell the operator a phase is ready for review. The gate starts the phase's validators; this changes no gate state.
argument-hint: <phase>
---
Phase $ARGUMENTS is ready for review. Your work for it must be committed: the gate runs the phase's validators on the current commit (this command started them), and uncommitted changes mean they cannot run.

Tell the operator exactly this, then stop and wait:

"Phase $ARGUMENTS is ready for review. The gate is running its validators on the current commit. Type `APPROVE $ARGUMENTS <code>` with the current code from your authenticator app. `REVIEW $ARGUMENTS` shows the gate's results first if you want to see them."

Do not type, quote, suggest or guess an approval code. Only the operator's own message can record an approval.
