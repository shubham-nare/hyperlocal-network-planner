# Task board

See `ORCHESTRATION.md` for coordination rules. This board is the concise handoff view; detailed decisions, commands, and evidence live in `CONTEXT.md`.

## Backlog

(nothing queued outside the active v2 build)

## Assigned

| Task | Owner | Scope / current checkpoint |
|---|---|---|
| V2 - Hyperlocal Growth & Reliability OS | Codex, then Claude | **In progress.** Charter, event/experiment foundations, simulated DuckDB harness, and the intervention comparator are done (Claude found and fixed one real bug in the comparator's scoring before committing). The evidence-first decision brief (the honest "AI copilot") is done and tested — no LLM call, composes only from already-computed numbers. Remaining: wire a Streamlit decision-workspace tab on real v1 city data, validate one real end-to-end case per city, polish the README/case study, then CV bullets from real output only. 105 tests passing. |

## In review

(none)

## Done

| Task | Agent | Outcome |
|---|---|---|
| 06 - Competitor-response game | Claude (cloud session) | **Done.** Stackelberg expansion game with Huff shares across brands; rivals respond rationally or as their revealed-demand models predict. Naive plans overstate value by up to 29%; anticipating the right response wins 18/18 comparisons (+2-51%); the rational-aware plan is the robust (minimax-regret) default in 7/9 cases. See `reports/competition.md`. |
| 05 - Peak-hour promise (rider queueing) | Claude (cloud session) | **Done.** M/G/c rider queue per store and hour on the real Blinkit networks. Under the usual 80%-utilisation rule the 10-min promise slips off-peak (79-92% of late orders outside 7-10 pm); queue-model staffing cuts late orders 40-52% for +6-9% rider-hours; re-spreading the same rider-hours cuts them 18-23% for free. See `reports/peak_sla.md`. |
| 04 - Staged rollout under uncertainty | Claude (cloud session) | **Done.** Two-wave rollout policy (commit sure bets, learn from them, re-plan the frontier) with INR objective, max-flow served orders, Bayesian spatial learning and trigger rules. Simulated: +INR 20.7-30.5 Cr over v1's plan in Hyderabad/Pune across all uncertainty levels; value is from learning, not waiting; Bengaluru's budget binds first so staging adds nothing there. See `reports/rollout_plan.md`. |
| 03 - Revealed demand (inverse siting model) | Claude (cloud session) | **Done.** Spacing-aware spatial entry model over real Blinkit/Zepto/Instamart networks; features rebuilt from Overture + Meta HRSL. Spacing + competitor co-location re-finds the exact store hex 2.4x as often as the v1 demand index (27.1% vs 11.5%, 9/9 held-out networks); public demand features add nothing once competitors are known. See `reports/revealed_demand.md`. Open: rerun with `--source v1` locally; forward-test the whitespace list on a later scrape. |
| 02 - Harden the Streamlit app + cloud-kitchen mode | Antigravity (interactive) | **Done.** Fixed `load_city_data()` feature-column loss, hardened `adoption_index`, added app tests, and verified every city/mode. Substantive files landed on `main` in `e3b56fd`; 84 tests passed. |
| 01 - Bengaluru & Pune scenarios + memos | Codex then Claude | **Done.** Completed all replication scenarios, city memos, and the three-city comparison. Main results landed in `a8f4446` and `295fb7b`; 84 tests passed. |

## Handoff notes

- Baseline commit `9798e61` contains the finalized v1 engine. Keep v1's public-data evidence and validation intact while building v2.
- `data/`, `.venv`, and `cache/` are shared, untracked junctioned state across worktrees. Do not regenerate `data/processed` casually.
- V2's generated event data must always be labelled simulated; it is a harness for product analytics and experiment mechanics, not real customer data or impact evidence.
- Record each meaningful v2 milestone, test command, data-source decision, and remaining next action in `CONTEXT.md` before switching workstreams.
