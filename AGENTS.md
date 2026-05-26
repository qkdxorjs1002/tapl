# Workflow
Mandatory workflow instructions for Codex in this repository. Keep workflow documents short, practical, current, and written in the user's language unless requested otherwise. Do not add unstated requirements or expand scope without explicit user approval.

## 0. `request_user_input` Contract
`request_user_input` is the only valid way to ask the user for a decision, approval, clarification, or next action.

Hard rules:
- If any trigger below applies, the next assistant action must be a `request_user_input` tool call.
- Do not ask decision, approval, clarification, or next-action questions in normal text, final answers, progress updates, TODO comments, or workflow files as a substitute for the tool call.
- Do not continue implementation, file edits, write commands, or destructive/external side effects while waiting for the user's answer.
- After the user answers, update workflow files before proceeding when the answer changes requirements, scope, plan, tasks, or approval status.
- When unsure whether a user-facing question requires the tool, use the tool.
- If `request_user_input` is unavailable, stop and state: `Blocked: request_user_input is unavailable, so I cannot ask for the required user decision.` Do not ask the question in plain text.

Required triggers:
- Execution approval: before implementation, refactoring, test additions/changes, project documentation changes, configuration changes, generated code, multi-file changes, migrations, formatters that rewrite files, or any worktree-modifying command.
- Decision required: scope, requirements, architecture, API behavior, schema, dependencies, migration strategy, data handling, security posture, UX behavior, performance, compatibility, or public behavior.
- Clarification required: the request has multiple plausible interpretations and guessing could affect implementation, files, data, or external behavior.
- Next-action choice: proceed, stop, continue to another phase, run optional verification, commit, push, deploy, open a PR, broaden scope, or choose among plan variants.
- Risky/external side effects: commit, push, rebase, reset, checkout that may overwrite work, delete files, publish packages, deploy, change databases/cloud resources, rotate secrets, or mutate external APIs.
- User-requested confirmation: the user asks to approve, confirm, choose, decide, or be asked before continuing.

No-tool cases:
- Pure progress updates that do not request a decision.
- Internal implementation choices already covered by approved requirements and plan.
- Read-only inspection, repository search, status checks, and dry-run commands allowed by Plan Mode.
- Completion summaries that do not ask for a next action.

Question format:
- Ask one blocking decision per call unless decisions are tightly coupled.
- State the decision, why it matters, 2-4 practical options when useful, and a recommended option when there is a clear safe default.
- Approval questions must include scope, affected files/areas, verification, and options: approve, revise, stop.

Before any user-facing response, check whether it asks the user to approve, choose, confirm, clarify, proceed, or decide. If yes, call `request_user_input` instead of writing the question in normal text.

## 1. Core Rules
- Active workflow files must live under `.agent-workflow/`, not the project root.
- Create or update only workflow files needed for the current task.
- Workflow files may be created or updated before execution approval.
- Implementation, refactoring, tests, project documentation, configuration, generated code, and multi-file changes require approval before execution.
- Check worktree state before and after work when possible.
- Never overwrite user changes.
- Do not commit, push, rebase, reset, discard, deploy, publish, or delete files unless explicitly approved or directly requested.
- Do not include workflow files in commits unless explicitly requested.

Workflow files:
- `.agent-workflow/request.md`: confirmed requirements, open questions, approvals, excluded scope.
- `.agent-workflow/plan.md`: executable plan derived from confirmed requirements.
- `.agent-workflow/task.md`: active task window for the current execution phase.
- `.agent-workflow/task.recent.md`: recent completion and verification summary.
- `.agent-workflow/speedwagon.md`: current external findings that affect requirements, specs, tasks, or verification.
- `.agent-workflow/archive/<timestamp>-<task-slug>/`: archived history and detailed logs.

## 2. Plan Mode
Plan Mode comes before implementation and produces a decision-complete plan ready for approval.

Allowed before approval:
- Read relevant files, configs, schemas, docs, tests, and current behavior.
- Search the repository, check status, and run dry-run commands that do not create changes.
- Create or update `.agent-workflow/*` files needed to capture requirements, plans, tasks, or findings.

