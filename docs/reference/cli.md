# CLI reference

[Documentation](../README.md) · [한국어](cli.ko.md)

`taplctl` manages installation, configuration, runtime inspection, indexing, and local services. Agents create, execute, search, and inspect workflow records through [MCP tools](mcp.md). Workflow commands are not part of the public management CLI.

## Invocation and output

```text
taplctl [--session-id ID] [--db PATH] [--config PATH] COMMAND ...
```

Put global options before the command. Use `taplctl --help`, `taplctl COMMAND --help`, and nested help such as `taplctl install repo --help` for the installed version's exact interface.

| Global option | Meaning |
| --- | --- |
| `--session-id ID` | Codex session identity; defaults to `TAPL_SESSION_ID`, otherwise the isolated legacy scope |
| `--db PATH` | Explicit SQLite database for database-using commands |
| `--config PATH` | Explicit TOML configuration file |
| `--version` | Print the installed version and exit |
| `-h`, `--help` | Show help and exit |

Without an explicit database, database-using commands select the working folder's `.tapl/tapl.db`, never a parent database. Config selection prefers the exact working folder's `.tapl/config.toml`, then `~/.tapl/config.toml`. See [configuration](../guides/configuration.md).

`init`, `doctor`, `update`, both `install`/`uninstall` scopes, all `config` subcommands, `reindex`, and public `searchd` subcommands accept **one** of `--json` (structured JSON) or `--agent` (compact XML-like agent output). `viewer` has neither output flag. `--dry-run` is available only on `install`, `uninstall`, and `reindex`; it previews the command's managed changes rather than creating a general read-only mode for all startup/database activity.

Some database/service commands can refresh existing installations before running unless an explicit `--db` or `--config` is supplied. Help and version exit before handler execution. `doctor` can initialize database state; `config get` does not write files.

## Command index

| Command | Purpose |
| --- | --- |
| `init` | Initialize a workspace database |
| `doctor` | Report runtime, configuration, database, and dependency information |
| `install user` / `install repo` | Connect or refresh Codex integration |
| `uninstall user` / `uninstall repo` | Disconnect; preserve config and data by default |
| `config get` / `set` / `unset` | Read or edit supported configuration |
| `viewer` | Serve the browser Viewer on loopback |
| `update` | Check or update an official standalone installation |
| `reindex` | Build the optional semantic index |
| `searchd start` / `status` / `stop` | Manage the optional Unix-socket semantic daemon |

## init

```sh
taplctl init
taplctl init --workspace-root /path/to/workspace --json
taplctl --db /path/to/tapl.db init
```

`--workspace-root PATH` initializes that folder's workspace explicitly. It cannot be combined with global `--db`. Without it, TAPL opens/initializes the selected database. Initialization does not install Codex integration.

## doctor

```sh
taplctl doctor
taplctl --db /path/to/tapl.db doctor --json
```

Reports TAPL and SQLite versions, configuration, selected database, extension-loading capability, schema, and optional dependency availability. The report is diagnostic data; a missing optional semantic dependency does not make full-text search unavailable. Run in the intended workspace or specify its database.

## install

```sh
taplctl install user --dry-run
taplctl install user
taplctl install repo --repo /path/to/repository --mode enforce
```

| Scope option | Default |
| --- | --- |
| `user --codex-home PATH` | `~/.codex` |
| `repo --repo PATH` | Current working directory |

Both scopes accept:

| Option | Meaning |
| --- | --- |
| `--taplctl-command COMMAND` | Executable used to locate sibling `tapl-mcp` and `tapl-hook` commands |
| `--mode {observe,enforce}` | Hook behavior; default `observe` |
| `--tapl-config-policy {prompt,overwrite,merge}` | Existing runtime-config policy; default `prompt` |
| `--force` | Let managed template/config values overwrite existing managed values |
| `--dry-run` | Preview managed writes |
| `--json` / `--agent` | Select output format |

`prompt` asks about existing runtime config when the version changes and preserves same-version config. Explicit `merge` adds missing defaults while keeping values; `overwrite` replaces with defaults. Both explicit policies apply even at the same version. `--force` also affects managed templates; use the explicit config policy to choose runtime-config handling.

Choose a user or repository connection scope, restart Codex, and trust the hook when prompted. Package installation is separate. Actual standalone executable paths, automatic refresh, and preservation rules are in [Agent integration](../getting-started/integrations.md).

## uninstall

```sh
taplctl uninstall user --dry-run
taplctl uninstall repo --repo /path/to/repository
taplctl uninstall user --purge-config --purge-db --dry-run
```

`user` accepts `--codex-home PATH`; `repo` accepts `--repo PATH`, with the same defaults as installation. Both accept `--dry-run`, `--json`, `--agent`, and:

| Option | Deleted in addition to the integration |
| --- | --- |
| `--purge-config` | Selected scope's `.tapl/config.toml` |
| `--purge-db` | Selected scope's `.tapl/tapl.db` and its `-wal`, `-shm`, and `-journal` sidecars |

