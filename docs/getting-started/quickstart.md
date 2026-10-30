# Quick start

[Documentation](../README.md) · [한국어](quickstart.ko.md)

Install TAPL, connect it to Codex, and keep asking for work in your own words. Codex manages the workflow records; you do not need to write PLAN or TASK records by hand.

## 1. Install TAPL

On macOS with Homebrew:

```sh
brew tap qkdxorjs1002/tap
brew trust --formula qkdxorjs1002/tap/taplctl
brew install taplctl
```

For Linux, Windows, semantic search, or prereleases, use [installation](installation.md). To delegate setup, copy the [agent installation prompt](integrations.md#ask-your-agent-to-install-tapl).

## 2. Choose one connection scope

| Scope | Use it when | Command |
| --- | --- | --- |
| User | You want TAPL across Codex projects | `taplctl install user` |
| Repository | You want TAPL only in the target repository | `taplctl install repo` |

Run `repo` in the target repository, or add `--repo /path/to/repository`. Standalone installations may need their [actual executable path](integrations.md#standalone-executable-paths).

Restart Codex, then trust the installed hook when prompted. Open your intended working folder. TAPL uses that exact folder's `.tapl/tapl.db`; a nested folder gets separate history.

## 3. Verify setup

From the intended working folder:

```sh
taplctl --version
taplctl doctor
```

Check the reported version, database path, SQLite capabilities, and dependencies. Semantic dependencies are optional. `doctor` may initialize workspace state and refresh an existing integration.

## 4. Ask for an outcome

For example:

> Investigate why the test command fails, fix the cause, and run the relevant checks.

Codex reads the current TAPL policy and session state, classifies the request, checks relevant history, and plans work where required. An explicit request to fix or test authorizes that scope. Material unresolved scope or tradeoffs can still require clarification.

You will see a RUN classification such as **Implementation · Standard · Planned**, plus concise planning, execution, and verification notices. The actual classification depends on the work: security/permission changes require Strict rigor; a Fast non-durable answer may need no PLAN or TASK records.

For planned work, the agent records the plan and tasks, executes approved work, verifies the result, records findings that affect decisions, and settles the run. At completion it reviews useful memory lessons, records the result, and archives once remaining work and memory errors are resolved. A planning-only request stays active until you choose execution or closure.

## 5. Inspect the result

Start the Viewer from that same folder:

```sh
taplctl viewer
# tapl viewer: http://127.0.0.1:8000
```

Open <http://127.0.0.1:8000>. Inspect the selected RUN, plans, tasks, findings, archives, and memories. The command does not open a browser automatically; press `Ctrl+C` to stop it. Use `taplctl viewer --port 9000` when port 8000 is busy.

For later work, ask Codex to find the relevant previous task or continue the current session's work. Session-owned RUNs remain isolated even in the same folder; working files remain shared. See [workflow boundaries](../concepts/workflow.md#workspace-and-session-boundaries).

## Next steps and limits

- [Workflow](../concepts/workflow.md): modes, approval, validation, and closure.
- [Records and metadata](../concepts/records.md): what is stored and how to read it.
- [Configuration](../guides/configuration.md): user/workspace settings and defaults.
- [Viewer](../guides/viewer.md) and [VS Code](../guides/vscode.md): inspect work in either interface.
- [Troubleshooting](../guides/troubleshooting.md): missing tools, hook trust, paths, and runtime problems.

Existing connected scopes refresh after TAPL updates; reconnecting is normally unnecessary. Restart Codex when host settings need reloading. TAPL's workflow records do not isolate concurrent file edits or replace your version-control workflow.
