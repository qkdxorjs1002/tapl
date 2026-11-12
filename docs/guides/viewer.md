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

The RUN bar stays fixed. Desktop navigation starts as an icon rail: hover or keyboard focus expands labels over the page. Leaving the panel delays collapse by 0.6 seconds and returning cancels it. Clicking outside collapses an unpinned panel immediately, including during this delay; clicks inside the sidebar or Explore flyout do not. The rightmost pin control after the theme control keeps it expanded and reserves page width. Pinning is remembered separately from RUN preferences. The collapsed rail shows icons without count badges. Expanded navigation shows full counts with units; tooltips and accessible names retain the full count. The sidebar scrolls independently on short screens; narrow windows use the navigation drawer. The Current RUN canvas pans instead of scrolling the page. In the web Viewer, the folder icon beside the Workspace heading opens a folder-selection modal. Cancel, invalid paths and selecting the same folder preserve the current RUN, page, filters and scroll; a validated different folder resets workspace-specific navigation. Theme and pin controls sit beside the text brand. Choose the UI language in Management → Settings; stored records keep their original language. VS Code theme tokens supply the initial editor palette; a manual theme choice is retained.

- **Current RUN** contains only a RUN → PLAN → TASK mindmap. It includes every TASK state; a TASK without a valid parent PLAN connects directly to RUN. The RUN shows integer completion, PLANs show completed/total counts, and PLAN/TASK nodes open the original details.

  Active RUNs start with automatic following ON. **Follow active tasks** switches it ON/OFF. It centers and adjusts zoom to frame **In Progress** TASKs together with their actual parent PLANs, keeping concurrent work visible and limiting enlargement for readability. If no TASK is in progress, it follows **In Progress** PLANs; with neither, it uses the usual RUN-centered view. Turning it ON recenters immediately, and record updates or viewport resizing refresh the target. Hovering or clicking a node keeps following ON.

  Drags, two-finger or wheel pans, and pinch zooms bend the view softly, with resistance increasing over a long elastic stroke. Releasing early returns smoothly to the follow target; a new gesture during return starts from the visible position, and a remaining pinch finger keeps the current view. Pulling far enough turns following OFF and continues into free navigation without a jump. Release depends on gesture distance or scale, with no hold-time requirement. Continuous gestures accumulate movement, while separate small gestures start fresh so incidental trackpad motion keeps following ON. Toolbar zoom and keyboard camera controls turn following OFF immediately; use the follow button to resume. The camera and ON/OFF choice are remembered per source database and RUN during detail visits and RUN switches in the same page session. Reloading starts active RUNs with following ON again; ended RUNs have no follow button.

  Return motion has a small elastic rebound before settling. Live updates in the same RUN preserve ongoing gestures and return motion; after a gesture ends, the view follows the latest TASK and PLAN positions.

  While following, two-finger panning compensates accelerated input and responds without extra camera easing. Remaining scroll inertia starts the elastic return instead of stretching the view further or releasing following. A new stroke resumes from the visible position. Browsers with a [wheel momentum signal](https://w3c.github.io/pointerevents/#interface-wheelevent) use it directly; others estimate inertia from sustained deceleration, so the feel can vary by device. A deliberate long stroke still releases following.

  While following is ON, executing TASKs and their ancestor paths stay highlighted as on hover; with no executing TASK, executing PLANs take their place. Idle siblings remain dim. Direct hover or keyboard focus takes priority, and leaving restores the automatic highlight. With following OFF or an ended RUN, only direct hover/focus highlights items. Highlighting includes both the executing glass tube and travelling light without restarting the flow. Idle paths remain still.

  Drag or two-finger scroll pans both axes; pinch or Ctrl+wheel zooms around the gesture position, and Shift+wheel pans horizontally. Arrow keys and +/− work; Escape or Center view turns following OFF and returns to a readable RUN-centered view. Pan limits and minimum zoom follow actual node bounds and viewport size to prevent distant empty-space travel. Clicking or dragging does not draw a canvas focus outline; keyboard focus remains visible. Nodes and connectors respond together to the pointer; motion is enabled by default and follows the system reduced-motion setting.
- **Settings**, beneath Management, edits all CLI-supported preferences and the Viewer language. Save changes or confirm a reset to defaults; the selected workspace controls the target file. See [Viewer settings](configuration.md#viewer-settings).
- **TASK status** filters the full TASK list. Selecting a TASK opens its detailed page; **Back** returns to the preceding filter, query, scroll and focus.
- **Explore** opens one PLAN, TASK or FINDING list to the right on hover or click. Its list scrolls independently. Keyboard users can open it with Enter or Right Arrow and close it with Escape.
- **Record search** starts with all records and collapsed RUN groups. Switch between all records and the selected RUN, or grouped and flat results. See [Search](search.md#browse-records-in-the-viewer).
- **Associative memory** places the workspace at the center and branches through sources, memories and cues in all directions for the current results page. The center groups results from connected databases without changing their actual provenance. Shared sources and identical normalized cues join branches. Select a memory for details, a source for its original record/RUN, or a cue to search. It keeps direct pan, pinch, keyboard and reduced-motion controls without automatic following; returning restores the workspace/query/page camera. Search, pagination and diagnostics stay available. See [Memory](memory.md#read-memories-in-the-viewer). The Debug control sits beside Management.

The top bar lists unarchived RUNs. Opening an archived source from records or memory adds one temporary tab at the right; selecting another RUN removes it. Source database and RUN ID remain paired during navigation. Internal links provide Back. Clicking the already selected RUN tab preserves its page and return trail; switching RUNs, direct sidebar navigation and reload clear the trail. Per-RUN filters and theme/language choices persist separately from that trail.

Page, RUN, source and detail changes use brief transitions without replaying them on polling or filter edits; menus and dialogs also ease in and out, while system reduced motion removes animations and transition waits.

Both maps keep every node available for keyboard navigation. Pointer motion updates nearby nodes and their connectors. In an active RUN, layered glow surrounds light traveling inside glass-like connection channels only toward **In Progress** records and along their ancestor paths; hovering another record does not start its flow. Other states, ended RUNs and associative memory links do not carry moving light. Moving light is limited to 24 visible executing connections at 30 frames per second. Stationary node/connector geometry is reused, and decorative work stops when the map is hidden or system reduced motion is enabled. Camera movement retains its separate frame rate.

Repeated snapshots reuse unchanged map data and viewport geometry. Record content still updates immediately; changes to layout, connections or execution rebuild the affected viewport caches. Camera movement checks only executing connections for moving light.

## Read details and structured fields

PLAN, TASK and FINDING details use a reading column with a separate properties rail. PLAN purpose, requirements, approach, scope, sequence, risks, validation and approval needs appear when recorded. PLAN has no separate Content section; original body text remains inspectable in collapsed additional fields. TASK goal, action, result, verification, blocker and next action are likewise visible; FINDING content and impact remain readable. Related-record links use actual references within the source RUN. Generated TASK Markdown that exactly repeats structured fields is shown once.

Ownership, timestamps, status, source database and parent PLAN belong in properties. Additional/custom/execution fields use vertical nested entries with expandable objects and arrays, rather than serialized JSON blocks. Zero, false, null and empty containers remain distinguishable. The same field presentation is used in memory and diagnostics.

In VS Code automatic theme mode, the shell, both maps, status indicators, controls, dialogs, tooltips and reading surfaces follow the host's current colors, including live theme changes. General boundaries use the host's editor/surface border color without extra transparency; older themes fall back to sidebar, panel or editor-group borders. Inputs, popups and tooltips use their corresponding border tokens. Keyboard focus and high-contrast boundaries remain distinct. See the [VS Code theme color reference](https://code.visualstudio.com/api/references/theme-color). A manually selected light/dark palette takes precedence.

Icon-only controls have short localized hover/focus tooltips. Status labels retain text and distinct indicators and follow the host semantic colors. The built-in palettes use slate for pending, blue for in progress, terracotta for blocked, green for completed and violet for skipped. Diagnostics show hook events chronologically with expandable payloads. Loading, errors and unsupported capabilities remain inside the fixed shell.

## Database access and protected services

Saving settings also requires write access to the selected configuration file and its directory; database records keep the read-only access below.

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
