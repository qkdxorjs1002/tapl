"""Lifecycle context packets for tapl hooks and CLI output."""

from __future__ import annotations

import sqlite3
from typing import Any

from . import config as tapl_config, db, validation


def taplctl_execution_guidance() -> str:
    return (
        "Assume `taplctl` is installed as a user-global command; type the literal "
        "`taplctl` for workflow CLI calls, never `$taplctl`, repo-local paths, "
        "`.venv/bin/taplctl`, or `tapl_hook.py`; configure hooks with "
        "`taplctl install user` or `taplctl install repo`, and keep workflow "
        "DB/config in the current repo workspace."
    )


def taplctl_argument_guidance() -> str:
    return (
        "When composing taplctl shell commands, quote every argument that contains spaces, "
        "newlines, or shell metacharacters; always write multi-word statuses as "
        "`--status 'In Progress'` or `--status \"In Progress\"`, never `--status In Progress`."
    )


def taplctl_command_guidance() -> str:
    return (
        "Use `taplctl status --json` for state. Search takes one query argument: "
        "`taplctl search '<query>' --json`, not separate unquoted words."
    )


def build_context(
    conn: sqlite3.Connection,
    *,
    event: str,
    settings: tapl_config.TaplConfig,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    state = db.status_payload(conn)
    plan_task = validation.validate_plan_task_execute(conn, settings.plan_task_execute)
    return {
        "ok": True,
        "event": event,
        "active_run": active_run_summary(state),
        "counts": {
            "plans": len(state.get("plans", [])),
            "tasks": len(state.get("tasks", [])),
            "incomplete_tasks": state.get("incomplete_tasks", 0),
        },
        "config": settings.as_dict(),
        "plan_task_execute": plan_task,
        "instructions": instructions(settings.plan_task_execute, event=event),
        "next_actions": next_actions(state, plan_task, event),
        "prompt_summary": prompt_summary(payload or {}),
    }


def format_context(packet: dict[str, Any]) -> str:
    run = packet["active_run"]
    counts = packet["counts"]
    lines = [
        "tapl context:",
    ]
    if run["present"]:
        summary = f"active run: {run['request_summary']}" if run["request_summary"] else "active run present"
        lines.append(f"- State: {summary}; {counts['plans']} plan(s), {counts['tasks']} task(s), {counts['incomplete_tasks']} incomplete.")
    else:
        lines.append("- State: no active run.")

    for item in packet["instructions"]:
        lines.append(f"- {item}")
    for item in packet["next_actions"]:
        lines.append(f"- Next: {item}")
    return "\n".join(lines)


def active_run_summary(state: dict[str, Any]) -> dict[str, Any]:
    run = state.get("active_run")
    if not run:
        return {"present": False, "request_summary": "", "created_at": ""}
    return {
        "present": True,
        "request_summary": run.get("request_summary") or "",
        "created_at": run.get("created_at") or "",
    }


def instructions(settings: tapl_config.PlanTaskExecuteConfig, *, event: str) -> list[str]:
    allowed_subagents = ", ".join(validation.LEVEL_SUBAGENTS)
    task_statuses = "Pending, In Progress, Completed, Blocked, Skipped"
    base = [
        "Use SQLite state, hook feedback, and the global taplctl command as the workflow source of truth.",
        taplctl_command_guidance(),
    ]

    if event == "SessionStart":
        return [
            *base,
            "SessionStart is bootstrap context; wait for the user's concrete request before creating new plan/task records.",
            taplctl_execution_guidance(),
            f"Task statuses: {task_statuses}. Required subagents: {allowed_subagents}.",
        ]

    if event == "UserPromptSubmit":
        return [
            *base,
            "For non-trivial work, inspect state/search first, then upsert a plan and executable tasks before durable edits.",
            taplctl_argument_guidance(),
            f"Required subagents must be one of: {allowed_subagents}. Do not use level names such as `level2`.",
            "Keep task status current and write tapl records in the user's language unless asked otherwise.",
            f"Plan detail: {validation.plan_detail_guidance(settings.plan_detail)}",
            f"Task splitting: {validation.task_granularity_guidance(settings.task_granularity)}",
        ]

    return [
        *base,
        "No separate agent guide is required; lifecycle hooks provide tapl operating context.",
        taplctl_execution_guidance(),
        taplctl_argument_guidance(),
        "For non-trivial work, inspect state/search, record plan state, record executable tasks, then keep task status current.",
        "Write plan, task, finding, and archive text in the user's language unless asked otherwise.",
        f"Plan detail: {validation.plan_detail_guidance(settings.plan_detail)}",
        f"Task splitting: {validation.task_granularity_guidance(settings.task_granularity)}",
        f"Level subagent routing: {validation.level_subagent_guidance(settings)}",
    ]


def next_actions(state: dict[str, Any], plan_task: dict[str, Any], event: str) -> list[str]:
    actions: list[str] = []
    covered_issue_codes: set[str] = set()
    if event == "SessionStart":
        if state.get("incomplete_tasks", 0):
            actions.append("After the user request, resume or update the incomplete task state before new durable edits.")
        return actions

    if not state.get("active_run"):
        actions.append("Create an active workflow run before durable work.")
        return actions

    if not state.get("plans"):
        actions.append("Create or update plan state with `taplctl plan upsert`.")
        covered_issue_codes.add("missing_plan")
    if not state.get("tasks"):
        actions.append("Create executable task state with `taplctl task upsert` before durable edits.")
    if state.get("incomplete_tasks", 0):
        actions.append("Complete, block, or skip remaining tasks before archiving.")
    if state.get("tasks") and not state.get("incomplete_tasks", 0) and event == "Stop":
        actions.append("Archive completed work with `taplctl archive create`.")

    for issue in (plan_task.get("issues") or [])[:3]:
        if issue.get("code") in covered_issue_codes:
            continue
        actions.append(f"{issue['message']} {issue['remediation']}")
    return actions


def prompt_summary(payload: dict[str, Any]) -> str:
    for key in ("prompt", "user_prompt", "message"):
        value = payload.get(key)
        if isinstance(value, str):
            return value.strip()[:240]
    return ""
