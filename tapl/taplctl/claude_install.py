"""Claude Code integration with independent opt-in and refresh markers."""

from __future__ import annotations

import base64
import binascii
import copy
import hashlib
import json
from pathlib import Path
import shlex
import tomllib
from typing import Any

from . import __version__, config, config_editor, db, install
from .command_runtime import windows_hook_command, windows_hook_tokens


VERSION_RELATIVE = Path(".tapl/claude-code.version")
INSTALL_STATE_RELATIVE = Path(".tapl/claude-code.install-state.json")
INSTALL_MIGRATION_REVISION = 1
_WINDOWS_PREFIX = "powershell.exe -NoProfile -NonInteractive -OutputFormat Text -EncodedCommand "


def _windows_codex_command(command: str) -> str | None:
    """Normalize only the exact encoded launcher shape generated below."""
    if not command.startswith(_WINDOWS_PREFIX):
        return None
    try:
        script = base64.b64decode(command[len(_WINDOWS_PREFIX):], validate=True).decode("utf-16-le")
    except (ValueError, UnicodeError, binascii.Error):
        return None
    client_arg = " '--client' 'claude-code' '--event' "
    if script.count(client_arg) != 1:
        return None
    script = script.replace(client_arg, " '--event' ", 1)
    normalized = _WINDOWS_PREFIX + base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    return normalized if windows_hook_tokens(normalized) is not None else None


def hook_command(*, taplctl_command: str, event: str, mode: str) -> str:
    hook = install.sibling_tapl_command(taplctl_command, "tapl-hook")
    if install.WINDOWS:
        encoded = windows_hook_command(hook, event, mode)
        script = base64.b64decode(encoded[len(_WINDOWS_PREFIX):]).decode("utf-16-le")
        script = script.replace(" '--event' ", " '--client' 'claude-code' '--event' ", 1)
        return _WINDOWS_PREFIX + base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    return f"{shlex.quote(hook)} --client claude-code --event {shlex.quote(event)} --mode {shlex.quote(mode)}"


def _owned_hook(hook: Any) -> bool:
    if not isinstance(hook, dict) or hook.get("type", "command") != "command":
        return False
    command = hook.get("command")
    return isinstance(command, str) and install.is_tapl_hook_command(_windows_codex_command(command) or command)


def build_hooks_config(*, taplctl_command: str, mode: str) -> dict[str, Any]:
    text = install.template_text(".claude", "settings.json")
    if text is None:
        raise ValueError("TAPL Claude Code settings template is missing")
    managed = json.loads(text)
    for event, entries in managed["hooks"].items():
        for entry in entries:
            for hook in entry["hooks"]:
                if _owned_hook(hook):
                    hook["command"] = hook_command(taplctl_command=taplctl_command, event=event, mode=mode)
    return managed


def _without_hooks(settings: dict[str, Any]) -> dict[str, Any]:
    updated = copy.deepcopy(settings)
    hooks = updated.get("hooks")
    if hooks is None:
        return updated
    if not isinstance(hooks, dict):
        raise ValueError("Claude Code hooks must be a JSON object")
    for event, entries in list(hooks.items()):
        if not isinstance(entries, list):
            raise ValueError(f"Claude Code hooks.{event} must be an array")
        kept = []
        for entry in entries:
            if _owned_hook(entry):
                continue
            if isinstance(entry, dict) and isinstance(entry.get("hooks"), list):
                remaining = [hook for hook in entry["hooks"] if not _owned_hook(hook)]
                if len(remaining) != len(entry["hooks"]):
                    if not remaining:
                        continue
                    entry = {**entry, "hooks": remaining}
            kept.append(entry)
        if kept or not entries:
            hooks[event] = kept
        else:
            del hooks[event]
    return updated


def merge_hooks(settings: dict[str, Any], managed: dict[str, Any]) -> dict[str, Any]:
    updated = _without_hooks(settings)
    hooks = updated.setdefault("hooks", {})
    for event, entries in managed["hooks"].items():
        hooks.setdefault(event, []).extend(entries)
    return updated


def build_mcp_config(*, taplctl_command: str) -> dict[str, Any]:
    text = install.template_text(".claude", "mcp.json")
    if text is None:
        raise ValueError("TAPL Claude Code MCP template is missing")
    managed = json.loads(text)
    managed["mcpServers"]["tapl"]["command"] = install.sibling_tapl_command(taplctl_command, "tapl-mcp")
    return managed


def merge_mcp(settings: dict[str, Any], managed: dict[str, Any]) -> dict[str, Any]:
    updated = copy.deepcopy(settings)
    servers = updated.setdefault("mcpServers", {})
    if not isinstance(servers, dict):
        raise ValueError("Claude Code mcpServers must be a JSON object")
    server = servers.setdefault("tapl", {})
    if not isinstance(server, dict):
        raise ValueError("Claude Code mcpServers.tapl must be a JSON object")
    env = server.setdefault("env", {})
    if not isinstance(env, dict):
        raise ValueError("Claude Code mcpServers.tapl.env must be a JSON object")
    template = managed["mcpServers"]["tapl"]
    env.update(template["env"])
    server.update({key: value for key, value in template.items() if key != "env"})
    # A managed stdio launcher must not inherit stale arguments or URL transport.
    for key in ("args", "url", "headers"):
        server.pop(key, None)
    return updated


