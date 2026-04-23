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

from typing import Generic, List, Optional, TypeVar

from pydantic import BaseModel

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
)
from tau2.environment.tool import Tool
from tau2.utils.llm_utils import generate
from tau2.agent.base.llm_config import LLMConfigMixin


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
        if isinstance(message, MultiToolMessage):
            state.messages.extend(message.tool_messages)
        else:
            state.messages.append(message)
        messages = state.system_messages + state.messages
        assistant_message = generate(
            model=self.llm,
            tools=self.tools,
            messages=messages,
            call_name="agent_response",
            **self.llm_args,
        )
        return assistant_message


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
