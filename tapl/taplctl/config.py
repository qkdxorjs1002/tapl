"""Configuration loading for tapl."""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from pathlib import Path
from typing import Any
import tomllib
from urllib.parse import urlsplit

from . import db


CONFIG_RELATIVE = Path(".tapl") / "config.toml"

DEFAULT_SEARCH_MODE = "hybrid"
DEFAULT_HYBRID_SEMANTIC_RATIO = 0.65
DEFAULT_SEARCH_MAX_RESULTS = 12
DEFAULT_SEMANTIC_PROVIDER = "auto"
DEFAULT_SEARCHD_MODEL_IDLE_TIMEOUT_SECONDS = 1800
DEFAULT_SUBAGENTS_ENABLED = True
DEFAULT_SUBAGENT_STRATEGY = "aggressive"
DEFAULT_SUBAGENT_MODELS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("gpt-5.6-sol", ("medium", "high", "xhigh", "max")),
    ("gpt-5.6-terra", ("high", "xhigh")),
    ("gpt-5.6-luna", ("xhigh", "max")),
)
DEFAULT_SUBAGENT_PROFILE_SPECS: tuple[
    tuple[str, str, str, str, tuple[tuple[str, str], ...]], ...
] = (
    (
        "high-risk-cross-cutting",
        (
            "High-risk, cross-cutting work where mistakes could affect security, "
            "data integrity, compatibility, or multiple system boundaries."
        ),
        (
            "Broad changes across components; ambiguous failure modes; security, "
            "migration, concurrency, or irreversible-impact concerns."
        ),
        "avoid",
        (
            ("gpt-5.6-sol", "max"),
            ("gpt-5.6-sol", "xhigh"),
            ("gpt-5.6-terra", "xhigh"),
        ),
    ),
    (
        "deep-reasoning",
        (
            "Complex analysis or implementation that benefits from sustained "
            "reasoning and careful trade-off evaluation."
        ),
        (
            "Novel architecture, subtle debugging, multi-step inference, competing "
            "constraints, or uncertain solution paths."
        ),
        "neutral",
        (
            ("gpt-5.6-sol", "xhigh"),
            ("gpt-5.6-terra", "xhigh"),
            ("gpt-5.6-sol", "max"),
        ),
    ),
    (
        "general-implementation",
        "Typical implementation work with a clear outcome and moderate scope.",
        (
            "Feature changes, refactoring, integration work, and tests spanning a "
            "small number of related components."
        ),
        "inherit",
        (
            ("gpt-5.6-terra", "high"),
            ("gpt-5.6-luna", "xhigh"),
            ("gpt-5.6-sol", "high"),
        ),
    ),
    (
        "bounded-routine",
        (
            "Small, well-scoped routine work with clear inputs, outputs, and "
            "verification."
        ),
        (
            "Local edits, mechanical updates, focused tests, and predictable "
            "implementation with limited context."
        ),
        "prefer",
        (
            ("gpt-5.6-luna", "xhigh"),
            ("gpt-5.6-terra", "high"),
            ("gpt-5.6-sol", "medium"),
        ),
    ),
)

SEARCH_MODES = ("semantic", "bm25", "word", "hybrid")
SEMANTIC_PROVIDERS = ("local", "daemon", "auto")
SUBAGENT_STRATEGIES = ("conservative", "balanced", "aggressive")
SUBAGENT_DELEGATION_BIASES = ("inherit", "prefer", "neutral", "avoid")


@dataclass(frozen=True)
class EditableConfigKey:
    """A public config key accepted by ``taplctl config set``."""

    key: str
    value_name: str
    description: str
    allowed: tuple[str, ...] = ()
    dynamic_prefix: str = ""

    def matches(self, candidate: str) -> bool:
        if self.dynamic_prefix:
            suffix = candidate.removeprefix(self.dynamic_prefix)
            return candidate.startswith(self.dynamic_prefix) and bool(suffix)
        return candidate == self.key


