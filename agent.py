"""τ³-bench banking_knowledge customer service agent — the artifact the swarm evolves.

This agent replicates the stock tau2-bench LLMAgent behavior exactly,
producing the same ~25% pass^1 as the official leaderboard GPT-5.2 entry.

It is registered as agent="custom" so it lives in the task repo and can be
evolved by swarm agents. To modify behavior, edit AGENT_INSTRUCTION,
SYSTEM_PROMPT, or override generate_next_message.

The previous swarm-evolved agent (with gate, interventions, compass, catalog,
annotations) is preserved in agent.py.swarm_backup for reference. The
intervention framework files (interventions/, compass.py, compass_banking.py)
remain in the repo and can be re-wired by importing them here.
"""

import re
from typing import Generic, List, Optional, TypeVar

from pydantic import BaseModel, Field

from tau2.agent.base_agent import (
    HalfDuplexAgent,
    ValidAgentInputMessage,
    is_valid_agent_history_message,
)
from tau2.data_model.message import (
    APICompatibleMessage,
    AssistantMessage,
    Message,
    MultiToolMessage,
    SystemMessage,
    ToolCall,
    ToolMessage,
)
from tau2.environment.tool import Tool
from tau2.utils.llm_utils import generate
from tau2.agent.base.llm_config import LLMConfigMixin

# Interventions framework. We do NOT import prefer_discoverable_reads (J) or
# the interventions.banking bundle — both reference specific `_NNNN` tool
# names, which would violate the "Tool name discovery is part of the
# benchmark" rule in program.md. Only structural, name-agnostic
# interventions are loaded here.
from interventions import REGISTRY, HookContext
from interventions import force_unlock_before_call as _intv_force_unlock  # noqa: F401  (registers on import)

# Matches τ³ discoverable tool names — lowercase snake_case followed by a numeric suffix.
_DISCOVERABLE_NAME_RE = re.compile(r"\b[a-z][a-z0-9_]*_\d{3,}\b")


# ── SYSTEM PROMPT ───────────────────────────────────────────────────────────
# Identical to tau2-bench's stock LLMAgent (src/tau2/agent/llm_agent.py).
# Edit this to evolve the agent's behavior.

