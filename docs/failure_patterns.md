# Failure patterns — banking_knowledge

This file tracks open failure patterns. Update after every eval run:

- **ADD** a new pattern if you observe one not listed here.
- **Mark RESOLVED** (with your agent name + commit SHA) when a pattern drops below a meaningful threshold in your eval.
- **Mark REGRESSED** (with your agent name + commit SHA + date) if a RESOLVED pattern re-emerges.
- **Update "Last observed"** counts when your eval completes.

Diagnostic signals reference fields in `traces/latest.json`, which is written after every eval by `eval/extract_traces.py`.

---

## P1 — Verification or unlock missing (OPEN)

**Symptom in trace:**
- `trace["primary_failure_class"] == "priority_1_verification_or_unlock"`
- `trace["discoverable_tool_analysis"]["missing_unlocks"]` is non-empty (agent never unlocked a tool the expected action needed)
- `trace["verification_analysis"]["mutation_calls_before_verify"] > 0` (less common but also P1)

**What this looks like in behavior:** agent verifies identity and reads base tool results, but never finds the discoverable variant the procedure requires. Either it stops after the base-tool read, escalates via generic `transfer_to_human_agents` instead of a specific variant, or picks the wrong variant and the user tool never fires.

**Most-missed discoverable tools at baseline** (count = failing tasks where agent should have unlocked but didn't):

| Count | Tool |
|---|---|
| 32 | `initial_transfer_to_human_agent_0218` |
| 31 | `apply_statement_credit_8472` |
| 31 | `order_replacement_credit_card_7291` |
| 30 | `transfer_funds_between_bank_accounts_7291` |
| 27 | `update_transaction_rewards_3847` |
| 26 | `file_credit_card_transaction_dispute_4829` |
| 26 | `initial_transfer_to_human_agent_1822` |
| 26 | `get_bank_account_transactions_9173` |

**History:**
- 2026-04-21: 69/73 failures (94%) at baseline
- 2026-04-22: 6/8 failures on lite (brianbot8, sha=8b809e5) after tool_selection catalog hint (lite-only, full TBD).
- 2026-04-22: 58/68 failures on full (brianbot8, sha=8b809e5). P1 primary events 69 → 58 (-11). 367 unmentioned-then-uncalled tool events across 58 tasks — catalog coverage is the dominant remaining gap. Still OPEN.

---

## P2 — Wrong arguments to meta-tools (OPEN)

**Symptom in trace:**
- `trace["primary_failure_class"] == "priority_2_wrong_arguments"` (only 2 at baseline), OR
- `trace["argument_analysis"]["arg_key_mismatches"]` has entries (appears as secondary signal in many P1 failures)

**Most common arg mismatches at baseline** (count = events across failing tasks):

| Count | Tool + key |
|---|---|
| 53 | `call_discoverable_agent_tool.arguments` |
| 51 | `call_discoverable_agent_tool.agent_tool_name` |
| 14 | `unlock_discoverable_agent_tool.agent_tool_name` |
| 4 | `transfer_to_human_agents.summary` |
| 1 | `transfer_to_human_agents.reason` |

**Wasted unlocks at baseline** (agent unlocked but called wrong variant or never called at all):

| Count | Tool |
|---|---|
| 7 | `submit_cash_back_dispute_0589` |
| 7 | `get_card_last_4_digits` |
| 3 | `transfer_funds_between_bank_accounts_7291` |
| 3 | `close_bank_account_7392` |
| 2 | `file_credit_card_transaction_dispute_4829` |
| 2 | `close_credit_card_account_7834` |
| 2 | `log_credit_card_closure_reason_4521` |
| 2 | `open_bank_account_4821` |

**What this looks like in behavior:** agent finds the right procedure area but picks a similarly-named tool variant, or gets the inner JSON arguments wrong (wrong key, wrong enum string, wrong number format).

**History:**
- 2026-04-21: 2 primary + 123 secondary arg-mismatch events at baseline
- 2026-04-22: 0 primary P2 events on lite (brianbot8, sha=8b809e5, lite-only, full TBD) after AGENT_INSTRUCTION block spelled out the `call_discoverable_agent_tool` outer-field contract (`agent_tool_name` + `arguments`).
- 2026-04-22: 6 primary P2 events on full (brianbot8, sha=8b809e5) — UP from baseline's 2. Likely a P1→P2 shift: more tasks now reach the call stage (P1 dropped 69→58) and a fraction fail on arg errors the outer-field-contract text didn't prevent. Stricter arg-surfacing (enum lists, schema validation) is the next layer.

---

## P3 — Retrieval misses (OPEN, LOW-OBSERVED)

**Symptom in trace:**
- `trace["retrieval_analysis"]["kb_queries_yielding_tool_names"] == 0` with `kb_query_count >= 3`
- In `terminal_use` mode: multiple shell greps that return no `_NNNN` tool names

**Observed frequency at baseline:** 0 classified as primary. Retrieval (shell grep on KB docs) is generally finding content — the gap is acting on what's found.

**History:**
- 2026-04-21: 0 primary events at baseline

---

## P4 — Execution discipline (OPEN)

**Symptom in trace:**
- `trace["primary_failure_class"] == "priority_4_execution_discipline"` (2 at baseline), OR
- `trace["termination_reason"] == "max_steps"` (18/73 failures hit this)
- `trace["execution_analysis"]["action_completeness"] < 1.0`

**What this looks like in behavior:** agent starts the procedure correctly, but either loops in shell searches (avg 56 shell calls on failures vs 33 on passes) or stops partway through a multi-step procedure without completing all expected actions.

**Key stats at baseline:**
- Failing tasks avg: 56 shell calls, 146 turns
- Passing tasks avg: 33 shell calls, 91 turns
- 18/73 failures terminate via `max_steps` (budget exhaustion)

**History:**
- 2026-04-21: 2 primary + 18 max_steps events at baseline
- 2026-04-22: 2 primary P4 events on lite (brianbot8, sha=8b809e5, lite-only, full TBD). Straggler observation: lite wall time is gated by the single slowest task under `max_concurrency=8`. On this run the 3 longest failures (task_091 ~26min, task_017 ~12min, task_087 ~12min) dwarfed typical passing-task duration. P4 discipline compresses iteration time, not just score.
- 2026-04-22: 3 primary P4 events on full (brianbot8, sha=8b809e5) — roughly flat vs baseline's 2. Catalog hint does not reach the looping failure mode. Full run had a ~20 min straggler (task_097) that held the run open after 95/97 finished — same pattern as lite. P4 still OPEN and increasingly the single biggest wall-time lever.
