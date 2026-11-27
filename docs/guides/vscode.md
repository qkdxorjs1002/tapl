# VS Code extension

[Documentation](../README.md) · [한국어](vscode.ko.md)

TAPL Workflow Viewer adds active-work and archive trees, history search, and a dashboard to VS Code. It reads the workspace through a persistent `tapl-mcp` stdio connection. A running browser Viewer service is not required.

Select Codex and Claude Code RUNs from the same dashboard, including RUNs stored in one database. RUN selection, shared history results, and details preserve their database source. See [Viewer](viewer.md).

## Install and open

You need VS Code **1.90+**, an initialized workspace containing `.tapl/tapl-{UUID}.db`, and a reachable `tapl-mcp` executable. Follow [Installation](../getting-started/installation.md) and [Agent integration](../getting-started/integrations.md) first.

Install `paragonnov.tapl-workflow-viewer` from Marketplace, or download a `.vsix` from a `viewer-*` entry in [GitHub Releases](https://github.com/qkdxorjs1002/tapl/releases) and run **Extensions: Install from VSIX…**. Open the initialized folder, select **TAPL** in the Activity Bar, then run **TAPL Workflow: Open TAPL Dashboard**.

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
| `taplWorkflow.showTour` | Show Product Tour | Open the Viewer and its help menu. |

Labels above are the English labels under **TAPL Workflow**; the UI also supports Korean.

**Show Product Tour** opens the same help menu as the Viewer’s question mark. Tour choices are remembered in the current VS Code profile across workspaces. See [Product tours](viewer.md#product-tours).

| Setting | Accepted values | Default |
| --- | --- | --- |
| `viewer.mcp_path` | Command name or executable path | Empty string: automatic discovery |
| `viewer.layout` | `auto`, `small`, `medium`, `large` | `auto` |
| `viewer.language` | `auto`, `ko`, `en` | `auto`: follow VS Code's display language |

Manage these fields in the [TAPL configuration file](configuration.md#workspace-and-file-selection), rather than VS Code settings. Native TOML bootstrap reads them before MCP starts, including a custom executable. Saving applies language/layout; external file edits also refresh the Viewer. Workspace-defined and workspace-relative executables respect Workspace Trust. If an invalid MCP path prevents connection, edit the file directly or run `taplctl config unset viewer.mcp_path` to restore discovery.

TAPL's sun/moon button switches only its own local light/dark appearance. VS Code retains its chosen theme and settings. Initially TAPL follows the host's appearance; a local choice is remembered across reloads and workspace changes. The browser Viewer also keeps its appearance choice local.

TAPL continues to follow VS Code's live color palette. A matching light/dark appearance uses the native colors and border roles unchanged. For the opposite appearance, TAPL derives readable surfaces, text and boundaries from those colors while retaining their hue and the native primary-button color pair. High-contrast boundaries remain distinct. A host theme change updates the palette while preserving the selected TAPL brightness. See [theming webview content](https://code.visualstudio.com/api/extension-guides/webview#theming-webview-content).

## Workspace and session routing

The initial target is the first VS Code workspace folder. Change folders in VS Code. The extension starts a separate local stdio process with that folder as its working directory and sets `TAPL_MCP_MODE=viewer` for the process. It resolves the executable settings and database in that workspace. Agent connections continue to use their host hook session rules. See [Viewer stdio tools](../reference/mcp.md#viewer-stdio).

Connections are pooled by workspace. Database and WAL events are coalesced for two seconds, then checked for a changed database or WAL with data frames. SHM bookkeeping and empty WAL creation/removal do not reload the screens. Overlapping refresh requests are combined; a change during a read schedules a follow-up check. Visible Viewer panels keep loading updates even when the VS Code window has no focus. Hidden panels defer data loading and coalesce pending changes into one catch-up refresh when visible again; focusing or clicking the window is not required. **Refresh Workflow Views** still forces a reload.

Changing the executable invalidates connections. Changing workspace resets the dashboard route. The dashboard remembers the selected source database and RUN ID for each workspace. A stale read cannot overwrite a newer navigation or workspace selection. The webview retains compact UI preferences and navigation state and fetches screen data from TAPL on reload.

## Shared Viewer and capabilities

The browser and extension share React screens, CSS, and `src/viewer/types.ts`. VS Code supplies workspace/MCP adapters; the browser supplies HTTP and local folder selection. Both provide memory list/search/detail and original-source navigation. Memory editing and deletion require an explicit agent request.

The extension discovers the server's supported tools when it connects. Earlier servers with `tapl_get_run` can still open exact RUNs. **Management → Discard RUN** requires an eligible local RUN and a server that advertises `tapl_viewer_discard_run`. The dialog requires the full matching RUN ID and explicit confirmation. See [Discard a RUN](viewer.md#discard-a-run).

The shared [Viewer navigation guide](viewer.md#navigate-the-viewer) describes the Current RUN and workspace-centered memory relationship mindmaps, fixed RUN tabs, collapsible icon navigation with pinning and hover expansion, Explore flyouts, per-RUN TASK filters, record browsing and Back. `small` uses a navigation drawer. Other layouts retain the fixed shell when width permits. The record library and memory screens require their corresponding server capabilities.

Open **Management → Settings** to edit, save or reset all `taplctl config` preferences; language selection also lives there. The MCP server must support the settings tools. Older versions show an update notice. See [Viewer settings](configuration.md#viewer-settings) for file scope, revision conflicts and reset behavior.

## Validate or diagnose

Run **Developer: Show Running Extensions** to check activation. Verify the executable path, restart VS Code if needed, then use **Refresh Workflow Views**. For source changes, run from `vscode-extension`:

```sh
npm run test:host
npm run compile
```

Host tests cover workspace routing, refresh/navigation, session and memory views, execution timing, and confirmed discard. Compilation bundles the extension and shared webview and syncs browser assets. See [Contributing](../development/contributing.md) for dependency setup and [Troubleshooting](troubleshooting.md) for reports.
