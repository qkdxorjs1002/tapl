"""MCP facade that maps structured TAPL tools to the ``taplctl`` CLI."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Annotated, Any, Literal

from mcp.server import MCPServer
from mcp_types import ToolAnnotations
from pydantic import Field

from . import __version__, config as tapl_config, db, prompt as tapl_prompt


SERVER_NAME = "tapl_mcp"
CLI_TIMEOUT_SECONDS = 60
PLAN_ID_PATTERN = r"^(?:PLAN|SPEC)-\d{3,}$"
TASK_ID_PATTERN = r"^TASK-\d{3,}$"

READ_ONLY = ToolAnnotations(
    read_only_hint=True,
    destructive_hint=False,
    idempotent_hint=True,
    open_world_hint=False,
)
WRITE = ToolAnnotations(
    read_only_hint=False,
    destructive_hint=False,
    idempotent_hint=False,
    open_world_hint=False,
)

PlanId = Annotated[
    str,
    Field(description=tapl_prompt.field_help("plan", "id"), pattern=PLAN_ID_PATTERN),
]
TaskId = Annotated[
    str,
    Field(description=tapl_prompt.field_help("task", "id"), pattern=TASK_ID_PATTERN),
]
CustomFields = Annotated[
    dict[str, Any] | None,
    Field(description=tapl_prompt.field_help("task", "custom_fields")),
]
ApprovalSource = Literal["explicit_user", "request_user_input"]
WorkflowMode = Literal["planned", "lightweight"]


class TaplCliError(RuntimeError):
    """An actionable error returned by the mapped ``taplctl`` command."""


def resolve_workspace_root(start: Path | None = None) -> Path:
    """Anchor one MCP process to the workspace selected when it starts."""

    candidate = (start or Path.cwd()).expanduser().resolve()
    return (db.find_workspace_root(candidate) or db.find_repo_root(candidate)).resolve()


def compact_payload(**values: Any) -> dict[str, Any]:
    """Omit top-level ``None`` values while preserving nested JSON nulls."""

    return {name: value for name, value in values.items() if value is not None}


def cli_error_message(command: tuple[str, ...], payload: dict[str, Any] | None, stderr: str) -> str:
    """Build a concise error that tells the model what to correct next."""

    details: list[str] = []
    if payload:
        error = str(payload.get("error") or "").strip()
        if error:
            details.append(error)
        check = payload.get("plan_task_execute")
        if isinstance(check, dict):
            for issue in list(check.get("issues") or [])[:3]:
                if not isinstance(issue, dict):
                    continue
                message = str(issue.get("message") or "").strip()
                remediation = str(issue.get("remediation") or "").strip()
                if message:
                    details.append(f"{message} {remediation}".strip())
        suggestion = str(payload.get("suggestion") or "").strip()
        if suggestion:
            details.append(f"Suggested next step: {suggestion}")
    if not details and stderr.strip():
        details.append(stderr.strip())
    if not details:
        details.append("taplctl did not return an actionable error message")
    return f"taplctl {' '.join(command)} failed: {' '.join(details)}"


async def run_taplctl(
    workspace_root: Path,
    *command: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run the same installed TAPL package as a JSON-only CLI subprocess."""

    db_path = workspace_root / db.DEFAULT_DB_RELATIVE
    argv = [sys.executable, "-m", "taplctl", "--db", str(db_path), *command]
    input_bytes: bytes | None = None
    if payload is not None:
        argv.append("--stdin-json")
        input_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    argv.append("--json")

    process = await asyncio.create_subprocess_exec(
        *argv,
        cwd=str(workspace_root),
        env=os.environ.copy(),
        stdin=asyncio.subprocess.PIPE if input_bytes is not None else asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            process.communicate(input_bytes),
            timeout=CLI_TIMEOUT_SECONDS,
        )
    except TimeoutError as exc:
        process.kill()
        await process.wait()
        raise TaplCliError(
            f"taplctl {' '.join(command)} timed out after {CLI_TIMEOUT_SECONDS} seconds; "
            "retry after checking the workspace and semantic search service"
        ) from exc

    stdout = stdout_bytes.decode("utf-8", errors="replace").strip()
    stderr = stderr_bytes.decode("utf-8", errors="replace").strip()
    parsed: dict[str, Any] | None = None
    if stdout:
        try:
            candidate = json.loads(stdout)
        except json.JSONDecodeError as exc:
            raise TaplCliError(
                f"taplctl {' '.join(command)} returned non-JSON output; run the CLI manually for diagnostics"
            ) from exc
        if not isinstance(candidate, dict):
            raise TaplCliError(f"taplctl {' '.join(command)} returned a non-object JSON result")
        parsed = candidate

    if process.returncode != 0 or parsed is None or parsed.get("ok") is False:
        raise TaplCliError(cli_error_message(tuple(command), parsed, stderr))
    return parsed


