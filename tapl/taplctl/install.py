"""Install tapl workflow hooks and repo-local state."""

from __future__ import annotations

import json
import shlex
import shutil
import sys
from importlib import resources
from pathlib import Path
from typing import Any

from . import config, db


DEFAULT_HOOK_MODE = "observe"
HOOK_EVENTS: tuple[dict[str, str | None], ...] = (
    {"event": "SessionStart", "matcher": "startup|resume|clear|compact"},
    {"event": "UserPromptSubmit", "matcher": None},
    {"event": "PreToolUse", "matcher": "Bash|apply_patch|Edit|Write|MultiEdit"},
    {"event": "PermissionRequest", "matcher": "Bash|apply_patch|Edit|Write|MultiEdit"},
    {"event": "PostToolUse", "matcher": "Bash|apply_patch|Edit|Write|MultiEdit"},
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
    command = resolved_taplctl_command(taplctl_command)
    hooks_path = target / "hooks.json"
    files = [
        install_hooks(hooks_path, taplctl_command=command, mode=mode, dry_run=dry_run),
        *install_static_codex_templates(target, force=force, dry_run=dry_run),
    ]
    return {
        "ok": True,
        "install": "user",
        "codex_home": str(target),
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

    hooks = dict(existing_hooks)
    for event, managed_entries in managed["hooks"].items():
        current_entries = hooks.get(event, [])
        if not isinstance(current_entries, list):
            current_entries = []
        preserved = [entry for entry in current_entries if not is_tapl_hook_entry(entry)]
        hooks[event] = [*preserved, *managed_entries]

    merged["hooks"] = hooks
    return merged


def is_tapl_hook_entry(entry: Any) -> bool:
    if not isinstance(entry, dict):
        return False
    hooks = entry.get("hooks")
    if not isinstance(hooks, list):
        return False
    for hook in hooks:
        if not isinstance(hook, dict):
            continue
        command = hook.get("command")
        if isinstance(command, str) and ("tapl_hook.py" in command or ("taplctl" in command and "hook-event" in command)):
            return True
    return False


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
hybrid_semantic_ratio = {config.DEFAULT_HYBRID_SEMANTIC_RATIO}

[plan-task-execute]
use_level_subagent = {str(config.DEFAULT_USE_LEVEL_SUBAGENT).lower()}
level_subagent_aggressiveness = "{config.DEFAULT_LEVEL_SUBAGENT_AGGRESSIVENESS}"
plan_detail = "{config.DEFAULT_PLAN_DETAIL}"
task_granularity = "{config.DEFAULT_TASK_GRANULARITY}"
"""


def install_static_codex_templates(target: Path, *, force: bool, dry_run: bool) -> list[dict[str, str]]:
    results: list[dict[str, str]] = []
    for relative in CODEX_STATIC_TEMPLATE_FILES:
        text = codex_template_text(*relative.parts)
        if text is None:
            continue
        results.append(write_text_if_needed(target / relative, text, force=force, dry_run=dry_run))
    return results


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
