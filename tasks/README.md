# Task briefs

One file per assignment, written by Claude. Copy the relevant one to the target worktree's
`TASK_BRIEF.md` before launching that agent (Claude does this as part of assigning the task).

## Launching Codex on a brief

From the **main** worktree (this repo), with the brief already copied to the codex worktree:

```bash
codex exec \
  -C "C:\Users\Shubham\.worktrees\hyperlocal-network-planner\codex" \
  --sandbox workspace-write \
  --add-dir "C:\Users\Shubham\AppData\Local\Programs\Python\Python314" \
  -o "C:\Users\Shubham\.worktrees\hyperlocal-network-planner\codex\last_message.txt" \
  "Read TASK_BRIEF.md and CONTEXT.md in this directory, then do the task. Run the test suite as \
  PYTHONPATH=src .venv/Scripts/python.exe -m pytest -q --basetemp=.pytest_tmp before finishing. \
  Do NOT run git add/commit — Claude reviews and commits after. Write a short NOTES.md summarizing \
  what you did and any decisions."
```

`--sandbox workspace-write` lets it edit files and run the test suite without per-command approval
prompts, but keeps it inside the worktree directory. Add `--approve-for-me` if it still stops for
approval on something reasonable (network access, etc.) — never `--dangerously-bypass-approvals-and-sandbox`
for this project.

**Two sandbox quirks found and fixed 2026-09-15, both required to get a working run:**
- The `.venv` junction's `python.exe` needs its standard library from the real Python install
  (`C:\...\Programs\Python\Python314`), which sits outside the worktree — without
  `--add-dir` pointing at it, every Python invocation fails with `Access is denied` before your
  prompt even runs. This directory is shared system infrastructure, not part of the isolation
  boundary that matters (the main repo's working tree/`.git` is) — safe to grant.
- pytest's `tmp_path` fixture defaults to Windows' `%TEMP%\pytest-of-<user>`, which the sandbox also
  blocks — always add `--basetemp=.pytest_tmp` to the test command so pytest's temp dir lands inside
  the workspace instead.
- **Committing is out of scope for Codex here on purpose**, not just because of a sandbox error: a
  worktree's `.git` metadata (`.git/worktrees/<name>/`) physically lives inside the **main** repo's
  `.git`. Granting Codex write access there would mean granting it write access to your main working
  tree, which defeats the isolation the worktree was for. Claude commits Codex's branch after
  reviewing it, same as for its own work.

**Codex has a usage limit that can hit mid-task (learned 2026-09-15):** on task 01, it got through
all 5 Bengaluru scenarios and had started Pune before hitting "You've hit your usage limit... try
again at Oct 13th, 2026" and stopping. It handled this well — no fabricated output, just an honest
stop with whatever it had genuinely finished left as files. If this happens again: review and commit
whatever real progress exists, note the limit date, and either wait, upgrade, or have Claude finish
the remaining scope directly.

## Launching Antigravity on a brief

**There IS a headless Antigravity CLI** — `agy.exe` at `C:\Users\Shubham\AppData\Local\agy\bin\agy.exe`,
with a `-p`/`--print` non-interactive mode, `--sandbox`, `--mode accept-edits`,
`--dangerously-skip-permissions`, `--add-dir`. It was findable via the registry-persisted user PATH
even when a running shell couldn't see it yet (installed after that shell started). **However,
tested 2026-09-15 and found unreliable for actually running commands:**
- `--sandbox` alone: correctly detects a shell-command request in headless mode and cleanly auto-denies
  it (it can't show the interactive approval prompt) — fast, no hang, but useless for real work since
  everything gets denied.
- `--sandbox --dangerously-skip-permissions`: **hangs for the full print-timeout on any command**,
  even a trivial `echo`, burning real reasoning tokens but returning empty output.
- No `--sandbox` at all (with or without skip-permissions): hangs immediately with **zero** API usage
  — doesn't even reach the model.
- Its persistent allow-list (`~/.gemini/antigravity-cli/settings.json`, `permissions.allow` as
  `command(<literal string>)` entries) only does **exact full-string matches**, not prefixes, despite
  the interactive UI's "commands that start with X" wording — confirmed by adding `command(echo)` and
  finding it did not match `echo hello-from-agy`. This makes pre-authorizing an open-ended coding task
  impractical (you'd need to predict every exact command in advance).
- `agy install` only configures PATH/shell-profile aliases — unrelated to this, does not help.
- **No log file** exists anywhere under its install directory to diagnose the hang further.

**Conclusion: use the interactive path, not headless, until/unless a future `agy` version fixes this.**
Antigravity IDE, its GUI, has a working interactive agent (confirmed working via screenshot and via
task 02 actually being completed that way) — it just needs Shubham at the keyboard approving each
tool call:

```
"C:\Users\Shubham\AppData\Local\Programs\Antigravity IDE\bin\antigravity-ide.cmd" ^
  "C:\Users\Shubham\.worktrees\hyperlocal-network-planner\antigravity"
```

Then in the IDE's agent panel: "Read TASK_BRIEF.md and CONTEXT.md, then do the task described.
Run the test suite before you're done. Write a short NOTES.md of what you did." Commit from the
IDE's source control panel or a terminal inside it (this worked fine — no sandbox restriction issue
in the interactive/GUI path, unlike Codex's headless sandbox).
