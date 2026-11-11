"""Workspace-bound settings documents and atomic, revision-checked edits.

This service never opens a workflow database. Its only write entry point is an
explicit user settings action; callers must not invoke it from workflow entry.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from threading import RLock
from typing import Any

from . import clients, config, config_editor


class SettingsConflict(ValueError):
    """The caller's document no longer identifies the current target/content."""


_WRITE_LOCK = RLock()
# Runtime-compatible spelling aliases also count as overrides. Resetting them
# avoids a hidden legacy alias taking effect after the canonical key is removed.
_ALIASES = {
    "search.max_results": ("search.max-results", "search.limit"),
    "search.hybrid_semantic_ratio": ("search.hybrid-semantic-ratio", "search.semantic_ratio", "search.semantic-ratio"),
    "search.semantic_provider": ("search.semantic-provider",),
    "search.searchd_model_idle_timeout_seconds": tuple("search." + key for key in (
        "searchd-model-idle-timeout-seconds", "model_idle_timeout_seconds", "model-idle-timeout-seconds",
        "searchd_idle_timeout_seconds", "searchd-idle-timeout-seconds", "idle_timeout_seconds", "idle-timeout-seconds",
    )),
    "viewer.allowed_origins": ("viewer.allowed-origins",),
}


def settings_fields() -> list[dict[str, Any]]:
    """Derive the complete form allowlist from the CLI's editable registry."""
    fields: list[dict[str, Any]] = []
    for spec in config.EDITABLE_CONFIG_KEYS:
        key = spec.dynamic_prefix.rstrip(".") if spec.dynamic_prefix else spec.key
        if spec.dynamic_prefix:
            kind = "models"
        elif key.endswith(".profiles"):
            kind = "profiles"
        elif spec.value_name == "BOOLEAN":
            kind = "boolean"
        elif spec.allowed:
            kind = "select"
        elif spec.value_name in {"INTEGER", "SECONDS"}:
            kind = "integer"
        elif spec.value_name == "NUMBER":
            kind = "number"
        elif spec.value_name == "TOML_ARRAY":
            kind = "string-list"
        else:
            kind = "string"
        field: dict[str, Any] = {
            "key": key, "section": key.split(".")[0], "type": kind,
            "description": ("Model IDs mapped to non-empty, unique reasoning effort arrays."
                            if kind == "models" else spec.description),
        }
        if kind == "select":
            field["allowed"] = list(spec.allowed)
        if kind == "integer":
            field["min"] = 1 if spec.value_name == "INTEGER" else 0
        if kind == "number":
            field.update(min=0, max=1)
        fields.append(field)
        if key.startswith("subagents."):
            explicit = {**field, "key": "clients.claude-code." + key,
                        "section": config.CLAUDE_SUBAGENTS_PREFIX}
            if kind == "models":
                explicit["description"] = "Claude model IDs mapped to unique reasoning effort arrays; [] leaves effort unspecified. The inherit selection requires []."
            fields.append(explicit)
    return fields


def _lookup(data: dict[str, Any], key: str, default: Any = None) -> Any:
    current: Any = data
    for part in key.split("."):
        if not isinstance(current, dict) or part not in current:
            return default
        current = current[part]
    return current


def _effective(data: dict[str, Any], path: Path, *, exists: bool) -> dict[str, Any]:
    with clients.client_scope("codex"):
        loaded = config.from_mapping(data, path=path, exists=exists)
    result = loaded.as_dict()
    # as_dict omits an intentionally empty profile list; forms must retain it.
    result["subagents"]["profiles"] = [profile.as_dict() for profile in loaded.subagents.profiles]
    claude = config._parse_subagents(_lookup(data, config.CLAUDE_SUBAGENTS_PREFIX, {}), client="claude-code")
    result["clients"] = {"claude-code": {"subagents": {
        **claude.as_dict(), "profiles": [profile.as_dict() for profile in claude.profiles],
    }}}
    return {field["key"]: _lookup(result, field["key"]) for field in settings_fields()}


