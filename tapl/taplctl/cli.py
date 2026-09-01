"""Management-only command line interface for TAPL.

Workflow operations are exposed by the dedicated ``tapl-mcp`` server and hook
events by ``tapl-hook``.  This module intentionally contains only installation,
configuration, health, viewer, update, and semantic-index management commands.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any

from . import (
    __version__,
    config as tapl_config,
    config_editor,
    db,
    embeddings,
    searchd,
    updater,
    viewer,
)
from . import install as tapl_install


JSON_HELP = "Print JSON output."
AGENT_HELP = "Print agent-optimized XML-like output."
DRY_RUN_HELP = "Preview changes without writing files."

_AGENT_SKIP_KEYS = frozenset(
    {
        "archived",
        "archived_at",
        "archive_created_at",
        "body",
        "config",
        "created_at",
        "errors",
        "payload_json",
        "raw_text",
        "run_id",
        "schema",
        "search_config",
        "source_scores",
        "updated_at",
        "warnings",
    }
)
_AGENT_LIST_ITEM_TAGS = {
    "dependencies": "dependency",
    "files": "file",
    "issues": "issue",
    "results": "result",
}


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    if not hasattr(args, "handler"):
        parser.print_help()
        return 2
    try:
        auto_install_before_handler(args)
        return int(args.handler(args) or 0)
    except updater.UpdateError as exc:
        emit_update_error(args, exc)
        return 1
    except Exception as exc:
        if getattr(args, "json", False):
            print_json({"ok": False, "error": str(exc)})
        elif getattr(args, "agent", False):
            print(agent_error(str(exc)))
        else:
            print(f"taplctl: {exc}", file=sys.stderr)
        return 1


def auto_install_before_handler(args: argparse.Namespace) -> None:
    if not should_skip_auto_install(args):
        tapl_install.auto_install_if_needed()


def should_skip_auto_install(args: argparse.Namespace) -> bool:
    command = getattr(args, "command", None)
    if args.db is not None or args.config is not None:
        return True
    if command in {None, "config", "init", "install", "update", "viewer"}:
        return True
    return command == "searchd" and getattr(args, "searchd_command", None) == "run"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="taplctl",
        description=(
            "Manage TAPL installation, configuration, health, indexing, and local services."
        ),
        epilog="Agent workflow operations are available through the dedicated `tapl-mcp` server.",
    )
    parser.add_argument("--db", type=Path, default=None, help="Path to TAPL SQLite DB.")
    parser.add_argument("--config", type=Path, default=None, help="Path to TAPL TOML config.")
    parser.add_argument(
        "--version",
        action="version",
        version=f"taplctl {__version__}",
        help="Show version and exit.",
    )
    sub = parser.add_subparsers(dest="command")

    init = sub.add_parser("init", help="Initialize the TAPL database.")
    init.add_argument(
        "--workspace-root",
        type=Path,
        default=None,
        help="Explicit workspace root where .tapl/tapl.db is initialized.",
    )
    add_agent_output_args(init)
    init.set_defaults(handler=cmd_init)

    doctor = sub.add_parser("doctor", help="Check TAPL runtime dependencies.")
    add_agent_output_args(doctor)
    doctor.set_defaults(handler=cmd_doctor)

    update = sub.add_parser(
        "update",
        help="Check for or install a newer installer-managed release.",
        description=(
            "Check for or install a newer taplctl release for curl | sh or "
            "PowerShell installations."
        ),
    )
    update.add_argument("--check", action="store_true", help="Check without installing.")
    add_agent_output_args(update)
    update.set_defaults(handler=cmd_update)

    install = sub.add_parser("install", help="Install TAPL hooks and repo-local state.")
    install_sub = install.add_subparsers(dest="install_command")
    install_user = install_sub.add_parser("user", help="Install user-global Codex hooks.")
    install_user.add_argument("--codex-home", type=Path, default=None)
    add_install_common_args(install_user)
    install_user.set_defaults(handler=cmd_install_user)
    install_repo = install_sub.add_parser("repo", help="Install repo-local Codex hooks and state.")
    install_repo.add_argument("--repo", type=Path, default=None)
    add_install_common_args(install_repo)
    install_repo.set_defaults(handler=cmd_install_repo)

    config_cmd = sub.add_parser(
        "config",
        help="Edit TAPL's TOML configuration.",
        description=(
            "Set or unset supported .tapl/config.toml values without rewriting "
            "comments or unrelated settings."
        ),
        epilog=config_key_help(),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    config_sub = config_cmd.add_subparsers(dest="config_command", required=True)
    config_set = config_sub.add_parser(
        "set",
        help="Set a supported configuration value.",
        description=(
            "Set KEY to VALUE. VALUE uses TOML syntax; enum strings such as hybrid "
            "may be passed without quotes."
        ),
        epilog=config_key_help(include_examples=True),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    config_set.add_argument("key", metavar="KEY", help="Supported dot-separated key.")
    config_set.add_argument("value", metavar="VALUE", help="Value in the format listed below.")
    add_agent_output_args(config_set)
    config_set.set_defaults(handler=cmd_config_set)

    config_unset = config_sub.add_parser(
        "unset",
        help="Remove a supported configuration value.",
        description=(
            "Remove KEY so TAPL's built-in default applies. The resulting complete "
            "configuration must remain valid."
        ),
        epilog=config_key_help(include_examples=True),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    config_unset.add_argument("key", metavar="KEY", help="Supported dot-separated key.")
    add_agent_output_args(config_unset)
    config_unset.set_defaults(handler=cmd_config_unset)

    viewer_cmd = sub.add_parser("viewer", help="Serve the workflow viewer locally.")
    viewer_cmd.add_argument(
        "--port",
        type=viewer_port_arg,
        default=viewer.DEFAULT_PORT,
        help=f"Local TCP port. Defaults to {viewer.DEFAULT_PORT}.",
    )
    viewer_cmd.add_argument(
        "--allowed-origin",
        dest="allowed_origins",
        action="append",
        type=viewer_origin_arg,
        default=None,
        help=(
            "Additional HTTP(S) browser origin allowed to call the viewer API. "
            "Repeat for multiple origins."
        ),
    )
    viewer_cmd.set_defaults(handler=cmd_viewer)

    reindex = sub.add_parser("reindex", help="Build the optional semantic index.")
    add_dry_run_arg(reindex)
    add_agent_output_args(reindex)
    reindex.set_defaults(handler=cmd_reindex)

    searchd_cmd = sub.add_parser("searchd", help="Manage the semantic search daemon.")
    searchd_sub = searchd_cmd.add_subparsers(dest="searchd_command")

    searchd_start = searchd_sub.add_parser("start", help="Start the semantic search daemon.")
    searchd_start.add_argument("--socket", default=None, help="Unix socket path.")
    searchd_start.add_argument(
        "--idle-timeout",
        type=non_negative_int_arg,
        default=None,
        help="Seconds before unloading an idle model.",
    )
    searchd_start.add_argument(
        "--timeout-ms",
        type=positive_int_arg,
        default=None,
        help="Milliseconds to wait for daemon readiness.",
    )
    searchd_start.add_argument("--no-wait", action="store_true")
    add_agent_output_args(searchd_start)
    searchd_start.set_defaults(handler=cmd_searchd_start)

    searchd_status = searchd_sub.add_parser("status", help="Show daemon status.")
    searchd_status.add_argument("--socket", default=None)
    searchd_status.add_argument("--timeout-ms", type=positive_int_arg, default=None)
    add_agent_output_args(searchd_status)
    searchd_status.set_defaults(handler=cmd_searchd_status)

    searchd_stop = searchd_sub.add_parser("stop", help="Stop the daemon.")
    searchd_stop.add_argument("--socket", default=None)
    searchd_stop.add_argument("--timeout-ms", type=positive_int_arg, default=None)
    add_agent_output_args(searchd_stop)
    searchd_stop.set_defaults(handler=cmd_searchd_stop)

    searchd_run = searchd_sub.add_parser("run", help=argparse.SUPPRESS)
    searchd_run.add_argument("--socket", default=None, help=argparse.SUPPRESS)
    searchd_run.add_argument(
        "--idle-timeout",
        type=non_negative_int_arg,
        default=None,
        help=argparse.SUPPRESS,
    )
    add_agent_output_args(searchd_run)
    searchd_run.set_defaults(handler=cmd_searchd_run)
    return parser


def add_agent_output_args(parser: argparse.ArgumentParser) -> None:
    output = parser.add_mutually_exclusive_group()
    output.add_argument("--json", action="store_true", help=JSON_HELP)
    output.add_argument("--agent", action="store_true", help=AGENT_HELP)


def config_key_help(*, include_examples: bool = False) -> str:
    lines = [
        "Target file:",
        "  Use `taplctl --config PATH config ...` to select a file explicitly.",
        "  Otherwise TAPL prefers repo-local .tapl/config.toml, then ~/.tapl/config.toml.",
        "",
        "Supported KEY values:",
    ]
    for spec in tapl_config.EDITABLE_CONFIG_KEYS:
        details = spec.description
        if spec.allowed:
            details += f" Allowed: {', '.join(spec.allowed)}."
        lines.append(f"  {spec.key} {spec.value_name}")
        lines.append(f"      {details}")
    lines.extend(
        (
            "",
            "TOML_ARRAY examples: [\"https://tapl.example.com\"] or [\"high\", \"xhigh\"].",
            "Profile arrays use inline tables; each candidate must be allowlisted in subagents.models.",
        )
    )
    if include_examples:
        lines.extend(
            (
                "",
                "Examples:",
                "  taplctl config set search.mode hybrid",
                "  taplctl config set viewer.allowed_origins '[\"https://tapl.example.com\"]'",
                "  taplctl config set subagents.models.gpt-5.6-sol '[\"high\", \"xhigh\"]'",
                "  taplctl config set subagents.profiles '[{ name = \"routine\", characteristics = \"small, local changes\", delegation_bias = \"prefer\", candidates = [{ model = \"gpt-5.6-luna\", reasoning_effort = \"xhigh\" }, { model = \"gpt-5.6-terra\", reasoning_effort = \"high\" }] }]'",
                "  taplctl config unset search.mode",
            )
        )
    return "\n".join(lines)


def add_dry_run_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--dry-run", action="store_true", help=DRY_RUN_HELP)


def add_install_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--taplctl-command",
        default=None,
        help="taplctl executable used to locate sibling tapl-mcp and tapl-hook commands.",
    )
    parser.add_argument(
        "--mode",
        choices=("observe", "enforce"),
        default=tapl_install.DEFAULT_HOOK_MODE,
        help="Hook handling mode.",
    )
    parser.add_argument(
        "--tapl-config-policy",
        choices=tapl_install.TAPL_CONFIG_POLICIES,
        default=tapl_install.TAPL_CONFIG_POLICY_PROMPT,
        help="How to handle existing TAPL config when the installed version changes.",
    )
    parser.add_argument("--force", action="store_true", help="Overwrite managed templates and config.")
    add_dry_run_arg(parser)
    add_agent_output_args(parser)


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


def viewer_port_arg(value: str) -> int:
    try:
        return viewer.parse_port(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def viewer_origin_arg(value: str) -> str:
    try:
        return viewer.parse_allowed_origin(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def open_conn(args: argparse.Namespace, *, start: Path | None = None) -> sqlite3.Connection:
    return db.connect(args.db or db.default_db_path(start))


def load_config(args: argparse.Namespace, *, start: Path | None = None) -> tapl_config.TaplConfig:
    return tapl_config.load(args.config, start=start)


def cmd_init(args: argparse.Namespace) -> int:
    if args.workspace_root is not None:
        if args.db is not None:
            raise ValueError("--workspace-root cannot be combined with --db")
        initialized = db.initialize_workspace(args.workspace_root)
        conn = db.connect(initialized["db"])
        try:
            payload = {"ok": True, **initialized, "schema": db.get_meta(conn)}
        finally:
            conn.close()
    else:
        conn = open_conn(args)
        try:
            payload = {
                "ok": True,
                "db": str(args.db or db.default_db_path()),
                "schema": db.get_meta(conn),
            }
        finally:
            conn.close()
    emit(payload, args.json, args.agent)
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    conn = open_conn(args)
    try:
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
    finally:
        conn.close()
    emit(payload, args.json, args.agent)
    return 0


def cmd_update(args: argparse.Namespace) -> int:
    payload = updater.check_for_update() if args.check else updater.update_installation()
    if args.json:
        print_json(payload)
    elif args.agent:
        print(agent_output(payload))
    else:
        print(humanize_update(payload))
    return 0


def cmd_viewer(args: argparse.Namespace) -> int:
    workspace = None if args.db is not None else viewer.existing_workspace()
    selected_db = args.db.expanduser().resolve() if args.db is not None else None
    if workspace is not None:
        selected_db = workspace / db.DEFAULT_DB_RELATIVE
    settings = load_config(args, start=workspace)
    allowed_origins = tuple(
        dict.fromkeys(
            (*settings.viewer.allowed_origins, *(args.allowed_origins or ()))
        )
    )
    viewer.serve(
        port=args.port,
        allowed_origins=allowed_origins,
        default_db=selected_db,
        default_workspace=workspace,
    )
    return 0


def cmd_install_user(args: argparse.Namespace) -> int:
    payload = tapl_install.install_user(
        codex_home=args.codex_home,
        taplctl_command=args.taplctl_command,
        mode=args.mode,
        force=args.force,
        dry_run=args.dry_run,
        tapl_config_policy=args.tapl_config_policy,
    )
    emit(payload, args.json, args.agent)
    return 0


def cmd_install_repo(args: argparse.Namespace) -> int:
    payload = tapl_install.install_repo(
        repo=args.repo,
        taplctl_command=args.taplctl_command,
        mode=args.mode,
        force=args.force,
        dry_run=args.dry_run,
        tapl_config_policy=args.tapl_config_policy,
    )
    emit(payload, args.json, args.agent)
    return 0


def cmd_config_set(args: argparse.Namespace) -> int:
    path = tapl_config.resolve_config_path(args.config)
    result = config_editor.set_value(path, args.key, args.value)
    emit(
        {
            "ok": True,
            "config_action": "set",
            "path": result.path,
            "key": result.key,
            "value": result.value,
            "changed": result.changed,
        },
        args.json,
        args.agent,
    )
    return 0


def cmd_config_unset(args: argparse.Namespace) -> int:
    path = tapl_config.resolve_config_path(args.config)
    result = config_editor.unset_value(path, args.key)
    emit(
        {
            "ok": True,
            "config_action": "unset",
            "path": result.path,
            "key": result.key,
            "changed": result.changed,
        },
        args.json,
        args.agent,
    )
    return 0


def cmd_reindex(args: argparse.Namespace) -> int:
    conn = open_conn(args)
    try:
        payload = embeddings.reindex(conn, dry_run=args.dry_run)
    finally:
        conn.close()
    emit(payload, args.json, args.agent)
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
    emit(payload, args.json, args.agent)
    return 0 if payload.get("ok") else 1


def cmd_searchd_status(args: argparse.Namespace) -> int:
    settings = load_config(args)
    payload = searchd.status(settings.search, socket_path=args.socket, timeout_ms=args.timeout_ms)
    payload["config"] = settings.search.as_dict()
    emit(payload, args.json, args.agent)
    return 0


def cmd_searchd_stop(args: argparse.Namespace) -> int:
    settings = load_config(args)
    payload = searchd.stop(settings.search, socket_path=args.socket, timeout_ms=args.timeout_ms)
    payload["config"] = settings.search.as_dict()
    emit(payload, args.json, args.agent)
    return 0 if payload.get("ok") else 1


def cmd_searchd_run(args: argparse.Namespace) -> int:
    settings = load_config(args)
    payload = searchd.run_server(
        settings.search,
        socket_path=args.socket,
        model_idle_timeout_seconds=args.idle_timeout,
    )
    emit(payload, args.json, args.agent)
    return 0 if payload.get("ok") else 1


def emit_update_error(args: argparse.Namespace, error: updater.UpdateError) -> None:
    payload = error.as_dict()
    if getattr(args, "json", False):
        print_json(payload)
    elif getattr(args, "agent", False):
        print(agent_output(payload))
    else:
        print(humanize_update_error(error), file=sys.stderr)


def humanize_update(payload: dict[str, Any]) -> str:
    status = payload.get("status")
    current = str(payload.get("current_version") or "unknown")
    latest = str(payload.get("latest_version") or current)
    if status == "update-available":
        return f"Update available: taplctl {current} → {latest}. Run taplctl update to install it."
    if status == "up-to-date":
        return f"taplctl is up to date ({current})."
    if status == "current-newer":
        return f"Installed taplctl ({current}) is newer than the published release ({latest})."
    if status == "updated":
        previous = str(payload.get("previous_version") or current)
        return f"Updated taplctl: {previous} → {current}."
    return f"taplctl update: {status or 'completed'} (current version: {current})."


def humanize_update_error(error: updater.UpdateError) -> str:
    if error.code == "unsupported_installation":
        return (
            "taplctl update is available only for installations made with the official "
            "curl | sh or PowerShell installer. For Homebrew, run `brew upgrade taplctl` "
            "(or `brew upgrade taplctl-semantic`); otherwise use the original install method."
        )
    return f"taplctl update failed ({error.code}): {error}"


def emit(payload: dict[str, Any], as_json: bool, as_agent: bool = False) -> None:
    if as_json:
        print_json(payload)
    elif as_agent:
        print(agent_output(payload))
    else:
        print(humanize(payload))


def print_json(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


def humanize(payload: dict[str, Any]) -> str:
    if "error" in payload:
        return f"error: {payload['error']}"
    if "db" in payload:
        return f"tapl db: {payload['db']}"
    if "install" in payload:
        lines = [f"tapl install {payload['install']}: {payload.get('repo') or payload.get('codex_home')}"]
        lines.extend(f"{item['action']}: {item['path']}" for item in payload.get("files", []))
        return "\n".join(lines)
    if "config_action" in payload:
        state = "updated" if payload.get("changed") else "unchanged"
        return (
            f"config {payload['config_action']} {payload.get('key')}: {state} "
            f"({payload.get('path')})"
        )
    if "running" in payload:
        state = "running" if payload.get("running") else "stopped"
        return f"searchd {state}: {payload.get('socket_path', '')}".rstrip()
    if "results" in payload:
        return f"indexed {len(payload.get('results') or [])} item(s)"
    return "ok" if payload.get("ok") else str(payload)


def agent_error(message: str) -> str:
    return f"<tapl_error>\n  <message>{agent_escape(message)}</message>\n</tapl_error>"


def agent_output(payload: dict[str, Any], root_tag: str = "tapl_output") -> str:
    lines = [f"<{root_tag}>"]
    for key, value in payload.items():
        append_agent_node(lines, 1, key, value)
    lines.append(f"</{root_tag}>")
    return "\n".join(lines)


def append_agent_node(lines: list[str], depth: int, tag: str, value: Any) -> None:
    if tag in _AGENT_SKIP_KEYS or not agent_value_present(value):
        return
    tag_name = agent_tag_name(tag)
    if isinstance(value, dict):
        section: list[str] = []
        for key, child in value.items():
            append_agent_node(section, depth + 1, str(key), child)
        if section:
            indent = "  " * depth
            lines.extend((f"{indent}<{tag_name}>", *section, f"{indent}</{tag_name}>"))
        return
    if isinstance(value, list):
        section = []
        item_tag = _AGENT_LIST_ITEM_TAGS.get(tag, "item")
        for child in value:
            append_agent_node(section, depth + 1, item_tag, child)
        if section:
            indent = "  " * depth
            lines.extend((f"{indent}<{tag_name}>", *section, f"{indent}</{tag_name}>"))
        return
    lines.append(f"{'  ' * depth}<{tag_name}>{agent_escape(value)}</{tag_name}>")


def agent_value_present(value: Any) -> bool:
    return value is not None and value != "" and value != [] and value != {}


def agent_tag_name(value: str) -> str:
    normalized = re.sub(r"[^\w.]+", "_", value.replace("-", "_"), flags=re.UNICODE).strip("_")
    if not normalized:
        return "field"
    return f"field_{normalized}" if normalized[0].isdigit() or normalized[0] == "." else normalized


def agent_escape(value: Any) -> str:
    text = "true" if value is True else "false" if value is False else str(value)
    return html.escape(text, quote=False)


if __name__ == "__main__":
    raise SystemExit(main())
