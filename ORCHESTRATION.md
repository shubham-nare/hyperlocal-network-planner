# Multi-agent orchestration: Claude / Codex / Antigravity

Set up 2026-09-15. Read this once; `TASKS.md` is the day-to-day board.

## Why this exists

Three different agent CLIs are installed on this machine (Claude Code, Codex CLI, Antigravity IDE).
They cannot talk to each other directly — no shared protocol between vendors. This document is the
manual scaffolding that lets them work on the same project without stepping on each other: git
worktrees for isolation, this repo's filesystem for coordination, and a human (or Claude, as lead)
in the loop to assign, review and merge.

## Roles

- **Claude (lead)** — works in the **main worktree** (this folder, branch `main`). Writes task briefs,
  reviews diffs from the other two, gives feedback, merges finished branches into `main`, keeps
  `CONTEXT.md` and `TASKS.md` current. Claude is the only one who touches `CONTEXT.md` — the other two
  write their own worktree-local `NOTES.md` instead, which Claude folds into `CONTEXT.md` at merge time
  (the project's standing rule is one CONTEXT.md per project folder; see the global CLAUDE.md rule).
- **Codex** — fully scriptable. Runs non-interactively via `codex exec` in its own worktree/branch.
  Claude can launch it, read its diff, and re-launch it with feedback without any human step in between.
- **Antigravity** — **not** scriptable. It's a GUI IDE (VS Code fork) with an agent chat panel, not a
  headless CLI. There is no `antigravity exec`. Its loop needs a human: Shubham opens the IDE on
  Antigravity's worktree, pastes/points it at that worktree's `TASK_BRIEF.md`, runs its agent there,
  then either reports back or commits — Claude reviews via `git diff` same as for Codex.

## Layout

```
Hyperlocal Network Planner/              <- main worktree, branch main. Claude works here.
  ORCHESTRATION.md                        <- this file
  TASKS.md                                <- the board (backlog / assigned / in review / done)
  tasks/task-XX-*.md                      <- task briefs Claude writes, one per assignment

C:\Users\Shubham\.worktrees\hyperlocal-network-planner\
  codex\                                  <- branch codex/work. Codex works here via `codex exec`.
    TASK_BRIEF.md                         <- current assignment (Claude writes/updates this)
    NOTES.md                              <- Codex's own log of what it did/decided
  antigravity\                            <- branch antigravity/work. Shubham + Antigravity IDE work here.
    TASK_BRIEF.md
    NOTES.md
```

Worktrees live **outside OneDrive** (`C:\Users\Shubham\.worktrees\...`) on purpose: two agents writing
many small files inside a synced folder fights with OneDrive's own file locking and generates sync
noise. All three worktrees share one `.git` object database, so `git log`/`git branch` from any of them
sees all the others' commits even before anything is merged.

## Shared vs. per-branch state

`.venv`, `data/`, and `cache/` are **junctioned** (Windows directory junctions) from each worktree back
to the main worktree's copies — not duplicated. This is deliberate: the WorldPop raster alone is 784 MB,
and reinstalling the venv three times is wasteful for one machine. The consequence: **these are shared,
mutable, and not git-tracked** (per `.gitignore`). Rules that follow from that:

- A task that only **reads** `data/processed/*.gpkg` (the simulator, memos, new analysis scripts) is
  always safe to run in any worktree at any time.
- A task that **regenerates** pipeline outputs (`build_study_area.py`, `build_demand.py`,
  `build_stores.py`, `build_coverage.py`, `optimize_network.py` writing back into `data/processed`) is
  writing into the *same physical files* every worktree sees. Only one agent should be doing this at a
  time; say so explicitly in the task brief, and prefer writing new outputs into `reports/` (which is
  real per-branch content, not junctioned) instead of overwriting `data/processed`.
- `config/*.yaml`, `src/`, `tests/`, `app/`, `scripts/`, `reports/` are ordinary git-tracked files —
  each worktree has its own real copy on its own branch, exactly as intended.

## Workflow

1. **Claude writes a task brief** (`tasks/task-XX-<slug>.md` in main, copied/adapted as
   `TASK_BRIEF.md` into the target worktree). A brief states: goal, acceptance criteria (tests to add/
   pass, a command that proves it works), files it's expected to touch, files it must **not** touch
   (to avoid merge conflicts with the other agent's parallel task), and what NOT to do (e.g. "don't
   touch CONTEXT.md", "don't regenerate data/processed").
2. **Codex**: Claude runs
   `codex exec -C <worktree> --sandbox workspace-write -o <worktree>/last_message.txt "$(cat TASK_BRIEF.md)"`
   (see `tasks/README.md` for the exact command). Codex works, commits its own changes on `codex/work`.
3. **Antigravity**: Shubham runs `antigravity-ide "C:\Users\Shubham\.worktrees\hyperlocal-network-planner\antigravity"`,
   opens the agent panel, points it at `TASK_BRIEF.md`, and lets it work. Commits happen from inside
   the IDE or Shubham runs `git add -A && git commit` in that worktree afterwards.
4. **Claude reviews**: `git -C <worktree> log -p codex/work` (or `antigravity/work`) since the branch
   point, or `git diff main...codex/work`. Claude checks it against the brief's acceptance criteria,
   runs the tests itself from that worktree, and either:
   - **merges** (`git checkout main && git merge codex/work`), and folds the worktree's `NOTES.md`
     into `CONTEXT.md`, or
   - **sends feedback**: updates `TASK_BRIEF.md` in that worktree with what to fix and re-runs
     Codex (or asks Shubham to relay the feedback into Antigravity's chat).
5. Update `TASKS.md` at every step so the board reflects reality even if the session restarts.

## Conflict avoidance

Because both side-agents may be active around the same time, task briefs are written to touch
**disjoint files** wherever possible. If two tasks must touch the same file, they are sequenced
(one waits for the other to merge) rather than run in parallel. Claude decides this when writing briefs.

## Known limits (stated once, not repeated in every brief)

- Antigravity's step always needs Shubham at the keyboard; it cannot be kicked off unattended.
- `codex exec` costs real API usage per run — Claude should batch feedback rather than re-running for
  every tiny nit.
- Junctions mean `data/processed` writes are immediately visible (and immediately overwritable) from
  every worktree, including main. Treat that directory as a shared, uncommitted cache, not
  branch-private state.
