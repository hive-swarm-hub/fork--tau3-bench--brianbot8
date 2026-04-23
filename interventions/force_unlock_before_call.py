"""Intervention — force_unlock_before_call.

Trace evidence from brianbot8's earlier lite runs: a significant fraction of
P1 ("verification or unlock missing") failures are NOT catalog-coverage
problems. The agent correctly identifies the target tool name via KB
retrieval, then skips `unlock_discoverable_agent_tool` and proceeds
directly to `call_discoverable_agent_tool`. The call silently returns
reward 0 because the environment never accepted the unlock.

This intervention treats the unlock step as a structural pre-requisite:
when the agent attempts `call_discoverable_agent_tool(agent_tool_name=X)`
and X is NOT in state.unlocked_for_agent, rewrite the call into an
`unlock_discoverable_agent_tool(agent_tool_name=X)`. Next turn the LLM
(having seen the successful unlock in state) should re-issue the call.

Design constraints:
- NO specific `_NNNN` names in this file. Whatever the LLM proposes as
  `agent_tool_name` is treated as opaque data.
- Intervention only fires on `call_discoverable_agent_tool`. It does not
  touch base tools, reads, shell commands, or `unlock_discoverable_agent_tool`
  itself.
- The state-tracking (`unlocked_for_agent` populated from successful
  unlock results) is handled by the framework wiring in `agent.py`. This
  intervention just reads that set.
"""

from __future__ import annotations

from typing import Optional

from interventions import REGISTRY, HookContext, HookResult, Intervention

try:
    from tau2.data_model.message import ToolCall
except Exception:  # pragma: no cover
    ToolCall = None  # type: ignore[assignment]


def force_unlock_before_call(ctx: HookContext) -> Optional[HookResult]:
    """If the agent tries to call a discoverable tool it hasn't unlocked, rewrite to unlock first."""
    tc = ctx.tool_call
    if tc is None:
        return None
    if getattr(tc, "name", "") != "call_discoverable_agent_tool":
        return None

    args = getattr(tc, "arguments", None) or {}
    proposed_name = args.get("agent_tool_name")
    if not isinstance(proposed_name, str) or not proposed_name:
        return None

    unlocked = ctx.state.get("unlocked_for_agent", set()) or set()
    if proposed_name in unlocked:
        return None  # already unlocked — let the call through

    if ToolCall is None:
        # Fallback: block with a nudge if we can't construct a rewrite.
        return HookResult(
            drop=True,
            drop_note=(
                f"Cannot call `{proposed_name}` — it has not been unlocked yet. "
                f"First call unlock_discoverable_agent_tool(agent_tool_name='{proposed_name}'), "
                f"then retry the call next turn."
            ),
            log={"intervention": "force_unlock", "case": "block_no_rewrite", "proposed": proposed_name},
        )

    unlock_call = ToolCall(
        id=getattr(tc, "id", "") or "",
        name="unlock_discoverable_agent_tool",
        arguments={"agent_tool_name": proposed_name},
        requestor=getattr(tc, "requestor", "assistant"),
    )
    return HookResult(
        drop=True,
        replace_with=unlock_call,
        drop_note=(
            f"Rewriting: before I can call `{proposed_name}` I need to unlock it. "
            f"Unlocking now; next turn I'll re-issue the call via call_discoverable_agent_tool."
        ),
        log={"intervention": "force_unlock", "case": "rewrite_to_unlock", "proposed": proposed_name},
    )


REGISTRY.register(Intervention(
    id="force_unlock",
    name="force-unlock-before-call",
    hook="gate_pre",
    target_cluster="unlock_mechanics",
    author="brianbot8",
    description=(
        "When the agent proposes call_discoverable_agent_tool for a name not yet in "
        "state.unlocked_for_agent, rewrite the call to unlock_discoverable_agent_tool "
        "for the same name. Structural — no specific tool names hardcoded; reacts "
        "to whatever the LLM retrieved from the KB."
    ),
    status="active",
    apply=force_unlock_before_call,
))
