"""Prompt templates and guidance rendering for tapl."""

from __future__ import annotations

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
- Before implementation starts, ask whether to execute the prepared tasks and record approval with `taplctl approval set --decision approved --prompt '<approved scope>' --agent`.

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
taplctl approval set --decision approved --prompt '<approved scope>' --agent
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
        "subagent_routing_guidance": subagent_routing_guidance(config),
        "subagent_execution_guidance": subagent_execution_guidance(config),
        "execution_approval_guidance": execution_approval_guidance(config),
        "command_required_subagent": (
            " --required-subagent '@junior-worker'" if config.use_level_subagent else ""
        ),
    }
    values.update({key: str(value) for key, value in overrides.items()})
    return values


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
        guidance = [
            WORKFLOW_INTRO,
            core_context_guidance(),
            REQUEST_STARTUP,
        ]
        if should_suggest_prior_search(state, prompt):
            guidance.append(prior_search_guidance())
        guidance.extend(plan_task_context_guidance(settings))
        guidance.append(external_findings_guidance())
        return guidance

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
        "Plan: include "
        + plan_detail_context(settings.plan_detail)
        + "; "
        + plan_key_label_guidance()
        + " "
        + planning_approval_guidance(settings.planning_approval_level),
        "Tasks: after source plan exists, set --spec-id PLAN-001/SPEC-001; "
        "tasks are executable implementation/verification work derived from the stored plan, not planning or task-design work; "
        + task_granularity_guidance(settings.task_granularity)
        + " "
        + task_execution_order_guidance()
        + " "
        + task_fields_context_guidance(settings),
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
    fields = "`spec_id`, goal, action"
    if settings.use_level_subagent:
        fields += ", required subagent"
    fields += ", and verification"
    return f"Each task must include {fields} when applicable."


def task_fields_context_guidance(settings: tapl_config.PlanTaskExecuteConfig) -> str:
    executable_fields = ["spec_id", "goal", "action"]
    if settings.use_level_subagent and settings.level_subagent_aggressiveness != "minimal":
        executable_fields.append("required_subagent")
    executable_fields.append("verification")
    return (
        f"fields: executable={', '.join(executable_fields)}; "
        "completed=verification, result; blocked=blocker, next_action; updates are partial."
    )


def task_format_guidance(settings: tapl_config.PlanTaskExecuteConfig) -> str:
    fields = ["source spec_id", "goal", "action"]
    if settings.use_level_subagent and settings.level_subagent_aggressiveness != "minimal":
        fields.append("required_subagent")
    fields.append("verification")
    optional_subagent = ""
    if settings.use_level_subagent and settings.level_subagent_aggressiveness == "minimal":
        optional_subagent = " Set required_subagent only for explicit subagent routing."
    return (
        f"Executable implementation/verification tasks should include {', '.join(fields)}, "
        "and result when completed; blocked tasks should include blocker and next_action. "
        "When updating an existing task, pass only changed fields; omitted fields keep stored values."
        f"{optional_subagent}"
    )


def execution_approval_guidance(settings: tapl_config.PlanTaskExecuteConfig) -> str:
    base = (
        "After task design/task set and before starting or continuing task execution, set execution approval with "
        "`taplctl approval set --decision approved --prompt '<approved scope>' --agent`."
    )
    if settings.require_execution_approval:
        return base + " Missing execution approval is a validation error when require_execution_approval is true."
    return base + " Missing execution approval is a warning, and enforce-mode hooks block on it."


def execution_approval_context_guidance(settings: tapl_config.PlanTaskExecuteConfig) -> str:
    if settings.require_execution_approval:
        return (
            "planning clarifications follow planning_approval_level before plan set; after task set, "
            "set execution approval before task execution/durable edits: "
            "`taplctl approval set --decision approved --prompt '<approved scope>' --agent`."
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
        "Example:\n"
        "  taplctl plan set --id PLAN-001 --title 'Plan title' \\\n"
        "    --summary 'REQ-001: approach, affected files, risks, validation' \\\n"
        "    --objective 'Implement requested behavior' \\\n"
        "    --requirements-trace 'REQ-001: field-based plan records' \\\n"
        "    --validation 'Run focused tests' --status Finalized --agent"
    )


def task_set_epilog(
    *,
    statuses: Iterable[str] = TASK_STATUSES,
    subagents: Iterable[str] = LEVEL_SUBAGENTS,
) -> str:
    status_values = ", ".join(statuses)
    subagent_values = ", ".join(subagents)
    return (
        "Task writing rules:\n"
        f"  {structured_record_guidance('task content')}\n"
        f"  {stable_id_guidance()}\n"
        f"  {task_plan_dependency_guidance()}\n"
        f"  {task_execution_order_guidance()}\n"
        "  Existing task updates are partial: pass --id plus only changed fields;\n"
        "  omitted fields keep their stored values. New task creation requires --title and --status.\n"
        "  Executable implementation/verification tasks should include source spec_id, goal, action, verification,\n"
        "  and result when completed; blocked tasks should include blocker and next_action.\n"
        "  When level subagent routing is enabled, set required_subagent in the same command\n"
        "  that creates each executable task; treat it as routing metadata.\n"
        "  Before execution set In Progress; spawn that exact subagent only when a subagent\n"
        "  tool is available and user/session policy allows delegation. Otherwise do not claim\n"
        "  delegation occurred; the main agent records direct execution and result/status.\n"
        "  Split tasks by meaningful implementation or verification step.\n"
        f"  Status values: {status_values}. Quote multi-word statuses, e.g. --status 'In Progress'.\n"
        f"  Allowed required_subagent values when enabled: {subagent_values}. Do not use level names such as `level2`.\n"
        "  Keep task text in the user's language unless asked otherwise.\n"
        "\n"
        "Field guidance:\n"
        "  --spec-id: numeric stable id of the source plan/spec, e.g. PLAN-001 or SPEC-001.\n"
        "  --goal: outcome the task must achieve.\n"
        "  --action: concrete work to perform.\n"
        "  --verification: command, check, or review that proves the task is done.\n"
        "  --result: concise completion note; use with Completed tasks.\n"
        "  --blocker/--next-action: why a Blocked task cannot proceed and what unblocks it.\n"
        "\n"
        "Example:\n"
        "  taplctl task set --id TASK-001 --title 'Implement change' \\\n"
        "    --status 'In Progress' --spec-id PLAN-001 --goal 'Make requested behavior work' \\\n"
        "    --action 'Edit the relevant files' --required-subagent '@senior-worker' \\\n"
        "    --verification 'Run focused tests' --agent\n"
        "  taplctl task set --id TASK-001 --status Completed --result 'Focused tests passed' --agent"
    )


def finding_add_epilog() -> str:
    return (
        "Finding writing rules:\n"
        f"  {markdown_record_guidance('finding details and impact')}\n"
        "  Add only decision-relevant facts; include source and impact when they affect\n"
        "  requirements, plan, tasks, or verification.\n"
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
        "  and before starting or continuing task execution. The prompt should describe the\n"
        "  approved decision/scope, not just `yes`.\n"
        "\n"
        "Example:\n"
        "  taplctl approval set --decision approved \\\n"
        "    --prompt 'Execute TASK-001 from PLAN-001' --agent"
    )
