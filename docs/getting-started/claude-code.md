# Claude Code

[Documentation](../README.md) · [한국어](claude-code.ko.md)

Claude Code uses TAPL's shared workflow MCP tools, lifecycle checks, history and Viewer. Its installation, session owners and delegation settings are separate from Codex. Install the [TAPL executables](installation.md) first.

## Connect and remove

Choose one scope:

```sh
taplctl install user --client claude-code
# Or, inside the intended working folder:
taplctl install repo --client claude-code --mode enforce
```

The default client remains `codex`. Add `--client claude-code` to every Claude install/uninstall command. Both scopes support `--dry-run`, `--tapl-config-policy`, `--taplctl-command` and `--mode observe|enforce`; see [CLI options](../reference/cli.md#install). `observe` is the installation default.

| Scope | MCP configuration | Lifecycle hooks |
| --- | --- | --- |
| User | `~/.claude.json`, top-level `mcpServers.tapl` | `~/.claude/settings.json` |
| Repository | `.mcp.json` | `.claude/settings.json` |

`install repo --repo PATH` selects a working folder. `install user --claude-home PATH` selects the Claude settings directory; its parent holds `.claude.json` and `.tapl`. This is different from Claude's project-local MCP scope in `~/.claude.json`: TAPL's `repo` command writes the shared project `.mcp.json`.

Restart Claude Code and complete its MCP/workspace trust steps, then check `/mcp`. The installed server launches `tapl-mcp` with `TAPL_CLIENT=claude-code`; the five command hooks launch `tapl-hook --client claude-code`. Keep that client binding when moving an executable. The [executable discovery examples](integrations.md#executable-discovery) also apply with the client option added.

```sh
taplctl uninstall user --client claude-code --dry-run
taplctl uninstall user --client claude-code
# Or:
taplctl uninstall repo --client claude-code --repo /path/to/workspace
```

Installation merges TAPL-owned entries while preserving other hooks, servers and settings. Even `--tapl-config-policy overwrite` preserves the other client's delegation settings. Removal keeps TAPL data/config by default. Explicit purge preserves shared files when another client has installation markers, configured preferences or recorded session ownership; JSON output reports `preserved_shared`. Generated defaults alone do not count as configured peer preferences. See [uninstall boundaries](../reference/cli.md#uninstall).

Automatic refresh checks only previously installed Claude scopes, preserving hook mode and a missing local config. It uses `.tapl/claude-code.version` and `.tapl/claude-code.install-state.json`; Codex retains its existing markers. Removing one client does not opt it back in through another client's startup.

## Hooks and session ownership

`SessionStart` and `UserPromptSubmit` supply context, `PreToolUse` checks durable edits, `PostToolUse` supplies research-recording guidance, and `Stop` checks remaining workflow work. Claude receives event-specific `additionalContext` and denial responses. TAPL does not auto-allow a call or change Claude's permission rules. Enforced hooks are workflow checks, not a security sandbox.

Use the exact TAPL `session_id` from hook context on **every** MCP call. Claude's owner is `claude-code:<native-session-id>`; raw, missing and foreign-client IDs are rejected. Codex keeps its existing IDs and isolated legacy behavior. The shared DB can hold separate RUNs for both clients without transferring approvals, queues or completion ownership. Files remain shared, so coordinate concurrent edits or use worktrees.

Helpers retain the parent's TAPL owner and their separate Claude `agent_id`. They do not create a root RUN or stop the parent's lifecycle. Root alone writes TAPL state. Stop reentry does not repeatedly block the same continuation. Resume/compaction contexts must retain or reload the correct owner and policy.

## Models and Agent execution

Claude preferences live under `[clients.claude-code.subagents]`; `[subagents]` remains Codex's configuration. First-use setup and later catalog checks use the current host's actual tool schema and your confirmed choices. TAPL does not fetch a provider model catalog or infer one from Codex preferences.

This example assumes the live Agent tool exposes the `sonnet` alias but no effort parameter:

```toml
[clients.claude-code.subagents]
enabled = true
setup_complete = true
strategy = "balanced"
preference = "Prefer independent bounded tasks."
profiles = []

[clients.claude-code.subagents.models]
sonnet = []

[clients.claude-code.subagents.available_models]
sonnet = []
```

An empty effort array means omit `Agent.effort`; it does not assert an effort capability. The optional selection `models.inherit = []` means omit both `Agent.model` and `Agent.effort`, letting the host/agent definition choose. `inherit` is a selection mode and is rejected in `available_models`. Requested aliases can resolve differently through model definitions, organization policy and environment overrides; record observed differences.

Per-invocation effort needs a Claude version and live Agent schema that expose it. The [official Agent reference](https://code.claude.com/docs/en/sub-agents#choose-an-effort-level) documents version-dependent precedence. Use the live schema rather than assuming an installed version exposes every option.

For executable parallel work, root creates independent tasks with disjoint `owned_paths`, obtains approval and atomically calls `tapl_dispatch_tasks`. It verifies the manifest, starts one Agent per entry and passes the exact parent owner, task ID and execution ID. After reviewing results, root calls `tapl_complete_task`, `tapl_block_task` or `tapl_skip_task` with that execution ID. Failed/interrupted spawn requires batch recovery/cancellation before redispatch; new executions have new IDs. Agent completion alone does not settle a TASK. See [SubAgents](../guides/subagents.md).

```sh
taplctl config get clients.claude-code.subagents --json
taplctl config set clients.claude-code.subagents.strategy balanced
```

## Verification and troubleshooting

Automatic coverage includes installation/removal/refresh, wheel/sdist templates, hook response contracts, owner isolation, independent settings, and two-task dispatch/settlement/recovery. The built wheel has also passed installation and SessionStart checks in a morae Linux ARM64 VM. Live Claude model/Agent conversations and the full OS/version matrix remain separate validation gates; protocol tests alone do not establish them.

If MCP is connected but a call reports a missing owner, start a new session and verify the hooks loaded. Do not guess another session's ID. If user and repository integrations both exist, inspect Claude's effective MCP source and remove the unwanted scope explicitly. For stale executables, preview reinstall with `--taplctl-command`; for invalid JSON/TOML, repair the named file before refresh. See [troubleshooting](../guides/troubleshooting.md).
