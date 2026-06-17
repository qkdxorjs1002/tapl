"""Install tapl workflow hooks and repo-local state."""

from __future__ import annotations

import json
import re
import shlex
import shutil
import sys
import tomllib
from datetime import date, datetime, time
from importlib import resources
from pathlib import Path
from typing import Any

from . import config, db


DEFAULT_HOOK_MODE = "observe"
HOOK_EVENTS: tuple[dict[str, str | None], ...] = (
    {"event": "UserPromptSubmit", "matcher": None},
    {"event": "PreToolUse", "matcher": "Bash|apply_patch|Edit|Write|MultiEdit"},
    {"event": "PermissionRequest", "matcher": "Bash|apply_patch|Edit|Write|MultiEdit"},
    {"event": "PostToolUse", "matcher": "Bash|apply_patch|Edit|Write|MultiEdit|web\\.run|WebSearch|WebFetch|Browser"},
    {"event": "Stop", "matcher": None},
)
CODEX_STATIC_TEMPLATE_FILES: tuple[Path, ...] = (
    Path("config.toml"),
    Path("agents/junior-worker.toml"),
    Path("agents/senior-worker.toml"),
    Path("agents/specialist-worker.toml"),
)


def install_user(
    *,
    codex_home: Path | None = None,
    taplctl_command: str | None = None,
    mode: str = DEFAULT_HOOK_MODE,
    force: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    target = (codex_home or Path.home() / ".codex").expanduser()
    tapl_config_path = config.user_config_path(target.parent)
    command = resolved_taplctl_command(taplctl_command)
    hooks_path = target / "hooks.json"
    files = [
        install_hooks(hooks_path, taplctl_command=command, mode=mode, dry_run=dry_run),
        *install_static_codex_templates(target, force=force, dry_run=dry_run),
        write_text_if_needed(tapl_config_path, default_config_text(), force=force, dry_run=dry_run),
    ]
    return {
        "ok": True,
        "install": "user",
        "codex_home": str(target),
        "tapl_config": str(tapl_config_path),
        "taplctl_command": command,
        "mode": mode,
        "force": force,
        "dry_run": dry_run,
        "files": files,
    }


def install_repo(
    *,
    repo: Path | None = None,
    taplctl_command: str | None = None,
    mode: str = DEFAULT_HOOK_MODE,
    force: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    root = db.find_repo_root(repo)
    command = resolved_taplctl_command(taplctl_command)
    hooks_path = root / ".codex" / "hooks.json"
    config_path = root / config.CONFIG_RELATIVE
    db_path = root / db.DEFAULT_DB_RELATIVE

    files = [
        install_hooks(hooks_path, taplctl_command=command, mode=mode, dry_run=dry_run),
        *install_static_codex_templates(root / ".codex", force=force, dry_run=dry_run),
        write_text_if_needed(config_path, default_config_text(), force=force, dry_run=dry_run),
        initialize_db(db_path, dry_run=dry_run),
    ]
    return {
        "ok": True,
        "install": "repo",
        "repo": str(root),
        "taplctl_command": command,
        "mode": mode,
        "force": force,
        "dry_run": dry_run,
        "files": files,
    }


def install_hooks(path: Path, *, taplctl_command: str, mode: str, dry_run: bool) -> dict[str, str]:
    existing = read_json(path)
    updated = merge_hooks(existing, build_hooks_config(taplctl_command=taplctl_command, mode=mode))
    text = json.dumps(updated, ensure_ascii=False, indent=2) + "\n"
    return write_text_if_needed(path, text, force=True, dry_run=dry_run)


def resolved_taplctl_command(command: str | None) -> str:
    if command:
        return command
    found = shutil.which("taplctl")
    if found:
        return found
    argv0 = Path(sys.argv[0])
    if argv0.name == "taplctl" and (argv0.is_absolute() or argv0.parent != Path(".")):
        return str(argv0.expanduser().resolve())
    return "taplctl"


def build_hooks_config(*, taplctl_command: str, mode: str) -> dict[str, Any]:
    template = template_hooks_config(taplctl_command=taplctl_command, mode=mode)
    if template is not None:
        return template

    hooks: dict[str, list[dict[str, Any]]] = {}
    for spec in HOOK_EVENTS:
        event = str(spec["event"])
        entry: dict[str, Any] = {
            "hooks": [
                {
                    "type": "command",
                    "command": hook_command(taplctl_command=taplctl_command, event=event, mode=mode),
                }
            ]
        }
        if spec["matcher"]:
            entry["matcher"] = spec["matcher"]
        hooks[event] = [entry]
    return {"hooks": hooks}


def hook_command(*, taplctl_command: str, event: str, mode: str) -> str:
    return f"{shlex.quote(taplctl_command)} hook-event --event {shlex.quote(event)} --mode {shlex.quote(mode)}"


def template_hooks_config(*, taplctl_command: str, mode: str) -> dict[str, Any] | None:
    text = codex_template_text("hooks.json")
    if text is None:
        return None
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("tapl hooks template must be a JSON object")
    return retarget_hooks_config(data, taplctl_command=taplctl_command, mode=mode)


def retarget_hooks_config(template: dict[str, Any], *, taplctl_command: str, mode: str) -> dict[str, Any]:
    updated = json.loads(json.dumps(template))
    hooks_by_event = updated.get("hooks")
    if not isinstance(hooks_by_event, dict):
        raise ValueError("tapl hooks template must contain a hooks object")

    for event, entries in hooks_by_event.items():
        if not isinstance(event, str) or not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            hook_entries = entry.get("hooks")
            if not isinstance(hook_entries, list):
                continue
            for hook in hook_entries:
                if not isinstance(hook, dict):
                    continue
                command = hook.get("command")
                if isinstance(command, str) and is_tapl_hook_command(command):
                    hook["command"] = hook_command(taplctl_command=taplctl_command, event=event, mode=mode)
    return updated


def is_tapl_hook_command(command: str) -> bool:
    return "taplctl" in command and "hook-event" in command


def merge_hooks(existing: dict[str, Any], managed: dict[str, Any]) -> dict[str, Any]:
    merged = dict(existing)
    existing_hooks = existing.get("hooks")
    if not isinstance(existing_hooks, dict):
        existing_hooks = {}

    hooks: dict[str, Any] = {}
    for event, current_entries in existing_hooks.items():
        if not isinstance(current_entries, list):
            hooks[event] = current_entries
            continue
        preserved = [
            stripped
            for entry in current_entries
            if (stripped := strip_tapl_hooks_from_entry(entry)) is not None
        ]
        if preserved:
            hooks[event] = preserved

    for event, managed_entries in managed["hooks"].items():
        current_entries = hooks.get(event, [])
        if not isinstance(current_entries, list):
            current_entries = []
        hooks[event] = [*current_entries, *managed_entries]

    merged["hooks"] = hooks
    return merged


def strip_tapl_hooks_from_entry(entry: Any) -> Any | None:
    if not isinstance(entry, dict):
        return entry
    hooks = entry.get("hooks")
    if not isinstance(hooks, list):
        return entry

    preserved_hooks = [hook for hook in hooks if not is_tapl_hook_command_entry(hook)]
    if len(preserved_hooks) == len(hooks):
        return entry
    if not preserved_hooks:
        return None

    updated = dict(entry)
    updated["hooks"] = preserved_hooks
    return updated


def is_tapl_hook_command_entry(hook: Any) -> bool:
    if not isinstance(hook, dict):
        return False
    command = hook.get("command")
    return isinstance(command, str) and (
        "tapl_hook.py" in command or ("taplctl" in command and "hook-event" in command)
    )


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"expected JSON object: {path}")
    return data


def write_text_if_needed(path: Path, content: str, *, force: bool, dry_run: bool) -> dict[str, str]:
    existed = path.exists()
    if existed and path.read_text(encoding="utf-8") == content:
        action = "unchanged"
    elif existed and not force:
        action = "skipped"
    else:
        action = "updated" if existed else "created"

    if dry_run:
        action = f"would_{action}" if action != "unchanged" else "unchanged"
    elif action in {"created", "updated"}:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    return {"path": str(path), "action": action}


def initialize_db(path: Path, *, dry_run: bool) -> dict[str, str]:
    existed = path.exists()
    if dry_run:
        return {"path": str(path), "action": "unchanged" if existed else "would_create"}
    conn = db.connect(path)
    conn.close()
    return {"path": str(path), "action": "unchanged" if existed else "created"}


def default_config_text() -> str:
    template = template_text(".tapl", "config.toml")
    if template is not None:
        return template
    return f"""[search]
mode = "{config.DEFAULT_SEARCH_MODE}"
max_results = {config.DEFAULT_SEARCH_MAX_RESULTS}
hybrid_semantic_ratio = {config.DEFAULT_HYBRID_SEMANTIC_RATIO}

[plan-task-execute]
use_level_subagent = {str(config.DEFAULT_USE_LEVEL_SUBAGENT).lower()}
level_subagent_aggressiveness = "{config.DEFAULT_LEVEL_SUBAGENT_AGGRESSIVENESS}"
plan_detail = "{config.DEFAULT_PLAN_DETAIL}"
task_granularity = "{config.DEFAULT_TASK_GRANULARITY}"
require_execution_approval = {str(config.DEFAULT_REQUIRE_EXECUTION_APPROVAL).lower()}
"""


def install_static_codex_templates(target: Path, *, force: bool, dry_run: bool) -> list[dict[str, str]]:
    results: list[dict[str, str]] = []
    for relative in CODEX_STATIC_TEMPLATE_FILES:
        text = codex_template_text(*relative.parts)
        if text is None:
            continue
        path = target / relative
        if relative == Path("config.toml"):
            results.append(merge_codex_config(path, text, force=force, dry_run=dry_run))
        else:
            results.append(write_text_if_needed(path, text, force=force, dry_run=dry_run))
    return results


def merge_codex_config(path: Path, template: str, *, force: bool, dry_run: bool) -> dict[str, str]:
    if not path.exists():
        return write_text_if_needed(path, template, force=force, dry_run=dry_run)

    existing_text = path.read_text(encoding="utf-8")
    if existing_text == template:
        return {"path": str(path), "action": "unchanged"}

    try:
        existing = tomllib.loads(existing_text)
        managed = tomllib.loads(template)
    except tomllib.TOMLDecodeError:
        if not force:
            return {"path": str(path), "action": "skipped"}
        return write_text_if_needed(path, template, force=True, dry_run=dry_run)

    if force:
        merged_text = dump_toml(merge_toml_values(existing, managed, managed_wins=True))
        action = "updated" if existing_text != merged_text else "unchanged"
    else:
        missing = missing_toml_values(existing, managed)
        if not missing:
            action = "unchanged"
            merged_text = existing_text
        else:
            merged_text = insert_missing_toml_values(existing_text, existing, missing)
            action = "merged" if existing_text != merged_text else "unchanged"

    if dry_run:
        action = f"would_{action}" if action != "unchanged" else "unchanged"
    elif action in {"merged", "updated"}:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(merged_text, encoding="utf-8")

    return {"path": str(path), "action": action}


def merge_toml_values(existing: dict[str, Any], managed: dict[str, Any], *, managed_wins: bool) -> dict[str, Any]:
    merged = dict(existing)
    for key, managed_value in managed.items():
        existing_value = merged.get(key)
        if isinstance(existing_value, dict) and isinstance(managed_value, dict):
            merged[key] = merge_toml_values(existing_value, managed_value, managed_wins=managed_wins)
        elif managed_wins or key not in merged:
            merged[key] = managed_value
    return merged


def missing_toml_values(
    existing: dict[str, Any],
    managed: dict[str, Any],
    prefix: tuple[str, ...] = (),
) -> list[tuple[tuple[str, ...], Any]]:
    missing: list[tuple[tuple[str, ...], Any]] = []
    for key, managed_value in managed.items():
        path = (*prefix, key)
        if key not in existing:
            collect_toml_leaf_values(path, managed_value, missing)
            continue
        existing_value = existing[key]
        if isinstance(existing_value, dict) and isinstance(managed_value, dict):
            missing.extend(missing_toml_values(existing_value, managed_value, path))
    return missing


def collect_toml_leaf_values(
    path: tuple[str, ...],
    value: Any,
    output: list[tuple[tuple[str, ...], Any]],
) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            collect_toml_leaf_values((*path, key), child, output)
    else:
        output.append((path, value))


def insert_missing_toml_values(
    existing_text: str,
    existing: dict[str, Any],
    missing: list[tuple[tuple[str, ...], Any]],
) -> str:
    lines = existing_text.splitlines(keepends=True)
    if existing_text and not existing_text.endswith(("\n", "\r")):
        lines[-1] = f"{lines[-1]}\n"

    ranges = toml_table_ranges(lines)
    explicit_tables = {table: (start, end) for table, start, end in ranges}
    first_table_index = min((start for _, start, _ in ranges), default=len(lines))

    top_level: list[str] = []
    table_insertions: dict[tuple[str, ...], list[str]] = {}
    appended_tables: dict[tuple[str, ...], list[str]] = {}

    for path, value in missing:
        table_path = path[:-1]
        key = path[-1]
        if not table_path:
            top_level.append(format_toml_assignment((key,), value))
        elif table_path in explicit_tables:
            table_insertions.setdefault(table_path, []).append(format_toml_assignment((key,), value))
        elif lookup_toml_table(existing, table_path) is not None:
            top_level.append(format_toml_assignment(path, value))
        else:
            appended_tables.setdefault(table_path, []).append(format_toml_assignment((key,), value))

    inserts: list[tuple[int, list[str]]] = []
    if top_level:
        inserts.append((first_table_index, ensure_leading_gap(lines, first_table_index, top_level)))

    for table_path, assignments in table_insertions.items():
        start, end = explicit_tables[table_path]
        insert_at = end
        while insert_at > start + 1 and lines[insert_at - 1].strip() == "":
            insert_at -= 1
        inserts.append((insert_at, ensure_trailing_gap(lines, insert_at, assignments)))

    for index, block in sorted(inserts, key=lambda item: item[0], reverse=True):
        lines[index:index] = block

    if appended_tables:
        if lines and lines[-1].strip():
            lines.append("\n")
        for table_path, assignments in appended_tables.items():
            if lines and lines[-1].strip():
                lines.append("\n")
            lines.append(f"[{format_toml_dotted_key(table_path)}]\n")
            lines.extend(assignments)

    return "".join(lines)


def toml_table_ranges(lines: list[str]) -> list[tuple[tuple[str, ...], int, int]]:
    headers: list[tuple[tuple[str, ...], int]] = []
    for index, line in enumerate(lines):
        parsed = parse_toml_table_header(line)
        if parsed is not None:
            headers.append((parsed, index))

    ranges: list[tuple[tuple[str, ...], int, int]] = []
    for index, (table, start) in enumerate(headers):
        end = headers[index + 1][1] if index + 1 < len(headers) else len(lines)
        ranges.append((table, start, end))
    return ranges


def parse_toml_table_header(line: str) -> tuple[str, ...] | None:
    if re.match(r"^\s*\[\[", line):
        return None
    match = re.match(r"^\s*\[([^\[\]\n]+)\]\s*(?:#.*)?$", line)
    if not match:
        return None
    try:
        parsed = tomllib.loads(f"[{match.group(1)}]\n__tapl_table_marker__ = true\n")
    except tomllib.TOMLDecodeError:
        return None
    return find_toml_marker_path(parsed)


def find_toml_marker_path(data: dict[str, Any], prefix: tuple[str, ...] = ()) -> tuple[str, ...] | None:
    if data.get("__tapl_table_marker__") is True:
        return prefix
    for key, value in data.items():
        if isinstance(value, dict):
            found = find_toml_marker_path(value, (*prefix, key))
            if found is not None:
                return found
    return None


def lookup_toml_table(data: dict[str, Any], path: tuple[str, ...]) -> dict[str, Any] | None:
    current: Any = data
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current if isinstance(current, dict) else None


def ensure_leading_gap(lines: list[str], index: int, block: list[str]) -> list[str]:
    if index > 0 and lines[index - 1].strip():
        return ["\n", *block]
    return block


def ensure_trailing_gap(lines: list[str], index: int, block: list[str]) -> list[str]:
    if index < len(lines) and lines[index].strip():
        return [*block, "\n"]
    return block


def dump_toml(data: dict[str, Any]) -> str:
    lines: list[str] = []
    dump_toml_table(data, (), lines)
    return "".join(lines).rstrip() + "\n"


def dump_toml_table(data: dict[str, Any], path: tuple[str, ...], lines: list[str]) -> None:
    scalars = [(key, value) for key, value in data.items() if not isinstance(value, dict)]
    tables = [(key, value) for key, value in data.items() if isinstance(value, dict)]

    if path:
        if lines and lines[-1] != "\n":
            lines.append("\n")
        lines.append(f"[{format_toml_dotted_key(path)}]\n")

    for key, value in scalars:
        lines.append(format_toml_assignment((key,), value))

    for key, value in tables:
        dump_toml_table(value, (*path, key), lines)


def format_toml_assignment(path: tuple[str, ...], value: Any) -> str:
    return f"{format_toml_dotted_key(path)} = {format_toml_value(value)}\n"


def format_toml_dotted_key(path: tuple[str, ...]) -> str:
    return ".".join(format_toml_key(part) for part in path)


def format_toml_key(key: str) -> str:
    if re.match(r"^[A-Za-z0-9_-]+$", key):
        return key
    return json.dumps(key)


def format_toml_value(value: Any) -> str:
    if isinstance(value, str):
        return json.dumps(value)
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return repr(value).lower()
    if isinstance(value, list):
        return "[" + ", ".join(format_toml_value(item) for item in value) + "]"
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, (date, time)):
        return value.isoformat()
    raise TypeError(f"unsupported TOML value for Codex config merge: {type(value).__name__}")


def codex_template_text(*parts: str) -> str | None:
    return template_text(".codex", *parts)


def template_text(*parts: str) -> str | None:
    resource_text = packaged_template_text(*parts)
    if resource_text is not None:
        return resource_text

    source_path = Path(__file__).resolve().parents[1] / Path(*parts)
    if source_path.is_file():
        return source_path.read_text(encoding="utf-8")
    return None


def packaged_template_text(*parts: str) -> str | None:
    try:
        target = resources.files(__package__).joinpath("_templates", *parts)
    except (AttributeError, ModuleNotFoundError, FileNotFoundError):
        return None
    if not target.is_file():
        return None
    return target.read_text(encoding="utf-8")
