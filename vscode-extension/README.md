# TAPL Workflow Viewer

Inspect the durable workflow state for the current repository without leaving
Visual Studio Code. The extension connects to the workspace-scoped `tapl-mcp`
server and presents active work, plans, tasks, findings, approvals, archives,
and history in a native tree view and dashboard.

## Features

- See the active TAPL run and its plan, task, approval, and finding state.
- Open a responsive dashboard for detailed workflow inspection.
- Browse and open completed TAPL archives.
- Search durable workflow history from the current workspace.
- Refresh automatically when `.tapl/tapl.db`, its WAL, or SHM file changes.
- Choose an automatic, compact, balanced, or spacious dashboard layout.
- Follow the VS Code display language automatically or select Korean or English.

## Requirements

- Visual Studio Code 1.90 or newer.
- TAPL installed with a reachable `tapl-mcp` executable.
- A workspace initialized by TAPL, containing `.tapl/tapl.db`.

See the [TAPL installation guide](https://github.com/qkdxorjs1002/tapl#installation)
for macOS, Linux, and Windows setup options.

## Getting started

1. Install TAPL and connect it to Codex.
2. Open a TAPL-enabled repository in VS Code.
3. Select the TAPL icon in the Activity Bar.
4. Open **TAPL Workflow: Open TAPL Dashboard** from the Command Palette for the
   complete workspace view.

If VS Code cannot find `tapl-mcp`, configure its command name or absolute path:

```json
{
  "taplWorkflow.taplMcpPath": "/opt/homebrew/bin/tapl-mcp"
}
```

When this setting is empty, the extension searches `PATH`,
`/opt/homebrew/bin/tapl-mcp`, and `/usr/local/bin/tapl-mcp`.

## Commands

- **TAPL Workflow: Refresh Workflow Views**
- **TAPL Workflow: Open TAPL Dashboard**
- **TAPL Workflow: Open TAPL Archive**
- **TAPL Workflow: Search TAPL Workflow**

## Settings

- `taplWorkflow.taplMcpPath`: command or absolute path for `tapl-mcp`.
- `taplWorkflow.layout`: dashboard layout size.
- `taplWorkflow.language`: automatic, Korean, or English display language.

## Support and license

Report problems through [GitHub Issues](https://github.com/qkdxorjs1002/tapl/issues)
after checking the [support guide](SUPPORT.md).

TAPL Workflow Viewer is released under the [MIT License](LICENSE.md). Bundled
third-party notices are available in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
