"""Prompt templates and guidance rendering for tapl."""

from __future__ import annotations

from dataclasses import dataclass
from string import Template
from typing import Iterable, Any

from . import config as tapl_config


PLAN_KEY_LABELS = (
    "Objective",
    "Requirements trace",
    "Selected approach",
    "Affected files/interfaces",
    "Execution order",
    "Risks",
    "Validation",
    "Approval needs",
)
TASK_STATUSES = ("Pending", "In Progress", "Completed", "Blocked", "Skipped")
EXECUTABLE_TASK_STATUSES = ("Pending", "In Progress", "Blocked")


@dataclass(frozen=True)
class FieldSpec:
    name: str
    flag: str
    help: str
    required: str = ""
    label: str = ""


RUN_FIELDS = (
    FieldSpec("summary", "--summary", "Short description of the current request.", label="Summary"),
    FieldSpec("result", "--result", "Short description of the completed result.", label="Result"),
    FieldSpec(
        "workflow_mode",
        "--workflow-mode",
        "Agent-selected run mode: planned for persisted planning/execution, lightweight for direct non-durable answers.",
        "defaults to planned",
        "Workflow mode",
    ),
)
PLAN_FIELDS = (
    FieldSpec("id", "--id", "Numeric plan/spec id, e.g. PLAN-001 or SPEC-001.", "defaults to PLAN-001", "Plan id"),
    FieldSpec("title", "--title", "Short human-readable plan title.", "recommended when creating", "Title"),
    FieldSpec("summary", "--summary", "Compact requirements trace and approach summary.", "recommended", "Summary"),
    FieldSpec("objective", "--objective", "Plan objective.", "required for detailed plans", "Objective"),
    FieldSpec(
        "requirements_trace",
        "--requirements-trace",
        "REQ-* trace or requirement mapping.",
        "required for detailed plans",
        "Requirements trace",
    ),
    FieldSpec(
        "selected_approach",
        "--selected-approach",
        "Selected implementation approach.",
        "required for detailed plans",
        "Selected approach",
    ),
    FieldSpec(
        "affected_files",
        "--affected-files",
        "Affected files, modules, or interfaces.",
        "required for detailed plans",
        "Affected files/interfaces",
    ),
    FieldSpec(
        "execution_order",
        "--execution-order",
        "Ordered execution steps.",
        "required for detailed plans",
        "Execution order",
    ),
    FieldSpec("risks", "--risks", "Risks, compatibility notes, or tradeoffs.", "required for detailed plans", "Risks"),
    FieldSpec("validation", "--validation", "Validation strategy or commands.", "required for detailed plans", "Validation"),
    FieldSpec("approval_needs", "--approval-needs", "Approval requirements before execution.", label="Approval needs"),
    FieldSpec("notes", "--notes", "Additional notes rendered after standard plan fields.", label="Notes"),
    FieldSpec(
        "custom_fields",
        "--custom-fields",
        "JSON object of history-relevant metadata; values may be any JSON type and top-level null values delete keys.",
        label="Custom fields",
    ),
    FieldSpec("status", "--status", "Plan lifecycle label, e.g. Draft or Finalized.", label="Status"),
)
TASK_FIELDS = (
    FieldSpec("id", "--id", "Numeric task id, e.g. TASK-001.", "CLI required", "Task id"),
    FieldSpec("title", "--title", "Short human-readable task title.", "required when creating", "Title"),
    FieldSpec("status", "--status", "Task lifecycle status.", "required when creating", "Status"),
    FieldSpec(
        "spec_id",
        "--spec-id",
        "Numeric source plan/spec id, e.g. PLAN-001 or SPEC-001.",
        "required for executable tasks",
        "Source plan/spec",
    ),
    FieldSpec("goal", "--goal", "Outcome this task must achieve.", "required for executable tasks", "Goal"),
    FieldSpec("action", "--action", "Concrete work to perform.", "required for executable tasks", "Action"),
    FieldSpec(
        "verification",
        "--verification",
        "Command, check, or review proving completion.",
        "required for executable and completed tasks",
        "Verification",
    ),
    FieldSpec("result", "--result", "Completion note for Completed tasks.", "required for completed tasks", "Result"),
    FieldSpec("blocker", "--blocker", "Reason a Blocked task cannot proceed.", "required for blocked tasks", "Blocker"),
    FieldSpec(
        "next_action",
        "--next-action",
        "Specific action that would unblock a Blocked task.",
        "required for blocked tasks",
        "Next action",
    ),
    FieldSpec(
        "custom_fields",
        "--custom-fields",
        "JSON object of history-relevant metadata; values may be any JSON type and top-level null values delete keys.",
        label="Custom fields",
    ),
)
FINDING_FIELDS = (
    FieldSpec("title", "--title", "Short finding title.", "CLI required", "Title"),
    FieldSpec("source", "--source", "Where the finding came from.", label="Source"),
    FieldSpec("finding", "--finding", "Finding details.", "required for decision-relevant facts", "Finding"),
    FieldSpec(
        "impact",
        "--impact",
        "Why the finding matters.",
        "required when it affects requirements, plan, tasks, or verification",
        "Impact",
    ),
    FieldSpec("related_ids", "--related-ids", "Related plan, task, or item ids.", label="Related ids"),
)
APPROVAL_FIELDS = (
    FieldSpec("kind", "--kind", "Approval kind.", label="Kind"),
    FieldSpec("decision", "--decision", "Approval decision.", "CLI required", "Decision"),
    FieldSpec("prompt", "--prompt", "Approved or rejected execution scope.", "required for meaningful approvals", "Prompt"),
    FieldSpec(
        "source",
        "--source",
        "Approval origin: explicit_user, request_user_input, or unspecified.",
        "defaults to explicit_user for new approvals",
        "Source",
    ),
)
FIELD_SPECS = {
    "run": RUN_FIELDS,
    "plan": PLAN_FIELDS,
    "task": TASK_FIELDS,
    "finding": FINDING_FIELDS,
    "approval": APPROVAL_FIELDS,
}
PLAN_BODY_FIELDS = (
    "summary",
    "objective",
    "requirements_trace",
    "selected_approach",
    "affected_files",
    "execution_order",
    "risks",
    "validation",
    "approval_needs",
    "notes",
)
TASK_BODY_FIELDS = ("goal", "action", "verification", "result", "blocker", "next_action")
AGENT_STATUS_FIELDS = {
    "plan": ("id", "stable_id", "title", "status", "summary", "custom_fields"),
    "task": (
        "id",
        "stable_id",
        "title",
        "status",
        "spec_id",
        "goal",
        "action",
        "verification",
        "result",
        "blocker",
        "next_action",
        "custom_fields",
    ),
    "finding": ("id", "stable_id", "title", "source"),
}
AGENT_ITEM_FIELDS = {
    "plan": ("plan_id", *PLAN_BODY_FIELDS, "custom_fields"),
    "task": ("spec_id", "goal", "action", "verification", "result", "blocker", "next_action", "custom_fields"),
    "finding": ("body", "impact", "related_ids"),
}