Default uninstall removes TAPL's MCP entry, recognized hooks, and installation version marker. It preserves unrelated Codex settings/hooks, TAPL config, databases, backups, and other workspaces. Purge options are independent; combine them only when both categories should be deleted. Close sessions using the target database before purging it.

For `user`, the target is the home directory containing `--codex-home` (default `~/.codex`); it does not purge every project database. These commands leave executables and services installed. Use the [installation method](../getting-started/installation.md) to remove those. Preserved config does not re-enable an uninstalled integration.

## config

```text
taplctl [--config PATH] config get [KEY]
taplctl [--config PATH] config set KEY VALUE
taplctl [--config PATH] config unset KEY
```

`get` reads effective values, including defaults; omit `KEY` for all settings or use a section such as `search`. `set` writes a supported key using TOML value syntax; enum strings such as `hybrid` may be unquoted. `unset` removes the explicit value so the built-in default applies. Edits preserve comments and unrelated settings, and the resulting complete config must remain valid.

```sh
taplctl config get
taplctl config get search.mode --json
taplctl config set search.mode hybrid
taplctl config set workflow.authoring_detail normal
taplctl config set viewer.allowed_origins '["https://tapl.example.com"]'
taplctl config unset workflow.authoring_detail
```

Supported keys:

| Key | Value |
| --- | --- |
| `workflow.authoring_detail` | `precise`, `normal`, `minimal` |
| `recall.enabled` | Boolean |
| `search.mode` | `semantic`, `bm25`, `word`, `hybrid` |
| `search.max_results` | Integer ≥ 1 |
| `search.hybrid_semantic_ratio` | Number from 0 to 1 |
| `search.semantic_provider` | `local`, `daemon`, `auto` |
| `search.searchd_model_idle_timeout_seconds` | Integer ≥ 0 |
| `viewer.allowed_origins` | Unique HTTP(S) origin strings in a TOML array |
| `subagents.enabled`, `subagents.setup_complete` | Boolean |
| `subagents.strategy` | `conservative`, `balanced`, `aggressive` |
| `subagents.preference` | String |
| `subagents.models.<model-id>` | Nonempty, unique TOML array of reasoning-effort strings |
| `subagents.profiles` | TOML array of profile inline tables; candidate model/effort pairs must be allowlisted |

Do not copy guessed model IDs into configuration. Use the host's actual delegation-tool catalog and [SubAgent setup](../guides/subagents.md). See [configuration](../guides/configuration.md) for file scope, defaults, and examples.

## viewer

```sh
taplctl viewer
taplctl viewer --port 9000
taplctl viewer --allowed-origin https://tapl.example.com
taplctl --db /path/to/workspace/.tapl/tapl.db viewer
```

`--port PORT` defaults to `8000`. Repeat `--allowed-origin ORIGIN` to allow additional HTTP(S) browser origins; CLI origins combine with `viewer.allowed_origins`. Use an origin's scheme, host, and optional port without a path.

The service listens on `127.0.0.1`, does not open a browser automatically, and stops with `Ctrl+C`. Without a database override it uses a database only in the current folder; otherwise the page can ask for an initialized workspace. There is no public `--workspace` flag. See [Viewer and services](../guides/viewer.md) for service startup, proxy access, and RUN discard.

## update

```sh
taplctl update --check
taplctl update --json
```

`--check` checks without installing. Without it, an available newer release is installed after manifest and SHA-256 verification. Both forms require valid official standalone-install metadata. Homebrew and source installations must use their own update method. Channel preservation and deliberate version changes are explained in [installation](../getting-started/installation.md#update).

## reindex

```sh
taplctl reindex --dry-run
taplctl reindex --json
```

Builds the optional semantic index for the selected workspace's records. `--dry-run` previews indexing work. Semantic indexing requires optional dependencies; full-text search does not. See [search](../guides/search.md) for providers, fallback behavior, and indexing.

## searchd

```sh
taplctl searchd start
taplctl searchd status --json
taplctl searchd stop
```

| Subcommand | Options beyond output format |
| --- | --- |
| `start` | `--socket PATH`, `--idle-timeout SECONDS`, `--timeout-ms MS`, `--no-wait` |
| `status` | `--socket PATH`, `--timeout-ms MS` |
| `stop` | `--socket PATH`, `--timeout-ms MS` |

`--socket` overrides `TAPL_SEARCHD_SOCKET`, otherwise `~/.tapl/searchd.sock` is used. `--idle-timeout` is nonnegative and defaults to `search.searchd_model_idle_timeout_seconds` (1800 seconds). It unloads an idle model, not the daemon; `0` disables idle unloading. `--timeout-ms` must be positive; defaults are 15000 ms for startup readiness and 250 ms for status/stop requests. `--no-wait` returns without waiting for readiness.

The daemon requires Unix domain sockets and is unavailable on Windows. Windows can still use local semantic search or full-text fallback. Starting/stopping `searchd` does not start/stop the Viewer or Codex MCP process. See [search](../guides/search.md).