def _json_text(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2) + "\n"


def managed_install_state() -> dict[str, Any]:
    inputs = {
        "migration_revision": INSTALL_MIGRATION_REVISION,
        "tapl_config": install.default_config_text(),
        "hooks": build_hooks_config(taplctl_command="taplctl", mode=install.DEFAULT_HOOK_MODE),
        "mcp": build_mcp_config(taplctl_command="taplctl"),
    }
    digest = hashlib.sha256(json.dumps(inputs, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
    return {"schema_version": 1, "client": "claude-code", "version": __version__, "fingerprint": digest}


def scope_has_install(root: Path) -> bool:
    return (root / VERSION_RELATIVE).is_file()


def _stale(root: Path) -> bool:
    if not scope_has_install(root):
        return False
    if install.installed_version(root / VERSION_RELATIVE) != __version__:
        return True
    try:
        return install.read_json(root / INSTALL_STATE_RELATIVE) != managed_install_state()
    except (ValueError, UnicodeError):
        return True


def _validate_config(path: Path) -> None:
    if path.exists():
        try:
            tomllib.loads(path.read_text(encoding="utf-8"))
        except (tomllib.TOMLDecodeError, UnicodeError) as exc:
            raise ValueError(f"Cannot refresh TAPL: repair invalid TOML in {path}: {exc}") from exc


def _install(
    root: Path, target: Path, mcp_path: Path, *, scope: str,
    taplctl_command: str | None, mode: str, force: bool, dry_run: bool,
    tapl_config_policy: str, create_missing_config: bool = True,
) -> dict[str, Any]:
    from .uninstall import _validate_paths

    command = install.resolved_taplctl_command(taplctl_command)
    settings_path = target / "settings.json"
    config_path = root / config.CONFIG_RELATIVE
    version_path = root / VERSION_RELATIVE
    paths = [settings_path, mcp_path, config_path, version_path, root / INSTALL_STATE_RELATIVE]
    _validate_paths(root, target, root / ".tapl", paths)
    # Validate both JSON documents and rendering before writing either one.
    settings = merge_hooks(install.read_json(settings_path), build_hooks_config(taplctl_command=command, mode=mode))
    mcp = merge_mcp(install.read_json(mcp_path), build_mcp_config(taplctl_command=command))
    previous_version = install.installed_version(version_path)
    files = [
        install.write_text_if_needed(settings_path, _json_text(settings), force=True, dry_run=dry_run),
        install.write_text_if_needed(mcp_path, _json_text(mcp), force=True, dry_run=dry_run),
        install.write_tapl_config(
            config_path, install.installation_config_text(config_path, client="claude-code"), force=force, dry_run=dry_run,
            previous_version=previous_version, tapl_config_policy=tapl_config_policy,
        ) if create_missing_config or config_path.exists()
        else {"path": str(config_path), "action": "skipped_missing"},
    ]
    if scope == "repo":
        database = (db.local_db_path(root) or root / ".tapl/tapl-<installation-uuid>.db") if dry_run else db.default_db_path(root)
        files.append(install.initialize_db(database, dry_run=dry_run))
    failed = [item for item in files if item.get("reason") == "invalid_toml"]
    for item in failed:
        item["error"] = f"Repair invalid TOML in {item['path']} and retry TAPL installation."
    if not failed:
        files.extend([
            install.write_version_marker(version_path, dry_run=dry_run),
            install.write_text_if_needed(root / INSTALL_STATE_RELATIVE, _json_text(managed_install_state()), force=True, dry_run=dry_run),
        ])
    return {
        "ok": not failed, "client": "claude-code", "install": scope,
        "claude_home" if scope == "user" else "repo": str(target if scope == "user" else root),
        "tapl_config": str(config_path), "taplctl_command": command,
        "mode": mode, "force": force, "dry_run": dry_run,
        "previous_version": previous_version, "files": files,
    }


def install_user(
    *, claude_home: Path | None = None, taplctl_command: str | None = None,
    mode: str = install.DEFAULT_HOOK_MODE, force: bool = False, dry_run: bool = False,
    tapl_config_policy: str = install.TAPL_CONFIG_POLICY_PROMPT,
) -> dict[str, Any]:
    target = (claude_home or Path.home() / ".claude").expanduser()
    return _install(
        target.parent, target, target.parent / ".claude.json", scope="user",
        taplctl_command=taplctl_command, mode=mode, force=force, dry_run=dry_run,
        tapl_config_policy=tapl_config_policy,
    )


def install_repo(
    *, repo: Path | None = None, taplctl_command: str | None = None,
    mode: str = install.DEFAULT_HOOK_MODE, force: bool = False, dry_run: bool = False,
    tapl_config_policy: str = install.TAPL_CONFIG_POLICY_PROMPT,
    create_missing_config: bool = True,
) -> dict[str, Any]:
    root = db.find_repo_root(repo)
    return _install(
        root, root / ".claude", root / ".mcp.json", scope="repo",
        taplctl_command=taplctl_command, mode=mode, force=force, dry_run=dry_run,
        tapl_config_policy=tapl_config_policy, create_missing_config=create_missing_config,
    )


def _installed_mode(path: Path, fallback: str) -> str:
    settings = install.read_json(path)
    for entries in settings.get("hooks", {}).values():
        for entry in entries if isinstance(entries, list) else []:
            for hook in entry.get("hooks", []) if isinstance(entry, dict) else []:
                if _owned_hook(hook):
                    command = hook["command"]
                    normalized = _windows_codex_command(command) or command
                    args = windows_hook_tokens(normalized) or shlex.split(normalized)
                    for index, token in enumerate(args):
                        mode = args[index + 1] if token == "--mode" and index + 1 < len(args) else token.removeprefix("--mode=") if token.startswith("--mode=") else None
                        if mode in {"observe", "enforce"}:
                            return mode
    return fallback


def auto_install_if_needed(
    *, start: Path | None = None, home: Path | None = None,
    taplctl_command: str | None = None, mode: str = install.DEFAULT_HOOK_MODE,
) -> list[dict[str, Any]]:
    home_path = (home or Path.home()).expanduser()
    root = db.find_repo_root(start)
    scopes = [("user", home_path), ("repo", root)]
    results = []
    for scope, scope_root in scopes:
        if not _stale(scope_root) or (scope == "repo" and not db.discover_db_paths(scope_root)):
            continue
        _validate_config(scope_root / config.CONFIG_RELATIVE)
        settings = scope_root / ".claude/settings.json"
        # Reject malformed MCP config before refreshing either document.
        install.read_json(scope_root / (".claude.json" if scope == "user" else ".mcp.json"))
        options = {
            "taplctl_command": taplctl_command, "mode": _installed_mode(settings, mode),
            "tapl_config_policy": install.TAPL_CONFIG_POLICY_MERGE,
        }
        if scope == "user":
            results.append(install_user(claude_home=scope_root / ".claude", **options))
        else:
            results.append(install_repo(repo=scope_root, create_missing_config=False, **options))
    return results


def uninstall(
    root: Path, target: Path, *, scope: str, purge_config: bool,
    purge_db: bool, dry_run: bool,
) -> dict[str, Any]:
    from . import uninstall as removal

    settings_path = target / "settings.json"
    mcp_path = root / (".claude.json" if scope == "user" else ".mcp.json")
    config_path = root / config.CONFIG_RELATIVE
    database_paths = [root / ".tapl" / name for name in removal._DB_NAMES]
    local = db.local_db_path(root)
    if local is not None:
        database_paths.extend(Path(str(local) + suffix) for suffix in ("", "-wal", "-shm", "-journal"))
    removals = [root / VERSION_RELATIVE, root / INSTALL_STATE_RELATIVE]
    paths = [settings_path, mcp_path, config_path, *removals, *database_paths]
    removal._validate_paths(root, target, root / ".tapl", paths)
    _validate_config(config_path)
    protect_config, protect_db = removal.purge_protection(
        root, client="claude-code", config_path=config_path, db_paths=database_paths,
        purge_config=purge_config, purge_db=purge_db,
    )
    if purge_config and not protect_config:
        removals.append(config_path)
    if purge_db and not protect_db:
        removals.extend(database_paths)
    preserved = ([config_path] if protect_config else []) + (database_paths if protect_db else [])
    original_settings, original_mcp = removal._read(settings_path), removal._read(mcp_path)
    settings = _without_hooks(install.read_json(settings_path))
    mcp = install.read_json(mcp_path)
    servers = mcp.get("mcpServers")
    if servers is not None and not isinstance(servers, dict):
        raise ValueError("Claude Code mcpServers must be a JSON object")
    if isinstance(servers, dict):
        servers.pop("tapl", None)
    updates = []
    files = []
    for path, original, updated in [(settings_path, original_settings, settings), (mcp_path, original_mcp, mcp)]:
        changed = original is not None and json.loads(original) != updated
        action = "updated" if changed else "missing" if original is None else "unchanged"
        files.append({"path": str(path), "action": "would_updated" if changed and dry_run else action})
        if changed:
            updates.append((path, _json_text(updated)))
    for path in dict.fromkeys(removals):
        action = "removed" if path.exists() else "missing"
        files.append({"path": str(path), "action": "would_removed" if dry_run and action == "removed" else action})
    files.extend({"path": str(path), "action": "preserved_shared"} for path in dict.fromkeys(preserved))
    if not dry_run:
        removal._validate_paths(root, target, root / ".tapl", paths)
        for path, text in updates:
            config_editor._atomic_write(path, text)
        for path in dict.fromkeys(removals):
            path.unlink(missing_ok=True)
    return {
        "ok": True, "client": "claude-code", "uninstall": scope,
        "claude_home" if scope == "user" else "repo": str(target if scope == "user" else root),
        "purge_config": purge_config, "purge_db": purge_db, "dry_run": dry_run,
        "files": files,
    }