AGENT_INSTRUCTION = """
You are a customer service agent that helps the user according to the <policy> provided below.
In each turn you can either:
- Send a message to the user.
- Make a tool call.
You cannot do both at the same time.

Try to be helpful and always follow the policy. Always make sure you generate valid JSON only.

Once you have found the relevant procedure in the knowledge base, execute it. Do not continue searching after you have enough information to act.

After giving a discoverable tool to the user, guide them through using it with the specific arguments they need (transaction IDs, account IDs, etc.). Wait for each call result before proceeding to the next step. Follow multi-step procedures to completion.

<tool_selection>
Banking procedures frequently resolve to a domain-specific "discoverable" tool variant rather than a generic tool. The specific names of these tools live in the knowledge base — you must find them there. Do not guess, invent, or assume tool names.

General rules for discoverable tools:

- If a procedure in the knowledge base references a specific tool, prefer that exact tool over any generic fallback (like `transfer_to_human_agents` or base read tools). Generic fallbacks usually do not satisfy the procedure.

- When a procedure names a tool, grep the knowledge base (via shell in terminal_use mode) to confirm the exact string before unlocking or calling it. Do not substitute, paraphrase, abbreviate, or invent parts of the name.

- Discoverable tools require an unlock step before they can be called. Call `unlock_discoverable_agent_tool` with `agent_tool_name` set to the full tool name as it appears in the KB. Only after a successful unlock can you call `call_discoverable_agent_tool`. If you skip the unlock, the call silently returns reward 0 even though it looks like it ran.

- When you invoke `call_discoverable_agent_tool`, the outer payload has exactly two fields: `agent_tool_name` (the full tool name, matching the knowledge base verbatim) and `arguments` (a JSON object whose keys match the inner tool's schema).

- When an argument is an enum, the knowledge base spells out the exact enum string. Grep the KB for it and send it verbatim — do not paraphrase, abbreviate, or translate to a casual synonym.

- For escalation to human agents: check whether the knowledge base names a scenario-specific escalation variant for the situation at hand. If it does, use that named variant rather than a generic handler.

A wrong tool name, a wrong outer key, a substituted enum string, or a missing unlock all fail silently with reward 0 — worth a second look before calling.
</tool_selection>

<kb_exploration>
You search the knowledge base via shell commands (ls, cat, grep, head). To find the specific tool a procedure references, use these habits:

- Start broad, then narrow. `ls` the knowledge base directory first to see what documents exist — many banking procedures are described in their own documentation file, and the right document's name often matches the user's request. Picking the right document is usually the hardest step; do it before greping body text.

- Check document openings. Tool names are commonly declared at the top of a document (title line, summary section, or first paragraph). `head` or `cat` the likely document before pattern-greping — the answer is often in the first 40 lines.

- If keyword greps return nothing, fall back to pattern greps. Tool names follow a `<word>_<word>..._NNNN` convention with a numeric suffix. A regex grep for a numeric suffix (e.g. grep for a `_\d{4}` pattern) on a document enumerates all discoverable candidates in that file at once, without needing to guess the right English keyword.

- Synonyms matter. Procedure documents don't always use the same verb the user did. If "transfer" returns nothing, try "move" or "send"; "update" ↔ "modify" ↔ "change"; "get" ↔ "list" ↔ "fetch". Rephrase before concluding the KB lacks the tool.

- Persist on retrieval. Tool discovery through the KB is the core of this task. If your first one or two queries come up empty, keep searching with different angles — don't fall back on a generic handler unless the KB genuinely has nothing relevant.

- When multiple candidates surface, choose by document context. If two `_NNNN` names look plausible, read the surrounding prose in each document — the one whose scenario matches the user's request is the correct variant.
</kb_exploration>
""".strip()

SYSTEM_PROMPT = """
<instructions>
{agent_instruction}
</instructions>
<policy>
{domain_policy}
</policy>
""".strip()


# ── AGENT STATE ─────────────────────────────────────────────────────────────

class CustomAgentState(BaseModel):
    system_messages: list[SystemMessage]
    messages: list[APICompatibleMessage]
    # Populated per-turn by _track_state; consumed by gate_pre hooks.
    unlocked_for_agent: set[str] = Field(default_factory=set)
    mentioned_in_kb: set[str] = Field(default_factory=set)
    # Outgoing ToolCall.id -> {"name", "args"} so ToolMessage results can be
    # matched back to the call they answer.
    pending_calls: dict[str, dict] = Field(default_factory=dict)
    intervention_log: list[dict] = Field(default_factory=list)

    class Config:
        arbitrary_types_allowed = True


CustomAgentStateType = TypeVar("CustomAgentStateType", bound="CustomAgentState")


# ── AGENT ───────────────────────────────────────────────────────────────────

