"""Prompt templates and guidance rendering for tapl."""

from __future__ import annotations

from dataclasses import dataclass
from string import Template
from typing import Iterable, Any

from . import config as tapl_config


LEVEL_SUBAGENTS = ("@junior-worker", "@senior-worker", "@specialist-worker")
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
        "required_subagent",
        "--required-subagent",
        "One of the configured @*-worker values.",
        "required for executable tasks when routing is enabled",
        "Required subagent",
    ),
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
    "plan": ("id", "stable_id", "title", "status", "summary"),
    "task": (
        "id",
        "stable_id",
        "title",
        "status",
        "spec_id",
        "goal",
        "action",
        "required_subagent",
        "verification",
        "result",
        "blocker",
        "next_action",
    ),
    "finding": ("id", "stable_id", "title", "source"),
}
AGENT_ITEM_FIELDS = {
    "plan": ("plan_id", *PLAN_BODY_FIELDS),
    "task": ("spec_id", "goal", "action", "required_subagent", "verification", "result", "blocker", "next_action"),
    "finding": ("body", "impact", "related_ids"),
}

WORKFLOW_INTRO = """# Workflow

Write workflow records and reports in the user's language unless asked otherwise. Keep them short, practical, and current. Do not add unstated requirements or expand scope without explicit user approval."""

CORE_RULES = """## 0. Core Rules

- Workflow state lives in the repo-local TAPL database through `taplctl`.
- Use `taplctl ... --agent` for agent-readable output. Check `taplctl <command> <subcommand> --help` when syntax is uncertain.
- Do not modify source, tests, docs, configs, migrations, generated files, or other durable project artifacts before execution approval.
- TAPL run, plan, task, finding, approval, and archive records may be created or updated before execution approval.
- Do not commit, push, rebase, reset, discard changes, or include workflow records in commits unless explicitly requested.
- Check the worktree before and after work when practical. Never overwrite user changes.
- Keep TAPL records as current-state snapshots, not logs.
- The main agent writes TAPL records and final status. Subagents may draft or execute only and must not modify TAPL records.
- Subagent timeouts are system-enforced. Check status every 5 minutes and wait calmly until completion, failure, or timeout."""

REQUEST_STARTUP = """## 1. Request Startup

At the start of every non-trivial user request:

1. Run `taplctl status --agent`.
2. If the active run contains remaining actionable work, use `request_user_input` before starting the new request.
3. Ask whether to do the remaining work first, combine it with the new request, defer/archive it, or discard the active workflow and start fresh.
4. If no actionable work remains but an active run is stale, archive it with `taplctl archive create --slug '<timestamp-task-slug>' --summary '<summary>' --agent`.
5. Set the current request summary with `taplctl run set --summary '<request summary>' --agent`.
6. Before planning non-trivial work, run `taplctl search '<compact prompt query>' --agent`; use only relevant results, and call `taplctl item show --id <id> --agent` when a snippet is insufficient."""

RECORDS = """## 2. TAPL Records

Use only the records needed for the current task.

- Run: request summary and final result.
- Plan: objective, requirements trace, assumptions, open questions, out-of-scope items, references, selected approach, affected files or interfaces, execution order, risks, validation, and approval needs.
- Task: executable implementation or verification work derived from the stored plan.
- Finding: external documentation or search findings that affect requirements, plan, tasks, or verification.
- Approval: explicit user decisions for residual work, planning choices, or execution scope.
- Archive: completed, superseded, discarded, or stale workflow history.

Do not create or edit legacy workflow markdown files unless the user explicitly asks for them."""

PLAN = """## 3. Plan

Planning must happen before implementation. Requirements are captured inside the plan, not in a separate requirements file or request artifact.

Create or update the plan with `taplctl plan set`. Keep it current as decisions are made. Mark it finalized only after explicit user confirmation.

Before finalizing the plan, use `request_user_input` proactively for material ambiguity, trade-offs, or choices that affect scope, risk, compatibility, cost, architecture, UX, data model, public interfaces, or implementation direction.

Plan detail for the current config: ${plan_detail_guidance}

The plan must be concise but executable. Include only what is needed:

- Objective
- Requirements trace: stable `REQ-001`, `REQ-002`, etc., plus assumptions, open questions, out-of-scope items, and references when useful
- Selected approach
- Affected files or interfaces
- Execution order
- Risks and edge cases
- Alternatives considered when decision-relevant
- Validation strategy
- Approval needs

Keep plan section labels in English: ${plan_labels}; write each section's content in the user's language.
Use numeric stable IDs only: `PLAN-001`, `SPEC-001`, `TASK-001`. Do not use word suffixes.

Each `SPEC-*` must include a concise goal, trace to one or more `REQ-*`, enough implementation detail to execute safely, and relevant risks, validation, or approval needs.

Planning approval guidance: ${planning_approval_guidance}"""

TASKS = """## 4. Tasks

After the source plan exists, create or update tasks with `taplctl task set`.

- Split work into phases and executable tasks.
- ${task_required_fields}
- Use explicit states: `${task_statuses}`.
- Keep tasks focused on the current execution window and next useful step.
- Do not create tasks for planning or task design; tasks are executable work derived from the stored plan.
- Before implementation starts, record approval with `taplctl approval set --decision approved --prompt '<approved scope>' --source explicit_user --agent` when the user explicitly requested execution, or `--source request_user_input` when the user approved continuing through request_user_input.

Task granularity for the current config: ${task_granularity_guidance}
Task fields: ${task_fields_guidance}
${subagent_routing_guidance}
${subagent_execution_guidance}
Execution approval guidance: ${execution_approval_guidance}"""

EXECUTION = """## 5. Execution

After approval, execute tasks one at a time in order.

- Mark a task `In Progress` immediately before work.
- Mark it `Completed` only after implementation and verification are done.
- Mark blocked work as `Blocked` with the blocker and next action.
- Keep blocked, skipped, pending, or unverified work in TAPL task records.
- If scope or implementation changes materially, update the plan or tasks and ask the user before continuing."""