MCP_SERVER_INSTRUCTIONS_TEMPLATE = """TAPL is the workflow system for this workspace. Use the `tapl_*` MCP tools instead of constructing or executing `taplctl` shell commands. Call `tapl_get_status` and `tapl_get_next` before non-trivial work or whenever state is uncertain. These server instructions, tool descriptions, and JSON schemas are the authoritative workflow and field contract; do not call CLI `--help` to rediscover them. The `taplctl` CLI remains a manual repair fallback only when this MCP server is unavailable.

# Workflow

Write workflow records and reports in the user's language unless asked otherwise. Keep them short, practical, and current. Do not add unstated requirements or expand scope without explicit user approval.

## Role Boundaries

- Workflow state lives in the repo-local TAPL database behind these tools.
- Prefer high-level lifecycle tools and `tapl_get_next`; use the CLI only for manual repair when MCP is unavailable.
- Do not modify source, tests, docs, configs, migrations, generated files, or other durable project artifacts before execution approval.
- TAPL run, plan, task, finding, approval, and archive records may be created or updated before execution approval.
- Do not commit, push, rebase, reset, discard changes, or include workflow records in commits unless explicitly requested.
- Check the worktree before and after work when practical. Never overwrite user changes.
- Keep TAPL records as current-state snapshots, not logs.
- ${custom_fields_guidance}

## Planning

${workflow_mode_guidance}

Planning must happen before implementation. Requirements are captured inside the plan, not in a separate requirements file or request artifact.

Keep the plan current as decisions are made. Mark it finalized only after explicit user confirmation.

Fixed plan detail (`plan_detail = "very_detailed"`): ${plan_detail_guidance}

The plan must be concise but executable. Include only what is needed for the implementation to proceed safely.

Fixed planning approval (`planning_approval_level = "more"`): ${planning_approval_guidance}

## Tasks And Execution

Tasks are executable implementation or verification work derived from the stored plan, not planning or task-design work.

- Keep tasks focused on the current execution window and next useful step.
Fixed task granularity (`task_granularity = "very_granular"`): ${task_granularity_guidance}
${task_execution_order_guidance}
${subagent_delegation_guidance}
${context_execution_approval_guidance}

- Task state must reflect current reality: only active work is In Progress, completed work has implementation and verification done, and blocked work records the blocker and next action.
- Keep blocked, skipped, pending, or unverified work in TAPL records.
- If scope or implementation changes materially, update the plan or tasks and ask the user before continuing.

## Records And History

Use only the records needed for the current task. Do not create or edit legacy workflow markdown files unless the user explicitly asks for them.

${history_search_guidance}

When external search or documentation review affects the task, store only decision-relevant findings with source and impact; never store raw dumps, long candidate lists, or stale findings.

Archive the active run when no actionable tasks remain, the workflow is superseded, the user chooses to archive or discard remaining work, or the active run is stale.

## Completion Report

When work finishes, report changed files/behavior, verification commands/results, remaining risks or blocked work, and whether the TAPL run was archived.

Record the final result with `tapl_finish_run` before archiving with `tapl_finish_archive`."""

CONTEXT_INJECTION_PROMPT_TEMPLATE = """# TAPL MCP

Use the installed `tapl_*` MCP tools for workflow state. The MCP server instructions, tool descriptions, and input schemas contain the authoritative workflow policy and field contracts. Call `tapl_get_next` for the current safe action. Do not run `taplctl --help`; use the CLI only as a manual fallback when the MCP server is unavailable."""

