---
name: reflect-queue
description: Learnings queue for the MOADIX retro. During any phase, append each operator correction ("no, use X", "actually...", "remember:") to docs/retro/learnings-queue.jsonl; at the retro (phase 12), review the queue with the operator one item at a time and write only the learnings they agree to. Use when the operator corrects you, says "remember this", or when running the retro.
---

# Reflect Queue - Learn From Corrections

A two-stage system that helps Claude Code learn from user corrections.

## How It Works

**Stage 1: Capture (explicit, during any phase)**
When the operator corrects you ("no, use X", "actually...", "use X not Y", "remember: ...") or rejects a tool call with guidance, append it to the queue yourself:

```bash
python3 -I "<this skill's directory>/scripts/capture_learning.py" --text "<the operator's words, verbatim>" --note "<what it applies to>" --phase "<current phase label>"
```

The queue is `docs/retro/learnings-queue.jsonl` in the product repo, one JSON object per line. Capture only; do not edit CLAUDE.md or any doc at capture time. If you cannot run the script, append one line with the same fields yourself (`type`, `message`, `timestamp`, `project`, `patterns`, `confidence`, `sentiment`, `decay_days`, optional `note`, `phase`).

**Stage 2: Process (with the operator, at the retro)**
At the retro, review the queued learnings with the operator. Each learning is written only after the operator agrees to that one item.

## Correction Detection Patterns

High-confidence corrections:
- Tool rejections (user stops an action with guidance)
- "no, use X" / "don't use Y"
- "actually..." / "I meant..."
- "use X not Y" / "X instead of Y"
- "remember:" (explicit marker)

`capture_learning.py` runs the same detector to set `type`, `patterns` and `confidence`. Text it does not recognise is still queued, as type `manual`, because you only call it after judging the text to be a correction.

## Learning Destinations

Only paths the agent may always write in the product repo:

- `./CLAUDE.md` - Project-specific learnings (conventions, tools, structure)
- `docs/retro/learnings.md` - Learnings the operator wants recorded but not loaded into every session
- Another file under `docs/` that the operator names

Never write a learning under `~/.claude/` or `.claude/` (user memory, rules, settings): MOADIX denies those paths, and the operator chooses the destination.

## Processing the Queue (retro)

### Step 1: Load

```bash
python3 -I "<this skill's directory>/scripts/read_queue.py"
```

Add all queue items to the working list. If the queue is empty, read the phase notes the session kept (for example `docs/retro/` or the phase documents) for corrections that were not captured, and offer them as candidates. If there are none, say so and stop.

### Step 2: Review each item yourself first

For each item: is it a reusable learning, or noise (a one-off task request, a question, praise with no referent)? Rewrite each keeper as one clean, actionable statement. Check `./CLAUDE.md` and `docs/retro/learnings.md` for an existing entry that says the same thing, and note its line number.

Items captured in a different project (`item.project` is not this repo) are shown with a warning: "FROM DIFFERENT PROJECT".

### Step 3: Present the summary

```
════════════════════════════════════════════════════════════
LEARNINGS SUMMARY — [N] items found
════════════════════════════════════════════════════════════

┌────┬─────────────────────────────────────────┬──────────────────────────┐
│ #  │ Learning                                │ Proposed destination     │
├────┼─────────────────────────────────────────┼──────────────────────────┤
│ 1  │ Use DB for persistent storage           │ ./CLAUDE.md              │
│ 2  │ Backoff on actual errors only           │ docs/retro/learnings.md  │
│ ...│ ...                                     │ ...                      │
└────┴─────────────────────────────────────────┴──────────────────────────┘
```

### Step 4: Ask the operator about each item

One item at a time, show the learning card and wait for the operator's answer:

```
════════════════════════════════════════════════════════════
LEARNING [N] of [TOTAL]
════════════════════════════════════════════════════════════
Original message:
  "[the operator's original text]"

Proposed addition ([destination]):
┌──────────────────────────────────────────────────────────┐
│ ## [Section Name]                                        │
│ - [Exact bullet point that will be added]                │
└──────────────────────────────────────────────────────────┘

Duplicate check:
  ✓ None found
  OR
  ⚠️ SIMILAR in [file]:
     Line [N]: "[existing content]"

Write this? [y]es | [e]dit | [d]ifferent destination | [s]kip | [l]ater
════════════════════════════════════════════════════════════
```

Never write an item the operator has not answered "yes" to (after any edit they asked for). Do not offer an "apply all" shortcut. If the operator stops partway, keep the undecided items queued.

### Step 5: Write the agreed learnings

For each item the operator agreed to:
1. Read the destination file.
2. Use the Edit tool with a precise old_string; add new entries under the relevant section header (create the header if missing).
3. For a duplicate the operator chose to replace, edit that line instead of adding a new one.

Do not commit anything. The written files are part of the retro's output for the operator to review.

### Step 6: Clear the queue

Only after every item is decided (written, skipped, or kept for later):

```bash
python3 -I "<this skill's directory>/scripts/clear_queue.py" --keep "<positions the operator said to keep for later>"
```

If the operator says to discard the whole queue, show the count and a one-line preview of each item, ask "Are you sure? [y/n]", and run `clear_queue.py` only on "y".

### Step 7: Report

```
════════════════════════════════════════════════════════════
Learnings written: [N]
════════════════════════════════════════════════════════════
  ./CLAUDE.md                [N] entries
  docs/retro/learnings.md    [N] entries

  Skipped: [N]   Kept for later: [N]
════════════════════════════════════════════════════════════
```

Then stop. Whether the retro is accepted is the operator's decision (MOADIX gate).

## Viewing the Queue

To show the queue without processing it, run `read_queue.py` and print one line per item: confidence `[0.XX]`, the first 50 characters of the message, the pattern name in parentheses (`(manual)` when empty), and how long ago it was captured:

```
[0.85] "use gpt-5.1 not gpt-5" (use-X-not-Y) - 2 days ago
```

## Formatting Rules

- **Bullets, not prose**: Keep entries as single bullet points
- **Actionable**: "Use X for Y" not "X is better than Y"
- **Concise**: Max 2 lines per entry
- **Examples when helpful**: `(e.g., gpt-5.2 not gpt-5.1)`

## Section Headers

Use these standard headers:
- `## LLM Model Recommendations` — model names, versions
- `## Tool Usage` — MCP, APIs, which tool for what
- `## Project Conventions` — coding style, patterns
- `## Guardrails` — constraints and "don't do X" rules
- `## Common Errors to Avoid` — gotchas, mistakes
- `## Environment Setup` — venv, configs, paths

## Size Check

If CLAUDE.md exceeds 150 lines, tell the operator and suggest consolidating similar entries or moving some to `docs/retro/learnings.md`.

## Example Interaction

```
User: no, use gpt-5.1 not gpt-5 for reasoning tasks
Claude: Got it, I'll use gpt-5.1 for reasoning tasks.
        [runs capture_learning.py --text "no, use gpt-5.1 not gpt-5 for reasoning tasks"]

... later, at the retro ...

Claude: Found 1 learning queued. "Use gpt-5.1 for reasoning tasks"
        Proposed destination: ./CLAUDE.md
        Write this? [y]es | [e]dit | [d]ifferent destination | [s]kip | [l]ater
User: y
```
