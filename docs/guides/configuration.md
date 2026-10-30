# Configuration

[Documentation](../README.md) · [한국어](configuration.ko.md)

Choose the configuration file that controls the current working folder, inspect effective values, and change supported settings without rewriting unrelated TOML.

## Workspace and file selection

A Codex session owns `.tapl/tapl.db` in its exact working folder. Hooks require an existing absolute `cwd` and reject missing or invalid values. A hook `--db` override must name that folder's database. The MCP server stays bound to its startup folder for its lifetime. TAPL does not search parent databases, Git roots or repository markers: `repo/packages/app` uses `repo/packages/app/.tapl/tapl.db` even when `repo/.tapl/tapl.db` exists. Each folder keeps independent history; existing databases are neither moved nor merged. Administrative CLI commands retain explicit `--db` and `--workspace-root` overrides.

Configuration selects **one file**, in this order:

1. The explicit global `--config PATH`, when supplied, even if that file does not exist.
2. `.tapl/config.toml` in the current working folder, if it exists.
3. `~/.tapl/config.toml`, if it exists.
4. Otherwise the current folder's `.tapl/config.toml` path, with runtime defaults until a file is created.

There is no parent-folder lookup or per-key merge between local and user files. When a local file exists, its missing keys use built-in defaults, not values from the user file. A repository-scoped install writes local configuration for the selected folder; this is still a working-folder rule rather than Git-root discovery.

## Read and edit

```sh
taplctl config get
taplctl config get search
taplctl config get workflow.authoring_detail
taplctl config get subagents.available_models --json
taplctl config set search.mode hybrid
taplctl config set search.max_results 20
taplctl config set subagents.strategy balanced
taplctl config unset search.mode
taplctl --config /path/to/config.toml config get search.mode --json
taplctl --config /path/to/config.toml config set search.mode bm25
```

`workflow.authoring_detail` reports the configured selection, including the default `auto`; it does not resolve a RUN mode. Runtime `authoring_policy` separately reports `configured`, `effective` and `workflow_mode`. `auto` maps Fast → `minimal`, Standard → `normal`, Strict → `precise`, with `normal` when no RUN is active. Explicit levels stay fixed and installation/updates preserve existing selections. See [Authoring detail](authoring-detail.md) for policy refresh and validation.

`get` never creates a missing file. Omit `KEY` for all effective settings, or select a section or dot-separated key. Strings print directly; other values print as JSON. `--json` includes the selected path, file existence, key and value. `--agent` keeps the JSON value in `<value format="json">`, including empty values and `null` for an unset catalog. Unknown keys and invalid config fail with a nonzero exit code.

`set KEY VALUE` accepts TOML values; enum strings may be unquoted. Shell-quote arrays and TOML strings. `unset KEY` removes the stored value so its default applies. Both commands validate the complete resulting configuration and preserve comments and unrelated settings. If neither local nor user file exists, a write creates the local path. An existing user file is selected for edits when there is no local file: use `--config` to choose the destination explicitly.

```sh
taplctl config set subagents.preference '"Prefer independent bounded tasks."'
taplctl config set viewer.allowed_origins '["https://viewer.example.invalid"]'
```

The example origin is a placeholder; replace it with the exact trusted browser origin. Origin values contain a scheme, host and optional port, with no credentials, path, query or fragment. The Viewer still listens on loopback. See [Viewer and services](viewer.md) for proxy configuration.

## Public configuration keys

These canonical keys are accepted by `config set` and `config unset`. Runtime defaults below can differ from values selected during installation or first-use setup.

| Key | Type / allowed values | Built-in default |
| --- | --- | --- |
| `workflow.authoring_detail` | `auto`, `precise`, `normal`, `minimal` | `auto` |
| `recall.enabled` | Boolean | `true` |
| `search.mode` | `semantic`, `bm25`, `word`, `hybrid` | `hybrid` |
| `search.max_results` | Integer ≥ 1 | `12` |
| `search.hybrid_semantic_ratio` | Number 0.0–1.0 | `0.65` |
| `search.semantic_provider` | `local`, `daemon`, `auto` | `auto` |
| `search.searchd_model_idle_timeout_seconds` | Integer ≥ 0; `0` disables idle model unloading | `1800` |
| `viewer.allowed_origins` | Unique HTTP(S) origins as a TOML string array | `[]` |
| `subagents.enabled` | Boolean; effective delegation also needs completed setup | `true` |
| `subagents.strategy` | `conservative`, `balanced`, `aggressive` | `aggressive` |
| `subagents.setup_complete` | Boolean | `false` for a fresh config; inferred `true` if omitted with a nonempty model allowlist or disabled delegation |
| `subagents.preference` | TOML string | `""` |
| `subagents.models.<model-id>` | Nonempty array of unique reasoning-effort strings | No predefined model pairs |
| `subagents.profiles` | Ordered TOML inline tables; `[]` disables profiles | Four model-neutral profiles with empty candidates |

Read-only/effective values also include `search.hybrid_bm25_ratio` (`1 - hybrid_semantic_ratio`, default `0.35`) and `subagents.available_models` (the saved runtime catalog, or `null` when absent). They are not accepted by `config set`/`unset`. Catalog setup and updates use the agent's `tapl_configure_subagents` workflow. `path` and `exists` describe the selected source in structured output; they are not editable runtime settings.

Profile tables use `name`, optional `description`, `characteristics`, `delegation_bias` (`inherit`, `prefer`, `neutral`, `avoid`) and ordered `candidates` with `model` and `reasoning_effort`. Names must be unique and candidates must belong to the allowlist. User profiles replace built-ins. See [SubAgents](subagents.md) for setup and selection rules.

## Validate and apply

```sh
taplctl config set --help
taplctl config get --json
taplctl doctor
```

Inspect the reported source path before changing settings. A malformed selected file fails rather than falling through to another file. Removing a value must still leave the complete configuration valid; for example, completed enabled delegation requires an allowed model pair. `config get` reports defaults and inferred values, so removing a key does not necessarily make its effective value disappear.

The next full MCP policy lookup reflects changed policy settings and returns a changed `policy_revision`. Restart Codex after changing its MCP/hooks integration; restart the Viewer service after changing its origin settings. Installation config merge/overwrite policies concern installation-time file updates, separately from runtime file selection; see [Installation](../getting-started/installation.md).

## Related pages

[Authoring detail](authoring-detail.md) · [SubAgents](subagents.md) · [Memory](memory.md) · [Search](search.md) · [CLI reference](../reference/cli.md)
