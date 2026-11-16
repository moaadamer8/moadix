# Standing instructions per product (proposed in 0.6.4, built in 0.7.0)

> **Standing instructions cannot change any gate rule.** They never relax or override a check, a path map, a waiver rule, a verifier's brief or an operator command, and the gate never reads them when it decides. They are the operator's standing guidance to the agent, nothing more.

Status: **built in 0.7.0 as proposed** (Addition 3 of the 0.6.4 review). The same statement heads every `.sdlc/standing.md` the gate writes.

## The problem

The operator gives standing instructions about a product, such as "`reference/` is never modified" or "phase 0 detail that a story can settle goes to phase 2". Today they have nowhere to live:

- The agent's memory directory (`~/.claude/projects/…/memory/`) is blocked by the managed policy for reads and writes.
- `CLAUDE.md` in the product is a file the agent can edit, so an instruction there is not the operator's on the record.
- Chat is lost at the end of the session.

As a result, every new session repeats the same correction, and nothing proves which version of an instruction was in force when.

## How it works

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

## What ADOPT checks (gate/adopt.py)

- The file is UTF-8 text, at most 4 KB.
- Every line is blank, a heading, `- SI-n: <instruction> (since YYYY-MM-DD)` or `- SI-n: withdrawn <why>`.
- No ID appears twice.
- Every ID in the adopted file is still there. An instruction is never deleted or renumbered: it is marked withdrawn.
- The gate writes `.sdlc/standing.md` as its own header followed by the proposal, and the ADOPT line records the result's sha256.

## Mechanical binding

Not built. A standing instruction is text only. Making one bind the agent, for example turning "never write under `reference/`" into a path-map deny, stays a path-map change through the maintainer.