SESSION_START_GUIDANCE_TEMPLATE = """# TAPL MCP

SessionStart is bootstrap only; wait for a concrete user request before creating workflow records. Use the installed `tapl_*` MCP tools and their server instructions; the CLI is a manual fallback only."""

STOP_GUIDANCE_TEMPLATE = """# TAPL MCP

Use `tapl_get_next` to settle remaining tasks or batches. When work is verified, record the result with `tapl_finish_run`, archive eligible work with `tapl_finish_archive`, and report changed behavior, verification, remaining risk, and archive status."""

ROOT_HELP_TEMPLATE = """Manual CLI fallback:
  Agent workflow guidance and structured field contracts are provided by the `tapl-mcp` server.
  Use this CLI for human operation, diagnostics, or repair when MCP is unavailable.
  Subcommand `--help` output documents flags only; it is not the agent workflow prompt."""

SEARCH_HELP_TEMPLATE = """Manual CLI fallback for TAPL history search.
Use the `tapl_search_history` and `tapl_get_item` MCP tools for agent workflows."""

PLAN_SET_HELP_TEMPLATE = """Manual CLI fallback for plan record repair.
Use the typed `tapl_apply_plan` MCP tool for agent workflows; command options below document CLI fields."""

TASK_SET_HELP_TEMPLATE = """Manual CLI fallback for task record repair.
Use the typed TAPL task MCP tools for agent workflows; command options below document CLI fields."""

FINDING_ADD_HELP_TEMPLATE = """Manual CLI fallback for finding record repair.
Use the typed `tapl_add_finding` MCP tool for agent workflows; command options below document CLI fields."""

APPROVAL_SET_HELP_TEMPLATE = """Manual CLI fallback for approval record repair.
Use `tapl_approve_execution` or `tapl_reject_execution` for agent workflows; command options below document CLI fields."""


def render_template(template: str, **variables: Any) -> str:
    values = {key: str(value) for key, value in variables.items()}
    return Template(template).safe_substitute(values).strip()


def render(template: str, **overrides: Any) -> str:
    return render_template(template, **template_variables(**overrides))


def template_variables(**overrides: Any) -> dict[str, str]:
    values = {
        "plan_labels": ", ".join(PLAN_KEY_LABELS),
        "task_statuses": "`, `".join(TASK_STATUSES),
        "plan_detail_guidance": plan_detail_guidance(),
        "planning_approval_guidance": planning_approval_guidance(),
        "task_granularity_guidance": task_granularity_guidance(),
        "task_required_fields": task_required_fields(),
        "task_fields_guidance": task_format_guidance(),
        "task_required_field_summary": task_required_field_summary(),
        "execution_approval_guidance": execution_approval_guidance(),
        "taplctl_execution_guidance": taplctl_execution_guidance(),
        "taplctl_command_guidance": taplctl_command_guidance(),
        "lifecycle_recipe_guidance": lifecycle_recipe_guidance(),
        "history_search_guidance": history_search_guidance(),
        "structured_record_guidance": structured_record_guidance(),
        "structured_record_guidance_plan_task": structured_record_guidance("plan/task content"),
        "structured_record_guidance_task": structured_record_guidance("task content"),
        "custom_fields_guidance": custom_fields_guidance(),
        "stable_id_guidance": stable_id_guidance(),
        "workflow_order_guidance": workflow_order_guidance(),
        "workflow_mode_guidance": workflow_mode_guidance(),
        "workflow_stage_progression_guidance": workflow_stage_progression_guidance(),
        "task_execution_order_guidance": task_execution_order_guidance(),
        "subagent_delegation_guidance": subagent_delegation_guidance(),
        "plan_key_label_guidance": plan_key_label_guidance(),
        "plan_format_guidance": plan_format_guidance(),
        "task_plan_dependency_guidance": task_plan_dependency_guidance(),
        "context_execution_approval_guidance": context_execution_approval_guidance(),
        "status_values": ", ".join(TASK_STATUSES),
        "plan_field_contract": field_contract_section("plan"),
        "task_field_contract": field_contract_section("task"),
        "finding_field_contract": field_contract_section("finding"),
        "approval_field_contract": field_contract_section("approval"),
        "markdown_finding_guidance": markdown_record_guidance("finding details and impact"),
    }
    values.update({key: str(value) for key, value in overrides.items()})
    return values


def field_specs(record: str) -> tuple[FieldSpec, ...]:
    return FIELD_SPECS[record]


def field_spec(record: str, name: str) -> FieldSpec:
    for spec in field_specs(record):
        if spec.name == name:
            return spec
    raise KeyError(f"unknown {record} field: {name}")


def field_help(record: str, name: str) -> str:
    spec = field_spec(record, name)
    return spec.help


def field_flag(record: str, name: str) -> str:
    return field_spec(record, name).flag


def field_label(record: str, name: str) -> str:
    spec = field_spec(record, name)
    return spec.label or spec.name.replace("_", " ").title()


def field_required_note(
    record: str,
    spec: FieldSpec,
) -> str:
    return spec.required