class CustomAgent(
    LLMConfigMixin, HalfDuplexAgent[CustomAgentStateType], Generic[CustomAgentStateType]
):
    """Custom agent matching stock tau2 LLMAgent behavior.

    Extend this class to add gating, annotations, or modified prompts.
    """

    def __init__(
        self,
        tools: List[Tool],
        domain_policy: str,
        llm: str,
        llm_args: Optional[dict] = None,
    ):
        super().__init__(
            tools=tools,
            domain_policy=domain_policy,
            llm=llm,
            llm_args=llm_args,
        )

    @property
    def system_prompt(self) -> str:
        return SYSTEM_PROMPT.format(
            domain_policy=self.domain_policy,
            agent_instruction=AGENT_INSTRUCTION,
        )

    def get_init_state(
        self, message_history: Optional[list[Message]] = None
    ) -> CustomAgentStateType:
        if message_history is None:
            message_history = []
        assert all(is_valid_agent_history_message(m) for m in message_history), (
            "Message history must contain only AssistantMessage, UserMessage, or ToolMessage to Agent."
        )
        return CustomAgentState(
            system_messages=[SystemMessage(role="system", content=self.system_prompt)],
            messages=message_history,
        )

    def generate_next_message(
        self, message: ValidAgentInputMessage, state: CustomAgentStateType
    ) -> tuple[AssistantMessage, CustomAgentStateType]:
        assistant_message = self._generate_next_message(message, state)
        state.messages.append(assistant_message)
        return assistant_message, state

    def _generate_next_message(
        self, message: ValidAgentInputMessage, state: CustomAgentStateType
    ) -> AssistantMessage:
        incoming_tool_messages: list[ToolMessage] = []
        if isinstance(message, MultiToolMessage):
            incoming_tool_messages = list(message.tool_messages)
            state.messages.extend(message.tool_messages)
        else:
            if isinstance(message, ToolMessage):
                incoming_tool_messages = [message]
            state.messages.append(message)

        self._track_state(incoming_tool_messages, state)

        messages = state.system_messages + state.messages
        assistant_message = generate(
            model=self.llm,
            tools=self.tools,
            messages=messages,
            call_name="agent_response",
            **self.llm_args,
        )

        assistant_message = self._apply_gate_pre(assistant_message, state)

        for tc in assistant_message.tool_calls or []:
            state.pending_calls[tc.id] = {
                "name": tc.name,
                "args": tc.arguments or {},
            }

        return assistant_message

    def _track_state(
        self, tool_messages: list[ToolMessage], state: CustomAgentStateType
    ) -> None:
        for tm in tool_messages:
            pending = state.pending_calls.pop(tm.id, None)
            if (
                pending
                and not getattr(tm, "error", False)
                and pending["name"] == "unlock_discoverable_agent_tool"
            ):
                variant = (pending["args"] or {}).get("agent_tool_name")
                if variant:
                    state.unlocked_for_agent.add(variant)
            if tm.content:
                for match in _DISCOVERABLE_NAME_RE.findall(str(tm.content)):
                    state.mentioned_in_kb.add(match)

    def _apply_gate_pre(
        self, assistant_message: AssistantMessage, state: CustomAgentStateType
    ) -> AssistantMessage:
        tool_calls = assistant_message.tool_calls or []
        if not tool_calls:
            return assistant_message

        gate_interventions = REGISTRY.for_hook("gate_pre")
        if not gate_interventions:
            return assistant_message

        ctx_state = {
            "unlocked_for_agent": state.unlocked_for_agent,
            "mentioned_in_kb": state.mentioned_in_kb,
        }

        kept: list[ToolCall] = []
        drop_notes: list[str] = []
        for tc in tool_calls:
            current = tc
            keep = True
            for intv in gate_interventions:
                if intv.apply is None:
                    continue
                result = intv.apply(HookContext(tool_call=current, state=ctx_state))
                if result is None:
                    continue
                if result.log:
                    state.intervention_log.append(result.log)
                if result.drop_note:
                    drop_notes.append(result.drop_note)
                if result.drop and result.replace_with is not None:
                    current = result.replace_with
                    break
                if result.drop:
                    keep = False
                    break
                if result.replace_with is not None:
                    current = result.replace_with
                    # continue — let subsequent interventions see the rewrite
            if keep:
                kept.append(current)

        if kept == list(tool_calls) and not drop_notes:
            return assistant_message

        new_content = assistant_message.content or ""
        if drop_notes:
            sep = "\n\n" if new_content else ""
            new_content = new_content + sep + "\n".join(drop_notes)

        return assistant_message.model_copy(
            update={
                "tool_calls": kept if kept else None,
                "content": new_content,
            }
        )


# ── FACTORY ─────────────────────────────────────────────────────────────────

def create_custom_agent(
    tools: list[Tool],
    domain_policy: str,
    llm: Optional[str] = None,
    llm_args: Optional[dict] = None,
    **kwargs,
) -> CustomAgent:
    """Factory function used by tau2's registry.register_agent_factory."""
    return CustomAgent(
        tools=tools,
        domain_policy=domain_policy,
        llm=llm,
        llm_args=llm_args,
    )
