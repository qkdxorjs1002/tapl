# Workflow

Write all workflow documents in the user's language unless the user asks otherwise. Keep them short, practical, and current. Do not add unstated requirements or expand scope without explicit user approval.

## 0. Core Rules

- Active workflow files must live under `.agent-workflow/`, not in the project root.
- Create or update only the workflow files needed for the task.
- Workflow files may be created or updated before execution approval.
- Implementation, refactoring, test additions or changes, project documentation changes, and multi-file changes require user approval before execution.
- When asking the user a question, use the `request_user_input` tool with concise wording.
- Check the worktree before and after work when possible, and never overwrite user changes.

## 1. Workflow Files

- `.agent-workflow/speedwagon.md`: current valid findings from external searches or external documents.
- `.agent-workflow/request.md`: confirmed requirements, open questions, and explicitly excluded scope.
- `.agent-workflow/plan.md`: executable plan derived from confirmed requirements.
- `.agent-workflow/task.md`: active task window for the current execution phase.
- `.agent-workflow/task.recent.md`: recent completion and verification summary.
- `.agent-workflow/archive/<timestamp>-<task-slug>/`: archived workflow history and detailed logs.

## 2. Context Budget and Compaction

Active workflow files are current-state snapshots, not append-only logs. Do not keep conversation logs, raw tool outputs, rejected historical plans, old requirement versions, or full completed-task history in active workflow files.

Compact workflow files before continuing when any of the following applies:

- `.agent-workflow/request.md` exceeds about 100 lines or 12 KB.
- `.agent-workflow/plan.md` exceeds about 200 lines or 24 KB.
- `.agent-workflow/task.md` contains more than about 40 active tasks.
- `.agent-workflow/task.recent.md` contains more than about 30 completed entries.
- `.agent-workflow/speedwagon.md` starts to look like a search log or contains stale findings.
- A phase has been completed.
- Requirements or the plan changed materially.
- Execution approval is about to be requested.

Compaction procedure:

1. If history may still be useful, archive it under `.agent-workflow/archive/<timestamp>-<task-slug>/`.
2. Include a short `summary.md` in the archive explaining what was archived and why.
3. Rewrite active workflow files from the current confirmed state.
4. Preserve existing `REQ-*`, `SPEC-*`, and `TASK-*` IDs when they still refer to the same item.
5. Remove superseded, completed, resolved, failed-but-handled, and irrelevant content from active files.
6. Add a single archive pointer line to active files when useful.

## 3. Plan Mode

In Plan Mode, planning comes before implementation. The goal is to produce a decision-complete plan that is ready to execute.

Allowed before approval:

- Read relevant files, configs, schemas, docs, and current behavior.
- Search the repository.
- Check status.
- Run dry-run style commands that do not create changes.

Not allowed before approval:

- Modify project, source, or documentation files.
- Generate code into the repository.
- Run formatters or commands that rewrite files.
- Run migrations, refactor code, add or modify tests, or make implementation changes.

Reduce uncertainty by inspecting the actual environment first. If a decision is still needed, ask with `request_user_input` and include 2–3 practical options or a recommendation when useful.

## 4. Requirements

Use `.agent-workflow/request.md` for complex tasks or tasks that require approval.

- Start by summarizing the user's request.
- Assign stable IDs starting from `REQ-001` to confirmed requirements.
- Mark unclear items as questions instead of guessing.
- Record explicit out-of-scope items when they exist.
- Do not finalize the plan until requirements are clear enough.
- Do not accumulate change history; rewrite the file to reflect the current confirmed state.

## 5. Plan

When planning is needed, derive `.agent-workflow/plan.md` from `.agent-workflow/request.md`.

- Use Plan Mode first for tasks that require planning, so requirements, impact scope, execution order, and verification methods are clarified before execution.
- If implementation, refactoring, test additions or changes, project documentation changes, or multi-file changes are expected, finalize the execution plan in Plan Mode before requesting user approval.
- Before approval, only inspect relevant files, search the repository, check status, and run dry-run commands that do not create changes.
- Before approval, do not modify source code, tests, documentation, or configuration files.
- Assign stable IDs starting from `SPEC-001` to implementation specs.
- Each `SPEC-*` must trace back to one or more `REQ-*` IDs.
- Include the approach, affected files or interfaces, execution order, dependencies, risks, edge cases, assumptions, and verification method as needed.
- Use a structure that fits the task instead of forcing a fixed template.
- Move rejected approaches and verbose investigation notes to the archive.

## 6. Tasks

When execution tasks are needed, create `.agent-workflow/task.md`.

- `.agent-workflow/task.md` is a task window, not the full project TODO list.
- For large plans, include only the current phase and a next-phase preview.
- Generate detailed future-phase tasks from `.agent-workflow/plan.md` when that phase becomes active.
- Assign stable IDs starting from `TASK-001`.
- Each task must reference its source `SPEC-*`.
- Each task must be actionable and ordered by execution sequence.
- Tasks that require verification must include a verification method.

Example:

```markdown
### Phase 1: Parser

- [ ] TASK-001 Add cursor parser. Source: SPEC-001. Verify: parser unit tests.
- [ ] TASK-002 Add pagination test. Source: SPEC-001. Verify: failing case passes.

### Next Phase Preview

- TASK-003 Wire parser into list endpoint. Source: SPEC-002.
```

Completed and verified tasks must not remain duplicated in `.agent-workflow/task.md`. Keep only a recent completion and verification summary in `.agent-workflow/task.recent.md`, and move older completion logs to the archive.

## 7. External Findings

When external search or external documentation review is needed, record only findings that affect the current requirements, specs, tasks, or verification in `.agent-workflow/speedwagon.md`.

Keep each entry short:

- source ID or link
- key finding
- related `REQ-*` or `SPEC-*`
- impact on the current decision

Do not store raw search dumps, long candidate link lists, or stale findings in active workflow files.

## 8. Execution Approval

Before implementation, refactoring, test additions or changes, project documentation changes, or multi-file changes, ask for user approval.

Use `request_user_input` with a concise approval question.

If the user rejects, revises, or adds requirements:

1. Update `.agent-workflow/request.md`.
2. Update `.agent-workflow/plan.md`.
3. Regenerate or adjust `.agent-workflow/task.md`.
4. Compact workflow files when needed.
5. Ask for approval again.

## 9. Execution

After approval, execute the current phase in `.agent-workflow/task.md` from top to bottom.

- Before each task, read the referenced `SPEC-*` and nearby context.
- Mark a task complete only after implementation and verification are done.
- Move completed and verified work into `.agent-workflow/task.recent.md` as a summary, then remove it from the active task list.
- Keep failed, blocked, or unverified work in `.agent-workflow/task.md` as actionable follow-up tasks.
- If a task is skipped, record the reason.
- When scope or implementation details change, update workflow files to reflect the current state.

## 10. Worktree Protection

- Before editing target files, check the worktree state when possible.
- Do not overwrite user changes.
- Do not commit, push, rebase, reset, or discard changes unless explicitly requested.
- Do not include workflow files in commits unless explicitly requested.
