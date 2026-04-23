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

- [POS] Adding a `<tool_selection>` block to AGENT_INSTRUCTION that (a) lists the top-8 baseline-missed `*_NNNN` variants and (b) spells out the `call_discoverable_agent_tool` outer-field contract (`agent_tool_name` + `arguments`) moves full 24/97 → 29/97 (+5, 24.7% → 29.9% — ~21% relative lift). Lite moved 10/20 → 12/20 on the same commit. On full, P1 primary events dropped 69 → 58 (-11) and P4 stayed ~flat (2 → 3); P2 went UP 2 → 6. Consistent with a P1→P2 shift: more tasks now reach the call_discoverable_agent_tool stage, and a fraction fail there on arg errors the outer-field-contract text didn't prevent. (brianbot8, sha=8b809e5)

- [OBS] Straggler tasks dominate eval wall time super-linearly. On both lite and full runs, a single max_steps/P4 failure gates wall time under `max_concurrency=8`. Lite had one 26-min straggler; full had a 20+ min task_097 straggler that held the run open after 95/97 finished. P4-discipline work compresses iteration time dramatically, not just score. (brianbot8)

- [OBS] Lite overpredicts full. On this commit, lite +2 / 20 tasks → full +5 / 97 tasks — NOT the +10 that simple proportional scaling would suggest. Lite's curated failure-cluster sampling over-weights the clusters a given change happens to help with; don't multiply lite deltas by ~5 to estimate full. Treat lite as a triage signal (which direction helped at all) and full as the only real magnitude measurement. (brianbot8, sha=8b809e5)

- [OBS] On the 29/97 full run, 58 of 68 failures are P1 with 367 "unmentioned-then-uncalled" tool events across 58 tasks. Catalog coverage is the dominant unresolved variable — the top-8 list is nowhere near enough. Domain-dimension framing (card × credit/debit × activate/freeze/dispute/close/transfer) plus an explicit "expect an `_NNNN` variant for every mutation; grep the KB" instruction is the clearest next move on the prompt surface. (brianbot8)
