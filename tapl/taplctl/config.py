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
DEFAULT_SEARCH_MAX_RESULTS = 7
DEFAULT_SEMANTIC_PROVIDER = "auto"
DEFAULT_SEARCHD_MODEL_IDLE_TIMEOUT_SECONDS = 1800
DEFAULT_USE_LEVEL_SUBAGENT = True
DEFAULT_LEVEL_SUBAGENT_AGGRESSIVENESS = "auto"
DEFAULT_PLAN_DETAIL = "detailed"
DEFAULT_PLANNING_APPROVAL_LEVEL = "auto"
DEFAULT_TASK_GRANULARITY = "granular"
DEFAULT_REQUIRE_EXECUTION_APPROVAL = True

SEARCH_MODES = ("semantic", "bm25", "word", "hybrid")
SEMANTIC_PROVIDERS = ("local", "daemon", "auto")
LEVEL_SUBAGENT_AGGRESSIVENESS = ("minimal", "auto", "force")
PLAN_DETAILS = ("minimal", "less_detailed", "detailed", "very_detailed")
PLANNING_APPROVAL_LEVELS = ("less", "auto", "more")
TASK_GRANULARITIES = ("minimal", "less_granular", "granular", "very_granular")


@dataclass(frozen=True)
class SearchConfig:
    mode: str = DEFAULT_SEARCH_MODE
    hybrid_semantic_ratio: float = DEFAULT_HYBRID_SEMANTIC_RATIO
    max_results: int = DEFAULT_SEARCH_MAX_RESULTS
    semantic_provider: str = DEFAULT_SEMANTIC_PROVIDER
    searchd_model_idle_timeout_seconds: int = DEFAULT_SEARCHD_MODEL_IDLE_TIMEOUT_SECONDS

    @property
    def searchd_idle_timeout_seconds(self) -> int:
        return self.searchd_model_idle_timeout_seconds

    @property
    def hybrid_bm25_ratio(self) -> float:
        return round(1.0 - self.hybrid_semantic_ratio, 6)

    def as_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "max_results": self.max_results,
            "hybrid_semantic_ratio": self.hybrid_semantic_ratio,
            "hybrid_bm25_ratio": self.hybrid_bm25_ratio,
            "semantic_provider": self.semantic_provider,
            "searchd_model_idle_timeout_seconds": self.searchd_model_idle_timeout_seconds,
        }


@dataclass(frozen=True)
class PlanTaskExecuteConfig:
    use_level_subagent: bool = DEFAULT_USE_LEVEL_SUBAGENT
    level_subagent_aggressiveness: str = DEFAULT_LEVEL_SUBAGENT_AGGRESSIVENESS
    plan_detail: str = DEFAULT_PLAN_DETAIL
    planning_approval_level: str = DEFAULT_PLANNING_APPROVAL_LEVEL
    task_granularity: str = DEFAULT_TASK_GRANULARITY
    require_execution_approval: bool = DEFAULT_REQUIRE_EXECUTION_APPROVAL

    def as_dict(self) -> dict[str, Any]:
        return {
            "use_level_subagent": self.use_level_subagent,
            "level_subagent_aggressiveness": self.level_subagent_aggressiveness,
            "plan_detail": self.plan_detail,
            "planning_approval_level": self.planning_approval_level,
            "task_granularity": self.task_granularity,
            "require_execution_approval": self.require_execution_approval,
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
        max_results=positive_int(
            setting(
                search_data,
                "max_results",
                "max-results",
                "limit",
                default=DEFAULT_SEARCH_MAX_RESULTS,
            ),
            "search.max_results",
        ),
        semantic_provider=choice(
            setting(
                search_data,
                "semantic_provider",
                "semantic-provider",
                default=DEFAULT_SEMANTIC_PROVIDER,
            ),
            SEMANTIC_PROVIDERS,
            "search.semantic_provider",
        ),
        searchd_model_idle_timeout_seconds=non_negative_int(
            setting(
                search_data,
                "searchd_model_idle_timeout_seconds",
                "searchd-model-idle-timeout-seconds",
                "model_idle_timeout_seconds",
                "model-idle-timeout-seconds",
                "searchd_idle_timeout_seconds",
                "searchd-idle-timeout-seconds",
                "idle_timeout_seconds",
                "idle-timeout-seconds",
                default=DEFAULT_SEARCHD_MODEL_IDLE_TIMEOUT_SECONDS,
            ),
            "search.searchd_model_idle_timeout_seconds",
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
        planning_approval_level=choice(
            setting(
                plan_task_data,
                "planning_approval_level",
                "planning-approval-level",
                default=DEFAULT_PLANNING_APPROVAL_LEVEL,
            ),
            PLANNING_APPROVAL_LEVELS,
            "plan_task_execute.planning_approval_level",
        ),
        task_granularity=choice(
            setting(plan_task_data, "task_granularity", "task-granularity", default=DEFAULT_TASK_GRANULARITY),
            TASK_GRANULARITIES,
            "plan_task_execute.task_granularity",
        ),
        require_execution_approval=boolean(
            setting(
                plan_task_data,
                "require_execution_approval",
                "require-execution-approval",
                default=DEFAULT_REQUIRE_EXECUTION_APPROVAL,
            ),
            "plan_task_execute.require_execution_approval",
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


def positive_int(value: Any, key: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{key} must be a positive integer")
    if value < 1:
        raise ValueError(f"{key} must be a positive integer")
    return value


def non_negative_int(value: Any, key: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{key} must be a non-negative integer")
    if value < 0:
        raise ValueError(f"{key} must be a non-negative integer")
    return value


def boolean(value: Any, key: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{key} must be a boolean")
    return value
