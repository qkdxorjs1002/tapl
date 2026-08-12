"""Dedicated, self-contained command-line entry point for TAPL hook events."""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
from pathlib import Path
from typing import Any

from . import config as tapl_config
from . import db, hooks
from . import install as tapl_install


JSON_HELP = "Print JSON output."
AGENT_HELP = "Print agent-optimized XML-like output."
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
    "active_batches": "batch",
    "active_executions": "execution",
    "approvals": "approval",
    "archives": "archive",
    "executions": "execution",
    "files": "file",
    "findings": "finding",
    "instructions": "instruction",
    "issues": "issue",
    "items": "item",
    "next_actions": "next_action",
    "plans": "plan",
    "recipes": "recipe",
    "recommendations": "recommendation",
    "results": "result",
    "tasks": "task",
    "updated_fields": "field",
    "validation_issues": "validation_issue",
    "workflow_guidance": "guidance",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tapl-hook",
        description="Handle one Codex hook event through TAPL.",
    )
    parser.add_argument("--event", required=True, help="Codex hook event name.")
    parser.add_argument(
        "--mode",
        choices=("observe", "enforce"),
        default="observe",
        help="Hook handling mode.",
    )
    parser.add_argument("--tool", default=None, help="Tool name for tool hook events.")
    parser.add_argument("--db", type=Path, default=None, help="Path to tapl SQLite DB.")
    parser.add_argument("--config", type=Path, default=None, help="Path to tapl TOML config.")
    output = parser.add_mutually_exclusive_group()
    output.add_argument("--json", action="store_true", help=JSON_HELP)
    output.add_argument("--agent", action="store_true", help=AGENT_HELP)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(sys.argv[1:] if argv is None else argv)
    try:
        return _handle_hook(args)
    except Exception as exc:
        _emit_error(str(exc), as_json=args.json, as_agent=args.agent)
        return 1


def _handle_hook(args: argparse.Namespace) -> int:
    payload = _read_stdin_payload()
    start = _payload_cwd(payload)
    workspace: dict[str, Any] | None = None
    if args.db is None and args.config is None:
        start, workspace = _initialize_workspace(start)
        tapl_install.auto_install_if_needed(start=start)

    settings = tapl_config.load(args.config, start=start)
    conn = db.connect(args.db or db.default_db_path(start))
    try:
        outcome = hooks.handle_event(
            conn,
            event=args.event,
            mode=args.mode,
            tool=args.tool,
            payload=payload,
            tapl_settings=settings,
        )
    finally:
        conn.close()

    if workspace is not None:
        outcome["workspace"] = workspace
    _emit_outcome(outcome, as_json=args.json, as_agent=args.agent)
    return 2 if outcome.get("block") else 0


def _read_stdin_payload() -> dict[str, Any]:
    raw = sys.stdin.read() if not sys.stdin.isatty() else ""
    if not raw.strip():
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {"raw": raw}
    return parsed if isinstance(parsed, dict) else {}


def _payload_cwd(payload: dict[str, Any]) -> Path | None:
    value = payload.get("cwd")
    return Path(value).expanduser() if isinstance(value, str) and value.strip() else None


def _initialize_workspace(start: Path | None) -> tuple[Path | None, dict[str, Any] | None]:
    if start is None:
        return None, None
    workspace_root = db.find_workspace_root(start) or start
    initialized = db.initialize_workspace(workspace_root)
    return Path(initialized["workspace_root"]), initialized


def _emit_outcome(outcome: dict[str, Any], *, as_json: bool, as_agent: bool) -> None:
    if as_json:
        _print_json(outcome)
        return
    if as_agent:
        print(_agent_output(outcome, "tapl_hook_event"))
        return
    if outcome.get("event") == "Stop":
        if outcome.get("block"):
            _print_json(
                {
                    "decision": "block",
                    "reason": outcome.get("message") or "tapl blocked Stop hook.",
                }
            )
        return
    if outcome.get("message"):
        print(outcome["message"], file=sys.stderr if outcome.get("block") else sys.stdout)


def _emit_error(message: str, *, as_json: bool, as_agent: bool) -> None:
    if as_json:
        _print_json({"ok": False, "error": message})
    elif as_agent:
        print(f"<tapl_error>\n  <message>{_agent_escape(message)}</message>\n</tapl_error>")
    else:
        print(f"tapl-hook: {message}", file=sys.stderr)


def _print_json(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


def _agent_output(payload: dict[str, Any], root_tag: str) -> str:
    lines = [f"<{root_tag}>"]
    for key, value in payload.items():
        _append_agent_node(lines, 1, key, value)
    lines.append(f"</{root_tag}>")
    return "\n".join(lines)


def _append_agent_node(lines: list[str], depth: int, tag: str, value: Any) -> None:
    if tag in _AGENT_SKIP_KEYS or not _agent_value_present(value):
        return
    tag_name = _agent_tag_name(tag)
    if isinstance(value, dict):
        section: list[str] = []
        for key, child in value.items():
            _append_agent_node(section, depth + 1, str(key), child)
        if section:
            indent = "  " * depth
            lines.extend((f"{indent}<{tag_name}>", *section, f"{indent}</{tag_name}>"))
        return
    if isinstance(value, list):
        section = []
        item_tag = _AGENT_LIST_ITEM_TAGS.get(tag, "item")
        for child in value:
            _append_agent_node(section, depth + 1, item_tag, child)
        if section:
            indent = "  " * depth
            lines.extend((f"{indent}<{tag_name}>", *section, f"{indent}</{tag_name}>"))
        return
    lines.append(f"{'  ' * depth}<{tag_name}>{_agent_escape(value)}</{tag_name}>")


def _agent_value_present(value: Any) -> bool:
    return value is not None and value != "" and value != [] and value != {}


def _agent_tag_name(value: str) -> str:
    normalized = re.sub(r"[^\w.]+", "_", value.replace("-", "_"), flags=re.UNICODE).strip("_")
    if not normalized:
        return "field"
    return f"field_{normalized}" if normalized[0].isdigit() or normalized[0] == "." else normalized


def _agent_escape(value: Any) -> str:
    text = "true" if value is True else "false" if value is False else str(value)
    return html.escape(text, quote=False)


if __name__ == "__main__":
    raise SystemExit(main())
