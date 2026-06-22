<p align="center">
  <img src="assets/tapl-readme-hero-with-text.png" alt="tapl: Harness over prompting. State over files." />
</p>

# tapl

[한국어](README.ko.md)

`tapl` helps Codex CLI keep track of coding work inside a repository. For each
request, it stores the user's instruction, Codex's plan, tasks, findings,
approvals, lifecycle events, archives, and searchable history in a repo-local
SQLite database. Codex still writes the code; `tapl` makes the work visible
while it is happening and resumable after the chat context is gone.

## Quick Start

Follow [Install Details](#install-details) once, then keep using Codex normally
inside your repositories.

## How does it work?

The point is not another prompt template. The point is that a normal Codex CLI
request now has state around it. The capture-style image below mirrors the
commands `tapl` recorded around this README rewrite.

<p align="center">
  <img src="assets/tapl-codex-iterm-demo.svg" alt="Terminal-style capture of Codex CLI using tapl state before editing README files" />
</p>

After installation, keep using Codex normally. `tapl` gives Codex a
repo-local workflow state before tool calls, records plans and tasks as the
work progresses, and validates the run before Codex stops. You usually do not
need to run the workflow-writing commands yourself.

The state lives in `.tapl/tapl.db`, so the next Codex session, a hook, you, or
the VS Code viewer can inspect the same run.

## Why This Exists

Codex sessions are good at doing work. Long-running engineering work needs more
than the latest prompt:

- What did the user ask for?
- What plan did the agent choose?
- Which tasks are still pending?
- Was durable file editing approved?
- What did the agent learn during implementation?
- Can a later session search that history instead of rediscovering it?

`tapl` answers those questions with one global CLI and one repo-local SQLite
database.

## Features

After installation, this workflow runs automatically during normal Codex CLI
use. Hooks call `taplctl`, lifecycle context tells Codex what state to record,
and you can inspect or validate that state when you want to understand what
Codex is doing.

### 1. Check the current Codex run

Use these commands when you want to see what Codex has recorded for the current
repository:

```sh
taplctl status
taplctl validate
```

`status` shows the active request, plans, tasks, findings, approval state, and
recent activity. `validate` reports missing plan/task/approval records that may
make a long Codex session harder to resume.

For integrations, `--json` remains available. Codex hooks use `--agent`
internally for compact output that Codex can read efficiently; it is not the
normal human-facing mode.

### 2. Let Codex record plans and tasks

Plans and tasks are first-class records, not loose Markdown notes.
Codex receives lifecycle guidance from `tapl`, writes plan/task content through
structured CLI fields, and `tapl` renders stable Markdown bodies for stored
records.

For normal use, ask Codex to do the work and let the installed hooks keep the
records current. If you are debugging or manually repairing workflow state, the
field rules are available in command help:

```sh
taplctl plan set --help
taplctl task set --help
taplctl approval set --help
```

### 3. Searchable history for completed work

Past work is archived and searchable.

```sh
taplctl search "workflow dashboard"
taplctl search "workflow dashboard" --limit 5
taplctl item show --id 1
```

Search uses SQLite FTS, with optional semantic/vector search when the semantic
dependencies are installed. Use `taplctl archive list` and
`taplctl archive show --id <id>` to inspect completed runs.

### 4. Hooks around the Codex lifecycle

`tapl` installs Codex hook wiring for:

- `UserPromptSubmit`
- `PreToolUse`
- `PermissionRequest`
- `PostToolUse`
- `Stop`

Those hooks call `taplctl hook-event`, load the current workflow state, and
return concise lifecycle context. The agent interprets intent; hooks guard the
boundary.

### 5. One CLI, repo-local state

Install `taplctl` once. Each repository keeps its own `.tapl/tapl.db`.

That split keeps installation simple while preventing one workspace's workflow
state from leaking into another.

### 6. Optional VS Code viewer

The VS Code extension in `vscode-extension/` reads the same state through:

```sh
taplctl status --json
taplctl archive list --json
taplctl search --json
taplctl item show --id <id> --json
```

It gives you an activity-bar view over active runs, plans, tasks, findings,
archives, and search results.

## Install Details

### Requirements

- Python 3.11 or newer. The bundled Homebrew formula uses `python@3.12`.
- SQLite with FTS5 and extension loading support.
- Homebrew, if installing with the bundled formula.
- `uv`, if developing or building from source.
- VS Code, only if you want the optional workflow viewer.

### Homebrew

```sh
brew tap qkdxorjs1002/tap
brew trust --formula qkdxorjs1002/tap/taplctl
```

Then install one of the two formulas:

```sh
# Basic workflow tracking
brew install taplctl
```

```sh
# Workflow tracking with semantic search support
brew install taplctl-semantic
```

If you chose `taplctl-semantic`, you can keep the semantic search model
pre-loaded:

```sh
brew services start taplctl-semantic
```

Then choose how to wire it into Codex:

```sh
# Most users: install once for your Codex account
taplctl install user

# Or install only in the current repository
taplctl install repo

taplctl validate
```

The first time Codex asks for confirmation after installation, trust the
installed hook.

<p align="center">
  <img src="assets/tapl-trust-hook.png" alt="Codex trust prompt for the installed tapl hook" />
</p>

Install merge policy:

- `hooks.json` is managed-merged. Existing non-tapl hooks are preserved; tapl
  managed hooks are replaced.
- `config.toml` is TOML-merged. Existing user values win, and missing tapl
  template keys are added.
- `--force` makes tapl template values win for managed keys while preserving
  unrelated user keys.
- Agent templates are create-or-skip by default and are overwritten with
  `--force`.

### Source

```sh
cd tapl
uv sync
uv run taplctl --version
uv build
```

## Useful Commands

```sh
taplctl init
taplctl doctor
taplctl status
taplctl validate
taplctl search "query"
taplctl item show --id 1
taplctl archive list
taplctl archive show --id <id>
taplctl reindex

# Advanced workflow repair/debugging
taplctl run set --help
taplctl plan set --help
taplctl task set --help
taplctl finding add --help
taplctl approval set --help
taplctl archive create --help
```

`taplctl search` returns 7 results by default. Set `[search] max_results` in
`.tapl/config.toml` or `~/.tapl/config.toml` to change the default, and use
`--limit` for one-off overrides. When a search result is relevant and the
snippet is not enough context, use its numeric `id` with
`taplctl item show --id <id>` before relying on the full record details.

Plan/task validation is controlled by `[plan-task-execute]` in the same config
files. Settings such as `plan_detail`, `task_granularity`,
`planning_approval_level`, `level_subagent_aggressiveness`, and
`require_execution_approval` are reflected in lifecycle context and validation
issues.

## Source Layout

```text
.
├── .codex/                    # Repo-local files produced by taplctl install repo
├── .tapl/config.toml          # Repo-local runtime config
├── tapl/.codex/               # Codex hook and agent templates packaged with taplctl
├── tapl/.tapl/config.toml     # Default tapl config template
├── tapl/taplctl/              # Python CLI and workflow harness implementation
├── tapl/tests/                # Python tests
├── tapl/pyproject.toml        # taplctl package metadata
├── vscode-extension/          # Optional VS Code workflow viewer
├── README.md                  # English README
└── README.ko.md               # Korean README
```

Runtime state and local build output are intentionally not part of the source
contract:

```text
.tapl/tapl.db
tapl/.venv/
tapl/dist/
```

## Contributor Checks

```sh
uv --directory tapl sync --extra test
uv --directory tapl run --extra test python -m unittest discover -s tests
uv --directory tapl build
npm --prefix vscode-extension run compile
git diff --check
taplctl validate
```

## License

MIT. See [LICENSE.md](LICENSE.md).
