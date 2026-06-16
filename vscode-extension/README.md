# tapl Workflow Viewer

View `.tapl/tapl.db` workflow state in a VS Code Webview through the `taplctl` CLI.

## Features

- Active tree backed by `taplctl status --json`.
- Dashboard for plan records, task status, findings, hook events, archives, and top search.
- Archives tree backed by `taplctl archive list --json`.
- Search results and item detail pages backed by `taplctl search --json` and `taplctl item show --json`.
- Debounced automatic tree refresh when `.tapl/tapl.db`, WAL, or SHM files change.

## Usage

Install `taplctl`, run `taplctl install repo`, then use the tapl icon in the Activity Bar.

If VS Code cannot find `taplctl`, set `taplWorkflow.taplctlPath` to the full command path, for example:

```json
{
  "taplWorkflow.taplctlPath": "/opt/homebrew/bin/taplctl"
}
```

When the setting is empty, the extension searches `PATH`, `/opt/homebrew/bin/taplctl`, and `/usr/local/bin/taplctl`.