def field_contract_lines(record: str) -> list[str]:
    lines: list[str] = []
    for spec in field_specs(record):
        note = field_required_note(record, spec)
        required = f" ({note})" if note else ""
        lines.append(f"{spec.flag}{required}: {spec.help}")
    return lines


def field_contract_section(
    record: str,
    *,
    indent: str = "  ",
) -> str:
    return "\n".join(f"{indent}{line}" for line in field_contract_lines(record))


def markdown_body_fields(record: str) -> tuple[tuple[str, str], ...]:
    names = PLAN_BODY_FIELDS if record == "plan" else TASK_BODY_FIELDS
    return tuple((field_label(record, name), name) for name in names)


def agent_status_fields(record: str) -> tuple[str, ...]:
    return AGENT_STATUS_FIELDS[record]


def agent_item_fields(record: str) -> tuple[str, ...]:
    return AGENT_ITEM_FIELDS[record]


def task_required_field_names(status: str) -> tuple[str, ...]:
    if status in EXECUTABLE_TASK_STATUSES:
        fields = ["spec_id", "goal", "action", "verification"]
        if status == "Blocked":
            fields.extend(("blocker", "next_action"))
        return tuple(fields)
    if status == "Completed":
        return ("verification", "result")
    return ()


def task_required_field_flags(status: str) -> tuple[str, ...]:
    return tuple(field_flag("task", field) for field in task_required_field_names(status))


def task_required_field_summary() -> str:
    executable = ", ".join(task_required_field_flags("Pending"))
    completed = ", ".join(task_required_field_flags("Completed"))
    blocked = ", ".join(task_required_field_flags("Blocked"))
    return (
        f"new task: --id, --title, --status; executable task: {executable}; "
        f"completed task: {completed}; blocked task: {blocked}."
    )


def invalid_plan_id_remediation() -> str:
    return "Use `PLAN-001` or `SPEC-001`;"


def invalid_task_id_remediation() -> str:
    return "Use `TASK-001`;"


def invalid_task_spec_id_remediation() -> str:
    return "Set `spec_id` to a stored numeric plan/spec id such as `PLAN-001` or `SPEC-001`."


def missing_plan_remediation() -> str:
    return "Create or update a plan with `tapl_apply_plan` before durable edits."


def sparse_plan_remediation() -> str:
    return "Expand the plan enough to cover objective, approach, affected files, risks, and validation."


def plan_content_remediation() -> str:
    return "Include objective, REQ trace, selected approach, affected files/interfaces, execution order, risks, and validation."


def task_content_remediation() -> str:
    required = task_required_field_summary()
    return f"Set missing task fields according to the fixed field contract: {required}"


def multiple_tasks_in_progress_remediation() -> str:
    return (
        "For sequential work, complete, block, or skip the current task before starting another. "
        "For intentional parallel work, return the tasks to Pending, declare the parallel/subagent "
        "contract and exclusive owned_paths, then use `tapl_dispatch_tasks`."
    )


def task_started_out_of_order_remediation() -> str:
    return "Run tasks in task order; finish, resolve, skip, or replan earlier tasks before continuing the later task."


def sequential_task_contract_remediation() -> str:
    return (
        "Use execution_mode=sequential, executor_kind=main, and an empty parallel_group; "
        "otherwise declare the complete parallel subagent contract."
    )


def parallel_task_contract_remediation() -> str:
    return (
        "Set execution_mode=parallel, executor_kind=subagent, and the same non-empty "
        "parallel_group on tasks intended for one dispatch."
    )


def parallel_owned_paths_remediation() -> str:
    return (
        "Declare the files or directory scopes exclusively owned by this SubAgent with owned_paths "
        "before dispatch."
    )


def parallel_group_size_remediation() -> str:
    return "Add another independent Pending task to the group or make this task sequential."


def task_dependency_remediation() -> str:
    return "Replace the dependency with a task in the active run or remove the invalid edge."


def task_dependency_cycle_remediation() -> str:
    return "Remove or reorder dependency edges until the task graph is acyclic."


def parallel_group_dependency_remediation() -> str:
    return (
        "Tasks dispatched in the same parallel_group must be independent; move the dependent task "
        "to a later group or remove the dependency."
    )


def unmet_task_dependency_remediation() -> str:
    return "Complete every dependency before starting or dispatching this task."


def owned_path_overlap_remediation() -> str:
    return (
        "Give each concurrent SubAgent exclusive non-overlapping owned_paths, or execute the "
        "conflicting tasks in separate batches."
    )


def stale_execution_batch_remediation(batch_id: str) -> str:
    return (
        f"Inspect batch {batch_id}, settle every active execution by its execution_id, or use "
        "`tapl_recover_batch` before continuing."
    )


def execution_batch_contract_remediation(batch_id: str) -> str:
    return (
        f"Recover batch {batch_id}, repair the affected task contracts while Pending, and dispatch "
        "one same-plan, same-group task set again."
    )


def execution_task_state_remediation() -> str:
    return (
        "Do not edit a batch-managed task status directly; settle it with "
        "`tapl_complete_task`, `tapl_block_task`, or `tapl_skip_task` using the execution_id, or recover its batch."
    )


def parallel_task_missing_execution_remediation() -> str:
    return (
        "Return the task to Pending through `tapl_recover_batch`, then use `tapl_dispatch_tasks`; "
        "parallel tasks must not be started with the sequential task start command."
    )


