# Local identity and shared history

[Documentation](../README.md) · [한국어](storage.ko.md)

TAPL writes each local environment's records to `.tapl/tapl-{UUID}.db` in the exact working folder. History search, archives, memory recall, and the Viewer also read the other `tapl-*.db` files in that folder. Workflow changes stay in the local database.

## Persistent installation identity

The first operation needing a default writable database creates a random UUID v4 in `~/.tapl/installation_id`. Concurrent starts reuse one complete value. Every workspace used by that local user environment uses the same UUID suffix; the records themselves stay in each workspace. This identifier is independent of Codex accounts, sessions, and installation IDs.

The identity file is separate from `config.toml`. TAPL removal, including `--purge-config` and `--purge-db`, preserves it. Reinstalling TAPL therefore selects the same database name. Removing executables also leaves this file in place.

The UUID follows the local user's home directory. Copying that directory to another environment copies the identity too. An invalid identity is reported instead of silently generating a replacement: restore the original canonical UUID v4 from a backup or the filename of your local database. Read-only Viewer discovery does not create an identity.

## Existing database migration

Stop existing TAPL MCP servers, hooks, and other database users before upgrading. The next default writable initialization adopts `.tapl/tapl.db` as `.tapl/tapl-{UUID}.db`. For example:

```sh
taplctl init --workspace-root /path/to/workspace
```

TAPL checks the existing database, checkpoints committed WAL data, requires exclusive access, closes the SQLite connection, and moves the file without replacing an existing destination. Successful filename migration removes the old `tapl.db` name. It does not merge databases or create a separate filename-migration backup. Existing schema upgrades retain their versioned backup behavior.

A busy database, unsupported/invalid source, existing destination, or destination sidecar stops migration and preserves the source. Resolve the reported condition before retrying. After an interrupted migration, inspect both names before removing `.tapl/.legacy-migration.lock`; do not remove a live process's lock. To roll back a filename migration, stop all TAPL processes first and move the complete database back to the old name; preserve any later records separately before restoring a schema backup.

Readonly viewers can inspect an existing legacy database before migration. They do not migrate it. Refresh the Viewer after migration because its source filename changes. An explicit administrative `--db PATH` continues to select that exact file.

## Querying multiple databases

Only the selected working folder is scanned; parent folders and Git roots are not searched. Place peer `tapl-*.db` files in that folder's `.tapl` directory to make their history available. Symlink databases and directories are not followed.

Search, archive lists, and memory recall combine readable sources. Results include `source_db`, the exact database filename. Forward it with an item, archive, memory, or RUN detail request. Item numbers and archive slugs can repeat across databases, so an ID alone does not identify a peer record. Omitting `source_db` selects local history.

```json
{"session_id":"<current-hook-session-id>","item_id":42,"source_db":"tapl-123e4567-e89b-42d3-a456-426614174000.db","compact":true}
```

The example arguments are for `tapl_get_item`; use the filename returned by your actual search. The Viewer preserves this source selection when opening details and refreshing. It can display peer RUNs, but only local RUNs support confirmed discard.

Search merges per-database ranks rather than comparing raw scores from different indexes, then applies the global result limit. Archive and manual memory pagination also apply across the combined results. Unreadable, corrupt, or incompatible sources appear in `source_errors` while healthy sources remain available. TAPL never migrates a peer database during a read; its owner must update it. Automatic recall keeps its existing byte budget and may summarize omitted source errors with `source_errors_omitted`.

Peer memory updates and deletion are rejected. Include `source_db` in finish-time `memory_uses`; peer uses are reported as read-only skips and do not reinforce another database. If an omitted source would be ambiguous because the same memory ID exists in a peer, the use is rejected until the source is supplied. See [Memory](memory.md) and the [MCP reference](../reference/mcp.md).

## Removal and sharing boundaries

`--purge-db` removes the selected scope's local UUID database, any legacy database, and their SQLite sidecars. It preserves peer databases, backups, and `~/.tapl/installation_id`. `--purge-config` removes configuration only. See [CLI removal options](../reference/cli.md#uninstall).

Discovery is local file access, not synchronization between Git clones. This repository ignores workflow databases by default. To transfer history, stop its writers or create a consistent SQLite backup before copying it; do not copy only a live main file while committed records remain in its WAL. The same identity used in multiple independent clones can still modify the same database filename, so file discovery does not resolve binary merge conflicts.

## Related pages

[Configuration](configuration.md) · [Installation](../getting-started/installation.md) · [Search](search.md) · [Viewer](viewer.md) · [Troubleshooting](troubleshooting.md)
