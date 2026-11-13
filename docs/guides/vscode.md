# VS Code extension

[Documentation](../README.md) · [한국어](vscode.ko.md)

TAPL Workflow Viewer adds active-work and archive trees, history search, and a dashboard to VS Code. It reads the workspace through a persistent `tapl-mcp` stdio connection. A running browser Viewer service is not required.

Shared history results, details, and RUN selections preserve their database source. Peer RUNs do not offer the close action. See [Local identity and shared history](storage.md).

## Install and open

You need VS Code **1.90+**, an initialized workspace containing `.tapl/tapl-{UUID}.db`, and a reachable `tapl-mcp` executable. Follow [Installation](../getting-started/installation.md) and [Agent integration](../getting-started/integrations.md) first.

Install `paragonnov.tapl-workflow-viewer` from Marketplace, or download a `.vsix` from [GitHub Releases](https://github.com/qkdxorjs1002/tapl/releases) and run **Extensions: Install from VSIX…**. Open the initialized folder, select **TAPL** in the Activity Bar, then run **TAPL Workflow: Open TAPL Dashboard**.

The dashboard uses the workspace opened in VS Code and has no workspace-change button or folder-selection modal. Folder selection inside the Viewer is available only in the [browser Viewer](viewer.md#navigate-the-viewer).

The default executable search uses `PATH`, `/opt/homebrew/bin/tapl-mcp`, and `/usr/local/bin/tapl-mcp`; Windows uses `tapl-mcp.exe`. Override it when necessary:

```toml
# .tapl/config.toml (or ~/.tapl/config.toml)
[viewer]
mcp_path = "/opt/homebrew/bin/tapl-mcp"
layout = "auto"
language = "auto"
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
| `viewer.mcp_path` | Command name or executable path | Empty string: automatic discovery |
| `viewer.layout` | `auto`, `small`, `medium`, `large` | `auto` |
| `viewer.language` | `auto`, `ko`, `en` | `auto`: follow VS Code's display language |

Manage these fields in the [TAPL configuration file](configuration.md#workspace-and-file-selection), rather than VS Code settings. Native TOML bootstrap reads them before MCP starts, including a custom executable. Saving applies language/layout; external file edits also refresh the Viewer. Workspace-defined and workspace-relative executables respect Workspace Trust. If an invalid MCP path prevents connection, edit the file directly or run `taplctl config unset viewer.mcp_path` to restore discovery.

## Workspace and session routing

The initial target is the first VS Code workspace folder. Change folders in VS Code; the Viewer does not display a workspace picker. TAPL launches that folder's MCP process with the folder as its working directory and resolves executable settings for that folder. It does not search parent folders for a database.

Connections are pooled by workspace. Database and WAL events are coalesced for two seconds, then checked for a changed database or WAL with data frames. SHM bookkeeping and empty WAL creation/removal do not reload the screens. Overlapping refresh requests are combined; a change during a read schedules a follow-up check. Hidden or unfocused Viewer panels defer data loading and catch up when visible and focused again. **Refresh Workflow Views** still forces a reload.

Changing the executable invalidates connections; changing workspace resets the dashboard route. RUN selection is retained per workspace and reads the selected owner's session. A stale read cannot overwrite a newer navigation or workspace selection. The webview retains compact UI preferences and navigation state; screen data is fetched from TAPL when it reloads.

## Shared Viewer and capabilities

The browser and extension share React screens, CSS, and `src/viewer/types.ts`. VS Code supplies workspace/MCP adapters; the browser supplies HTTP and local folder selection. Both provide memory list/search/detail and original-source navigation. Memory editing and deletion require an explicit agent request.

Capabilities come from the server. Older servers without memory support still show the other screens. **Management → Discard RUN** is available only when a current server advertises it; otherwise RUN records remain read-only. The dialog requires the full matching RUN ID and explicit confirmation. Retained work is archived; truly empty RUNs are deleted. External agents keep running. See [Viewer](viewer.md#discard-a-run) for exact effects.

The shared [Viewer navigation guide](viewer.md#navigate-the-viewer) describes the Current RUN and workspace-centered memory relationship mindmaps, fixed RUN tabs, collapsible icon navigation with pinning and hover expansion, Explore flyouts, per-RUN TASK filters, record browsing and Back. `small` uses a navigation drawer; other layout choices retain the fixed shell when width permits. Upgrade the workspace MCP server to use exact historical RUN pages and the record library; unsupported memory remains capability-gated.

Open **Management → Settings** to edit, save or reset all `taplctl config` preferences; language selection also lives there. The MCP server must support the settings tools. Older versions show an update notice. See [Viewer settings](configuration.md#viewer-settings) for file scope, revision conflicts and reset behavior.

## Validate or diagnose

Run **Developer: Show Running Extensions** to check activation. Verify the executable path, restart VS Code if needed, then use **Refresh Workflow Views**. For source changes, run from `vscode-extension`:

```sh
npm run test:host
npm run compile
```

Host tests cover workspace routing, refresh/navigation, session and memory views, execution timing, and confirmed discard. Compilation bundles the extension and shared webview and syncs browser assets. See [Contributing](../development/contributing.md) for dependency setup and [Troubleshooting](troubleshooting.md) for reports.
