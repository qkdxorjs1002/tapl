# Viewer and services

[Documentation](../README.md) · [한국어](viewer.ko.md)

The browser Viewer shows active RUNs, plans, tasks, approvals, findings, archives, history search, and associative memories from a local TAPL workspace. Memory lists, searches, details, and original sources are read-only; ask the agent explicitly to edit or delete a memory.

The same Viewer reads Codex and Claude Code RUNs. Select the owning session explicitly; Claude owners carry the `claude-code:` prefix. See [Claude Code](../getting-started/claude-code.md).

The Viewer reads the folder's `tapl-*.db` files together and preserves the source database through details and refresh. Peer RUNs are viewable but cannot be discarded. Read-only discovery does not create a UUID. See [Local identity and shared history](storage.md).

## Open a workspace

From the initialized working folder:

```sh
taplctl viewer
# tapl viewer: http://127.0.0.1:8000

# Use another port if needed:
taplctl viewer --port 9000
```

Open the printed URL yourself. The command does not launch a browser and stops with `Ctrl+C`. The CLI binds to `127.0.0.1` only. It selects `.tapl/tapl-{UUID}.db` in the starting folder, without searching parent folders. A child directory is a separate workspace when initialized there.

If the starting folder has no database, choose a folder containing `.tapl/tapl-{UUID}.db` on the page. The browser remembers its last successful selection. This is useful when a login service starts outside your repository. Selection does not initialize a folder; use `taplctl init --workspace-root /path/to/workspace` first. There is no Viewer `--workspace` option.

RUN tabs select the session whose records you inspect. Archives and history let you revisit earlier work; the memory view links a reusable cue back to its original evidence. Changing the selected RUN does not transfer its ownership.

## Navigate the Viewer

The desktop sidebar and RUN bar stay fixed while the page scrolls. The sidebar scrolls independently on short screens; narrow windows use a navigation drawer. In the web Viewer, the folder icon beside the Workspace heading opens a folder-selection modal. Cancel, invalid paths and selecting the same folder preserve the current RUN, page, filters and scroll; a validated different folder resets workspace-specific navigation. Language and light/dark controls sit beside the text brand; UI language does not translate stored records. VS Code theme tokens supply the initial editor palette; a manual theme choice is retained.

- **Current RUN** shows recorded work type, workflow mode and record mode in one compact row, followed by PLAN cards and then In Progress TASK cards. PLAN previews objective, approach and validation; TASK previews goal, action and verification, with recorded owner, parent PLAN, prerequisite count and execution timing. Both card rows scroll horizontally when they overflow, with fading edges and independent scroll positions. Missing fields are omitted, long previews are shortened, and selecting a card opens the full record. The sidebar's integer completion percentage is calculated from all TASK states, not the selected page.
- **TASK status** filters the full TASK list. Selecting a TASK opens its detailed page; **Back** returns to the preceding filter, query, scroll and focus.
- **Explore** opens one PLAN, TASK or FINDING list to the right on hover or click. Its list scrolls independently. Keyboard users can open it with Enter or Right Arrow and close it with Escape.
- **Record search** starts with all records and collapsed RUN groups. Switch between all records and the selected RUN, or grouped and flat results. See [Search](search.md#browse-records-in-the-viewer).
- **Associative memory** retains read-only list, search, detail and original-source inspection. Refresh and Debug controls sit beside Management.

The top bar lists unarchived RUNs. Opening an archived source from records or memory adds one temporary tab at the right; selecting another RUN removes it. Source database and RUN ID remain paired during navigation. Internal links provide Back. Clicking the already selected RUN tab preserves its page and return trail; switching RUNs, direct sidebar navigation and reload clear the trail. Per-RUN filters and theme/language choices persist separately from that trail.

## Read details and structured fields

PLAN, TASK and FINDING details use a reading column with a separate properties rail. PLAN purpose, requirements, approach, scope, sequence, risks, validation and approval needs appear when recorded. PLAN has no separate Content section; original body text remains inspectable in collapsed additional fields. TASK goal, action, result, verification, blocker and next action are likewise visible; FINDING content and impact remain readable. Related-record links use actual references within the source RUN. Generated TASK Markdown that exactly repeats structured fields is shown once.

Ownership, timestamps, status, source database and parent PLAN belong in properties. Additional/custom/execution fields use vertical nested entries with expandable objects and arrays, rather than serialized JSON blocks. Zero, false, null and empty containers remain distinguishable. The same field presentation is used in memory and diagnostics.

Icon-only controls have short localized hover/focus tooltips. Status labels retain text and distinct indicators: slate for pending, blue for in progress, terracotta for blocked, green for completed and violet for skipped. Diagnostics show hook events chronologically with expandable payloads. Loading, errors and unsupported capabilities remain inside the fixed shell.

## Database access and protected services

Viewer data requests open the selected database with SQLite `mode=ro` and `query_only`, using a read transaction per connection. They do not create a database, change journal mode, migrate the schema, or update metadata. A service can start without `~/.tapl/tapl-{UUID}.db`; do not require it in a startup check. A successful page load or `revision` response confirms the web server or file metadata, not that SQLite queries succeed.

The database must match the installed TAPL schema. If migration is required, run this outside the protected Viewer service, with write access to the database directory, then refresh:

```sh
taplctl --db /path/to/history.db init
```

This command can create migration backups beside the database. A newer-than-supported schema requires upgrading TAPL instead; the Viewer never downgrades a database.

For systemd services using `ProtectSystem=strict` or `ProtectHome=read-only`, the service user needs read and directory traversal access to the workspace. SQLite WAL databases also need readable existing `tapl-{UUID}.db-wal` and `tapl-{UUID}.db-shm` files, or permission to create them in the database directory. With usable sidecars, the Viewer reads committed WAL changes while another process writes, without taking a database write lock. Uncommitted changes stay invisible.

When all writers close, SQLite can remove the sidecars. A WAL database without them can therefore fail in a fully read-only directory. Keep a trusted writer connection open with usable sidecars, or allow writes only to the selected `.tapl` directory with systemd `ReadWritePaths=/path/to/workspace/.tapl`. Do not create sidecars by hand or use `immutable=1` against a live database: it bypasses SQLite's change detection and can miss committed WAL data. See [SQLite's read-only WAL requirements](https://www.sqlite.org/wal.html#read_only_databases).

Confirmed [RUN discard](#discard-a-run) uses the separate write API and still needs directory write access. A service with only read access can inspect records but cannot discard RUNs. Optional semantic search may also need its model cache; see [Search](search.md) for provider configuration and BM25 fallback.

## Discard a RUN

Select the RUN tab, then choose **Management → Discard RUN** in the sidebar. In the dialog, type or paste the **full RUN ID** exactly as displayed. This is the RUN identifier, not `PLAN-001`, a session ID, or a shortened hash. Confirmation remains disabled unless case and whitespace also match. Cancel or Escape changes nothing.

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

The browser and VS Code use the same React screens and protocol types. Browser HTTP origin/workspace checks are covered in `tapl/tests/test_viewer.py` and `test_viewer_discard.py`; database permissions, schema compatibility and WAL snapshots are covered in `test_viewer_readonly.py`. Discard lifecycle checks are in `test_run_discard.py`. Shared UI confirmation and routing checks live in `vscode-extension/tests`.

- [VS Code extension](vscode.md) for editor workspace routing and prerequisites.
- [Configuration](configuration.md) for configuration scope and effective values.
- [Troubleshooting](troubleshooting.md) for missing workspaces, ports, and origin errors.
