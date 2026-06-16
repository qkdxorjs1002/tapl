"""Plan/task validation driven by tapl runtime config."""

from __future__ import annotations

import sqlite3
from typing import Any

from . import config as tapl_config, db


LEVEL_SUBAGENTS = ("@junior-worker", "@senior-worker", "@specialist-worker")
EXECUTABLE_STATUSES = ("Pending", "In Progress", "Blocked")


def validate_plan_task_execute(
    conn: sqlite3.Connection,
    settings: tapl_config.PlanTaskExecuteConfig,
) -> dict[str, Any]:
    state = db.status_payload(conn)
    if not state.get("active_run"):
        return {
            "ok": True,
            "errors": [],
            "warnings": [],
            "issues": [],
            "guidance": guidance(settings),
        }

    plans = state.get("plans", [])
    tasks = state.get("tasks", [])
    issues: list[dict[str, Any]] = []
    issues.extend(validate_level_subagents(tasks, settings))
    issues.extend(validate_plan_detail(plans, settings))
    issues.extend(validate_task_granularity(plans, tasks, settings))
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
    required_subagent: str,
    settings: tapl_config.PlanTaskExecuteConfig,
) -> dict[str, Any]:
    task = {
        "stable_id": task_id,
        "status": status,
        "required_subagent": required_subagent,
    }
    issues = validate_level_subagents([task], settings)
    errors = [item for item in issues if item["severity"] == "error"]
    warnings = [item for item in issues if item["severity"] == "warning"]
    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "issues": issues,
        "guidance": guidance(settings),
    }


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
                "Create or update a plan with `taplctl plan upsert` before durable edits.",
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


def executable_tasks(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [task for task in tasks if task_status(task) in EXECUTABLE_STATUSES]


def task_status(task: dict[str, Any]) -> str:
    return str(task.get("status") or "")


def guidance(settings: tapl_config.PlanTaskExecuteConfig) -> dict[str, Any]:
    return {
        "allowed_level_subagents": list(LEVEL_SUBAGENTS),
        "level_subagent": level_subagent_guidance(settings),
        "plan_detail": plan_detail_guidance(settings.plan_detail),
        "task_granularity": task_granularity_guidance(settings.task_granularity),
    }


def level_subagent_guidance(settings: tapl_config.PlanTaskExecuteConfig) -> str:
    if not settings.use_level_subagent:
        return "Level subagent routing is disabled."
    if settings.level_subagent_aggressiveness == "minimal":
        return "Set a level subagent only for obvious risk or explicit routing."
    if settings.level_subagent_aggressiveness == "force":
        return "Every executable task must use @junior-worker, @senior-worker, or @specialist-worker."
    return "Choose a level subagent automatically based on task risk."


def plan_detail_guidance(value: str) -> str:
    return {
        "minimal": "Record objective, selected approach, affected files, and validation only.",
        "less_detailed": "Add constraints and risks only when they affect execution.",
        "detailed": "Include requirements trace, execution order, risks, and validation.",
        "very_detailed": "Expand edge cases, alternatives considered, and per-spec validation.",
    }[value]


def task_granularity_guidance(value: str) -> str:
    return {
        "minimal": "Use one executable task unless phases are truly separate.",
        "less_granular": "Split by major phase or owner boundary.",
        "granular": "Split by meaningful implementation and verification steps.",
        "very_granular": "Split every independent edit, migration, and verification step.",
    }[value]


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
