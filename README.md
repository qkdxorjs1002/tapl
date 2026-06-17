<p align="center">
  <img src="assets/tapl-readme-hero-with-text.png" alt="tapl: Harness over prompting. State over files." />
</p>

# tapl

[한국어](README.ko.md)

`tapl` is a workflow harness for Codex. It installs one user-global
`taplctl` command, keeps each repository's workflow state local in SQLite, and
uses Codex hooks to make agent work traceable, resumable, and inspectable.

## Introduction

Agent work often starts as a prompt, but real engineering work needs more than
prompt text. It needs a current plan, executable tasks, findings, lifecycle
events, searchable history, and a clear point where tool use can be observed or
blocked.

`tapl` provides that small control plane. It does not replace the agent. It gives
the agent a durable workflow surface that survives context compression, session
resumes, and long-running repository work.

## What It Is

`tapl` is made of five pieces:

- `taplctl`: the CLI used by agents, hooks, humans, and the VS Code viewer.
- `.tapl/tapl.db`: a repo-local SQLite database for active runs, plans, tasks,
  findings, approvals, events, archives, and embeddings.
- Codex hooks: lifecycle wiring for `UserPromptSubmit`, `PreToolUse`,
  `PermissionRequest`, `PostToolUse`, and `Stop`.
- Lifecycle context: short state-aware instructions generated from the current
  repo DB and config.
- Search and archive tools: FTS and semantic search over current and completed
  work.

The installed command is global; the workflow state is local to the repository.
That split keeps installation simple while preventing one workspace's state from
leaking into another.

## Why Use It

Use `tapl` when Codex work should be auditable and recoverable:

- Long tasks can be resumed from stored plan/task state.
- Prior decisions and findings can be searched instead of rediscovered.
- Hooks can warn before durable edits happen without active workflow state.
- Completed work can be archived into searchable history.
- Human and agent views read the same SQLite state through the same CLI.
- A repository no longer needs `AGENTS.md` to act as the workflow source of
  truth.

The practical result is less dependence on prompt memory and more dependence on
state that tools can inspect.

## Philosophy

- **Harness over prompting**: prompts guide intent; hooks and state hold the
  workflow boundary.
- **State over files**: active workflow records live in SQLite instead of a
  scattered pile of Markdown files.
- **Search over manual indexes**: past work should be discoverable without
  maintaining a hand-written index.
- **Observe before enforce**: start by recording lifecycle events and warnings;
  turn on blocking only where the workflow has proven useful.
- **Global command, repo-local state**: install `taplctl` once, keep each
  repository's `.tapl/tapl.db` separate.
- **Agent and hook separation**: the agent interprets user intent; hooks guard
  lifecycle and tool-use boundaries.

## Principles

`tapl` follows a small operating model:

1. Codex starts or receives a prompt.
2. Hooks call `taplctl hook-event` and load the current repo state.
3. The agent inspects `taplctl status` and searches prior work when the task is
   non-trivial.
4. The agent records a plan and executable tasks before durable edits.
5. `PreToolUse` and `PostToolUse` hooks observe or enforce the workflow
   boundary.
6. Completed work is archived and can be found later with `taplctl search`.

The source templates used by installation live in `tapl/.codex` and
`tapl/.tapl/config.toml`. `taplctl install user` and `taplctl install repo`
copy those templates into the user Codex home, user tapl config directory, or
target repository as needed. Runtime config is resolved from the repo
`.tapl/config.toml` first, then `~/.tapl/config.toml`.

## Installation

### Requirements

- Python 3.11 or newer. The bundled Homebrew formula uses `python@3.12`.
- SQLite with FTS5 and extension loading support.
- Homebrew, if installing with the bundled formula.
- `uv`, if developing or building from source.
- VS Code, only if you want the optional workflow viewer.

### Install `taplctl`

For Homebrew:

```sh
brew tap qkdxorjs1002/tap
brew trust --formula qkdxorjs1002/tap/taplctl
brew install taplctl
# with semantic search dependency
brew install taplctl-semantic
```

Then install Codex workflow wiring:

```sh
# For ~/
taplctl install user

# For repo
taplctl install repo

taplctl doctor --json
```

`install user` writes user-level Codex hook and agent templates plus
`~/.tapl/config.toml`. `install repo` writes repo-local hook/config files and
initializes `.tapl/tapl.db`.

Codex install merge policy:

- `hooks.json` is managed-merged: existing non-tapl hooks are preserved, and
  tapl-managed hooks are replaced.