def mcp_next_recommendations(payload: dict[str, Any]) -> dict[str, Any]:
    """Replace CLI command recipes with MCP tool names in MCP-facing output."""

    tool_map: dict[str, str | list[str]] = {
        "summarize-request": "tapl_summarize_run",
        "apply-plan": "tapl_apply_plan",
        "create-task": "tapl_create_task",
        "approve-execution": "tapl_approve_execution",
        "settle-parallel-task": ["tapl_complete_task", "tapl_block_task", "tapl_skip_task"],
        "recover-parallel-batch": "tapl_recover_batch",
        "complete-or-block-task": ["tapl_complete_task", "tapl_block_task"],
        "block-task": "tapl_block_task",
        "dispatch-parallel-tasks": "tapl_dispatch_tasks",
        "start-task": "tapl_start_task",
        "finish-run": "tapl_finish_run",
        "archive-run": "tapl_finish_archive",
        "inspect-status": "tapl_get_status",
    }
    recommendations: list[dict[str, Any]] = []
    for recommendation in payload.get("recommendations") or []:
        if not isinstance(recommendation, dict):
            continue
        item = {key: value for key, value in recommendation.items() if key != "command"}
        item["tool"] = tool_map.get(str(item.get("name") or ""), "tapl_get_status")
        recommendations.append(item)
    return {**payload, "recommendations": recommendations}


def select_receipt_fields(value: Any, fields: tuple[str, ...]) -> dict[str, Any]:
    """Keep only model-actionable identity and state fields from one CLI object."""

    if not isinstance(value, dict):
        return {}
    return {
        field: value[field]
        for field in fields
        if field in value and value[field] not in (None, "", [], {})
    }


def compact_validation_receipt(value: Any) -> dict[str, Any]:
    """Summarize validation without repeating full error and warning collections."""

    if not isinstance(value, dict):
        return {}
    issues = value.get("issues") if isinstance(value.get("issues"), list) else []
    selected_issues = [
        select_receipt_fields(
            issue,
            ("severity", "code", "stable_id", "message", "remediation"),
        )
        for issue in issues[:3]
        if isinstance(issue, dict)
    ]
    receipt: dict[str, Any] = {"ok": bool(value.get("ok", not issues))}
    if issues:
        receipt["issue_count"] = len(issues)
        receipt["issues"] = selected_issues
    return receipt


