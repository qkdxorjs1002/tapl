"""Plan/task validation driven by TAPL's adaptive workflow policy."""

from __future__ import annotations

import re
import sqlite3
from typing import Any

from . import db, prompt as tapl_prompt


EXECUTABLE_STATUSES = ("Pending", "In Progress", "Blocked")
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

    run = state.get("active_run") if isinstance(state.get("active_run"), dict) else {}
    record_mode = str(run.get("record_mode") or db.DEFAULT_RECORD_MODE)
    plans = state.get("plans", [])
    tasks = state.get("tasks", [])
    issues: list[dict[str, Any]] = []
    issues.extend(validate_stable_ids(plans, tasks))
    issues.extend(validate_plan_detail(plans, required=record_mode != "lightweight"))
    issues.extend(validate_plan_content(plans))
    issues.extend(validate_task_granularity(plans, tasks))
    issues.extend(validate_task_content(tasks))
    issues.extend(validate_task_planning_contract(tasks))
    issues.extend(validate_task_dependencies(tasks))
    issues.extend(validate_owned_path_exclusivity(state, tasks))
    issues.extend(validate_execution_state(state, tasks))
    issues.extend(validate_task_execution_order(tasks, state))
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


def validate_plan_detail(
    plans: list[dict[str, Any]],
    *,
    required: bool = True,
) -> list[dict[str, Any]]:
    if not plans and not required:
        return []
    if not plans:
        return [
            issue(
                "error",
                "missing_plan",
                "Planned runs require a plan record before task execution.",
                tapl_prompt.missing_plan_remediation(),
            )
        ]
    return []


