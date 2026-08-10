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

The point is not another prompt template. TAPL exposes typed MCP tools backed by
the existing CLI and repo-local state, so Codex receives the workflow contract
once from the MCP server instead of repeatedly reading CLI help. The capture-style image below mirrors the
commands `tapl` recorded around this README rewrite.

<p align="center">
  <img src="assets/tapl-codex-iterm-demo.svg" alt="Terminal-style capture of Codex CLI using tapl state before editing README files" />
</p>

After installation, keep using Codex normally. The TAPL MCP server gives Codex
typed workflow tools and invariant guidance. Hooks add only concise current-state
context and enforce durable-edit boundaries. You usually do not need to run the
workflow-writing commands yourself.

The state lives in `.tapl/tapl.db`, so the next Codex session, a hook, you, or
the browser or VS Code viewer can inspect the same run.

## Why This Exists

Codex sessions are good at doing work. Long-running engineering work needs more
than the latest prompt:

- What did the user ask for?
- What plan did the agent choose?
- Which tasks are still pending?
- Was durable file editing approved?
- What did the agent learn during implementation?
- Can a later session search that history instead of rediscovering it?

`tapl` answers those questions with one global CLI, a typed MCP facade, and one
repo-local SQLite database.

## Features

After installation, this workflow runs automatically during normal Codex CLI
use. MCP tools map structured calls to `taplctl`, while hooks return concise
lifecycle state. You can inspect or validate that state when you want to
understand what Codex is doing.

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

Plans and tasks are first-class records, not loose Markdown notes. Codex receives
lifecycle guidance from the MCP server, writes plan/task content through typed
MCP tool fields, and `tapl` renders stable Markdown bodies for stored records.

For normal use, ask Codex to do the work and let the installed MCP server and
hooks keep the records current. MCP tool descriptions and JSON schemas are the
authoritative agent field contract. CLI help remains available for human
operation, diagnostics, and manual repair; it documents flags rather than the
agent workflow prompt:

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
return concise lifecycle context. The MCP server owns invariant guidance and
typed tool contracts; hooks guard the current-state boundary.

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

### 6. Browser and optional VS Code viewers

Start the bundled browser viewer from an initialized workspace:

```sh
taplctl viewer
# tapl viewer: http://127.0.0.1:8000

# Choose another local port when 8000 is busy
taplctl viewer --port 9000
```

Open the printed URL in a browser. The server listens only on the local
loopback interface, does not open the browser automatically, and exposes only
viewer read operations. Stop a foreground server with `Ctrl+C`.

When the command starts inside a workspace, its nearest `.tapl/tapl.db` wins.
When it starts without one—such as a Homebrew login service—the page asks for
an initialized workspace folder and remembers the last successful path in that
browser. An explicit database can also be selected before the subcommand:

```sh
taplctl --db /path/to/workspace/.tapl/tapl.db viewer
```

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

- Python 3.11 or newer with the `venv` module. The bundled Homebrew formula
  uses `python@3.12`.
- SQLite with FTS5 and extension loading support.
- For the Windows standalone installer: Windows 10 or 11 and either Windows
  PowerShell 5.1 or newer, or PowerShell 7.
- Homebrew, if installing with the bundled formula.
- `uv`, if developing or building from source.
- A web browser for `taplctl viewer`; VS Code only for the optional extension.

### Linux (`curl | sh`)

The standalone installer supports Linux and installs the `taplctl` CLI with
the bundled browser viewer:

```sh
curl -fsSL https://raw.githubusercontent.com/qkdxorjs1002/tapl/main/install.sh | sh
```

It requires `curl`, Python 3.11 or newer with the `venv` module, and writable
installation directories. By default these are
`${XDG_DATA_HOME:-$HOME/.local/share}/tapl` and
`${XDG_BIN_HOME:-$HOME/.local/bin}`; set the corresponding XDG variables (or
`TAPL_INSTALL_ROOT` and `TAPL_BIN_DIR`) if you need different locations.

