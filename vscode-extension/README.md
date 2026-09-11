<!-- Absolute repository URLs also work when VSCE packages this nested README. -->
<p align="center">
  <img src="https://raw.githubusercontent.com/qkdxorjs1002/tapl/main/assets/readme/tapl-logo.png" width="100" alt="TAPL logo" />
</p>
<h1 align="center">TAPL Workflow Viewer</h1>
<p align="center"><strong>Your workflow, beside your code.</strong></p>
<p align="center">Inspect Codex plans, progress, and history from your VS Code workspace.</p>
<p align="center">
  <a href="#get-started">Get started</a> ·
  <a href="https://github.com/qkdxorjs1002/tapl">TAPL</a> ·
  <a href="https://github.com/qkdxorjs1002/tapl/issues">Report an issue</a>
</p>

## See the work behind the conversation

TAPL keeps workflow state in your repository's `.tapl/tapl.db`. This optional
extension brings that record into a native tree view and a detailed dashboard.

| View | What you can inspect |
| --- | --- |
| Active work | The current run, plans, tasks, approvals, and findings |
| Dashboard | Workflow details in a layout that fits your editor |
| Archives | Completed work and the context behind it |
| History search | Earlier findings and decisions in this workspace |

Views refresh when the workflow database changes. The interface follows your
VS Code display language, with English and Korean available explicitly.

New to TAPL? [See the workflow example](https://github.com/qkdxorjs1002/tapl#workflow)
and [install TAPL](https://github.com/qkdxorjs1002/tapl/blob/main/docs/guide.md).

## Get started

You need **VS Code 1.90+**, a reachable **`tapl-mcp`** executable, and a workspace
initialized by TAPL.

1. [Install TAPL and connect it to Codex](https://github.com/qkdxorjs1002/tapl/blob/main/docs/guide.md#connect).
2. Install the extension. You can download a `.vsix` from
   [GitHub Releases](https://github.com/qkdxorjs1002/tapl/releases) and use
   **Extensions: Install from VSIX…** in the Command Palette.
3. Open a repository containing `.tapl/tapl.db` and select **TAPL** in the Activity Bar.
4. Run **TAPL Workflow: Open TAPL Dashboard** for the complete workspace view.

If the extension cannot find the MCP executable, set its command name or absolute
path in VS Code settings:

```json
{
  "taplWorkflow.taplMcpPath": "/opt/homebrew/bin/tapl-mcp"
}
```

With the setting empty, the extension searches `PATH` and common Homebrew
locations (`/opt/homebrew/bin/tapl-mcp` and `/usr/local/bin/tapl-mcp`). On Windows,
it uses `tapl-mcp.exe`.

## Commands

Open the Command Palette and search for **TAPL Workflow**.

| Command | Action |
| --- | --- |
| **Refresh Workflow Views** | Reload the workspace's workflow state |
| **Open TAPL Dashboard** | Inspect the detailed dashboard |
| **Open TAPL Archive** | Browse a saved run |
| **Search TAPL Workflow** | Find earlier workflow records |

## Make it fit your workspace

| Setting | Values | Default |
| --- | --- | --- |
| `taplWorkflow.taplMcpPath` | MCP command or absolute path | Automatic discovery |
| `taplWorkflow.layout` | `auto`, `small`, `medium`, `large` | `auto` |
| `taplWorkflow.language` | `auto`, `ko`, `en` | `auto` |

The extension keeps a workspace-scoped MCP connection and watches the database,
WAL, and SHM files so workflow changes appear without a manual refresh.

## Support and license

Start with the [support guide](https://github.com/qkdxorjs1002/tapl/blob/main/vscode-extension/SUPPORT.md)
or report a problem in [GitHub Issues](https://github.com/qkdxorjs1002/tapl/issues).

Released under the [MIT License](https://github.com/qkdxorjs1002/tapl/blob/main/vscode-extension/LICENSE.md).
See [third-party notices](https://github.com/qkdxorjs1002/tapl/blob/main/vscode-extension/THIRD_PARTY_NOTICES.md)
for bundled dependencies.

## Shared Viewer

The extension and browser Viewer use the same React screens, CSS, and protocol types (`src/viewer/types.ts`). The extension provides the VS Code workspace and MCP adapters; the browser provides HTTP and local workspace selection.

Both show associative memory lists, search, details, and original sources. Memory screens are read-only: ask the agent to change or delete a memory. Use a current `tapl-mcp` for memory support; older servers keep the other Viewer screens available.

Run `npm run test:host` to check the extension's read-only routing, refresh, navigation, and workspace contracts, then `npm run compile` to build and sync the shared browser assets.