def mixed_execution_batches_remediation() -> str:
    return "Settle or recover one active batch before dispatching or continuing another batch."


def mixed_in_progress_state_remediation() -> str:
    return (
        "Settle the batch-managed tasks by execution_id and finish/block/skip unmanaged sequential "
        "tasks; do not mix both execution modes concurrently."
    )


def execution_approval_rejected_remediation() -> str:
    return "Resolve scope with the user, then set approval before starting or continuing task execution."


def execution_approval_missing_remediation() -> str:
    return (
        "Before starting or continuing task execution, use `tapl_approve_execution` with source "
        "`explicit_user` for explicit execution requests or `request_user_input` for tool-confirmed continuation."
    )


def task_granularity_remediation() -> str:
    return "Split every independent edit, migration, and verification step."


def summarize_request_next_action() -> str:
    return "Summarize the request with `tapl_summarize_run`."


def create_plan_next_action() -> str:
    return "Create or update plan state with `tapl_apply_plan` before task design."


def lightweight_run_next_action() -> str:
    return (
        "This run is lightweight: answer directly without plan/task records, then use `tapl_finish_run` and "
        "`tapl_finish_archive`. If the work becomes complex or needs durable edits, call `tapl_apply_plan`; "
        "creating the plan promotes the run to planned mode."
    )


def archive_lightweight_run_next_action() -> str:
    return "The lightweight result is recorded; archive it with `tapl_finish_archive`."


def decide_after_plan_next_action() -> str:
    return (
        "Plan is ready and no tasks exist; agent must judge the user's requested scope directly. "
        "If the user limited work to planning/reporting, report the plan/status and stop without tasks, "
        "execution approval, or durable edits. If planning was requested without execution, use "
        "request_user_input to ask whether to continue. If execution, edits, testing, or verification were "
        "explicitly requested, create executable tasks and record execution approval with "
        "`tapl_approve_execution` using source `explicit_user` "
        "before task execution."
    )


def approval_rejected_next_action() -> str:
    return (
        "Approval rejected; resolve scope, then use `tapl_approve_execution` with source `explicit_user` "
        "before continuing, or source `request_user_input` if approval came from that tool."
    )


def approval_missing_next_action() -> str:
    return (
        "Before task execution, use `tapl_approve_execution` with source `explicit_user` when the user explicitly "
        "requested execution, or source `request_user_input` when the user approved continuing through that tool."
    )


def session_start_incomplete_next_action() -> str:
    return "After the user request, resume or update the incomplete task state before new durable edits."


def stop_incomplete_tasks_next_action() -> str:
    return (
        "Complete, block, or skip remaining tasks and settle or recover every active execution "
        "batch before Stop auto-archives."
    )


def run_stopped_during_task_next_action(label: str) -> str:
    return (
        f"Run stopped during task execution at {label}; get user approval before durable edits: "
        f"continue execution from {label} and finish existing work first, defer the existing run and archive it, "
        "or merge the work into one plan with the new request."
    )


def run_stopped_during_batch_next_action(labels: str) -> str:
    return (
        f"Run stopped while a parallel batch is active for {labels}; do not start unrelated durable "
        "work. Continue the existing SubAgents and settle every execution_id, or recover/cancel the "
        "batch before asking the user whether to defer, archive, or merge a different request."
    )


def incomplete_run_next_action() -> str:
    return (
        "Open run has incomplete tasks; get user approval before durable edits: "
        "finish existing work first, defer the existing run and archive it, or merge the work into one plan."
    )


def different_request_next_action() -> str:
    return (
        "This request appears different from the open run; get user approval before durable edits: "
        "finish existing work first, defer the existing run and archive it, or merge the work into one plan."
    )


def multiple_in_progress_next_action(labels: str) -> str:
    return (
        f"Unmanaged tasks are simultaneously In Progress; finish/block/skip all but the current "
        f"sequential task, or recover and explicitly dispatch them as one parallel batch: {labels}."
    )


def continue_task_next_action(label: str) -> str:
    return f"Continue only {label}; set Completed, Blocked, or Skipped before another task."


def dispatch_parallel_tasks_next_action(labels: str) -> str:
    return (
        f"Dispatch ready parallel tasks atomically with `tapl_dispatch_tasks` for {labels}. "
        "Then the root agent must spawn one SubAgent per manifest execution concurrently."
    )


def continue_parallel_batch_next_action(batch_id: str, assignments: str) -> str:
    return (
        f"Continue active batch {batch_id}. Root agent only: keep TAPL writes centralized, run one "
        f"SubAgent per task concurrently, and settle each result with its exact execution id "
        "using `tapl_complete_task`, `tapl_block_task`, or `tapl_skip_task` with the exact execution id. "
        f"Assignments: {assignments}. If any spawn did not start, recover or cancel the whole batch."
    )


def multiple_active_batches_next_action(batch_ids: str) -> str:
    return (
        f"Multiple execution batches are active ({batch_ids}); do not spawn more SubAgents. "
        "Settle or recover/cancel one batch at a time until the state is consistent."
    )


