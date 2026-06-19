"""Lifecycle context packets for tapl hooks and CLI output."""

from __future__ import annotations

import sqlite3
from typing import Any

from . import config as tapl_config, db, validation


def taplctl_execution_guidance() -> str:
    return (
        "Use literal global `taplctl`; keep workflow DB/config repo-local."
    )


def taplctl_argument_guidance() -> str:
    return (
        "When composing taplctl shell commands, quote every argument that contains spaces, "
        "newlines, or shell metacharacters; always write multi-word statuses as "
        "`--status 'In Progress'` or `--status \"In Progress\"`, never `--status In Progress`."
    )


def taplctl_command_guidance() -> str:
    return (
        "Inspect/search: `taplctl status --json`; `taplctl search '<query>' --json`."
    )


def taplctl_help_guidance() -> str:
    return (
        "Syntax: `taplctl <command> <subcommand> --help`."
    )


def external_findings_guidance() -> str:
    return (
        "Findings: if external search/docs changes requirements/plan/tasks/verification, "
        "add decision-relevant facts with `taplctl finding add`; Markdown form for details/impact."
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
        "next_actions": next_actions(state, plan_task, event, prompt, settings.plan_task_execute),
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
        lines.append(
            f"- State: {summary}; plans={counts['plans']}, tasks={counts['tasks']}, "
            f"incomplete={counts['incomplete_tasks']}."
        )
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
        "Use repo-local tapl DB; write records in the user's language.",
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
        "Records: Markdown form for multi-line content; Use numeric stable ids only: "
        "PLAN-001/SPEC-001, TASK-001; no word suffixes.",
        "Order: Phase order: plan with user -> `taplctl plan set`; derive tasks from stored plan -> "
        "`taplctl task set`.",
        plan_context_guidance(settings),
        task_context_guidance(settings),
        "Agent contract: main agent writes plan/task records and final status; subagents may draft/execute only.",
    ]
    if settings.use_level_subagent:
        guidance.append(f"Subagents: {subagent_context_guidance(settings)}")
    if settings.require_execution_approval:
        guidance.append("Approval: set execution approval before durable edits: `taplctl approval set --decision approved --prompt '<approved scope>' --json`.")
    else:
        guidance.append("Approval: set execution approval for material risk/scope; missing approval is a warning.")
    return guidance


def plan_context_guidance(settings: tapl_config.PlanTaskExecuteConfig) -> str:
    detail = {
        "minimal": "objective, approach, affected files, validation",
        "less_detailed": "objective, approach, constraints, affected files, risks, validation",
        "detailed": "requirements trace, execution order, risks, validation",
        "very_detailed": "requirements trace, execution order, risks, edge cases, alternatives, per-spec validation",
    }[settings.plan_detail]
    return (
        f"Plan: include {detail}; {validation.plan_key_label_guidance()} "
        f"{validation.planning_approval_guidance(settings.planning_approval_level)}"
    )


def task_context_guidance(settings: tapl_config.PlanTaskExecuteConfig) -> str:
    fields = "spec_id, goal, action, "
    if settings.use_level_subagent and settings.level_subagent_aggressiveness != "minimal":
        fields += "required_subagent, "
    fields += "verification, result"
    subagent_note = ""
    if settings.use_level_subagent and settings.level_subagent_aggressiveness == "minimal":
        subagent_note = " Use required_subagent only for explicit subagent routing."
    return (
        "Tasks: after source plan exists, set --spec-id PLAN-001/SPEC-001; split by meaningful "
        "implementation/verification; Execute planned tasks one at a time in order: In Progress "
        f"before work, then Completed/Blocked/Skipped; fields: {fields}; "
        "blocked: blocker, next_action; updates are partial."
        f"{subagent_note}"
    )


def subagent_context_guidance(settings: tapl_config.PlanTaskExecuteConfig) -> str:
    allowed = ", ".join(validation.LEVEL_SUBAGENTS)
    if settings.level_subagent_aggressiveness == "minimal":
        return (
            "Set required_subagent only for clear risk/routing; it is routing metadata. "
            "If set, mark the task In Progress before work; spawn that exact subagent only when the "
            "subagent tool is available and user/session policy allows delegation; otherwise do not claim "
            f"delegation occurred; main records result/status. Allowed: {allowed}."
        )
    if settings.level_subagent_aggressiveness == "force":
        return (
            "Every executable task needs required_subagent in the task creation command; treat it as routing metadata. "
            "mark In Progress before work; spawn that exact subagent only when the subagent tool is available and "
            f"user/session policy allows delegation; otherwise do not claim delegation occurred; main records result/status. Allowed: {allowed}."
        )
    return (
        "Choose required_subagent by task risk/config in the same command that creates each executable task; "
        "treat it as routing metadata; mark In Progress before work; spawn that exact subagent only when the "
        "subagent tool is available and user/session policy allows delegation; otherwise do not claim delegation "
        f"occurred; main records result/status. Allowed: {allowed}."
    )


