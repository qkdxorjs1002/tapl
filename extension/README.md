# REPLTA Workflow Viewer

Read `.agent-workflow/` Markdown files in a dedicated VSCode Webview from the Activity Bar.

## Features

- Active Workflow tree for `request.md`, `plan.md`, `task.md`, `speedwagon.md`, and `index.md`.
- Workflow Dashboard Webview with task status, document cards, and archive summary.
- Archives tree for `.agent-workflow/archive/*/` folders and their Markdown documents.
- Open documents and archives in the same Webview UI.
- Automatic TreeView and open Webview refresh when `.agent-workflow/**/*.md` changes.

## Usage

Open a workspace that contains `.agent-workflow/`, then use the Workflow icon in the Activity Bar. Select **Workflow Dashboard** to review active workflow state, or select any workflow document/archive entry to render it in the Webview panel.
