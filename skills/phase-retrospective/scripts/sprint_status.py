# /// script
# requires-python = ">=3.10"
# dependencies = ["ruamel.yaml>=0.18"]
# ///
"""Detect the current retrospective epic from sprint-status.yaml (read only).

Prints ONLY JSON to stdout. Errors are emitted as JSON to stdout with a non-zero
exit code.

Modified by MOADIX (2026-11-11): the upstream ``update`` subcommand, which wrote
sprint-status.yaml (retro key status, action items), is removed together with the
helpers only it used. See MOADIX-CHANGES.md.
"""

import argparse
import json
import re
import sys
from collections.abc import Mapping

from ruamel.yaml import YAML

STORY_RE = re.compile(r"^(\d+)-\d+[a-z]?-")  # trailing [a-z]? matches split-story keys like 2-6a-...


def _load_yaml(path):
    yaml = YAML(typ="rt")
    yaml.preserve_quotes = True
    # Pin the emitter to the indentation the sprint-status template ships with.
    # Without this, ruamel re-dumps block sequences at its own default offset and
    # every write silently de-indents pre-existing, untouched action_items.
    yaml.indent(mapping=2, sequence=4, offset=2)
    # Pin the dump encoding too: `_dump_bytes` serializes into a BytesIO, so the
    # emitter -- not this module -- encodes the bytes that land in the user's
    # file. utf-8 is ruamel's current default, but the file is read back as
    # utf-8 unconditionally, so state it rather than inherit it.
    yaml.encoding = "utf-8"
    with open(path, "r", encoding="utf-8") as fh:
        data = yaml.load(fh)
    return yaml, data


def _emit(obj, code=0):
    sys.stdout.write(json.dumps(obj))
    sys.exit(code)


def _emit_error(message, code=1, restored=None):
    """Emit a failure on the JSON-only contract.

    ``restored`` is included only when the caller can speak to the state of the
    target file; ``retro-document.md`` teaches callers to read it, so a write-path
    failure must never omit it and a read-only subcommand must never invent it.
    """
    payload = {"ok": False, "error": message}
    if restored is not None:
        payload["restored"] = restored
    _emit(payload, code)


class JsonArgumentParser(argparse.ArgumentParser):
    """Emit argparse failures on the JSON-only stdout contract, not usage text.

    Every parser built from this class is constructed with ``add_help=False``.
    The override below covers ``error()``, but ``-h`` never reaches it: the
    built-in help action calls ``print_help()`` and ``exit(0)`` directly, which
    would put plain usage text on stdout with a zero exit and break the
    JSON-only contract for the machine consumer this script exists to serve.
    Removing the action instead of intercepting it keeps the fix to one keyword
    per parser and routes ``-h`` through the already-tested ``error()`` path as
    an ordinary unrecognized argument. The cost is that the ``help=`` strings
    are unreachable from the CLI; the skill's references carry the usage a
    human needs.
    """

    def error(self, message):
        _emit({"ok": False, "error": f"argument error: {message}"}, 2)


def _load_document(path, restored=None):
    """Load and shape-check the document, reporting every failure as JSON.

    Returns ``(yaml, data, dev)``. ``dev`` is the live ``development_status``
    mapping when the key exists, otherwise a detached empty mapping -- the key is
    never inserted into the document as a side effect of loading.
    """
    try:
        yaml, data = _load_yaml(path)
    except UnicodeDecodeError as exc:
        _emit_error(f"{path} is not valid UTF-8: {exc}", 1, restored)
    except OSError as exc:
        _emit_error(str(exc), 1, restored)
    except Exception as exc:  # noqa: BLE001 - report any parse error as JSON
        _emit_error(str(exc), 1, restored)

    if data is not None and not isinstance(data, Mapping):
        _emit_error("root document is not a mapping", 1, restored)

    dev = data.get("development_status") if data is not None else None
    if dev is None:
        dev = {}
    elif not isinstance(dev, Mapping):
        _emit_error("development_status is not a mapping", 1, restored)

    return yaml, data, dev


def _retro_status(dev, retro_key, restored=None):
    status_value = dev.get(retro_key)
    if status_value is not None and not isinstance(status_value, str):
        _emit_error(
            f"{retro_key} status must be a string or null",
            1,
            restored,
        )
    return status_value


def cmd_detect_epic(args):
    # detect-epic never writes, so it reports no "restored" key.
    _, _, dev = _load_document(args.file)

    done_stories = []
    max_epic = None
    # Every story key with its epic, in document order, so the pending list can
    # be scoped to whichever epic detection lands on without a second pass over
    # the mapping. Non-story keys (epic-2, epic-2-retrospective, ...) never enter
    # here, because STORY_RE does not match them.
    story_keys = []
    for key, value in dev.items():
        m = STORY_RE.match(str(key))
        if not m:
            continue
        epic_num = int(m.group(1))
        story_keys.append((epic_num, key, value))
        if value == "done":
            done_stories.append(key)
            if max_epic is None or epic_num > max_epic:
                max_epic = epic_num

    # Optional --epic aims the gate at a supplied number (the -H <epic> path)
    # instead of auto-picking the highest epic with a done story. Without it,
    # behavior is unchanged: detect, then scope pending_stories to that epic.
    if args.epic is not None:
        if args.epic < 1:
            _emit_error(
                f"invalid --epic {args.epic} (expected a positive integer)",
                1,
            )
        selected = args.epic
    else:
        selected = max_epic

    if selected is None:
        # Uniform shape: pending_stories is always present, even with no epic to
        # scope it to, so a caller can read it without branching on epic first.
        _emit(
            {
                "epic": None,
                "story_count": 0,
                "done_stories": done_stories,
                "pending_stories": [],
                "retro_key": None,
                "retro_status": None,
            }
        )

    # Scoped to the selected epic only -- deliberately unlike done_stories, which
    # spans the whole file. A pending story in some *other* epic is not this
    # retrospective's business.
    selected_keys = [
        (key, value) for epic_num, key, value in story_keys if epic_num == selected
    ]
    pending_stories = [key for key, value in selected_keys if value != "done"]

    retro_key = f"epic-{selected}-retrospective"
    retro_status = _retro_status(dev, retro_key)
    _emit(
        {
            "epic": selected,
            # An epic the file has never heard of returns the same empty
            # pending_stories as a finished one; story_count is the key that
            # separates "complete" from "nonexistent" (a typo'd --epic), so the
            # unfinished-story gate can refuse to read silence as done.
            "story_count": len(selected_keys),
            "done_stories": done_stories,
            "pending_stories": pending_stories,
            "retro_key": retro_key,
            "retro_status": retro_status,
        }
    )


def build_parser():
    parser = JsonArgumentParser(
        description="Detect the current retrospective epic (read only).",
        add_help=False,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_detect = sub.add_parser(
        "detect-epic",
        help=(
            "Find the highest epic with a done story and its retrospective "
            "status, or aim the same pending_stories gate at --epic N."
        ),
        add_help=False,
    )
    p_detect.add_argument("--file", required=True, help="Path to sprint-status.yaml")
    p_detect.add_argument(
        "--epic",
        type=int,
        default=None,
        help=(
            "Optional. Scope the response to this epic number instead of "
            "auto-detecting the highest epic with a done story. Orchestrators "
            "passing -H <epic> should pass the same number here so pending_stories "
            "covers the epic they are about to retro."
        ),
    )
    p_detect.set_defaults(func=cmd_detect_epic)

    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    if sys.platform == "win32":
        # Piped output on Windows defaults to a legacy code page, not UTF-8.
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    main()
