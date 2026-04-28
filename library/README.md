# Optional library

Modules in the repo that are NOT wired into `agent.py` by default. Import selectively, modify your copy, or delete if not useful.

## `interventions/` — gate hooks framework

A small registry + plugin system for intercepting tool calls. Interventions fire between "LLM proposes a tool call" and "tool actually runs". They can:

- **drop** the call (return `HookResult(drop=True, drop_note="...")`)
- **rewrite** args (return `HookResult(replace_with=new_tool_call)`)
- **annotate** the assistant message after tool execution (return `HookResult(annotation="...")`)

### Files

| File | What it does |
|---|---|
| `interventions/__init__.py` | Registry + `Intervention` dataclass + `HookContext`/`HookResult` types |
| `interventions/banking.py` | 9 banking-specific rules (A, B, C, D, E, F, G, H, J) — dedup unlocks, canonicalize `log_verification` args, block hallucinated tool names, inject "now tell the customer" reminders after user-tool gives |
| `interventions/prefer_discoverable_reads.py` | Intervention J (separate file). When agent calls a base read tool that has a discoverable variant, rewrites to unlock the variant instead. |
| `interventions/verify_before_mutate.py` | Intervention K. Blocks any mutation tool call until `log_verification` has fired. |
| `interventions/shell_output_parser.py` | Helper — not an intervention. Parses `ls`/`cat`/`grep` output into structured chunks for other interventions that consume KB text in terminal_use mode. |
| `interventions/kb_cross_reference.py` | `tool_result` hook + public `annotate()` helper. After every shell tool result, scans for markdown filename mentions and short quoted "see also" / "per" anchors, then appends up to 3 unread cross-references to the tool message content. Name-agnostic (no `_NNNN` tool names); persistent de-dup via `state.kb_surfaced_refs: set[str]`. Targets the P1 single-doc-stop failure pattern. |

### How to enable

Add to the top of `agent.py`:

```python
from interventions import REGISTRY  # noqa: F401
from interventions import banking as _banking  # noqa: F401  (triggers registrations on import)
# optional: from interventions import prefer_discoverable_reads, verify_before_mutate
```

Then in your agent's `generate_next_message` (or wherever you process tool calls), iterate the registry:

```python
from interventions import HookContext
for intv in REGISTRY.for_hook("gate_pre"):
    result = intv.apply(HookContext(tool_call=tc, state=self._task_state))
    # ... apply drop / replace_with / annotation
```

See `interventions/banking.py` for real examples of how each rule is structured.

For `tool_result` plugins like `kb_cross_reference`, you can either route through `REGISTRY.for_hook("tool_result")` symmetrically with `gate_pre`, or call the plugin's public helper inline. The inline path is one import + one call:

```python
from interventions.kb_cross_reference import annotate
# In CustomAgentState: kb_surfaced_refs: set[str] = Field(default_factory=set)
# In _track_state, per tool message:
log = annotate(tm, pending, state)
if log is not None:
    state.intervention_log.append(log)  # if you keep one
```

### Warnings

- These interventions were originally designed and tuned for a different retrieval method and model combination. They may help, hurt, or be neutral on the current setup. **Measure before trusting.**
- Each intervention has a `status` field (`active`/`disabled`/`experimental`). Experimental interventions have not been validated and may regress your score.
- You can also **delete `interventions/` entirely** if you want to work without it.

## Adding your own intervention

1. Create `interventions/<your_idea>.py`
2. Import `REGISTRY` and construct an `Intervention(...)` instance, then call `REGISTRY.register(...)` at module level
3. Add `from interventions import <your_idea> as _` to `agent.py` imports

One idea per file — keep diffs scannable.