EXTERNAL_FINDINGS = """## 6. External Findings

When external search or documentation review affects the task, add only decision-relevant findings:

`taplctl finding add --title '<title>' --source '<source>' --finding '<finding>' --impact '<impact>' --related-ids '<ids>' --agent`

Do not store raw search dumps, long candidate lists, or stale findings."""

ARCHIVING = """## 7. Archiving

Archive the active run when no actionable tasks remain, the workflow is superseded, the user chooses to archive or discard remaining work, or the active run is stale.

Use:

`taplctl archive create --slug '<timestamp-task-slug>' --summary '<summary>' --agent`

Use `taplctl search`, `taplctl item show`, `taplctl archive list`, and `taplctl archive show` as lookup tools instead of maintaining filesystem indexes."""

COMPLETION_REPORT = """## 8. Completion Report

When work finishes, report briefly:

- changed files and behavior,
- verification commands and results,
- remaining risks or blocked work,
- whether the TAPL run was archived.

Record the final result with `taplctl run set --result '<result summary>' --agent` before archiving."""

COMMAND_SHAPES = """## 9. Command Shapes

```sh
taplctl run set --summary '<request summary>' --agent
taplctl plan set --id PLAN-001 --title '<title>' --summary '<summary>' --objective '<objective>' --requirements-trace '<REQ trace>' --selected-approach '<approach>' --affected-files '<files/interfaces>' --execution-order '<steps>' --risks '<risks>' --validation '<checks>' --approval-needs '<approval needs>' --notes '<assumptions/questions/out-of-scope/references>' --status Draft --agent
taplctl task set --id TASK-001 --title '<task>' --status Pending --spec-id PLAN-001 --goal '<goal>' --action '<action>'${command_required_subagent} --verification '<check>' --agent
taplctl approval set --decision approved --prompt '<approved scope>' --source explicit_user --agent
taplctl task set --id TASK-001 --status Completed --verification '<check result>' --result '<result>' --agent
taplctl archive create --slug '<timestamp-task-slug>' --summary '<summary>' --agent
```"""

CONTEXT_FLOW = (
    "Flow: status -> resolve residual run with user approval -> analyze/search/clarify loop -> "
    "plan set -> plan-based task design -> task set -> execution approval -> execute/update tasks "
    "with subagents per config -> result/status briefing -> auto-archive when eligible."
)


def render_template(template: str, **variables: Any) -> str:
    values = {key: str(value) for key, value in variables.items()}
    return Template(template).safe_substitute(values).strip()


def render(template: str, settings: tapl_config.PlanTaskExecuteConfig | None = None, **overrides: Any) -> str:
    return render_template(template, **template_variables(settings, **overrides))


def template_variables(
    settings: tapl_config.PlanTaskExecuteConfig | None = None,
    **overrides: Any,
) -> dict[str, str]:
    config = settings or tapl_config.PlanTaskExecuteConfig()
    values = {
        "allowed_subagents": ", ".join(LEVEL_SUBAGENTS),
        "plan_labels": ", ".join(PLAN_KEY_LABELS),
        "task_statuses": "`, `".join(TASK_STATUSES),
        "plan_detail_guidance": plan_detail_guidance(config.plan_detail),
        "planning_approval_guidance": planning_approval_guidance(config.planning_approval_level),
        "task_granularity_guidance": task_granularity_guidance(config.task_granularity),
        "task_required_fields": task_required_fields(config),
        "task_fields_guidance": task_format_guidance(config),
        "task_required_field_summary": task_required_field_summary(config),
        "subagent_routing_guidance": subagent_routing_guidance(config),
        "subagent_execution_guidance": subagent_execution_guidance(config),
        "execution_approval_guidance": execution_approval_guidance(config),
        "command_required_subagent": (
            " --required-subagent '@junior-worker'" if config.use_level_subagent else ""
        ),
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
    settings: tapl_config.PlanTaskExecuteConfig | None = None,
) -> str:
    if record == "task" and spec.name == "required_subagent" and settings is not None:
        if not settings.use_level_subagent:
            return "optional; routing disabled"
        if settings.level_subagent_aggressiveness == "minimal":
            return "optional for explicit subagent routing"
    return spec.required


def field_contract_lines(
    record: str,
    settings: tapl_config.PlanTaskExecuteConfig | None = None,
) -> list[str]:
    lines: list[str] = []
    for spec in field_specs(record):
        note = field_required_note(record, spec, settings)
        required = f" ({note})" if note else ""
        lines.append(f"{spec.flag}{required}: {spec.help}")
    return lines


def field_contract_section(
    record: str,
    *,
    indent: str = "  ",
    settings: tapl_config.PlanTaskExecuteConfig | None = None,
) -> str:
    return "\n".join(f"{indent}{line}" for line in field_contract_lines(record, settings))


def field_contract_compact(
    record: str,
    names: Iterable[str] | None = None,
    settings: tapl_config.PlanTaskExecuteConfig | None = None,
) -> str:
    selected = field_specs(record)
    if names is not None:
        selected = tuple(field_spec(record, name) for name in names)
    return "; ".join(
        f"{spec.flag}{f' ({note})' if (note := field_required_note(record, spec, settings)) else ''}"
        for spec in selected
    )


def markdown_body_fields(record: str) -> tuple[tuple[str, str], ...]:
    names = PLAN_BODY_FIELDS if record == "plan" else TASK_BODY_FIELDS
    return tuple((field_label(record, name), name) for name in names)


def agent_status_fields(record: str) -> tuple[str, ...]:
    return AGENT_STATUS_FIELDS[record]


def agent_item_fields(record: str) -> tuple[str, ...]:
    return AGENT_ITEM_FIELDS[record]