EDITABLE_CONFIG_KEYS = (
    EditableConfigKey(
        "search.mode",
        "MODE",
        "Search backend.",
        allowed=SEARCH_MODES,
    ),
    EditableConfigKey(
        "search.max_results",
        "INTEGER",
        "Default result limit; integer greater than or equal to 1.",
    ),
    EditableConfigKey(
        "search.hybrid_semantic_ratio",
        "NUMBER",
        "Hybrid semantic weight; number from 0.0 to 1.0.",
    ),
    EditableConfigKey(
        "search.semantic_provider",
        "PROVIDER",
        "Semantic model provider.",
        allowed=SEMANTIC_PROVIDERS,
    ),
    EditableConfigKey(
        "search.searchd_model_idle_timeout_seconds",
        "SECONDS",
        "Idle model timeout; integer greater than or equal to 0.",
    ),
    EditableConfigKey(
        "viewer.allowed_origins",
        "TOML_ARRAY",
        "Unique HTTP(S) origins as a TOML string array.",
    ),
    EditableConfigKey(
        "subagents.enabled",
        "BOOLEAN",
        "Whether eligible tasks may be delegated; true or false.",
        allowed=("true", "false"),
    ),
    EditableConfigKey(
        "subagents.strategy",
        "STRATEGY",
        "SubAgent delegation strategy.",
        allowed=SUBAGENT_STRATEGIES,
    ),
    EditableConfigKey(
        "subagents.models.<model-id>",
        "TOML_ARRAY",
        "Allowed reasoning efforts for one model as a non-empty, unique TOML string array.",
        dynamic_prefix="subagents.models.",
    ),
    EditableConfigKey(
        "subagents.profiles",
        "TOML_ARRAY",
        "Ordered advisory task profiles as TOML inline tables.",
    ),
)


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


@dataclass(frozen=True)
class SubagentModelCandidateConfig:
    """One ordered, allowlisted model/effort preference for a task profile."""

    model: str
    reasoning_effort: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "reasoning_effort": self.reasoning_effort,
        }


@dataclass(frozen=True)
class SubagentTaskProfileConfig:
    """User-defined advisory routing preferences for a class of tasks."""

    name: str
    description: str = ""
    characteristics: str = ""
    delegation_bias: str = "inherit"
    candidates: tuple[SubagentModelCandidateConfig, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "characteristics": self.characteristics,
            "delegation_bias": self.delegation_bias,
            "candidates": [candidate.as_dict() for candidate in self.candidates],
        }


def default_subagent_models() -> tuple[SubagentModelConfig, ...]:
    return tuple(
        SubagentModelConfig(name=name, reasoning_efforts=reasoning_efforts)
        for name, reasoning_efforts in DEFAULT_SUBAGENT_MODELS
    )


def default_subagent_profiles(
    models: tuple[SubagentModelConfig, ...] | None = None,
) -> tuple[SubagentTaskProfileConfig, ...]:
    """Build advisory defaults, retaining candidates supported by ``models``."""

    allowed_efforts = None
    if models is not None:
        allowed_efforts = {
            model.name: set(model.reasoning_efforts)
            for model in models
        }

    profiles: list[SubagentTaskProfileConfig] = []
    for name, description, characteristics, delegation_bias, candidate_specs in (
        DEFAULT_SUBAGENT_PROFILE_SPECS
    ):
        candidates = tuple(
            SubagentModelCandidateConfig(
                model=model_name,
                reasoning_effort=reasoning_effort,
            )
            for model_name, reasoning_effort in candidate_specs
            if allowed_efforts is None
            or reasoning_effort in allowed_efforts.get(model_name, set())
        )
        profiles.append(
            SubagentTaskProfileConfig(
                name=name,
                description=description,
                characteristics=characteristics,
                delegation_bias=delegation_bias,
                candidates=candidates,
            )
        )
    return tuple(profiles)


@dataclass(frozen=True)
class SubagentsConfig:
    enabled: bool = DEFAULT_SUBAGENTS_ENABLED
    strategy: str = DEFAULT_SUBAGENT_STRATEGY
    models: tuple[SubagentModelConfig, ...] = field(default_factory=default_subagent_models)
    profiles: tuple[SubagentTaskProfileConfig, ...] = field(
        default_factory=default_subagent_profiles
    )

    def as_dict(self) -> dict[str, Any]:
        rendered: dict[str, Any] = {
            "enabled": self.enabled,
            "strategy": self.strategy,
            "models": {
                model.name: list(model.reasoning_efforts)
                for model in self.models
            },
        }
        if self.profiles:
            rendered["profiles"] = [profile.as_dict() for profile in self.profiles]
        return rendered


@dataclass(frozen=True)
class ViewerConfig:
    allowed_origins: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {"allowed_origins": list(self.allowed_origins)}


@dataclass(frozen=True)
class TaplConfig:
    path: str
    exists: bool
    search: SearchConfig = field(default_factory=SearchConfig)
    subagents: SubagentsConfig = field(default_factory=SubagentsConfig)
    viewer: ViewerConfig = field(default_factory=ViewerConfig)

    def as_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "exists": self.exists,
            "search": self.search.as_dict(),
            "viewer": self.viewer.as_dict(),
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

    return from_mapping(data, path=config_path, exists=exists)


