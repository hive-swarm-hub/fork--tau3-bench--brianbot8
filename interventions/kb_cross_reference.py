"""Intervention — kb_cross_reference.

Hypothesis: τ-Banking's KB is densely interlinked (lost-card → lost-card
protocol → identity verification → unlock-then-call), but the agent
typically reads one document and stops, missing the link graph it just
crossed. When it later hits a wall, it grep-restarts from scratch instead
of following references that already appeared in retrieved text.

This plugin scans every shell tool result for *.md filename mentions and
short quoted "see also" / "per" anchors, then appends a single line to
the tool result content listing up to 3 cross-references the agent has
not yet inspected. Persistent de-dup via a single set on the agent's
state so the same nudges don't repeat.

Two ways to use:

1. INLINE (recommended for minimal wiring — no dispatcher required):

       from interventions.kb_cross_reference import annotate

       # In your CustomAgentState, add:
       #   kb_surfaced_refs: set[str] = Field(default_factory=set)

       # In your _track_state, inside the per-tool-message loop:
       #   log = annotate(tm, pending, state)
       #   if log is not None and hasattr(state, "intervention_log"):
       #       state.intervention_log.append(log)

2. REGISTRY (if your agent has a tool_result dispatcher):

       from interventions import REGISTRY
       from interventions import kb_cross_reference  # noqa: F401  (registers)

       # Your dispatcher iterates REGISTRY.for_hook("tool_result") and
       # invokes intv.apply(HookContext(incoming=tm, state=ctx_state,
       # meta={"pending": pending}))

Design constraints:
- NO `_NNNN` tool names hardcoded. Only filename references and short
  quoted anchor text — both are pure structural artifacts of the KB.
- Operates on tool results from shell-class tool calls only (skip
  log_verification, unlock_*, call_discoverable_agent_tool, etc.).
- Caps surfaced refs at 3 per turn; persistent de-dup via the
  ``kb_surfaced_refs: set[str]`` attribute (or dict key) on ``state``.
- Pure regex; no LLM call, no offline pre-extraction.
"""

from __future__ import annotations

import re
from typing import Any, Optional

from interventions import REGISTRY, HookContext, HookResult, Intervention


_MD_FILE_RE = re.compile(r"(?<![\w/])([\w./-]+\.md)\b")
_REFERENCE_ANCHOR_RE = re.compile(
    r"(?i)\b(?:see\s+also|see|per|refer\s+to|under|in)\s+[`'\"]([\w .,/\-]+?)[`'\"]"
)

_SHELL_TOOL_NAMES = frozenset({
    "shell", "execute_shell", "execute_command", "bash", "run_shell",
})

_MAX_REFS_PER_TURN = 3
_STATE_ATTR = "kb_surfaced_refs"


def extract_kb_refs(content: str) -> list[str]:
    """Pull markdown filenames and short quoted anchor targets from doc text.

    Order is preserved (markdown filenames first, then anchors); duplicates
    within the same content are dropped. Caller decides about cross-doc
    de-duplication.
    """
    refs: list[str] = []
    seen: set[str] = set()
    for m in _MD_FILE_RE.finditer(content):
        ref = m.group(1).strip()
        if ref and ref not in seen:
            seen.add(ref)
            refs.append(ref)
    for m in _REFERENCE_ANCHOR_RE.finditer(content):
        ref = m.group(1).strip()
        if ref and len(ref) < 60 and ref not in seen:
            seen.add(ref)
            refs.append(ref)
    return refs


def _read_surfaced_set(state: Any) -> set[str]:
    """Get the persistent surfaced-refs set from state (attr or dict-like).

    Falls back to a fresh per-call set if the state doesn't accept the
    attribute (de-dup degrades from cross-turn to in-call).
    """
    if state is None:
        return set()
    if isinstance(state, dict):
        surfaced = state.get(_STATE_ATTR)
        if surfaced is None:
            surfaced = set()
            state[_STATE_ATTR] = surfaced
        return surfaced
    surfaced = getattr(state, _STATE_ATTR, None)
    if surfaced is None:
        surfaced = set()
        try:
            setattr(state, _STATE_ATTR, surfaced)
        except Exception:
            pass
    return surfaced


def annotate(tool_message: Any, pending: Optional[dict], state: Any) -> Optional[dict]:
    """Public API. Annotate a shell tool result with up to 3 unread KB refs.

    Mutates ``tool_message.content`` in place when a meaningful annotation
    can be added; otherwise leaves it untouched. State is read/written via
    the ``kb_surfaced_refs`` attribute (or dict key) so de-dup persists
    across turns.

    Args:
        tool_message: tau2 ToolMessage. ``.content`` must be a non-empty str
            to be eligible.
        pending: dict like ``{"name": "shell", "args": {...}}`` from the
            agent's pending_calls table for this tool_message.id, or None.
            Non-shell tool calls are skipped.
        state: an object (e.g. CustomAgentState) or dict on which the
            persistent ``kb_surfaced_refs: set[str]`` lives.

    Returns:
        A log dict on annotation, else None. Caller decides whether to
        retain logs (e.g. ``state.intervention_log.append(log)``).
    """
    if tool_message is None:
        return None
    pending = pending or {}
    if pending.get("name") not in _SHELL_TOOL_NAMES:
        return None
    content = getattr(tool_message, "content", None)
    if not isinstance(content, str) or not content.strip():
        return None

    refs = extract_kb_refs(content)
    if not refs:
        return None

    surfaced = _read_surfaced_set(state)
    new_refs = [r for r in refs if r not in surfaced][:_MAX_REFS_PER_TURN]
    if not new_refs:
        return None
    surfaced.update(new_refs)

    suffix = (
        "\n\n[kb_cross_reference] Cross-references appearing in this output "
        "that you have not yet inspected: "
        + ", ".join(new_refs)
        + ". Consider reading the most relevant one before searching elsewhere."
    )
    try:
        tool_message.content = content + suffix
    except Exception:
        return {
            "intervention": "kb_cross_reference",
            "case": "annotated_pending_apply",
            "refs_surfaced": new_refs,
            "doc_len": len(content),
            "suffix": suffix,
        }
    return {
        "intervention": "kb_cross_reference",
        "case": "annotated",
        "refs_surfaced": new_refs,
        "doc_len": len(content),
    }


def _registry_apply(ctx: HookContext) -> Optional[HookResult]:
    """REGISTRY-style hook entry point.

    For agents that route via REGISTRY.for_hook("tool_result"). The
    dispatcher is expected to populate ctx.incoming (ToolMessage),
    ctx.meta["pending"], and ctx.state (a dict-like or object with
    ``kb_surfaced_refs``).
    """
    log = annotate(ctx.incoming, (ctx.meta or {}).get("pending"), ctx.state)
    if log is None:
        return None
    if log.get("case") == "annotated_pending_apply" and log.get("suffix"):
        return HookResult(annotation=log["suffix"], log=log)
    return HookResult(log=log)


REGISTRY.register(Intervention(
    id="kb_cross_reference",
    name="kb-cross-reference",
    hook="tool_result",
    target_cluster="retrieval",
    author="task-maintainer",
    description=(
        "After every shell tool result, scan for markdown filenames and "
        "short quoted 'see also' / 'per' anchors. Append a single line "
        "listing up to 3 cross-references the agent has not yet inspected. "
        "Persistent de-dup via state.kb_surfaced_refs (set[str]). No tool "
        "names hardcoded; relies entirely on text the agent retrieved."
    ),
    status="active",
    apply=_registry_apply,
))