def validate_task_granularity(
    plans: list[dict[str, Any]],
    tasks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Accept coherent task bundles; depth is selected by the workflow policy.

    A task may cover a tightly coupled implementation and its verification.  The
    remaining validators still enforce task identifiers, content, dependencies,
    execution contracts, and approval before execution.
    """

    del plans, tasks
    return []


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


def validate_task_planning_contract(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    parallel_groups: dict[str, list[dict[str, Any]]] = {}
    for task in tasks:
        label = task_label(task)
        mode = str(task.get("execution_mode") or "sequential")
        executor = str(task.get("executor_kind") or "main")
        group = str(task.get("parallel_group") or "").strip()
        owned_paths = task_owned_paths(task)

        if mode not in db.EXECUTION_MODES:
            issues.append(
                issue(
                    "error",
                    "invalid_task_execution_mode",
                    f"{label} has invalid execution_mode `{mode}`.",
                    tapl_prompt.parallel_task_contract_remediation(),
                    stable_id=label,
                )
            )
            continue
        if executor not in db.EXECUTOR_KINDS:
            issues.append(
                issue(
                    "error",
                    "invalid_task_executor_kind",
                    f"{label} has invalid executor_kind `{executor}`.",
                    tapl_prompt.parallel_task_contract_remediation(),
                    stable_id=label,
                )
            )
            continue

        if mode == "sequential":
            if executor != "main" or group:
                issues.append(
                    issue(
                        "error",
                        "invalid_sequential_task_contract",
                        f"{label} is sequential but executor_kind={executor} or parallel_group is set.",
                        tapl_prompt.sequential_task_contract_remediation(),
                        stable_id=label,
                    )
                )
            continue

        if executor != "subagent" or not group:
            issues.append(
                issue(
                    "error",
                    "invalid_parallel_task_contract",
                    f"{label} is parallel but does not declare executor_kind=subagent and a parallel_group.",
                    tapl_prompt.parallel_task_contract_remediation(),
                    stable_id=label,
                )
            )
        if not owned_paths:
            issues.append(
                issue(
                    "warning",
                    "parallel_task_owned_paths_missing",
                    f"{label} is parallel but does not declare owned_paths.",
                    tapl_prompt.parallel_owned_paths_remediation(),
                    stable_id=label,
                )
            )
        if group:
            parallel_groups.setdefault(group, []).append(task)

    for group, members in parallel_groups.items():
        executable_members = [
            task
            for task in members
            if task_status(task) in EXECUTABLE_STATUSES
        ]
        if len(executable_members) == 1:
            issues.append(
                issue(
                    "warning",
                    "parallel_group_has_single_executable_task",
                    f"Parallel group `{group}` has only one executable task.",
                    tapl_prompt.parallel_group_size_remediation(),
                    stable_id=task_label(executable_members[0]),
                )
            )
    return issues


def validate_task_dependencies(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    tasks_by_id = {task_label(task): task for task in tasks}
    graph = {label: task_dependencies(task) for label, task in tasks_by_id.items()}

    for label, dependencies in graph.items():
        task = tasks_by_id[label]
        for dependency_id in dependencies:
            dependency = tasks_by_id.get(dependency_id)
            if dependency is None:
                issues.append(
                    issue(
                        "error",
                        "unknown_task_dependency",
                        f"{label} depends on missing task {dependency_id}.",
                        tapl_prompt.task_dependency_remediation(),
                        stable_id=label,
                    )
                )
                continue
            if (
                str(task.get("execution_mode") or "sequential") == "parallel"
                and str(task.get("parallel_group") or "").strip()
                == str(dependency.get("parallel_group") or "").strip()
                and str(task.get("parallel_group") or "").strip()
            ):
                issues.append(
                    issue(
                        "error",
                        "parallel_group_dependency_conflict",
                        f"{label} depends on {dependency_id} in the same parallel_group.",
                        tapl_prompt.parallel_group_dependency_remediation(),
                        stable_id=label,
                    )
                )
            if task_status(dependency) != "Completed" and task_status(task) in EXECUTABLE_STATUSES:
                severity = "error" if task_status(task) == "In Progress" else "warning"
                issues.append(
                    issue(
                        severity,
                        "unmet_task_dependency",
                        f"{label} is {task_status(task)} but dependency {dependency_id} is {task_status(dependency)}.",
                        tapl_prompt.unmet_task_dependency_remediation(),
                        stable_id=label,
                    )
                )

    cycle = dependency_cycle(graph)
    if cycle:
        issues.append(
            issue(
                "error",
                "task_dependency_cycle",
                f"Task dependency cycle detected: {' -> '.join(cycle)}.",
                tapl_prompt.task_dependency_cycle_remediation(),
                stable_id=cycle[0],
            )
        )
    return issues


def validate_owned_path_exclusivity(
    state: dict[str, Any],
    tasks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    conflicts: set[str] = set()
    parallel_groups: dict[str, list[dict[str, Any]]] = {}
    for task in tasks:
        if (
            str(task.get("execution_mode") or "sequential") == "parallel"
            and task_status(task) in EXECUTABLE_STATUSES
        ):
            group = str(task.get("parallel_group") or "").strip()
            if group:
                parallel_groups.setdefault(group, []).append(task)

    for group, members in parallel_groups.items():
        for index, left in enumerate(members):
            for right in members[index + 1 :]:
                for left_path in task_owned_paths(left):
                    for right_path in task_owned_paths(right):
                        if db._owned_paths_overlap(left_path, right_path):
                            conflicts.add(
                                f"group {group}: {task_label(left)}:{left_path} overlaps "
                                f"{task_label(right)}:{right_path}"
                            )

    active_executions = state.get("active_executions")
    if not isinstance(active_executions, list):
        active_executions = []
    for index, left in enumerate(active_executions):
        if not isinstance(left, dict):
            continue
        for right in active_executions[index + 1 :]:
            if not isinstance(right, dict):
                continue
            for left_path in task_owned_paths(left):
                for right_path in task_owned_paths(right):
                    if db._owned_paths_overlap(left_path, right_path):
                        conflicts.add(
                            f"active executions: {task_label(left)}:{left_path} overlaps "
                            f"{task_label(right)}:{right_path}"
                        )

    return [
        issue(
            "error",
            "owned_path_overlap",
            f"Parallel task ownership overlaps: {conflict}.",
            tapl_prompt.owned_path_overlap_remediation(),
        )
        for conflict in sorted(conflicts)
    ]


def validate_execution_state(
    state: dict[str, Any],
    tasks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    tasks_by_id = {task_label(task): task for task in tasks}
    active_batches = state.get("active_batches")
    if not isinstance(active_batches, list):
        active_batches = []
    active_executions = state.get("active_executions")
    if not isinstance(active_executions, list):
        active_executions = []
    active_by_task = {
        task_label(execution): execution
        for execution in active_executions
        if isinstance(execution, dict)
    }

    for payload in active_batches:
        if not isinstance(payload, dict):
            continue
        batch = payload.get("batch") if isinstance(payload.get("batch"), dict) else {}
        executions = payload.get("executions") if isinstance(payload.get("executions"), list) else []
        active = [
            execution
            for execution in executions
            if isinstance(execution, dict)
            and execution.get("execution_state") in db.ACTIVE_EXECUTION_STATES
        ]
        batch_id = str(batch.get("batch_id") or batch.get("id") or "batch")
        batch_state = str(batch.get("state") or "")
        if batch_state == "active" and not active:
            issues.append(
                issue(
                    "error",
                    "stale_active_execution_batch",
                    f"Execution batch {batch_id} is active but has no active executions.",
                    tapl_prompt.stale_execution_batch_remediation(batch_id),
                )
            )
        elif batch_state != "active" and active:
            issues.append(
                issue(
                    "error",
                    "execution_batch_state_mismatch",
                    f"Execution batch {batch_id} is {batch_state or 'unknown'} while executions remain active.",
                    tapl_prompt.stale_execution_batch_remediation(batch_id),
                )
            )

        batch_group = str(batch.get("parallel_group") or "").strip()
        specs: set[str] = set()
        for execution in executions:
            if not isinstance(execution, dict):
                continue
            specs.add(str(execution.get("spec_id") or ""))
            if (
                str(execution.get("parallel_group") or "").strip() != batch_group
                or execution.get("execution_mode") != "parallel"
                or execution.get("executor_kind") != "subagent"
            ):
                issues.append(
                    issue(
                        "error",
                        "execution_batch_contract_mismatch",
                        f"{task_label(execution)} does not match execution batch {batch_id}'s parallel contract.",
                        tapl_prompt.execution_batch_contract_remediation(batch_id),
                        stable_id=task_label(execution),
                    )
                )
        if len(specs) > 1:
            issues.append(
                issue(
                    "error",
                    "execution_batch_mixed_plans",
                    f"Execution batch {batch_id} contains tasks from multiple plans.",
                    tapl_prompt.execution_batch_contract_remediation(batch_id),
                )
            )

    for execution in active_executions:
        if not isinstance(execution, dict):
            continue
        label = task_label(execution)
        task = tasks_by_id.get(label)
        if task is None or task_status(task) != "In Progress":
            issues.append(
                issue(
                    "error",
                    "active_execution_task_state_mismatch",
                    f"Active execution {execution.get('execution_id') or ''} expects {label} to be In Progress.",
                    tapl_prompt.execution_task_state_remediation(),
                    stable_id=label,
                )
            )

    for task in tasks:
        if (
            task_status(task) == "In Progress"
            and str(task.get("execution_mode") or "sequential") == "parallel"
            and task_label(task) not in active_by_task
        ):
            issues.append(
                issue(
                    "error",
                    "parallel_task_missing_active_execution",
                    f"{task_label(task)} is In Progress without an active execution.",
                    tapl_prompt.parallel_task_missing_execution_remediation(),
                    stable_id=task_label(task),
                )
            )
    return issues


def validate_task_execution_order(
    tasks: list[dict[str, Any]],
    state: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    in_progress: list[tuple[int, dict[str, Any]]] = [
        (index, task)
        for index, task in enumerate(tasks)
        if task_status(task) == "In Progress"
    ]
    active_executions = (
        state.get("active_executions")
        if isinstance(state, dict) and isinstance(state.get("active_executions"), list)
        else []
    )
    active_by_task = {
        task_label(execution): execution
        for execution in active_executions
        if isinstance(execution, dict)
    }
    batch_ids = {
        str(active_by_task[task_label(task)].get("batch_id") or "")
        for _, task in in_progress
        if task_label(task) in active_by_task
    }
    all_have_execution = bool(in_progress) and all(
        task_label(task) in active_by_task for _, task in in_progress
    )
    valid_parallel_batch = len(in_progress) > 1 and all_have_execution and len(batch_ids) == 1
    if len(in_progress) > 1 and all_have_execution and len(batch_ids) > 1:
        labels = ", ".join(task_label(task) for _, task in in_progress)
        issues.append(
            issue(
                "error",
                "multiple_active_execution_batches",
                f"In Progress tasks span multiple execution batches: {labels}.",
                tapl_prompt.mixed_execution_batches_remediation(),
            )
        )
    elif len(in_progress) > 1 and active_by_task and not all_have_execution:
        labels = ", ".join(task_label(task) for _, task in in_progress)
        issues.append(
            issue(
                "error",
                "mixed_in_progress_execution_state",
                f"In Progress tasks mix batch-managed and unmanaged execution: {labels}.",
                tapl_prompt.mixed_in_progress_state_remediation(),
            )
        )
    elif len(in_progress) > 1 and not valid_parallel_batch:
        labels = ", ".join(task_label(task) for _, task in in_progress)
        issues.append(
            issue(
                "warning",
                "multiple_tasks_in_progress",
                f"Multiple tasks are In Progress: {labels}.",
                tapl_prompt.multiple_tasks_in_progress_remediation(),
            )
        )

    if not in_progress or valid_parallel_batch:
        return issues

    sequential_in_progress = [
        (index, task)
        for index, task in in_progress
        if task_label(task) not in active_by_task
    ]
    if not sequential_in_progress:
        return issues
    first_index, first_task = sequential_in_progress[0]
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


def task_dependencies(task: dict[str, Any]) -> list[str]:
    value = task.get("depends_on")
    if not isinstance(value, list):
        return []
    return [str(dependency).strip() for dependency in value if str(dependency).strip()]


def task_owned_paths(task: dict[str, Any]) -> list[str]:
    value = task.get("owned_paths")
    try:
        return db.parse_owned_paths(value)
    except ValueError:
        return []


def dependency_cycle(graph: dict[str, list[str]]) -> list[str]:
    visited: set[str] = set()
    active: list[str] = []
    active_set: set[str] = set()

    def visit(node: str) -> list[str]:
        if node in active_set:
            index = active.index(node)
            return [*active[index:], node]
        if node in visited:
            return []
        visited.add(node)
        active.append(node)
        active_set.add(node)
        for dependency in graph.get(node, []):
            if dependency not in graph:
                continue
            cycle = visit(dependency)
            if cycle:
                return cycle
        active.pop()
        active_set.remove(node)
        return []

    for node in graph:
        cycle = visit(node)
        if cycle:
            return cycle
    return []


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
        "field_contract_source": "Use TAPL MCP tool descriptions and input schemas for exact field contracts.",
        "stable_ids": stable_id_guidance(),
        "adaptive_plan_policy": plan_detail_guidance(),
        "adaptive_task_policy": task_granularity_guidance(),
        "task_required_fields": tapl_prompt.task_required_field_summary(),
        "execution_approval_policy": execution_approval_validation_guidance(),
    }
    return payload


def plan_detail_guidance() -> str:
    return tapl_prompt.plan_detail_guidance()


def stable_id_guidance() -> str:
    return tapl_prompt.stable_id_guidance()


def task_granularity_guidance() -> str:
    return tapl_prompt.task_granularity_guidance()


def execution_approval_validation_guidance() -> str:
    return "Missing execution approval is always a validation error; use `tapl_approve_execution`."


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