class SettingsService:
    """Resolve CLI precedence at the selected workspace; optionally pin --config."""

    def __init__(self, workspace: Path, *, config_path: Path | None = None) -> None:
        self.workspace = workspace.expanduser().resolve()
        self.config_path = config_path.expanduser().resolve() if config_path is not None else None

    def _path(self) -> Path:
        return config.resolve_config_path(self.config_path, start=self.workspace).resolve()

    def _revision(self, path: Path, content: str, exists: bool) -> str:
        identity = json.dumps([str(self.workspace), str(path), exists], separators=(",", ":"))
        return hashlib.sha256(identity.encode() + b"\0" + content.encode("utf-8")).hexdigest()

    def _document(self, path: Path, content: str, exists: bool) -> dict[str, Any]:
        parsed = config_editor._parse(content, path)
        fields = settings_fields()
        sentinel = object()
        overrides = [field["key"] for field in fields if any(
            _lookup(parsed, key, sentinel) is not sentinel
            for key in (field["key"], *_ALIASES.get(field["key"], ()))
        )]
        return {
            "path": str(path), "exists": exists,
            "revision": self._revision(path, content, exists), "fields": fields,
            "values": _effective(parsed, path, exists=exists),
            "defaults": _effective({}, path, exists=False), "overrides": overrides,
            "restart_required": ["viewer.allowed_origins"],
        }

    def get(self) -> dict[str, Any]:
        path = self._path()
        return self._document(path, config_editor._read(path), path.exists())

    def save(self, values: dict[str, Any], expected_revision: str, *, reset_all: bool = False) -> dict[str, Any]:
        if not isinstance(values, dict):
            raise ValueError("settings values must be an object")
        if not isinstance(expected_revision, str) or not expected_revision:
            raise ValueError("expected_revision is required")
        if not isinstance(reset_all, bool):
            raise ValueError("reset_all must be a boolean")
        if reset_all and values:
            raise ValueError("reset_all requires empty values")
        fields = {field["key"]: field for field in settings_fields()}
        unknown = set(values) - set(fields)
        if unknown:
            raise ValueError(f"unsupported settings keys: {', '.join(sorted(map(str, unknown)))}")
        normalized = {key: _normalize(field=fields[key], value=value) for key, value in values.items()}
        with _WRITE_LOCK:
            path = self._path()
            original = config_editor._read(path)
            exists = path.exists()
            if expected_revision != self._revision(path, original, exists):
                raise SettingsConflict("Settings changed or the workspace/config target differs. Reload settings before saving.")
            original_document = self._document(path, original, exists)
            # Unchanged form values remain implicit defaults instead of becoming
            # new overrides just because the complete form was submitted.
            changes = {key: value for key, value in normalized.items()
                       if value != original_document["values"][key]}
            remove = tuple(key for field in fields for key in (field, *_ALIASES.get(field, ()))) if reset_all else ()
            candidate = config_editor.prepare_values(original, changes, remove=remove)
            if not reset_all:
                candidate = config_editor._preserve_inferred_setup_completion(original, candidate, path)
            # Both client scopes and cross-field references are validated once,
            # after every requested field has been staged in memory.
            document = self._document(path, candidate, exists or candidate != original)
            changed = candidate != original
            if changed:
                if self._path() != path or self._revision(path, config_editor._read(path), path.exists()) != expected_revision:
                    raise SettingsConflict("Settings changed while saving. Reload settings before saving.")
                config_editor._atomic_write(path, candidate)
            return {"ok": True, "settings": document, "changed": changed}


def _normalize(*, field: dict[str, Any], value: Any) -> Any:
    key, kind = field["key"], field["type"]
    valid = {
        "boolean": lambda: isinstance(value, bool),
        "integer": lambda: isinstance(value, int) and not isinstance(value, bool),
        "number": lambda: isinstance(value, (int, float)) and not isinstance(value, bool),
        "string": lambda: isinstance(value, str),
        "select": lambda: isinstance(value, str),
        "string-list": lambda: isinstance(value, list) and all(isinstance(item, str) for item in value),
        "models": lambda: isinstance(value, dict),
        "profiles": lambda: isinstance(value, list),
    }[kind]()
    if not valid:
        raise ValueError(f"{key} must have type {kind}")
    client = "claude-code" if key.startswith(config.CLAUDE_SUBAGENTS_PREFIX + ".") else "codex"
    if kind == "models":
        if any(not isinstance(name, str) or name != name.strip() for name in value):
            raise ValueError(f"{key} model names must be strings without surrounding whitespace")
        models = config.parse_subagent_models(value, enabled=False, key=key, client=client)
        return {model.name: list(model.reasoning_efforts) for model in models}
    with clients.client_scope(client):
        return config.parse_editable_value(key, config_editor._render_value(value))
