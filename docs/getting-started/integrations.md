# Agent integration

[Documentation](../README.md) · [한국어](integrations.ko.md)

TAPL integrates with Codex through the `tapl-mcp` stdio server and `tapl-hook` lifecycle hooks. The installer configures both; `taplctl` handles management commands. This page documents the shipped Codex integration. Other MCP clients do not automatically gain Codex's hook or session behavior.

## Ask your agent to install TAPL

Copy this prompt into your coding agent, such as Codex:

```text
Install TAPL and connect it to Codex.
Repository: https://github.com/qkdxorjs1002/tapl
Installation guide: https://github.com/qkdxorjs1002/tapl/blob/main/docs/getting-started/installation.md
Connection guide: https://github.com/qkdxorjs1002/tapl/blob/main/docs/getting-started/integrations.md

Read the guides, detect my OS and shell, and check prerequisites and any existing installation.
Use the official installation method for my OS and the latest stable release unless I specify another channel.
Before connecting, confirm my preferred scope unless I already specified it: user (all my Codex projects) or repo (only the target repository).
Run taplctl install user or taplctl install repo for the chosen scope, using the platform-specific executable path when needed.
Preserve existing TAPL settings, hook mode, workflow databases, and unrelated Codex settings.
Verify the result with taplctl --version and taplctl doctor.
Report the installed version and any remaining terminal/Codex restart and hook-trust steps.
```

The prompt preserves your choice between user and repository scope. A repository URL in the prompt identifies the TAPL project; use the intended working repository for `install repo`.

## Choose a connection scope

[Install the executables](installation.md) first, then run **one** connection command:

| Scope | Applies to | Command |
| --- | --- | --- |
| User | Codex projects through user settings in `~/.codex` | `taplctl install user` |
| Repository | Target repository through its `.codex` settings | `taplctl install repo` |

Run `repo` inside the target repository, or pass `taplctl install repo --repo /path/to/repository`. For a nondefault Codex home, use `taplctl install user --codex-home /path/to/.codex`.

Both scopes add an enabled `mcp_servers.tapl` entry and lifecycle hooks. Repository installation also initializes local `.tapl` configuration and workflow state. User integration initializes each session's working-folder database on use without creating local `.tapl/config.toml` or `.tapl/version` files.

Restart Codex to load the server and hooks, then trust the installed hook when first prompted. Open the folder whose history you want to use. A nested folder owns its own database; the connection scope does not make all folders share history. See [workspace and session boundaries](../concepts/workflow.md#workspace-and-session-boundaries).

## Executable discovery

Normal Homebrew installation needs no path override. The installer discovers `taplctl` on `PATH` and locates its sibling `tapl-mcp` and `tapl-hook` executables.

Use `--taplctl-command` if discovery selects a different installation. For Homebrew, replace the formula name when using `taplctl-semantic` or `taplctl-pre`:

```sh
# Choose one scope:
taplctl install user --taplctl-command "$(brew --prefix taplctl)/libexec/bin/taplctl"
# Or, from the target repository:
taplctl install repo --taplctl-command "$(brew --prefix taplctl)/libexec/bin/taplctl"
```

### Standalone executable paths

Linux's public launcher can be a symlink. Use its resolved executable to find companion commands:

```sh
# Choose one scope:
taplctl install user --taplctl-command "$(realpath "$(command -v taplctl)")"
# Or, from the target repository:
taplctl install repo --taplctl-command "$(realpath "$(command -v taplctl)")"
```

For Windows, read the active virtual environment from installation metadata in PowerShell:

```powershell
$taplRoot = if ($env:TAPL_INSTALL_ROOT) { $env:TAPL_INSTALL_ROOT } else { Join-Path $env:LOCALAPPDATA "tapl" }
$taplInstall = Get-Content -Raw (Join-Path $taplRoot "install.json") | ConvertFrom-Json
# Choose one scope:
taplctl install user --taplctl-command (Join-Path $taplInstall.venv "Scripts\taplctl.exe")
# Or, from the target repository:
taplctl install repo --taplctl-command (Join-Path $taplInstall.venv "Scripts\taplctl.exe")
```

Run only your chosen scope's command. These paths select the installed executable and its companion commands; they do not select a different database.

## Hook mode and configuration preservation

New explicit installations default to `--mode observe`: hooks report workflow issues. `--mode enforce` can block durable tool use or stopping when required workflow state is missing. For example, from your target repository:

```sh
taplctl install repo --mode enforce --dry-run
taplctl install repo --mode enforce
```

Hook mode is separate from Fast/Standard/Strict workflow rigor. An enforced hook is a workflow check, not a sandbox or security boundary. See [workflow](../concepts/workflow.md).

Installation merges TAPL hooks and Codex TOML while preserving unrelated settings. Existing Codex values take precedence unless `--force` is used for managed templates. Runtime TAPL config has a separate `--tapl-config-policy`:

| Policy | Existing TAPL config behavior |
| --- | --- |
| `prompt` (default) | Ask when the installed version changes; preserve same-version config without prompting |
| `merge` | Keep existing values and add missing defaults, even at the same version |
| `overwrite` | Replace with runtime defaults, even at the same version |

Use `--dry-run` to preview. See [configuration](../guides/configuration.md) for file precedence and [CLI reference](../reference/cli.md) for options.

## Automatic refresh

At production MCP startup and hook entry, TAPL checks version and shipped-template fingerprints for previously installed scopes. It preserves hook mode, merges missing defaults, and migrates known obsolete managed keys. It also removes an obsolete TAPL MCP `cwd` override so the server can use the session working folder.

Automatic user refresh requires `~/.tapl/version`. Repository refresh requires an existing database and `.tapl/version`. Leftover hooks or config overrides alone do not opt in a scope. A missing local config stays missing so user settings/defaults continue to apply. Explicitly run `taplctl install repo` to restore missing repository installation files.

An uninstalled scope stays disabled. Restart Codex when host settings have changed; automatic refresh does not restart an already running host.

## Disconnect or reconnect

Use the matching scope:

```sh
taplctl uninstall user --dry-run
taplctl uninstall user
# Or:
taplctl uninstall repo --repo /path/to/repository
```

Uninstall removes TAPL's MCP entry, recognized hooks, and installation version marker. It preserves unrelated Codex settings, TAPL config, and workflow data. It leaves executables and background services installed; remove those with your [installation method](installation.md).

To reconnect, run the corresponding `taplctl install` command and restart Codex. `--purge-config` and `--purge-db` are explicit destructive uninstall options; see [CLI reference](../reference/cli.md#uninstall).

## Verify the connection

Run `taplctl --version` and `taplctl doctor` from the intended workspace, then start a new Codex session. The agent should have `tapl_*` MCP tools and receive hook context for that folder. Every MCP workflow call must pass the Codex hook's `session_id`; omitting it selects only the isolated legacy scope.

- [Quick start](quickstart.md): first workflow and Viewer check.
- [MCP reference](../reference/mcp.md): tools and session arguments.
- [Troubleshooting](../guides/troubleshooting.md): missing tools, hook trust, or stale paths.
