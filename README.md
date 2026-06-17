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

```sh
brew tap qkdxorjs1002/tap
brew trust --formula qkdxorjs1002/tap/taplctl
brew install taplctl

taplctl install user
taplctl install repo
taplctl doctor --json
```

## How does it work?

The point is not another prompt template. The point is that a normal Codex CLI
request now has state around it. The capture-style image below mirrors the
commands `tapl` recorded around this README rewrite.

<p align="center">
  <img src="assets/tapl-codex-iterm-demo.svg" alt="Terminal-style capture of Codex CLI using tapl state before editing README files" />
</p>

That terminal flow is the workflow contract `tapl` exposes to Codex:

```sh
taplctl status --json
taplctl search 'README self PR codex cli screenshot' --json
taplctl plan upsert --id SPEC-README-SELF-PR ...
taplctl task upsert --id TASK-README-001 ...
taplctl approval record --decision approved ...
```

The state lives in `.tapl/tapl.db`, so the next Codex session, a hook, a human,
or the VS Code viewer can inspect the same run.

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
use. Hooks call `taplctl`, lifecycle context tells Codex what state to
record.

### 1. State before edits

`taplctl status --json` is the source of truth for the current run.

```json
{
  "active_run": {
    "request_summary": "Rewrite README.* as self-PR docs..."
  },
  "approvals": {
    "execution": {
      "state": "approved"
    }
  },
  "task_counts": {
    "In Progress": 1,
    "Pending": 3
  }
}
```

Hooks can warn or block when the workflow contract is missing. The agent can
resume from the stored state instead of guessing from chat history.

### 2. Plans and tasks that tools can read

Plans and tasks are first-class records, not loose Markdown notes.

```sh
taplctl plan upsert \
  --id SPEC-EXAMPLE \
  --title "Example implementation plan" \
  --summary "REQ-001: approach, files, order, risks, validation" \
  --status Finalized \
  --json

taplctl task upsert \
  --id TASK-EXAMPLE \
  --title "Implement the change" \
  --status "In Progress" \
  --spec-id SPEC-EXAMPLE \
  --goal "Make the requested behavior work" \
  --action "Edit the relevant files" \
  --required-subagent "@senior-worker" \
  --verification "Run focused checks" \
  --json
```

The configured workflow guidance is injected into Codex lifecycle context, and
the exact field rules stay in command help:

```sh
taplctl plan upsert --help
taplctl task upsert --help
taplctl approval record --help
```

### 3. Searchable history for completed work

Past work is archived and searchable.

```sh
taplctl finding add \
  --title "Important implementation note" \
  --finding "What was learned" \
  --impact "Why it matters" \
  --json

taplctl archive create \
  --slug completed-change \
  --summary "What changed, how it was verified, and what remains" \
  --json

taplctl search "workflow dashboard" --json
taplctl search "workflow dashboard" --limit 5 --json
```

Search uses SQLite FTS, with optional semantic/vector search when the semantic
dependencies are installed.

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
taplctl item show --json
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
brew install taplctl
```

For semantic search support:

```sh
brew install taplctl-semantic
```

Then wire it into Codex:

```sh
# user-level Codex hook and agent templates
taplctl install user

# repo-local hooks, config, and .tapl/tapl.db
taplctl install repo

taplctl validate --json
```

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

## Command Map

```sh
taplctl init
taplctl doctor --json
taplctl status --json
taplctl validate --json
taplctl context --event UserPromptSubmit --json
taplctl run summary --summary "..." --json
taplctl plan upsert --help
taplctl task upsert --help
taplctl finding add --help
taplctl approval record --help
taplctl archive create --help
taplctl search "query" --json
taplctl reindex --json
```

`taplctl search` returns 7 results by default. Set `[search] max_results` in
`.tapl/config.toml` or `~/.tapl/config.toml` to change the default, and use
`--limit` for one-off overrides.

Plan/task validation is controlled by `[plan-task-execute]` in the same config
files. Settings such as `plan_detail`, `task_granularity`,
`level_subagent_aggressiveness`, and `require_execution_approval` are reflected
in lifecycle context and validation issues.

## Repository Layout

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

## Development Checks

```sh
uv --directory tapl sync --extra test
uv --directory tapl run --extra test python -m unittest discover -s tests
uv --directory tapl build
npm --prefix vscode-extension run compile
git diff --check
taplctl validate --json
```

## License

MIT. See [LICENSE.md](LICENSE.md).
