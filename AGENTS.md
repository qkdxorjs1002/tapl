# Workflow

Write workflow documents in the user's language unless asked otherwise. Keep them short, practical, and current. Do not add unstated requirements or expand scope without explicit user approval.

## 0. Core Rules

- Active workflow files live under `.agent-workflow/`.
- Do not modify source, tests, docs, configs, migrations, generated files, or other durable project artifacts before execution approval.
- Workflow files may be created or updated before execution approval.
- Do not commit, push, rebase, reset, discard changes, or include workflow files in commits unless explicitly requested.
- Check the worktree before and after work when practical. Never overwrite user changes.
- Keep active workflow files as current-state snapshots, not logs.

## 1. Request Startup

At the start of every non-trivial user request, inspect `.agent-workflow/` if it exists.

- If active workflow files contain remaining actionable work, use `request_user_input` Tool before starting the new request.
- Ask whether to:
  1. do the remaining work first,
  2. combine it with the new request,
  3. defer or archive it,
  4. discard the active workflow and start fresh.
- If no actionable work remains but active workflow files are still present, archive them before continuing.

## 2. Workflow Files

Use only the files needed for the current task.

- `.agent-workflow/request.md`: confirmed requirements, assumptions, open questions, out-of-scope items, and relevant references.
- `.agent-workflow/plan.md`: approved or proposed execution plan.
- `.agent-workflow/task.md`: current executable tasks.
- `.agent-workflow/speedwagon.md`: external findings that affect requirements, specs, tasks, or verification.
- `.agent-workflow/index.md`: compact lookup index for archived workflow summaries.
- `.agent-workflow/archive/<timestamp[yyyyMMdd-HHmmss]>-<task-slug>/`: archived workflow history.

## 3. Requirements

For complex or approval-requiring work, create or update `.agent-workflow/request.md`.

Before finalizing requirements:

- Check `.agent-workflow/index.md` first when prior workflow context may be useful, then open only the relevant archived `summary.md` or workflow files.
- Inspect repository files, documentation, or tools instead of guessing.
- Record concise references and confirmed facts only.
- Assign stable requirement IDs: `REQ-001`, `REQ-002`, etc.
- Keep assumptions and open questions separate.
- Do not finalize planning until requirements are clear enough to execute safely.

## 4. Plan

Planning must happen before implementation.

First, draft the implementation plan without writing files.

During planning, use `request_user_input` Tool whenever any ambiguity, trade-off, or implementation choice could affect scope, risk, compatibility, cost, or direction. Ask as many times as needed until all material ambiguities are resolved.

Create or update `.agent-workflow/plan.md` as a draft during planning. Keep it updated as user decisions are made, and mark it finalized only after user confirmation.

The plan must include only what is needed:

- objective,
- constraints and assumptions,
- selected approach,
- affected files or interfaces,
- execution order,
- risks and edge cases,
- validation strategy,
- items requiring approval.

Assign stable spec IDs: `SPEC-001`, `SPEC-002`, etc.
Each `SPEC-*` must trace to one or more `REQ-*`.

## 5. Tasks

After the plan is clear, create or update `.agent-workflow/task.md`.

- Split work into phases and tasks.
- Assign stable task IDs: `TASK-001`, `TASK-002`, etc.
- Each task must reference its source `SPEC-*`.
- Each task must include a `Task Level` from `1` to `5`.
- Each task must specify `Required Subagent` based on its level.
- Each task should include verification when applicable.
- Use explicit states: `Pending`, `In Progress`, `Completed`, `Blocked`, or `Skipped`.
- Keep `task.md` focused on the current execution window and next useful step.

Task level mapping:

