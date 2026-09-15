# Task briefs

One file per assignment, written by Claude. Copy the relevant one to the target worktree's
`TASK_BRIEF.md` before launching that agent (Claude does this as part of assigning the task).

## Launching Codex on a brief

From the **main** worktree (this repo), with the brief already copied to the codex worktree:

```bash
codex exec \
  -C "C:\Users\Shubham\.worktrees\hyperlocal-network-planner\codex" \
  --sandbox workspace-write \
  -o "C:\Users\Shubham\.worktrees\hyperlocal-network-planner\codex\last_message.txt" \
  "Read TASK_BRIEF.md and CONTEXT.md in this directory, then do the task. Run the test suite \
  (PYTHONPATH=src .venv/Scripts/python.exe -m pytest -q) before finishing. Commit your changes \
  yourself with a clear message. Write a short NOTES.md summarizing what you did and any decisions."
```

`--sandbox workspace-write` lets it edit files and run the test suite without per-command approval
prompts, but keeps it inside the worktree directory. Add `--approve-for-me` if it still stops for
approval on something reasonable (network access, etc.) — never `--dangerously-bypass-approvals-and-sandbox`
for this project.

To give feedback after reviewing: update `TASK_BRIEF.md` in that worktree with a "## Feedback"
section describing what to change, then re-run the same command — Codex starts a fresh reasoning
pass but sees its own prior commits in the worktree's git history.

## Launching Antigravity on a brief

Antigravity has no headless mode — this step needs Shubham:

```
"C:\Users\Shubham\AppData\Local\Programs\Antigravity IDE\bin\antigravity-ide.cmd" ^
  "C:\Users\Shubham\.worktrees\hyperlocal-network-planner\antigravity"
```

Then in the IDE's agent panel: "Read TASK_BRIEF.md and CONTEXT.md, then do the task described.
Run the test suite before you're done. Write a short NOTES.md of what you did." Commit from the
IDE's source control panel or a terminal inside it.
