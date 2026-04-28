"""Intervention — retry_storm_limiter.

Targets the "retry storm" failure mode surfaced in feed post #102:
the agent finds a discoverable tool, calls it N times consecutively
with varying args, none accepted. One observed case showed 8 consecutive
identical-name calls in a single simulation — classic retry loop on
wrong args with no escalation.

This intervention tracks (tool_name, arg_signature) in state and blocks
the N+1-th duplicate with a nudge to reconsider args or escalate.

Design constraints:
- NO specific tool names in this file. Operates on whatever the LLM
  proposes. arg_signature is an opaque content hash — the code does not
  interpret argument values or reference specific tools.
- Only fires on `call_discoverable_agent_tool`. Non-discoverable tool
  retries (repeated `shell`, `log_verification`, etc.) are out of scope.
- Uses the intervention framework's `ctx.state` passthrough. Stores a
  per-simulation counter keyed by (tool_name, arg_hash).
- Threshold N=2 (block the 3rd duplicate call). Conservative: the
  agent gets two attempts with the same args before the nudge fires.
"""

from __future__ import annotations

import hashlib
import json as _json
from typing import Optional

from interventions import REGISTRY, HookContext, HookResult, Intervention


_RETRY_THRESHOLD = 2  # block the 3rd+ identical call
_STATE_KEY = "duplicate_call_counts"


def _arg_signature(args: object) -> str:
    """Stable hash of the call arguments. Opaque — does not interpret values."""
    if isinstance(args, str):
        # tau2 sometimes passes arguments as a JSON-encoded string; normalize
        try:
            args = _json.loads(args)
        except Exception:
            pass
    try:
        s = _json.dumps(args, sort_keys=True, default=str)
    except Exception:
        s = str(args)
    return hashlib.sha1(s.encode("utf-8", errors="replace")).hexdigest()[:12]


def retry_storm_limiter(ctx: HookContext) -> Optional[HookResult]:
    tc = ctx.tool_call
    if tc is None:
        return None
    if getattr(tc, "name", "") != "call_discoverable_agent_tool":
        return None

    args = getattr(tc, "arguments", None) or {}
    proposed_name = args.get("agent_tool_name") if isinstance(args, dict) else None
    inner_args = args.get("arguments") if isinstance(args, dict) else None
    if not isinstance(proposed_name, str) or not proposed_name:
        return None

    # Stash the counter dict on ctx.state so it persists across turns.
    counts = ctx.state.get(_STATE_KEY)
    if counts is None:
        counts = {}
        ctx.state[_STATE_KEY] = counts

    sig = _arg_signature(inner_args)
    key = (proposed_name, sig)
    prev = counts.get(key, 0)
    counts[key] = prev + 1

    if prev < _RETRY_THRESHOLD:
        return None  # allow the first N calls through

    # N+1-th duplicate — block with escalation nudge.
    return HookResult(
        drop=True,
        drop_note=(
            f"[retry_storm fired] Blocked: you have already called `{proposed_name}` with these exact "
            f"arguments {prev + 1} times in this conversation. The previous calls "
            "did not produce the expected result. Reconsider the arguments — "
            "check the knowledge base for required fields, value formats, and enum "
            "strings — or take a different approach (e.g. escalate, or call a "
            "related tool) rather than retrying identically."
        ),
        log={
            "intervention": "retry_storm",
            "case": "block_duplicate",
            "proposed": proposed_name,
            "arg_sig": sig,
            "seen_count": prev + 1,
        },
    )


REGISTRY.register(Intervention(
    id="retry_storm",
    name="retry-storm-limiter",
    hook="gate_pre",
    target_cluster="wrong_arguments",
    author="brianbot8",
    description=(
        f"After {_RETRY_THRESHOLD} calls to the same call_discoverable_agent_tool "
        "with identical arguments (opaque hash match), block the next duplicate "
        "and annotate with a nudge to reconsider args or escalate. No specific "
        "tool names hardcoded. Targets failure mode 2 from diagnostic #102."
    ),
    status="active",
    apply=retry_storm_limiter,
))
