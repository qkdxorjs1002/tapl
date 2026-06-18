"""Command line interface for tapl."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

from . import (
    __version__,
    config as tapl_config,
    context as tapl_context,
    db,
    embeddings,
    hooks,
    importer,
    install as tapl_install,
    searchd,
    validation,
)


HELP_FORMATTER = argparse.RawDescriptionHelpFormatter
JSON_HELP = "Print JSON output."
DRY_RUN_HELP = "Preview changes without writing files."


def command_help_epilog() -> str:
    return (
        "Workflow guidance:\n"
        "  Use `taplctl status --json` to inspect state before non-trivial work.\n"
        f"  {validation.workflow_order_guidance()}\n"
        f"  {validation.task_execution_order_guidance()}\n"
        "  Use `taplctl <command> <subcommand> --help` for field-writing rules.\n"
        f"  {validation.markdown_record_guidance()}\n"
        "  Use `taplctl validate --json` after updates to catch missing plan/task details."
    )


def plan_set_epilog() -> str:
    return (
        "Plan writing rules:\n"
        f"  {validation.markdown_record_guidance()}\n"
        f"  {validation.stable_id_guidance()}\n"
        "  Write or update the plan before task records; downstream tasks should derive from this record.\n"
        f"  {validation.plan_format_guidance()}\n"
        "  Summary should be a compact trace such as `REQ-001: approach, files, risks, validation`.\n"
        "  Body is for the durable plan: objective, requirements trace, selected approach,\n"
        "  affected files/interfaces, execution order, risks, validation, and approval needs.\n"
        "  Status is free-form; common values are Draft, Finalized, Imported, and Superseded.\n"
        "\n"
        "Example:\n"
        "  taplctl plan set --id PLAN-001 --title 'Plan title' \\\n"
        "    --summary 'REQ-001: approach, affected files, risks, validation' \\\n"
        "    --body 'Objective: ...\\nValidation: ...' --status Finalized --json"
    )


def task_set_epilog() -> str:
    statuses = ", ".join(db.TASK_STATUSES)
    subagents = ", ".join(validation.LEVEL_SUBAGENTS)
    return (
        "Task writing rules:\n"
        f"  {validation.markdown_record_guidance()}\n"
        f"  {validation.stable_id_guidance()}\n"
        f"  {validation.task_plan_dependency_guidance()}\n"
        f"  {validation.task_execution_order_guidance()}\n"
        "  Existing task updates are partial: pass --id plus only changed fields;\n"
        "  omitted fields keep their stored values. New task creation requires --title and --status.\n"
        "  Executable tasks should include source spec_id, goal, action, required_subagent,\n"
        "  verification, and result when completed; blocked tasks should include blocker and next_action.\n"
        "  When level subagent routing is enabled, spawn the task's required_subagent\n"
        "  and assign only that task; the main agent keeps TAPL status updates.\n"
        "  Split tasks by meaningful implementation or verification step.\n"
        f"  Status values: {statuses}. Quote multi-word statuses, e.g. --status 'In Progress'.\n"
        f"  Required subagents: {subagents}. Do not use level names such as `level2`.\n"
        "  Keep task text in the user's language unless asked otherwise.\n"
        "\n"
        "Field guidance:\n"
        "  --spec-id: numeric stable id of the source plan/spec, e.g. PLAN-001 or SPEC-001.\n"
        "  --goal: outcome the task must achieve.\n"
        "  --action: concrete work to perform.\n"
        "  --verification: command, check, or review that proves the task is done.\n"
        "  --result: concise completion note; use with Completed tasks.\n"
        "  --blocker/--next-action: why a Blocked task cannot proceed and what unblocks it.\n"
        "\n"
        "Example:\n"
        "  taplctl task set --id TASK-001 --title 'Implement change' \\\n"
        "    --status 'In Progress' --spec-id PLAN-001 --goal 'Make requested behavior work' \\\n"
        "    --action 'Edit the relevant files' --required-subagent '@senior-worker' \\\n"
        "    --verification 'Run focused tests' --json\n"
        "  taplctl task set --id TASK-001 --status Completed --result 'Focused tests passed' --json"
    )


def finding_add_epilog() -> str:
    return (
        "Finding writing rules:\n"
        f"  {validation.markdown_record_guidance('finding details and impact')}\n"
        "  Add only decision-relevant facts; include source and impact when they affect\n"
        "  requirements, plan, tasks, or verification.\n"
        "\n"
        "Example:\n"
        "  taplctl finding add --title 'Finding title' --source 'Source' \\\n"
        "    --finding 'What was learned' --impact 'Why it matters' --json"
    )


def approval_set_epilog() -> str:
    return (
        "Approval writing rules:\n"
        "  Set explicit execution approval after task design and before starting or\n"
        "  continuing task execution. The prompt should describe the approved scope,\n"
        "  not just `yes`.\n"
        "\n"
        "Example:\n"
        "  taplctl approval set --decision approved \\\n"
        "    --prompt 'Execute TASK-001 from PLAN-001' --json"
    )


def add_json_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--json", action="store_true", help=JSON_HELP)


def add_dry_run_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--dry-run", action="store_true", help=DRY_RUN_HELP)


def add_run_set_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--summary", default=None, help="Short description of the current request.")
    parser.add_argument("--result", default=None, help="Short description of the completed result.")
    add_json_arg(parser)


def add_plan_write_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--id", default="PLAN-001", help="Numeric plan id, e.g. PLAN-001 or SPEC-001.")
    parser.add_argument("--title", default="Plan", help="Short human-readable plan title.")
    parser.add_argument("--summary", default="", help="Compact requirements trace and approach summary.")
    parser.add_argument("--body", default="", help="Detailed plan body; use newlines for sections.")
    parser.add_argument("--status", default="Draft", help="Plan lifecycle label, e.g. Draft or Finalized.")
    add_json_arg(parser)


def add_task_write_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--id", required=True, help="Numeric task id, e.g. TASK-001.")
    parser.add_argument("--title", default=None, help="Short human-readable task title. Required when creating a task.")
    parser.add_argument(
        "--status",
        default=None,
        choices=db.TASK_STATUSES,
        help="Task lifecycle status. Required when creating a task; omitted updates keep the stored status.",
    )
    parser.add_argument("--spec-id", default=None, help="Numeric source plan/spec id, e.g. PLAN-001 or SPEC-001.")
    parser.add_argument("--goal", default=None, help="Outcome this task must achieve.")
    parser.add_argument("--action", default=None, help="Concrete work to perform.")
    parser.add_argument("--required-subagent", default=None, help="One of the configured @*-worker values.")
    parser.add_argument("--verification", default=None, help="Command, check, or review proving completion.")
    parser.add_argument("--result", default=None, help="Completion note for Completed tasks.")
    parser.add_argument("--blocker", default=None, help="Reason a Blocked task cannot proceed.")
    parser.add_argument("--next-action", default=None, help="Specific action that would unblock a Blocked task.")
    add_json_arg(parser)


def add_approval_write_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--kind", default=db.DEFAULT_APPROVAL_KIND, help="Approval kind.")
    parser.add_argument("--decision", required=True, choices=db.APPROVAL_DECISIONS, help="Approval decision.")
    parser.add_argument("--prompt", default="", help="Approved or rejected execution scope.")
    add_json_arg(parser)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "handler"):
        parser.print_help()
        return 2
    try:
        auto_install_before_handler(args)
        return int(args.handler(args) or 0)
    except Exception as exc:
        if getattr(args, "json", False):
            print_json({"ok": False, "error": str(exc)})
        else:
            print(f"taplctl: {exc}", file=sys.stderr)
        return 1


def auto_install_before_handler(args: argparse.Namespace) -> None:
    if should_skip_auto_install(args):
        return
    tapl_install.auto_install_if_needed()


def should_skip_auto_install(args: argparse.Namespace) -> bool:
    command = getattr(args, "command", None)
    if args.db is not None or args.config is not None:
        return True
    if command in {None, "install", "hook-event"}:
        return True
    return command == "searchd" and getattr(args, "searchd_command", None) == "run"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="taplctl",
        description="Manage tapl workflow state for agent planning, execution, and validation.",
        epilog=command_help_epilog(),
        formatter_class=HELP_FORMATTER,
    )
    parser.add_argument("--db", type=Path, default=None, help="Path to tapl SQLite DB.")
    parser.add_argument("--config", type=Path, default=None, help="Path to tapl TOML config.")
    parser.add_argument("--version", action="version", version=f"taplctl {__version__}", help="Show version and exit.")
    sub = parser.add_subparsers(dest="command")

    init = sub.add_parser("init", help="Initialize the tapl database.")
    add_json_arg(init)
    init.set_defaults(handler=cmd_init)

    doctor = sub.add_parser("doctor", help="Check tapl runtime dependencies.")
    add_json_arg(doctor)
    doctor.set_defaults(handler=cmd_doctor)

    status = sub.add_parser("status", help="Show active workflow state.")
    add_json_arg(status)
    status.add_argument("--full", action="store_true", help="Include full plan/task/finding item details.")
    status.add_argument(
        "--include-events",
        action="store_true",
        help="Include recent hook event summaries. Event payloads are not included.",
    )
    status.add_argument("--events-limit", type=int, default=12, help="Recent hook events to include.")
    status.set_defaults(handler=cmd_status)

    validate = sub.add_parser("validate", help="Validate tapl database state.")
    add_json_arg(validate)
    validate.set_defaults(handler=cmd_validate)

    context_cmd = sub.add_parser("context", help="Show lifecycle context for Codex.")
    context_cmd.add_argument("--event", default="Manual", help="Lifecycle event name to format context for.")
    add_json_arg(context_cmd)
    context_cmd.set_defaults(handler=cmd_context)

    run = sub.add_parser("run", help="Manage the active workflow run.")
    run_sub = run.add_subparsers(dest="run_command")
    run_set = run_sub.add_parser(
        "set",
        help="Set active run fields.",
        description="Set active run fields.",
    )
    add_run_set_args(run_set)
    run_set.set_defaults(handler=cmd_run_set)

    install = sub.add_parser("install", help="Install tapl workflow hooks and repo-local state.")
    install_sub = install.add_subparsers(dest="install_command")
    install_user = install_sub.add_parser(
        "user",
        help="Install user-global Codex hooks.",
        description="Install user-global Codex hooks.",
    )
    install_user.add_argument("--codex-home", type=Path, default=None, help="Codex home directory to update.")
    add_install_common_args(install_user)
    install_user.set_defaults(handler=cmd_install_user)
    install_repo = install_sub.add_parser(
        "repo",
        help="Install repo-local Codex hooks, config, and DB.",
        description="Install repo-local Codex hooks, config, and DB.",
    )
    install_repo.add_argument("--repo", type=Path, default=None, help="Repository root to install into.")
    add_install_common_args(install_repo)
    install_repo.set_defaults(handler=cmd_install_repo)

    plan = sub.add_parser("plan", help="Manage plan items.", formatter_class=HELP_FORMATTER)
    plan_sub = plan.add_subparsers(dest="plan_command")
    plan_set = plan_sub.add_parser(
        "set",
        help="Create or update a plan.",
        description="Create or update a durable plan record.",
        epilog=plan_set_epilog(),
        formatter_class=HELP_FORMATTER,
    )
    add_plan_write_args(plan_set)
    plan_set.set_defaults(handler=cmd_plan_set)

    task = sub.add_parser("task", help="Manage tasks.", formatter_class=HELP_FORMATTER)
    task_sub = task.add_subparsers(dest="task_command")
    task_set = task_sub.add_parser(
        "set",
        help="Create or update a task.",
        description="Create or update an executable task record.",
        epilog=task_set_epilog(),
        formatter_class=HELP_FORMATTER,
    )
    add_task_write_args(task_set)
    task_set.set_defaults(handler=cmd_task_set)

    finding = sub.add_parser("finding", help="Manage findings.")
    finding_sub = finding.add_subparsers(dest="finding_command")
    finding_add = finding_sub.add_parser(
        "add",
        help="Add a finding.",
        description="Add a finding.",
        epilog=finding_add_epilog(),
        formatter_class=HELP_FORMATTER,
    )
    finding_add.add_argument("--title", required=True, help="Short finding title.")
    finding_add.add_argument("--source", default="", help="Where the finding came from.")
    finding_add.add_argument("--finding", default="", help="Finding details.")
    finding_add.add_argument("--impact", default="", help="Why the finding matters.")
    finding_add.add_argument("--related-ids", default="", help="Related plan, task, or item ids.")
    add_json_arg(finding_add)
    finding_add.set_defaults(handler=cmd_finding_add)

    approval = sub.add_parser("approval", help="Manage explicit workflow approvals.", formatter_class=HELP_FORMATTER)
    approval_sub = approval.add_subparsers(dest="approval_command")
    approval_set = approval_sub.add_parser(
        "set",
        help="Set an approval decision.",
        description="Set a user decision for workflow execution.",
        epilog=approval_set_epilog(),
        formatter_class=HELP_FORMATTER,
    )
    add_approval_write_args(approval_set)
    approval_set.set_defaults(handler=cmd_approval_set)
    approval_status = approval_sub.add_parser(
        "status",
        help="Show current approval state.",
        description="Show current approval state.",
    )
    approval_status.add_argument("--kind", default=db.DEFAULT_APPROVAL_KIND, help="Approval kind to inspect.")
    add_json_arg(approval_status)
    approval_status.set_defaults(handler=cmd_approval_status)
    approval_list = approval_sub.add_parser("list", help="List recent approvals.", description="List recent approvals.")
    approval_list.add_argument("--kind", default="", help="Filter by approval kind.")
    approval_list.add_argument("--limit", type=int, default=10, help="Maximum approvals to return.")
    add_json_arg(approval_list)
    approval_list.set_defaults(handler=cmd_approval_list)

    item = sub.add_parser("item", help="Inspect workflow items.")
    item_sub = item.add_subparsers(dest="item_command")
    item_show = item_sub.add_parser("show", help="Show one item by numeric id.", description="Show one item by numeric id.")
    item_show.add_argument("--id", type=int, required=True, help="Numeric item id.")
    add_json_arg(item_show)
    item_show.set_defaults(handler=cmd_item_show)

    archive = sub.add_parser("archive", help="Manage archives.")
    archive_sub = archive.add_subparsers(dest="archive_command")
    archive_create = archive_sub.add_parser("create", help="Archive the active run.", description="Archive the active run.")
    archive_create.add_argument("--slug", required=True, help="Stable archive slug.")
    archive_create.add_argument("--summary", default="", help="Archive summary text.")
    add_json_arg(archive_create)
    archive_create.set_defaults(handler=cmd_archive_create)
    archive_list = archive_sub.add_parser("list", help="List archives.", description="List archives.")
    archive_list.add_argument("--limit", type=int, default=None, help="Maximum archives to return.")
    add_json_arg(archive_list)
    archive_list.set_defaults(handler=cmd_archive_list)
    archive_show = archive_sub.add_parser("show", help="Show archive details.", description="Show archive details.")
    archive_show.add_argument("--id", required=True, help="Archive id or slug.")
    add_json_arg(archive_show)
    archive_show.set_defaults(handler=cmd_archive_show)

    search = sub.add_parser("search", help="Search workflow state and archive history.")
    search.add_argument("query", help="Search query string.")
    search.add_argument(
        "--limit",
        type=positive_int_arg,
        default=None,
        help="Maximum results to return. Defaults to search.max_results config.",
    )
    add_json_arg(search)
    search.set_defaults(handler=cmd_search)

    reindex = sub.add_parser("reindex", help="Build semantic index when optional deps are installed.")
    add_dry_run_arg(reindex)
    add_json_arg(reindex)
    reindex.set_defaults(handler=cmd_reindex)

    searchd_cmd = sub.add_parser("searchd", help="Manage the semantic search daemon.")
    searchd_sub = searchd_cmd.add_subparsers(dest="searchd_command")
    searchd_start = searchd_sub.add_parser(
        "start",
        help="Start the semantic search daemon.",
        description="Start the semantic search daemon.",
    )
    searchd_start.add_argument("--socket", default=None, help="Unix socket path. Defaults to ~/.tapl/searchd.sock.")
    searchd_start.add_argument(
        "--idle-timeout",
        type=non_negative_int_arg,
        default=None,
        help="Seconds before unloading an idle model. Defaults to search.searchd_model_idle_timeout_seconds.",
    )
    searchd_start.add_argument(
        "--timeout-ms",
        type=positive_int_arg,
        default=None,
        help="Milliseconds to wait for daemon readiness. Defaults to 15000.",
    )
    searchd_start.add_argument("--no-wait", action="store_true", help="Return immediately after spawning searchd.")
    add_json_arg(searchd_start)
    searchd_start.set_defaults(handler=cmd_searchd_start)

    searchd_status = searchd_sub.add_parser(
        "status",
        help="Show semantic search daemon status.",
        description="Show semantic search daemon status.",
    )
    searchd_status.add_argument("--socket", default=None, help="Unix socket path. Defaults to ~/.tapl/searchd.sock.")
    searchd_status.add_argument(
        "--timeout-ms",
        type=positive_int_arg,
        default=None,
        help="Milliseconds to wait for daemon response. Defaults to 250.",
    )
    add_json_arg(searchd_status)
    searchd_status.set_defaults(handler=cmd_searchd_status)

    searchd_stop = searchd_sub.add_parser(
        "stop",
        help="Stop the semantic search daemon.",
        description="Stop the semantic search daemon.",
    )
    searchd_stop.add_argument("--socket", default=None, help="Unix socket path. Defaults to ~/.tapl/searchd.sock.")
    searchd_stop.add_argument(
        "--timeout-ms",
        type=positive_int_arg,
        default=None,
        help="Milliseconds to wait for daemon response. Defaults to 250.",
    )
    add_json_arg(searchd_stop)
    searchd_stop.set_defaults(handler=cmd_searchd_stop)

    searchd_run = searchd_sub.add_parser(
        "run",
        help=argparse.SUPPRESS,
        description="Run the semantic search daemon server loop.",
    )
    searchd_run.add_argument("--socket", default=None, help=argparse.SUPPRESS)
    searchd_run.add_argument("--idle-timeout", type=non_negative_int_arg, default=None, help=argparse.SUPPRESS)
    add_json_arg(searchd_run)
    searchd_run.set_defaults(handler=cmd_searchd_run)

    import_md = sub.add_parser("import-md", help="Import legacy .agent-workflow markdown.")
    import_md.add_argument("--path", type=Path, default=Path(".agent-workflow"), help="Legacy workflow directory.")
    add_dry_run_arg(import_md)
    import_md.add_argument(
        "--migrate-existing",
        action="store_true",
        help="Convert older raw MD-* legacy import runs already stored in the DB.",
    )
    add_json_arg(import_md)
    import_md.set_defaults(handler=cmd_import_md)

    hook = sub.add_parser("hook-event", help="Handle a Codex hook event.")
    hook.add_argument("--event", required=True, help="Codex hook event name.")
    hook.add_argument("--mode", choices=("observe", "enforce"), default="observe", help="Hook handling mode.")
    hook.add_argument("--tool", default=None, help="Tool name for tool hook events.")
    add_json_arg(hook)
    hook.set_defaults(handler=cmd_hook_event)

    return parser


def add_install_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--taplctl-command", default=None, help="Command used by generated Codex hooks.")
    parser.add_argument("--mode", choices=("observe", "enforce"), default=tapl_install.DEFAULT_HOOK_MODE, help="Hook handling mode.")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite static templates and make managed Codex config keys use tapl defaults.",
    )
    add_dry_run_arg(parser)
    add_json_arg(parser)


def positive_int_arg(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a positive integer") from exc
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def non_negative_int_arg(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a non-negative integer") from exc
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be a non-negative integer")
    return parsed


def open_conn(args: argparse.Namespace, *, start: Path | None = None) -> sqlite3.Connection:
    return db.connect(args.db or db.default_db_path(start))


def load_config(args: argparse.Namespace, *, start: Path | None = None) -> tapl_config.TaplConfig:
    return tapl_config.load(args.config, start=start)


def cmd_init(args: argparse.Namespace) -> int:
    conn = open_conn(args)
    payload = {
        "ok": True,
        "db": str(args.db or db.default_db_path()),
        "schema": db.get_meta(conn),
    }
    emit(payload, args.json)
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    conn = open_conn(args)
    payload = {
        "ok": True,
        "version": __version__,
        "db": str(args.db or db.default_db_path()),
        "config": load_config(args).as_dict(),
        "sqlite_version": sqlite3.sqlite_version,
        "sqlite_extension_loading": hasattr(conn, "enable_load_extension"),
        "dependencies": embeddings.dependency_status(),
        "schema": db.get_meta(conn),
    }
    emit(payload, args.json)
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    conn = open_conn(args)
    settings = load_config(args)
    payload = db.status_payload(conn)
    payload["config"] = settings.as_dict()
    payload["plan_task_execute"] = validation.validate_plan_task_execute(
        conn,
        settings.plan_task_execute,
    )
    payload = status_output_payload(
        payload,
        full=args.full,
        include_events=args.include_events,
        events_limit=args.events_limit,
    )
    emit(payload, args.json)
    return 0


STATUS_COMPACT_ITEM_FIELDS = (
    "id",
    "stable_id",
    "kind",
    "title",
    "status",
    "source",
    "archived",
    "created_at",
    "updated_at",
)

STATUS_EVENT_SUMMARY_FIELDS = (
    "id",
    "run_id",
    "event_type",
    "tool_name",
    "mode",
    "message",
    "created_at",
)


def status_output_payload(
    payload: dict[str, Any],
    *,
    full: bool = False,
    include_events: bool = False,
    events_limit: int = 12,
) -> dict[str, Any]:
    plans = list(payload.get("plans") or [])
    tasks = list(payload.get("tasks") or [])
    findings = list(payload.get("findings") or [])
    archive_count = int(payload.get("archive_count") or len(payload.get("archives") or []))
    projected: dict[str, Any] = {
        "schema": payload.get("schema") or {},
        "active_run": payload.get("active_run"),
        "task_counts": payload.get("task_counts") or {},
        "incomplete_tasks": payload.get("incomplete_tasks", 0),
        "counts": {
            "plans": len(plans),
            "tasks": len(tasks),
            "findings": len(findings),
            "archives": archive_count,
        },
        "plans": plans if full else [compact_status_item(item) for item in plans],
        "tasks": tasks if full else [compact_status_item(item) for item in tasks],
        "findings": findings if full else [compact_status_item(item) for item in findings],
    }
    for key in ("config", "plan_task_execute", "approvals"):
        if key in payload:
            projected[key] = payload[key]
    if include_events:
        limit = max(events_limit, 0)
        events = list(payload.get("recent_events") or [])[:limit]
        projected["recent_events"] = [compact_status_event(event) for event in events]
    return projected


def compact_status_item(item: dict[str, Any]) -> dict[str, Any]:
    return {key: item[key] for key in STATUS_COMPACT_ITEM_FIELDS if key in item}


def compact_status_event(event: dict[str, Any]) -> dict[str, Any]:
    return {key: event[key] for key in STATUS_EVENT_SUMMARY_FIELDS if key in event}


def cmd_validate(args: argparse.Namespace) -> int:
    conn = open_conn(args)
    settings = load_config(args)
    meta = db.get_meta(conn)
    plan_task_execute = validation.validate_plan_task_execute(
        conn,
        settings.plan_task_execute,
    )
    payload = {
        "ok": meta.get("schema_version") == str(db.SCHEMA_VERSION) and plan_task_execute["ok"],
        "schema_version": meta.get("schema_version"),
        "active_run": db.row_to_dict(db.active_run(conn)),
        "incomplete_tasks": db.incomplete_task_count(conn),
        "config": settings.as_dict(),
        "plan_task_execute": plan_task_execute,
    }
    emit(payload, args.json)
    return 0 if payload["ok"] else 1


def cmd_context(args: argparse.Namespace) -> int:
    packet = tapl_context.build_context(
        open_conn(args),
        event=args.event,
        settings=load_config(args),
    )
    if args.json:
        print_json(packet)
    else:
        print(tapl_context.format_context(packet))
    return 0


def cmd_run_set(args: argparse.Namespace) -> int:
    if args.summary is None and args.result is None:
        emit(
            {
                "ok": False,
                "error": "provide --summary, --result, or both",
            },
            args.json,
        )
        return 1
    conn = open_conn(args)
    run = db.update_active_run_summary(
        conn,
        request_summary=args.summary,
        result_summary=args.result,
    )
    emit({"ok": True, "active_run": db.row_to_dict(run)}, args.json)
    return 0


def cmd_install_user(args: argparse.Namespace) -> int:
    payload = tapl_install.install_user(
        codex_home=args.codex_home,
        taplctl_command=args.taplctl_command,
        mode=args.mode,
        force=args.force,
        dry_run=args.dry_run,
    )
    emit(payload, args.json)
    return 0


def cmd_install_repo(args: argparse.Namespace) -> int:
    payload = tapl_install.install_repo(
        repo=args.repo,
        taplctl_command=args.taplctl_command,
        mode=args.mode,
        force=args.force,
        dry_run=args.dry_run,
    )
    emit(payload, args.json)
    return 0


def cmd_plan_set(args: argparse.Namespace) -> int:
    conn = open_conn(args)
    settings = load_config(args)
    input_check = validation.validate_plan_input(
        plan_id=args.id,
        settings=settings.plan_task_execute,
    )
    if not input_check["ok"]:
        emit({"ok": False, "plan_task_execute": input_check}, args.json)
        return 1

    item = db.upsert_item(
        conn,
        kind="plan",
        stable_id=args.id,
        title=args.title,
        body="\n".join(part for part in [args.summary, args.body] if part),
        status=args.status,
    )
    emit(
        {
            "ok": True,
            "item": db.row_to_dict(item),
            "plan_task_execute": validation.validate_plan_task_execute(
                conn,
                settings.plan_task_execute,
            ),
        },
        args.json,
    )
    return 0


def cmd_task_set(args: argparse.Namespace) -> int:
    conn = open_conn(args)
    settings = load_config(args)
    existing = db.get_active_task(conn, args.id)
    if existing is None:
        missing = [flag for flag, value in (("--title", args.title), ("--status", args.status)) if value is None]
        if missing:
            missing_text = ", ".join(missing)
            issue = validation.issue(
                "error",
                "task_create_missing_fields",
                f"{args.id} does not exist and is missing required field(s): {missing_text}.",
                "Create a new task with --title and --status, or update an existing task id with changed fields only.",
                stable_id=args.id,
            )
            emit(
                {
                    "ok": False,
                    "error": issue["message"],
                    "plan_task_execute": {
                        "ok": False,
                        "errors": [issue],
                        "warnings": [],
                        "issues": [issue],
                        "guidance": validation.guidance(settings.plan_task_execute),
                    },
                },
                args.json,
            )
            return 1

    def merged_field(name: str) -> str:
        value = getattr(args, name)
        if value is not None:
            return value
        if existing is None:
            return ""
        stored = existing[name]
        return "" if stored is None else str(stored)

    title = merged_field("title")
    status = merged_field("status")
    spec_id = merged_field("spec_id")
    goal = merged_field("goal")
    action = merged_field("action")
    required_subagent = merged_field("required_subagent")
    verification = merged_field("verification")
    result = merged_field("result")
    blocker = merged_field("blocker")
    next_action = merged_field("next_action")

    input_check = validation.validate_task_input(
        task_id=args.id,
        status=status,
        spec_id=spec_id,
        required_subagent=required_subagent,
        settings=settings.plan_task_execute,
    )
    if not input_check["ok"]:
        emit({"ok": False, "plan_task_execute": input_check}, args.json)
        return 1

    item = db.upsert_task(
        conn,
        task_id=args.id,
        title=title,
        status=status,
        spec_id=spec_id,
        goal=goal,
        action=action,
        required_subagent=required_subagent,
        verification=verification,
        result=result,
        blocker=blocker,
        next_action=next_action,
    )
    emit(
        {
            "ok": True,
            "item": db.row_to_dict(item),
            "plan_task_execute": validation.validate_plan_task_execute(
                conn,
                settings.plan_task_execute,
            ),
        },
        args.json,
    )
    return 0


def cmd_finding_add(args: argparse.Namespace) -> int:
    conn = open_conn(args)
    item = db.add_finding(
        conn,
        title=args.title,
        source=args.source,
        finding=args.finding,
        impact=args.impact,
        related_ids=args.related_ids,
    )
    emit({"ok": True, "item": db.row_to_dict(item)}, args.json)
    return 0


def cmd_approval_set(args: argparse.Namespace) -> int:
    approval = db.record_approval(
        open_conn(args),
        kind=args.kind,
        decision=args.decision,
        prompt=args.prompt,
    )
    emit({"ok": True, "approval": db.row_to_dict(approval)}, args.json)
    return 0


def cmd_approval_status(args: argparse.Namespace) -> int:
    status = db.approval_status(open_conn(args), kind=args.kind)
    emit({"ok": True, "approval": status}, args.json)
    return 0


def cmd_approval_list(args: argparse.Namespace) -> int:
    kind = args.kind.strip() or None
    approvals = db.list_approvals(open_conn(args), kind=kind, limit=args.limit)
    emit({"ok": True, "approvals": approvals}, args.json)
    return 0


def cmd_item_show(args: argparse.Namespace) -> int:
    item = db.item_detail(open_conn(args), args.id)
    if item is None:
        emit({"ok": False, "error": f"item not found: {args.id}"}, args.json)
        return 1
    emit({"ok": True, "item": item}, args.json)
    return 0


def cmd_archive_create(args: argparse.Namespace) -> int:
    archive = db.archive_active_run(open_conn(args), slug=args.slug, summary=args.summary)
    emit({"ok": True, "archive": db.row_to_dict(archive)}, args.json)
    return 0


def cmd_archive_list(args: argparse.Namespace) -> int:
    archives = db.list_archives(open_conn(args), limit=args.limit)
    emit({"ok": True, "archives": archives}, args.json)
    return 0


def cmd_archive_show(args: argparse.Namespace) -> int:
    detail = db.archive_detail(open_conn(args), args.id)
    if detail is None:
        emit({"ok": False, "error": f"archive not found: {args.id}"}, args.json)
        return 1
    detail["ok"] = True
    emit(detail, args.json)
    return 0


def cmd_search(args: argparse.Namespace) -> int:
    settings = load_config(args)
    limit = args.limit if args.limit is not None else settings.search.max_results
    payload = embeddings.search(open_conn(args), args.query, limit=limit, search_config=settings.search)
    payload["ok"] = True
    emit(payload, args.json)
    return 0


def cmd_reindex(args: argparse.Namespace) -> int:
    payload = embeddings.reindex(open_conn(args), dry_run=args.dry_run)
    emit(payload, args.json)
    return 0 if payload.get("ok") else 1


def cmd_searchd_start(args: argparse.Namespace) -> int:
    settings = load_config(args)
    payload = searchd.start(
        settings.search,
        socket_path=args.socket,
        model_idle_timeout_seconds=args.idle_timeout,
        timeout_ms=args.timeout_ms,
        wait=not args.no_wait,
    )
    payload["config"] = settings.search.as_dict()
    emit(payload, args.json)
    return 0 if payload.get("ok") else 1


def cmd_searchd_status(args: argparse.Namespace) -> int:
    settings = load_config(args)
    payload = searchd.status(settings.search, socket_path=args.socket, timeout_ms=args.timeout_ms)
    payload["config"] = settings.search.as_dict()
    emit(payload, args.json)
    return 0


def cmd_searchd_stop(args: argparse.Namespace) -> int:
    settings = load_config(args)
    payload = searchd.stop(settings.search, socket_path=args.socket, timeout_ms=args.timeout_ms)
    payload["config"] = settings.search.as_dict()
    emit(payload, args.json)
    return 0 if payload.get("ok") else 1


def cmd_searchd_run(args: argparse.Namespace) -> int:
    settings = load_config(args)
    payload = searchd.run_server(
        settings.search,
        socket_path=args.socket,
        model_idle_timeout_seconds=args.idle_timeout,
    )
    emit(payload, args.json)
    return 0 if payload.get("ok") else 1


def cmd_import_md(args: argparse.Namespace) -> int:
    payload = importer.import_markdown(
        open_conn(args),
        path=args.path,
        dry_run=args.dry_run,
        migrate_existing=args.migrate_existing,
    )
    emit(payload, args.json)
    return 0 if payload.get("ok") else 1


def cmd_hook_event(args: argparse.Namespace) -> int:
    raw = sys.stdin.read() if not sys.stdin.isatty() else ""
    payload: dict[str, Any] = {}
    if raw.strip():
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                payload = parsed
        except json.JSONDecodeError:
            payload = {"raw": raw}

    start = payload_cwd(payload)
    if args.db is None and args.config is None:
        tapl_install.auto_install_if_needed(start=start)
    settings = load_config(args, start=start)
    outcome = hooks.handle_event(
        open_conn(args, start=start),
        event=args.event,
        mode=args.mode,
        tool=args.tool,
        payload=payload,
        tapl_settings=settings,
        plan_task_settings=settings.plan_task_execute,
    )
    emit_hook_outcome(outcome, args.json)
    return 2 if outcome.get("block") else 0


def emit_hook_outcome(outcome: dict[str, Any], as_json: bool) -> None:
    if as_json:
        print_json(outcome)
        return

    if outcome.get("event") == "Stop":
        if outcome.get("block"):
            print_json(
                {
                    "decision": "block",
                    "reason": outcome.get("message") or "tapl blocked Stop hook.",
                }
            )
        return

    if outcome.get("message"):
        stream = sys.stderr if outcome.get("block") else sys.stdout
        print(outcome["message"], file=stream)


def payload_cwd(payload: dict[str, Any]) -> Path | None:
    value = payload.get("cwd")
    if isinstance(value, str) and value.strip():
        return Path(value).expanduser()
    return None


def emit(payload: dict[str, Any], as_json: bool) -> None:
    if as_json:
        print_json(payload)
        return
    print(humanize(payload))


def print_json(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


def humanize(payload: dict[str, Any]) -> str:
    if "error" in payload:
        return f"error: {payload['error']}"
    if "plan_task_execute" in payload and not payload.get("ok", True):
        return validation.format_issues(payload["plan_task_execute"])
    if "db" in payload:
        return f"tapl db: {payload['db']}"
    if "install" in payload:
        lines = [f"tapl install {payload['install']}: {payload.get('repo') or payload.get('codex_home')}"]
        lines.extend(f"{item['action']}: {item['path']}" for item in payload.get("files", []))
        return "\n".join(lines)
    if "archive" in payload and "items" in payload:
        archive = payload["archive"]
        lines = [f"{archive['created_at']} {archive['slug']}: {archive['summary']}"]
        lines.extend(f"{item['kind']} {item['stable_id']} {item['title']}" for item in payload["items"])
        return "\n".join(lines)
    if "active_run" in payload and "task_counts" in payload:
        return humanize_status(payload)
    if "item" in payload:
        item = payload["item"]
        return f"{item['kind']} {item['stable_id']} {item['title']}"
    if "approval" in payload:
        approval = payload["approval"]
        return f"approval {approval.get('kind', '')}: {approval.get('state') or approval.get('decision')}"
    if "approvals" in payload:
        approvals = payload["approvals"]
        return "\n".join(
            f"{item['decided_at']} {item['kind']} {item['decision']}: {item['prompt']}" for item in approvals
        ) or "no approvals"
    if "archives" in payload:
        return "\n".join(f"{item['created_at']} {item['slug']}: {item['summary']}" for item in payload["archives"]) or "no archives"
    if "results" in payload:
        return "\n".join(f"{item['stable_id']} {item['title']}" for item in payload["results"]) or "no results"
    if "active_run" in payload:
        run = payload["active_run"] or {}
        request = run.get("request_summary") or "active"
        result = run.get("result_summary") or ""
        return f"active run: {request}" + (f"\nresult: {result}" if result else "")
    return "ok" if payload.get("ok") else str(payload)


def humanize_status(payload: dict[str, Any]) -> str:
    run = payload.get("active_run")
    if isinstance(run, dict):
        request = run.get("request_summary") or "active"
        lines = [f"active run: {request}"]
    else:
        lines = ["active run: none"]

    task_counts = payload.get("task_counts") if isinstance(payload.get("task_counts"), dict) else {}
    plans = payload.get("plans") if isinstance(payload.get("plans"), list) else []
    tasks = payload.get("tasks") if isinstance(payload.get("tasks"), list) else []
    findings = payload.get("findings") if isinstance(payload.get("findings"), list) else []
    incomplete = payload.get("incomplete_tasks", 0)

    lines.append(
        f"plans: {len(plans)}, tasks: {len(tasks)}, findings: {len(findings)}, incomplete tasks: {incomplete}"
    )
    if task_counts:
        ordered = [f"{status}={task_counts.get(status, 0)}" for status in db.TASK_STATUSES]
        lines.append("task counts: " + ", ".join(ordered))

    plan_task_execute = payload.get("plan_task_execute")
    if isinstance(plan_task_execute, dict):
        issue_text = validation.format_issues(plan_task_execute, max_items=3)
        if issue_text:
            lines.append(issue_text)
    return "\n".join(lines)
