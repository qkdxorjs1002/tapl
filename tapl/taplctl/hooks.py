"""Codex hook event handling for tapl."""

from __future__ import annotations

import re
import sqlite3
from typing import Any

from . import config as tapl_config, context as tapl_context, db, validation


DURABLE_TOOLS = {"apply_patch", "Edit", "Write", "MultiEdit"}
DURABLE_BASH_HINTS = (
    ">",
    ">>",
    "tee ",
    "cat <<",
    "python ",
    "python3 ",
    "node ",
    "npm ",
    "rm ",
    "mv ",
    "cp ",
)
EXTERNAL_RESEARCH_HINTS = (
    "web.run",
    "search_query",
    "image_query",
    "websearch",
    "webfetch",
    "browser",
    "docs",
    "documentation",
)
EXTERNAL_BASH_HINTS = (
    "curl ",
    "wget ",
)


def handle_event(
    conn: sqlite3.Connection,
    *,
    event: str,
    mode: str,
    tool: str | None,
    payload: dict[str, Any],
    tapl_settings: tapl_config.TaplConfig | None = None,
    plan_task_settings: tapl_config.PlanTaskExecuteConfig | None = None,
) -> dict[str, Any]:
    tool_name = tool or infer_tool_name(payload)
    settings = plan_task_settings or (
        tapl_settings.plan_task_execute if tapl_settings else tapl_config.PlanTaskExecuteConfig()
    )
    message = ""
    block = False
    context_packet: dict[str, Any] | None = None
    record_run_id: str | None = None
    archive: sqlite3.Row | None = None

    if event == "UserPromptSubmit":
        db.ensure_active_run(conn, request_summary=db.DEFAULT_REQUEST_SUMMARY)

    if event in {"SessionStart", "UserPromptSubmit"}:
        resolved_settings = tapl_settings or tapl_config.TaplConfig(
            path="",
            exists=False,
            plan_task_execute=settings,
        )
        context_packet = tapl_context.build_context(
            conn,
            event=event,
            settings=resolved_settings,
            payload=payload,
        )
        message = combine_messages(message, tapl_context.format_context(context_packet))

    if event == "PreToolUse" and is_durable_tool(tool_name, payload):
        active = db.active_run(conn)
        task_count = db.active_task_count(conn)
        if not active or task_count == 0:
            message = (
                "tapl: durable edit requires an active tapl run with planned tasks. "
                f"{tapl_context.taplctl_execution_guidance()} "
                f"{tapl_context.taplctl_command_guidance()} "
                "Create/update plan and task state, then retry."
            )
            block = mode == "enforce"
        else:
            check = validation.validate_plan_task_execute(conn, settings)
            issue_message = validation.format_issues(check)
            if issue_message:
                message = combine_messages(message, issue_message)
            if mode == "enforce" and (check["errors"] or has_execution_approval_issue(check)):
                block = True

    if event == "PostToolUse" and is_external_research_tool(tool_name, payload):
        message = combine_messages(message, tapl_context.external_findings_guidance())

    if event == "Stop":
        state = db.status_payload(conn)
        active = state.get("active_run")
        if active:
            record_run_id = active["id"]
        remaining = state.get("incomplete_tasks", 0)
        if remaining:
            message = f"tapl: {remaining} task(s) remain incomplete; update task state or archive before stopping."
            block = mode == "enforce"
        check = validation.validate_plan_task_execute(conn, settings)
        issue_message = validation.format_issues(check)
        if issue_message:
            message = combine_messages(message, issue_message)
        if check["errors"] and mode == "enforce":
            block = True
        if should_auto_archive_on_stop(state, check, block, payload):
            archive = db.archive_active_run(
                conn,
                slug=auto_archive_slug(active),
                summary=auto_archive_summary(state, final_result=stop_result_summary(payload)),
            )
            message = combine_messages(
                message,
                f"tapl: archived completed run as {archive['slug']}.",
            )

    db.record_event(
        conn,
        event_type=event,
        tool_name=tool_name,
        mode=mode,
        payload=payload,
        message=message,
        run_id=record_run_id,
    )
    outcome = {
        "ok": not block,
        "block": block,
        "event": event,
        "mode": mode,
        "tool": tool_name,
        "message": message,
    }
    if context_packet is not None:
        outcome["context"] = context_packet
    if archive is not None:
        outcome["archive"] = db.row_to_dict(archive)
    return outcome


def combine_messages(*messages: str) -> str:
    return "\n".join(message for message in messages if message)


def has_execution_approval_issue(check: dict[str, Any]) -> bool:
    return any(
        item.get("code") in {"execution_approval_missing", "execution_approval_rejected"}
        for item in check.get("issues") or []
    )


def should_auto_archive_on_stop(
    state: dict[str, Any],
    check: dict[str, Any],
    block: bool,
    payload: dict[str, Any] | None = None,
) -> bool:
    run = state.get("active_run")
    result = run.get("result_summary") if isinstance(run, dict) else ""
    has_items = bool(state.get("plans") or state.get("tasks") or state.get("findings"))
    has_simple_result = bool(str(result or "").strip() or stop_result_summary(payload or {}))
    return bool(
        run
        and not state.get("incomplete_tasks", 0)
        and not check.get("errors")
        and not block
        and (has_items or has_simple_result)
    )


