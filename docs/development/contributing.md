# Contributing and verification

[Documentation](../README.md) · [한국어](contributing.ko.md)

Use this guide to prepare a source checkout, choose checks for the changed boundary, and maintain public documentation. [Architecture](architecture.md) maps the implementation; [Releases](releases.md) describes publishing rather than local development.

## Development environment

The Python package requires **Python 3.11+**. Its runtime dependency is pinned to `mcp==2.0.0`. The `test` extra declares pytest, PyYAML, and wheel; the `semantic` extra declares NumPy, sentence-transformers, and sqlite-vec. Use `uv.lock` for the package's resolved environment.

From the repository root:

```sh
uv --directory tapl sync --extra test
uv --directory tapl run --extra test python -m unittest discover -s tests
uv --directory tapl run --extra test python -m pytest -q tests
uv --directory tapl build
```

The repository contains both unittest and pytest-style tests. Unittest discovery alone does not execute every pytest function. For semantic work, include the optional environment:

```sh
uv --directory tapl sync --extra test --extra semantic
```

The extension uses TypeScript, React, Vite, and the MCP TypeScript SDK. Release CI uses **Node.js 22**. Prepare and verify from the repository root:

```sh
npm --prefix vscode-extension install --package-lock=false
npm --prefix vscode-extension run test:host
npm --prefix vscode-extension run compile
```

`test:host` compiles TypeScript then runs `tests/*.cjs` with Node's test runner. `compile` builds the extension bundle, webview, and synchronized Python browser assets. Run it after shared Viewer changes; do not hand-edit compiled `_viewer/assets` as the source of a fix. Packaging commands are `npm run package` and `npm run package:pre-release` from `vscode-extension`; they are local package builds, not publication commands.

## Choose meaningful checks

| Changed boundary | Relevant checks |
| --- | --- |
| Application, MCP, session routing | `test_application.py`, `test_mcp_native.py`, `test_session_mcp.py`, `test_cli_boundary.py` |
| Policy entry, compact responses, guidance | `test_context_optimization.py`, `test_compact_item.py`, authoring-detail and record-writing suites |
| Plans/tasks, dependencies, batch execution | `test_tapl.py`, application/session suites, `test_execution_timing.py` |
| Browser/shared Viewer and discard | `test_viewer.py`, `test_viewer_native.py`, `test_viewer_discard.py`, `test_run_discard.py`, extension `test:host` and `compile` |
| Memory and search | `test_recall*.py`, `test_memory_review.py`, `test_search.py`, memory extension tests |
| Installation and releases | Installer/update/uninstall suites, `test_release_version.py`, `test_release_packaging.py`, Homebrew and macOS signing suites |
| Windows runtime | `test_windows_runtime.py`, Windows installer/bootstrap tests, and the Windows lifecycle workflow |

For example, validate session changes with:

```sh
uv --directory tapl run --extra test python -m pytest -q tests/test_session_mcp.py tests/test_session_runs.py
```

Run targeted tests while changing behavior, then the relevant complete suite before reporting completion. Tests that exercise real Codex conversations in an isolated environment must use **morae-mcp**, as required by the project instructions. Local unit tests are not evidence that a real host conversation passed. Do not publish private experiment conversations or tooling as public validation artifacts.

Platform checks have different scope. Windows CI parses installer scripts with PowerShell 5.1, tests Python 3.11/3.12, builds a real wheel, and exercises install/update/reinstall/uninstall plus CLI/MCP runtime. macOS signature preservation needs the dedicated Homebrew workflow; a Linux unit test cannot establish Developer ID signatures survived installation. See [Releases](releases.md).

## Maintain English and Korean documentation

Keep the root README files concise: project purpose, core capabilities, quick start, and links. Put detailed behavior, setup, examples, limits, and verification in topic pages under `docs/`. The public topic inventory is [the English home](../README.md) and [the Korean home](../README.ko.md).

When changing behavior, review affected user actions, CLI/MCP arguments, configuration/defaults, installation/update flows, Viewer behavior, limitations, and troubleshooting in the same change. Remove obsolete workarounds. If no documentation change is needed, explain briefly why in the change review.

Keep corresponding `.md` and `.ko.md` pages aligned in behavior, command examples, and values. Link other pages to the topic's authoritative explanation instead of copying it. Every topic page links to its documentation home and language counterpart. When adding/moving a topic, update both homes and related links. Preserve published paths/anchors with compatibility navigation or anchors when reorganizing.

Base claims on current implementation, tests, and command help. Static source package versions are not evidence of the latest release. Public validation may include approved aggregate values/excerpts, conditions, and interpretation limits; recalculate changes from the baseline when changing reported numbers. Private experiment sources, individual records/conversations, and dedicated tools belong outside public docs and commits.

Before completing documentation changes:

```sh
git diff --check
```

Also check relative links and anchors, actual command options, English/Korean parity, and rendered Markdown structure. Avoid making documentation checks execute mutating lifecycle examples. See [MCP reference](../reference/mcp.md) for illustrative calls and [Reference benchmark](../reference/benchmarks.md) for published measurement boundaries.

## Review and commit

Follow applicable project instructions, reuse a recent branch for similar work when suitable, and commit the authorized workspace changes. Preserve other contributors' edits and keep workflow database/private experiment material out of commits. Describe the concrete behavior change, validation evidence, and material remaining limitations in the review. Installation, release publication, and external service changes need their own explicit scope; local build success alone does not publish anything.
