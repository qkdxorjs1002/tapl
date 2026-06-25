"""Plan/task validation driven by tapl runtime config."""

from __future__ import annotations

import re
import sqlite3
from typing import Any

from . import config as tapl_config, db, prompt as tapl_prompt


LEVEL_SUBAGENTS = tapl_prompt.LEVEL_SUBAGENTS
EXECUTABLE_STATUSES = ("Pending", "In Progress", "Blocked")
PLAN_KEY_LABELS = tapl_prompt.PLAN_KEY_LABELS
PLAN_ID_PATTERN = re.compile(r"^(?:PLAN|SPEC)-\d{3,}$")
TASK_ID_PATTERN = re.compile(r"^TASK-\d{3,}$")


def validate_plan_task_execute(
    conn: sqlite3.Connection,
    settings: tapl_config.PlanTaskExecuteConfig,
    *,
    include_guidance: bool = False,
) -> dict[str, Any]:
    state = db.status_payload(conn)
    if not state.get("active_run"):
        result: dict[str, Any] = {
            "ok": True,
            "errors": [],
            "warnings": [],
            "issues": [],
        }
        if include_guidance:
            result["guidance"] = guidance(settings)
        return result

    plans = state.get("plans", [])
    tasks = state.get("tasks", [])
    issues: list[dict[str, Any]] = []
    issues.extend(validate_stable_ids(plans, tasks))
    issues.extend(validate_level_subagents(tasks, settings))
    issues.extend(validate_plan_detail(plans, settings))
    issues.extend(validate_plan_content(plans, settings))
    issues.extend(validate_task_granularity(plans, tasks, settings))
    issues.extend(validate_task_content(tasks, settings))
    issues.extend(validate_task_execution_order(tasks))
    issues.extend(validate_execution_approval(state, tasks, settings))
    errors = [item for item in issues if item["severity"] == "error"]
    warnings = [item for item in issues if item["severity"] == "warning"]
    result = {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "issues": issues,
    }
    if include_guidance:
        result["guidance"] = guidance(settings)
    return result


def validate_plan_input(
    *,
    plan_id: str,
    settings: tapl_config.PlanTaskExecuteConfig,
) -> dict[str, Any]:
    issues = validate_stable_ids([{"stable_id": plan_id}], [])
    errors = [item for item in issues if item["severity"] == "error"]
    warnings = [item for item in issues if item["severity"] == "warning"]
    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "issues": issues,
        "guidance": guidance(settings),
    }


def validate_task_input(
    *,
    task_id: str,
    status: str,
    spec_id: str,
    required_subagent: str,
    settings: tapl_config.PlanTaskExecuteConfig,
) -> dict[str, Any]:
    task = {
        "stable_id": task_id,
        "status": status,
        "spec_id": spec_id,
        "required_subagent": required_subagent,
    }
    issues = validate_stable_ids([], [task])
    issues.extend(validate_level_subagents([task], settings))
    errors = [item for item in issues if item["severity"] == "error"]
    warnings = [item for item in issues if item["severity"] == "warning"]
    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "issues": issues,
        "guidance": guidance(settings),
    }


def validate_new_task_routing(
    *,
    task_id: str,
    status: str,
    required_subagent: str,
    settings: tapl_config.PlanTaskExecuteConfig,
) -> list[dict[str, Any]]:
    if not requires_required_subagent(settings):
        return []
    if status not in EXECUTABLE_STATUSES:
        return []
    if required_subagent.strip():
        return []
    allowed = ", ".join(LEVEL_SUBAGENTS)
    return [
        issue(
            "error",
            "missing_required_subagent",
            f"{task_id} is executable and new task creation requires required_subagent.",
            "Pass --required-subagent in the same `taplctl task set` command "
            f"using one of: {allowed}. Use minimal routing config only for intentionally direct tasks.",
            stable_id=task_id,
        )
    ]


def requires_required_subagent(settings: tapl_config.PlanTaskExecuteConfig) -> bool:
    return bool(settings.use_level_subagent and settings.level_subagent_aggressiveness != "minimal")


