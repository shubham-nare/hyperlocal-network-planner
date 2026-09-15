# Task 02 — Fix and harden the Streamlit app + cloud-kitchen mode

**Assigned to:** Antigravity, worktree `antigravity/work`.
**Goal:** `app/app.py` and `src/planner/cloud_kitchen.py` already exist (built earlier, before this
board existed) but the app is currently **broken in both of its modes**. Fix that, then harden it.

## The confirmed bug (fix this first)

`load_city_data()` in `app/app.py` does:
```python
pins = gpd.read_file(ROOT / "data" / "processed" / f"{city}_hex_pincode_r{res}.gpkg")
cols = ["h3", "pincode", "pincode_office", "pincode_district"]
coverage = coverage.merge(pins[cols], on="h3", how="left")
```
This drops the `office`, `food_retail`, `education`, `residential_highrise`, `density_per_km2`
columns (and their `_pct` versions) that the pincode file also has. Both `adoption_index()` (used by
"Dark-store simulator") and `opportunity_index()` (used by "Cloud-kitchen discovery") need those
columns and fail without them. Reproduced directly:
```
KeyError: 'food_retail_pct'
  ...raised from planner/orders.py, adoption_index(), when app.py calls dark_store_result()
```
**Fix:** extend `cols` (or just merge the columns `adoption_index`/`opportunity_index` actually need)
so `load_city_data()` carries the raw feature columns and their `_pct` versions through. Verify by
actually running `streamlit run app/app.py`, selecting each city, and using **both** sidebar modes —
don't just fix the merge and assume it works, click through it.

## A related robustness gap (fix while you're in there)

`adoption_index()` in `src/planner/orders.py` indexes `hexes[f"{k}_pct"]` directly with no existence
check, so a missing column raises a raw `KeyError` instead of the clean `ValueError` that
`opportunity_index()` in `cloud_kitchen.py` already raises for the same situation (it checks
`missing = set(weights) - set(hexes.columns)` first). Make `adoption_index` do the same check and
raise a `ValueError` naming the missing columns. Add a test for it in `tests/test_orders.py`
alongside the existing `test_adoption_index_is_weighted_mean_of_percentiles_and_rejects_density`
(follow that test's style).

## Hardening, once the app actually runs

1. Wrap the "Run scenario" block in `main()` in a try/except that shows `st.error(...)` with a short
   message instead of an unhandled traceback — a bad combination of sliders (e.g. capacity below every
   city's break-even) could make the solver return nothing useful, and the app shouldn't crash.
2. Click through all 3 cities in both modes. Note in NOTES.md anything that looks wrong on the map or
   in the numbers (not just exceptions — e.g. store markers in the wrong place, a table column that
   doesn't make sense).
3. Add `tests/test_app_helpers.py` for the app's pure-logic functions that don't need Streamlit or
   real data: `point_frame()` and `fast_candidates()` in `app/app.py`. You'll need to make `app/` and
   `src/` both importable from the test — check how `app/app.py` already does `sys.path.insert(0, ...)`
   and use the same approach, or add `app/__init__.py` + a `pytest.ini`/`conftest.py` tweak if that's
   cleaner. Use your judgment; explain the choice in NOTES.md.
4. Confirm `config/cloud_kitchen.yaml`'s weights (`density_per_km2, food_retail, office, education,
   residential_highrise`) match real column names in `data/processed/{city}_demand_r8.gpkg` for all
   three cities, not just Hyderabad — a quick Python check is enough, doesn't need to be a formal test.
5. Run the full test suite (`PYTHONPATH=src .venv/Scripts/python.exe -m pytest -q`) — should be more
   than 80 passing once your new tests are added, and nothing existing should break.
6. Write `NOTES.md`: what was broken, what you fixed, what you clicked through and observed, any
   remaining rough edges you left for later (state them, don't silently drop them).
7. Commit your work with a clear message.

## Files you should touch

`app/app.py`, `src/planner/orders.py` (only `adoption_index`, for the ValueError fix),
`tests/test_orders.py`, new `tests/test_app_helpers.py`, your own `NOTES.md`. Possibly `pytest.ini`
or a new `conftest.py` if needed for the app import (explain if so).

## Files you must NOT touch

`src/planner/cloud_kitchen.py` (already correct — don't change its behavior, only consume it
correctly from `app.py`), `src/planner/optimize.py`, `src/planner/economics.py`, anything under
`scripts/` or `reports/network_*` (a parallel task, Codex on `codex/work`, is running those), `CONTEXT.md`.

## Non-goals

Don't add new sliders, new modes, or visual redesign. Don't build a "cloud kitchen unit economics"
model — `cloud_kitchen.py`'s own docstring is explicit that it stops at market discovery, not P&L;
keep it that way.
