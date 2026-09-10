# TAPL user guide

Operational details for installing, configuring, and running TAPL with Codex.

[← README](../README.md) · [한국어 가이드](guide.ko.md)

[Requirements](#requirements) · [Homebrew](#homebrew) · [Linux](#linux) ·
[Windows](#windows) · [Connect](#connect) · [Viewer](#viewer) ·
[Configuration](#configuration) · [SubAgents](#subagents) · [Troubleshooting](#troubleshooting)

<a id="requirements"></a>

## Requirements

- Python 3.11 or newer with the `venv` module. Homebrew uses `python@3.12`.
- SQLite with FTS5 and extension loading support.
- Homebrew for a formula installation; `uv` for source development.
- Windows PowerShell 5.1 or newer, or PowerShell 7, for the Windows installer.
- A browser for `taplctl viewer`; VS Code only for the optional extension.

The release wheel is platform-independent, but its Python dependencies still need compatible wheels. Uncommon architectures, very new Python releases, and musl-based Linux distributions such as Alpine may require local build tools.

<a id="homebrew"></a>

## Homebrew

Add the tap, then choose exactly one formula:

```sh
brew tap qkdxorjs1002/tap

# Stable release with full-text search
brew trust --formula qkdxorjs1002/tap/taplctl
brew install taplctl

# Or: stable release with semantic/vector search dependencies
brew trust --formula qkdxorjs1002/tap/taplctl-semantic
brew install taplctl-semantic

# Or: newest published release, including prereleases
brew trust --formula qkdxorjs1002/tap/taplctl-pre
brew install taplctl-pre
```

`taplctl` and `taplctl-semantic` follow stable releases. `taplctl-pre` follows the
newest published release, whether stable or prerelease; `taplctl@pre` is an alias.
Use the canonical formula names above consistently for trust, installation, and
prefix lookup.

All three formulae link `taplctl`, `tapl-mcp`, and `tapl-hook` and cannot coexist.
Before switching, uninstall the current formula, for example `brew uninstall taplctl`.
Homebrew installs pinned dependencies from release-hosted wheel bundles without
resolving packages from PyPI during installation.

During an upgrade or reinstall, the formula attempts to restart its viewer
service only if it was already running. A stopped or unregistered service, and a
fresh install, remain stopped. This does not restart a manually started
`searchd` or MCP stdio process.

Next, [connect TAPL to Codex](#connect).

<a id="linux"></a>

## Linux

```sh
curl -fsSL https://raw.githubusercontent.com/qkdxorjs1002/tapl/main/install.sh | sh
```

The installer needs `curl`, Python 3.11+ with `venv`, and writable installation directories. Its defaults are `${XDG_DATA_HOME:-$HOME/.local/share}/tapl` and `${XDG_BIN_HOME:-$HOME/.local/bin}`; override them with the corresponding XDG variables or `TAPL_INSTALL_ROOT` and `TAPL_BIN_DIR`.

It does not modify shell startup files or install Codex hooks. Apply any printed `PATH` export, make it persistent if needed, then connect TAPL to Codex below.

The standalone installer defaults to the latest stable release.

<a id="windows"></a>

## Windows

```powershell
irm https://raw.githubusercontent.com/qkdxorjs1002/tapl/main/install.ps1 | iex
```

The installer supports Windows 10 and 11 with Windows PowerShell 5.1+ or
PowerShell 7, Python 3.11+ with `venv`, and per-user writable directories. It
defaults to `%LOCALAPPDATA%\tapl` with a launcher at
`%LOCALAPPDATA%\tapl\bin\taplctl.cmd`. Override the paths or manifest with
`TAPL_INSTALL_ROOT`, `TAPL_BIN_DIR`, or `TAPL_INSTALL_MANIFEST_URL`.

It updates only the user `PATH`, requires no administrator privileges, validates
the release manifest, and verifies the wheel SHA-256 before activation. It does
not install Codex hooks. Review the script first if your environment requires a
different trust process.

The standalone installer defaults to the latest stable release.

<a id="connect"></a>

## Connect TAPL to Codex

For any of the three Homebrew formulae, run:

```sh
taplctl install user
```

The installer finds `taplctl` on `PATH` and uses the sibling `tapl-mcp` and
`tapl-hook` commands. A normal Homebrew installation needs no path override.

<details>
<summary>Optional: select a specific installation</summary>

Use `--taplctl-command` only when automatic discovery selects the wrong executable
or you need a specific installation. For example:

```sh
taplctl install user --taplctl-command "$(brew --prefix taplctl)/libexec/bin/taplctl"
```

Replace the formula name if you installed `taplctl-semantic` or `taplctl-pre`.
The specified executable locates that installation's companion commands.

</details>

Standalone installations use their actual executable paths:

Linux standalone installer:

```sh
taplctl install user --taplctl-command "$(realpath "$(command -v taplctl)")"
```

Windows standalone installer (PowerShell):

```powershell
$taplRoot = if ($env:TAPL_INSTALL_ROOT) { $env:TAPL_INSTALL_ROOT } else { Join-Path $env:LOCALAPPDATA "tapl" }
$taplInstall = Get-Content -Raw (Join-Path $taplRoot "install.json") | ConvertFrom-Json
taplctl install user --taplctl-command (Join-Path $taplInstall.venv "Scripts\taplctl.exe")
```

These commands install for your Codex account. Replace `user` with `repo` to
connect only the current repository. Installation adds an enabled
`mcp_servers.tapl` entry for `tapl-mcp` and lifecycle hooks for `tapl-hook`.
Restart Codex afterward, then trust the installed hook when first prompted.

<p align="center">
  <img src="../assets/tapl-trust-hook.png" alt="Codex trust prompt for the installed TAPL hook" />
</p>

<a id="viewer"></a>

## Viewer and services

From an initialized workspace:

```sh
taplctl viewer
# tapl viewer: http://127.0.0.1:8000

taplctl viewer --port 9000  # when port 8000 is busy
```

The viewer listens only on `127.0.0.1`, does not open a browser automatically,
and stops with `Ctrl+C`. The nearest `.tapl/tapl.db` is selected. If no workspace
is available—for example, when started as a Homebrew login service—the page asks
for an initialized workspace folder and remembers the last successful choice in
that browser.

When a trusted reverse proxy or tunnel publishes the viewer at another origin,
allow that exact browser origin explicitly:

```sh
taplctl viewer --allowed-origin https://tapl.example.com
```

For a persistent service, add the origins to `~/.tapl/config.toml` and restart
the matching Homebrew service:

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

The value must contain only the HTTP(S) scheme, host, and optional port. Repeat
`--allowed-origin` or use the configuration array to allow more than one origin.
CLI and configuration origins are combined. TAPL continues to listen only on
loopback; the proxy should handle authentication and TLS. Avoid wildcard origin
rules when the viewer is reachable from an untrusted network.

Start the installed Homebrew formula automatically at login with
`brew services start taplctl`, `brew services start taplctl-semantic`, or
`brew services start taplctl-pre`. Each service serves the viewer on port 8000.

The semantic formula intentionally does not start a preloaded search process.
Run `taplctl searchd start` and `taplctl searchd status` when you want one.

The optional VS Code extension uses a persistent workspace-scoped `tapl-mcp`
client. Set `taplWorkflow.taplMcpPath` if it cannot locate the executable.

See the [VS Code extension guide](../vscode-extension/README.md) for its setup.

## Resume and search

Codex reads current state, archive details, and history through typed MCP tools.
SQLite full-text search works in every installation. Install the semantic extra
or the `taplctl-semantic` formula for embedding and vector search. Use
`taplctl reindex` when an existing workspace needs its index rebuilt.

## Management commands

`taplctl` has eight public commands. Agents use MCP to create, dispatch, settle,
search, and inspect workflow records; the CLI manages the installation.

| Command | Purpose |
| --- | --- |
| `taplctl init --workspace-root /path/to/workspace` | Select or initialize a workspace root |
| `taplctl doctor` | Diagnose installation and workspace problems |
| `taplctl install SCOPE` | Install or refresh Codex integration |
| `taplctl config set/unset` | Edit supported runtime configuration values |
| `taplctl viewer [--port 9000]` | Serve the local browser viewer |
| `taplctl update --check` / `update` | Check or update standalone installations |
| `taplctl reindex` | Rebuild search indexes |
| `taplctl searchd start` / `status` | Manage the optional semantic search process |

<a id="updates"></a>

## Updates

For Linux and Windows standalone installations:

```sh
taplctl update --check
taplctl update
```

The updater validates the release manifest and wheel SHA-256. It does not update
Homebrew or source checkouts. For Homebrew, use `brew update` followed by
`brew upgrade taplctl`, `brew upgrade taplctl-semantic`, or
`brew upgrade taplctl-pre`, matching the installed formula.

<a id="configuration"></a>

## Workspace and configuration

TAPL loads repo-local `.tapl/config.toml` before `~/.tapl/config.toml`. A database
also acts as the workspace anchor: the first hook initializes the payload working
directory if no ancestor database exists, and nested Git repositories reuse the
nearest workspace database. Run `taplctl init --workspace-root PATH` inside a
deliberately independent nested repository to give it separate history.

Installation preserves unrelated Codex settings. `hooks.json` is managed-merged,
and `.codex/config.toml` is TOML-merged with existing user values taking
precedence. Runtime config is created on first install; upgrades can prompt to
overwrite defaults or merge missing keys. Use `--force` for TAPL-managed template
values to win, or `--tapl-config-policy {prompt,overwrite,merge}` to select the
runtime config policy explicitly.

Edit runtime values without hand-editing TOML:

```sh
taplctl config set search.mode hybrid
taplctl config set search.max_results 20
taplctl config set viewer.allowed_origins '["https://tapl.example.com"]'
taplctl config set subagents.strategy balanced
taplctl config unset search.mode
```

`set` accepts a dot-separated `KEY` and one `VALUE`. Values use TOML syntax;
enum strings may be unquoted, while arrays should normally be shell-quoted as
shown above. `unset` accepts only `KEY` and restores the built-in default. Both
commands validate the complete resulting config and preserve comments and
unrelated settings. Use `taplctl config --help` or `taplctl config set --help`
for every supported key, value format, allowed enum, and example.

The supported keys are `search.mode` (`semantic`, `bm25`, `word`, or `hybrid`),
`search.max_results` (integer ≥ 1), `search.hybrid_semantic_ratio` (0.0–1.0),
`search.semantic_provider` (`local`, `daemon`, or `auto`),
`search.searchd_model_idle_timeout_seconds` (integer ≥ 0),
`viewer.allowed_origins` (unique HTTP(S) origins in a TOML string array),
`subagents.enabled` (`true` or `false`), `subagents.strategy` (`conservative`,
`balanced`, or `aggressive`), `subagents.setup_complete` (`true` or `false`),
`subagents.preference` (a free-form string), `subagents.models.<model-id>` (a
non-empty TOML array of unique reasoning-effort strings), or
`subagents.profiles` (a TOML array of inline profile tables).

Without an override, the command uses the same repo-local-then-user lookup order
described above and creates the repo-local path when neither file exists. To edit
another file, place the global option before the command:

```sh
taplctl --config /path/to/config.toml config set search.mode bm25
```

## Associative memory

Automatic hints are capped at 1,200 UTF-8 bytes in total. They use the existing
SQLite database and FTS, without embeddings, additional model calls, or a daemon.
Reinforcement occurs at most once per run and requires 24 hours since the last
content edit or reinforcement. Age alone never deletes or excludes a relevant memory.

`[recall] enabled = true` is the default. `tapl_summarize_run` accepts an optional
`recall_query` and emits at most three compact hints once per run. Hooks, status,
and next-action checks do not search memory. Start from emitted cues and verify
the original item or archive; use `tapl_search_history` when cues are insufficient.
Memory text is evidence to assess, never instructions to execute.

`tapl_finish_run` accepts optional `memory_candidates` and `memory_uses`. Each
candidate has slot 1 or 2, 3–5 cues, a note of at most 240 characters, and
`source_run_id` with an optional `source_item_id`. Capture only durable lessons
supported by this run, such as a verified pitfall or reusable decision. Omit
routine summaries, secrets, raw dumps, and speculation. Uses identify the memory
and revision, `source_checked=true`, and concrete `usage`; merely seeing a hint
does not strengthen it. Supply `expected_run_id` with either memory argument.

The result commits before optional memory processing. Inspect the returned
per-candidate/use errors; retry using the same run and slot only while that run
is active. A stale archived-run retry cannot update the next active run. Content
edits reset the memory's freshness; verified use can extend its half-life from
7 days toward a 90-day cap without rewriting content timestamps.

The Viewer supports read-only memory list/search, detail, and original-source
inspection. Ask the agent explicitly to update or delete a memory through
`tapl_update_memory` or `tapl_delete_memory` with `expected_revision`. Conflicts
require reading the current revision before trying again. Deletion tombstones
the memory and removes it from recall. `tapl_recall` is a manual read-only query.

```sh
taplctl config set recall.enabled false
taplctl config unset recall.enabled  # restore default true
```

Disabling recall stops automatic capture, recall, and reinforcement. Manual
inspection, update, and deletion remain available. These use MCP; no workflow
memory commands are added to the management CLI.
The schema 11 migration first saves a one-time `.tapl/tapl.db.pre-v11.bak` backup
and preserves original workflow records. To roll back, stop the servers before
restoring that backup; preserve work recorded after the backup separately.

<a id="subagents"></a>

## SubAgent setup and preferences

TAPL coordinates execution manifests; the Codex/root runtime creates and manages
SubAgents. Executable tasks need completed dependencies and exclusive,
non-overlapping file or directory ownership. Sequential work, shared state, and
cross-task decisions remain on root. Strategy and profiles guide the decision;
they do not force delegation.

```toml
[subagents]
# TAPL asks for preferences on the first concrete request.
setup_complete = false
enabled = true
# strategy is a decision bias; the agent still evaluates each task.
strategy = "aggressive"
preference = ""

[subagents.models]
# Models are recorded from the current runtime during first-use setup.
```

On the first concrete TAPL request, the agent checks the model IDs and reasoning
efforts exposed by its current runtime, then asks whether to use SubAgents and
what preferences to apply. It saves the answer in the resolved
configuration file and marks setup complete. TAPL never calls a provider API or
ships an external model list for this step. `enabled = true` takes effect only
after setup is complete. If the runtime catalog is unavailable, setup remains
pending and work stays on the root agent. After an answer, the agent records it
with `tapl_configure_subagents`; the answer itself is the user confirmation.
Existing configurations with an explicit model allowlist or `enabled = false`
remain complete and retain their choices; new model settings apply only when
the user requests an update.

After your answer, TAPL also records the full runtime catalog in `subagents.available_models`. On the first request in each session, the agent passes the current catalog to `tapl_get_next`. Added or removed models and changed reasoning efforts trigger an update-or-keep suggestion. Keeping your choices records the new catalog without changing your allowlist, so the same change is not proposed again. Existing configurations without a catalog keep working; the agent can offer to record a baseline once.

The installed template includes these model-neutral advisory profiles, listed
in safety-first order:

| Profile | Use when | Bias |
| --- | --- | --- |
| `high-risk-cross-cutting` | High-risk, cross-cutting, shared-context, or coordination-heavy work | `avoid` |
| `deep-reasoning` | Complex, uncertain, or context-heavy decisions | `neutral` |
| `general-implementation` | Ordinary bounded implementation work | `inherit` |
| `bounded-routine` | Small, local, predictable, low-risk work | `prefer` |

Profiles have empty candidates until setup supplies the runtime-supported model
and effort pairs. They describe task characteristics and delegation bias; they
do not assign permanent roles to model IDs.

An explicit `profiles = []` disables profiles. Any non-empty user
`subagents.profiles` array fully replaces the template profiles, and its
candidates must be present in `subagents.models`.

When enabled, TAPL delivers its delegation policy, active profiles, and
model/reasoning allowlist through `tapl_get_next`. Matching remains advisory: the
agent evaluates all task characteristics, prefers the most specific profile,
and uses configured order only as a tie-break. It may choose and record a
justified profile or candidate override, skips unavailable candidates, and
falls back to another allowlisted pair or root when needed. The installed
`.tapl/config.toml` records selected models and preferences, then documents
every runtime option, its type, and allowed values inline.

For example, this array replaces the template profiles with one model-neutral
preference:

```toml
[[subagents.profiles]]
name = "release-automation"
characteristics = "bounded deployment steps with a known rollback"
delegation_bias = "prefer"
candidates = []
```

The `strategy` setting controls the delegation bias:

- `aggressive` (the default) favors delegation when tasks are independent,
  sufficiently self-contained, low enough risk, and have meaningful parallel
  value or save root context. It does not require delegation when context sharing
  or coordination cost makes root execution better.
- `balanced` weighs the same dimensions without a directional preference.
- `conservative` favors root execution and delegates only when the expected
  parallel value or root context savings clearly outweigh context transfer,
  coordination, and risk.

For stored or executable tasks, every strategy still requires execution approval,
dependency readiness, exclusive non-overlapping `owned_paths`, atomic dispatch,
and settlement by the exact `execution_id`; the root retains TAPL writes and
cross-task decisions. Dispatch records the manifest model and reasoning effort
in the legacy `SubAgent Model`
custom field before the runtime spawns that SubAgent. To change the bias, set
`strategy` to `balanced` or `conservative`; to disable TAPL delegation guidance,
set `enabled = false`. This does not remove delegation instructions from another
source such as `AGENTS.md`.

For each executable task, TAPL uses four canonical task custom fields throughout
the lifecycle:

- `Task Profile` records the selected profile (or no match) and match reason.
- `Task Characteristics` records independence, required context, risk,
  coordination cost, and parallel value.
- `Execution Decision` records root versus SubAgent, model/effort, rationale,
  and any profile or model override. Create or update these fields during task
  design, before dispatch, and after settlement when the decision changes.
- `User Notes` is conditional. Add it only for durable user-relevant facts not
  represented by standard fields, using concise category/content/impact entries.

The legacy `SubAgent Model` field remains written at atomic dispatch for
compatibility and is omitted when no SubAgent runs. The installed configuration
is preference input; runtime support, safety gates, and the recorded decision
remain authoritative.

The workflow follows the scope the user authorized. An explicit request to edit
or test counts as approval for that work; an investigation-only request does not
authorize a fix. Record the applicable approval and execution state without
asking again for permission already given.

### Read-only exploration

Once setup is complete and delegation is enabled, bounded exploration may use a
host SubAgent before or after planning without artificial tasks, batches, or
`owned_paths`. Skip scouting for self-contained requests or sufficiently known
scope. Root handles a known target needing one check; unclear targets,
dependencies, or validation boundaries can use one eligible read-only helper
without nested helpers.

Before classification, root and helper share at most three targeted local
read-only lookups total. Failures do not replenish that budget; unreported helper
usage consumes its allocated quota. Give the helper the request, scope, remaining
lookup and response budgets, restrictions, and stop condition instead of full
history by default. Prioritize source, configuration, and tests; request compact
`file:line` findings, dependencies, validation needs, risks, unknowns, and lookup
usage. Root uses the report without repeating searches except for essential
unresolved questions within the remaining budget.

The scout may not edit, run tests, perform external research or history searches,
or mutate TAPL state. Root classifies the workflow and writes its records after
the scout. After classification, applicable source and history rules apply.
Select only model/effort pairs in both the configured allowlist and live runtime
catalog. Pending setup, disabled delegation, or no suitable candidate leaves the
lookup on root. Scouting does not bypass execution approval and does not
promise lower latency or token usage.

<a id="troubleshooting"></a>

## Troubleshooting

| Symptom | What to do |
| --- | --- |
| Codex does not see TAPL | Run `taplctl doctor`, repeat the package-specific connect command in [Connect TAPL to Codex](#connect), then restart Codex |
| `taplctl` is not found after standalone install | Apply the installer's printed `PATH` export and add it to your shell profile |
| The viewer cannot find a workspace | Initialize it or choose a folder that already contains `.tapl/tapl.db` |
| Port 8000 is busy | Stop the Homebrew service or run `taplctl viewer --port PORT` |
| A Homebrew formula conflicts | Uninstall the installed TAPL formula before selecting another |

For an unresolved issue, include the relevant `taplctl doctor` output in a
[bug report](https://github.com/qkdxorjs1002/tapl/issues).
