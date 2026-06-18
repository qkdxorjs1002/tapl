"""Lifecycle context packets for tapl hooks and CLI output."""

from __future__ import annotations

import sqlite3
from typing import Any

from . import config as tapl_config, db, validation


def taplctl_execution_guidance() -> str:
    return (
        "Use the literal global `taplctl` command; keep workflow DB/config repo-local."
    )


def taplctl_argument_guidance() -> str:
    return (
        "When composing taplctl shell commands, quote every argument that contains spaces, "
        "newlines, or shell metacharacters; always write multi-word statuses as "
        "`--status 'In Progress'` or `--status \"In Progress\"`, never `--status In Progress`."
    )


def taplctl_command_guidance() -> str:
    return (
        "Inspect state with `taplctl status --json`; search with one quoted query: "
        "`taplctl search '<query>' --json`."
    )


def taplctl_help_guidance() -> str:
    return (
        "For command syntax, run `taplctl <command> <subcommand> --help`."
    )


def external_findings_guidance() -> str:
    return (
        "Findings: if external search/docs changed requirements, plan, tasks, or verification, "
        "add only decision-relevant facts with `taplctl finding add`. "
        f"{validation.markdown_record_guidance('finding details and impact')}"
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
    prompt = prompt_summary(payload or {})
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
        "workflow_guidance": workflow_guidance(
            settings.plan_task_execute,
            event=event,
            state=state,
            prompt=prompt,
        ),
        "next_actions": next_actions(state, plan_task, event, prompt),
        "prompt_summary": prompt,
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

    for item in packet.get("instructions", []):
        lines.append(f"- {item}")
    for item in packet.get("workflow_guidance", []):
        lines.append(f"- {item}")
    for item in packet["next_actions"]:
        lines.append(f"- Next: {item}")
    return "\n".join(lines)


def active_run_summary(state: dict[str, Any]) -> dict[str, Any]:
    run = state.get("active_run")
    if not run:
        return {"present": False, "request_summary": "", "result_summary": "", "created_at": ""}
    return {
        "present": True,
        "request_summary": run.get("request_summary") or "",
        "result_summary": run.get("result_summary") or "",
        "created_at": run.get("created_at") or "",
    }


def instructions(settings: tapl_config.PlanTaskExecuteConfig, *, event: str) -> list[str]:
    base = [
        "Use repo-local tapl DB state; write tapl records in the user's language.",
        taplctl_command_guidance(),
    ]

    if event == "SessionStart":
        return [
            *base,
            "SessionStart is bootstrap only; wait for a concrete user request before creating plan/task records.",
            taplctl_execution_guidance(),
        ]

    if event == "UserPromptSubmit":
        return [
            *base,
            taplctl_help_guidance(),
        ]

    if event == "Stop":
        return [
            *base,
            "Before stopping, set the result and finish, block, or skip tasks so archive state is accurate.",
        ]

    return [
        *base,
        taplctl_execution_guidance(),
    ]


def workflow_guidance(
    settings: tapl_config.PlanTaskExecuteConfig,
    *,
    event: str,
    state: dict[str, Any],
    prompt: str = "",
) -> list[str]:
    lines = [
        "Flow: search relevant prior work -> summarize request -> plan set -> plan-based task design -> task set -> approval set -> execute/update -> result/archive.",
    ]

    if event == "SessionStart":
        return lines

    if event == "Stop":
        lines.append("Stop: set result, leave no actionable task unmarked, then archive completed work.")
        return lines

    if event == "UserPromptSubmit":
        if should_suggest_prior_search(state, prompt):
            lines.append(
                "Search: before planning non-trivial work, run `taplctl search '<compact prompt query>' --json` and use only relevant results."
            )
        lines.extend(plan_task_context_guidance(settings))
        lines.append(external_findings_guidance())
        return lines

    lines.extend(plan_task_context_guidance(settings))
    return lines


def should_suggest_prior_search(state: dict[str, Any], prompt: str) -> bool:
    if not prompt.strip():
        return False
    if state.get("plans") or state.get("tasks"):
        return False
    return True


def plan_task_context_guidance(settings: tapl_config.PlanTaskExecuteConfig) -> list[str]:
    guidance = [
        f"Records: {validation.markdown_record_guidance()}",
        f"Order: {validation.workflow_order_guidance()}",
        f"Plan: {validation.plan_detail_guidance(settings.plan_detail)} Ask the user to choose when scope, risk, API, UX, data, or compatibility decisions matter.",
        f"Tasks: {validation.task_plan_dependency_guidance()} {validation.task_granularity_guidance(settings.task_granularity)} {validation.task_execution_order_guidance()} {validation.task_format_guidance(settings)}",
        validation.agent_writer_contract_guidance(),
    ]
    if settings.use_level_subagent:
        guidance.append(f"Subagents: {subagent_context_guidance(settings)}")
    if settings.require_execution_approval:
        guidance.append("Approval: before durable edits, set execution approval with `taplctl approval set --decision approved --prompt '<approved scope>' --json`.")
    else:
        guidance.append("Approval: set execution approval when risk or scope warrants it; missing approval is reported as a warning.")
    return guidance


def subagent_context_guidance(settings: tapl_config.PlanTaskExecuteConfig) -> str:
    allowed = ", ".join(validation.LEVEL_SUBAGENTS)
    if settings.level_subagent_aggressiveness == "minimal":
        return f"Set required_subagent only for clear risk or explicit routing. Allowed: {allowed}."
    if settings.level_subagent_aggressiveness == "force":
        return f"Every executable task needs required_subagent. Allowed: {allowed}."
    return f"Choose required_subagent by task risk. Allowed: {allowed}."


def next_actions(state: dict[str, Any], plan_task: dict[str, Any], event: str, prompt: str = "") -> list[str]:
    actions: list[str] = []
    covered_issue_codes: set[str] = set()
    if event == "SessionStart":
        if state.get("incomplete_tasks", 0):
            actions.append("After the user request, resume or update the incomplete task state before new durable edits.")
        return actions

    if not state.get("active_run"):
        actions.append("Create an active workflow run before durable work.")
        return actions

    run = state.get("active_run") if isinstance(state.get("active_run"), dict) else {}
    if run.get("request_summary") == db.DEFAULT_REQUEST_SUMMARY:
        actions.append(
            "Summarize the user's request and update the active run with `taplctl run set --summary '<request summary>' --json`."
        )
    if event == "UserPromptSubmit" and state.get("incomplete_tasks", 0):
        actions.append(
            "If this is a new request, ask whether to finish, combine, defer/archive, or discard remaining work before durable edits."
        )
    has_plans = bool(state.get("plans"))
    has_tasks = bool(state.get("tasks"))
    if not has_plans:
        actions.append("Create or update plan state with `taplctl plan set` before task design.")
        covered_issue_codes.add("missing_plan")
    elif not has_tasks:
        actions.append(
            "Using the stored plan, design executable tasks and create task state with `taplctl task set` before durable edits."
        )
    if state.get("incomplete_tasks", 0):
        execution_action = task_execution_next_action(state)
        if execution_action:
            actions.append(execution_action)
        actions.append("Complete, block, or skip remaining tasks before Stop can auto-archive.")

    for issue in (plan_task.get("issues") or [])[:3]:
        if issue.get("code") in covered_issue_codes:
            continue
        actions.append(f"{issue['message']} {issue['remediation']}")
    return actions


def task_execution_next_action(state: dict[str, Any]) -> str:
    tasks = state.get("tasks") if isinstance(state.get("tasks"), list) else []
    if not tasks:
        return ""

    in_progress = [task for task in tasks if str(task.get("status") or "") == "In Progress"]
    if len(in_progress) > 1:
        labels = ", ".join(task_label(task) for task in in_progress)
        return f"Only one task may be In Progress at a time; finish, block, or skip all but the earliest task before continuing: {labels}."
    if in_progress:
        label = task_label(in_progress[0])
        return f"Continue only {label}; update it to Completed, Blocked, or Skipped before starting another task."

    for task in tasks:
        status = str(task.get("status") or "")
        label = task_label(task)
        if status == "Pending":
            return f"Start next task {label} by updating it to In Progress immediately before execution."
        if status == "Blocked":
            return f"Resolve, replan, or skip blocked task {label} before starting later tasks."
    return ""


def task_label(task: dict[str, Any]) -> str:
    return str(task.get("stable_id") or task.get("task_id") or "task")


def prompt_summary(payload: dict[str, Any]) -> str:
    for key in ("prompt", "user_prompt", "message"):
        value = payload.get(key)
        if isinstance(value, str):
            return value.strip()[:240]
    return ""
