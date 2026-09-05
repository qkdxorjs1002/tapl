"""Comment-preserving edits for TAPL's TOML configuration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
import json
import os
from pathlib import Path
import stat
import tempfile
from typing import Any
import tomllib

from . import config


@dataclass(frozen=True)
class ConfigEditResult:
    path: str
    key: str
    changed: bool
    value: Any = None


@dataclass(frozen=True)
class SubagentsConfigEditResult:
    """The result of replacing the standard SubAgent setup settings."""

    path: str
    changed: bool
    config: config.SubagentsConfig


@dataclass(frozen=True)
class _Assignment:
    path: tuple[str, ...]
    start: int
    end: int
    value_start: int
    value_end: int


@dataclass(frozen=True)
class _Table:
    path: tuple[str, ...]
    start: int
    content_start: int
    end: int
    array: bool = False


def set_value(path: Path | str, key: str, raw_value: str) -> ConfigEditResult:
    """Set one supported key after validating the complete resulting config."""

    config_path = Path(path).expanduser()
    value = config.parse_editable_value(key, raw_value)
    original = _read(config_path)
    rendered = _render_value(value)
    target = _key_path(key)
    prepared = _remove_array_tables(original, target)
    candidate = _replace_or_add(prepared, target, rendered)
    candidate = _preserve_inferred_setup_completion(original, candidate, config_path)
    _validate(candidate, config_path)
    changed = candidate != original
    if changed:
        _atomic_write(config_path, candidate)
    return ConfigEditResult(str(config_path), key, changed, value)


def unset_value(path: Path | str, key: str) -> ConfigEditResult:
    """Remove one supported key after validating the complete resulting config."""

    config.editable_config_key(key)
    config_path = Path(path).expanduser()
    original = _read(config_path)
    target = _key_path(key)
    assignments, _ = _scan(original)
    assignment = next((item for item in assignments if item.path == target), None)
    if assignment is None:
        candidate = _remove_array_tables(original, target)
        if candidate != original:
            candidate = _preserve_inferred_setup_completion(
                original,
                candidate,
                config_path,
            )
            _validate(candidate, config_path)
            _atomic_write(config_path, candidate)
            return ConfigEditResult(str(config_path), key, True)
        parsed = _parse(original, config_path)
        if _mapping_contains(parsed, target):
            raise ValueError(
                f"cannot unset {key}: the value is stored in an inline TOML table"
            )
        _validate(original, config_path)
        return ConfigEditResult(str(config_path), key, False)

    candidate = original[: assignment.start] + original[assignment.end :]
    candidate = _preserve_inferred_setup_completion(original, candidate, config_path)
    _validate(candidate, config_path)
    if candidate != original:
        _atomic_write(config_path, candidate)
    return ConfigEditResult(str(config_path), key, candidate != original)


def configure_subagents(
    path: Path | str,
    *,
    enabled: bool,
    strategy: str,
    models: dict[str, list[str]],
    profiles: list[dict] | None = None,
    preference: str = "",
    available_models: dict[str, list[str]] | None = None,
) -> SubagentsConfigEditResult:
    """Atomically save a completed first-use SubAgent configuration.

    The editor owns the standard setup fields, while retaining nonstandard
    ``subagents`` settings and all unrelated TOML content.
    """

    normalized_enabled = config.boolean(enabled, "subagents.enabled")
    normalized_strategy = config.choice(
        strategy,
        config.SUBAGENT_STRATEGIES,
        "subagents.strategy",
    )
    normalized_preference = config.string(preference, "subagents.preference")
    normalized_available = (
        config.parse_subagent_models(available_models, enabled=False, key="subagents.available_models")
        if available_models is not None else None
    )
    normalized_models = config.parse_subagent_models(
        models,
        enabled=normalized_enabled,
        setup_complete=True,
    )
    raw_profiles: list[dict]
    if profiles is None:
        raw_profiles = [
            profile.as_dict()
            for profile in config.default_subagent_profiles(normalized_models)
        ]
    else:
        raw_profiles = profiles
    normalized_profiles = config.parse_subagent_profiles(
        raw_profiles,
        models=normalized_models,
    )

    config_path = Path(path).expanduser()
    original = _read(config_path)
    prepared, inline_custom = _remove_standard_subagent_settings(original, config_path)
    if inline_custom:
        prepared = _add_inline_subagent_custom_settings(prepared, inline_custom)
    candidate = _add_standard_subagent_settings(
        prepared,
        enabled=normalized_enabled,
        strategy=normalized_strategy,
        models=normalized_models,
        profiles=normalized_profiles,
        preference=normalized_preference,
    )
    if normalized_available is not None:
        # An omitted catalog preserves the last confirmed snapshot. Only an
        # actual setup/keep answer may advance it to a newly observed catalog.
        assignments, tables = _scan(candidate)
        target = ("subagents", "available_models")
        ranges = [(item.start, item.end) for item in assignments if item.path[:2] == target]
        ranges.extend((item.start, item.end) for item in tables if item.path[:2] == target)
        candidate = _remove_ranges(candidate, ranges)
        candidate = _replace_or_add_subagent_setting(candidate, target, _render_value({
            model.name: list(model.reasoning_efforts) for model in normalized_available
        }))
    parsed = _parse(candidate, config_path)
    loaded = config.from_mapping(parsed, path=config_path, exists=bool(candidate))
    changed = candidate != original
    if changed:
        _atomic_write(config_path, candidate)
    return SubagentsConfigEditResult(
        path=str(config_path),
        changed=changed,
        config=loaded.subagents,
    )


_STANDARD_SUBAGENT_ASSIGNMENTS = frozenset(
    {
        ("subagents", "enabled"),
        ("subagents", "strategy"),
        ("subagents", "setup_complete"),
        ("subagents", "preference"),
        ("subagents", "models"),
        ("subagents", "profiles"),
    }
)


def _remove_standard_subagent_settings(
    text: str,
    path: Path,
) -> tuple[str, dict[str, Any]]:
    """Drop standard settings while retaining custom SubAgent settings."""

    parsed = _parse(text, path)
    assignments, tables = _scan(text)
    ranges: list[tuple[int, int]] = []
    inline_custom: dict[str, Any] = {}
    for assignment in assignments:
        if assignment.path == ("subagents",):
            raw_subagents = parsed.get("subagents")
            if isinstance(raw_subagents, dict):
                inline_custom = {
                    key: value
                    for key, value in raw_subagents.items()
                    if key not in {
                        "enabled",
                        "strategy",
                        "setup_complete",
                        "preference",
                        "models",
                        "profiles",
                    }
                }
            ranges.append((assignment.start, assignment.end))
        elif (
            assignment.path in _STANDARD_SUBAGENT_ASSIGNMENTS
            or assignment.path[:2] in {
                ("subagents", "models"),
                ("subagents", "profiles"),
            }
        ):
            ranges.append((assignment.start, assignment.end))
    for table in tables:
        if table.path[:2] in {
            ("subagents", "models"),
            ("subagents", "profiles"),
        }:
            ranges.append((table.start, table.end))
    return _remove_ranges(text, ranges), inline_custom


def _remove_ranges(text: str, ranges: list[tuple[int, int]]) -> str:
    """Remove possibly overlapping ranges from right to left."""

    merged: list[tuple[int, int]] = []
    for start, end in sorted(ranges):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    for start, end in reversed(merged):
        text = text[:start] + text[end:]
    return text


def _add_inline_subagent_custom_settings(text: str, custom: dict[str, Any]) -> str:
    for key, value in custom.items():
        text = _replace_or_add(
            text,
            ("subagents", key),
            _render_value(value),
        )
    return text


def _add_standard_subagent_settings(
    text: str,
    *,
    enabled: bool,
    strategy: str,
    models: tuple[config.SubagentModelConfig, ...],
    profiles: tuple[config.SubagentTaskProfileConfig, ...],
    preference: str,
) -> str:
    values = {
        "enabled": enabled,
        "strategy": strategy,
        "setup_complete": True,
        "preference": preference,
        "profiles": [profile.as_dict() for profile in profiles],
    }
    for key, value in values.items():
        text = _replace_or_add_subagent_setting(
            text,
            ("subagents", key),
            _render_value(value),
        )
    for model in models:
        text = _replace_or_add_subagent_setting(
            text,
            ("subagents", "models", model.name),
            _render_value(list(model.reasoning_efforts)),
        )
    if not models:
        text = _ensure_table(text, ("subagents", "models"))
    return text


def _replace_or_add_subagent_setting(
    text: str,
    target: tuple[str, ...],
    rendered: str,
) -> str:
    """Add a setting without redefining a parent created by dotted keys."""

    assignments, tables = _scan(text)
    if any(assignment.path == target for assignment in assignments) or any(
        table.path == ("subagents",) for table in tables
    ):
        return _replace_or_add(text, target, rendered)
    if any(assignment.path[:1] == ("subagents",) for assignment in assignments):
        newline = "\r\n" if "\r\n" in text else "\n"
        line = ".".join(_render_key(part) for part in target)
        line = f"{line} = {rendered}{newline}"
        position = min((table.start for table in tables), default=len(text))
        prefix = text[:position]
        if prefix and not prefix.endswith(("\n", "\r")):
            line = newline + line
        return prefix + line + text[position:]
    return _replace_or_add(text, target, rendered)


def _ensure_table(text: str, target: tuple[str, ...]) -> str:
    _, tables = _scan(text)
    if any(table.path == target for table in tables):
        return text
    newline = "\r\n" if "\r\n" in text else "\n"
    prefix = text
    if prefix and not prefix.endswith(("\n", "\r")):
        prefix += newline
    if prefix and not prefix.endswith(newline * 2):
        prefix += newline
    header = ".".join(_render_key(part) for part in target)
    return f"{prefix}[{header}]{newline}"


def _remove_array_tables(text: str, target: tuple[str, ...]) -> str:
    """Remove array-of-table entries for a settable aggregate value.

    `subagents.profiles` is documented in readable ``[[...]]`` form, while the
    config editor writes one equivalent inline-table array assignment. Removing
    all matching blocks first lets set/unset work with either representation.
    """

    _, tables = _scan(text)
    matches = [table for table in tables if table.array and table.path == target]
    for table in reversed(matches):
        text = text[: table.start] + text[table.end :]
    return text


def _preserve_inferred_setup_completion(
    original: str,
    candidate: str,
    path: Path,
) -> str:
    """Persist a legacy completed state before an ordinary field edit.

    A legacy file has no explicit setup marker.  Removing its last model must
    not accidentally turn an enabled configuration back into first-use setup.
    """

    original_data = _parse(original, path)
    original_subagents = original_data.get("subagents", {})
    if (
        not isinstance(original_subagents, dict)
        or "setup_complete" in original_subagents
    ):
        return candidate
    original_config = config.from_mapping(
        original_data,
        path=path,
        exists=bool(original),
    )
    candidate_data = _parse(candidate, path)
    candidate_subagents = candidate_data.get("subagents", {})
    if (
        original_config.subagents.setup_complete
        and isinstance(candidate_subagents, dict)
        and "setup_complete" not in candidate_subagents
        and not config.from_mapping(candidate_data, path=path, exists=bool(candidate)).subagents.setup_complete
    ):
        return _replace_or_add_subagent_setting(
            candidate,
            ("subagents", "setup_complete"),
            "true",
        )
    return candidate


def _read(path: Path) -> str:
    if not path.exists():
        return ""
    with path.open("r", encoding="utf-8", newline="") as handle:
        return handle.read()


def _key_path(key: str) -> tuple[str, ...]:
    prefix = "subagents.models."
    if key.startswith(prefix):
        return ("subagents", "models", key.removeprefix(prefix))
    return tuple(key.split("."))


def _replace_or_add(text: str, target: tuple[str, ...], rendered: str) -> str:
    assignments, tables = _scan(text)
    assignment = next((item for item in assignments if item.path == target), None)
    if assignment is not None:
        return text[: assignment.value_start] + rendered + text[assignment.value_end :]

    table_path = target[:-1]
    table = next((item for item in tables if item.path == table_path), None)
    newline = "\r\n" if "\r\n" in text else "\n"
    line = f"{_render_key(target[-1])} = {rendered}{newline}"
    if table is not None:
        local_assignments = [
            item
            for item in assignments
            if table.content_start <= item.start < table.end
        ]
        position = max(
            (item.end for item in local_assignments),
            default=table.content_start,
        )
        prefix = text[:position]
        if prefix and not prefix.endswith(("\n", "\r")):
            line = newline + line
        return prefix + line + text[position:]

    prefix = text
    if prefix and not prefix.endswith(("\n", "\r")):
        prefix += newline
    if prefix and not prefix.endswith(newline * 2):
        prefix += newline
    header = ".".join(_render_key(part) for part in table_path)
    return f"{prefix}[{header}]{newline}{line}"


def _scan(text: str) -> tuple[list[_Assignment], list[_Table]]:
    assignments: list[_Assignment] = []
    table_markers: list[tuple[tuple[str, ...], int, int, bool]] = []
    current_table: tuple[str, ...] = ()
    offset = 0
    lines = text.splitlines(keepends=True)
    index = 0
    while index < len(lines):
        line = lines[index]
        line_start = offset
        line_end = line_start + len(line)
        table_path = _parse_table_path(line)
        if table_path is not None:
            current_table = table_path
            table_markers.append(
                (table_path, line_start, line_end, line.lstrip().startswith("[["))
            )
            offset = line_end
            index += 1
            continue

        equal = _assignment_equal(line)
        if equal is not None:
            local_path = _parse_key_path(line[:equal])
            if local_path is not None:
                value_start, value_end, statement_end = _value_span(
                    text,
                    line_start + equal + 1,
                )
                assignments.append(
                    _Assignment(
                        current_table + local_path,
                        line_start,
                        statement_end,
                        value_start,
                        value_end,
                    )
                )
                while index < len(lines) and offset < statement_end:
                    offset += len(lines[index])
                    index += 1
                continue

        offset = line_end
        index += 1

    tables = [
        _Table(
            path=path,
            start=start,
            content_start=content_start,
            end=table_markers[position + 1][1]
            if position + 1 < len(table_markers)
            else len(text),
            array=is_array,
        )
        for position, (path, start, content_start, is_array) in enumerate(table_markers)
    ]
    return assignments, tables


def _parse_table_path(line: str) -> tuple[str, ...] | None:
    stripped = line.lstrip()
    if not stripped.startswith("["):
        return None
    try:
        parsed = tomllib.loads(
            f'{line.rstrip()}\n__tapl_table_probe__ = "__tapl_table_probe__"\n'
        )
    except tomllib.TOMLDecodeError:
        return None
    probe_path = _find_probe(parsed, "__tapl_table_probe__")
    return probe_path[:-1] if probe_path is not None else None


def _assignment_equal(line: str) -> int | None:
    quote = ""
    escaped = False
    for index, character in enumerate(line):
        if quote:
            if quote == '"' and character == "\\" and not escaped:
                escaped = True
                continue
            if character == quote and not escaped:
                quote = ""
            escaped = False
            continue
        if character in {'"', "'"}:
            quote = character
        elif character == "#":
            return None
        elif character == "=":
            return index
    return None


def _parse_key_path(lhs: str) -> tuple[str, ...] | None:
    try:
        parsed = tomllib.loads(f"{lhs}= \"__tapl_key_probe__\"\n")
    except tomllib.TOMLDecodeError:
        return None
    return _find_probe(parsed, "__tapl_key_probe__")


def _find_probe(data: Any, probe: Any) -> tuple[str, ...] | None:
    if isinstance(data, dict):
        for key, value in data.items():
            if value == probe:
                return (key,)
            nested = _find_probe(value, probe)
            if nested is not None:
                return (key, *nested)
    elif isinstance(data, list):
        for value in data:
            nested = _find_probe(value, probe)
            if nested is not None:
                return nested
    return None


def _value_span(text: str, after_equal: int) -> tuple[int, int, int]:
    start = after_equal
    while start < len(text) and text[start] in " \t":
        start += 1

    index = start
    square_depth = 0
    curly_depth = 0
    quote = ""
    triple = False
    escaped = False
    in_comment = False
    last_significant = start
    while index < len(text):
        character = text[index]
        if in_comment:
            if character in "\r\n":
                in_comment = False
                if square_depth == 0 and curly_depth == 0:
                    return start, last_significant, _newline_end(text, index)
            index += 1
            continue

        if quote:
            if triple and text.startswith(quote * 3, index):
                index += 3
                quote = ""
                triple = False
                escaped = False
                last_significant = index
                continue
            if not triple and quote == '"' and character == "\\" and not escaped:
                escaped = True
                index += 1
                last_significant = index
                continue
            if not triple and character == quote and not escaped:
                quote = ""
            escaped = False
            index += 1
            last_significant = index
            continue

        if character in {'"', "'"}:
            quote = character
            triple = text.startswith(character * 3, index)
            step = 3 if triple else 1
            index += step
            last_significant = index
            continue
        if character == "#":
            in_comment = True
            index += 1
            continue
        if character == "[":
            square_depth += 1
        elif character == "]":
            square_depth -= 1
        elif character == "{":
            curly_depth += 1
        elif character == "}":
            curly_depth -= 1
        elif character in "\r\n" and square_depth == 0 and curly_depth == 0:
            return start, last_significant, _newline_end(text, index)

        index += 1
        if not character.isspace():
            last_significant = index
    return start, last_significant, len(text)


def _newline_end(text: str, index: int) -> int:
    if text.startswith("\r\n", index):
        return index + 2
    return index + 1


def _render_key(value: str) -> str:
    if (
        value
        and value.isascii()
        and all(character.isalnum() or character in "_-" for character in value)
    ):
        return value
    return json.dumps(value, ensure_ascii=False)


def _render_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, list):
        return "[" + ", ".join(_render_value(item) for item in value) + "]"
    if isinstance(value, dict):
        return "{" + ", ".join(
            f"{_render_key(key)} = {_render_value(item)}"
            for key, item in value.items()
        ) + "}"
    if isinstance(value, (int, float)):
        return repr(value)
    raise TypeError(f"unsupported TOML value type: {type(value).__name__}")


def _parse(text: str, path: Path) -> dict[str, Any]:
    try:
        parsed = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"invalid TOML config {path}: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ValueError(f"tapl config must be a TOML table: {path}")
    return parsed


def _validate(text: str, path: Path) -> None:
    parsed = _parse(text, path)
    config.from_mapping(parsed, path=path, exists=bool(text))


def _mapping_contains(data: dict[str, Any], path: tuple[str, ...]) -> bool:
    current: Any = data
    for part in path:
        if not isinstance(current, dict) or part not in current:
            return False
        current = current[part]
    return True


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    existing_mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else None
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        if existing_mode is not None:
            os.chmod(temporary, existing_mode)
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
