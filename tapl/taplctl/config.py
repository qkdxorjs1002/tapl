"""Configuration loading for tapl."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import tomllib

from . import db


CONFIG_RELATIVE = Path(".tapl") / "config.toml"

DEFAULT_SEARCH_MODE = "hybrid"
DEFAULT_HYBRID_SEMANTIC_RATIO = 0.65
DEFAULT_USE_LEVEL_SUBAGENT = True
DEFAULT_LEVEL_SUBAGENT_AGGRESSIVENESS = "auto"
DEFAULT_PLAN_DETAIL = "detailed"
DEFAULT_TASK_GRANULARITY = "granular"

SEARCH_MODES = ("semantic", "bm25", "word", "hybrid")
LEVEL_SUBAGENT_AGGRESSIVENESS = ("minimal", "auto", "force")
PLAN_DETAILS = ("minimal", "less_detailed", "detailed", "very_detailed")
TASK_GRANULARITIES = ("minimal", "less_granular", "granular", "very_granular")


@dataclass(frozen=True)
class SearchConfig:
    mode: str = DEFAULT_SEARCH_MODE
    hybrid_semantic_ratio: float = DEFAULT_HYBRID_SEMANTIC_RATIO

    @property
    def hybrid_bm25_ratio(self) -> float:
        return round(1.0 - self.hybrid_semantic_ratio, 6)

    def as_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "hybrid_semantic_ratio": self.hybrid_semantic_ratio,
            "hybrid_bm25_ratio": self.hybrid_bm25_ratio,
        }


@dataclass(frozen=True)
class PlanTaskExecuteConfig:
    use_level_subagent: bool = DEFAULT_USE_LEVEL_SUBAGENT
    level_subagent_aggressiveness: str = DEFAULT_LEVEL_SUBAGENT_AGGRESSIVENESS
    plan_detail: str = DEFAULT_PLAN_DETAIL
    task_granularity: str = DEFAULT_TASK_GRANULARITY

    def as_dict(self) -> dict[str, Any]:
        return {
            "use_level_subagent": self.use_level_subagent,
            "level_subagent_aggressiveness": self.level_subagent_aggressiveness,
            "plan_detail": self.plan_detail,
            "task_granularity": self.task_granularity,
        }


@dataclass(frozen=True)
class TaplConfig:
    path: str
    exists: bool
    search: SearchConfig = field(default_factory=SearchConfig)
    plan_task_execute: PlanTaskExecuteConfig = field(default_factory=PlanTaskExecuteConfig)

    def as_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "exists": self.exists,
            "search": self.search.as_dict(),
            "plan_task_execute": self.plan_task_execute.as_dict(),
        }


def default_config_path(start: Path | None = None) -> Path:
    return db.find_repo_root(start) / CONFIG_RELATIVE


def user_config_path(home: Path | None = None) -> Path:
    return (home or Path.home()).expanduser() / CONFIG_RELATIVE


def default_config_paths(start: Path | None = None, *, home: Path | None = None) -> tuple[Path, Path]:
    return (
        default_config_path(start),
        user_config_path(home),
    )


def resolve_config_path(
    path: Path | str | None = None,
    *,
    start: Path | None = None,
    home: Path | None = None,
) -> Path:
    if path:
        return Path(path).expanduser()

    candidates = default_config_paths(start, home=home)
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def load(
    path: Path | str | None = None,
    *,
    start: Path | None = None,
    home: Path | None = None,
) -> TaplConfig:
    config_path = resolve_config_path(path, start=start, home=home)
    data: dict[str, Any] = {}
    exists = config_path.exists()

    if exists:
        parsed = tomllib.loads(config_path.read_text(encoding="utf-8"))
        if not isinstance(parsed, dict):
            raise ValueError(f"tapl config must be a TOML table: {config_path}")
        data = parsed

    search_data = table(data, "search")
    plan_task_data = table(data, "plan-task-execute", "plan_task_execute")

    search = SearchConfig(
        mode=choice(
            setting(search_data, "mode", default=DEFAULT_SEARCH_MODE),
            SEARCH_MODES,
            "search.mode",
        ),
        hybrid_semantic_ratio=ratio(
            setting(
                search_data,
                "hybrid_semantic_ratio",
                "hybrid-semantic-ratio",
                "semantic_ratio",
                "semantic-ratio",
                default=DEFAULT_HYBRID_SEMANTIC_RATIO,
            ),
            "search.hybrid_semantic_ratio",
        ),
    )
    plan_task_execute = PlanTaskExecuteConfig(
        use_level_subagent=boolean(
            setting(
                plan_task_data,
                "use_level_subagent",
                "use-level-subagent",
                default=DEFAULT_USE_LEVEL_SUBAGENT,
            ),
            "plan_task_execute.use_level_subagent",
        ),
        level_subagent_aggressiveness=choice(
            setting(
                plan_task_data,
                "level_subagent_aggressiveness",
                "level-subagent-aggressiveness",
                default=DEFAULT_LEVEL_SUBAGENT_AGGRESSIVENESS,
            ),
            LEVEL_SUBAGENT_AGGRESSIVENESS,
            "plan_task_execute.level_subagent_aggressiveness",
        ),
        plan_detail=choice(
            setting(plan_task_data, "plan_detail", "plan-detail", default=DEFAULT_PLAN_DETAIL),
            PLAN_DETAILS,
            "plan_task_execute.plan_detail",
        ),
        task_granularity=choice(
            setting(plan_task_data, "task_granularity", "task-granularity", default=DEFAULT_TASK_GRANULARITY),
            TASK_GRANULARITIES,
            "plan_task_execute.task_granularity",
        ),
    )
    return TaplConfig(
        path=str(config_path),
        exists=exists,
        search=search,
        plan_task_execute=plan_task_execute,
    )


def table(data: dict[str, Any], *keys: str) -> dict[str, Any]:
    for key in keys:
        if key not in data:
            continue
        value = data[key]
        if not isinstance(value, dict):
            raise ValueError(f"{key} must be a TOML table")
        return value
    return {}


def setting(data: dict[str, Any], *keys: str, default: Any) -> Any:
    for key in keys:
        if key in data:
            return data[key]
    return default


def choice(value: Any, allowed: tuple[str, ...], key: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{key} must be a string")
    normalized = value.strip().lower().replace("-", "_")
    if normalized not in allowed:
        joined = ", ".join(allowed)
        raise ValueError(f"{key} must be one of: {joined}")
    return normalized


def ratio(value: Any, key: str) -> float:
    if not isinstance(value, (int, float)):
        raise ValueError(f"{key} must be a number between 0.0 and 1.0")
    parsed = float(value)
    if parsed < 0.0 or parsed > 1.0:
        raise ValueError(f"{key} must be between 0.0 and 1.0")
    return parsed


def boolean(value: Any, key: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{key} must be a boolean")
    return value
