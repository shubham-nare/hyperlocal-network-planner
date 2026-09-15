# Task board

See `ORCHESTRATION.md` for how this works. Claude keeps this file current.

## Backlog

- Finish task 01's remaining scope (Pune scenarios + Pune memo + city comparison) — Claude will do
  this directly, since Codex is out of usage (see below).

## Assigned

(none currently — both original assignments have resolved, see Done)

## In review

(none)

## Done

| Task | Agent | Outcome |
|---|---|---|
| 02 — Harden the Streamlit app + cloud-kitchen mode | Antigravity (interactive) | **Done.** Fixed the confirmed `load_city_data()` column-drop bug, hardened `adoption_index` with a clean `ValueError`, wrapped the scenario runner in try/except, added `app/__init__.py` + `pytest.ini` pythonpath so `app/` is testable, added 4 new tests, verified `cloud_kitchen.yaml` weights across all 3 cities, walked through every city/mode combination. Committed on `antigravity/work` (`8c7021b`); the substantive files were brought onto `main` directly (`e3b56fd`) rather than merged wholesale, since that branch forked before `ORCHESTRATION.md`/`TASKS.md`/`tasks/` existed and a blind merge would have shown them as "deleted" (branch-divergence artifact, not real deletions — verified before doing anything). 84 tests passing. |
| 01 — Bengaluru & Pune scenarios + memos | Codex (`codex exec`) | **Partially done, then blocked.** First launch failed cleanly on two real sandbox issues (see `tasks/README.md`); fixed both and relaunched. Completed all 5 Bengaluru scenarios + Bengaluru's memo + `scripts/build_city_comparison.py`, started Pune's `e0` scenario, then **hit "You've hit your usage limit... try again at Oct 13th, 2026" mid-run.** Did not fabricate anything — left real, reviewable partial output and stopped. Bengaluru's output verified (tests pass) and brought onto `main`. **Codex is unusable for this project until Oct 13, 2026 (or an upgrade).** Claude is finishing the remaining Pune + comparison work directly.

## Notes

- Baseline commit `9798e61` on `main` — 80 tests passing — is what both worktrees branched from.
- `codex/work` and `antigravity/work` still exist with their own commit histories; they're not being
  deleted, just not merged wholesale. Future tasks can keep reusing them.
- Both `TASK_BRIEF.md` files remain in their worktrees for reference.
