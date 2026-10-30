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
and [install TAPL](https://github.com/qkdxorjs1002/tapl/blob/main/docs/getting-started/installation.md).

## Get started

You need **VS Code 1.90+**, a reachable **`tapl-mcp`** executable, and a workspace
initialized by TAPL.

1. [Install TAPL and connect it to Codex](https://github.com/qkdxorjs1002/tapl/blob/main/docs/getting-started/integrations.md).
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

Use the Command Palette to find **TAPL Workflow** commands. The [extension guide](https://github.com/qkdxorjs1002/tapl/blob/main/docs/guides/vscode.md#commands-and-settings) lists every command and setting.

## Make it fit your workspace

See [workspace and session routing](https://github.com/qkdxorjs1002/tapl/blob/main/docs/guides/vscode.md#workspace-and-session-routing) for multi-root workspaces, executable discovery, layout, and language settings.

## Support and license

Start with the [support guide](https://github.com/qkdxorjs1002/tapl/blob/main/vscode-extension/SUPPORT.md)
or report a problem in [GitHub Issues](https://github.com/qkdxorjs1002/tapl/issues).

Released under the [MIT License](https://github.com/qkdxorjs1002/tapl/blob/main/vscode-extension/LICENSE.md).
See [third-party notices](https://github.com/qkdxorjs1002/tapl/blob/main/vscode-extension/THIRD_PARTY_NOTICES.md)
for bundled dependencies.

## Shared Viewer

The extension and browser share the same Viewer. See the [extension guide](https://github.com/qkdxorjs1002/tapl/blob/main/docs/guides/vscode.md#shared-viewer-and-capabilities) for feature availability and the [Viewer guide](https://github.com/qkdxorjs1002/tapl/blob/main/docs/guides/viewer.md) for RUN discard confirmation and service setup.

For development checks, use [contributing and verification](https://github.com/qkdxorjs1002/tapl/blob/main/docs/development/contributing.md).
