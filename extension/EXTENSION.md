# REPLTA Workflow Viewer

VSCode extension for reading `.agent-workflow/` Markdown files in a dedicated Webview panel from the Activity Bar.

## Features

- Active Workflow tree for `request.md`, `plan.md`, `task.md`, `speedwagon.md`, and `index.md`.
- Workflow Dashboard Webview with task status, document cards, and archive summary.
- Archives tree for `.agent-workflow/archive/*/` folders and their Markdown documents.
- Opens active documents, archive folders, and archive documents in the same Webview UI.
- Refreshes the TreeViews and any open Webview automatically when `.agent-workflow/**/*.md` changes.

## Development

```sh
npm run compile
```

Open this repository in VSCode and run the extension through an Extension Development Host.
