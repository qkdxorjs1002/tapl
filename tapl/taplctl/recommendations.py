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

    advisory_recommendations = advisory_selection_recommendations(plan_task_execute)
    run = state.get("active_run") if isinstance(state.get("active_run"), dict) else None
    if not run:
        queued = state.get("queued_runs") if isinstance(state.get("queued_runs"), list) else []
        if queued:
            return [
                recommendation(
                    "inspect-status",
                    "Queued split runs exist but none has satisfied dependencies; inspect waiting_on before continuing.",
                )
            ]
        return [
            recommendation(
                "classify-request",
                "Classify the prompt as one request or multiple independent requests before durable workflow work.",
            )
        ]

    if str(run.get("request_summary") or "") == db.DEFAULT_REQUEST_SUMMARY:
        return [
            recommendation(
                "classify-request",
                "The active run is fresh; split independent outcomes or summarize one cohesive request.",
            )
        ]

    plans = state.get("plans") if isinstance(state.get("plans"), list) else []
    tasks = state.get("tasks") if isinstance(state.get("tasks"), list) else []
    is_planning_scope = str(run.get("work_type") or "") == "planning"
    if not plans:
        if str(run.get("record_mode") or db.DEFAULT_RECORD_MODE) == "lightweight":
            if is_planning_scope:
                return [planning_confirmation_recommendation()]
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
                        "This run has a derived lightweight record_mode; complete the Fast non-durable work without plan/task "
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
        if is_planning_scope:
            return [planning_confirmation_recommendation()]
        return [
            recommendation(
                "decide-after-plan",
                (
                    "The plan has no executable tasks. Finish the run for analysis or reporting scope; "
                    "create a task only when execution was explicitly requested."
                ),
            )
        ]

    approval = (state.get("approvals") or {}).get(db.DEFAULT_APPROVAL_KIND) or {}
    if state.get("incomplete_tasks", 0) and approval.get("state") != "approved":
        return [
            recommendation(
                "approve-execution",
                "Executable tasks exist but execution approval is not recorded.",
            )
        ] + advisory_recommendations

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
            ] + advisory_recommendations
        return [
            recommendation(
                "complete-or-block-task",
                "A task is in progress; complete or block it before starting another.",
            ),
            recommendation(
                "block-task",
                "Use this if the current task cannot proceed.",
            ),
        ] + advisory_recommendations

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
            ] + advisory_recommendations
        return [
            recommendation(
                "start-task",
                "Start the next pending task with the high-level lifecycle command.",
            )
        ] + advisory_recommendations

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
        ] + advisory_recommendations

    return [
        recommendation(
            "inspect-status",
            "No single safe lifecycle command was inferred; inspect current state.",
        )
    ] + advisory_recommendations


def advisory_selection_recommendations(
    plan_task_execute: dict[str, Any],
) -> list[dict[str, str]]:
    """Surface advisory record gaps without changing the primary safe action."""

    issues = (
        plan_task_execute.get("issues")
        if isinstance(plan_task_execute, dict)
        and isinstance(plan_task_execute.get("issues"), list)
        else []
    )
    if not any(
        isinstance(item, dict)
        and str(item.get("severity") or "") == "warning"
        and str(item.get("code") or "").startswith("advisory_")
        for item in issues
    ):
        return []
    return [
        recommendation(
            "review-advisory-selection-context",
            (
                "Advisory profile or model-selection context has gaps; review validation warnings and record "
                "the missing rationale or profile details without treating them as execution blockers."
            ),
        )
    ]


def recommendation(name: str, reason: str) -> dict[str, str]:
    """Create the stable recommendation shape used by MCP adapters."""

    return {"name": name, "reason": reason}


def planning_confirmation_recommendation() -> dict[str, str]:
    """Keep planning-only work open until the user chooses its disposition."""

    return recommendation(
        "confirm-after-plan",
        (
            "Complete and report the requested planning scope, then use request_user_input to ask whether to keep "
            "the run active, proceed to execution, or finish and archive it. Do not finish or archive before the "
            "user chooses."
        ),
    )


def first_task_with_status(
    tasks: list[dict[str, Any]], statuses: tuple[str, ...]
) -> dict[str, Any] | None:
    """Return the first task matching any requested workflow status."""

    for task in tasks:
        if str(task.get("status") or "") in statuses:
            return task
    return None
