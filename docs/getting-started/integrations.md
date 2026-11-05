# Agent integration

[Documentation](../README.md) · [한국어](integrations.ko.md)

TAPL connects Codex and Claude Code through the shared `tapl-mcp` stdio server and host-specific `tapl-hook` lifecycle handling. Select the client and connection scope below. For Claude's session ownership and Agent preferences, see the [Claude Code guide](claude-code.md). Other MCP clients do not automatically gain either host's lifecycle behavior.

## Ask your agent to install TAPL

Copy this prompt into your coding agent:

```text
Install TAPL and connect it to my coding client.
Repository: https://github.com/qkdxorjs1002/tapl
Installation guide: https://github.com/qkdxorjs1002/tapl/blob/main/docs/getting-started/installation.md
Connection guide: https://github.com/qkdxorjs1002/tapl/blob/main/docs/getting-started/integrations.md

Read the guides, detect my OS and shell, and check prerequisites and any existing installation.
Before connecting, confirm my client and preferred scope unless already specified:
client: Codex or Claude Code; scope: user (all my projects) or repo (only the target repository).
Use the official installation method and the documented channel for that client unless I specify another release.
Run taplctl install user or taplctl install repo for my chosen scope; add --client claude-code for Claude Code and omit --client for Codex. Use the platform-specific executable path when needed.
Preserve existing TAPL settings, hook mode, workflow databases, and unrelated client settings.
Verify the result with taplctl --version and taplctl doctor.
Report the installed version and any remaining terminal/client restart and trust steps.
```

A repository URL in the prompt identifies the TAPL project; use the intended working repository for `install repo`.

## Choose a connection scope

[Install the executables](installation.md) first, then choose **one** row:

| Client | Scope | Command |
| --- | --- | --- |
| Codex | User: all your projects | `taplctl install user` |
| Codex | Repository: target repository only | `taplctl install repo` |
| Claude Code | User: all your projects | `taplctl install user --client claude-code` |
| Claude Code | Repository: target repository only | `taplctl install repo --client claude-code` |

The CLI defaults to `codex` when `--client` is omitted. Always include `--client claude-code` for Claude installation and removal. Run `repo` inside the target repository, or add `--repo /path/to/repository`.

The selected integration writes these host files:

| Client / scope | MCP configuration | Lifecycle hooks |
| --- | --- | --- |
| Codex user | `~/.codex/config.toml`, `mcp_servers.tapl` | `~/.codex/hooks.json` |
| Codex repository | `.codex/config.toml`, `mcp_servers.tapl` | `.codex/hooks.json` |
| Claude Code user | `~/.claude.json`, top-level `mcpServers.tapl` | `~/.claude/settings.json` |
| Claude Code repository | `.mcp.json`, `mcpServers.tapl` | `.claude/settings.json` |

Codex MCP settings use TOML; Claude MCP settings and both clients' hook files use JSON. TAPL's Claude `repo` scope writes shared project `.mcp.json`, rather than Claude's project-local MCP entry in `~/.claude.json`.

For a nondefault home, use `taplctl install user --codex-home /path/to/.codex` or `taplctl install user --client claude-code --claude-home /path/to/.claude`. The selected directory's parent holds user `.tapl` settings; for Claude it also holds `.claude.json`.

Repository installation also initializes local `.tapl` configuration and workflow state. User integration initializes each session's working-folder database on use without creating local `.tapl/config.toml` or repository installation markers.

