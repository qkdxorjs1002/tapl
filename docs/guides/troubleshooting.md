# Troubleshooting

[Documentation](../README.md) · [한국어](troubleshooting.ko.md)

Start in the working folder where Codex uses TAPL. Workspaces use that folder's `.tapl/tapl.db`; TAPL does not discover a parent database. Installation scope, configuration scope, and active session identity can therefore explain apparently missing records.

## Check runtime and configuration

```sh
taplctl --version
taplctl doctor --json
taplctl config get
```

`doctor` reports the database path, SQLite/runtime information, and effective settings. Run it in the intended workspace: database-opening commands can initialize a missing database. Avoid pointing diagnostic commands at a different folder and assuming it represents the original workspace.

| Symptom | Check and remedy |
| --- | --- |
| Codex cannot see TAPL tools | Run `taplctl doctor`, repeat the connect command for your installation method and chosen scope in [Agent integration](../getting-started/integrations.md), then restart Codex. |
| `taplctl` is missing after standalone installation | Apply the installer's printed `PATH` export and persist it in your shell profile; reopen the terminal. On Windows, reopen the shell after PATH updates. |
| Installed version or channel seems wrong | Compare `taplctl --version` with the installer channel and installation metadata. Use Homebrew for Homebrew installs and `taplctl update` for installer-managed installs; see [Installation](../getting-started/installation.md). |
| Homebrew formula conflicts | Uninstall the installed TAPL formula before choosing `taplctl`, `taplctl-semantic`, or `taplctl-pre`. They provide the same commands. |
| Configuration changes have no effect | Inspect `taplctl config get` and the reported path. An explicit config or repository configuration can select a different file from the user configuration. See [Configuration](configuration.md). |

## Viewer and VS Code

| Symptom | Check and remedy |
| --- | --- |
| Viewer asks for a workspace | Choose a folder that already contains `.tapl/tapl.db`, or initialize the intended folder with `taplctl init --workspace-root /path/to/workspace`. A login service may start outside your repository. |
| Port 8000 is in use | Stop the matching Homebrew service or run `taplctl viewer --port 9000`. Multiple formula services use the same default port. |
| Proxy or tunnel shows `Origin is not allowed.` | Allow the exact public HTTP(S) origin with `--allowed-origin` or `viewer.allowed_origins`, then restart the service. An origin has no path. See [Viewer](viewer.md#reverse-proxies-and-tunnels). |
| RUN discard confirmation stays disabled | Enter or paste the full displayed RUN ID with exact case and whitespace. Cancelling leaves all records unchanged. |
| VS Code cannot start MCP | Check `tapl-mcp` is available. Set `taplWorkflow.taplMcpPath` to its executable path if needed. The extension starts the server itself; it does not connect to the browser service. |
| VS Code shows another folder or RUN | Select the intended open workspace and RUN in the dashboard. Each folder owns its connection, database, and selected session. |
| Memory or RUN discard UI is absent | Update the reachable `tapl-mcp`. These screens/actions depend on server capabilities; older servers retain the other views. |
| VS Code views do not refresh | Run **Developer: Show Running Extensions**, confirm activation, then **TAPL Workflow: Refresh Workflow Views**. Restart VS Code after correcting executable availability. |

## Search and lifecycle checks

| Symptom | Check and remedy |
| --- | --- |
| Semantic search falls back to BM25 | Inspect effective search settings and optional semantic dependencies. Use [Search](search.md) for indexing and provider checks. Full-text search does not require the semantic extra. |
| `searchd` is unavailable on Windows | Use the local semantic provider with optional dependencies, or BM25. The daemon requires Unix sockets. |
| Current work seems missing through MCP | Pass the same hook `session_id` on every call. Omitted identity selects the isolated legacy namespace. An MCP transport connection is not the conversation identity. |
| A task cannot start or dispatch | Inspect `tapl_get_next` recommendations and `tapl_validate_state` errors. Confirm the plan, execution approval, completed dependencies, and non-overlapping ownership for parallel tasks. |
| Parallel completion rejects an execution | Use the exact `execution_id` returned by the active dispatch manifest. After interruption, recover or cancel the original batch before retrying. |
| Finishing returns `review_required` | Complete memory review for the active RUN, then archive separately. Use `expected_run_id` with memory arguments; see [Associative memory](memory.md). |
| A memory edit reports a revision conflict | Read the current memory, review the changed content, then use its current `expected_revision` only under the explicit user request. |

Do not fix lifecycle errors by deleting the database or changing another session's identity. Preserve the concrete blocker and next action in the task. [Workflow](../concepts/workflow.md) and the [MCP reference](../reference/mcp.md) explain valid transitions.

## Report an unresolved issue

Use [GitHub Issues](https://github.com/qkdxorjs1002/tapl/issues). Include OS, TAPL and VS Code/extension versions when relevant, installation method, executable path, exact reproduction steps, and scoped `doctor` or error output with secrets and private workspace content removed. Report security vulnerabilities through [private vulnerability reporting](https://github.com/qkdxorjs1002/tapl/security/advisories/new).

These remedies follow the CLI, Viewer, extension support contract, and session/runtime regression tests. [Contributing](../development/contributing.md) lists local validation commands; [Releases](../development/releases.md) covers signing and publishing failures.