def validate_stable_ids(plans: list[dict[str, Any]], tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for plan in plans:
        stable_id = str(plan.get("stable_id") or "").strip()
        if not is_numeric_plan_id(stable_id):
            issues.append(
                issue(
                    "error",
                    "invalid_plan_id",
                    f"Plan id `{stable_id or 'plan'}` must use a numeric stable id.",
                    "Use `PLAN-001` or `SPEC-001`; do not use word suffixes such as `PLAN-MEANINGS`.",
                    stable_id=stable_id or None,
                )
            )

    for task in tasks:
        stable_id = str(task.get("stable_id") or task.get("task_id") or "").strip()
        if not is_numeric_task_id(stable_id):
            issues.append(
                issue(
                    "error",
                    "invalid_task_id",
                    f"Task id `{stable_id or 'task'}` must use a numeric stable id.",
                    "Use `TASK-001`; do not use word suffixes such as `TASK-MEANINGS`.",
                    stable_id=stable_id or None,
                )
            )

        spec_id = str(task.get("spec_id") or "").strip()
        if spec_id and not is_numeric_plan_id(spec_id):
            issues.append(
                issue(
                    "error",
                    "invalid_task_spec_id",
                    f"Task source spec id `{spec_id}` must use a numeric plan/spec stable id.",
                    "Set --spec-id to a stored numeric plan/spec id such as `PLAN-001` or `SPEC-001`.",
                    stable_id=stable_id or None,
                )
            )
    return issues


def is_numeric_plan_id(stable_id: str) -> bool:
    return bool(PLAN_ID_PATTERN.fullmatch(stable_id))


def is_numeric_task_id(stable_id: str) -> bool:
    return bool(TASK_ID_PATTERN.fullmatch(stable_id))


def validate_level_subagents(
    tasks: list[dict[str, Any]],
    settings: tapl_config.PlanTaskExecuteConfig,
) -> list[dict[str, Any]]:
    if not settings.use_level_subagent:
        return []

    issues: list[dict[str, Any]] = []
    for task in executable_tasks(tasks):
        stable_id = str(task.get("stable_id") or task.get("task_id") or "task")
        required = str(task.get("required_subagent") or "").strip()
        if required and required not in LEVEL_SUBAGENTS:
            issues.append(
                issue(
                    "error",
                    "invalid_required_subagent",
                    f"{stable_id} has invalid required_subagent `{required}`.",
                    f"Use one of: {', '.join(LEVEL_SUBAGENTS)}.",
                    stable_id=stable_id,
                )
            )
            continue
        if required:
            continue

        if settings.level_subagent_aggressiveness == "force":
            severity = "error"
        elif settings.level_subagent_aggressiveness == "auto":
            severity = "warning"
        else:
            continue
        issues.append(
            issue(
                severity,
                "missing_required_subagent",
                f"{stable_id} is executable but has no required_subagent.",
                f"Set --required-subagent to one of: {', '.join(LEVEL_SUBAGENTS)}.",
                stable_id=stable_id,
            )
        )
    return issues


def validate_plan_detail(
    plans: list[dict[str, Any]],
    settings: tapl_config.PlanTaskExecuteConfig,
) -> list[dict[str, Any]]:
    if settings.plan_detail == "minimal":
        return []

    body = "\n".join(str(plan.get("body") or plan.get("title") or "") for plan in plans).strip()
    if not plans:
        severity = "error" if settings.plan_detail == "very_detailed" else "warning"
        return [
            issue(
                severity,
                "missing_plan",
                f"plan_detail is `{settings.plan_detail}`, but the active run has no plan record.",
                "Create or update a plan with `taplctl plan set` before durable edits.",
            )
        ]

    minimum_lengths = {
        "less_detailed": 20,
        "detailed": 80,
        "very_detailed": 180,
    }
    minimum = minimum_lengths.get(settings.plan_detail, 0)
    if minimum and len(body) < minimum:
        return [
            issue(
                "warning",
                "plan_detail_too_sparse",
                f"plan_detail is `{settings.plan_detail}`, but plan text is sparse.",
                "Expand the plan enough to cover objective, approach, affected files, risks, and validation.",
            )
        ]
    return []


def validate_task_granularity(
    plans: list[dict[str, Any]],
    tasks: list[dict[str, Any]],
    settings: tapl_config.PlanTaskExecuteConfig,
) -> list[dict[str, Any]]:
    granularity = settings.task_granularity
    if granularity == "minimal":
        return []

    task_count = len([task for task in tasks if task_status(task) != "Skipped"])
    if task_count == 0:
        return []

    plan_count = len(plans)
    if granularity == "less_granular":
        target = 2 if plan_count > 1 else 1
        severity = "warning"
    elif granularity == "granular":
        target = max(1, plan_count)
        severity = "warning"
    else:
        target = max(2, plan_count * 2)
        severity = "error" if task_count <= 1 else "warning"

    if task_count >= target:
        return []

    return [
        issue(
            severity,
            "task_granularity_too_coarse",
            f"task_granularity is `{granularity}`, but {task_count} task(s) cover {plan_count} plan item(s).",
            task_granularity_remediation(granularity),
        )
    ]


def validate_plan_content(
    plans: list[dict[str, Any]],
    settings: tapl_config.PlanTaskExecuteConfig,
) -> list[dict[str, Any]]:
    if settings.plan_detail in {"minimal", "less_detailed"} or not plans:
        return []

    body = "\n".join(str(plan.get("body") or plan.get("title") or "") for plan in plans).strip()
    missing: list[str] = []
    if not has_any(body, ("REQ-", "Trace:", "requirements trace", "요구사항")):
        missing.append("requirements trace")
    if not has_any(body, ("Validation:", "Verification:", "validation", "verification", "검증")):
        missing.append("validation strategy")

    if not missing:
        return []
    return [
        issue(
            "warning",
            "plan_content_missing_guidance",
            f"Plan content is missing: {', '.join(missing)}.",
            "Include objective, REQ trace, selected approach, affected files/interfaces, execution order, risks, and validation.",
        )
    ]


def validate_task_content(
    tasks: list[dict[str, Any]],
    settings: tapl_config.PlanTaskExecuteConfig,
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for task in tasks:
        status = task_status(task)
        if status == "Skipped":
            continue

        stable_id = str(task.get("stable_id") or task.get("task_id") or "task")
        missing: list[str] = []
        for field in tapl_prompt.task_required_field_names(settings, status):
            if not str(task.get(field) or "").strip():
                missing.append(field)

        if missing:
            issues.append(
                issue(
                    "warning",
                    "task_content_missing_fields",
                    f"{stable_id} is missing task field(s): {', '.join(missing)}.",
                    "Set task goal, numeric source plan/spec id, action, required subagent, verification, and result or blocker details as applicable.",
                    stable_id=stable_id,
                )
            )
    return issues


def validate_task_execution_order(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    in_progress: list[tuple[int, dict[str, Any]]] = [
        (index, task)
        for index, task in enumerate(tasks)
        if task_status(task) == "In Progress"
    ]
    if len(in_progress) > 1:
        labels = ", ".join(task_label(task) for _, task in in_progress)
        issues.append(
            issue(
                "warning",
                "multiple_tasks_in_progress",
                f"Multiple tasks are In Progress: {labels}.",
                "Execute planned tasks one at a time; complete, block, or skip the current task before starting another.",
            )
        )

    if not in_progress:
        return issues

    first_index, first_task = in_progress[0]
    earlier_incomplete = [
        task
        for task in tasks[:first_index]
        if task_status(task) in {"Pending", "Blocked"}
    ]
    if earlier_incomplete:
        labels = ", ".join(task_label(task) for task in earlier_incomplete)
        issues.append(
            issue(
                "warning",
                "task_started_out_of_order",
                f"{task_label(first_task)} is In Progress while earlier task(s) remain incomplete: {labels}.",
                "Run tasks in task order; finish, resolve, skip, or replan earlier tasks before continuing the later task.",
                stable_id=task_label(first_task),
            )
        )
    return issues


def validate_execution_approval(
    state: dict[str, Any],
    tasks: list[dict[str, Any]],
    settings: tapl_config.PlanTaskExecuteConfig,
) -> list[dict[str, Any]]:
    if not executable_tasks(tasks):
        return []

    approval = (state.get("approvals") or {}).get(db.DEFAULT_APPROVAL_KIND) or {}
    approval_state = str(approval.get("state") or "")
    if approval_state == "approved":
        return []

    if approval_state == "rejected":
        return [
            issue(
                "error",
                "execution_approval_rejected",
                "Execution approval was explicitly rejected for the active run.",
                "Resolve scope with the user, then set approval before starting or continuing task execution.",
            )
        ]

    severity = "error" if settings.require_execution_approval else "warning"
    return [
        issue(
            severity,
            "execution_approval_missing",
            "Executable tasks exist but execution approval is not recorded.",
            "Before starting or continuing task execution, set execution approval with `taplctl approval set --decision approved --prompt '<approved scope>' --agent`.",
        )
    ]


def executable_tasks(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [task for task in tasks if task_status(task) in EXECUTABLE_STATUSES]


def task_status(task: dict[str, Any]) -> str:
    return str(task.get("status") or "")


def task_label(task: dict[str, Any]) -> str:
    return str(task.get("stable_id") or task.get("task_id") or "task")


def has_any(text: str, needles: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(needle.lower() in lowered for needle in needles) or bool(re.search(r"\bREQ-\d+\b", text))


def guidance(settings: tapl_config.PlanTaskExecuteConfig) -> dict[str, Any]:
    return {
        "allowed_level_subagents": list(LEVEL_SUBAGENTS),
        "record_format": structured_record_guidance(),
        "stable_ids": stable_id_guidance(),
        "workflow_order": workflow_order_guidance(),
        "task_dependency": task_plan_dependency_guidance(),
        "agent_writer_contract": agent_writer_contract_guidance(),
        "level_subagent": level_subagent_guidance(settings),
        "subagent_execution": subagent_execution_guidance(settings),
        "plan_detail": plan_detail_guidance(settings.plan_detail),
        "planning_approval": planning_approval_guidance(settings.planning_approval_level),
        "plan_format": plan_format_guidance(),
        "task_granularity": task_granularity_guidance(settings.task_granularity),
        "task_execution_order": task_execution_order_guidance(),
        "task_format": task_format_guidance(settings),
        "execution_approval": execution_approval_guidance(settings),
    }


def level_subagent_guidance(settings: tapl_config.PlanTaskExecuteConfig) -> str:
    return tapl_prompt.level_subagent_guidance(settings)


def subagent_execution_guidance(settings: tapl_config.PlanTaskExecuteConfig) -> str:
    return tapl_prompt.subagent_execution_guidance(settings)


def plan_detail_guidance(value: str) -> str:
    return tapl_prompt.plan_detail_guidance(value)


def planning_approval_guidance(value: str) -> str:
    return tapl_prompt.planning_approval_guidance(value)


def plan_format_guidance() -> str:
    return tapl_prompt.plan_format_guidance()


def plan_key_label_guidance() -> str:
    return tapl_prompt.plan_key_label_guidance()


def markdown_record_guidance(subject: str = "plan, task, and finding content") -> str:
    return tapl_prompt.markdown_record_guidance(subject)


def structured_record_guidance(subject: str = "plan and task content") -> str:
    return tapl_prompt.structured_record_guidance(subject)


def stable_id_guidance() -> str:
    return tapl_prompt.stable_id_guidance()


def workflow_order_guidance() -> str:
    return tapl_prompt.workflow_order_guidance()


def task_plan_dependency_guidance() -> str:
    return tapl_prompt.task_plan_dependency_guidance()


def task_execution_order_guidance() -> str:
    return tapl_prompt.task_execution_order_guidance()


def agent_writer_contract_guidance() -> str:
    return tapl_prompt.agent_writer_contract_guidance()


def task_granularity_guidance(value: str) -> str:
    return tapl_prompt.task_granularity_guidance(value)


def task_format_guidance(settings: tapl_config.PlanTaskExecuteConfig) -> str:
    return tapl_prompt.task_format_guidance(settings)


def execution_approval_guidance(settings: tapl_config.PlanTaskExecuteConfig) -> str:
    return tapl_prompt.execution_approval_guidance(settings)


def task_granularity_remediation(value: str) -> str:
    if value == "less_granular":
        return "Split the work into major phases or owner boundaries."
    if value == "very_granular":
        return "Split the work so independent edits, migrations, docs, and verification each have tasks."
    return "Split the work into meaningful implementation and verification tasks."


def format_issues(result: dict[str, Any], *, max_items: int = 6) -> str:
    issues = result.get("issues") or []
    if not issues:
        return ""
    lines = ["tapl: plan-task-execute validation found issues:"]
    for item in issues[:max_items]:
        lines.append(
            f"- {item['severity']} {item['code']}: {item['message']} Remediation: {item['remediation']}"
        )
    remaining = len(issues) - max_items
    if remaining > 0:
        lines.append(f"- ...and {remaining} more issue(s).")
    return "\n".join(lines)


def issue(
    severity: str,
    code: str,
    message: str,
    remediation: str,
    *,
    stable_id: str | None = None,
) -> dict[str, Any]:
    payload = {
        "severity": severity,
        "code": code,
        "message": message,
        "remediation": remediation,
    }
    if stable_id:
        payload["stable_id"] = stable_id
    return payload
