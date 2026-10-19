# Concurrent work with Git worktrees

Use one worktree and one branch for each independent task. The existing checkout
can continue on `main`; worktrees share Git objects but have separate files and
working state.

## Create a task workspace

From the primary checkout, first inspect its status and choose a unique task name.
Then create a branch and worktree from the current `main`:

```sh
git status --short
git worktree add -b feature/task-name ../tally-task-name main
cd ../tally-task-name
```

If the task continues an existing branch, omit `-b` and use that branch name:

```sh
git worktree add ../tally-task-name feature/existing-branch
```

Do not check out the same branch in two worktrees. Keep commits scoped to the task
branch, then merge or rebase through the normal repository workflow. Before starting
work, inspect `git status --short` in that worktree too.

## Keep development instances separate

When running the app from multiple worktrees, use a distinct Compose project name,
port and cookie names for each task. Compose project names isolate database and
backup volumes; unique ports avoid bind conflicts, and unique cookies keep browser
sessions separate. For example:

```sh
make demo TALLY_INSTANCE_NAME=tally-task-name TALLY_DEV_PORT=8012 \
  TALLY_SESSION_COOKIE_NAME=tally_task_name_session \
  TALLY_CSRF_COOKIE_NAME=tally_task_name_csrf
```

Use the same values for later `make login`, `make logs` and `make down` commands.
Only seed a disposable, empty instance with fictional demo data. Never point a task
worktree at another portfolio's Compose project or database. Do not reuse one Compose
project name from different worktrees: Compose could replace a running container
with a bind mount from the other checkout.

For local Python development, create a virtual environment separately in each
worktree and install `requirements-dev.txt`. A `.venv` from another worktree is not
shared automatically.

## Playwright MCP coordination

The configured Playwright MCP is a shared browser service with persistent browser
state. Its current configuration runs `npx @playwright/mcp@latest` without
`--isolated`; attempting to start another instance against the same profile reports
that the browser profile is already in use. The MCP tools also operate on shared
tabs, so different tabs do not make simultaneous actions safe.

For now, allow only one context at a time to navigate or interact through Playwright
MCP. Other contexts can continue code, review and command-line work. Coordinate the
browser handoff explicitly and leave the page in a known state when finished.

The Playwright MCP supports `--isolated`, which keeps browser state in memory. To
run browser checks concurrently, each context must have its own separately
configured MCP server session using that flag; separate contexts pointed at the
same MCP session still share its tabs. The current shared MCP integration does not
provide per-worktree sessions, so do not claim parallel browser isolation until
those separate sessions are configured and confirmed. Isolated sessions start with
fresh browser state, so log in using the disposable instance's credentials as
needed. Never put credentials in screenshots or logs.

## Finish and remove a worktree

Commit or otherwise preserve the task work, then remove its worktree after it is no
longer needed:

```sh
git worktree remove ../tally-task-name
```

Stop its disposable Compose instance first with the same project name and options.
Git refuses removal when the worktree has uncommitted changes unless `--force` is
used; inspect and preserve those changes instead of forcing removal. Remove the
branch only after its changes have been merged and the branch is no longer needed.
