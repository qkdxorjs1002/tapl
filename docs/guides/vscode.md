# VS Code extension

[Documentation](../README.md) · [한국어](vscode.ko.md)

TAPL Workflow Viewer adds active-work and archive trees, history search, and a dashboard to VS Code. It reads the workspace through a persistent `tapl-mcp` stdio connection. A running browser Viewer service is not required.

Shared history results, details, and RUN selections preserve their database source. Peer RUNs do not offer the close action. See [Local identity and shared history](storage.md).

## Install and open

You need VS Code **1.90+**, an initialized workspace containing `.tapl/tapl-{UUID}.db`, and a reachable `tapl-mcp` executable. Follow [Installation](../getting-started/installation.md) and [Agent integration](../getting-started/integrations.md) first.

Install `paragonnov.tapl-workflow-viewer` from Marketplace, or download a `.vsix` from [GitHub Releases](https://github.com/qkdxorjs1002/tapl/releases) and run **Extensions: Install from VSIX…**. Open the initialized folder, select **TAPL** in the Activity Bar, then run **TAPL Workflow: Open TAPL Dashboard**.

The dashboard uses the workspace opened in VS Code and has no workspace-change button or folder-selection modal. Folder selection inside the Viewer is available only in the [browser Viewer](viewer.md#navigate-the-viewer).

The default executable search uses `PATH`, `/opt/homebrew/bin/tapl-mcp`, and `/usr/local/bin/tapl-mcp`; Windows uses `tapl-mcp.exe`. Override it when necessary:

```json
{
  "taplWorkflow.taplMcpPath": "/opt/homebrew/bin/tapl-mcp",
  "taplWorkflow.layout": "auto",
  "taplWorkflow.language": "auto"
}
```

## Commands and settings

| Command ID | Command Palette label | Purpose |
| --- | --- | --- |
| `taplWorkflow.refresh` | Refresh Workflow Views | Refresh trees and the open dashboard. |
| `taplWorkflow.openOverview` | Open TAPL Dashboard | Open the workspace dashboard. |
| `taplWorkflow.openArchive` | Open TAPL Archive | Open the selected archive tree entry. |
| `taplWorkflow.search` | Search TAPL Workflow | Search earlier workspace records. |

Labels above are the English labels under **TAPL Workflow**; the UI also supports Korean.

| Setting | Accepted values | Default |
| --- | --- | --- |
| `taplWorkflow.taplMcpPath` | Command name or executable path | Empty string: automatic discovery |
| `taplWorkflow.layout` | `auto`, `small`, `medium`, `large` | `auto` |
| `taplWorkflow.language` | `auto`, `ko`, `en` | `auto`: follow VS Code's display language |

## Workspace and session routing

The initial target is the first VS Code workspace folder. In a multi-root window, use the dashboard's workspace picker to choose another open folder. TAPL launches that folder's MCP process with the folder as its working directory and resolves executable settings for that folder. It does not search parent folders for a database.

Connections are pooled by workspace. Database, WAL, and SHM changes (`.tapl/tapl-*.db`, `-wal`, `-shm`) trigger debounced refreshes. Changing the executable invalidates connections; changing workspace resets the dashboard route. RUN selection is retained per workspace and reads the selected owner's session. A stale read cannot overwrite a newer navigation or workspace selection.

## Shared Viewer and capabilities

The browser and extension share React screens, CSS, and `src/viewer/types.ts`. VS Code supplies workspace/MCP adapters; the browser supplies HTTP and local folder selection. Both provide memory list/search/detail and original-source navigation. Memory editing and deletion require an explicit agent request.

Capabilities come from the server. Older servers without memory support still show the other screens. **Management → Discard RUN** is available only when a current server advertises it; otherwise the Viewer remains read-only. The dialog requires the full matching RUN ID and explicit confirmation. Retained work is archived; truly empty RUNs are deleted. External agents keep running. See [Viewer](viewer.md#discard-a-run) for exact effects.

The shared [Viewer navigation guide](viewer.md#navigate-the-viewer) describes the Current RUN and workspace-centered memory relationship mindmaps, fixed RUN tabs, collapsible icon navigation with pinning and hover expansion, Explore flyouts, per-RUN TASK filters, record browsing and Back. `small` uses a navigation drawer; other layout choices retain the fixed shell when width permits. Upgrade the workspace MCP server to use exact historical RUN pages and the record library; unsupported memory remains capability-gated.

## Validate or diagnose

Run **Developer: Show Running Extensions** to check activation. Verify the executable path, restart VS Code if needed, then use **Refresh Workflow Views**. For source changes, run from `vscode-extension`:

```sh
npm run test:host
npm run compile
```

Host tests cover workspace routing, refresh/navigation, session and memory views, execution timing, and confirmed discard. Compilation bundles the extension and shared webview and syncs browser assets. See [Contributing](../development/contributing.md) for dependency setup and [Troubleshooting](troubleshooting.md) for reports.
