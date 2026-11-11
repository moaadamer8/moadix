#!/usr/bin/env python3
"""Detect and capture correction patterns from user prompts.

Cross-platform compatible (Windows, macOS, Linux).

MOADIX: upstream ran this as a UserPromptSubmit hook that read the prompt as
JSON on stdin. Under MOADIX a plugin cannot install hooks, so the agent runs it
explicitly when the operator corrects it during a phase:

    python3 -I scripts/capture_learning.py --text "<the operator's words>" \
        [--note "<what it applies to>"] [--phase <label>] [--repo <product repo>]

The text may also come on stdin when --text is omitted. The entry is appended
to docs/retro/learnings-queue.jsonl in the product repo. Nothing is written
anywhere else and nothing is committed. See ../MOADIX-CHANGES.md.
"""
import argparse
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib.reflect_utils import (  # noqa: E402
    ensure_utf8_io,
    append_to_queue,
    detect_patterns,
    create_queue_item,
    should_include_message,
    get_repo_root,
)


def main() -> int:
    """Main entry point."""
    ensure_utf8_io()
    parser = argparse.ArgumentParser(description="Append one learning to docs/retro/learnings-queue.jsonl")
    parser.add_argument("--text", default=None, help="The operator's words (default: read stdin)")
    parser.add_argument("--note", default=None, help="Optional context: what the correction applies to")
    parser.add_argument("--phase", default=None, help="Optional MOADIX phase label the correction came from")
    parser.add_argument("--repo", default=None, help="Product repo root (default: $CLAUDE_PROJECT_DIR or cwd)")
    args = parser.parse_args()

    prompt = args.text if args.text is not None else sys.stdin.read()
    prompt = (prompt or "").strip()
    if not prompt:
        print("[reflect] Nothing to capture: empty text.", file=sys.stderr)
        return 1

    # Filter out system content (XML tags, tool results, session continuations)
    if not should_include_message(prompt):
        print("[reflect] Not captured: text looks like system content, not the operator's words.", file=sys.stderr)
        return 1

    # Detect patterns
    item_type, patterns, confidence, sentiment, decay_days = detect_patterns(prompt)

    # MOADIX: the agent calls this only when it has judged the text to be a
    # correction or a "remember", so an undetected one is still queued, as
    # "manual" with a neutral confidence. The operator decides at the retro.
    if not item_type:
        item_type, patterns, confidence, sentiment, decay_days = ("manual", "", 0.60, "correction", 90)

    queue_item = create_queue_item(
        message=prompt,
        item_type=item_type,
        patterns=patterns,
        confidence=confidence,
        sentiment=sentiment,
        decay_days=decay_days,
        project=str(get_repo_root(args.repo)),
    )
    if args.note:
        queue_item["note"] = args.note
    if args.phase:
        queue_item["phase"] = args.phase

    path = append_to_queue(queue_item, args.repo)

    preview = prompt[:40] + "..." if len(prompt) > 40 else prompt
    # Plain ASCII: Windows consoles default to cp1252 and raise
    # UnicodeEncodeError on emoji, which swallowed this confirmation.
    print(f"[reflect] Learning captured: '{preview}' (confidence: {confidence:.0%}) -> {path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