Restart the selected client. In Codex, trust the installed hook when prompted. In Claude Code, complete MCP/workspace trust and check `/mcp`. Open the folder whose history you want to use. A nested folder owns its own database; connection scope does not make all folders share history. See [workspace and session boundaries](../concepts/workflow.md#workspace-and-session-boundaries).

## Executable discovery

Normal Homebrew installation needs no path override. The installer discovers `taplctl` on `PATH` and locates its sibling `tapl-mcp` and `tapl-hook` executables.

Use `--taplctl-command` if discovery selects a different installation. These examples select user scope; replace `install user` with `install repo` for repository scope. Use the formula you installed (`taplctl`, `taplctl-semantic`, or `taplctl-pre`):

```sh
# Codex, with the taplctl formula:
taplctl install user --taplctl-command "$(brew --prefix taplctl)/libexec/bin/taplctl"
# Claude Code, with the taplctl-pre formula:
taplctl install user --client claude-code --taplctl-command "$(brew --prefix taplctl-pre)/libexec/bin/taplctl"
```

### Standalone executable paths

Linux's public launcher can be a symlink. Use its resolved executable to find companion commands. Choose the client, and replace `install user` with `install repo` for repository scope:

```sh
# Codex:
taplctl install user --taplctl-command "$(realpath "$(command -v taplctl)")"
# Claude Code:
taplctl install user --client claude-code --taplctl-command "$(realpath "$(command -v taplctl)")"
```

For Windows, read the active virtual environment from installation metadata in PowerShell:

```powershell
$taplRoot = if ($env:TAPL_INSTALL_ROOT) { $env:TAPL_INSTALL_ROOT } else { Join-Path $env:LOCALAPPDATA "tapl" }
$taplInstall = Get-Content -Raw (Join-Path $taplRoot "install.json") | ConvertFrom-Json
# Codex:
taplctl install user --taplctl-command (Join-Path $taplInstall.venv "Scripts\taplctl.exe")
# Claude Code:
taplctl install user --client claude-code --taplctl-command (Join-Path $taplInstall.venv "Scripts\taplctl.exe")
```

Run only the selected client's command; replace `install user` with `install repo` for repository scope. These paths select the installed executable and its companion commands; they do not select a different database.

## Hook mode and configuration preservation

New explicit installations default to `--mode observe`: hooks report workflow issues. `--mode enforce` can block durable tool use or stopping when required workflow state is missing. Preview and apply for your client, for example:

```sh
taplctl install repo --mode enforce --dry-run
taplctl install repo --mode enforce
# Or, for Claude Code:
taplctl install repo --client claude-code --mode enforce --dry-run
taplctl install repo --client claude-code --mode enforce
```

Hook mode is separate from Fast/Standard/Strict workflow rigor. An enforced hook is a workflow check, not a sandbox or security boundary. See [workflow](../concepts/workflow.md).

Installation merges TAPL-owned MCP entries and hooks, preserving unrelated host settings. Existing Codex TOML values take precedence unless `--force` is used for managed templates. Claude's managed MCP and hook entries are replaced while other servers and hooks are preserved. Runtime TAPL config has a separate `--tapl-config-policy`:

| Policy | Existing TAPL config behavior |
| --- | --- |
| `prompt` (default) | Ask when the installed version changes; preserve same-version config without prompting |
| `merge` | Keep existing values and add missing defaults, even at the same version |
| `overwrite` | Replace with runtime defaults, even at the same version; preserve the other client's delegation settings |

Use `--dry-run` to preview. See [configuration](../guides/configuration.md) for file precedence and [CLI reference](../reference/cli.md) for options.

## Automatic refresh

At production MCP startup and hook entry, TAPL checks version and shipped-template fingerprints for the current client's previously installed scopes. It preserves hook mode, merges missing defaults, and migrates known obsolete managed keys. Codex refresh also removes an obsolete TAPL MCP `cwd` override so the server can use the session working folder.

Each client has separate opt-in markers under user `~/.tapl` or repository `.tapl`:

| Client | Version marker | Template state |
| --- | --- | --- |
| Codex | `version` | `install-state.json` |
| Claude Code | `claude-code.version` | `claude-code.install-state.json` |

Automatic user refresh requires that client's version marker. Repository refresh also requires an existing database. Leftover hooks or config overrides alone do not opt in a scope. A missing local config stays missing so user settings/defaults continue to apply. Explicitly run the corresponding `taplctl install repo` command (add `--client claude-code` for Claude) to restore missing repository installation files.

An uninstalled client/scope stays disabled, including when the other client starts. Restart the selected client when host settings have changed; automatic refresh does not restart an already running host.

## Disconnect or reconnect

Use the matching client and scope. Preview before removal if needed:

```sh
# Codex:
taplctl uninstall user --dry-run
taplctl uninstall user
# Or:
taplctl uninstall repo --repo /path/to/repository

# Claude Code:
taplctl uninstall user --client claude-code --dry-run
taplctl uninstall user --client claude-code
# Or:
taplctl uninstall repo --client claude-code --repo /path/to/repository
```

Uninstall removes the selected client's TAPL MCP entry, recognized hooks, and installation markers. It preserves unrelated host settings, TAPL config, and workflow data. It leaves executables and background services installed; remove those with your [installation method](installation.md).

To reconnect, run the corresponding install command and restart that client. `--purge-config` and `--purge-db` are explicit destructive uninstall options. Shared files are preserved when the other client has installation markers, configured preferences or recorded session ownership; generated defaults alone do not count as configured preferences. JSON output reports `preserved_shared`. See [uninstall boundaries](../reference/cli.md#uninstall).

## Verify the connection

Run `taplctl --version` and `taplctl doctor` from the intended workspace, then start a new session in the selected client. The agent should have `tapl_*` MCP tools and receive hook context for that folder. Every MCP workflow call must pass the exact TAPL `session_id` supplied by that client's hook. Claude requires the namespaced owner `claude-code:<native-session-id>` and rejects missing, raw or foreign-client IDs. Codex retains its existing IDs; omitting its ID selects only the isolated legacy scope.

- [Quick start](quickstart.md): first workflow and Viewer check.
- [Claude Code](claude-code.md): hook events, session ownership, and Agent model preferences.
- [MCP reference](../reference/mcp.md): tools and session arguments.
- [Troubleshooting](../guides/troubleshooting.md): missing tools, hook trust, or stale paths.
