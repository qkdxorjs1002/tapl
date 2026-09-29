"""Remove TAPL integration from exactly one selected installation scope."""

from __future__ import annotations

import copy
import json
import math
import os
from pathlib import Path
import re
import shlex
import tomllib
from typing import Any

from . import config_editor, install


_DB_NAMES = ("tapl.db", "tapl.db-wal", "tapl.db-shm", "tapl.db-journal")


def uninstall_user(
    *, codex_home: Path | None = None, purge_config: bool = False,
    purge_db: bool = False, dry_run: bool = False,
) -> dict[str, Any]:
    """Disable user integration, retaining settings and data unless purged."""
    selected = Path(os.path.abspath((codex_home or Path.home() / ".codex").expanduser()))
    # Resolve the containing scope once (including macOS /tmp), but never the
    # .codex directory itself: a linked installation must not redirect edits.
    root = selected.parent.resolve()
    target = root / selected.name
    return _uninstall(
        root, target, scope="user", purge_config=purge_config, purge_db=purge_db, dry_run=dry_run,
    )


def uninstall_repo(
    *, repo: Path | None = None, purge_config: bool = False,
    purge_db: bool = False, dry_run: bool = False,
) -> dict[str, Any]:
    """Disable integration in this folder without searching parent workspaces."""
    selected = Path(os.path.abspath((repo if repo is not None else Path.cwd()).expanduser()))
    if selected.is_symlink():
        raise ValueError(f"refusing symlink in uninstall scope: {selected}")
    root = selected.resolve()
    return _uninstall(
        root, root / ".codex", scope="repo",
        purge_config=purge_config, purge_db=purge_db, dry_run=dry_run,
    )


def _validate_paths(root: Path, codex: Path, tapl: Path, paths: list[Path]) -> None:
    for directory in (root, codex, tapl):
        if directory.is_symlink():
            raise ValueError(f"refusing symlink in uninstall scope: {directory}")
        if directory.exists() and not directory.is_dir():
            raise ValueError(f"expected directory in uninstall scope: {directory}")
    for path in paths:
        if path.is_symlink():
            raise ValueError(f"refusing symlink in uninstall scope: {path}")
        if path.exists() and not path.is_file():
            raise ValueError(f"expected regular file in uninstall scope: {path}")


def _read(path: Path) -> str | None:
    if not path.exists():
        return None
    try:
        with path.open(encoding="utf-8", newline="") as handle:
            return handle.read()
    except UnicodeError as exc:
        raise ValueError(f"invalid UTF-8 configuration {path}") from exc


def _parse_toml(text: str, path: Path) -> dict[str, Any]:
    try:
        return tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"invalid TOML configuration {path}: {exc}") from exc


def _uninstall(
    root: Path, codex: Path, *, scope: str, purge_config: bool, purge_db: bool, dry_run: bool,
) -> dict[str, Any]:
    tapl = root / ".tapl"
    hooks_path = codex / "hooks.json"
    codex_config = codex / "config.toml"
    version_path = tapl / "version"
    config_path = tapl / "config.toml"
    db_paths = [tapl / name for name in _DB_NAMES]
    all_paths = [hooks_path, codex_config, version_path, config_path, *db_paths]
    _validate_paths(root, codex, tapl, all_paths)

    # Finish every read, parse and rendering check before the first mutation.
    # The preserved TAPL config is checked as well, including in dry-run mode.
    tapl_text = _read(tapl / "config.toml")
    if tapl_text is not None:
        _parse_toml(tapl_text, tapl / "config.toml")
    original_config = _read(codex_config)
    updated_config = (
        _remove_mcp(original_config, codex_config) if original_config is not None else None
    )
    original_hooks = _read(hooks_path)
    updated_hooks = (
        _remove_hooks(original_hooks, hooks_path) if original_hooks is not None else None
    )
    updates = [(codex_config, original_config, updated_config), (hooks_path, original_hooks, updated_hooks)]
    removals = [version_path]
    if purge_config:
        removals.append(config_path)
    if purge_db:
        removals.extend(db_paths)
    files: list[dict[str, str]] = []
    for path, original, updated in updates:
        action = "missing" if original is None else "unchanged" if updated == original else "updated"
        files.append({"path": str(path), "action": f"would_{action}" if dry_run and action == "updated" else action})
    for path in removals:
        action = "removed" if path.exists() else "missing"
        files.append({"path": str(path), "action": f"would_{action}" if dry_run and action == "removed" else action})
    if not dry_run:
        _validate_paths(root, codex, tapl, all_paths)
        for path, original, updated in updates:
            if updated is not None and updated != original:
                config_editor._atomic_write(path, updated)
        for path in removals:
            path.unlink(missing_ok=True)
    return {
        "ok": True, "uninstall": scope,
        "codex_home" if scope == "user" else "repo": str(codex if scope == "user" else root),
        "purge_config": purge_config, "purge_db": purge_db,
        "dry_run": dry_run, "files": files,
    }


def _same_data(left: Any, right: Any) -> bool:
    if isinstance(left, dict) and isinstance(right, dict):
        return left.keys() == right.keys() and all(_same_data(left[key], right[key]) for key in left)
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(_same_data(a, b) for a, b in zip(left, right))
    if isinstance(left, float) and isinstance(right, float) and math.isnan(left) and math.isnan(right):
        return True
    return left == right


