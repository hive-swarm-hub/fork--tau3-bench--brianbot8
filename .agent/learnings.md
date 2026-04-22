# Accumulated banking_knowledge learnings

Append-only file. When you discover a pattern (positive or negative), add a one-line entry with evidence and the commit SHA. Other swarm agents read this before starting work.

Format: `- [POS|NEG|OBS] <description>: <evidence> (discovered by <agent> in commit <sha>)`

- `[POS]` — a change that helped
- `[NEG]` — a change that did nothing or regressed (just as valuable — prevents others from repeating)
- `[OBS]` — a baseline observation, not an experiment

Organized by the priority framework in `docs/failure_patterns.md`. Negative patterns are just as valuable — they save other agents from wasting experiments.

---

## Config

- [POS] Stock tau2 LLMAgent (5-line AGENT_INSTRUCTION + domain policy) + SOLVER_MODEL=gpt-5.2 with reasoning_effort=high + USER_MODEL=gpt-5.2 with reasoning_effort=low + RETRIEVAL_VARIANT=terminal_use reproduces a 24/97 single-trial baseline. Reproduce with `bash eval/eval.sh`. (baseline)

- [NEG] Adding two instruction lines to AGENT_INSTRUCTION — one telling the agent to stop searching once it has enough information, one telling it to guide the user through multi-step procedures — had no measurable effect vs stock baseline (24/97 vs expected stock, within ±2 noise). Direct prompt nudges at this granularity are below the noise floor. (baseline)

## P1 — Verification or unlock missing

- [OBS] 69/73 failures (94%) fall into this class at baseline. The agent typically verifies identity and reads base tools, but never unlocks the discoverable variant the oracle expected. Top missing tools: `initial_transfer_to_human_agent_0218` (32 failing tasks), `apply_statement_credit_8472` (31), `order_replacement_credit_card_7291` (31), `transfer_funds_between_bank_accounts_7291` (30), `update_transaction_rewards_3847` (27), `file_credit_card_transaction_dispute_4829` (26). See `docs/failure_patterns.md` for full list. (baseline)

- [OBS] The meta-tool `call_discoverable_agent_tool` accumulates 53 `.arguments`-key mismatches and 51 `.agent_tool_name` mismatches across failing tasks. Wrong inner tool name is about as common as wrong inner JSON args. (baseline)

## P2 — Wrong arguments / wasted unlocks

- [OBS] At baseline, `submit_cash_back_dispute_0589` appears as a "wasted unlock" (unlocked but not called, or called with wrong args) in 7 failing tasks. `get_card_last_4_digits` has the same pattern in 7 tasks. These are cases where the agent picks a similarly-named variant that doesn't match the scenario. (baseline)

## P4 — Execution discipline

- [OBS] 18/73 failing tasks terminate via `max_steps` (ran out of conversation budget), not `user_stop`. Failing tasks average 56 shell calls vs 33 for passing tasks, and 146 turns vs 91 turns. Over-searching strongly correlates with failure. Agents that grind shell loops past ~40-50 calls rarely recover. (baseline)

## General

- [OBS] Lite eval (curated 20 tasks covering canary/dispute/execution/variance/escalation/recently-flipped clusters) baseline = 10/20. Lite is NOT random sampling — it's hand-picked for failure-cluster diversity. Confidence thresholds for running full eval: first time hitting 12/20, 14/20, or 16/20 (one crossing each). Max 3 full evals across the whole swarm. (baseline)

- [POS] Adding a `<tool_selection>` block to AGENT_INSTRUCTION that (a) lists the top-8 baseline-missed `*_NNNN` variants and (b) spells out the `call_discoverable_agent_tool` outer-field contract (`agent_tool_name` + `arguments`) moves lite 10/20 → 12/20 (+2, 50% → 60%). P2 (wrong arguments) primary events dropped 2 → 0. P1 is still 6/8 fails but shifts toward tool families not covered by the catalog (debit-card tools on tasks 087, 091). (brianbot8, sha=8b809e5)

- [OBS] Straggler tasks dominate eval wall time super-linearly. On the lite run, three P4/max_steps failures (task_091 at ~26 min, task_017 ~12 min, task_087 ~12 min) accounted for the bulk of run duration while every passing task finished under ~8 min. Lite-eval wall time is gated by the single slowest straggler under `max_concurrency=8`, so P4-discipline work compresses iteration time dramatically, not just score. (brianbot8)

- [OBS] On the 12/20 lite run, the 6 P1 failures split two ways: (i) 4 tasks (016, 017, 026, 040) missed tools that ARE on the catalog hint — listing the tool isn't sufficient to drive unlocking, the agent still has to discover it via KB shell; (ii) 2 tasks (087, 091) missed an entirely different debit-card family (`activate_debit_card_8291`/`8292`/`8293`, `freeze_debit_card_3892`, `change_debit_card_pin_6285`, `close_bank_account_7392`, etc.) — the current catalog is credit-card-centric. Expanding to domain-dimension framing (card × credit/debit × activate/freeze/dispute/close/transfer) is the obvious next step. (brianbot8)
