#!/usr/bin/env python3
"""Clear the current project's learnings queue. Helper for slash commands.

MOADIX: clears docs/retro/learnings-queue.jsonl in the product repo. Run it
only after the operator has decided every queued item, or has said to discard
them. With --keep "1,4" (1-based positions as read_queue.py lists them) the
named entries stay queued, for items the operator deferred.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib.reflect_utils import ensure_utf8_io, load_queue, save_queue  # noqa: E402

if __name__ == "__main__":
    ensure_utf8_io()
    parser = argparse.ArgumentParser(description="Clear docs/retro/learnings-queue.jsonl")
    parser.add_argument("--repo", default=None, help="Product repo root (default: $CLAUDE_PROJECT_DIR or cwd)")
    parser.add_argument("--keep", default="", help="Comma-separated 1-based positions to keep queued")
    args = parser.parse_args()
    items = load_queue(args.repo)
    keep = {int(x) for x in args.keep.split(",") if x.strip().isdigit()}
    kept = [it for n, it in enumerate(items, 1) if n in keep]
    save_queue(kept, args.repo)
    print(f"Cleared {len(items) - len(kept)} queued learning(s); {len(kept)} kept.")