def repair_missing_parallel_execution_next_action(labels: str) -> str:
    return (
        f"Parallel task(s) are In Progress without a manifest execution ({labels}); do not continue "
        "or settle them as sequential tasks. Repair them to Pending, then dispatch the complete group "
        "atomically, or recover the batch if one exists."
    )


def start_task_next_action(label: str) -> str:
    return f"Start next task {label}: set In Progress immediately before execution."


def resolve_blocked_task_next_action(label: str) -> str:
    return f"Resolve, replan, or skip blocked task {label} before later tasks."


def durable_edit_requires_plan_message() -> str:
    return (
        "tapl: durable edit requires an active tapl run with planned tasks. "
        f"{taplctl_execution_guidance()} "
        f"{taplctl_command_guidance()} "
        "Create/update plan and task state, then retry."
    )


def stop_remaining_tasks_message(remaining: int) -> str:
    return f"tapl: {remaining} task(s) remain incomplete; update task state or archive before stopping."


def stop_active_executions_message(count: int) -> str:
    return (
        f"tapl: {count} execution(s) remain active; settle each execution_id or recover/cancel "
        "the batch before stopping."
    )


def archived_completed_run_message(slug: str) -> str:
    return f"tapl: archived completed run as {slug}."


def archive_summary(
    *,
    request: str,
    result: str,
    selected_plan: str,
    completed_tasks: str,
    verification: str,
    remaining: int,
) -> str:
    parts = [
        f"Original request: {request or 'archived workflow'}",
        f"Result: {result}" if result else "",
        f"Selected plan: {selected_plan}",
        f"Completed tasks: {completed_tasks}",
        f"Verification: {verification}",
        f"Remaining work: {'None' if remaining == 0 else str(remaining)}",
    ]
    return "; ".join(part for part in parts if part)


def context_workflow_guidance(
    *,
    event: str,
    state: dict[str, Any],
    prompt: str = "",
    subagents: tapl_config.SubagentsConfig | None = None,
) -> list[str]:
    if event == "SessionStart":
        return [session_start_guidance()]
    if event == "Stop":
        return [stop_guidance()]

    return [user_prompt_submit_guidance(subagents=subagents)]


def session_start_guidance() -> str:
    return render(SESSION_START_GUIDANCE_TEMPLATE)


def stop_guidance() -> str:
    return render(STOP_GUIDANCE_TEMPLATE)


def user_prompt_submit_guidance(*, subagents: tapl_config.SubagentsConfig | None = None) -> str:
    guidance = render(CONTEXT_INJECTION_PROMPT_TEMPLATE)
    delegation_request = subagent_delegation_request_guidance(subagents)
    return "\n\n".join(part for part in (guidance, delegation_request) if part)


def mcp_server_instructions(*, subagents: tapl_config.SubagentsConfig | None = None) -> str:
    """Render the complete invariant workflow policy once at MCP initialization."""

    return render(
        MCP_SERVER_INSTRUCTIONS_TEMPLATE,
        subagent_delegation_guidance=subagent_delegation_guidance(subagents),
    )


def context_execution_approval_guidance() -> str:
    return (
        "Fixed execution approval (`require_execution_approval = true`): execution approval is required before "
        "task execution or durable edits; explicit edit, test, implementation, and verification requests count as "
        "explicit user approval. Tool-confirmed continuation uses the request_user_input source."
    )


def taplctl_execution_guidance() -> str:
    return "Workflow state lives in the repo-local TAPL database behind the installed `tapl_*` MCP tools."


def taplctl_command_guidance() -> str:
    return (
        "Use the installed `tapl_*` MCP tools and their typed schemas for agent workflows. "
        "The `taplctl` CLI is a manual fallback only when MCP is unavailable."
    )


def external_findings_guidance() -> str:
    return (
        "When external search or documentation review affects the task, add only decision-relevant findings "
        "with `tapl_add_finding`, including source and impact. Do not store raw search dumps, long candidate "
        "lists, or stale findings."
    )


def plan_detail_guidance() -> str:
    return "Expand edge cases, alternatives considered, and per-spec validation."


def planning_approval_guidance() -> str:
    guidance = (
        "Before finalizing the plan with `tapl_apply_plan`, use request_user_input Tool early for unclear planning "
        "methods, material scope/risk/API/UX/data/compat, or tradeoffs. Ask short, focused "
        "questions with 2-3 mutually exclusive options, and continue with follow-ups until "
        "the plan is materially clear."
    )
    return (
        f"{guidance} Invoke it only when the Tool is available in the current mode; "
        "when multiple independent decisions are already known, batch up to three short questions in one "
        "request_user_input call. Set autoResolutionMs=240000 whenever the tool contract allows auto-resolution; "
        "omit it only when explicit user input is required before continuing; if unavailable, state assumptions "
        "or ask one concise plain-text question only when blocked."
    )


def plan_format_guidance() -> str:
    return (
        "Plan records should include objective, related REQ-* trace, selected approach, "
        "affected files/interfaces, execution order, risks, validation, and approval needs when applicable."
    )


def plan_key_label_guidance() -> str:
    labels = ", ".join(PLAN_KEY_LABELS)
    return (
        f"Keep plan section labels in English: {labels}; "
        "write each section's content in the user's language."
    )


def markdown_record_guidance(subject: str = "plan, task, and finding content") -> str:
    return (
        f"Write {subject} in Markdown form; use headings, bullets, or concise labeled "
        "sections for multi-line fields."
    )