def auto_archive_slug(active_run: dict[str, Any] | None) -> str:
    source = ""
    if active_run:
        source = str(active_run.get("request_summary") or active_run.get("slug") or "")
    slug = re.sub(r"[^a-zA-Z0-9가-힣_-]+", "-", source.strip()).strip("-").lower()
    return slug[:80].strip("-") or "completed-run"


def auto_archive_summary(state: dict[str, Any], *, final_result: str = "") -> str:
    active_run = state.get("active_run") if isinstance(state.get("active_run"), dict) else None
    request = str(active_run.get("request_summary") or "").strip() if active_run else ""
    run_result = str(active_run.get("result_summary") or "").strip() if active_run else ""
    result = final_result.strip() or run_result
    plans = state.get("plans") if isinstance(state.get("plans"), list) else []
    tasks = state.get("tasks") if isinstance(state.get("tasks"), list) else []
    completed_tasks = [task for task in tasks if task.get("status") == "Completed"]
    remaining = int(state.get("incomplete_tasks") or 0)

    parts = [
        f"Original request: {request or 'archived workflow'}",
        f"Result: {result}" if result else "",
        f"Selected plan: {summarize_items(plans, fallback='None')}",
        f"Completed tasks: {summarize_items(completed_tasks, fallback='None', include_result=True)}",
        f"Verification: {summarize_verification(completed_tasks)}",
        f"Remaining work: {'None' if remaining == 0 else str(remaining)}",
    ]
    return compact_text("; ".join(part for part in parts if part), limit=1000)


def summarize_items(items: list[dict[str, Any]], *, fallback: str, include_result: bool = False) -> str:
    if not items:
        return fallback
    summaries: list[str] = []
    for item in items[:4]:
        label = " ".join(str(part) for part in (item.get("stable_id"), item.get("title")) if part).strip()
        result = str(item.get("result") or "").strip() if include_result else ""
        summaries.append(f"{label}: {result}" if result else label)
    if len(items) > 4:
        summaries.append(f"+{len(items) - 4} more")
    return ", ".join(summaries)


def summarize_verification(tasks: list[dict[str, Any]]) -> str:
    values = []
    for task in tasks:
        verification = str(task.get("verification") or "").strip()
        if verification and verification not in values:
            values.append(verification)
    return ", ".join(values[:4]) if values else "Not recorded"


def stop_result_summary(payload: dict[str, Any]) -> str:
    for key in (
        "result",
        "final_result",
        "final_message",
        "assistant_response",
        "response",
        "output",
        "summary",
    ):
        if key in payload:
            text = payload_text(payload.get(key))
            if text:
                return compact_text(text, limit=500)
    return ""


def payload_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        for item in reversed(value):
            text = payload_text(item)
            if text:
                return text
    if isinstance(value, dict):
        for key in ("content", "text", "message", "result", "summary", "output"):
            if key in value:
                text = payload_text(value.get(key))
                if text:
                    return text
    return ""


def compact_text(text: str, *, limit: int) -> str:
    compact = re.sub(r"\s+", " ", text).strip()
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3].rstrip() + "..."


def infer_tool_name(payload: dict[str, Any]) -> str | None:
    for key in ("tool_name", "toolName", "tool", "name"):
        value = payload.get(key)
        if isinstance(value, str):
            return value
        if isinstance(value, dict):
            nested = value.get("name")
            if isinstance(nested, str):
                return nested
    return None


def is_durable_tool(tool_name: str | None, payload: dict[str, Any]) -> bool:
    if tool_name in DURABLE_TOOLS:
        return True
    if tool_name == "Bash":
        command = payload_command(payload)
        return any(hint in command for hint in DURABLE_BASH_HINTS)
    return False


def is_external_research_tool(tool_name: str | None, payload: dict[str, Any]) -> bool:
    name = (tool_name or "").lower()
    if any(hint in name for hint in EXTERNAL_RESEARCH_HINTS):
        return True
    if name == "bash":
        command = payload_command(payload).lower()
        return any(hint in command for hint in EXTERNAL_BASH_HINTS)
    blob = str(payload).lower()
    return any(hint in blob for hint in EXTERNAL_RESEARCH_HINTS)


def payload_command(payload: dict[str, Any]) -> str:
    for key in ("command", "cmd"):
        value = payload.get(key)
        if isinstance(value, str):
            return value
    params = payload.get("parameters")
    if isinstance(params, dict):
        for key in ("command", "cmd"):
            value = params.get(key)
            if isinstance(value, str):
                return value
    tool_input = payload.get("tool_input")
    if isinstance(tool_input, dict):
        for key in ("command", "cmd"):
            value = tool_input.get(key)
            if isinstance(value, str):
                return value
    return ""


def prompt_summary(payload: dict[str, Any]) -> str:
    for key in ("prompt", "user_prompt", "message"):
        value = payload.get(key)
        if isinstance(value, str):
            return value.strip()[:240]
    return ""
