# Viewer and services

[Documentation](../README.md) · [한국어](viewer.ko.md)

The browser Viewer shows active RUNs, plans, tasks, approvals, findings, archives, history search, and associative memories from a local TAPL workspace. Memory lists, searches, details, and original sources are read-only; ask the agent explicitly to edit or delete a memory.

## Open a workspace

From the initialized working folder:

```sh
taplctl viewer
# tapl viewer: http://127.0.0.1:8000

# Use another port if needed:
taplctl viewer --port 9000
```

Open the printed URL yourself. The command does not launch a browser and stops with `Ctrl+C`. The CLI binds to `127.0.0.1` only. It selects `.tapl/tapl.db` in the starting folder, without searching parent folders. A child directory is a separate workspace when initialized there.

If the starting folder has no database, choose a folder containing `.tapl/tapl.db` on the page. The browser remembers its last successful selection. This is useful when a login service starts outside your repository. Selection does not initialize a folder; use `taplctl init --workspace-root /path/to/workspace` first. There is no Viewer `--workspace` option.

RUN tabs select the session whose records you inspect. Archives and history let you revisit earlier work; the memory view links a reusable cue back to its original evidence. Changing the selected RUN does not transfer its ownership.

## Discard a RUN

Click **×** on the RUN tab. In the dialog, type or paste the **full RUN ID** exactly as displayed. This is the RUN identifier, not `PLAN-001`, a session ID, or a shortened hash. Confirmation remains disabled unless case and whitespace also match. Cancel or Escape changes nothing.

After confirmation:

- The selected RUN and all queued RUNs with the same owner and split group are processed together, whether or not they have dependency links.
- Each RUN with retained work is force-archived with its plans, tasks and findings; each truly empty RUN is deleted without an archive. Results, execution history, memories and retained references count as records to preserve.
- Active database executions and batches are cancelled, and task timers stop. No queued RUN starts automatically.
- Other sessions and unrelated requests remain unchanged. An external agent process continues running; discard only changes TAPL state.

The browser request must carry an allowed `Origin`. The server also verifies the selected workspace, owner session, exact RUN ID, and explicit confirmation. See [MCP reference](../reference/mcp.md#confirmed-discard) for the corresponding tool contract.

## Run as a Homebrew service

Start the formula you installed; all three serve port 8000, so run only one Viewer service on that port:

```sh
brew services start taplctl
# Alternatives: taplctl-semantic or taplctl-pre
brew services restart taplctl
brew services stop taplctl
```

Upgrade/reinstall attempts to restart a running Viewer service. The semantic formula does not preload a search daemon. On Unix, start it separately when wanted:

```sh
taplctl searchd start
taplctl searchd status
```

`searchd` uses Unix sockets and is unavailable on Windows. Optional local semantic search can run on Windows without that daemon; BM25/full-text search remains available. See [Search](search.md).

## Reverse proxies and tunnels

When a trusted proxy or tunnel exposes the Viewer under another browser origin, allow that exact origin:

```sh
taplctl viewer --allowed-origin https://tapl.example.com
```

For a persistent Homebrew service, edit the effective configuration and restart the matching formula:

```toml
[viewer]
allowed_origins = [
  "https://tapl.example.com",
  "https://tapl.internal.example",
]
```

```sh
brew services restart taplctl
```

An origin contains only an HTTP(S) scheme, host, and optional port; paths, credentials, queries, fragments, and wildcards are not accepted. Repeat `--allowed-origin` for multiple values. CLI and configured origins are combined with the local origin. This permits requests from those browser origins; it does not enable general CORS or change loopback binding. The proxy must provide authentication and TLS before exposing access to local workflow data.

## Verification and related pages

The browser and VS Code use the same React screens and protocol types. Browser HTTP origin/workspace checks are covered in `tapl/tests/test_viewer.py` and `test_viewer_discard.py`; discard lifecycle checks are in `test_run_discard.py`. Shared UI confirmation and routing checks live in `vscode-extension/tests`.

- [VS Code extension](vscode.md) for editor workspace routing and prerequisites.
- [Configuration](configuration.md) for configuration scope and effective values.
- [Troubleshooting](troubleshooting.md) for missing workspaces, ports, and origin errors.
