<!-- Absolute repository URLs also work when VSCE packages this nested README. -->
<p align="center">
  <img src="https://raw.githubusercontent.com/qkdxorjs1002/tapl/main/assets/readme/tapl-logo.png" width="100" alt="TAPL logo" />
</p>
<h1 align="center">TAPL Workflow Viewer</h1>
<p align="center"><strong>Your workflow, beside your code.</strong></p>
<p align="center">Inspect Codex and Claude Code plans, progress, and history from your VS Code workspace.</p>
<p align="center">
  <a href="#get-started">Get started</a> ·
  <a href="https://github.com/qkdxorjs1002/tapl">TAPL</a> ·
  <a href="https://github.com/qkdxorjs1002/tapl/issues">Report an issue</a>
</p>

## See the work behind the conversation

TAPL keeps workflow state in your working folder's `.tapl/tapl-{UUID}.db`. Open the
dashboard to choose Codex and Claude Code RUNs from the same workspace, including
RUNs stored in the same database.

| View | What you can inspect |
| --- | --- |
| Active work | Active RUNs, plans, tasks, approvals, and findings |
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

1. [Install TAPL and connect Codex or Claude Code](https://github.com/qkdxorjs1002/tapl/blob/main/docs/getting-started/integrations.md).
2. Install the extension. You can download a `.vsix` from
   a `viewer-*` entry in [GitHub Releases](https://github.com/qkdxorjs1002/tapl/releases) and use
   **Extensions: Install from VSIX…** in the Command Palette.
3. Open the working folder containing `.tapl/tapl-{UUID}.db` and select **TAPL** in the Activity Bar.
4. Run **TAPL Workflow: Open TAPL Dashboard** for the complete workspace view.

If the extension cannot find the MCP executable, set its command name or absolute
path in the selected `.tapl/config.toml` (or `~/.tapl/config.toml`):

```toml
[viewer]
mcp_path = "/opt/homebrew/bin/tapl-mcp"
language = "auto"
layout = "auto"
```

With the setting empty, the extension searches `PATH` and common Homebrew
locations (`/opt/homebrew/bin/tapl-mcp` and `/usr/local/bin/tapl-mcp`). On Windows,
it uses `tapl-mcp.exe`.

## Commands

Use the Command Palette to find **TAPL Workflow** commands. The [extension guide](https://github.com/qkdxorjs1002/tapl/blob/main/docs/guides/vscode.md#commands-and-settings) lists every command and setting.

## Make it fit your workspace

Open **Management → Settings** to edit, save or reset CLI-supported configuration. Language and layout are stored in the same TOML file; the former VS Code extension settings are no longer used.

See [workspace and session routing](https://github.com/qkdxorjs1002/tapl/blob/main/docs/guides/vscode.md#workspace-and-session-routing) for multi-root workspaces, executable discovery, layout, and language settings.

## Support and license

Start with the [support guide](https://github.com/qkdxorjs1002/tapl/blob/main/vscode-extension/SUPPORT.md)
or report a problem in [GitHub Issues](https://github.com/qkdxorjs1002/tapl/issues).

Released under the [MIT License](https://github.com/qkdxorjs1002/tapl/blob/main/vscode-extension/LICENSE.md).
See [third-party notices](https://github.com/qkdxorjs1002/tapl/blob/main/vscode-extension/THIRD_PARTY_NOTICES.md)
for bundled dependencies.

## Shared Viewer

The extension and browser share RUN navigation, TASK details, record browsing and language/theme controls. The extension opens its own local MCP connection. Confirmed RUN discard is available when the connected server advertises the Viewer discard tool and the selected RUN supports it. See the [extension guide](https://github.com/qkdxorjs1002/tapl/blob/main/docs/guides/vscode.md#shared-viewer-and-capabilities) and [RUN discard guide](https://github.com/qkdxorjs1002/tapl/blob/main/docs/guides/viewer.md#discard-a-run).

For development checks, use [contributing and verification](https://github.com/qkdxorjs1002/tapl/blob/main/docs/development/contributing.md).