def structured_record_guidance(subject: str = "plan and task content") -> str:
    return (
        f"Pass {subject} through the typed MCP tool fields; TAPL renders the stored Markdown body "
        "from templates during record merge."
    )


def custom_fields_guidance() -> str:
    return (
        "When writing plans/tasks, proactively populate `custom_fields` when context has metadata useful for future search, "
        "review, handoff, or decision reconstruction, even when AGENTS.md and the user do not explicitly request it. "
        "Put metadata shared by the run or multiple tasks—work type, user choices, global constraints, strategy, and "
        "decision rationale—on the plan instead of copying it to every task. Populate a task's `custom_fields` only "
        "with metadata unique to that task, such as owned files or interfaces, task-specific constraints, or validation. "
        "When a task was actually delegated to a subagent, the root records the actual model and reasoning effort used, "
        "not merely requested, during settlement: e.g. `서브 에이전트 모델`: `gpt-5.6-sol (xhigh)` or "
        "`SubAgent Model`: `gpt-5.6-sol (xhigh)`; omit this field when no subagent was used. Do not copy a fact already "
        "represented on the source plan or the same key and value across sibling tasks; reuse a label only with "
        "task-specific values or context. Before a patch, inspect the record's existing `custom_fields` with "
        "`tapl_get_status` or `tapl_get_item`. Keep one field per fact, decision, constraint, or path; update its exact "
        "stored key instead of adding a synonymous label or duplicate value. For redundant aliases, choose the clearest, "
        "most specific label as the canonical key and send its current value plus top-level nulls for the obsolete alias "
        "keys in one patch. Do not consolidate genuinely different facts; when the distinction is unclear, preserve them "
        "or ask. New fields use concise natural-language labels and human-readable string values in the user's language; "
        "avoid snake_case/code-style labels. Preserve exact source text for paths, commands, APIs, stable IDs, and code "
        "identifiers, plus JSON types for non-strings. Do not rename or migrate unrelated keys, copy standard fields, "
        "record transient progress, or invent facts. Omitted fields are preserved; provided keys merge at top level; "
        "top-level null deletes a key."
    )


def stable_id_guidance() -> str:
    return (
        "Use numeric stable ids only: `PLAN-001` or `SPEC-001` for plans/specs, `TASK-001` for tasks."
    )


def workflow_order_guidance() -> str:
    return (
        "Lifecycle order: `tapl_get_status`/`tapl_get_next` -> resolve residual run direction with user approval -> "
        "`tapl_search_history` and clarify until unblocked -> `tapl_summarize_run` with agent-selected "
        "`planned` or `lightweight` mode. Lightweight non-durable answers may finish/archive without records and "
        "are promoted by `tapl_apply_plan` if complexity grows. Planned work continues through `tapl_apply_plan` -> "
        "`tapl_create_task` -> `tapl_approve_execution` -> sequential start and settlement tools or "
        "`tapl_dispatch_tasks` plus execution-id settlement -> `tapl_finish_run` -> `tapl_finish_archive`."
    )


def workflow_mode_guidance() -> str:
    return (
        "When calling `tapl_summarize_run`, the agent must select `lightweight` only for a direct, non-durable "
        "answer whose complexity does not need a persisted plan; select `planned` for complex analysis, planning, "
        "execution, edits, tests, or verification. A lightweight run may finish/archive without plan or task "
        "records, and `tapl_apply_plan` promotes it to planned mode when complexity grows."
    )


def workflow_stage_progression_guidance() -> str:
    return (
        "unless the user explicitly limits the workflow to a specific stage, continue to the next "
        "lifecycle step automatically. If the user asks for planning only, stop after the plan and report status. "
        "If the user asks to plan but does not explicitly ask for implementation/execution, ask with request_user_input "
        "whether to continue after the plan. If the user explicitly asks for implementation, edits, verification, or "
        "testing, treat that as explicit_user execution approval and record approval source accordingly before execution."
    )


def history_search_guidance() -> str:
    return (
        "Before planning non-trivial work, search relevant prior TAPL history with "
        "`tapl_search_history`; use relevant results as context "
        "and ignore unrelated matches. If a result may affect the work and its snippet is "
        "insufficient, inspect it with `tapl_get_item`. During execution, "
        "search again when prior TAPL history may answer a question about previous decisions, "
        "implementation patterns, failures, or tradeoffs."
    )


def lifecycle_recipe_guidance() -> str:
    return (
        "Primary lifecycle tools: `tapl_summarize_run`, `tapl_apply_plan`, `tapl_create_task`, "
        "`tapl_approve_execution`, `tapl_start_task`, `tapl_dispatch_tasks`, `tapl_complete_task`, "
        "`tapl_block_task`, `tapl_skip_task`, `tapl_cancel_batch`, `tapl_recover_batch`, "
        "`tapl_finish_run`, and `tapl_finish_archive`."
    )


def task_plan_dependency_guidance() -> str:
    return (
        "Create or update executable task records only after the source plan/spec exists; "
        "tasks derive from the stored plan/spec and should not represent planning or task-design work; "
        "set `spec_id` to the stored numeric plan/spec id, e.g. `PLAN-001` or `SPEC-001`."
    )