The installer does not modify your shell startup files or install Codex hooks.
If it prints a `PATH` export, run that export in the current shell and add it
to your shell configuration for future shells. Once `taplctl` resolves in your
`PATH`, run `taplctl install user` (or `taplctl install repo`) and then
`taplctl validate`, as shown in [Configure Codex hooks](#configure-codex-hooks).

### Windows (`irm | iex`)

The PowerShell installer supports Windows 10 and 11 and installs the `taplctl`
CLI with the bundled browser viewer:

```powershell
irm https://raw.githubusercontent.com/qkdxorjs1002/tapl/main/install.ps1 | iex
```

It requires Windows PowerShell 5.1 or newer (or PowerShell 7), Python 3.11 or
newer with the `venv` module, and writable per-user installation directories.
By default, the managed installation root is `%LOCALAPPDATA%\tapl` and the
public launcher is `%LOCALAPPDATA%\tapl\bin\taplctl.cmd`. Set
`TAPL_INSTALL_ROOT`, `TAPL_BIN_DIR`, or `TAPL_INSTALL_MANIFEST_URL` to override
the installation root, launcher directory, or release manifest URL.

The installer adds its launcher directory to the user `PATH` only when it is
not already present, and also updates the current PowerShell session. New
processes receive the user `PATH` entry; the system `PATH` is not changed and
no administrator privileges are required. It does not install Codex hooks
automatically. Once `taplctl` resolves in `PATH`, run `taplctl install user`
(or `taplctl install repo`) and then `taplctl validate`, as shown in
[Configure Codex hooks](#configure-codex-hooks).

The installer validates the release manifest and verifies the downloaded wheel
against its published SHA-256 before activation. As with any `irm | iex`
command, review the script source if your environment requires a different
trust process. The CLI wheel itself is platform-independent, but its Python
dependencies still need wheels compatible with your Windows Python version and
architecture. Standard supported Windows Python environments normally install
them through pip; an uncommon architecture or very new Python release can
require build tools or fail when a compatible dependency wheel is unavailable.

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

Both formulas install the pinned MCP runtime from release-hosted wheel bundles;
the semantic formula additionally installs the optional embedding and vector
search stack. Homebrew installation does not resolve Python packages from PyPI
at install time.

Start the browser viewer automatically at login with the formula you installed:

```sh
brew services start taplctl
# or
brew services start taplctl-semantic
```

Both formula services run `taplctl viewer` on `127.0.0.1:8000`. Open that URL
and choose a workspace on the first visit. The semantic formula's Homebrew
service intentionally does not start `searchd`; start it separately when you
want a pre-loaded semantic model:

```sh
taplctl searchd start
taplctl searchd status
```

If port 8000 is occupied, stop the Homebrew service and run
`taplctl viewer --port PORT` manually.

### Configure Codex hooks

After installing `taplctl` by any method, choose how to wire it into Codex:

```sh
# Most users: install once for your Codex account
taplctl install user

# Or install only in the current repository
taplctl install repo

taplctl validate
```

The installer also adds an enabled `mcp_servers.tapl` entry that launches
`taplctl mcp`. Restart Codex after installation so the new stdio server is
loaded.

The first time Codex asks for confirmation after installation, trust the
installed hook.

<p align="center">
  <img src="assets/tapl-trust-hook.png" alt="Codex trust prompt for the installed tapl hook" />
</p>

Install merge policy:

- `hooks.json` is managed-merged. Existing non-tapl hooks are preserved; tapl
  managed hooks are replaced.
- `.codex/config.toml` is TOML-merged. Existing user values win, and missing
  tapl template keys are added, including the TAPL MCP server. The MCP launcher
  reuses the resolved `taplctl` executable used by hooks.
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

Use `uv sync --extra semantic` when developing or running the optional semantic
search features from a source checkout.

### Updates

`taplctl update` manages installations created by the Linux `curl | sh` or
Windows PowerShell installers. It verifies the release manifest and wheel
SHA-256 before activating an update. It does not change Homebrew or
source-checkout installations.

```sh
# Linux curl-sh installation
taplctl update --check
taplctl update

# Equivalent: re-run the installer to fetch the latest managed release
curl -fsSL https://raw.githubusercontent.com/qkdxorjs1002/tapl/main/install.sh | sh
```

```powershell
# Windows PowerShell managed installation
taplctl update --check
taplctl update

# Equivalent: re-run the installer to fetch the latest managed release
irm https://raw.githubusercontent.com/qkdxorjs1002/tapl/main/install.ps1 | iex
```

Update a Homebrew installation with the formula you installed:

```sh
# Basic formula
brew update && brew upgrade taplctl

# Semantic-search formula
brew update && brew upgrade taplctl-semantic
```

For a source checkout, update the checkout and its dependencies using the
source workflow. The release CLI wheel is platform-independent, but its Python
dependencies still need compatible wheels for the target platform. In
particular, musl-based Linux systems such as Alpine may require compatible
wheels or local build tools; the same can apply on Windows for an uncommon
architecture or very new Python release. Installation can fail when those
dependencies cannot be installed.

## Useful Commands

```sh
taplctl init --workspace-root /path/to/workspace
taplctl doctor
taplctl status
taplctl validate
taplctl viewer
taplctl viewer --port 9000
taplctl update --check
taplctl update
taplctl search "query"
taplctl item show --id 1
taplctl archive list
taplctl archive show --id <id>
taplctl reindex
taplctl searchd start
taplctl searchd status

# Advanced manual workflow repair/debugging (flag help only)
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
whether TAPL includes its delegation policy and the model/reasoning allowlist
in the MCP server instructions as follows:

```toml
[subagents]
enabled = true

[subagents.models]
"gpt-5.6-sol" = ["xhigh", "max"]
"gpt-5.6-terra" = ["high", "xhigh", "max"]
"gpt-5.6-luna" = ["high", "xhigh"]
```

When enabled, the MCP policy tells the root agent to assess the complexity
of every executable task and delegate it using an efficient configured
model/reasoning pair. To disable that TAPL-provided MCP instruction content, set:

```toml
[subagents]
enabled = false
```

With `enabled = false`, TAPL includes neither its SubAgent delegation policy
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
approval before durable edits. The MCP server instructions and typed tool
schemas expose this fixed policy; CLI help is only a manual fallback.

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