def compact_batch_receipt(payload: dict[str, Any], *, include_contract: bool) -> dict[str, Any]:
    """Preserve settlement ids and, for dispatch, the contract needed to launch workers."""

    receipt: dict[str, Any] = {}
    batch = select_receipt_fields(
        payload.get("batch"),
        ("batch_id", "id", "state", "parallel_group", "failure_policy"),
    )
    if batch:
        # ``batch_id`` is the public identifier; avoid returning the same value twice.
        if batch.get("batch_id") == batch.get("id"):
            batch.pop("id", None)
        receipt["batch"] = batch

    base_fields = (
        "execution_id",
        "task_id",
        "execution_state",
        "task_status",
        "executor_ref",
        "model",
        "reasoning_effort",
        "execution_error",
    )
    contract_fields = (
        "title",
        "spec_id",
        "goal",
        "action",
        "verification",
        "execution_mode",
        "executor_kind",
        "parallel_group",
        "owned_paths",
        "owned_paths_json",
    )
    executions = []
    for execution in payload.get("executions") or []:
        selected = select_receipt_fields(
            execution,
            base_fields + (contract_fields if include_contract else ()),
        )
        owned_paths_json = selected.pop("owned_paths_json", None)
        if owned_paths_json:
            try:
                selected["owned_paths"] = json.loads(owned_paths_json)
            except (TypeError, json.JSONDecodeError):
                selected["owned_paths"] = owned_paths_json
        if selected:
            executions.append(selected)
    if executions:
        receipt["executions"] = executions
    return receipt


def mcp_write_receipt(payload: dict[str, Any], *, operation: str) -> dict[str, Any]:
    """Convert verbose CLI JSON into a compact MCP-facing write receipt."""

    receipt: dict[str, Any] = {
        "ok": bool(payload.get("ok", True)),
        "operation": str(payload.get("operation") or operation),
    }
    object_fields = (
        ("active_run", ("id", "slug", "status", "workflow_mode")),
        ("item", ("id", "stable_id", "kind", "status")),
        ("approval", ("id", "kind", "decision", "source")),
        ("archive", ("id", "slug")),
    )
    for key, fields in object_fields:
        selected = select_receipt_fields(payload.get(key), fields)
        if selected:
            receipt[key] = selected

    if payload.get("settled_execution_id"):
        receipt["settled_execution_id"] = payload["settled_execution_id"]
    receipt.update(
        compact_batch_receipt(
            payload,
            include_contract=receipt["operation"] == "task_dispatch",
        )
    )
    validation_receipt = compact_validation_receipt(payload.get("plan_task_execute"))
    if validation_receipt:
        receipt["plan_task_execute"] = validation_receipt
    return receipt


async def run_taplctl_write(
    workspace_root: Path,
    *command: str,
    payload: dict[str, Any] | None = None,
    operation: str,
) -> dict[str, Any]:
    """Execute a write, compact its receipt, and attach the latest safe MCP action."""

    result = await run_taplctl(workspace_root, *command, payload=payload)
    receipt = mcp_write_receipt(result, operation=operation)
    try:
        next_payload = await run_taplctl(workspace_root, "next")
        receipt["recommendations"] = mcp_next_recommendations(next_payload).get(
            "recommendations", []
        )
    except TaplCliError:
        # The write already succeeded; a transient advisory failure must not report it as failed.
        receipt["recommendations"] = [
            {
                "name": "inspect-status",
                "reason": "The write succeeded but the next-action lookup failed; inspect current state.",
                "tool": "tapl_get_status",
            }
        ]
    return receipt


