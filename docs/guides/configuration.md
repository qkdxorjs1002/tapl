# Configuration

[Documentation](../README.md) · [한국어](configuration.ko.md)

Choose the configuration file that controls the current working folder, inspect effective values, and change supported settings without rewriting unrelated TOML.

Delegation preferences are client-scoped: `[subagents]` belongs to Codex, while `[clients.claude-code.subagents]` belongs to Claude Code. Use `taplctl config get clients.claude-code.subagents --json` to inspect Claude settings and the same explicit prefix with `config set`/`unset`. Within a Claude MCP/hook call, logical `subagents` values resolve to that host. Claude permits empty effort arrays and an explicit inheritance selection; see [the Claude guide](../getting-started/claude-code.md#models-and-agent-execution).

## Workspace and file selection

Agent sessions write to `.tapl/tapl-{UUID}.db` in their exact working folder and read other `tapl-*.db` history there. Hooks require an existing absolute `cwd`; a hook `--db` must name that folder's current local database. The MCP server stays bound to its startup folder. Parent databases, Git roots, and repository markers are not searched, so child folders keep separate history. Administrative CLI commands retain explicit `--db` and `--workspace-root` overrides. See [Local identity and shared history](storage.md) for UUID persistence and legacy migration.

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

## Viewer settings

Open **Management → Settings** in the browser Viewer or VS Code extension. The page covers every key in the CLI's editable registry, including separate Codex and Claude Code model allowlists and ordered profiles/candidates. Model IDs, effort lists, profiles and origins use structured inputs. Display language, layout and the extension MCP executable use `viewer.language`, `viewer.layout` and `viewer.mcp_path` in this same file. Save to apply changes. `auto` follows the host language and available width.

Check the displayed file path: selection follows the precedence above for the current workspace. A browser Viewer started with explicit `--config PATH` stays pinned to that file. Selecting an archived RUN or another source database does not change the configuration target. **Save changes** validates the complete candidate and writes all changed values atomically, retaining comments and unrelated settings. Concurrent external changes invalidate the document revision; reload before saving again. Failed saves preserve the draft. Returning to Settings retains edits until the workspace changes or the Viewer reloads.

**Reset all to defaults** requires confirmation and removes every editable override for both clients from that file, including legacy aliases. Built-in defaults apply; comments, unrelated keys and saved model catalogs remain. A field's **Use default** control changes its draft value; save to apply it. Reset returns display language and layout to `auto`. Origin changes require restarting the browser Viewer service. A backend without settings support shows an update notice; update TAPL and restart its MCP/Viewer process. The CLI commands above remain available.

The extension reads these bootstrap fields directly before starting MCP; settings-page reads and writes use MCP, while the browser uses HTTP to the same validated Python settings service. Workspace and user config changes refresh the Viewer; changing the MCP executable reconnects after an in-flight save reply. The retired VS Code settings `taplWorkflow.language`, `taplWorkflow.layout` and `taplWorkflow.taplMcpPath` are ignored. Set the new TOML keys explicitly; no automatic migration writes user files.

## Public configuration keys

These canonical keys are accepted by `config set` and `config unset`. Runtime defaults below can differ from values selected during installation or first-use setup. The table uses Codex's `subagents.*` keys; the same delegation settings for Claude Code use `clients.claude-code.subagents.*`.

| Key | Type / allowed values | Built-in default |
| --- | --- | --- |
| `workflow.authoring_detail` | `auto`, `precise`, `normal`, `minimal` | `auto` |
| `recall.enabled` | Boolean | `true` |
| `search.mode` | `semantic`, `bm25`, `word`, `hybrid` | `hybrid` |
| `search.max_results` | Integer ≥ 1 | `12` |
| `search.hybrid_semantic_ratio` | Number 0.0–1.0 | `0.65` |
| `search.semantic_provider` | `local`, `daemon`, `auto` | `auto` |
| `search.searchd_model_idle_timeout_seconds` | Integer ≥ 0; `0` disables idle model unloading | `1800` |
| `viewer.language` | `auto`, `ko`, `en` | `auto`: follow the host language |
| `viewer.layout` | `auto`, `small`, `medium`, `large` | `auto`: adapt to available width |
| `viewer.mcp_path` | One executable path or command name; no shell arguments | `""`: automatic discovery in the extension |
| `viewer.allowed_origins` | Unique HTTP(S) origins as a TOML string array | `[]` |
| `subagents.enabled` | Boolean; effective delegation also needs completed setup | `true` |
| `subagents.strategy` | `conservative`, `balanced`, `aggressive` | `aggressive` |
| `subagents.setup_complete` | Boolean | `false` for a fresh config; inferred `true` if omitted with a nonempty model allowlist or disabled delegation |
| `subagents.preference` | TOML string; agent-authored English summary during [setup or preference updates](subagents.md#first-use-setup) | `""` |
| `subagents.models.<model-id>` | Unique reasoning-effort strings; Codex requires a nonempty array, Claude Code also accepts `[]` | No predefined model pairs |
| `subagents.profiles` | Ordered TOML inline tables; `[]` disables profiles | Four model-neutral profiles with empty candidates |

Read-only/effective values also include `search.hybrid_bm25_ratio` (`1 - hybrid_semantic_ratio`, default `0.35`) and `subagents.available_models` (the saved runtime catalog, or `null` when absent). They are not accepted by `config set`/`unset`. Catalog setup and updates use the agent's `tapl_configure_subagents` workflow. `path` and `exists` describe the selected source in structured output; they are not editable runtime settings.

Profile tables use `name`, optional `description`, `characteristics`, `delegation_bias` (`inherit`, `prefer`, `neutral`, `avoid`) and ordered `candidates` with `model` and `reasoning_effort`. For Claude Code, omitted or empty `reasoning_effort` means unspecified effort and must match an empty-effort allowlist entry; Codex requires a nonempty effort. Names must be unique and candidates must belong to the allowlist. User profiles replace built-ins. See [SubAgents](subagents.md) for setup and selection rules.

## Validate and apply

```sh
taplctl config set --help
taplctl config get --json
taplctl doctor
```

Inspect the reported source path before changing settings. A malformed selected file fails rather than falling through to another file. Removing a value must still leave the complete configuration valid; for example, completed enabled delegation requires an allowed model pair. `config get` reports defaults and inferred values, so removing a key does not necessarily make its effective value disappear.

The next full MCP policy lookup reflects changed policy settings and returns a changed `policy_revision`. Restart the affected host after changing its MCP/hooks integration; restart the Viewer service after changing its origin settings. Installation config merge/overwrite policies concern installation-time file updates, separately from runtime file selection; see [Installation](../getting-started/installation.md).

## Related pages

[Authoring detail](authoring-detail.md) · [SubAgents](subagents.md) · [Memory](memory.md) · [Search](search.md) · [CLI reference](../reference/cli.md)
