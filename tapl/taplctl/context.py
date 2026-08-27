"""Lifecycle context packets for tapl hooks and CLI output."""

from __future__ import annotations

import sqlite3
from typing import Any

from . import config as tapl_config, db, prompt as tapl_prompt, validation


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
    plan_task = validation.validate_plan_task_execute(conn)
    prompt = prompt_summary(payload or {})
    covered_issue_codes = covered_validation_issue_codes(state, plan_task)
    return {
        "ok": True,
        "event": event,
        "active_run": active_run_summary(state),
        "queued_runs": state.get("queued_runs", []),
        "counts": {
            "plans": len(state.get("plans", [])),
            "tasks": len(state.get("tasks", [])),
            "incomplete_tasks": state.get("incomplete_tasks", 0),
            "active_batches": len(state.get("active_batches", [])),
            "active_executions": len(state.get("active_executions", [])),
            "queued_runs": len(state.get("queued_runs", [])),
        },
        "active_batches": state.get("active_batches", []),
        "active_executions": state.get("active_executions", []),
        "config": settings.as_dict(),
        "plan_task_execute": plan_task,
        "instructions": instructions(event=event),
        "workflow_guidance": workflow_guidance(
            event=event,
            state=state,
            prompt=prompt,
            subagents=settings.subagents,
        ),
        "next_actions": next_actions(state, plan_task, event, prompt),
        "validation_issues": validation_issues(plan_task, covered_issue_codes),
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
    if counts.get("queued_runs"):
        queued_labels = ", ".join(
            str(item.get("split_key") or item.get("id") or "queued")
            for item in packet.get("queued_runs", [])
            if isinstance(item, dict)
        )
        lines.append(
            f"- Queue: {counts['queued_runs']} split run(s) waiting"
            f"{f' ({queued_labels})' if queued_labels else ''}."
        )

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
    validation_items = [
        str(item).strip() for item in packet.get("validation_issues", []) if str(item).strip()
    ]
    if validation_items:
        lines.append("")
        lines.append("## Validation Issues")
        for item in validation_items:
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
        return {
            "present": False,
            "request_summary": "",
            "result_summary": "",
            "work_type": "",
            "workflow_mode": "",
            "record_mode": "",
            "split_group_id": "",
            "split_key": "",
            "split_position": 0,
            "created_at": "",
        }
    return {
        "present": True,
        "request_summary": run.get("request_summary") or "",
        "result_summary": run.get("result_summary") or "",
        "work_type": run.get("work_type") or db.DEFAULT_WORK_TYPE,
        "workflow_mode": run.get("workflow_mode") or db.DEFAULT_WORKFLOW_MODE,
        "record_mode": run.get("record_mode") or db.DEFAULT_RECORD_MODE,
        "split_group_id": run.get("split_group_id") or "",
        "split_key": run.get("split_key") or "",
        "split_position": run.get("split_position") or 0,
        "created_at": run.get("created_at") or "",
    }


def instructions(*, event: str) -> list[str]:
    return []


def workflow_guidance(
    *,
    event: str,
    state: dict[str, Any],
    prompt: str = "",
    subagents: tapl_config.SubagentsConfig | None = None,
) -> list[str]:
    return tapl_prompt.context_workflow_guidance(
        event=event,
        state=state,
        prompt=prompt,
        subagents=subagents,
    )


def next_actions(
    state: dict[str, Any],
    plan_task: dict[str, Any],
    event: str,
    prompt: str = "",
) -> list[str]:
    actions: list[str] = []
    if event == "SessionStart":
        if state.get("incomplete_tasks", 0):
            actions.append(tapl_prompt.session_start_incomplete_next_action())
            execution_action = task_execution_next_action(state)
            if state.get("active_batches") and execution_action:
                actions.append(execution_action)
        return actions

    if not state.get("active_run"):
        queued = state.get("queued_runs") if isinstance(state.get("queued_runs"), list) else []
        if queued:
            actions.append(
                "Queued split runs are waiting on unfinished dependencies; inspect their waiting_on fields before new durable work."
            )
        else:
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
        if str(run.get("record_mode") or db.DEFAULT_RECORD_MODE) == "lightweight":
            if str(run.get("result_summary") or "").strip():
                actions.append(tapl_prompt.archive_lightweight_run_next_action())
            else:
                actions.append(tapl_prompt.lightweight_run_next_action())
        else:
            actions.append(tapl_prompt.create_plan_next_action())
    elif not has_tasks:
        actions.append(tapl_prompt.decide_after_plan_next_action())
    if state.get("incomplete_tasks", 0):
        approval_action = approval_next_action(plan_task)
        if approval_action:
            actions.append(approval_action)
        execution_action = task_execution_next_action(state)
        if execution_action:
            actions.append(execution_action)
        actions.append(tapl_prompt.stop_incomplete_tasks_next_action())
    return actions


def covered_validation_issue_codes(state: dict[str, Any], plan_task: dict[str, Any]) -> set[str]:
    codes: set[str] = set()
    if not state.get("active_run"):
        return codes
    run = state.get("active_run") if isinstance(state.get("active_run"), dict) else {}
    if (
        not state.get("plans")
        and str(run.get("record_mode") or db.DEFAULT_RECORD_MODE) != "lightweight"
    ):
        codes.add("missing_plan")
    if state.get("incomplete_tasks", 0):
        if approval_next_action(plan_task):
            codes.update({"execution_approval_missing", "execution_approval_rejected"})
        execution_action = task_execution_next_action(state)
        if execution_action:
            codes.add("multiple_tasks_in_progress")
    return codes


def validation_issues(
    plan_task: dict[str, Any],
    covered_issue_codes: set[str],
    *,
    max_items: int = 3,
) -> list[str]:
    items: list[str] = []
    for issue in plan_task.get("issues") or []:
        if not isinstance(issue, dict):
            continue
        if issue.get("code") in covered_issue_codes:
            continue
        message = str(issue.get("message") or "").strip()
        remediation = str(issue.get("remediation") or "").strip()
        if not message and not remediation:
            continue
        items.append(f"{message} {remediation}".strip())
        if len(items) >= max_items:
            break
    return items


def active_run_direction_next_action(state: dict[str, Any], prompt: str) -> str:
    tasks = state.get("tasks") if isinstance(state.get("tasks"), list) else []
    in_progress = [task for task in tasks if str(task.get("status") or "") == "In Progress"]
    if in_progress:
        active_batches = state.get("active_batches")
        if isinstance(active_batches, list) and active_batches:
            labels = ", ".join(task_label(task) for task in in_progress)
            return tapl_prompt.run_stopped_during_batch_next_action(labels)
        label = task_label(in_progress[0])
        return tapl_prompt.run_stopped_during_task_next_action(label)

    if state.get("incomplete_tasks", 0):
        return tapl_prompt.incomplete_run_next_action()

    if request_differs_from_active_run(state, prompt):
        return tapl_prompt.different_request_next_action()

    return ""


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
) -> str:
    tasks = state.get("tasks") if isinstance(state.get("tasks"), list) else []
    if not tasks:
        return ""

    active_batches = state.get("active_batches")
    if isinstance(active_batches, list) and active_batches:
        if len(active_batches) > 1:
            batch_ids = ", ".join(batch_id(payload) for payload in active_batches)
            return tapl_prompt.multiple_active_batches_next_action(batch_ids)
        payload = active_batches[0] if isinstance(active_batches[0], dict) else {}
        batch = payload.get("batch") if isinstance(payload.get("batch"), dict) else {}
        executions = payload.get("executions") if isinstance(payload.get("executions"), list) else []
        assignments = ", ".join(
            execution_assignment(execution)
            for execution in executions
            if isinstance(execution, dict)
        )
        return tapl_prompt.continue_parallel_batch_next_action(
            str(batch.get("batch_id") or batch.get("id") or "batch"),
            assignments or "no execution rows; recover this stale batch",
        )

    active_task_ids = {
        task_label(execution)
        for execution in (
            state.get("active_executions")
            if isinstance(state.get("active_executions"), list)
            else []
        )
        if isinstance(execution, dict)
    }
    missing_parallel_execution = [
        task
        for task in tasks
        if str(task.get("status") or "") == "In Progress"
        and str(task.get("execution_mode") or "sequential") == "parallel"
        and task_label(task) not in active_task_ids
    ]
    if missing_parallel_execution:
        labels = ", ".join(task_label(task) for task in missing_parallel_execution)
        return tapl_prompt.repair_missing_parallel_execution_next_action(labels)

    if execution_approved(state):
        dispatchable_sets = dispatchable_parallel_task_sets(state)
        if dispatchable_sets:
            labels = " ".join(task_label(task) for task in dispatchable_sets[0])
            return tapl_prompt.dispatch_parallel_tasks_next_action(labels)

    in_progress = [task for task in tasks if str(task.get("status") or "") == "In Progress"]
    if len(in_progress) > 1:
        labels = ", ".join(task_label(task) for task in in_progress)
        return tapl_prompt.multiple_in_progress_next_action(labels)
    if in_progress:
        task = in_progress[0]
        label = task_label(task)
        return tapl_prompt.continue_task_next_action(label)

    for task in tasks:
        status = str(task.get("status") or "")
        label = task_label(task)
        if status == "Pending":
            return tapl_prompt.start_task_next_action(label)
        if status == "Blocked":
            return tapl_prompt.resolve_blocked_task_next_action(label)
    return ""


