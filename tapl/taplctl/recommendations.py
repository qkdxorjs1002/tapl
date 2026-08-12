"""Pure state-to-recommendation helpers for TAPL workflow clients."""

from __future__ import annotations

from typing import Any

from . import db


def next_recommendations(
    state: dict[str, Any], plan_task_execute: dict[str, Any]
) -> list[dict[str, str]]:
    """Return the next safe workflow actions for a status payload.

    ``plan_task_execute`` remains part of the public function contract so all
    callers can supply the validation receipt alongside the state snapshot.
    Recommendations currently derive from the snapshot itself.
    """

    del plan_task_execute
    run = state.get("active_run") if isinstance(state.get("active_run"), dict) else None
    if not run:
        return [
            recommendation(
                "summarize-request",
                "Create or update the active request summary before durable workflow work.",
            )
        ]

    if str(run.get("request_summary") or "") == db.DEFAULT_REQUEST_SUMMARY:
        return [
            recommendation(
                "summarize-request",
                "The active run still has the default request summary.",
            )
        ]

    plans = state.get("plans") if isinstance(state.get("plans"), list) else []
    tasks = state.get("tasks") if isinstance(state.get("tasks"), list) else []
    if not plans:
        if str(run.get("workflow_mode") or db.DEFAULT_WORKFLOW_MODE) == "lightweight":
            if str(run.get("result_summary") or "").strip():
                return [
                    recommendation(
                        "archive-run",
                        "The lightweight result is recorded and ready to archive.",
                    )
                ]
            return [
                recommendation(
                    "finish-run",
                    (
                        "The agent selected a lightweight run; answer directly and finish it without plan/task "
                        "records, or apply a plan first if the work becomes complex or requires durable edits."
                    ),
                )
            ]
        return [
            recommendation(
                "apply-plan",
                "No plan exists for the active run; feed the plan JSON object on stdin.",
            )
        ]
    if not tasks:
        return [
            recommendation(
                "create-task",
                "No executable tasks exist; create the first task from a JSON object.",
            )
        ]

    approval = (state.get("approvals") or {}).get(db.DEFAULT_APPROVAL_KIND) or {}
    if state.get("incomplete_tasks", 0) and approval.get("state") != "approved":
        return [
            recommendation(
                "approve-execution",
                "Executable tasks exist but execution approval is not recorded.",
            )
        ]

    in_progress = first_task_with_status(tasks, ("In Progress",))
    if in_progress:
        parallel_in_progress = [
            task
            for task in tasks
            if task.get("status") == "In Progress"
            and task.get("execution_mode") == "parallel"
            and task.get("executor_kind") == "subagent"
        ]
        if parallel_in_progress:
            return [
                recommendation(
                    "settle-parallel-task",
                    (
                        "One or more parallel subagent tasks are active; use the exact "
                        "execution id from the dispatch manifest to prevent stale settlement."
                    ),
                ),
                recommendation(
                    "recover-parallel-batch",
                    "Use the dispatch manifest batch id if an interrupted batch must return to Pending.",
                ),
            ]
        return [
            recommendation(
                "complete-or-block-task",
                "A task is in progress; complete or block it before starting another.",
            ),
            recommendation(
                "block-task",
                "Use this if the current task cannot proceed.",
            ),
        ]

    pending = first_task_with_status(tasks, ("Pending",))
    if pending:
        parallel_groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for task in tasks:
            if (
                task.get("status") == "Pending"
                and task.get("execution_mode") == "parallel"
                and task.get("executor_kind") == "subagent"
                and str(task.get("parallel_group") or "").strip()
            ):
                key = (
                    str(task.get("spec_id") or ""),
                    str(task.get("parallel_group") or ""),
                )
                parallel_groups.setdefault(key, []).append(task)
        dispatchable = next(
            (group for group in parallel_groups.values() if len(group) >= 2),
            None,
        )
        if dispatchable:
            return [
                recommendation(
                    "dispatch-parallel-tasks",
                    (
                        "At least two Pending subagent tasks share a parallel group; "
                        "dispatch validates dependencies and owned paths atomically."
                    ),
                )
            ]
        return [
            recommendation(
                "start-task",
                "Start the next pending task with the high-level lifecycle command.",
            )
        ]

    if int(state.get("incomplete_tasks") or 0) == 0:
        return [
            recommendation(
                "finish-run",
                "All tasks are complete; record the final result before archiving.",
            ),
            recommendation(
                "archive-run",
                "Archive when no actionable tasks remain.",
            ),
        ]

    return [
        recommendation(
            "inspect-status",
            "No single safe lifecycle command was inferred; inspect current state.",
        )
    ]


def recommendation(name: str, reason: str) -> dict[str, str]:
    """Create the stable recommendation shape used by MCP adapters."""

    return {"name": name, "reason": reason}


def first_task_with_status(
    tasks: list[dict[str, Any]], statuses: tuple[str, ...]
) -> dict[str, Any] | None:
    """Return the first task matching any requested workflow status."""

    for task in tasks:
        if str(task.get("status") or "") in statuses:
            return task
    return None
