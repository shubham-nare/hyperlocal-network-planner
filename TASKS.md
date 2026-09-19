# Task board

See `ORCHESTRATION.md` for coordination rules. This board is the concise handoff view; detailed decisions, commands, and evidence live in `CONTEXT.md`.

## Backlog

(nothing queued outside the active v2 build)

## Assigned

| Task | Owner | Scope / current checkpoint |
|---|---|---|
| V2 - Hyperlocal Growth & Reliability OS | Codex | **In progress.** Preserve v1; build product events, Experiment Studio, simulated DuckDB harness, intervention comparison, decision workspace, and evidence-backed brief. Charter, event/experiment foundations, and simulated DuckDB harness are complete; next is the tested intervention comparator. |

## In review

(none)

## Done

| Task | Agent | Outcome |
|---|---|---|
| 02 - Harden the Streamlit app + cloud-kitchen mode | Antigravity (interactive) | **Done.** Fixed `load_city_data()` feature-column loss, hardened `adoption_index`, added app tests, and verified every city/mode. Substantive files landed on `main` in `e3b56fd`; 84 tests passed. |
| 01 - Bengaluru & Pune scenarios + memos | Codex then Claude | **Done.** Completed all replication scenarios, city memos, and the three-city comparison. Main results landed in `a8f4446` and `295fb7b`; 84 tests passed. |

## Handoff notes

- Baseline commit `9798e61` contains the finalized v1 engine. Keep v1's public-data evidence and validation intact while building v2.
- `data/`, `.venv`, and `cache/` are shared, untracked junctioned state across worktrees. Do not regenerate `data/processed` casually.
- V2's generated event data must always be labelled simulated; it is a harness for product analytics and experiment mechanics, not real customer data or impact evidence.
- Record each meaningful v2 milestone, test command, data-source decision, and remaining next action in `CONTEXT.md` before switching workstreams.
