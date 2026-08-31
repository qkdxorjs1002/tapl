"""Comment-preserving edits for TAPL's TOML configuration."""

from __future__ import annotations

from dataclasses import dataclass
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


def set_value(path: Path | str, key: str, raw_value: str) -> ConfigEditResult:
    """Set one supported key after validating the complete resulting config."""

    config_path = Path(path).expanduser()
    value = config.parse_editable_value(key, raw_value)
    original = _read(config_path)
    rendered = _render_value(value)
    candidate = _replace_or_add(original, _key_path(key), rendered)
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
        parsed = _parse(original, config_path)
        if _mapping_contains(parsed, target):
            raise ValueError(
                f"cannot unset {key}: the value is stored in an inline TOML table"
            )
        _validate(original, config_path)
        return ConfigEditResult(str(config_path), key, False)

    candidate = original[: assignment.start] + original[assignment.end :]
    _validate(candidate, config_path)
    if candidate != original:
        _atomic_write(config_path, candidate)
    return ConfigEditResult(str(config_path), key, candidate != original)


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
    table_markers: list[tuple[tuple[str, ...], int, int]] = []
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
            table_markers.append((table_path, line_start, line_end))
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
        )
        for position, (path, start, content_start) in enumerate(table_markers)
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
    if isinstance(value, list):
        return "[" + ", ".join(_render_value(item) for item in value) + "]"
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
