"""Lifecycle context packets for tapl hooks and CLI output."""

from __future__ import annotations

import sqlite3
from typing import Any

from . import config as tapl_config, db, prompt as tapl_prompt, validation


def taplctl_execution_guidance() -> str:
    return tapl_prompt.taplctl_execution_guidance()


def taplctl_command_guidance() -> str:
    return tapl_prompt.taplctl_command_guidance()


def external_findings_guidance() -> str:
    return tapl_prompt.external_findings_guidance()


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
    guidance = [str(item).strip() for item in packet.get("workflow_guidance", []) if str(item).strip()]
    if guidance:
        lines.append("")
        lines.extend(guidance_lines(guidance))
    next_actions = [str(item).strip() for item in packet["next_actions"] if str(item).strip()]
    if next_actions:
        lines.append("")
        lines.append("## Next Actions")
        for item in next_actions:
            lines.append(f"- {item}")
    return "\n".join(lines)


def guidance_lines(items: list[str]) -> list[str]:
    lines: list[str] = []
    for index, item in enumerate(items):
        if index:
            lines.append("")
        if "\n" in item or item.lstrip().startswith("#"):
            lines.append(item)
        else:
            lines.append(f"- {item}")
    return lines


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
    return []


def workflow_guidance(
    settings: tapl_config.PlanTaskExecuteConfig,
    *,
    event: str,
    state: dict[str, Any],
    prompt: str = "",
) -> list[str]:
    return tapl_prompt.context_workflow_guidance(
        settings,
        event=event,
        state=state,
        prompt=prompt,
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
    stage_intent = workflow_stage_intent(state, prompt)
    if event == "SessionStart":
        if state.get("incomplete_tasks", 0):
            actions.append(tapl_prompt.session_start_incomplete_next_action())
        return actions

    if not state.get("active_run"):
        actions.append("Create an active workflow run before durable work.")
        return actions

    run = state.get("active_run") if isinstance(state.get("active_run"), dict) else {}
    if run.get("request_summary") == db.DEFAULT_REQUEST_SUMMARY:
        actions.append(tapl_prompt.summarize_request_next_action())
    if event == "UserPromptSubmit":
        direction_action = active_run_direction_next_action(state, prompt)
        if direction_action:
            actions.append(direction_action)
    has_plans = bool(state.get("plans"))
    has_tasks = bool(state.get("tasks"))
    if not has_plans:
        actions.append(tapl_prompt.create_plan_next_action())
        covered_issue_codes.add("missing_plan")
    elif not has_tasks:
        if stage_intent == "plan_only":
            actions.append(tapl_prompt.plan_only_next_action())
        elif stage_intent == "plan_then_ask":
            actions.append(tapl_prompt.ask_after_plan_next_action())
        else:
            actions.append(tapl_prompt.create_tasks_next_action())
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
        actions.append(tapl_prompt.stop_incomplete_tasks_next_action())

    for issue in (plan_task.get("issues") or [])[:3]:
        if issue.get("code") in covered_issue_codes:
            continue
        actions.append(f"{issue['message']} {issue['remediation']}")
    return actions


def active_run_direction_next_action(state: dict[str, Any], prompt: str) -> str:
    tasks = state.get("tasks") if isinstance(state.get("tasks"), list) else []
    in_progress = [task for task in tasks if str(task.get("status") or "") == "In Progress"]
    if in_progress:
        label = task_label(in_progress[0])
        return tapl_prompt.run_stopped_during_task_next_action(label)

    if state.get("incomplete_tasks", 0):
        return tapl_prompt.incomplete_run_next_action()

    if request_differs_from_active_run(state, prompt):
        return tapl_prompt.different_request_next_action()

    return ""


def workflow_stage_intent(state: dict[str, Any], prompt: str) -> str:
    run = state.get("active_run") if isinstance(state.get("active_run"), dict) else {}
    text = prompt.strip() or str(run.get("request_summary") or "").strip()
    if not text or text == db.DEFAULT_REQUEST_SUMMARY:
        return "auto"

    normalized = normalized_prompt(text)
    has_plan_term = contains_any(normalized, ("계획", "플랜", "설계", "plan", "planning"))
    if not has_plan_term:
        return "auto"

    plan_only_markers = (
        "계획만",
        "계획 까지만",
        "계획까지만",
        "플랜만",
        "설계만",
        "plan only",
        "planning only",
        "only plan",
        "only planning",
    )
    if contains_any(normalized, plan_only_markers):
        return "plan_only"

    execution_markers = (
        "구현",
        "수정",
        "반영",
        "적용",
        "고쳐",
        "고치",
        "테스트",
        "검증",
        "실행",
        "실제 동작",
        "implement",
        "implementation",
        "fix",
        "edit",
        "modify",
        "test",
        "verify",
        "execute",
        "execution",
    )
    if contains_any(normalized, execution_markers):
        return "explicit_execution"

    return "plan_then_ask"


def contains_any(value: str, needles: tuple[str, ...]) -> bool:
    return any(needle in value for needle in needles)


def request_differs_from_active_run(state: dict[str, Any], prompt: str) -> bool:
    run = state.get("active_run") if isinstance(state.get("active_run"), dict) else {}
    request_summary = str(run.get("request_summary") or "").strip()
    if not prompt.strip():
        return False

    has_records = bool(state.get("plans") or state.get("tasks") or state.get("findings"))
    if not has_records:
        return False

    if not request_summary or request_summary == db.DEFAULT_REQUEST_SUMMARY:
        return False

    return normalized_prompt(prompt) != normalized_prompt(request_summary)


def normalized_prompt(value: str) -> str:
    return " ".join(value.split()).casefold()


def approval_next_action(plan_task: dict[str, Any]) -> str:
    issues = plan_task.get("issues") if isinstance(plan_task.get("issues"), list) else []
    codes = {str(issue.get("code") or "") for issue in issues if isinstance(issue, dict)}
    if "execution_approval_rejected" in codes:
        return tapl_prompt.approval_rejected_next_action()
    if "execution_approval_missing" in codes:
        return tapl_prompt.approval_missing_next_action()
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
        return tapl_prompt.multiple_in_progress_next_action(labels)
    if in_progress:
        task = in_progress[0]
        label = task_label(task)
        assignment = subagent_assignment_guidance(task, settings)
        return tapl_prompt.continue_task_next_action(label, assignment)

    for task in tasks:
        status = str(task.get("status") or "")
        label = task_label(task)
        if status == "Pending":
            assignment = subagent_assignment_guidance(task, settings)
            return tapl_prompt.start_task_next_action(label, assignment)
        if status == "Blocked":
            return tapl_prompt.resolve_blocked_task_next_action(label)
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
    return tapl_prompt.subagent_assignment_next_action(required)


def task_label(task: dict[str, Any]) -> str:
    return str(task.get("stable_id") or task.get("task_id") or "task")


def prompt_summary(payload: dict[str, Any]) -> str:
    for key in ("prompt", "user_prompt", "message"):
        value = payload.get(key)
        if isinstance(value, str):
            return value.strip()[:240]
    return ""