def _remove_mcp(text: str, path: Path) -> str:
    parsed = _parse_toml(text, path)
    servers = parsed.get("mcp_servers")
    if not isinstance(servers, dict) or "tapl" not in servers:
        return text
    expected = copy.deepcopy(parsed)
    del expected["mcp_servers"]["tapl"]
    target = ("mcp_servers", "tapl")
    assignments, tables = config_editor._scan(text)
    ranges = [(item.start, item.end) for item in assignments if item.path[:2] == target]
    # Remove headers and assignments separately: trailing comments in a table
    # can document the next unrelated section and must not disappear with TAPL.
    ranges.extend((item.start, item.content_start) for item in tables if item.path[:2] == target)
    candidate = config_editor._remove_ranges(text, ranges)
    # An inline parent assignment needs a value replacement instead of dropping
    # its whole statement. This keeps surrounding comments and other servers.
    parent = next((item for item in assignments if item.path == ("mcp_servers",)), None)
    if parent is not None:
        candidate = text[:parent.value_start] + config_editor._render_value(expected["mcp_servers"]) + text[parent.value_end:]
    try:
        actual = tomllib.loads(candidate)
        if "mcp_servers" not in actual and not expected["mcp_servers"]:
            expected.pop("mcp_servers")
        if _same_data(actual, expected):
            return candidate
    except tomllib.TOMLDecodeError:
        pass
    # Unusual valid TOML layouts may defeat the text scanner. Serialize only
    # after semantic checks; formatting/comments can change in this fallback.
    candidate = install.dump_toml(expected)
    if not _same_data(_parse_toml(candidate, path), expected):
        raise ValueError(f"cannot safely remove TAPL MCP configuration: {path}")
    return candidate


def _command_tokens(command: str, *, windows: bool) -> list[str]:
    lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|<>()")
    lexer.whitespace_split = True
    lexer.commenters = ""
    if windows:
        lexer.escape = ""
    return list(lexer)


def _executable_name(value: str) -> str:
    return value.replace("\\", "/").rsplit("/", 1)[-1].lower()


def is_tapl_hook_command(command: str) -> bool:
    """Recognize owned executable invocations, never references in arguments."""
    if "\n" in command or "\r" in command or "$(" in command or "`" in command:
        return False
    for windows in (False, True):
        try:
            tokens = _command_tokens(command, windows=windows)
        except ValueError:
            continue
        if not tokens or any(token and all(char in ";&|<>()" for char in token) for token in tokens):
            continue
        # A shell's exec and env's assignments do not change the executable.
        # Other wrappers/options are intentionally left alone when ambiguous.
        while tokens and _executable_name(tokens[0]) in {"exec", "env", "env.exe"}:
            wrapper = _executable_name(tokens.pop(0))
            if tokens and tokens[0] == "--":
                tokens.pop(0)
            if wrapper in {"env", "env.exe"}:
                while tokens and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", tokens[0]):
                    tokens.pop(0)
        if not tokens:
            continue
        executable = _executable_name(tokens[0])
        if executable in {"tapl-hook", "tapl-hook.exe"}:
            return True
        if executable in {"taplctl", "taplctl.exe"}:
            if len(tokens) > 1 and tokens[1] == "hook-event":
                return True
        if re.fullmatch(r"python(?:\d+(?:\.\d+)*)?(?:\.exe)?|py(?:\.exe)?", executable):
            index = 1
            while index < len(tokens) and tokens[index] in {"-u", "-B", "-E", "-I", "-s", "-S", "-O", "-OO", "-3"}:
                index += 1
            if index < len(tokens) and _executable_name(tokens[index]) == "tapl_hook.py":
                return True
    return False


def _owned_hook(hook: Any) -> bool:
    return (
        isinstance(hook, dict)
        and hook.get("type", "command") == "command"
        and isinstance(hook.get("command"), str)
        and is_tapl_hook_command(hook["command"])
    )


def _remove_hooks(text: str, path: Path) -> str:
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON hooks configuration {path}: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ValueError(f"expected JSON object: {path}")
    hooks = parsed.get("hooks")
    if not isinstance(hooks, dict):
        return text
    updated = copy.deepcopy(parsed)
    changed = False
    for event, entries in hooks.items():
        if not isinstance(entries, list):
            continue
        kept_entries = []
        for entry in entries:
            if _owned_hook(entry):
                changed = True
                continue
            if isinstance(entry, dict) and isinstance(entry.get("hooks"), list):
                kept_hooks = [hook for hook in entry["hooks"] if not _owned_hook(hook)]
                if len(kept_hooks) != len(entry["hooks"]):
                    changed = True
                    if not kept_hooks:
                        continue
                    entry = {**entry, "hooks": kept_hooks}
            kept_entries.append(entry)
        if kept_entries or not entries:
            updated["hooks"][event] = kept_entries
        else:
            updated["hooks"].pop(event)
    return json.dumps(updated, ensure_ascii=False, indent=2) + "\n" if changed else text
