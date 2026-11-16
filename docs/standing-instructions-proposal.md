# Standing instructions per product: proposal (0.6.4, item 7)

Status: **proposal for the operator's review. Nothing here is built.**

## The problem

The operator gives standing instructions about a product, such as "`reference/` is never modified" or "phase 0 detail that a story can settle goes to phase 2". Today they have nowhere to live:

- The agent's memory directory (`~/.claude/projects/…/memory/`) is blocked by the managed policy for reads and writes.
- `CLAUDE.md` in the product is a file the agent can edit, so an instruction there is not the operator's on the record.
- Chat is lost at the end of the session.

As a result, every new session repeats the same correction, and nothing proves which version of an instruction was in force when.

## Proposal

| | |
|---|---|
| **Where** | `.sdlc/standing.md` in the product. It is gate-owned: the sandbox and the gate's hook already deny every agent write under `.sdlc/`. |
| **Who writes it** | The operator only, by the same route as the product settings. The agent drafts `.sdlc-proposals/standing.md` and the operator types `ADOPT <code>`, which `gate/adopt.py` already does for `product.yaml` and `coverage-overrides.yaml`. The ADOPT ledger line records its sha256. An operator may also edit the file in Terminal, but then the drift check (`adopt.drift`) reports it until it goes through ADOPT, so an unrecorded edit is visible. |
| **Format** | Markdown, at most 4 KB, one instruction per bullet: `- SI-n: <instruction> (since YYYY-MM-DD)`. IDs are never reused; an instruction that is withdrawn is marked `withdrawn`, as trace IDs are. |
| **Shown at session start** | `gate/session.py` (SessionStart) adds it to the session's context in full, under the heading "Operator's standing instructions for <product> (adopted at ledger seq N)". It is shown only when its digest matches the ADOPT line; on drift the session is told the file changed outside ADOPT and the text is not shown as the operator's. |
| **Shown to verifiers** | Not by default: a verifier's brief stays built from the documents only. A standing instruction that a critic must respect belongs in the phase's documents or a ruling (`DISCOVERY.md`, an ADR). |
| **STATUS** | One line: `standing instructions: N active (adopted at seq N)`. |

## Why there and not elsewhere

- **Not the memory directory.** Opening it would let the agent write its own standing orders. That is the reason it is blocked.
- **Not a machine-wide file** like the local overlay (`~/.config/moadix/`). Instructions are per product. A machine-wide layer could be added later, read the same way.
- **Not a new operator command carrying the text.** A message is capped at the checker's 512-character action, and editing a list through typed commands is clumsy. ADOPT already gives a reviewed, signed, digest-checked path.

## Open question

**Q1.** Should a standing instruction also be able to bind the agent mechanically, for example "never write under `reference/`" becoming a path-map deny? Recommended: not in this step. Text only, and a path rule stays a path-map change through the maintainer, as today.
