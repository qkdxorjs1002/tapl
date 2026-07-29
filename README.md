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
field rules and required field sets are available in command help. `--config`
controls search behavior only; task help and validation always use TAPL's fixed
workflow policy:

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

### 5. One CLI, workspace-local state

Install `taplctl` once. Each Codex workspace keeps its state in
`.tapl/tapl.db`, which also acts as the workspace anchor. On the first hook
event, `tapl` explicitly initializes the payload working directory when no
ancestor database exists. Nested Git repositories then reuse that workspace
database instead of creating separate history databases.

To select the workspace root manually, run:

```sh
taplctl init --workspace-root /path/to/workspace
```

An intentionally independent nested repository can initialize its own
`.tapl/tapl.db`.

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

### 7. Parallel SubAgent dispatch

TAPL is the repo-local SQLite state store, validator, and execution-manifest
coordinator. It does **not** spawn workers itself: the Codex/root runtime
spawns and manages the actual SubAgents. Sequential tasks run on the main
agent by default; use parallel dispatch only for independent work that can be
given exclusive file or directory scopes.

Create compatible `Pending` tasks in one plan and one non-empty group. Each
parallel task must declare `parallel` mode, the `subagent` executor, and its
exclusive owned paths. Dependencies are optional, but every listed dependency
must already be `Completed` before dispatch.

```sh
# TASK-004 is already Completed. These two tasks own separate paths.
taplctl task create --id TASK-005 --title 'Add focused tests' --status Pending \
  --spec-id PLAN-001 --goal 'Cover parallel dispatch behavior' \
  --action 'Add focused CLI tests' --verification 'Run the focused test suite' \
  --execution-mode parallel --executor-kind subagent --parallel-group dispatch-docs \
  --owned-path tapl/tests/test_tapl.py --owned-path tapl/tests/fixtures \
  --depends-on TASK-004 --agent

taplctl task create --id TASK-006 --title 'Document parallel dispatch' --status Pending \
  --spec-id PLAN-001 --goal 'Document the supported workflow' \
  --action 'Update the user documentation' --verification 'Review the README examples' \
  --execution-mode parallel --executor-kind subagent --parallel-group dispatch-docs \
  --owned-path README.md --depends-on TASK-004 --agent
```

Dispatch two or more compatible `Pending` tasks in the same group atomically.
`--batch-id` makes a retry identifiable, and `--execution-metadata` records
the intended executor reference, model, and reasoning effort for every task.
The command prints one manifest row per task, including its `execution_id`.

```sh
taplctl task dispatch TASK-005 TASK-006 --batch-id docs-20260727 \
  --execution-metadata '{
    "TASK-005": {"executor_ref": "tests-worker", "model": "gpt-5.6-terra", "reasoning_effort": "high"},
    "TASK-006": {"executor_ref": "docs-worker", "model": "gpt-5.6-terra", "reasoning_effort": "high"}
  }' --agent
```

The root agent reads that manifest, concurrently spawns a different SubAgent
for each returned task and `execution_id`, and keeps each worker within its
declared paths. Only the root agent writes TAPL state. It settles each result
with the exact manifest ID—never by directly editing a batch-managed status:

```sh
taplctl task complete TASK-005 --execution-id <execution-id-for-TASK-005> \
  --verification 'uv run python -m unittest tests.test_tapl' \
  --result 'Focused dispatch coverage passed' --agent
taplctl task block TASK-006 --execution-id <execution-id-for-TASK-006> \
  --verification 'README review' --blocker 'Required product decision is unavailable' \
  --next-action 'Obtain the decision and redispatch the task' --agent
taplctl task skip TASK-006 --execution-id <execution-id-for-TASK-006> \
  --result 'No longer needed after the plan changed' --agent
```

Dispatch rejects tasks with unmet dependencies, mixed plans or groups, paths
that overlap (including a file and its parent directory), or other active work
that conflicts with their owned paths. Tasks in one group must be independent;
do not make one depend on another member of that same group. If any worker
cannot be spawned, or the root runtime is interrupted, settle what ran and
recover or cancel the entire active batch before retrying:

```sh
taplctl batch recover docs-20260727 --reason 'Root runtime interrupted' --agent
taplctl batch cancel docs-20260727 --block \
  --reason 'One worker could not be started' --agent
```

Use `taplctl status --agent` to inspect active batches and execution IDs, and
`taplctl next --agent` for the safest follow-up command. Do not start a second
batch while the current batch remains active.

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
- `.codex/config.toml` is TOML-merged. Existing user values win, and missing
  tapl template keys are added.
- tapl runtime `config.toml` (`.tapl/config.toml` or `~/.tapl/config.toml`) is
  created on first install. When the installed tapl version changes, tapl asks
  whether to overwrite it with updated defaults or keep existing values and add
  missing default keys. Non-interactive hook/JSON refreshes keep existing
  values and add missing keys.
- `--force` makes tapl template values win for managed keys while preserving
  unrelated Codex config keys, and overwrites tapl runtime `config.toml`.
- `--tapl-config-policy {prompt,overwrite,merge}` selects the tapl runtime
  config upgrade behavior explicitly.
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
taplctl init --workspace-root /path/to/workspace
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

### SubAgent delegation configuration

TAPL loads the repo-local `.tapl/config.toml` before `~/.tapl/config.toml`, so
the repository configuration takes precedence when both files exist. Configure
whether TAPL injects its delegation policy and the model/reasoning allowlist
into the agent prompt as follows:

```toml
[subagents]
enabled = true

[subagents.models]
"gpt-5.6-sol" = ["xhigh", "max"]
"gpt-5.6-terra" = ["high", "xhigh", "max"]
"gpt-5.6-luna" = ["high", "xhigh"]
```

When enabled, the injected policy tells the root agent to assess the complexity
of every executable task and delegate it using an efficient configured
model/reasoning pair. To disable that TAPL-provided prompt content, set:

```toml
[subagents]
enabled = false
```

With `enabled = false`, TAPL injects neither its SubAgent delegation policy
nor its model/reasoning allowlist. This setting does not remove separate
delegation instructions from another source, such as `AGENTS.md`.

The configured model list is a policy allowlist, not a runtime installation or
capability guarantee. A root agent must use only the intersection of the
configured model/reasoning pairs and the pairs its current runtime actually
supports; unavailable configured pairs must not be selected. If that
intersection is empty, the root agent executes the task directly.

Plan/task workflow policy is fixed rather than configurable. TAPL always asks
for a very detailed plan, explicit user confirmation before plan finalization,
independently split edit/migration/verification tasks, and recorded execution
approval before durable edits. `taplctl task set --help` always shows the same
required task field set.

## Source Layout

```text
.
├── .codex/                    # Repo-local files produced by taplctl install repo
├── .tapl/config.toml          # Repo-local runtime config
├── tapl/.codex/               # Codex config and hook templates packaged with taplctl
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
