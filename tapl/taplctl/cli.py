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
    validation,
)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "handler"):
        parser.print_help()
        return 2
    try:
        return int(args.handler(args) or 0)
    except Exception as exc:
        if getattr(args, "json", False):
            print_json({"ok": False, "error": str(exc)})
        else:
            print(f"taplctl: {exc}", file=sys.stderr)
        return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="taplctl")
    parser.add_argument("--db", type=Path, default=None, help="Path to tapl SQLite DB.")
    parser.add_argument("--config", type=Path, default=None, help="Path to tapl TOML config.")
    parser.add_argument("--version", action="version", version=f"taplctl {__version__}")
    sub = parser.add_subparsers(dest="command")

    init = sub.add_parser("init", help="Initialize the tapl database.")
    init.add_argument("--json", action="store_true")
    init.set_defaults(handler=cmd_init)

    doctor = sub.add_parser("doctor", help="Check tapl runtime dependencies.")
    doctor.add_argument("--json", action="store_true")
    doctor.set_defaults(handler=cmd_doctor)

    status = sub.add_parser("status", help="Show active workflow state.")
    status.add_argument("--json", action="store_true")
    status.add_argument("--full", action="store_true", help="Include full plan/task/finding item details.")
    status.add_argument(
        "--include-events",
        action="store_true",
        help="Include recent hook event summaries. Event payloads are not included.",
    )
    status.add_argument("--events-limit", type=int, default=12, help="Recent hook events to include.")
    status.set_defaults(handler=cmd_status)

    validate = sub.add_parser("validate", help="Validate tapl database state.")
    validate.add_argument("--json", action="store_true")
    validate.set_defaults(handler=cmd_validate)

    context_cmd = sub.add_parser("context", help="Show lifecycle context for Codex.")
    context_cmd.add_argument("--event", default="Manual")
    context_cmd.add_argument("--json", action="store_true")
    context_cmd.set_defaults(handler=cmd_context)

    install = sub.add_parser("install", help="Install tapl workflow hooks and repo-local state.")
    install_sub = install.add_subparsers(dest="install_command")
    install_user = install_sub.add_parser("user", help="Install user-global Codex hooks.")
    install_user.add_argument("--codex-home", type=Path, default=None)
    add_install_common_args(install_user)
    install_user.set_defaults(handler=cmd_install_user)
    install_repo = install_sub.add_parser("repo", help="Install repo-local Codex hooks, config, and DB.")
    install_repo.add_argument("--repo", type=Path, default=None)
    add_install_common_args(install_repo)
    install_repo.set_defaults(handler=cmd_install_repo)

    plan = sub.add_parser("plan", help="Manage plan items.")
    plan_sub = plan.add_subparsers(dest="plan_command")
    plan_upsert = plan_sub.add_parser("upsert")
    plan_upsert.add_argument("--id", default="PLAN-001")
    plan_upsert.add_argument("--title", default="Plan")
    plan_upsert.add_argument("--summary", default="")
    plan_upsert.add_argument("--body", default="")
    plan_upsert.add_argument("--status", default="Draft")
    plan_upsert.add_argument("--json", action="store_true")
    plan_upsert.set_defaults(handler=cmd_plan_upsert)

    task = sub.add_parser("task", help="Manage tasks.")
    task_sub = task.add_subparsers(dest="task_command")
    task_upsert = task_sub.add_parser("upsert")
    task_upsert.add_argument("--id", required=True)
    task_upsert.add_argument("--title", required=True)
    task_upsert.add_argument("--status", required=True, choices=db.TASK_STATUSES)
    task_upsert.add_argument("--spec-id", default="")
    task_upsert.add_argument("--goal", default="")
    task_upsert.add_argument("--action", default="")
    task_upsert.add_argument("--required-subagent", default="")
    task_upsert.add_argument("--verification", default="")
    task_upsert.add_argument("--result", default="")
    task_upsert.add_argument("--blocker", default="")
    task_upsert.add_argument("--next-action", default="")
    task_upsert.add_argument("--json", action="store_true")
    task_upsert.set_defaults(handler=cmd_task_upsert)

    finding = sub.add_parser("finding", help="Manage findings.")
    finding_sub = finding.add_subparsers(dest="finding_command")
    finding_add = finding_sub.add_parser("add")
    finding_add.add_argument("--title", required=True)
    finding_add.add_argument("--source", default="")
    finding_add.add_argument("--finding", default="")
    finding_add.add_argument("--impact", default="")
    finding_add.add_argument("--related-ids", default="")
    finding_add.add_argument("--json", action="store_true")
    finding_add.set_defaults(handler=cmd_finding_add)

    item = sub.add_parser("item", help="Inspect workflow items.")
    item_sub = item.add_subparsers(dest="item_command")
    item_show = item_sub.add_parser("show")
    item_show.add_argument("--id", type=int, required=True)
    item_show.add_argument("--json", action="store_true")
    item_show.set_defaults(handler=cmd_item_show)

    archive = sub.add_parser("archive", help="Manage archives.")
    archive_sub = archive.add_subparsers(dest="archive_command")
    archive_create = archive_sub.add_parser("create")
    archive_create.add_argument("--slug", required=True)
    archive_create.add_argument("--summary", default="")
    archive_create.add_argument("--json", action="store_true")
    archive_create.set_defaults(handler=cmd_archive_create)
    archive_list = archive_sub.add_parser("list")
    archive_list.add_argument("--limit", type=int, default=None)
    archive_list.add_argument("--json", action="store_true")
    archive_list.set_defaults(handler=cmd_archive_list)
    archive_show = archive_sub.add_parser("show")
    archive_show.add_argument("--id", required=True)
    archive_show.add_argument("--json", action="store_true")
    archive_show.set_defaults(handler=cmd_archive_show)

    search = sub.add_parser("search", help="Search workflow state and archive history.")
    search.add_argument("query")
    search.add_argument("--limit", type=int, default=10)
    search.add_argument("--json", action="store_true")
    search.set_defaults(handler=cmd_search)

    reindex = sub.add_parser("reindex", help="Build semantic index when optional deps are installed.")
    reindex.add_argument("--dry-run", action="store_true")
    reindex.add_argument("--json", action="store_true")
    reindex.set_defaults(handler=cmd_reindex)

    import_md = sub.add_parser("import-md", help="Import legacy .agent-workflow markdown.")
    import_md.add_argument("--path", type=Path, default=Path(".agent-workflow"))
    import_md.add_argument("--dry-run", action="store_true")
    import_md.add_argument(
        "--migrate-existing",
        action="store_true",
        help="Convert older raw MD-* legacy import runs already stored in the DB.",
    )
    import_md.add_argument("--json", action="store_true")
    import_md.set_defaults(handler=cmd_import_md)

    hook = sub.add_parser("hook-event", help="Handle a Codex hook event.")
    hook.add_argument("--event", required=True)
    hook.add_argument("--mode", choices=("observe", "enforce"), default="observe")
    hook.add_argument("--tool", default=None)
    hook.add_argument("--json", action="store_true")
    hook.set_defaults(handler=cmd_hook_event)

    return parser


