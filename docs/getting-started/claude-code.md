# Claude Code

[Documentation](../README.md) · [한국어](claude-code.ko.md)

Claude Code uses TAPL's shared workflow MCP tools, lifecycle checks, history and Viewer. Its installation, session owners and delegation settings are separate from Codex. Install the [TAPL executables](installation.md) first.

## Connect and remove

Choose the Claude Code channel in [installation](installation.md), then select one connection scope:

```sh
taplctl install user --client claude-code
# Or, inside the intended working folder:
taplctl install repo --client claude-code
```

The installation default is `observe`; add `--mode enforce` for blocking checks. The CLI defaults to `codex`, so always add `--client claude-code` to Claude installation and removal commands.

See [Agent integration](integrations.md#choose-a-connection-scope) for MCP/hook files, user/repository scopes, custom homes, executable paths and trust steps. Preserve the client binding when moving executables: the MCP server launches with `TAPL_CLIENT=claude-code`, and hooks launch `tapl-hook --client claude-code`.

[Automatic refresh](integrations.md#automatic-refresh) and [disconnection/reconnection](integrations.md#disconnect-or-reconnect) apply to the selected client and scope. Claude and Codex have separate installation markers; removing one client does not opt it back in through the other client's startup. For shared-file purge preservation and the `preserved_shared` result, see [uninstall boundaries](../reference/cli.md#uninstall).

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

Automatic coverage includes installation/removal/refresh, wheel/sdist templates, hook response contracts, owner isolation, independent settings, and two-task dispatch/settlement/recovery.

The published `2.17.0-beta1` installer and runtime passed validation in a morae Linux ARM64 VM with Claude Code `2.1.318`. Three real conversations in print mode passed: planning without edits or execution approval, an approved single-file edit, and two native Agents called in the same response with separate file ownership. Checks confirmed exact session owners, file contents, execution-ID settlement and completed RUN archival; the planning RUN remained active. All five hook events were recorded, and a separate call to the registered enforce hook denied an unapproved `Write` request.

These conversations used VM-local `bypassPermissions` and `inherit` model selection, omitting Agent model/effort parameters. They do not cover every OS/version, interactive trust prompts or explicit model/effort selection. Protocol checks alone do not establish live conversation behavior.

If MCP is connected but a call reports a missing owner, start a new session and verify the hooks loaded. Do not guess another session's ID. If user and repository integrations both exist, inspect Claude's effective MCP source and remove the unwanted scope explicitly. For stale executables, preview reinstall with `--taplctl-command`; for invalid JSON/TOML, repair the named file before refresh. See [troubleshooting](../guides/troubleshooting.md).