def dispatchable_parallel_task_sets(state: dict[str, Any]) -> list[list[dict[str, Any]]]:
    tasks = state.get("tasks") if isinstance(state.get("tasks"), list) else []
    tasks_by_id = {task_label(task): task for task in tasks}
    active_executions = (
        state.get("active_executions")
        if isinstance(state.get("active_executions"), list)
        else []
    )
    active_paths = [
        path
        for execution in active_executions
        if isinstance(execution, dict)
        for path in owned_paths(execution)
    ]
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for task in tasks:
        if (
            str(task.get("status") or "") != "Pending"
            or str(task.get("execution_mode") or "sequential") != "parallel"
            or str(task.get("executor_kind") or "main") != "subagent"
        ):
            continue
        group = str(task.get("parallel_group") or "").strip()
        spec_id = str(task.get("spec_id") or "").strip()
        paths = owned_paths(task)
        dependencies = task.get("depends_on") if isinstance(task.get("depends_on"), list) else []
        if (
            not group
            or not paths
            or any(
                str(tasks_by_id.get(str(dependency), {}).get("status") or "") != "Completed"
                for dependency in dependencies
            )
            or any(db._owned_paths_overlap(path, active_path) for path in paths for active_path in active_paths)
        ):
            continue
        grouped.setdefault((spec_id, group), []).append(task)

    dispatchable: list[list[dict[str, Any]]] = []
    for members in grouped.values():
        if len(members) < 2 or group_has_owned_path_overlap(members):
            continue
        dispatchable.append(members)
    dispatchable.sort(key=lambda members: task_label(members[0]))
    return dispatchable


