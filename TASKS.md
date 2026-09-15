# Task board

See `ORCHESTRATION.md` for how this works. Claude keeps this file current.

## Backlog

(nothing queued beyond the two below yet)

## Assigned

| Task | Agent | Worktree/branch | Brief | Status |
|---|---|---|---|---|
| 01 — Bengaluru & Pune scenarios + memos | Codex | `codex/work` | `tasks/task-01-bengaluru-pune-memos.md` | not started |
| 02 — Harden the Streamlit app + cloud-kitchen mode | Antigravity | `antigravity/work` | `tasks/task-02-app-hardening.md` | not started |

## In review

(none yet)

## Done

(none yet)

## Notes

- Baseline commit `9798e61` on `main` — 80 tests passing — is what both worktrees branched from.
- `app/app.py` and `src/planner/cloud_kitchen.py` (+ config/tests) already existed on disk before this
  board was created — folded into the baseline commit rather than assigned as new work. Task 02 is about
  hardening/testing that existing code, not building it from scratch.