Not allowed before approval:
- Modify source, tests, project documentation, configuration, generated files, or other project files outside `.agent-workflow/`.
- Generate code into the repository.
- Run formatters, migrations, refactors, tests changes, or commands that rewrite files.

Procedure:
1. Inspect the actual repository before asking avoidable questions.
2. Record confirmed requirements and open questions in `.agent-workflow/request.md`.
3. If a blocking decision remains, call `request_user_input`.
4. When requirements are clear enough, write `.agent-workflow/plan.md`.
5. Write `.agent-workflow/task.md` for the first execution phase.
6. Call `request_user_input` for execution approval before modifying project files.

## 3. Requirements, Plan, and Findings
Requirements:
- Use `.agent-workflow/request.md` for complex tasks or tasks requiring approval.
- Summarize the request, assign stable `REQ-*` IDs, record exclusions and approvals, and mark unclear items as open questions instead of guessing.
- For every blocking open question, call `request_user_input`; do not leave it only in the file.
- Rewrite the file to the current confirmed state; do not keep change history.

Plan:
- Derive `.agent-workflow/plan.md` from `.agent-workflow/request.md`.
- Assign stable `SPEC-*` IDs; each spec must trace to one or more `REQ-*` IDs.
- Include approach, affected files/interfaces, order, dependencies, risks, edge cases, assumptions, and verification as needed.
- If alternatives need a user decision, call `request_user_input` before finalizing or executing.
- Move rejected approaches and verbose investigation notes to the archive.

External findings:
- Store only findings that affect current requirements, specs, tasks, or verification in `.agent-workflow/speedwagon.md`.
- Keep each entry to source/link, key finding, related `REQ-*`/`SPEC-*`, and current impact.
- Do not store raw search dumps, long link lists, or stale findings.

## 4. Tasks and Execution
Tasks:
- Use `.agent-workflow/task.md` as the active task window, not a full project TODO list.
- For large plans, include only the current phase and a next-phase preview.
- Assign stable `TASK-*` IDs; each task must reference its source `SPEC-*` and include verification when needed.
- If the next phase requires approval or a user choice, call `request_user_input` before starting it.

Execution:
- After approval, execute the current phase from top to bottom.
- Before each task, read the referenced spec and nearby context.
- Mark a task complete only after implementation and verification are done.
- Move completed verified work to `.agent-workflow/task.recent.md`, then remove it from `.agent-workflow/task.md`.
- Keep failed, blocked, skipped, or unverified work in `.agent-workflow/task.md` with an actionable reason.
- If scope or implementation details change, update workflow files; if approval scope changes, stop and call `request_user_input`.

## 5. Compaction
Active workflow files are current-state snapshots, not append-only logs. Do not keep conversation logs, raw tool outputs, rejected historical plans, old requirement versions, or full completion history in active files.

Compact before continuing when:
- `request.md` exceeds about 100 lines or 12 KB.
- `plan.md` exceeds about 200 lines or 24 KB.
- `task.md` has more than about 40 active tasks.
- `task.recent.md` has more than about 30 completed entries.
- `speedwagon.md` looks like a search log or contains stale findings.
- A phase completed, requirements changed materially, or execution approval is about to be requested.

Compaction procedure:
1. Archive useful history under `.agent-workflow/archive/<timestamp>-<task-slug>/` with a short `summary.md`.
2. Rewrite active workflow files from the current confirmed state.
3. Preserve `REQ-*`, `SPEC-*`, and `TASK-*` IDs when they still refer to the same item.
4. Remove superseded, completed, resolved, failed-but-handled, and irrelevant content.
5. Add one archive pointer line to active files when useful.

## 6. Common Failure Patterns
- Writing `Should I proceed?` in normal text instead of calling `request_user_input`.
- Listing options in a final answer and waiting for the user to reply instead of calling `request_user_input`.
- Continuing to edit files after identifying an approval requirement.
- Treating an open question in `.agent-workflow/request.md` as sufficient without asking through the tool.
- Asking multiple unrelated decisions or assuming approval from silence, prior approvals, or a plan summary.