- `config.toml` is TOML-merged: if missing, it is created from the tapl
  template; if present, existing user values win and only missing tapl template
  keys are added. Nested tables such as `[features]` are merged recursively.
- `--force` makes tapl template values win for managed `config.toml` keys while
  preserving unrelated user keys. If the existing TOML cannot be parsed,
  `--force` replaces it with the template.
- Agent templates are create-or-skip by default and are overwritten with
  `--force`.

For source development:

```sh
cd tapl
uv sync
uv run taplctl --version
uv build
```

## Usage

Inspect the current workflow state:

```sh
taplctl status --json
taplctl validate --json
taplctl context --event UserPromptSubmit --json
```

Lifecycle context stays focused on state, workflow order, and next actions.
Command syntax, field-writing rules, statuses, subagent values, and examples live
in command help:

```sh
taplctl --help
taplctl plan upsert --help
taplctl task upsert --help
taplctl approval record --help
```

Record a plan:

```sh
taplctl plan upsert \
  --id SPEC-EXAMPLE \
  --title "Example implementation plan" \
  --summary "REQ-001: Explain the approach, affected files, execution order, risks, and validation." \
  --status Finalized \
  --json
```

Record executable tasks:

```sh
taplctl task upsert \
  --id TASK-EXAMPLE \
  --title "Implement the change" \
  --status "In Progress" \
  --spec-id SPEC-EXAMPLE \
  --goal "Make the requested change" \
  --action "Edit the relevant files" \
  --required-subagent "@junior-worker" \
  --verification "Run focused checks" \
  --json
```

Before durable edits, record explicit execution approval:

```sh
taplctl approval record \
  --decision approved \
  --prompt "Execute TASK-EXAMPLE from SPEC-EXAMPLE" \
  --json

taplctl approval status --json
```

If a new prompt arrives while executable tasks remain, the lifecycle context
instructs the agent to ask whether to finish the remaining work first, combine
it with the new request, defer or archive it, or discard the active run and
start fresh.

Add findings and search history:

```sh
taplctl finding add \
  --title "Important implementation note" \
  --finding "What was learned" \
  --impact "Why it matters" \
  --json

taplctl search "workflow dashboard" --json
taplctl search "workflow dashboard" --limit 5 --json
```

`taplctl search` returns 7 results by default. Set `[search] max_results = 12`
in `.tapl/config.toml` or `~/.tapl/config.toml` to change the default, and use
`--limit` for one-off overrides.

Archive completed work:

```sh
taplctl archive create \
  --slug completed-change \
  --summary "What was completed and how it was verified" \
  --json
```

Completion reports should briefly state changed files and behavior,
verification commands and results, remaining risks or blocked work, and whether
the workflow was archived. Archive summaries should compactly capture the
original request, selected plan, completed tasks and results, verification, and
remaining work.

Rebuild the semantic search index:

```sh
taplctl reindex --json
```

The VS Code extension in `vscode-extension/` reads the same state through
`taplctl status`, `taplctl archive list`, `taplctl search`, and
`taplctl item show`.

## Dependency List

Runtime dependencies from `tapl/pyproject.toml`:

| Dependency | Purpose |
| --- | --- |
| Python `>=3.11` | Runtime for the `taplctl` CLI. |
| `numpy>=1.26` | Numeric support for embedding and vector operations. |
| `sentence-transformers>=5.0.0` | Semantic embeddings for archive/search. |
| `sqlite-vec>=0.1.6` | SQLite vector search extension. |
| SQLite FTS5 | Keyword search fallback and hybrid search support. |

Development and packaging dependencies:

| Dependency | Purpose |
| --- | --- |
| `uv` | Source environment, lockfile, and package build workflow. |
| `pytest>=8` | Python test dependency. |
| `pyyaml>=6.0` | Test/development dependency. |
| Homebrew | Local formula install and formula testing. |
| Node.js and npm | VS Code extension build workflow. |
| TypeScript | Compile `vscode-extension/src` into `vscode-extension/out`. |
| VS Code `^1.90.0` | Optional workflow viewer host. |

After installation, `taplctl doctor --json` reports dependency status:

```json
{
  "numpy": true,
  "sentence_transformers": true,
  "sqlite_vec": true
}
```

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
├── tap/Formula/taplctl.rb     # Homebrew formula
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
ruby -c tap/Formula/taplctl.rb
git diff --check
taplctl validate --json
```

## License

MIT. See [LICENSE.md](LICENSE.md).
