"""Prompt templates and guidance rendering for tapl."""

from __future__ import annotations

from dataclasses import dataclass
from string import Template
from typing import Any

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
        "work_type",
        "--work-type",
        "Request kind: answer, investigation, analysis, planning, implementation, or mixed.",
        "required when summarizing",
        "Work type",
    ),
    FieldSpec(
        "workflow_mode",
        "--workflow-mode",
        "Execution rigor selected from fast, standard, or strict.",
        "required when summarizing",
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

MCP_SERVER_INSTRUCTIONS_TEMPLATE = """TAPL is this workspace's workflow system. Its `tapl_*` MCP tools call the repo-local application. Call `tapl_get_status` and `tapl_get_next` before non-trivial or uncertain work. These instructions, tool descriptions, and JSON schemas are the authoritative workflow contract.

# Workflow

Write workflow records and reports in the user's language unless asked otherwise. Keep them short and current. Do not add unstated requirements or expand scope without explicit approval.

## Role Boundaries

- Do not modify source, tests, docs, configs, migrations, generated files, or other durable project artifacts before execution approval.
- TAPL run, plan, task, finding, approval, and archive records may be created or updated before execution approval.
- Do not commit, push, rebase, reset, discard changes, or include workflow records in commits unless explicitly requested.
- Never overwrite user changes. Keep TAPL records as current-state snapshots, not logs.
- ${custom_fields_guidance}

## Tool Result Display

${mcp_tool_result_display_guidance}

## Adaptive workflow

${request_partition_guidance}

${workflow_mode_guidance}

Planning must happen before implementation; keep requirements in the plan, not a separate artifact.

${plan_detail_guidance}
${planning_approval_guidance}

## Tasks And Execution

Tasks are executable implementation or verification work from the stored plan, not task-design work.

- ${task_granularity_guidance}
${task_execution_order_guidance}
${subagent_delegation_guidance}
${context_execution_approval_guidance}

- Task state must reflect current reality: only active work is In Progress, completed work has implementation and verification done, and blocked work records the blocker and next action.
- Keep blocked, skipped, pending, or unverified work in TAPL records.
- Reclassify upward only when scope, risk, or uncertainty grows; update the plan/tasks and ask when required.

## Records And History

${history_search_guidance}

When external search or documentation review affects the task, store only decision-relevant findings with source and impact; never store raw dumps, long candidate lists, or stale findings.

Archive when no actionable work remains, the run is superseded or stale, or the user chooses archive/discard. Planning-only: ask with request_user_input to keep active, execute, or archive; never finish/archive before the choice.

## Completion Report

When work finishes, report changed files/behavior, verification commands/results, remaining risks or blocked work, and whether the TAPL run was archived.

When the user asks to run, test, inspect, or show output, lead with the observed result and include the relevant raw output or a faithful excerpt; never substitute generic success/completion wording. Keep excerpts scoped and redact secrets.

Record the final result with `tapl_finish_run` before archiving with `tapl_finish_archive`."""

CONTEXT_INJECTION_PROMPT_TEMPLATE = """# TAPL MCP

Use the installed `tapl_*` MCP tools for workflow state. The MCP server instructions, tool descriptions, and input schemas contain the authoritative workflow policy and field contracts. Call `tapl_get_next` for the current safe action."""

SESSION_START_GUIDANCE_TEMPLATE = """# TAPL MCP

SessionStart is bootstrap only; wait for a concrete user request before creating workflow records. Use the installed `tapl_*` MCP tools and their server instructions."""

STOP_GUIDANCE_TEMPLATE = """# TAPL MCP

Use `tapl_get_next` to settle remaining tasks or batches. When work is verified, record the result with `tapl_finish_run`, archive eligible work with `tapl_finish_archive`, and report changed behavior, verification, remaining risk, and archive status. A planning-only run stays active after the plan is reported; ask the user what to do next and do not finish or archive it before their choice."""

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
        "mcp_tool_result_display_guidance": mcp_tool_result_display_guidance(),
        "stable_id_guidance": stable_id_guidance(),
        "workflow_order_guidance": workflow_order_guidance(),
        "workflow_mode_guidance": workflow_mode_guidance(),
        "request_partition_guidance": request_partition_guidance(),
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
    return (
        "Before planning, identify request boundaries and each outcome's work_type from the requested result. For "
        "workspace-dependent outcomes whose scope is not already clear, use at most three targeted read-only local "
        "lookups to locate the target, inspect immediate dependencies, and identify validation or risk boundaries "
        "before selecting workflow_mode. Then use `tapl_split_run` for independent outcomes or "
        "`tapl_summarize_run` for one cohesive request."
    )


def create_plan_next_action() -> str:
    return "Create or update plan state with `tapl_apply_plan` before task design."


def lightweight_run_next_action() -> str:
    return (
        "This run is lightweight: complete the Fast non-durable work without plan/task records. For work_type=planning, "
        "report the plan, keep the run active, and use request_user_input to ask whether to keep it active, proceed to "
        "execution, or finish and archive it; do not finish or archive before the user chooses. For other work types, use "
        "`tapl_finish_run` and `tapl_finish_archive` after completion. If the work becomes complex or needs durable edits, "
        "call `tapl_apply_plan`; "
        "creating the plan promotes its record_mode to planned."
    )


def archive_lightweight_run_next_action() -> str:
    return (
        "The lightweight result is recorded. For work_type=planning, keep the run active and use request_user_input to "
        "ask whether to keep it active, proceed to execution, or finish and archive it; do not archive before the user "
        "chooses. For other work types, archive it with `tapl_finish_archive`."
    )


def decide_after_plan_next_action() -> str:
    return (
        "Plan is ready and no tasks exist; agent must judge the user's requested scope directly. "
        "If work_type=planning or the user limited work to planning, report the plan/status, keep the run active, and use "
        "request_user_input to ask whether to keep it active, proceed to execution, or finish and archive it. Do not call "
        "`tapl_finish_run` or `tapl_finish_archive` before the user chooses. For analysis or reporting scope, finish the run "
        "without executable tasks. If execution, edits, testing, or verification were "
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
        "Execution approval is required before "
        "task execution or durable edits; explicit edit, test, implementation, and verification requests count as "
        "explicit user approval. Tool-confirmed continuation uses the request_user_input source."
    )


def taplctl_execution_guidance() -> str:
    return "Workflow state lives in the repo-local TAPL database behind the installed `tapl_*` MCP tools."


def taplctl_command_guidance() -> str:
    return "Use the installed `tapl_*` MCP tools and their typed schemas for agent workflows."


def external_findings_guidance() -> str:
    return (
        "When external search or documentation review affects the task, add only decision-relevant findings "
        "with `tapl_add_finding`, including source and impact. Do not store raw search dumps, long candidate "
        "lists, or stale findings."
    )


def plan_detail_guidance() -> str:
    return (
        "Plan depth follows the mode: Fast durable work gets a compact executable plan; Standard gets a concise "
        "executable plan; Strict documents risk, interfaces, rollback, and validation boundaries. "
        "Finalize only after explicit user confirmation."
    )


def planning_approval_guidance() -> str:
    guidance = (
        "Before finalizing with `tapl_apply_plan`, use request_user_input Tool early for unclear planning methods "
        "or material scope/risk/API/UX/data/compat/tradeoffs. Ask focused questions with 2-3 mutually exclusive "
        "options and continue with follow-ups until "
        "the plan is materially clear."
    )
    return (
        f"{guidance} Use it only when available in the mode; "
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
        "Use `custom_fields` for durable searchable metadata. Executable tasks maintain "
        "canonical fields `Task Profile` (profile or none plus match reason), `Task Characteristics` (independence, "
        "context, risk, coordination cost, parallel value), and `Execution Decision` (executor, model/effort, "
        "rationale, override). Set at design and before dispatch; update after settlement if changed. Add "
        "`사용자 참고사항`/`User Notes` only for durable user facts absent from "
        "standard fields, using concise `종류`/`category`, `내용`/`content`, `영향`/`impact`. Put shared "
        "facts on plan and task-specific facts on task; preserve keys/types; omit duplicates or "
        "transient progress. Dispatch writes legacy `SubAgent Model` (manifest model/effort) before return; root "
        "verifies before spawn. Example: `gpt-5.6-sol (xhigh)`; omit when no SubAgent runs. "
        "Use top-level null only to delete a duplicate."
    )


def mcp_tool_result_display_guidance() -> str:
    return (
        "Do not report every `tapl_*` call or result. On TAPL stage changes, emit at most one notice: "
        "`<emoji> **<tapl-kind>** · <current activity>`, e.g. `🧪 **TASK** · 전체 테스트 실행 중`. Use the TAPL workflow "
        "kind: **RUN**, **PLAN**, **TASK**, **HISTORY**, **FINDING**, **APPROVAL**, or **ARCHIVE**. Normal notices: one "
        "clause, 60 characters, progressive, current activity only. "
        "After `tapl_summarize_run`, emit one localized classification notice: "
        "`🔎 **RUN** · 분류: Implementation · Standard · Planned`. This one notice may report only the returned "
        "work_type, workflow_mode, and derived record_mode; do not repeat it unless the classification changes. "
        "Omit completed results, counts, rationale, lists, "
        "sequences, next steps, receipts, tables, IDs, statuses, payloads, and summaries; never echo returned data. Icons: "
        "🔎 inspect, 📝 plan, 🛠️ execute, 🧪 verify. Combine consecutive calls. Errors, blockers, approvals, or input requests "
        "may include reason and next action. "
        "Localize text. Final reports use prose."
    )


def stable_id_guidance() -> str:
    return (
        "Use numeric stable ids only: `PLAN-001` or `SPEC-001` for plans/specs, `TASK-001` for tasks."
    )


def workflow_order_guidance() -> str:
    return (
        "Lifecycle order: `tapl_get_status`/`tapl_get_next` -> resolve residual run direction with user approval -> "
        "identify independent outcomes and their work_type -> perform the bounded local scout when workspace facts "
        "are needed -> call `tapl_split_run` when needed, otherwise `tapl_summarize_run` with the selected "
        "work_type and evidence-based `fast`, `standard`, or `strict` workflow_mode -> search relevant history before "
        "planning. A derived lightweight record may finish/archive "
        "without plan/tasks and `tapl_apply_plan` promotes record_mode to planned. Each split child searches relevant history "
        "before its own plan. Planned records continue through `tapl_apply_plan` -> "
        "`tapl_create_task` -> `tapl_approve_execution` -> sequential start and settlement tools or "
        "`tapl_dispatch_tasks` plus execution-id settlement -> `tapl_finish_run` -> `tapl_finish_archive`."
    )


def workflow_mode_guidance() -> str:
    return (
        "Classify requested outcome as Answer/Investigation/Analysis/Planning/Implementation/Mixed. For unscoped "
        "workspace-dependent work, before workflow_mode make at most three targeted read-only local lookups: target, "
        "immediate dependencies, and test/config/public-interface/risk boundaries. Skip for self-contained requests or "
        "sufficient context; during the scout do not edit/test, use external research/TAPL history, or create plan/tasks. "
        "Choose mode from surface/coupling/uncertainty/risk/validation. Mixed uses its highest child mode. First choose "
        "Strict for security/privacy/permission, schema/destructive work, public compatibility, deploy/external writes, "
        "incident/data-correctness, irreversible impact, or conflicting evidence. Choose Fast only when every dimension "
        "is known low: one objective/surface, reversible change, one validation, closed boundaries, and implementation "
        "touches at most two files. Otherwise use Standard; unknowns never qualify for Fast. Pass final work_type and "
        "workflow_mode to `tapl_summarize_run`; store at most two reasons in needed records. TAPL derives "
        "record_mode=`lightweight` only for Fast non-durable Answer, Investigation, Analysis, or Planning work; durable "
        "work and every Standard or Strict run derive record_mode=`planned`. Lightweight runs need no plan/tasks; "
        "`tapl_apply_plan` promotes only record_mode. Reclassify upward if scope, risk, or "
        "uncertainty grows."
    )


def request_partition_guidance() -> str:
    return (
        "Before summarizing or planning, identify independently deliverable outcomes in the whole input. If at least two can "
        "each be completed and reported alone, call `tapl_split_run` and give each child its own summary and classification. "
        "Do not split steps, constraints, examples, or acceptance criteria serving one outcome. Preserve input order; add "
        "`depends_on` only for stated order or when a later outcome consumes an earlier one, and reference earlier keys only. "
        "Leave independent siblings dependency-free. Plan only the active child; finishing and archiving it activates the next "
        "ready child. Never share one plan across split runs."
    )


def workflow_stage_progression_guidance() -> str:
    return (
        "unless the user explicitly limits the workflow to a specific stage, continue to the next "
        "lifecycle step automatically. If the user asks for planning only, report the plan and keep the run active. "
        "If the user asks to plan but does not explicitly ask for implementation/execution, ask with request_user_input "
        "whether to keep the run active, proceed to execution, or finish and archive it; do not finish or archive before "
        "the user chooses. If the user explicitly asks for implementation, edits, verification, or "
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
        "Primary lifecycle tools: `tapl_split_run`, `tapl_summarize_run`, `tapl_apply_plan`, `tapl_create_task`, "
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
        "Execute planned tasks one at a time in task order when sequential: `tapl_start_task` immediately before work, then "
        "complete, block, or skip it before another. Parallel tasks with `execution_mode=parallel`, `executor_kind=subagent`, "
        "same `parallel_group`, completed dependencies, and exclusive owned_paths run concurrently only after atomic "
        "`tapl_dispatch_tasks`. Root agent is sole TAPL state writer: verify each `SubAgent Model` record, then spawn one "
        "SubAgent per manifest execution concurrently within its exclusive `owned_paths`; settle each with exact manifest "
        "execution_id via `tapl_complete_task`, `tapl_block_task`, or `tapl_skip_task`. If spawn fails or root is interrupted, "
        "recover or cancel the batch before retrying; never leave a partial batch or start another batch around it."
    )


def subagents_enabled(subagents: tapl_config.SubagentsConfig | None = None) -> bool:
    return (subagents or tapl_config.SubagentsConfig()).enabled


def subagent_strategy_guidance(
    subagents: tapl_config.SubagentsConfig | None = None,
) -> str:
    strategy = (subagents or tapl_config.SubagentsConfig()).strategy
    if strategy == "conservative":
        return (
            "Conservative bias against delegation, not a ban: delegate only when parallel value clearly exceeds "
            "context, coordination, and risk costs."
        )
    if strategy == "aggressive":
        return (
            "Aggressive bias toward delegation, not a forced outcome: prefer independent low-risk work with high "
            "parallel value; keep root when shared context or coordination dominates."
        )
    return (
        "Balanced neutral bias: weigh independence, context, risk, coordination cost, and parallel value; delegate "
        "only when value wins."
    )


def subagent_delegation_request_guidance(
    subagents: tapl_config.SubagentsConfig | None = None,
) -> str:
    if not subagents_enabled(subagents):
        return ""

    return (
        "This UserPromptSubmit developer context explicitly requests and authorizes Codex SubAgent delegation for every "
        "execution-approved TAPL task batch meeting the MCP delegation criteria. This TAPL context is the explicit "
        "delegation request required by any default no-proactive-delegation policy, so no additional user, AGENTS.md, or "
        "skill request is required. Do not bypass execution approval, dependency readiness, exclusive non-overlapping "
        "`owned_paths`, atomic dispatch, model allowlists/model selection, or exact `execution_id` settlement. "
        "Higher-priority scope, safety, permission, and sandbox constraints remain."
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


def _config_value(value: Any, key: str, default: Any = "") -> Any:
    """Read config objects and dict-like test doubles without coupling prompt code to them."""

    if isinstance(value, dict):
        return value.get(key, default)
    return getattr(value, key, default)


def _render_profile_characteristics(value: Any) -> str:
    if isinstance(value, dict):
        return ", ".join(f"{key}={item}" for key, item in value.items())
    if isinstance(value, (list, tuple, set)):
        return ", ".join(str(item) for item in value)
    return str(value).strip() if value else ""


def configured_subagent_profiles(
    subagents: tapl_config.SubagentsConfig | None = None,
) -> tuple[Any, ...]:
    """Return user profiles while remaining compatible with older config objects."""

    profiles = _config_value(subagents or tapl_config.SubagentsConfig(), "profiles", ())
    if profiles is None:
        return ()
    return tuple(profiles)


def _render_profile(
    profile: Any,
    index: int,
    *,
    available_candidates: set[tuple[str, str]] | None = None,
) -> str:
    name = str(_config_value(profile, "name", "")).strip() or f"profile-{index}"
    description = str(_config_value(profile, "description", "")).strip()
    characteristics = _render_profile_characteristics(
        _config_value(profile, "characteristics", "")
    )
    bias = str(_config_value(profile, "delegation_bias", "inherit")).strip()
    parts = [f"- `{name}`"]
    if description:
        parts.append(f"— {description}")
    if characteristics:
        parts.append(f"; characteristics: {characteristics}")
    parts.append(f"; bias: `{bias or 'inherit'}`")

    candidates = _config_value(profile, "candidates", ()) or ()
    rendered_candidates: list[str] = []
    for candidate in candidates:
        model = str(_config_value(candidate, "model", "")).strip()
        effort = str(
            _config_value(
                candidate,
                "reasoning_effort",
                _config_value(candidate, "effort", ""),
            )
        ).strip()
        if (
            model
            and effort
            and (
                available_candidates is None
                or (model, effort) in available_candidates
            )
        ):
            rendered_candidates.append(f"`{model}` (`{effort}`)")
        elif model and available_candidates is None:
            rendered_candidates.append(f"`{model}`")
    if rendered_candidates:
        parts.append("; ordered candidates: " + " -> ".join(rendered_candidates))
    else:
        parts.append("; ordered candidates: none (use allowlist/root fallback)")
    return "".join(parts)


def _profile_signature(profile: Any) -> tuple[Any, ...]:
    candidates = _config_value(profile, "candidates", ()) or ()
    return (
        str(_config_value(profile, "name", "")).strip(),
        str(_config_value(profile, "description", "")).strip(),
        _render_profile_characteristics(
            _config_value(profile, "characteristics", "")
        ),
        str(_config_value(profile, "delegation_bias", "inherit")).strip(),
        tuple(
            (
                str(_config_value(candidate, "model", "")).strip(),
                str(
                    _config_value(
                        candidate,
                        "reasoning_effort",
                        _config_value(candidate, "effort", ""),
                    )
                ).strip(),
            )
            for candidate in candidates
        ),
    )


def _uses_builtin_profiles(
    profiles: tuple[Any, ...],
    models: tuple[tuple[str, tuple[str, ...]], ...],
) -> bool:
    signature = tuple(_profile_signature(profile) for profile in profiles)
    if not signature:
        return False

    model_configs = tuple(
        tapl_config.SubagentModelConfig(name=name, reasoning_efforts=efforts)
        for name, efforts in models
    )
    expected_sets = (
        tapl_config.default_subagent_profiles(),
        tapl_config.default_subagent_profiles(model_configs),
    )
    return any(
        signature == tuple(_profile_signature(profile) for profile in expected)
        for expected in expected_sets
    )


def _render_builtin_profile(
    profile: Any,
    *,
    available_candidates: set[tuple[str, str]],
) -> str:
    name = str(_config_value(profile, "name", "")).strip()
    bias = str(_config_value(profile, "delegation_bias", "inherit")).strip()
    candidates = _config_value(profile, "candidates", ()) or ()
    rendered = [
        f"{str(_config_value(candidate, 'model', '')).strip().removeprefix('gpt-5.6-')}/"
        f"{_config_value(candidate, 'reasoning_effort', _config_value(candidate, 'effort', '')).strip()}"
        for candidate in candidates
        if (
            str(_config_value(candidate, "model", "")).strip(),
            str(
                _config_value(
                    candidate,
                    "reasoning_effort",
                    _config_value(candidate, "effort", ""),
                )
            ).strip(),
        )
        in available_candidates
    ]
    candidate_text = ",".join(rendered) or "fallback"
    return f"{name}={bias}[{candidate_text}]"


def subagent_delegation_guidance(subagents: tapl_config.SubagentsConfig | None = None) -> str:
    if not subagents_enabled(subagents):
        return ""

    profiles = configured_subagent_profiles(subagents)
    models = configured_subagent_models(subagents)
    available_candidates = {
        (name, effort)
        for name, efforts in models
        for effort in efforts
    }
    available_models = "; ".join(
        f"{name.removeprefix('gpt-5.6-')}[{','.join(efforts)}]"
        for name, efforts in models
    ) or "none (root only)"
    strategy_guidance = subagent_strategy_guidance(subagents)
    if profiles:
        if _uses_builtin_profiles(profiles, models):
            profile_guidance = "; ".join(
                _render_builtin_profile(
                    profile,
                    available_candidates=available_candidates,
                )
                for profile in profiles
            )
            profile_section = (
                f"- Default profiles (also used when `profiles` is absent): {profile_guidance}.\n"
            )
        else:
            profile_guidance = "\n".join(
                _render_profile(
                    profile,
                    index,
                    available_candidates=available_candidates,
                )
                for index, profile in enumerate(profiles, start=1)
            )
            profile_section = (
                "- User profiles replace built-ins; bias inherit=global, prefer=delegate, neutral=neutral, avoid=root:\n"
                f"{profile_guidance}\n"
            )
    else:
        profile_section = "- Profiles: disabled by explicit `profiles=[]`.\n"

    return (
        "### SubAgent Delegation\n\n"
        f"- Strategy: {strategy_guidance}\n"
        "- Assess independence, context, risk, coordination cost, and parallel value; record it in canonical task "
        "fields.\n"
        "- Advisory profiles: assess all characteristics; most specific wins, order breaks ties. Record overrides; skip "
        "unavailable candidates; no match -> allowlist, then root. Presets are replaceable, not model roles.\n"
        f"{profile_section}"
        f"- Allowlist: {available_models}.\n"
        "- Atomic dispatch verifies legacy `SubAgent Model`, uses `owned_paths`, settles `execution_id`, and recovers/cancels."
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
