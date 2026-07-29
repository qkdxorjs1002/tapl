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
DEFAULT_SEARCH_MAX_RESULTS = 12
DEFAULT_SEMANTIC_PROVIDER = "auto"
DEFAULT_SEARCHD_MODEL_IDLE_TIMEOUT_SECONDS = 1800
DEFAULT_SUBAGENTS_ENABLED = True
DEFAULT_SUBAGENT_MODELS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("gpt-5.6-sol", ("xhigh", "max")),
    ("gpt-5.6-terra", ("high", "xhigh", "max")),
    ("gpt-5.6-luna", ("high", "xhigh")),
)

SEARCH_MODES = ("semantic", "bm25", "word", "hybrid")
SEMANTIC_PROVIDERS = ("local", "daemon", "auto")


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
class SubagentModelConfig:
    name: str
    reasoning_efforts: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "reasoning_efforts": list(self.reasoning_efforts),
        }


def default_subagent_models() -> tuple[SubagentModelConfig, ...]:
    return tuple(
        SubagentModelConfig(name=name, reasoning_efforts=reasoning_efforts)
        for name, reasoning_efforts in DEFAULT_SUBAGENT_MODELS
    )


@dataclass(frozen=True)
class SubagentsConfig:
    enabled: bool = DEFAULT_SUBAGENTS_ENABLED
    models: tuple[SubagentModelConfig, ...] = field(default_factory=default_subagent_models)

    def as_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "models": {
                model.name: list(model.reasoning_efforts)
                for model in self.models
            },
        }


@dataclass(frozen=True)
class TaplConfig:
    path: str
    exists: bool
    search: SearchConfig = field(default_factory=SearchConfig)
    subagents: SubagentsConfig = field(default_factory=SubagentsConfig)

    def as_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "exists": self.exists,
            "search": self.search.as_dict(),
            "subagents": self.subagents.as_dict(),
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
    subagents_data = table(data, "subagents")
    subagents_enabled = boolean(
        setting(
            subagents_data,
            "enabled",
            default=DEFAULT_SUBAGENTS_ENABLED,
        ),
        "subagents.enabled",
    )
    if "models" in subagents_data:
        subagent_models = parse_subagent_models(
            subagents_data["models"],
            enabled=subagents_enabled,
        )
    else:
        subagent_models = default_subagent_models()

    return TaplConfig(
        path=str(config_path),
        exists=exists,
        search=search,
        subagents=SubagentsConfig(
            enabled=subagents_enabled,
            models=subagent_models,
        ),
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


def boolean(value: Any, key: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{key} must be a boolean")
    return value


def parse_subagent_models(
    value: Any,
    *,
    enabled: bool,
    key: str = "subagents.models",
) -> tuple[SubagentModelConfig, ...]:
    if not isinstance(value, dict):
        raise ValueError(f"{key} must be a TOML table")

    models: list[SubagentModelConfig] = []
    seen_models: set[str] = set()
    for raw_name, raw_efforts in value.items():
        if not isinstance(raw_name, str) or not raw_name.strip():
            raise ValueError(f"{key} model names must be non-empty strings")
        name = raw_name.strip()
        model_key = f"{key}.{name}"
        if name in seen_models:
            raise ValueError(f"{key} contains duplicate model name: {name}")
        seen_models.add(name)

        if not isinstance(raw_efforts, list):
            raise ValueError(f"{model_key} must be an array of reasoning effort strings")
        if not raw_efforts:
            raise ValueError(f"{model_key} must contain at least one reasoning effort")

        reasoning_efforts: list[str] = []
        seen: set[str] = set()
        for index, raw_effort in enumerate(raw_efforts):
            effort_key = f"{model_key}[{index}]"
            if not isinstance(raw_effort, str) or not raw_effort.strip():
                raise ValueError(f"{effort_key} must be a non-empty string")
            effort = raw_effort.strip()
            if effort in seen:
                raise ValueError(
                    f"{model_key} contains duplicate reasoning effort: {effort}"
                )
            seen.add(effort)
            reasoning_efforts.append(effort)

        models.append(
            SubagentModelConfig(
                name=name,
                reasoning_efforts=tuple(reasoning_efforts),
            )
        )

    if enabled and not models:
        raise ValueError(
            f"{key} must define at least one model when subagents.enabled is true"
        )
    return tuple(models)


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