def from_mapping(
    data: dict[str, Any],
    *,
    path: Path | str,
    exists: bool = True,
) -> TaplConfig:
    """Validate already parsed TOML data using the runtime config rules."""

    config_path = Path(path)

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
    subagent_strategy = choice(
        setting(
            subagents_data,
            "strategy",
            default=DEFAULT_SUBAGENT_STRATEGY,
        ),
        SUBAGENT_STRATEGIES,
        "subagents.strategy",
    )
    if "models" in subagents_data:
        subagent_models = parse_subagent_models(
            subagents_data["models"],
            enabled=subagents_enabled,
        )
    else:
        subagent_models = default_subagent_models()
    if "profiles" in subagents_data:
        subagent_profiles = parse_subagent_profiles(
            subagents_data["profiles"],
            models=subagent_models,
        )
    else:
        subagent_profiles = default_subagent_profiles(subagent_models)
    viewer_data = table(data, "viewer")
    viewer = ViewerConfig(
        allowed_origins=origin_array(
            setting(
                viewer_data,
                "allowed_origins",
                "allowed-origins",
                default=[],
            ),
            "viewer.allowed_origins",
        )
    )

    return TaplConfig(
        path=str(config_path),
        exists=exists,
        search=search,
        viewer=viewer,
        subagents=SubagentsConfig(
            enabled=subagents_enabled,
            strategy=subagent_strategy,
            models=subagent_models,
            profiles=subagent_profiles,
        ),
    )


def editable_config_key(key: str) -> EditableConfigKey:
    candidate = key.strip()
    if candidate != key or not candidate:
        raise ValueError("config key must be a non-empty dot-separated key")
    for spec in EDITABLE_CONFIG_KEYS:
        if spec.matches(candidate):
            return spec
    supported = ", ".join(spec.key for spec in EDITABLE_CONFIG_KEYS)
    raise ValueError(f"unsupported config key: {key}; supported keys: {supported}")


def parse_editable_value(key: str, raw_value: str) -> Any:
    """Parse and normalize a CLI value for one editable config key."""

    spec = editable_config_key(key)
    value: Any
    normalized = raw_value.strip().lower().replace("-", "_")
    if key != "subagents.enabled" and spec.allowed and normalized in spec.allowed:
        value = raw_value
    else:
        try:
            parsed_value = tomllib.loads(f"value = {raw_value}\n")
        except tomllib.TOMLDecodeError as exc:
            raise ValueError(
                f"{key} value must use TOML syntax (string choices may be unquoted)"
            ) from exc
        if set(parsed_value) != {"value"}:
            raise ValueError(f"{key} value must be one TOML value")
        value = parsed_value["value"]

    if key == "search.mode":
        return choice(value, SEARCH_MODES, key)
    if key == "search.max_results":
        return positive_int(value, key)
    if key == "search.hybrid_semantic_ratio":
        return ratio(value, key)
    if key == "search.semantic_provider":
        return choice(value, SEMANTIC_PROVIDERS, key)
    if key == "search.searchd_model_idle_timeout_seconds":
        return non_negative_int(value, key)
    if key == "viewer.allowed_origins":
        return list(origin_array(value, key))
    if key == "subagents.enabled":
        return boolean(value, key)
    if key == "subagents.strategy":
        return choice(value, SUBAGENT_STRATEGIES, key)
    if key == "subagents.profiles":
        profiles = parse_subagent_profiles(
            value,
            models=None,
            key=key,
        )
        return [profile.as_dict() for profile in profiles]
    if spec.dynamic_prefix:
        model_name = key.removeprefix(spec.dynamic_prefix)
        if model_name != model_name.strip():
            raise ValueError("subagents.models model names must not have surrounding whitespace")
        parsed = parse_subagent_models({model_name: value}, enabled=False)
        return list(parsed[0].reasoning_efforts)
    raise AssertionError(f"editable config key has no parser: {key}")


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