def group_has_owned_path_overlap(tasks: list[dict[str, Any]]) -> bool:
    for index, left in enumerate(tasks):
        for right in tasks[index + 1 :]:
            if any(
                db._owned_paths_overlap(left_path, right_path)
                for left_path in owned_paths(left)
                for right_path in owned_paths(right)
            ):
                return True
    return False


def owned_paths(task: dict[str, Any]) -> list[str]:
    try:
        return db.parse_owned_paths(task.get("owned_paths"))
    except ValueError:
        return []


def execution_approved(state: dict[str, Any]) -> bool:
    approval = (
        (state.get("approvals") or {}).get(db.DEFAULT_APPROVAL_KIND)
        if isinstance(state.get("approvals"), dict)
        else {}
    )
    return isinstance(approval, dict) and approval.get("state") == "approved"


def batch_id(payload: dict[str, Any]) -> str:
    batch = payload.get("batch") if isinstance(payload.get("batch"), dict) else {}
    return str(batch.get("batch_id") or batch.get("id") or "batch")


def execution_assignment(execution: dict[str, Any]) -> str:
    return (
        f"{task_label(execution)}={execution.get('execution_id') or 'missing-id'}"
        f"({execution.get('execution_state') or 'unknown'})"
    )


def task_label(task: dict[str, Any]) -> str:
    return str(task.get("stable_id") or task.get("task_id") or "task")


def prompt_summary(payload: dict[str, Any]) -> str:
    for key in ("prompt", "user_prompt", "message"):
        value = payload.get(key)
        if isinstance(value, str):
            return value.strip()[:240]
    return ""
