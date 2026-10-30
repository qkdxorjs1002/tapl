# Workflow

[Documentation](../README.md) · [한국어](workflow.ko.md)

TAPL preserves a request's intent, plan, approval, execution, evidence, and result in the workspace database. Codex manages the records through MCP while you ask for outcomes normally. The workflow adapts to the request; every answer does not need the same number of records.

## Records through the lifecycle

| Record or stage | Purpose |
| --- | --- |
| RUN | Own the request, classification, session, and final result |
| HISTORY | Recover relevant earlier work and check its original evidence |
| PLAN | Describe one topic's requirements, approach, scope, and validation |
| APPROVAL | Preserve the user's execution decision and authorized scope |
| TASK | Track concrete execution, dependencies, verification, and blockers |
| FINDING | Preserve a fact and its effect on a decision |
| ARCHIVE | Keep the settled result available for later work |

A typical planned request moves from RUN and HISTORY to PLAN, approved TASK execution, verification, result recording, and ARCHIVE. Findings can be added whenever decision-relevant evidence appears. These labels describe responsibilities rather than a fixed script of tool calls. See [records and metadata](records.md) for the stored fields.

## Work type, rigor, and record mode

The agent classifies the requested outcome as `answer`, `investigation`, `analysis`, `planning`, `implementation`, or `mixed`. It independently selects rigor:

| Mode | Selection rule | Planning depth |
| --- | --- | --- |
| Fast | All dimensions are known low: one objective/surface, reversible work, one validation, closed boundaries; implementation touches at most two files | Compact executable plan for durable work |
| Standard | Work that qualifies for neither Fast nor Strict | Concise executable plan |
| Strict | Security/privacy/permission, schema/destructive work, public compatibility, deploy/external writes, incident/data correctness, irreversible impact, or conflicting evidence | Risks, interfaces, rollback, and validation boundaries |

Unknowns do not qualify for Fast. For workspace-dependent unknowns, the agent can make a bounded read-only scout before classification: at most three targeted local lookups across the root and helpers. This scout does not perform edits or tests. Scope, risk, or uncertainty growing later requires upward reclassification.

TAPL derives the record mode rather than asking you to choose it:

- **Lightweight:** Fast, non-durable Answer/Investigation/Analysis/Planning; no PLAN or TASK records required.
- **Planned:** durable work and all Standard/Strict requests; explicit PLAN/TASK records carry execution.

Creating a plan can promote a lightweight run to planned without changing its work type or rigor. Authoring detail (`precise`, `normal`, `minimal`) changes record verbosity and task grouping; it does not change rigor, approval, required evidence, or completion rules. See [authoring detail](../guides/authoring-detail.md).

## One request, one or more topics

Default to one RUN. Independent topics use separate plans in request order, such as `PLAN-001` for a parser fix and `PLAN-002` for an unrelated Viewer improvement. Write each topic's requirements, approach, and validation before designing its tasks. A task's `spec_id` points to its topic's plan.

Steps, examples, constraints, and tests that serve one outcome stay together in one plan. Two independent edits for one feature can be separate tasks within that plan. Separate RUN lifecycles are used only when explicitly requested; split queues can express stated order or consumed-result dependencies.

For example:

> Fix the configuration parser and verify it. Separately, investigate Viewer startup delays.

This usually yields one RUN with two plans, not a plan per edited file. If the requested topics have different work types, the RUN is Mixed and uses the highest topic rigor.

## Approval and execution

Planning precedes implementation. The agent resolves material scope, compatibility, interface, or tradeoff questions and obtains explicit user confirmation before finalizing the plan. Plan confirmation and execution approval have separate purposes: an explicit request to edit, implement, verify, or test already authorizes execution within that scope, and TAPL records that approval. Approval does not expand the request or authorize unrelated changes.

For sequential execution, start a dependency-ready task immediately before work and settle it before starting the next task:

| Status | Meaning |
| --- | --- |
| Pending | Designed work that has not started |
| In Progress | Work actively executing |
| Completed | Implementation and its required verification are done |
| Blocked | Cannot proceed; preserve the blocker and concrete next action |
| Skipped | Intentionally omitted or superseded; preserve the reason |

Do not mark unverified work completed. Task grouping follows the configured authoring detail and the work's risk, dependencies, and ownership.

Parallel execution uses an atomic batch dispatch. Eligible tasks share a plan and parallel group, use a real SubAgent executor, have completed dependencies, and own exclusive paths. The root verifies the dispatch manifest, starts actual agents, and settles each execution with its exact `execution_id`. Interrupted or unstarted batches require recovery/cancellation before retrying. A database batch does not launch or terminate an external agent by itself. See [SubAgents](../guides/subagents.md).

## Workspace and session boundaries

The Codex working folder itself owns `.tapl/tapl.db`. TAPL does not search parent databases, Git roots, or repository markers. A session in `repo/packages/app` uses `repo/packages/app/.tapl/tapl.db`, even when `repo/.tapl/tapl.db` exists. It does not move or merge older databases.

The hook requires an existing absolute `cwd` in its event; the MCP server stays bound to its startup working folder for its lifetime. A hook database override must identify that folder's database. Administrative CLI commands offer explicit database/workspace selection; see [CLI reference](../reference/cli.md).

Every MCP call must pass the Codex hook's `session_id`. Each session owns its RUN, approval, tasks, split queue, Stop handling, and archive lifecycle. Resuming the same session continues its RUN; a new session does not adopt another session's work. Omission selects an isolated legacy scope, and unidentified writes are rejected after session-owned records exist. Existing pre-session records remain legacy; the schema upgrade first preserves `.tapl/tapl.db.pre-v14.bak`.

History can be searched across the workspace, while active workflow ownership remains session-scoped. Working files are shared: coordinate simultaneous edits or use separate worktrees. Session ownership and batch path checks are not filesystem isolation.

## Verification and closure

The agent checks task results against the plan's validation, records the final result with `tapl_finish_run`, and reviews memory candidates or explicitly skips capture with a reason. It inspects the finish receipt and resolves pending memory errors before `tapl_finish_archive`. The work result is saved separately from memory processing; see [associative memory](../guides/memory.md).

Leave pending, blocked, skipped, or unverified work visible rather than claiming completion. Archive when actionable work is settled, the run is superseded/stale, or the user explicitly chooses archive/discard. A planning-only request remains active until the user chooses execution or closure.

`observe` hooks report workflow issues; `enforce` hooks can block durable tool use or Stop for missing workflow prerequisites, incomplete tasks, or active batches. This hook setting is separate from Fast/Standard/Strict. The Viewer can show validation and provides an explicitly confirmed RUN discard action; it does not validate the correctness of your code. See [integration](../getting-started/integrations.md) and [Viewer](../guides/viewer.md).

For a practical first run, use [quick start](../getting-started/quickstart.md). For exact lifecycle arguments and validation tools, use the [MCP reference](../reference/mcp.md).
