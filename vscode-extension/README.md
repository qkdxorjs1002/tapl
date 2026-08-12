# tapl Workflow Viewer

View `.tapl/tapl.db` workflow state in a VS Code Webview through the workspace-scoped
`tapl-mcp` client.

## Features

- Active tree and dashboard backed by typed `tapl-mcp` workflow tools.
- Plan records, task status, findings, hook events, archives, search results, and item details in one workspace view.
- A persistent `tapl-mcp` client for each workspace, rather than a workflow CLI JSON data plane.
- Debounced automatic tree refresh when `.tapl/tapl.db`, WAL, or SHM files change.

## Usage

Install TAPL, run `taplctl install repo`, then use the TAPL icon in the Activity Bar.
That connection configures the `tapl-mcp` server used by the extension.

If VS Code cannot find `tapl-mcp`, set `taplWorkflow.taplMcpPath` to its command
or full executable path, for example:

```json
{
  "taplWorkflow.taplMcpPath": "/opt/homebrew/bin/tapl-mcp"
}
```

When the setting is empty, the extension searches `PATH`, `/opt/homebrew/bin/tapl-mcp`,
and `/usr/local/bin/tapl-mcp`.

## Development

```sh
npm run compile
```

Open this repository in VS Code and run the extension through an Extension Development Host.
