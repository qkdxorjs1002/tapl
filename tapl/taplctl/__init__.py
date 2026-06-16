"""tapl workflow harness."""

from __future__ import annotations

from importlib import metadata
from pathlib import Path
import tomllib


def _version_from_pyproject() -> str | None:
    pyproject_path = Path(__file__).resolve().parents[1] / "pyproject.toml"
    try:
        with pyproject_path.open("rb") as pyproject_file:
            pyproject = tomllib.load(pyproject_file)
    except (FileNotFoundError, OSError, tomllib.TOMLDecodeError):
        return None

    version = pyproject.get("project", {}).get("version")
    if isinstance(version, str):
        return version
    return None


def _version() -> str:
    version = _version_from_pyproject()
    if version is not None:
        return version

    try:
        return metadata.version("taplctl")
    except metadata.PackageNotFoundError:
        return "0.0.0"


__version__ = _version()
