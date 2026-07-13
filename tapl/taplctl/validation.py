"""Plan/task validation driven by TAPL's fixed workflow policy."""

from __future__ import annotations

import re
import sqlite3
from typing import Any

from . import db, prompt as tapl_prompt


EXECUTABLE_STATUSES = ("Pending", "In Progress", "Blocked")
PLAN_KEY_LABELS = tapl_prompt.PLAN_KEY_LABELS
PLAN_ID_PATTERN = re.compile(r"^(?:PLAN|SPEC)-\d{3,}$")
TASK_ID_PATTERN = re.compile(r"^TASK-\d{3,}$")


def validate_plan_task_execute(
    conn: sqlite3.Connection,
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
            result["guidance"] = guidance()
        return result

    plans = state.get("plans", [])
    tasks = state.get("tasks", [])
    issues: list[dict[str, Any]] = []
    issues.extend(validate_stable_ids(plans, tasks))
    issues.extend(validate_plan_detail(plans))
    issues.extend(validate_plan_content(plans))
    issues.extend(validate_task_granularity(plans, tasks))
    issues.extend(validate_task_content(tasks))
    issues.extend(validate_task_execution_order(tasks))
    issues.extend(validate_execution_approval(state, tasks))
    errors = [item for item in issues if item["severity"] == "error"]
    warnings = [item for item in issues if item["severity"] == "warning"]
    result = {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "issues": issues,
    }
    if include_guidance:
        result["guidance"] = guidance()
    return result


def validate_plan_input(
    *,
    plan_id: str,
) -> dict[str, Any]:
    issues = validate_stable_ids([{"stable_id": plan_id}], [])
    errors = [item for item in issues if item["severity"] == "error"]
    warnings = [item for item in issues if item["severity"] == "warning"]
    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "issues": issues,
        "guidance": guidance(),
    }


def validate_task_input(
    *,
    task_id: str,
    status: str,
    spec_id: str,
) -> dict[str, Any]:
    task = {
        "stable_id": task_id,
        "status": status,
        "spec_id": spec_id,
    }
    issues = validate_stable_ids([], [task])
    errors = [item for item in issues if item["severity"] == "error"]
    warnings = [item for item in issues if item["severity"] == "warning"]
    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "issues": issues,
        "guidance": guidance(),
    }


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
                    tapl_prompt.invalid_plan_id_remediation(),
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
                    tapl_prompt.invalid_task_id_remediation(),
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
                    tapl_prompt.invalid_task_spec_id_remediation(),
                    stable_id=stable_id or None,
                )
            )
    return issues


def is_numeric_plan_id(stable_id: str) -> bool:
    return bool(PLAN_ID_PATTERN.fullmatch(stable_id))


def is_numeric_task_id(stable_id: str) -> bool:
    return bool(TASK_ID_PATTERN.fullmatch(stable_id))


def validate_plan_detail(plans: list[dict[str, Any]]) -> list[dict[str, Any]]:
    body = "\n".join(str(plan.get("body") or plan.get("title") or "") for plan in plans).strip()
    if not plans:
        return [
            issue(
                "error",
                "missing_plan",
                "The fixed `very_detailed` policy requires a plan record for the active run.",
                tapl_prompt.missing_plan_remediation(),
            )
        ]

    if len(body) < 180:
        return [
            issue(
                "warning",
                "plan_detail_too_sparse",
                "The fixed `very_detailed` policy requires a less sparse plan.",
                tapl_prompt.sparse_plan_remediation(),
            )
        ]
    return []


def validate_task_granularity(
    plans: list[dict[str, Any]],
    tasks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    task_count = len([task for task in tasks if task_status(task) != "Skipped"])
    if task_count == 0:
        return []

    plan_count = len(plans)
    target = max(2, plan_count * 2)
    severity = "error" if task_count <= 1 else "warning"

    if task_count >= target:
        return []

    return [
        issue(
            severity,
            "task_granularity_too_coarse",
            f"The fixed `very_granular` policy has {task_count} task(s) for {plan_count} plan item(s).",
            task_granularity_remediation(),
        )
    ]


def validate_plan_content(plans: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not plans:
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
            tapl_prompt.plan_content_remediation(),
        )
    ]


def validate_task_content(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for task in tasks:
        status = task_status(task)
        if status == "Skipped":
            continue

        stable_id = str(task.get("stable_id") or task.get("task_id") or "task")
        missing: list[str] = []
        for field in tapl_prompt.task_required_field_names(status):
            if not str(task.get(field) or "").strip():
                missing.append(field)

        if missing:
            issues.append(
                issue(
                    "warning",
                    "task_content_missing_fields",
                    f"{stable_id} is missing task field(s): {', '.join(missing)}.",
                    tapl_prompt.task_content_remediation(),
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
                tapl_prompt.multiple_tasks_in_progress_remediation(),
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
                tapl_prompt.task_started_out_of_order_remediation(),
                stable_id=task_label(first_task),
            )
        )
    return issues


def validate_execution_approval(
    state: dict[str, Any],
    tasks: list[dict[str, Any]],
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
                tapl_prompt.execution_approval_rejected_remediation(),
            )
        ]

    return [
        issue(
            "error",
            "execution_approval_missing",
            "Executable tasks exist but execution approval is not recorded.",
            tapl_prompt.execution_approval_missing_remediation(),
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


def guidance() -> dict[str, Any]:
    payload: dict[str, Any] = {
        "field_contract_source": "Use `taplctl <command> <subcommand> --help` for exact field contracts and examples.",
        "stable_ids": stable_id_guidance(),
        "fixed_plan_policy": plan_detail_guidance(),
        "fixed_task_policy": task_granularity_guidance(),
        "task_required_fields": tapl_prompt.task_required_field_summary(),
        "fixed_execution_approval_policy": execution_approval_validation_guidance(),
    }
    return payload


def plan_detail_guidance() -> str:
    return tapl_prompt.plan_detail_guidance()


def stable_id_guidance() -> str:
    return tapl_prompt.stable_id_guidance()


def task_granularity_guidance() -> str:
    return tapl_prompt.task_granularity_guidance()


def execution_approval_validation_guidance() -> str:
    return "Missing execution approval is always a validation error; use `taplctl approval approve --help` for the high-level command."


def task_granularity_remediation() -> str:
    return tapl_prompt.task_granularity_remediation()


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