def task_required_field_names(
    settings: tapl_config.PlanTaskExecuteConfig,
    status: str,
) -> tuple[str, ...]:
    if status in EXECUTABLE_TASK_STATUSES:
        fields = ["spec_id", "goal", "action", "verification"]
        if settings.use_level_subagent and settings.level_subagent_aggressiveness != "minimal":
            fields.append("required_subagent")
        if status == "Blocked":
            fields.extend(("blocker", "next_action"))
        return tuple(fields)
    if status == "Completed":
        return ("verification", "result")
    return ()


def task_required_field_flags(
    settings: tapl_config.PlanTaskExecuteConfig,
    status: str,
) -> tuple[str, ...]:
    return tuple(field_flag("task", field) for field in task_required_field_names(settings, status))


def task_required_field_summary(settings: tapl_config.PlanTaskExecuteConfig) -> str:
    executable = ", ".join(task_required_field_flags(settings, "Pending"))
    completed = ", ".join(task_required_field_flags(settings, "Completed"))
    blocked = ", ".join(task_required_field_flags(settings, "Blocked"))
    return (
        f"new task: --id, --title, --status; executable task: {executable}; "
        f"completed task: {completed}; blocked task: {blocked}."
    )


def allowed_subagents_text() -> str:
    return ", ".join(LEVEL_SUBAGENTS)


def invalid_plan_id_remediation() -> str:
    return "Use `PLAN-001` or `SPEC-001`; do not use word suffixes such as `PLAN-MEANINGS`."


def invalid_task_id_remediation() -> str:
    return "Use `TASK-001`; do not use word suffixes such as `TASK-MEANINGS`."


def invalid_task_spec_id_remediation() -> str:
    return "Set --spec-id to a stored numeric plan/spec id such as `PLAN-001` or `SPEC-001`."


def required_subagent_remediation(settings: tapl_config.PlanTaskExecuteConfig | None = None) -> str:
    if settings is not None and settings.level_subagent_aggressiveness == "minimal":
        return "Use --required-subagent only for intentionally delegated tasks."
    return f"Set --required-subagent to one of: {allowed_subagents_text()}."


def new_task_required_subagent_remediation(settings: tapl_config.PlanTaskExecuteConfig) -> str:
    return (
        "Pass --required-subagent in the same `taplctl task set` command "
        f"using one of: {allowed_subagents_text()}. "
        "Use minimal routing config only for intentionally direct tasks."
    )


def missing_plan_remediation() -> str:
    return "Create or update a plan with `taplctl plan set` before durable edits."


def sparse_plan_remediation() -> str:
    return "Expand the plan enough to cover objective, approach, affected files, risks, and validation."


def plan_content_remediation() -> str:
    return "Include objective, REQ trace, selected approach, affected files/interfaces, execution order, risks, and validation."


def task_content_remediation(settings: tapl_config.PlanTaskExecuteConfig) -> str:
    required = task_required_field_summary(settings)
    return f"Set missing task fields according to the configured field contract: {required}"


def multiple_tasks_in_progress_remediation() -> str:
    return "Execute planned tasks one at a time; complete, block, or skip the current task before starting another."


def task_started_out_of_order_remediation() -> str:
    return "Run tasks in task order; finish, resolve, skip, or replan earlier tasks before continuing the later task."


def execution_approval_rejected_remediation() -> str:
    return "Resolve scope with the user, then set approval before starting or continuing task execution."


def execution_approval_missing_remediation() -> str:
    return (
        "Before starting or continuing task execution, set execution approval with "
        "`taplctl approval set --decision approved --prompt '<approved scope>' --source explicit_user --agent` "
        "for explicit execution requests, or `--source request_user_input` for tool-confirmed continuation."
    )


def task_granularity_remediation(value: str) -> str:
    if value == "less_granular":
        return "Split the work into major phases or owner boundaries."
    if value == "very_granular":
        return "Split the work so independent edits, migrations, docs, and verification each have tasks."
    return "Split the work into meaningful implementation and verification tasks."


def summarize_request_next_action() -> str:
    return "Summarize request: `taplctl run set --summary '<request summary>' --agent`."


def create_plan_next_action() -> str:
    return "Create or update plan state with `taplctl plan set` before task design."


def create_tasks_next_action() -> str:
    return "Using the stored plan, create executable tasks with `taplctl task set` before durable edits."


def approval_rejected_next_action() -> str:
    return (
        "Approval rejected; resolve scope, then set `taplctl approval set --decision approved "
        "--prompt '<approved scope>' --source explicit_user --agent` before continuing, or use "
        "`--source request_user_input` if approval came from request_user_input."
    )


def approval_missing_next_action() -> str:
    return (
        "Before task execution, set execution approval: `taplctl approval set --decision approved "
        "--prompt '<approved scope>' --source explicit_user --agent` when the user explicitly requested execution, "
        "or use `--source request_user_input` when the user approved continuing through request_user_input."
    )


def plan_only_next_action() -> str:
    return (
        "Plan-only request detected; stop after reporting the plan/status. Do not create tasks, "
        "record execution approval, or make durable edits unless the user asks to continue."
    )


def ask_after_plan_next_action() -> str:
    return (
        "Plan is ready but execution was not explicitly requested; use request_user_input to ask whether to continue. "
        "If the user approves, create tasks and record execution approval with "
        "`taplctl approval set --decision approved --prompt '<approved scope>' --source request_user_input --agent`."
    )


def session_start_incomplete_next_action() -> str:
    return "After the user request, resume or update the incomplete task state before new durable edits."


def stop_incomplete_tasks_next_action() -> str:
    return "Complete, block, or skip remaining tasks before Stop auto-archives."


