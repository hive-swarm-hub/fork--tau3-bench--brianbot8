"""Wrapper around upstream interventions.kb_cross_reference.annotate.

Diagnosis from #144: the upstream plugin fires correctly (~10x per task)
but its surfaced refs are dominated by alphabetical-first .md filenames
from `ls` output. Those refs are topically irrelevant — they're
directory-listing noise, not intentional cross-references.

This wrapper forwards to the upstream `annotate` only when the shell
command is content-reading (cat/grep/head/etc.), filtering out
listing commands (ls/find/etc.) before any regex runs. Same call
signature as the upstream function.
"""

from __future__ import annotations

from typing import Any, Optional

from interventions.kb_cross_reference import annotate as _upstream_annotate


# Commands that READ the content of a (presumably already-located) file.
# These outputs contain prose where intentional cross-refs ("see also `X.md`")
# are likely meaningful. Anything else (ls, find, tree, wc, stat) is
# structural metadata about the corpus, where the regex picks up alphabetic
# noise instead of semantic links.
_CONTENT_READING_COMMANDS = (
    "cat", "grep", "egrep", "fgrep", "head", "tail",
    "less", "more", "awk", "sed",
)


def _first_command(cmd: str) -> str:
    """Return the first whitespace-delimited token's basename.

    Handles `ls`, `/usr/bin/ls`, `LC_ALL=C ls -la`, `cat foo.md | grep X`
    — in the pipeline case the FIRST command wins (cat), which is
    appropriate for a content-reading filter.
    """
    if not cmd:
        return ""
    # Strip leading env assignments like `LC_ALL=C ls -la`.
    parts = cmd.split()
    while parts and "=" in parts[0] and not parts[0].startswith("/"):
        parts = parts[1:]
    if not parts:
        return ""
    head = parts[0]
    # Take basename in case of an absolute path.
    return head.rsplit("/", 1)[-1].lower()


def annotate(tool_message: Any, pending: Optional[dict], state: Any) -> Optional[dict]:
    if not pending:
        return None
    args = pending.get("args") or {}
    cmd = (args.get("command") or args.get("cmd") or args.get("input") or "")
    if isinstance(cmd, (list, tuple)):
        cmd = " ".join(str(p) for p in cmd)
    cmd = str(cmd).strip()
    if not cmd:
        return None
    first = _first_command(cmd)
    if first not in _CONTENT_READING_COMMANDS:
        return None
    return _upstream_annotate(tool_message, pending, state)