def task_execution_order_guidance() -> str:
    return (
        "Execute planned tasks one at a time in task order when they are sequential: use `tapl_start_task` "
        "immediately before work, then complete, block, or skip it before another sequential task. "
        "Tasks explicitly declared as execution_mode=parallel, executor_kind=subagent, in the same "
        "parallel_group, with completed dependencies and exclusive owned_paths may run concurrently only "
        "after atomic `tapl_dispatch_tasks`. The root agent is the sole TAPL state writer: it must spawn "
        "one SubAgent per dispatched task concurrently, keep each worker inside its owned_paths, and settle "
        "each task with the exact manifest execution_id via the complete, block, or skip MCP tool. "
        "Record the actual delegated model and reasoning effort in task custom_fields. If any SubAgent spawn "
        "fails or the root is interrupted, recover or cancel the batch before retrying; never leave a partial "
        "batch or start another batch around it."
    )


def subagents_enabled(subagents: tapl_config.SubagentsConfig | None = None) -> bool:
    return (subagents or tapl_config.SubagentsConfig()).enabled


def subagent_delegation_request_guidance(
    subagents: tapl_config.SubagentsConfig | None = None,
) -> str:
    if not subagents_enabled(subagents):
        return ""

    return (
        "For this TAPL run, this applicable workflow instruction explicitly requests SubAgent delegation. "
        "When the authoritative TAPL MCP server instructions select delegation for an approved executable task, "
        "spawn the required SubAgent(s) without asking the user again, while following all TAPL dispatch, "
        "ownership, model-selection, and settlement rules. This does not override higher-priority instructions, "
        "user scope, safety policy, sandboxing, or approval requirements."
    )


def configured_subagent_models(
    subagents: tapl_config.SubagentsConfig | None = None,
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    configured: list[tuple[str, tuple[str, ...]]] = []
    for model in (subagents or tapl_config.SubagentsConfig()).models:
        name = model.name.strip()
        efforts = tuple(
            effort.strip()
            for effort in model.reasoning_efforts
            if effort.strip()
        )
        if name and efforts:
            configured.append((name, efforts))
    return tuple(configured)


def subagent_delegation_guidance(subagents: tapl_config.SubagentsConfig | None = None) -> str:
    if not subagents_enabled(subagents):
        return ""

    models = configured_subagent_models(subagents)
    available_models = "\n".join(
        f"- `{name}`: {', '.join(f'`{effort}`' for effort in efforts)}"
        for name, efforts in models
    )
    if not available_models:
        available_models = "- No configured model/reasoning-effort pairs are available; do not delegate work."

    return (
        "### SubAgent Delegation\n\n"
        "- For every executable task, assess complexity/difficulty and delegate with an efficient suitable model and "
        "reasoning effort; the root retains coordination, TAPL writes, and cross-task decisions.\n"
        "- Choose only from the intersection of these configured pairs and pairs actually supported by the current "
        "SubAgent runtime; use the most efficient suitable pair:\n"
        f"{available_models}\n"
        "- If that intersection is empty, report delegation unavailable and let the root execute without a SubAgent.\n"
        "- Parallel delegation follows the preceding dispatch/ownership contract: atomically dispatch, concurrently "
        "spawn one SubAgent per manifest execution, constrain owned_paths, settle by exact execution_id, and recover or "
        "cancel on spawn failure/interruption.\n"
        "- At settlement, record the actual runtime model/reasoning effort—not merely requested—in task "
        "`custom_fields`; omit it when no SubAgent was used."
    )


def task_granularity_guidance() -> str:
    return "Split every independent edit, migration, and verification step."


def task_required_fields() -> str:
    fields = ", ".join(task_required_field_names("Pending"))
    return f"Each executable task must include {fields} when applicable."


def task_format_guidance() -> str:
    fields = task_required_field_names("Pending")
    return (
        f"Executable implementation/verification tasks should include {', '.join(fields)}, "
        f"completed tasks should include {', '.join(task_required_field_names('Completed'))}; "
        f"blocked tasks should include {', '.join(task_required_field_names('Blocked'))}. "
        "When updating an existing task, pass only changed fields; omitted fields keep stored values."
    )


def execution_approval_guidance() -> str:
    base = (
        "After task design/task creation and before starting or continuing task execution, use "
        "`tapl_approve_execution` with source `explicit_user` when the user explicitly requested execution; "
        "use source `request_user_input` when approval came from that tool."
    )
    return base + " Missing execution approval is always a validation error."


def command_help_epilog() -> str:
    return render(ROOT_HELP_TEMPLATE)


def search_epilog() -> str:
    return render(SEARCH_HELP_TEMPLATE)


def plan_set_epilog() -> str:
    return render(PLAN_SET_HELP_TEMPLATE)


def task_set_epilog(
    *,
    statuses: Iterable[str] = TASK_STATUSES,
) -> str:
    status_values = ", ".join(statuses)
    return render(
        TASK_SET_HELP_TEMPLATE,
        status_values=status_values,
    )


def finding_add_epilog() -> str:
    return render(FINDING_ADD_HELP_TEMPLATE)


def approval_set_epilog() -> str:
    return render(APPROVAL_SET_HELP_TEMPLATE)