def next_actions(
    state: dict[str, Any],
    plan_task: dict[str, Any],
    event: str,
    prompt: str = "",
    settings: tapl_config.PlanTaskExecuteConfig | None = None,
) -> list[str]:
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
            "Summarize request: `taplctl run set --summary '<request summary>' --json`."
        )
    if event == "UserPromptSubmit" and should_request_active_run_direction(state, prompt):
        actions.append(
            "If this request is different from the open run, get user approval before durable edits: "
            "finish existing work first, defer the existing run, or merge the work into one plan."
        )
    has_plans = bool(state.get("plans"))
    has_tasks = bool(state.get("tasks"))
    if not has_plans:
        actions.append("Create or update plan state with `taplctl plan set` before task design.")
        covered_issue_codes.add("missing_plan")
    elif not has_tasks:
        actions.append(
            "Using the stored plan, create executable tasks with `taplctl task set` before durable edits."
        )
    if state.get("incomplete_tasks", 0):
        approval_action = approval_next_action(plan_task)
        if approval_action:
            actions.append(approval_action)
            covered_issue_codes.update({"execution_approval_missing", "execution_approval_rejected"})
        execution_action = task_execution_next_action(
            state,
            settings or tapl_config.PlanTaskExecuteConfig(),
        )
        if execution_action:
            actions.append(execution_action)
        actions.append("Complete, block, or skip remaining tasks before Stop auto-archives.")

    for issue in (plan_task.get("issues") or [])[:3]:
        if issue.get("code") in covered_issue_codes:
            continue
        actions.append(f"{issue['message']} {issue['remediation']}")
    return actions


def should_request_active_run_direction(state: dict[str, Any], prompt: str) -> bool:
    if state.get("incomplete_tasks", 0):
        return True

    run = state.get("active_run") if isinstance(state.get("active_run"), dict) else {}
    request_summary = str(run.get("request_summary") or "").strip()
    if not prompt.strip():
        return False

    has_records = bool(state.get("plans") or state.get("tasks") or state.get("findings"))
    if has_records:
        return True

    if not request_summary or request_summary == db.DEFAULT_REQUEST_SUMMARY:
        return False

    return normalized_prompt(prompt) != normalized_prompt(request_summary)


def normalized_prompt(value: str) -> str:
    return " ".join(value.split()).casefold()


def approval_next_action(plan_task: dict[str, Any]) -> str:
    issues = plan_task.get("issues") if isinstance(plan_task.get("issues"), list) else []
    codes = {str(issue.get("code") or "") for issue in issues if isinstance(issue, dict)}
    if "execution_approval_rejected" in codes:
        return (
            "Approval rejected; resolve scope, then set `taplctl approval set --decision approved "
            "--prompt '<approved scope>' --json` before continuing."
        )
    if "execution_approval_missing" in codes:
        return (
            "Before task execution, set execution approval: `taplctl approval set --decision approved "
            "--prompt '<approved scope>' --json`."
        )
    return ""


def task_execution_next_action(
    state: dict[str, Any],
    settings: tapl_config.PlanTaskExecuteConfig,
) -> str:
    tasks = state.get("tasks") if isinstance(state.get("tasks"), list) else []
    if not tasks:
        return ""

    in_progress = [task for task in tasks if str(task.get("status") or "") == "In Progress"]
    if len(in_progress) > 1:
        labels = ", ".join(task_label(task) for task in in_progress)
        return f"Only one task may be In Progress; finish/block/skip all but earliest: {labels}."
    if in_progress:
        task = in_progress[0]
        label = task_label(task)
        assignment = subagent_assignment_guidance(task, settings)
        route = f" {assignment};" if assignment else ""
        return f"Continue only {label};{route} set Completed, Blocked, or Skipped before another task."

    for task in tasks:
        status = str(task.get("status") or "")
        label = task_label(task)
        if status == "Pending":
            assignment = subagent_assignment_guidance(task, settings)
            route = f"; {assignment}" if assignment else ""
            return f"Start next task {label}: set In Progress immediately before execution{route}."
        if status == "Blocked":
            return f"Resolve, replan, or skip blocked task {label} before later tasks."
    return ""


def subagent_assignment_guidance(
    task: dict[str, Any],
    settings: tapl_config.PlanTaskExecuteConfig,
) -> str:
    if not settings.use_level_subagent:
        return ""
    required = str(task.get("required_subagent") or "").strip()
    if not required:
        return ""
    return (
        f"if subagent delegation is available and allowed, spawn {required} for only this task; "
        "otherwise do not claim delegation occurred"
    )


def task_label(task: dict[str, Any]) -> str:
    return str(task.get("stable_id") or task.get("task_id") or "task")


def prompt_summary(payload: dict[str, Any]) -> str:
    for key in ("prompt", "user_prompt", "message"):
        value = payload.get(key)
        if isinstance(value, str):
            return value.strip()[:240]
    return ""
