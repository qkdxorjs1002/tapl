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
class TaplConfig:
    path: str
    exists: bool
    search: SearchConfig = field(default_factory=SearchConfig)

    def as_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "exists": self.exists,
            "search": self.search.as_dict(),
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
    return TaplConfig(
        path=str(config_path),
        exists=exists,
        search=search,
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
