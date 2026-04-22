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
Most banking procedures resolve to a domain-specific "discoverable" tool variant named with a four-digit numeric suffix (e.g. `apply_statement_credit_8472`). Prefer a specific `*_NNNN` variant over a generic tool like `transfer_to_human_agents` whenever the procedure names one. Common variants you are likely to need:

- `apply_statement_credit_8472` — apply a credit to a statement
- `order_replacement_credit_card_7291` — order a replacement physical card
- `transfer_funds_between_bank_accounts_7291` — transfer money between a customer's own accounts
- `update_transaction_rewards_3847` — edit rewards attached to a transaction
- `file_credit_card_transaction_dispute_4829` — file a formal dispute on a card transaction
- `get_bank_account_transactions_9173` — read transactions for a bank account (use instead of the base read tool when available)
- `initial_transfer_to_human_agent_0218` / `initial_transfer_to_human_agent_1822` — initial escalation to a human agent; pick the specific variant named in the procedure, not the generic `transfer_to_human_agents`

If the procedure references a `*_NNNN` tool whose suffix is not listed above, grep the knowledge base for that exact name. Never invent a suffix.

When you invoke `call_discoverable_agent_tool`, the outer payload has exactly two fields: `agent_tool_name` (the full `*_NNNN` string, matching the KB verbatim) and `arguments` (a JSON object whose keys match the inner tool's schema). A wrong suffix, a wrong outer key name, or a substituted enum string all fail silently with reward 0 — worth a second look before calling.
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