- Level `1`: [@junior-worker](subagent://junior-worker)
- Level `2 ~ 3`: [@senior-worker](subagent://senior-worker)
- Level `4 ~ 5`: [@specialist-worker](subagent://specialist-worker)

Before implementation starts, use `request_user_input` Tool to ask whether to execute the prepared `task.md`.

## 6. Execution

After approval, execute tasks phase by phase.

- Execute approved tasks from top to bottom.
- Use the specified Subagent for every task execution.
- Do not execute implementation work directly without a Subagent.
- Mark a task `Completed` only after implementation and verification are done.
- Mark blocked work as `Blocked` with the next required action.
- Keep blocked, skipped, pending, or unverified work in `task.md`.
- If scope or implementation changes materially, update workflow files and ask the user before continuing.

## 7. External Findings

When external search or documentation review affects the task, record only decision-relevant findings in `.agent-workflow/speedwagon.md`.

Each entry should be concise:

- source or link,
- key finding,
- related `REQ-*` or `SPEC-*`,
- impact on the current decision.

Do not store raw search dumps, long candidate lists, or stale findings.

## 8. Archiving

Archive workflow files when:

- no actionable tasks remain,
- a workflow is superseded,
- the user chooses to archive or discard remaining work,
- active files are stale but no longer needed.

Archive to:

`.agent-workflow/archive/<timestamp[yyyyMMdd-HHmmss]>-<task-slug>/`

Include existing workflow files and a concise `summary.md` with:

- original request,
- final requirements summary,
- selected plan,
- completed tasks,
- verification results,
- blocked, skipped, or remaining work.

Maintain an archive summary index at:

`.agent-workflow/index.md`

Use `index.md` as the first lookup point before scanning archive folders. The index should let agents find relevant prior work by task, date, summary, keywords, and archive path without reading every archived file.

After creating or updating an archive, update `index.md` with one concise entry:

- timestamp,
- task slug,
- short summary,
- key requirement or topic keywords,
- archive path,
- remaining or deferred work, if any.

Keep the index compact. Do not duplicate the full archive summary.

After successful archiving, active workflow files should be removed or cleared unless the user explicitly asks to keep them.

## 9. Completion Report

When work finishes, report briefly:

- changed files and behavior,
- verification commands and results,
- remaining risks or blocked work,
- whether workflow files were archived.

## 10. Minimal File Formats

Use these compact formats by default. Add sections only when they are useful.

### `.agent-workflow/request.md`

```md
# Request

## Summary
Brief summary of the user request.

## Requirements
- REQ-001: Confirmed requirement.
- REQ-002: Confirmed requirement.

## Assumptions
- ASSUMPTION-001: Current working assumption.

## Open Questions
- QUESTION-001: Question requiring user input.

## Out of Scope
- Item intentionally excluded.

## References
- Source or file path: short reason it matters.
```

### `.agent-workflow/plan.md`

```md
# Plan

## Objective
What this plan will achieve.

## Specs
- SPEC-001: Implementation spec. (REQ-001)
  - Affected files/interfaces: path or component
  - Validation: command or check

## Execution Order
1. SPEC-001
2. SPEC-002

## Risks
- Risk and mitigation.

## Approval Needed
- Decision or execution approval needed from the user.
```

### `.agent-workflow/task.md`

```md
# Tasks

## Phase 1: Phase name

- TASK-001 [Pending]: Task title (SPEC-001)
  - Action: Concrete action to perform
  - Task Level: task level (1~5)
  - Required Subagent: subagent based on level
  - Verification: Command or check
  - Result: What changed

- TASK-002 [Blocked]: Task title (SPEC-002)
  - Blocker: What is blocked
  - Task Level: task level (1~5)
  - Required Subagent: subagent based on level
  - Next action: What is needed to unblock
  - Result: What changed
```

### `.agent-workflow/speedwagon.md`

```md
# External Findings

- FINDING-001: Finding title (REQ-001, SPEC-001)
  - Source: link or document path
  - Finding: Short decision-relevant fact
  - Impact: How it affects the plan or verification
```

### `.agent-workflow/index.md`

```md
# Archive Index

- `.agent-workflow/archive/<timestamp[yyyyMMdd-HHmmss]>-<task-slug>/`
  - Summary: Short summary of the archived workflow.
  - Keywords: Key requirements, domains, files, components, or decision topics.
  - Remaining: Remaining, blocked, skipped, or deferred work. Use `None` if there is no remaining work.
```

### `.agent-workflow/archive/<timestamp[yyyyMMdd-HHmmss]>-<task-slug>/summary.md`

```md
# Archive Summary

## Original Request
Brief summary.

## Final Requirements
- REQ-001: Requirement summary.

## Selected Plan
Short summary of the chosen approach.

## Completed Work
- TASK-001: Result summary.

## Verification
- Command/check: result.

## Remaining Work
- Blocked, skipped, or deferred work, if any.

## Archived Files
- request.md
- plan.md
- task.md
- speedwagon.md
```
