# Task 01 — Bengaluru & Pune scenarios + memos + city comparison

**Assigned to:** Codex, worktree `codex/work`.
**Goal:** Bring Bengaluru and Pune up to the same analysis depth Hyderabad already has (see
`reports/expansion_memo_hyderabad.md` and the Week 4 section of `CONTEXT.md` for the pattern), then
add a 3-city comparison.

## Context to read first

- `CONTEXT.md` — read the whole "Week 4" section. It has exact commands, capacity/elasticity/growth
  values, and the reasoning behind them. Follow the same pattern; don't invent new scenario values.
- `reports/expansion_memo_hyderabad.md` — the target shape of the output for the other two cities.
- `scripts/optimize_network.py`, `scripts/build_memo.py` — already generalized by `--city`; you should
  not need to edit either. If you find you *must* edit them to make Bengaluru/Pune work, that's fine,
  but explain why in NOTES.md — likely means something about my Hyderabad-only assumption leaked in.

## Steps

1. For each of `bengaluru` and `pune`, run the same 5 scenarios already run for Hyderabad:
   ```
   PYTHONPATH=src .venv/Scripts/python.exe scripts/optimize_network.py --city <city> --curve --tag e0 --elasticity 0
   PYTHONPATH=src .venv/Scripts/python.exe scripts/optimize_network.py --city <city> --curve --tag e1 --elasticity 1
   PYTHONPATH=src .venv/Scripts/python.exe scripts/optimize_network.py --city <city> --curve --tag g15 --growth 1.5
   PYTHONPATH=src .venv/Scripts/python.exe scripts/optimize_network.py --city <city> --curve --tag cap1600 --capacity 1600
   PYTHONPATH=src .venv/Scripts/python.exe scripts/optimize_network.py --city <city> --curve --tag cap3000 --capacity 3000
   ```
   These write `reports/network_<city>_<tag>.{csv,png}` and `reports/network_<city>_<tag>_curve.csv`.
   Some runs took several minutes for Hyderabad (N=30 sometimes hits the 300s CBC time limit) — that's
   expected, not a bug.
2. Build each city's memo: `PYTHONPATH=src .venv/Scripts/python.exe scripts/build_memo.py --city bengaluru`
   and `--city pune`. Read the resulting `reports/expansion_memo_{bengaluru,pune}.md` and sanity-check
   the numbers against what's already in `CONTEXT.md` for the base run (Bengaluru N=10 ≈ +20,230 orders/
   day; Pune N=10 ≈ +20,268) — the core-picks and scenario table are new, the base numbers should be close
   to (not necessarily identical to, since CBC's gap tolerance means re-solves can vary slightly) what's
   already logged.
3. Write `scripts/build_city_comparison.py` that reads the three cities' base curve CSVs
   (`reports/network_{city}_base_curve.csv`), the three hold-out validation CSVs
   (`reports/holdout_validation_{city}.csv`), and each city's core-picks (from the memo generation
   logic in `build_memo.py` — reuse its `robust_areas` function rather than reimplementing it) to
   produce `reports/city_comparison.md`: one table with columns city / latent demand / % served today /
   N=10 incremental orders/day / % served after N=10 / hold-out recall@1.5km (optimiser vs. demand-index
   heuristic) / number of core picks. Add 2-3 sentences of interpretation (e.g. which city has the most
   headroom, which city's optimiser edge over the heuristic is strongest — Bengaluru's is; Hyderabad's is
   within noise — this is already established in CONTEXT.md, just carry it through).
4. Run the test suite: `PYTHONPATH=src .venv/Scripts/python.exe -m pytest -q`. It must still show
   **80 passed**, unchanged, since you're not supposed to touch `src/` (see below).
5. Write `NOTES.md` in this worktree: what you ran, wall-clock time per city, anything that didn't
   match the Hyderabad pattern, and any numbers worth flagging (e.g. if Pune's AFMC-style false-positive
   pattern from Hyderabad's cap3000 scenario shows up elsewhere).
6. Commit your work with a clear message.

## Files you should touch

`reports/network_bengaluru_*`, `reports/network_pune_*`, `reports/expansion_memo_bengaluru.md`,
`reports/expansion_memo_pune.md`, new `scripts/build_city_comparison.py`, `reports/city_comparison.md`,
your own `NOTES.md`.

## Files you must NOT touch

`src/planner/*`, `app/app.py`, `config/cloud_kitchen.yaml`, `tests/test_cloud_kitchen.py`,
`CONTEXT.md` (Claude owns it — your NOTES.md gets folded in at review time), anything under
`data/raw` or `data/interim` (read-only reference data). If you think one of these genuinely needs a
change to complete this task, stop and say so in NOTES.md rather than editing it — a parallel task
(Antigravity, on `antigravity/work`) is touching `src/planner/orders.py` and `app/app.py` at the same
time, and edits to shared files from both sides will conflict at merge.

## Non-goals

Don't build a new optimizer feature, don't change scenario values, don't add new cities. This is a
"run the existing machine three more times and summarize" task, not a modeling task.