def add_install_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--taplctl-command", default=None, help="Command used by generated Codex hooks.")
    parser.add_argument("--mode", choices=("observe", "enforce"), default=tapl_install.DEFAULT_HOOK_MODE)
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite static templates and make managed Codex config keys use tapl defaults.",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")


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
    for key in ("config", "plan_task_execute"):
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


def cmd_plan_upsert(args: argparse.Namespace) -> int:
    conn = open_conn(args)
    settings = load_config(args)
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


def cmd_task_upsert(args: argparse.Namespace) -> int:
    conn = open_conn(args)
    settings = load_config(args)
    input_check = validation.validate_task_input(
        task_id=args.id,
        status=args.status,
        required_subagent=args.required_subagent,
        settings=settings.plan_task_execute,
    )
    if not input_check["ok"]:
        emit({"ok": False, "plan_task_execute": input_check}, args.json)
        return 1

    item = db.upsert_task(
        conn,
        task_id=args.id,
        title=args.title,
        status=args.status,
        spec_id=args.spec_id,
        goal=args.goal,
        action=args.action,
        required_subagent=args.required_subagent,
        verification=args.verification,
        result=args.result,
        blocker=args.blocker,
        next_action=args.next_action,
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
    payload = embeddings.search(open_conn(args), args.query, limit=args.limit, search_config=settings.search)
    payload["ok"] = True
    emit(payload, args.json)
    return 0


def cmd_reindex(args: argparse.Namespace) -> int:
    payload = embeddings.reindex(open_conn(args), dry_run=args.dry_run)
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
    if "archives" in payload:
        return "\n".join(f"{item['created_at']} {item['slug']}: {item['summary']}" for item in payload["archives"]) or "no archives"
    if "results" in payload:
        return "\n".join(f"{item['stable_id']} {item['title']}" for item in payload["results"]) or "no results"
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