def create_server(
    *,
    workspace_root: Path | None = None,
    instructions: str | None = None,
) -> MCPServer[None]:
    """Create a workspace-bound stdio MCP server."""

    root = resolve_workspace_root(workspace_root)
    server_instructions = instructions
    if server_instructions is None:
        settings = tapl_config.load(start=root)
        server_instructions = tapl_prompt.mcp_server_instructions(subagents=settings.subagents)
    server: MCPServer[None] = MCPServer(
        SERVER_NAME,
        title="TAPL workflow tools",
        description="Structured agent workflow tools backed by the repo-local taplctl CLI and SQLite state.",
        instructions=server_instructions,
        version=__version__,
    )

    @server.tool(
        name="tapl_get_status",
        title="Inspect TAPL workflow status",
        annotations=READ_ONLY,
    )
    async def get_status(
        full: Annotated[bool, Field(description="Include full plan, task, and finding bodies.")] = False,
        include_events: Annotated[bool, Field(description="Include recent hook event summaries.")] = False,
        events_limit: Annotated[int, Field(description="Maximum recent events to include.", ge=0, le=100)] = 12,
    ) -> dict[str, Any]:
        """Inspect current run, plans, tasks, approval, batches, and validation state. Use before record updates."""

        args = ["status"]
        if full:
            args.append("--full")
        if include_events:
            args.extend(("--include-events", "--events-limit", str(events_limit)))
        return await run_taplctl(root, *args)

    @server.tool(name="tapl_get_next", title="Get safest TAPL action", annotations=READ_ONLY)
    async def get_next() -> dict[str, Any]:
        """Return the safest next lifecycle tool without exposing a shell command. Use when workflow state is uncertain."""

        return mcp_next_recommendations(await run_taplctl(root, "next"))

    @server.tool(name="tapl_validate_state", title="Validate TAPL state", annotations=READ_ONLY)
    async def validate_state() -> dict[str, Any]:
        """Validate plan detail, task contracts, dependencies, execution order, and approval state after updates."""

        return await run_taplctl(root, "validate")

    @server.tool(name="tapl_search_history", title="Search TAPL history", annotations=READ_ONLY)
    async def search_history(
        query: Annotated[str, Field(description="Compact task-specific query with likely files, features, or errors.", min_length=1, max_length=500)],
        limit: Annotated[int | None, Field(description="Maximum summarized matches.", ge=1, le=50)] = None,
    ) -> dict[str, Any]:
        """Search active and archived TAPL records before planning or when prior decisions may prevent rediscovery."""

        args = ["search", query]
        if limit is not None:
            args.extend(("--limit", str(limit)))
        return await run_taplctl(root, *args)

    @server.tool(name="tapl_get_item", title="Read one TAPL item", annotations=READ_ONLY)
    async def get_item(
        item_id: Annotated[int, Field(description="Numeric item id returned by tapl_search_history.", ge=1)],
    ) -> dict[str, Any]:
        """Read one complete plan, task, or finding when a search snippet is insufficient."""

        return await run_taplctl(root, "item", "show", "--id", str(item_id))

    @server.tool(name="tapl_summarize_run", title="Summarize active TAPL run", annotations=WRITE)
    async def summarize_run(
        summary: Annotated[str, Field(description=tapl_prompt.field_help("run", "summary"), min_length=1, max_length=2000)],
        workflow_mode: Annotated[
            WorkflowMode,
            Field(description="Agent-selected workflow complexity: planned or lightweight."),
        ] = db.DEFAULT_WORKFLOW_MODE,
    ) -> dict[str, Any]:
        """Summarize the request and explicitly select planned or lightweight workflow handling."""

        return await run_taplctl_write(
            root,
            "run",
            "summarize",
            payload={"summary": summary, "workflow_mode": workflow_mode},
            operation="run_summarize",
        )

    @server.tool(name="tapl_apply_plan", title="Create or update TAPL plan", annotations=WRITE)
    async def apply_plan(
        plan_id: PlanId = "PLAN-001",
        title: Annotated[str | None, Field(description=tapl_prompt.field_help("plan", "title"))] = None,
        summary: Annotated[str | None, Field(description=tapl_prompt.field_help("plan", "summary"))] = None,
        objective: Annotated[str | None, Field(description=tapl_prompt.field_help("plan", "objective"))] = None,
        requirements_trace: Annotated[str | None, Field(description=tapl_prompt.field_help("plan", "requirements_trace"))] = None,
        selected_approach: Annotated[str | None, Field(description=tapl_prompt.field_help("plan", "selected_approach"))] = None,
        affected_files: Annotated[str | None, Field(description=tapl_prompt.field_help("plan", "affected_files"))] = None,
        execution_order: Annotated[str | None, Field(description=tapl_prompt.field_help("plan", "execution_order"))] = None,
        risks: Annotated[str | None, Field(description=tapl_prompt.field_help("plan", "risks"))] = None,
        validation: Annotated[str | None, Field(description=tapl_prompt.field_help("plan", "validation"))] = None,
        approval_needs: Annotated[str | None, Field(description=tapl_prompt.field_help("plan", "approval_needs"))] = None,
        notes: Annotated[str | None, Field(description=tapl_prompt.field_help("plan", "notes"))] = None,
        custom_fields: CustomFields = None,
        status: Annotated[str | None, Field(description=tapl_prompt.field_help("plan", "status"))] = None,
    ) -> dict[str, Any]:
        """Create or partially update the detailed plan. New plans need all detailed fields; omitted update fields are preserved."""

        return await run_taplctl_write(
            root,
            "plan",
            "apply",
            payload=compact_payload(
                id=plan_id,
                title=title,
                summary=summary,
                objective=objective,
                requirements_trace=requirements_trace,
                selected_approach=selected_approach,
                affected_files=affected_files,
                execution_order=execution_order,
                risks=risks,
                validation=validation,
                approval_needs=approval_needs,
                notes=notes,
                custom_fields=custom_fields,
                status=status,
            ),
            operation="plan_apply",
        )

    @server.tool(name="tapl_create_task", title="Create TAPL task", annotations=WRITE)
    async def create_task(
        task_id: TaskId,
        title: Annotated[str, Field(description=tapl_prompt.field_help("task", "title"), min_length=1)],
        spec_id: PlanId,
        goal: Annotated[str, Field(description=tapl_prompt.field_help("task", "goal"), min_length=1)],
        action: Annotated[str, Field(description=tapl_prompt.field_help("task", "action"), min_length=1)],
        verification: Annotated[str, Field(description=tapl_prompt.field_help("task", "verification"), min_length=1)],
        execution_mode: Annotated[Literal["sequential", "parallel"], Field(description="Sequential or explicitly parallel execution.")] = "sequential",
        executor_kind: Annotated[Literal["main", "subagent"], Field(description="Main agent or actual delegated subagent executor.")] = "main",
        parallel_group: Annotated[str | None, Field(description="Shared non-empty group for compatible parallel tasks.")] = None,
        owned_paths: Annotated[list[str] | None, Field(description="Exclusive file or directory paths owned by this task.")] = None,
        depends_on: Annotated[list[str] | None, Field(description="Task ids that must be Completed before this task starts.")] = None,
        custom_fields: CustomFields = None,
    ) -> dict[str, Any]:
        """Create one Pending executable task derived from an existing plan. Split independent edit and verification work."""

        return await run_taplctl_write(
            root,
            "task",
            "create",
            payload=compact_payload(
                id=task_id,
                title=title,
                spec_id=spec_id,
                goal=goal,
                action=action,
                verification=verification,
                execution_mode=execution_mode,
                executor_kind=executor_kind,
                parallel_group=parallel_group,
                owned_paths=owned_paths,
                depends_on=depends_on,
                custom_fields=custom_fields,
            ),
            operation="task_create",
        )

    @server.tool(name="tapl_start_task", title="Start TAPL task", annotations=WRITE)
    async def start_task(task_id: TaskId, custom_fields: CustomFields = None) -> dict[str, Any]:
        """Mark one dependency-ready sequential task In Progress immediately before its implementation begins."""

        return await run_taplctl_write(
            root,
            "task",
            "start",
            task_id,
            payload=compact_payload(custom_fields=custom_fields),
            operation="task_start",
        )

    @server.tool(name="tapl_dispatch_tasks", title="Dispatch parallel TAPL tasks", annotations=WRITE)
    async def dispatch_tasks(
        task_ids: Annotated[list[TaskId], Field(description="At least two compatible Pending subagent task ids.", min_length=2)],
        batch_id: Annotated[str | None, Field(description="Optional stable batch id for idempotent retry.")] = None,
        failure_policy: Annotated[str, Field(description="Non-empty batch failure policy.", min_length=1)] = db.DEFAULT_FAILURE_POLICY,
        execution_metadata: Annotated[dict[str, dict[str, Any]] | None, Field(description="Per-task runtime model and reasoning metadata.")] = None,
    ) -> dict[str, Any]:
        """Atomically validate and dispatch compatible parallel tasks; retain every returned execution id for settlement."""

        return await run_taplctl_write(
            root,
            "task",
            "dispatch",
            payload=compact_payload(
                task_ids=task_ids,
                batch_id=batch_id,
                failure_policy=failure_policy,
                execution_metadata=execution_metadata,
            ),
            operation="task_dispatch",
        )

    @server.tool(name="tapl_complete_task", title="Complete TAPL task", annotations=WRITE)
    async def complete_task(
        task_id: TaskId,
        verification: Annotated[str, Field(description=tapl_prompt.field_help("task", "verification"), min_length=1)],
        result: Annotated[str, Field(description=tapl_prompt.field_help("task", "result"), min_length=1)],
        execution_id: Annotated[str | None, Field(description="Exact execution id required for a dispatched parallel task.")] = None,
        custom_fields: CustomFields = None,
    ) -> dict[str, Any]:
        """Mark a task Completed only after implementation and verification; settle parallel work with its exact execution id."""

        return await run_taplctl_write(
            root,
            "task",
            "complete",
            task_id,
            payload=compact_payload(
                verification=verification,
                result=result,
                execution_id=execution_id,
                custom_fields=custom_fields,
            ),
            operation="task_complete",
        )

    @server.tool(name="tapl_block_task", title="Block TAPL task", annotations=WRITE)
    async def block_task(
        task_id: TaskId,
        blocker: Annotated[str, Field(description=tapl_prompt.field_help("task", "blocker"), min_length=1)],
        next_action: Annotated[str, Field(description=tapl_prompt.field_help("task", "next_action"), min_length=1)],
        execution_id: Annotated[str | None, Field(description="Exact execution id required for a dispatched parallel task.")] = None,
        verification: Annotated[str | None, Field(description="Current verification evidence, if changed.")] = None,
        custom_fields: CustomFields = None,
    ) -> dict[str, Any]:
        """Mark a task Blocked with a concrete blocker and next action; use instead of leaving inactive work In Progress."""

        return await run_taplctl_write(
            root,
            "task",
            "block",
            task_id,
            payload=compact_payload(
                blocker=blocker,
                next_action=next_action,
                execution_id=execution_id,
                verification=verification,
                custom_fields=custom_fields,
            ),
            operation="task_block",
        )

    @server.tool(name="tapl_skip_task", title="Skip TAPL task", annotations=WRITE)
    async def skip_task(
        task_id: TaskId,
        result: Annotated[str, Field(description="Reason the task is intentionally skipped.", min_length=1)],
        execution_id: Annotated[str | None, Field(description="Exact execution id required for a dispatched parallel task.")] = None,
        custom_fields: CustomFields = None,
    ) -> dict[str, Any]:
        """Mark work Skipped when it is intentionally out of scope or superseded, preserving the reason."""

        return await run_taplctl_write(
            root,
            "task",
            "skip",
            task_id,
            payload=compact_payload(result=result, execution_id=execution_id, custom_fields=custom_fields),
            operation="task_skip",
        )

    @server.tool(name="tapl_cancel_batch", title="Cancel TAPL batch", annotations=WRITE)
    async def cancel_batch(
        batch_id: Annotated[str, Field(description="Active execution batch id.", min_length=1)],
        reason: Annotated[str, Field(description="Why the batch is being cancelled.", min_length=1)],
        block_tasks: Annotated[bool, Field(description="Block tasks instead of returning them to Pending.")] = True,
    ) -> dict[str, Any]:
        """Cancel an active batch after spawn failure or intentional stop and settle every active execution."""

        args = ["batch", "cancel", batch_id, "--reason", reason]
        if block_tasks:
            args.append("--block")
        return await run_taplctl_write(root, *args, operation="batch_cancel")

    @server.tool(name="tapl_recover_batch", title="Recover TAPL batch", annotations=WRITE)
    async def recover_batch(
        batch_id: Annotated[str, Field(description="Interrupted execution batch id.", min_length=1)],
        reason: Annotated[str, Field(description="Why recovery is required.", min_length=1)],
    ) -> dict[str, Any]:
        """Recover an interrupted batch and return its active tasks to Pending before a safe retry."""

        return await run_taplctl_write(
            root,
            "batch",
            "recover",
            batch_id,
            "--reason",
            reason,
            operation="batch_recover",
        )

    @server.tool(name="tapl_add_finding", title="Record TAPL finding", annotations=WRITE)
    async def add_finding(
        title: Annotated[str, Field(description=tapl_prompt.field_help("finding", "title"), min_length=1)],
        source: Annotated[str, Field(description=tapl_prompt.field_help("finding", "source"))] = "",
        finding: Annotated[str, Field(description=tapl_prompt.field_help("finding", "finding"))] = "",
        impact: Annotated[str, Field(description=tapl_prompt.field_help("finding", "impact"))] = "",
        related_ids: Annotated[str, Field(description=tapl_prompt.field_help("finding", "related_ids"))] = "",
    ) -> dict[str, Any]:
        """Record only a decision-relevant external or implementation finding with its source and impact."""

        return await run_taplctl_write(
            root,
            "finding",
            "add",
            "--title",
            title,
            "--source",
            source,
            "--finding",
            finding,
            "--impact",
            impact,
            "--related-ids",
            related_ids,
            operation="finding_add",
        )

    @server.tool(name="tapl_approve_execution", title="Approve TAPL execution", annotations=WRITE)
    async def approve_execution(
        prompt: Annotated[str, Field(description=tapl_prompt.field_help("approval", "prompt"), min_length=1)],
        source: Annotated[ApprovalSource, Field(description=tapl_prompt.field_help("approval", "source"))] = "explicit_user",
    ) -> dict[str, Any]:
        """Record execution approval only after the user explicitly requested execution or confirmed it through request_user_input."""

        return await run_taplctl_write(
            root,
            "approval",
            "approve",
            payload={"kind": db.DEFAULT_APPROVAL_KIND, "prompt": prompt, "source": source},
            operation="approval_approve",
        )

    @server.tool(name="tapl_reject_execution", title="Reject TAPL execution", annotations=WRITE)
    async def reject_execution(
        prompt: Annotated[str, Field(description="Rejected execution scope.", min_length=1)],
        source: Annotated[ApprovalSource, Field(description=tapl_prompt.field_help("approval", "source"))] = "explicit_user",
    ) -> dict[str, Any]:
        """Record an explicit execution rejection and keep executable work pending or blocked."""

        return await run_taplctl_write(
            root,
            "approval",
            "reject",
            payload={"kind": db.DEFAULT_APPROVAL_KIND, "prompt": prompt, "source": source},
            operation="approval_reject",
        )

    @server.tool(name="tapl_finish_run", title="Finish TAPL run", annotations=WRITE)
    async def finish_run(
        result: Annotated[str, Field(description=tapl_prompt.field_help("run", "result"), min_length=1)],
    ) -> dict[str, Any]:
        """Record the verified final result after no actionable tasks remain and before archiving."""

        return await run_taplctl_write(
            root,
            "run",
            "finish",
            payload={"result": result},
            operation="run_finish",
        )

    @server.tool(name="tapl_finish_archive", title="Archive TAPL run", annotations=WRITE)
    async def finish_archive(
        slug: Annotated[str, Field(description="Stable timestamped archive slug.", min_length=1, max_length=120)],
        summary: Annotated[str, Field(description="Concise archive summary.", max_length=2000)] = "",
    ) -> dict[str, Any]:
        """Archive a completed, superseded, or intentionally deferred run after every task and batch is settled."""

        return await run_taplctl_write(
            root,
            "archive",
            "finish",
            payload={"slug": slug, "summary": summary},
            operation="archive_finish",
        )

    return server


def main() -> None:
    """Run the local TAPL MCP server over stdio."""

    create_server().run()


if __name__ == "__main__":
    main()