def http_origin(value: Any, key: str = "origin") -> str:
    message = f"{key} must be an HTTP(S) origin without a path, query, or fragment"
    if not isinstance(value, str):
        raise ValueError(message)
    candidate = value.strip()
    if not candidate or any(character.isspace() for character in candidate):
        raise ValueError(message)
    try:
        parsed = urlsplit(candidate)
        port = parsed.port
    except ValueError as exc:
        raise ValueError(message) from exc
    scheme = parsed.scheme.lower()
    if (
        scheme not in {"http", "https"}
        or parsed.hostname is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(message)

    hostname = parsed.hostname.lower()
    authority = f"[{hostname}]" if ":" in hostname else hostname
    default_port = 80 if scheme == "http" else 443
    if port is not None and port != default_port:
        authority = f"{authority}:{port}"
    return f"{scheme}://{authority}"


def origin_array(value: Any, key: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ValueError(f"{key} must be an array of HTTP(S) origin strings")

    origins: list[str] = []
    seen: set[str] = set()
    for index, raw_origin in enumerate(value):
        origin = http_origin(raw_origin, f"{key}[{index}]")
        if origin in seen:
            raise ValueError(f"{key} contains duplicate origin: {origin}")
        seen.add(origin)
        origins.append(origin)
    return tuple(origins)


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


def parse_subagent_profiles(
    value: Any,
    *,
    models: tuple[SubagentModelConfig, ...] | None,
    key: str = "subagents.profiles",
) -> tuple[SubagentTaskProfileConfig, ...]:
    """Validate ordered advisory task profiles against the model allowlist."""

    if not isinstance(value, list):
        raise ValueError(f"{key} must be an array of TOML inline tables")

    allowed_efforts: dict[str, set[str]] | None = None
    if models is not None:
        allowed_efforts = {
            model.name: set(model.reasoning_efforts)
            for model in models
        }
    profiles: list[SubagentTaskProfileConfig] = []
    seen_names: set[str] = set()
    for index, raw_profile in enumerate(value):
        profile_key = f"{key}[{index}]"
        if not isinstance(raw_profile, dict):
            raise ValueError(f"{profile_key} must be a TOML inline table")

        name = non_empty_string(raw_profile.get("name"), f"{profile_key}.name")
        if name in seen_names:
            raise ValueError(f"{key} contains duplicate profile name: {name}")
        seen_names.add(name)
        description = optional_string(
            raw_profile.get("description", ""),
            f"{profile_key}.description",
        )
        characteristics = optional_string(
            raw_profile.get("characteristics", ""),
            f"{profile_key}.characteristics",
        )
        delegation_bias = choice(
            raw_profile.get("delegation_bias", "inherit"),
            SUBAGENT_DELEGATION_BIASES,
            f"{profile_key}.delegation_bias",
        )
        raw_candidates = raw_profile.get("candidates", [])
        if not isinstance(raw_candidates, list):
            raise ValueError(
                f"{profile_key}.candidates must be an array of TOML inline tables"
            )

        candidates: list[SubagentModelCandidateConfig] = []
        seen_candidates: set[tuple[str, str]] = set()
        for candidate_index, raw_candidate in enumerate(raw_candidates):
            candidate_key = f"{profile_key}.candidates[{candidate_index}]"
            if not isinstance(raw_candidate, dict):
                raise ValueError(f"{candidate_key} must be a TOML inline table")
            model_name = non_empty_string(
                raw_candidate.get("model"),
                f"{candidate_key}.model",
            )
            reasoning_effort = non_empty_string(
                raw_candidate.get("reasoning_effort"),
                f"{candidate_key}.reasoning_effort",
            )
            if allowed_efforts is not None and model_name not in allowed_efforts:
                raise ValueError(
                    f"{candidate_key}.model must be defined in subagents.models: "
                    f"{model_name}"
                )
            if (
                allowed_efforts is not None
                and reasoning_effort not in allowed_efforts[model_name]
            ):
                raise ValueError(
                    f"{candidate_key}.reasoning_effort is not allowed for {model_name}: "
                    f"{reasoning_effort}"
                )
            candidate_id = (model_name, reasoning_effort)
            if candidate_id in seen_candidates:
                raise ValueError(
                    f"{profile_key}.candidates contains duplicate model/effort pair: "
                    f"{model_name}/{reasoning_effort}"
                )
            seen_candidates.add(candidate_id)
            candidates.append(
                SubagentModelCandidateConfig(
                    model=model_name,
                    reasoning_effort=reasoning_effort,
                )
            )
        profiles.append(
            SubagentTaskProfileConfig(
                name=name,
                description=description,
                characteristics=characteristics,
                delegation_bias=delegation_bias,
                candidates=tuple(candidates),
            )
        )
    return tuple(profiles)


def non_empty_string(value: Any, key: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must be a non-empty string")
    return value.strip()


def optional_string(value: Any, key: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{key} must be a string")
    return value.strip()


def ratio(value: Any, key: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{key} must be a number between 0.0 and 1.0")
    parsed = float(value)
    if not math.isfinite(parsed) or parsed < 0.0 or parsed > 1.0:
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