def run_stopped_during_task_next_action(label: str) -> str:
    return (
        f"Run stopped during task execution at {label}; get user approval before durable edits: "
        f"continue execution from {label} and finish existing work first, defer the existing run and archive it, "
        "or merge the work into one plan with the new request."
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
    return f"Only one task may be In Progress; finish/block/skip all but earliest: {labels}."


def continue_task_next_action(label: str, assignment: str = "") -> str:
    route = f" {assignment};" if assignment else ""
    return f"Continue only {label};{route} set Completed, Blocked, or Skipped before another task."


def start_task_next_action(label: str, assignment: str = "") -> str:
    route = f"; {assignment}" if assignment else ""
    return f"Start next task {label}: set In Progress immediately before execution{route}."


def resolve_blocked_task_next_action(label: str) -> str:
    return f"Resolve, replan, or skip blocked task {label} before later tasks."


def subagent_assignment_next_action(required_subagent: str) -> str:
    return (
        f"if subagent delegation is available and allowed, spawn {required_subagent} for only this task; "
        "otherwise do not claim delegation occurred"
    )


def durable_edit_requires_plan_message() -> str:
    return (
        "tapl: durable edit requires an active tapl run with planned tasks. "
        f"{taplctl_execution_guidance()} "
        f"{taplctl_command_guidance()} "
        "Create/update plan and task state, then retry."
    )


def stop_remaining_tasks_message(remaining: int) -> str:
    return f"tapl: {remaining} task(s) remain incomplete; update task state or archive before stopping."


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


def full_workflow_prompt(settings: tapl_config.PlanTaskExecuteConfig | None = None) -> str:
    sections = (
        WORKFLOW_INTRO,
        CORE_RULES,
        REQUEST_STARTUP,
        RECORDS,
        PLAN,
        TASKS,
        EXECUTION,
        EXTERNAL_FINDINGS,
        ARCHIVING,
        COMPLETION_REPORT,
        COMMAND_SHAPES,
    )
    return "\n\n".join(render(section, settings) for section in sections)


def context_workflow_guidance(
    settings: tapl_config.PlanTaskExecuteConfig,
    *,
    event: str,
    state: dict[str, Any],
    prompt: str = "",
) -> list[str]:
    if event == "SessionStart":
        return [session_start_guidance()]
    if event == "Stop":
        return [stop_guidance()]

    if event == "UserPromptSubmit":
        return [user_prompt_submit_guidance(settings)]

    guidance = [core_context_guidance()]
    guidance.extend(plan_task_context_guidance(settings))
    return guidance


def session_start_guidance() -> str:
    return "\n\n".join(
        (
            WORKFLOW_INTRO,
            "SessionStart is bootstrap only; wait for a concrete user request before creating plan/task records.",
            taplctl_execution_guidance(),
            taplctl_command_guidance(),
        )
    )


def stop_guidance() -> str:
    return "\n\n".join((taplctl_command_guidance(), COMPLETION_REPORT, ARCHIVING))


def user_prompt_submit_guidance(settings: tapl_config.PlanTaskExecuteConfig) -> str:
    sections = [
        WORKFLOW_INTRO,
        startup_context_guidance(),
        core_rules_context_guidance(),
        records_context_guidance(),
        plan_context_guidance(settings),
        tasks_context_guidance(settings),
        approval_execution_context_guidance(settings),
        findings_context_guidance(),
    ]
    return "\n\n".join(section for section in sections if section)


def startup_context_guidance() -> str:
    return "\n".join(
        (
            "## Startup",
            "At the start of every non-trivial user request:",
            "1. Run `taplctl status --agent`.",
            "2. If the active run contains remaining actionable work, use `request_user_input`: finish first, "
            "combine, defer/archive, or discard and start fresh.",
            "3. If no actionable work remains but the run is stale, archive it with "
            "`taplctl archive create --slug '<timestamp-task-slug>' --summary '<summary>' --agent`.",
            "4. Set the request summary: `taplctl run set --summary '<request summary>' --agent`.",
            "5. Before planning non-trivial work, run `taplctl search '<compact prompt query>' --agent`; "
            "use relevant results only, and `taplctl item show --id <id> --agent` when a snippet is insufficient.",
        )
    )


def core_rules_context_guidance() -> str:
    return "\n".join(
        (
            "## Core Rules",
            "- "
            + taplctl_execution_guidance()
            + " "
            + taplctl_command_guidance(),
            "- Do not modify source, tests, docs, configs, migrations, generated files, or other durable project "
            "artifacts before execution approval; TAPL run/plan/task/finding/approval/archive records may be "
            "written before approval.",
            "- Main agent writes TAPL records and final status; subagents may draft/execute only and must not modify records.",
        )
    )


def records_context_guidance() -> str:
    return "\n".join(
        (
            "## Records",
            "- Records: "
            + structured_record_guidance("plan/task content")
            + " "
            + stable_id_guidance(),
            "- Order: status -> residual-run user approval -> analyze/search/clarify -> `taplctl plan set` -> "
            "plan-based task design -> `taplctl task set` -> execution approval -> execute/update tasks -> report/archive.",
            "- Stage: continue automatically unless the user limits scope; plan-only stops after plan; "
            "plan without explicit execution asks via `request_user_input`; explicit edit/test/implement means "
            "`explicit_user` execution approval source.",
        )
    )


def plan_context_guidance(settings: tapl_config.PlanTaskExecuteConfig) -> str:
    return "\n".join(
        (
            "## Plan",
            "- Plan: include "
            + plan_detail_context(settings.plan_detail)
            + "; "
            + plan_key_label_guidance(),
            "- " + planning_approval_context_compact(settings.planning_approval_level),
            "- Plan fields: --id (defaults to PLAN-001); --title (recommended when creating); "
            "--summary (recommended); detailed plans require --objective, --requirements-trace, "
            "--selected-approach, --affected-files, --execution-order, --risks, --validation.",
        )
    )


def tasks_context_guidance(settings: tapl_config.PlanTaskExecuteConfig) -> str:
    return "\n".join(
        (
            "## Tasks",
            "- Tasks: after source plan exists, set --spec-id PLAN-001/SPEC-001; tasks are executable "
            "implementation/verification work derived from the stored plan, not planning or task-design work.",
            "- "
            + task_granularity_guidance(settings.task_granularity)
            + " "
            + task_execution_order_guidance(),
            "- Task fields: " + task_required_field_summary_compact(settings) + " Updates are partial.",
        )
    )


def approval_execution_context_guidance(settings: tapl_config.PlanTaskExecuteConfig) -> str:
    lines = [
        "## Approval & Execution",
        "- Approval: " + execution_approval_context_compact(settings),
    ]
    subagent = subagent_context_compact(settings)
    if subagent:
        lines.append("- Subagents: " + subagent)
    return "\n".join(lines)


def findings_context_guidance() -> str:
    return "\n".join(
        (
            "## Findings",
            "When external search/docs affect the task, store only decision-relevant findings with "
            "`taplctl finding add --title '<title>' --source '<source>' --finding '<finding>' "
            "--impact '<impact>' --related-ids '<ids>' --agent`; no raw dumps, long lists, or stale findings.",
        )
    )


def planning_approval_context_compact(value: str) -> str:
    if value == "less":
        return (
            "Before `taplctl plan set`, use `request_user_input` only for blocking or high-risk material "
            "scope/risk/API/UX/data/compat choices; otherwise state assumptions; if unavailable, ask one "
            "concise blocking question at most."
        )
    if value == "auto":
        return (
            "Before `taplctl plan set`, use `request_user_input` for ambiguous material "
            "scope/risk/API/UX/data/compat decisions; prefer one short 2-3 option question. "
            "If unavailable, state assumptions or ask one concise blocking question."
        )
    return (
        "Before `taplctl plan set`, use `request_user_input` early for unclear methods, material "
        "scope/risk/API/UX/data/compat, or tradeoffs; ask short 2-3 option questions until clear. "
        "If unavailable, state assumptions or ask one concise blocking question."
    )


def task_required_field_summary_compact(settings: tapl_config.PlanTaskExecuteConfig) -> str:
    executable = "/".join(task_required_field_flags(settings, "Pending"))
    completed = "/".join(task_required_field_flags(settings, "Completed"))
    blocked = "/".join(task_required_field_flags(settings, "Blocked"))
    return (
        f"new=--id/--title/--status; executable={executable}; "
        f"completed={completed}; blocked={blocked}."
    )


def execution_approval_context_compact(settings: tapl_config.PlanTaskExecuteConfig) -> str:
    if settings.require_execution_approval:
        return (
            "planning clarifications follow planning_approval_level; after task set and before durable edits, "
            "set `taplctl approval set --decision approved --prompt '<approved scope>' --source explicit_user --agent` "
            "for explicit execution, or `--source request_user_input` for tool-confirmed continuation."
        )
    return (
        "planning clarifications follow planning_approval_level; execution approval is optional for material "
        "risk/scope, and missing approval is a warning."
    )


def subagent_context_compact(settings: tapl_config.PlanTaskExecuteConfig) -> str:
    allowed = ", ".join(LEVEL_SUBAGENTS)
    if not settings.use_level_subagent:
        return ""
    if settings.level_subagent_aggressiveness == "minimal":
        required = "set required_subagent only for clear risk/routing"
    elif settings.level_subagent_aggressiveness == "force":
        required = "every executable task needs required_subagent"
    else:
        required = "choose required_subagent by task risk/config in the same command that creates each executable task"
    return (
        f"{required}; routing metadata only. Mark In Progress before work; spawn the exact subagent only "
        "when the subagent tool is available and policy allows; otherwise do not claim delegation occurred. "
        f"Allowed: {allowed}."
    )


def core_context_guidance() -> str:
    return "\n".join(
        (
            taplctl_execution_guidance(),
            taplctl_command_guidance(),
            "Do not modify source, tests, docs, configs, migrations, generated files, or other durable project artifacts before execution approval.",
            "TAPL run, plan, task, finding, approval, and archive records may be created or updated before execution approval.",
            "The main agent writes TAPL records and final status. Subagents may draft or execute only and must not modify TAPL records.",
        )
    )


def plan_task_context_guidance(settings: tapl_config.PlanTaskExecuteConfig) -> list[str]:
    guidance = [
        "Records: "
        + structured_record_guidance("plan/task content")
        + " "
        + stable_id_guidance(),
        "Order: " + workflow_order_guidance(),
        "Stage progression: " + workflow_stage_progression_guidance(),
        "Plan: include "
        + plan_detail_context(settings.plan_detail)
        + "; "
        + plan_key_label_guidance()
        + " "
        + planning_approval_guidance(settings.planning_approval_level),
        "Plan fields: "
        + field_contract_compact(
            "plan",
            (
                "id",
                "title",
                "summary",
                "objective",
                "requirements_trace",
                "selected_approach",
                "affected_files",
                "execution_order",
                "risks",
                "validation",
            ),
        ),
        "Tasks: after source plan exists, set --spec-id PLAN-001/SPEC-001; "
        "tasks are executable implementation/verification work derived from the stored plan, not planning or task-design work; "
        + task_granularity_guidance(settings.task_granularity)
        + " "
        + task_execution_order_guidance()
        + " "
        + task_fields_context_guidance(settings),
        "Task required fields: " + task_required_field_summary(settings),
        "Agent contract: main agent writes plan/task records and final status; subagents may draft/execute only.",
    ]
    subagent = subagent_context_guidance(settings)
    if subagent:
        guidance.append("Subagents: " + subagent)
    guidance.append("Approval: " + execution_approval_context_guidance(settings))
    return guidance


def should_suggest_prior_search(state: dict[str, Any], prompt: str) -> bool:
    if not prompt.strip():
        return False
    if state.get("plans") or state.get("tasks"):
        return False
    return True


def prior_search_guidance() -> str:
    return (
        "Search: before planning non-trivial work, run "
        "`taplctl search '<compact prompt query>' --agent` and use only relevant results; "
        "for results you judge relevant where the snippet is insufficient, run "
        "`taplctl item show --id <id> --agent` before relying on full details."
    )


def taplctl_execution_guidance() -> str:
    return "Workflow state lives in the repo-local TAPL database through `taplctl`."


def taplctl_command_guidance() -> str:
    return (
        "Use `taplctl ... --agent` for agent-readable output. "
        "Check `taplctl <command> <subcommand> --help` when syntax is uncertain."
    )


def external_findings_guidance() -> str:
    return (
        "When external search or documentation review affects the task, add only decision-relevant findings: "
        "`taplctl finding add --title '<title>' --source '<source>' --finding '<finding>' "
        "--impact '<impact>' --related-ids '<ids>' --agent`. Do not store raw search dumps, "
        "long candidate lists, or stale findings."
    )


def level_subagent_guidance(settings: tapl_config.PlanTaskExecuteConfig) -> str:
    allowed = ", ".join(LEVEL_SUBAGENTS)
    if not settings.use_level_subagent:
        return "Level subagent routing is disabled; omit required_subagent and do not spawn subagents."
    if settings.level_subagent_aggressiveness == "minimal":
        return (
            "Set required_subagent only for obvious risk or explicit routing; missing values do "
            f"not warn or error. Treat it as routing metadata. Allowed values: {allowed}."
        )
    if settings.level_subagent_aggressiveness == "force":
        return (
            f"Every executable task must set required_subagent to one of {allowed}; missing values are errors. "
            "Set it when creating the task, not as a follow-up repair."
        )
    return (
        f"Choose required_subagent from {allowed} based on task risk/config and set it when creating "
        "new executable tasks; existing unrouted executable tasks warn. Do not use level labels such as `level2`."
    )


def subagent_execution_guidance(settings: tapl_config.PlanTaskExecuteConfig) -> str:
    if not settings.use_level_subagent:
        return "Subagent execution routing is disabled; execute tasks directly without subagent assignment."
    return (
        "Before executing a task with required_subagent, set it In Progress. Spawn that exact subagent "
        "only when a subagent tool is available and user/session policy allows delegation; otherwise "
        "do not claim delegation occurred, and the main agent records direct execution, result, and final status."
    )


def subagent_routing_guidance(settings: tapl_config.PlanTaskExecuteConfig) -> str:
    if not settings.use_level_subagent:
        return ""
    return (
        "Task routing:\n\n"
        "- `@junior-worker`: low-risk mechanical changes, formatting, small docs, simple test updates.\n"
        "- `@senior-worker`: normal feature work, refactoring, bug fixes, multi-file changes with clear tests, backward compatibility work.\n"
        "- `@specialist-worker`: security, auth, permissions, migrations, payments, data loss risk, performance-critical or concurrency-sensitive code, public API changes.\n\n"
        "Set `required_subagent` in the same command that creates each executable task. "
        "Spawn that exact subagent only when the subagent tool is available and policy allows delegation; "
        "otherwise execute directly and do not claim delegation occurred."
    )


def subagent_context_guidance(settings: tapl_config.PlanTaskExecuteConfig) -> str:
    if not settings.use_level_subagent:
        return ""
    allowed = ", ".join(LEVEL_SUBAGENTS)
    if settings.level_subagent_aggressiveness == "minimal":
        return (
            "Set required_subagent only for clear risk/routing; it is routing metadata. "
            "If set, mark the task In Progress before work; spawn that exact subagent only when the "
            "subagent tool is available and user/session policy allows delegation; otherwise do not claim "
            f"delegation occurred; main records result/status. Allowed: {allowed}."
        )
    if settings.level_subagent_aggressiveness == "force":
        return (
            "Every executable task needs required_subagent in the task creation command; treat it as routing metadata; "
            "mark In Progress before work; spawn that exact subagent only when the subagent tool is available and "
            f"user/session policy allows delegation; otherwise do not claim delegation occurred; main records result/status. Allowed: {allowed}."
        )
    return (
        "Choose required_subagent by task risk/config in the same command that creates each executable task; "
        "treat it as routing metadata; mark In Progress before work; spawn that exact subagent only when the "
        "subagent tool is available and user/session policy allows delegation; otherwise do not claim delegation "
        f"occurred; main records result/status. Allowed: {allowed}."
    )


def plan_detail_guidance(value: str) -> str:
    return {
        "minimal": "Write objective, selected approach, affected files, and validation only.",
        "less_detailed": "Add constraints and risks only when they affect execution.",
        "detailed": "Include requirements trace, execution order, risks, and validation.",
        "very_detailed": "Expand edge cases, alternatives considered, and per-spec validation.",
    }[value]


def plan_detail_context(value: str) -> str:
    return {
        "minimal": "objective, approach, affected files, validation",
        "less_detailed": "objective, approach, constraints, affected files, risks, validation",
        "detailed": "requirements trace, execution order, risks, validation",
        "very_detailed": "requirements trace, execution order, risks, edge cases, alternatives, per-spec validation",
    }[value]


def planning_approval_guidance(value: str) -> str:
    guidance = {
        "less": (
            "Before `taplctl plan set`, use request_user_input Tool only for blocking or "
            "high-risk material scope/risk/API/UX/data/compat choices. Ask follow-up questions "
            "only when the answer remains blocking; otherwise state assumptions."
        ),
        "auto": (
            "Before `taplctl plan set`, use request_user_input Tool for ambiguous material "
            "scope/risk/API/UX/data/compat decisions. Prefer one short question with 2-3 "
            "mutually exclusive options; ask additional questions only when needed to resolve "
            "material ambiguity."
        ),
        "more": (
            "Before `taplctl plan set`, use request_user_input Tool early for unclear planning "
            "methods, material scope/risk/API/UX/data/compat, or tradeoffs. Ask short, focused "
            "questions with 2-3 mutually exclusive options, and continue with follow-ups until "
            "the plan is materially clear."
        ),
    }[value]
    return (
        f"{guidance} Invoke it only when the Tool is available in the current mode; "
        "if unavailable, state assumptions or ask one concise plain-text question only when blocked."
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
        f"Pass {subject} through structured CLI field arguments; tapl renders the stored "
        "Markdown body from templates during record merge."
    )


def stable_id_guidance() -> str:
    return (
        "Use numeric stable ids only: `PLAN-001` or `SPEC-001` for plans/specs, "
        "`TASK-001` for tasks. Do not use word suffixes such as `TASK-MEANINGS`."
    )


def workflow_order_guidance() -> str:
    return (
        "Lifecycle order: inspect status -> resolve residual run direction with user approval -> "
        "analyze/search and clarify until unblocked -> `taplctl plan set` -> design executable tasks "
        "from the stored plan -> `taplctl task set` -> set execution approval -> execute/update tasks -> "
        "report result/status and allow eligible auto-archive."
    )


def workflow_stage_progression_guidance() -> str:
    return (
        "unless the user explicitly limits the workflow to a specific stage, continue to the next "
        "lifecycle step automatically. If the user asks for planning only, stop after the plan and report status. "
        "If the user asks to plan but does not explicitly ask for implementation/execution, ask with request_user_input "
        "whether to continue after the plan. If the user explicitly asks for implementation, edits, verification, or "
        "testing, treat that as explicit_user execution approval and record approval source accordingly before execution."
    )


def task_plan_dependency_guidance() -> str:
    return (
        "Create or update executable task records only after the source plan/spec exists; "
        "tasks derive from the stored plan/spec and should not represent planning or task-design work; "
        "set --spec-id to the stored numeric plan/spec id, e.g. `PLAN-001` or `SPEC-001`."
    )


def task_execution_order_guidance() -> str:
    return (
        "Execute planned tasks one at a time in task order: set the next task to "
        "`In Progress` immediately before work, then update it to `Completed`, "
        "`Blocked`, or `Skipped` before starting another task."
    )


def agent_writer_contract_guidance() -> str:
    return (
        "Agent contract: subagents may propose task drafts, but the main agent writes "
        "plan/task records and final task status in order."
    )


def task_granularity_guidance(value: str) -> str:
    return {
        "minimal": "Use one executable task unless phases are truly separate.",
        "less_granular": "Split by major phase or owner boundary.",
        "granular": "Split by meaningful implementation and verification steps.",
        "very_granular": "Split every independent edit, migration, and verification step.",
    }[value]


def task_required_fields(settings: tapl_config.PlanTaskExecuteConfig) -> str:
    fields = ", ".join(task_required_field_flags(settings, "Pending"))
    return f"Each executable task must include {fields} when applicable."


def task_fields_context_guidance(settings: tapl_config.PlanTaskExecuteConfig) -> str:
    executable_fields = task_required_field_flags(settings, "Pending")
    completed_fields = task_required_field_flags(settings, "Completed")
    blocked_fields = task_required_field_flags(settings, "Blocked")
    return (
        f"fields: executable={', '.join(executable_fields)}; "
        f"completed={', '.join(completed_fields)}; "
        f"blocked={', '.join(blocked_fields)}; updates are partial."
    )


def task_format_guidance(settings: tapl_config.PlanTaskExecuteConfig) -> str:
    fields = task_required_field_flags(settings, "Pending")
    optional_subagent = ""
    if settings.use_level_subagent and settings.level_subagent_aggressiveness == "minimal":
        optional_subagent = " Set --required-subagent only for explicit subagent routing."
    return (
        f"Executable implementation/verification tasks should include {', '.join(fields)}, "
        f"completed tasks should include {', '.join(task_required_field_flags(settings, 'Completed'))}; "
        f"blocked tasks should include {', '.join(task_required_field_flags(settings, 'Blocked'))}. "
        "When updating an existing task, pass only changed fields; omitted fields keep stored values."
        f"{optional_subagent}"
    )


def execution_approval_guidance(settings: tapl_config.PlanTaskExecuteConfig) -> str:
    base = (
        "After task design/task set and before starting or continuing task execution, set execution approval with "
        "`taplctl approval set --decision approved --prompt '<approved scope>' --source explicit_user --agent` "
        "when the user explicitly requested execution; use `--source request_user_input` when approval came from "
        "request_user_input."
    )
    if settings.require_execution_approval:
        return base + " Missing execution approval is a validation error when require_execution_approval is true."
    return base + " Missing execution approval is a warning, and enforce-mode hooks block on it."


def execution_approval_context_guidance(settings: tapl_config.PlanTaskExecuteConfig) -> str:
    if settings.require_execution_approval:
        return (
            "planning clarifications follow planning_approval_level before plan set; after task set, "
            "set execution approval before task execution/durable edits: "
            "`taplctl approval set --decision approved --prompt '<approved scope>' --source explicit_user --agent` "
            "for explicit user execution requests, or `--source request_user_input` for tool-confirmed continuation."
        )
    return (
        "planning clarifications follow planning_approval_level before plan set; execution approval is "
        "optional for material risk/scope; missing approval is a warning."
    )


def command_help_epilog() -> str:
    return (
        "Workflow guidance:\n"
        "  Use `taplctl status --agent` to inspect state before non-trivial work.\n"
        f"  {workflow_order_guidance()}\n"
        f"  Stage progression: {workflow_stage_progression_guidance()}\n"
        f"  {task_execution_order_guidance()}\n"
        "  Use `taplctl <command> <subcommand> --help` for field-writing rules.\n"
        f"  {structured_record_guidance()}\n"
        "  Use `taplctl validate --agent` after updates to catch missing plan/task details."
    )


def plan_set_epilog() -> str:
    return (
        "Plan writing rules:\n"
        f"  {structured_record_guidance()}\n"
        f"  {stable_id_guidance()}\n"
        "  Write or update the plan before executable task records; downstream tasks should derive from this record.\n"
        f"  {plan_format_guidance()}\n"
        f"  {plan_key_label_guidance()}\n"
        "  Pass plan content through field arguments; tapl renders the durable Markdown body from a template.\n"
        "  Summary should be a compact trace such as `REQ-001: approach, files, risks, validation`.\n"
        "  Existing plan updates are partial: omitted fields keep the stored values.\n"
        "  Status is free-form; common values are Draft, Finalized, Imported, and Superseded.\n"
        "\n"
        "Field contract:\n"
        f"{field_contract_section('plan')}\n"
        "\n"
        "Example:\n"
        "  taplctl plan set --id PLAN-001 --title 'Plan title' \\\n"
        "    --summary 'REQ-001: approach, affected files, risks, validation' \\\n"
        "    --objective 'Implement requested behavior' \\\n"
        "    --requirements-trace 'REQ-001: field-based plan records' \\\n"
        "    --validation 'Run focused tests' --status Finalized --agent"
    )


def task_set_epilog(
    *,
    settings: tapl_config.PlanTaskExecuteConfig | None = None,
    statuses: Iterable[str] = TASK_STATUSES,
    subagents: Iterable[str] = LEVEL_SUBAGENTS,
) -> str:
    config = settings or tapl_config.PlanTaskExecuteConfig()
    status_values = ", ".join(statuses)
    subagent_values = ", ".join(subagents)
    subagent_lines = task_help_subagent_lines(config, subagent_values)
    example_subagent = " --required-subagent '@senior-worker'" if requires_required_subagent(config) else ""
    return (
        "Task writing rules:\n"
        f"  {structured_record_guidance('task content')}\n"
        f"  {stable_id_guidance()}\n"
        f"  {task_plan_dependency_guidance()}\n"
        f"  {task_execution_order_guidance()}\n"
        "  Existing task updates are partial: pass --id plus only changed fields;\n"
        "  omitted fields keep their stored values. New task creation requires --title and --status.\n"
        f"  {task_format_guidance(config)}\n"
        f"{subagent_lines}"
        "  Split tasks by meaningful implementation or verification step.\n"
        f"  Status values: {status_values}. Quote multi-word statuses, e.g. --status 'In Progress'.\n"
        "  Keep task text in the user's language unless asked otherwise.\n"
        "\n"
        "Required field sets:\n"
        f"  {task_required_field_summary(config)}\n"
        "\n"
        "Field contract:\n"
        f"{field_contract_section('task', settings=config)}\n"
        "\n"
        "Example:\n"
        "  taplctl task set --id TASK-001 --title 'Implement change' \\\n"
        "    --status 'In Progress' --spec-id PLAN-001 --goal 'Make requested behavior work' \\\n"
        f"    --action 'Edit the relevant files'{example_subagent} \\\n"
        "    --verification 'Run focused tests' --agent\n"
        "  taplctl task set --id TASK-001 --status Completed --result 'Focused tests passed' --agent"
    )


def requires_required_subagent(settings: tapl_config.PlanTaskExecuteConfig) -> bool:
    return bool(settings.use_level_subagent and settings.level_subagent_aggressiveness != "minimal")


def task_help_subagent_lines(settings: tapl_config.PlanTaskExecuteConfig, subagent_values: str) -> str:
    if not settings.use_level_subagent:
        return "  Subagent routing is disabled; --required-subagent is optional metadata and not required.\n"
    if settings.level_subagent_aggressiveness == "minimal":
        return (
            "  Set --required-subagent only for explicit subagent routing; direct tasks may omit it.\n"
            "  Before execution set In Progress; spawn that exact subagent only when a subagent\n"
            "  tool is available and user/session policy allows delegation. Otherwise do not claim\n"
            "  delegation occurred; the main agent records direct execution and result/status.\n"
            f"  Allowed required_subagent values when used: {subagent_values}. Do not use level names such as `level2`.\n"
        )
    return (
        "  When level subagent routing is enabled, set required_subagent in the same command\n"
        "  that creates each executable task; treat it as routing metadata.\n"
        "  Before execution set In Progress; spawn that exact subagent only when a subagent\n"
        "  tool is available and user/session policy allows delegation. Otherwise do not claim\n"
        "  delegation occurred; the main agent records direct execution and result/status.\n"
        f"  Allowed required_subagent values when enabled: {subagent_values}. Do not use level names such as `level2`.\n"
    )


def finding_add_epilog() -> str:
    return (
        "Finding writing rules:\n"
        f"  {markdown_record_guidance('finding details and impact')}\n"
        "  Add only decision-relevant facts; include source and impact when they affect\n"
        "  requirements, plan, tasks, or verification.\n"
        "\n"
        "Field contract:\n"
        f"{field_contract_section('finding')}\n"
        "\n"
        "Example:\n"
        "  taplctl finding add --title 'Finding title' --source 'Source' \\\n"
        "    --finding 'What was learned' --impact 'Why it matters' --agent"
    )


def approval_set_epilog() -> str:
    return (
        "Approval writing rules:\n"
        "  Record explicit user decisions for residual-run handling, planning clarification,\n"
        "  or execution scope. Execution approval is normally set after task design/task set\n"
        "  and before starting or continuing task execution. Set --source explicit_user when\n"
        "  the request itself explicitly allowed execution, or --source request_user_input when\n"
        "  continuing was approved through the request_user_input tool. The prompt should\n"
        "  describe the approved decision/scope, not just `yes`.\n"
        "\n"
        "Field contract:\n"
        f"{field_contract_section('approval')}\n"
        "\n"
        "Example:\n"
        "  taplctl approval set --decision approved \\\n"
        "    --prompt 'Execute TASK-001 from PLAN-001' --source explicit_user --agent"
    )
