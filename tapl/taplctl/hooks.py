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

    if event in {"SessionStart", "UserPromptSubmit"}:
        request_summary = prompt_summary(payload) if event == "UserPromptSubmit" else ""
        db.ensure_active_run(conn, request_summary=request_summary)
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
            if check["errors"] and mode == "enforce":
                block = True

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
        if should_auto_archive_on_stop(state, check, block):
            archive = db.archive_active_run(
                conn,
                slug=auto_archive_slug(active),
                summary=auto_archive_summary(active),
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


def should_auto_archive_on_stop(state: dict[str, Any], check: dict[str, Any], block: bool) -> bool:
    return bool(
        state.get("active_run")
        and state.get("plans")
        and state.get("tasks")
        and not state.get("incomplete_tasks", 0)
        and not check.get("errors")
        and not block
    )


def auto_archive_slug(active_run: dict[str, Any] | None) -> str:
    source = ""
    if active_run:
        source = str(active_run.get("request_summary") or active_run.get("slug") or "")
    slug = re.sub(r"[^a-zA-Z0-9가-힣_-]+", "-", source.strip()).strip("-").lower()
    return slug[:80].strip("-") or "completed-run"


def auto_archive_summary(active_run: dict[str, Any] | None) -> str:
    if active_run and active_run.get("request_summary"):
        return active_run['request_summary']
    return "archived workflow"


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
    return ""


def prompt_summary(payload: dict[str, Any]) -> str:
    for key in ("prompt", "user_prompt", "message"):
        value = payload.get(key)
        if isinstance(value, str):
            return value.strip()[:240]
    return ""
