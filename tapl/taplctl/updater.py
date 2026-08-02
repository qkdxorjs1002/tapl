"""Self-update support for installations created by ``curl | sh``.

The updater deliberately refuses to operate on package-manager and source-tree
installations.  A valid installer metadata file, the active virtual
environment, and the public ``taplctl`` symlink must all describe the same
installation before either checking for or applying an update.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Any, BinaryIO, Iterator
from urllib import request as urllib_request
from urllib.parse import urlsplit


_VERSION_RE = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+")
_SHA256_RE = re.compile(r"[0-9a-fA-F]{64}")
_WHEEL_NAME_RE = re.compile(r"[A-Za-z0-9_.+-]+")
_MAX_MANIFEST_BYTES = 1024 * 1024


class UpdateError(RuntimeError):
    """A safe, user-facing self-update failure.

    ``code`` is stable enough for a CLI to select human, JSON, or agent output
    without parsing the message.  ``details`` contains non-secret structured
    context when it is useful to the caller.
    """

    def __init__(
        self,
        message: str,
        *,
        code: str = "update_failed",
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.details = dict(details or {})

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "ok": False,
            "error": {"code": self.code, "message": str(self)},
        }
        if self.details:
            payload["error"]["details"] = dict(self.details)
        return payload


@dataclass(frozen=True)
class _Installation:
    metadata_path: Path
    metadata: dict[str, Any]
    install_root: Path
    versions_dir: Path
    bin_dir: Path
    venv: Path
    executable: Path
    command: Path
    version: str
    manifest_url: str


@dataclass(frozen=True)
class _Manifest:
    version: str
    version_key: tuple[int, int, int]
    wheel_url: str
    wheel_sha256: str
    wheel_name: str


UrlOpener = Callable[[str], Any]
CommandRunner = Callable[..., Any]


def check_for_update(
    *,
    metadata_path: str | os.PathLike[str] | None = None,
    manifest_url: str | None = None,
    opener: UrlOpener | None = None,
    timeout: float = 30.0,
    current_prefix: str | os.PathLike[str] | None = None,
    current_python: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    """Return release information without changing any local file.

    ``TAPL_INSTALL_METADATA`` overrides metadata discovery for isolated tests.
    Explicit arguments take precedence over the environment.  ``opener`` is a
    small dependency-injection seam: it receives a URL and must return a binary
    file-like object (or bytes).
    """

    installation = _load_installation(
        metadata_path=metadata_path,
        current_prefix=current_prefix,
        current_python=current_python,
    )
    selected_manifest_url = _select_manifest_url(manifest_url, installation)
    manifest = _fetch_manifest(selected_manifest_url, opener=opener, timeout=timeout)
    return _check_payload(installation, manifest, selected_manifest_url)


def update_installation(
    *,
    metadata_path: str | os.PathLike[str] | None = None,
    manifest_url: str | None = None,
    opener: UrlOpener | None = None,
    timeout: float = 30.0,
    current_prefix: str | os.PathLike[str] | None = None,
    current_python: str | os.PathLike[str] | None = None,
    runner: CommandRunner | None = None,
) -> dict[str, Any]:
    """Atomically update a validated ``curl-sh`` installation.

    The old environment is retained.  A failed candidate build is removed, and
    a metadata activation failure restores the previous command symlink before
    returning an error.
    """

    installation = _load_installation(
        metadata_path=metadata_path,
        current_prefix=current_prefix,
        current_python=current_python,
    )
    selected_manifest_url = _select_manifest_url(manifest_url, installation)
    manifest = _fetch_manifest(selected_manifest_url, opener=opener, timeout=timeout)
    check_payload = _check_payload(installation, manifest, selected_manifest_url)
    if not check_payload["update_available"]:
        return {
            **check_payload,
            "action": "update",
            "updated": False,
            "status": _no_update_status(installation, manifest),
        }

    python_path = _absolute_path(current_python if current_python is not None else sys.executable)
    command_runner = runner or subprocess.run
    candidate: Path | None = None
    keep_candidate = False

    try:
        with tempfile.TemporaryDirectory(prefix="tapl-update-") as work_dir_name:
            work_dir = Path(work_dir_name)
            wheel_path = work_dir / manifest.wheel_name
            _download_wheel(
                manifest,
                wheel_path,
                opener=opener,
                timeout=timeout,
            )

            candidate = Path(
                tempfile.mkdtemp(
                    prefix=f"{manifest.version}-{manifest.wheel_sha256[:12]}.",
                    dir=installation.versions_dir,
                )
            )
            _build_candidate(
                candidate,
                wheel_path,
                manifest.version,
                python_path=python_path,
                runner=command_runner,
            )

            # Refuse a concurrent ownership or metadata change after the slow
            # download/install phase and before either atomic replacement.
            current_installation = _load_installation(
                metadata_path=installation.metadata_path,
                current_prefix=current_prefix,
                current_python=current_python,
            )
            if current_installation.metadata != installation.metadata:
                raise UpdateError(
                    "install metadata changed while the update was being prepared",
                    code="installation_changed",
                )

            _activate_candidate(
                installation,
                candidate,
                manifest,
                selected_manifest_url,
            )
            keep_candidate = True
    except UpdateError as exc:
        # A rollback failure can leave the public link on the candidate.  Keep
        # that environment in this exceptional case rather than create a
        # broken command while reporting the activation failure.
        if exc.details.get("candidate_active"):
            keep_candidate = True
        raise
    except (OSError, subprocess.SubprocessError) as exc:
        raise UpdateError(
            f"could not prepare the taplctl update: {exc}",
            code="update_prepare_failed",
        ) from exc
    finally:
        if candidate is not None and not keep_candidate:
            _remove_candidate(candidate)

    return {
        "ok": True,
        "action": "update",
        "status": "updated",
        "updated": True,
        "update_available": False,
        "previous_version": installation.version,
        "current_version": manifest.version,
        "latest_version": manifest.version,
        "manifest_url": _safe_url(selected_manifest_url),
        "wheel_url": _safe_url(manifest.wheel_url),
        "wheel_sha256": manifest.wheel_sha256,
        "install_root": str(installation.install_root),
        "venv": str(candidate),
        "executable": str(installation.executable),
    }


def _metadata_path(
    metadata_path: str | os.PathLike[str] | None,
    current_prefix: str | os.PathLike[str] | None,
) -> Path:
    if metadata_path is not None:
        return _absolute_path(metadata_path)
    override = os.environ.get("TAPL_INSTALL_METADATA")
    if override:
        return _absolute_path(override)
    prefix = _absolute_path(current_prefix if current_prefix is not None else sys.prefix)
    return prefix.parent.parent / "install.json"


def _load_installation(
    *,
    metadata_path: str | os.PathLike[str] | None,
    current_prefix: str | os.PathLike[str] | None,
    current_python: str | os.PathLike[str] | None,
) -> _Installation:
    prefix = _absolute_path(current_prefix if current_prefix is not None else sys.prefix)
    python_path = _absolute_path(current_python if current_python is not None else sys.executable)
    path = _metadata_path(metadata_path, prefix)

    try:
        if path.is_symlink() or not path.is_file():
            raise ValueError("metadata is missing or is not a regular file")
        metadata = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise UpdateError(
            "taplctl is not running from a valid curl-sh installation",
            code="unsupported_installation",
            details={"metadata_path": str(path)},
        ) from exc

    try:
        if not isinstance(metadata, dict):
            raise ValueError("metadata root is not an object")
        schema = metadata.get("schema_version")
        if schema != 1 or isinstance(schema, bool):
            raise ValueError("unsupported metadata schema")
        if metadata.get("method") != "curl-sh":
            raise ValueError("installation method is not curl-sh")

        install_root = _metadata_absolute_path(metadata, "install_root")
        bin_dir = _metadata_absolute_path(metadata, "bin_dir")
        venv = _metadata_absolute_path(metadata, "venv")
        executable = _metadata_absolute_path(metadata, "executable")
        versions_dir = install_root / "versions"
        command = venv / "bin" / "taplctl"

        if path != install_root / "install.json":
            raise ValueError("metadata path is outside the recorded install root")
        if executable != bin_dir / "taplctl":
            raise ValueError("recorded executable is outside the recorded bin directory")
        if not _is_strict_descendant(venv, versions_dir):
            raise ValueError("recorded venv is outside the versions directory")
        if prefix != venv:
            raise ValueError("the active Python prefix is not the recorded venv")
        if python_path != venv / "bin" / "python":
            raise ValueError("the active Python executable is not owned by the recorded venv")
        if not install_root.is_dir() or not versions_dir.is_dir() or not bin_dir.is_dir():
            raise ValueError("recorded installation directories are missing")
        if not command.is_file() or not os.access(command, os.X_OK):
            raise ValueError("recorded taplctl command is missing or not executable")
        if not executable.is_symlink():
            raise ValueError("the public taplctl executable is not a symlink")
        if _resolved_link_target(executable) != command:
            raise ValueError("the public taplctl symlink is not owned by this installation")

        version = _required_version(metadata.get("version"), "install metadata version")
        manifest_url = _required_url(metadata.get("manifest_url"), "install metadata manifest URL")
        _required_url(metadata.get("wheel_url"), "install metadata wheel URL")
        wheel_sha256 = metadata.get("wheel_sha256")
        if not isinstance(wheel_sha256, str) or _SHA256_RE.fullmatch(wheel_sha256) is None:
            raise ValueError("invalid install metadata wheel SHA-256")
    except (KeyError, OSError, ValueError) as exc:
        raise UpdateError(
            "taplctl is not running from a valid curl-sh installation",
            code="unsupported_installation",
            details={"metadata_path": str(path)},
        ) from exc

    return _Installation(
        metadata_path=path,
        metadata=metadata,
        install_root=install_root,
        versions_dir=versions_dir,
        bin_dir=bin_dir,
        venv=venv,
        executable=executable,
        command=command,
        version=version,
        manifest_url=manifest_url,
    )


def _metadata_absolute_path(metadata: Mapping[str, Any], field: str) -> Path:
    value = metadata.get(field)
    if not isinstance(value, str) or not value or "\x00" in value:
        raise ValueError(f"invalid install metadata {field}")
    if not os.path.isabs(value) or os.path.abspath(value) != value:
        raise ValueError(f"install metadata {field} is not a normalized absolute path")
    return Path(value)


def _absolute_path(value: str | os.PathLike[str]) -> Path:
    return Path(os.path.abspath(os.path.expanduser(os.fspath(value))))


def _is_strict_descendant(path: Path, parent: Path) -> bool:
    try:
        return path != parent and os.path.commonpath((path, parent)) == str(parent)
    except ValueError:
        return False


def _resolved_link_target(path: Path) -> Path:
    target = os.readlink(path)
    if os.path.isabs(target):
        return Path(os.path.abspath(target))
    return Path(os.path.abspath(path.parent / target))


def _select_manifest_url(override: str | None, installation: _Installation) -> str:
    if override is None:
        return installation.manifest_url
    try:
        return _required_url(override, "manifest URL")
    except ValueError as exc:
        raise UpdateError(
            str(exc),
            code="invalid_manifest_url",
            details={"manifest_url": _safe_url(override)},
        ) from exc


def _required_url(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value or any(char in value for char in "\r\n\t"):
        raise ValueError(f"invalid {label}")
    return value


def _safe_url(value: Any) -> str:
    """Return a display-only URL without credentials or request secrets."""

    if not isinstance(value, str):
        return "<invalid-url>"
    try:
        parsed = urlsplit(value)
        if (
            re.fullmatch(r"[A-Za-z][A-Za-z0-9+.-]*", parsed.scheme) is None
            or parsed.hostname is None
        ):
            return "<invalid-url>"
        port = parsed.port
        hostname = parsed.hostname
        if ":" in hostname:
            hostname = f"[{hostname}]"
        authority = hostname if port is None else f"{hostname}:{port}"
        return f"{parsed.scheme}://{authority}{parsed.path}"
    except (TypeError, ValueError):
        return "<invalid-url>"


def _required_version(value: Any, label: str) -> str:
    if not isinstance(value, str) or _VERSION_RE.fullmatch(value) is None:
        raise ValueError(f"invalid {label}")
    return value


@contextmanager
def _open_url(url: str, *, opener: UrlOpener | None, timeout: float) -> Iterator[BinaryIO]:
    response: Any = None
    try:
        response = opener(url) if opener is not None else urllib_request.urlopen(url, timeout=timeout)
        if isinstance(response, (bytes, bytearray)):
            response = io.BytesIO(response)
        if not callable(getattr(response, "read", None)):
            raise TypeError("URL opener did not return a binary stream")
        yield response
    except UpdateError:
        raise
    except Exception as exc:
        raise UpdateError(
            "could not download update data",
            code="download_failed",
            details={"url": _safe_url(url)},
        ) from exc
    finally:
        close = getattr(response, "close", None)
        if callable(close):
            try:
                close()
            except Exception:
                pass


def _fetch_manifest(url: str, *, opener: UrlOpener | None, timeout: float) -> _Manifest:
    with _open_url(url, opener=opener, timeout=timeout) as response:
        raw = response.read(_MAX_MANIFEST_BYTES + 1)
    if not isinstance(raw, bytes):
        raise UpdateError(
            "release manifest response was not bytes",
            code="invalid_manifest",
            details={"manifest_url": _safe_url(url)},
        )
    if len(raw) > _MAX_MANIFEST_BYTES:
        raise UpdateError(
            "release manifest is too large",
            code="invalid_manifest",
            details={"manifest_url": _safe_url(url)},
        )
    try:
        manifest = json.loads(raw.decode("utf-8"))
        if not isinstance(manifest, dict):
            raise ValueError("root must be an object")
        schema = manifest.get("schema_version")
        if schema != 1 or isinstance(schema, bool):
            raise ValueError("unsupported schema_version")
        version = _required_version(manifest.get("version"), "release manifest version")
        wheel = manifest.get("wheel")
        if not isinstance(wheel, dict):
            raise ValueError("wheel must be an object")
        wheel_url = _required_url(wheel.get("url"), "release manifest wheel URL")
        wheel_sha256_value = wheel.get("sha256")
        if not isinstance(wheel_sha256_value, str) or _SHA256_RE.fullmatch(wheel_sha256_value) is None:
            raise ValueError("invalid release manifest wheel SHA-256")
        wheel_sha256 = wheel_sha256_value.lower()
        wheel_name = os.path.basename(urlsplit(wheel_url).path)
        if not wheel_name.endswith(".whl") or _WHEEL_NAME_RE.fullmatch(wheel_name) is None:
            raise ValueError("invalid release manifest wheel filename")
    except (UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise UpdateError(
            f"release manifest validation failed: {exc}",
            code="invalid_manifest",
            details={"manifest_url": _safe_url(url)},
        ) from exc
    return _Manifest(
        version=version,
        version_key=_version_key(version),
        wheel_url=wheel_url,
        wheel_sha256=wheel_sha256,
        wheel_name=wheel_name,
    )


def _version_key(version: str) -> tuple[int, int, int]:
    major, minor, patch = version.split(".")
    return int(major), int(minor), int(patch)


def _check_payload(
    installation: _Installation,
    manifest: _Manifest,
    manifest_url: str,
) -> dict[str, Any]:
    update_available = manifest.version_key > _version_key(installation.version)
    return {
        "ok": True,
        "action": "check",
        "status": "update-available" if update_available else _no_update_status(installation, manifest),
        "update_available": update_available,
        "current_version": installation.version,
        "latest_version": manifest.version,
        "manifest_url": _safe_url(manifest_url),
        "wheel_url": _safe_url(manifest.wheel_url),
        "wheel_sha256": manifest.wheel_sha256,
        "install_root": str(installation.install_root),
        "venv": str(installation.venv),
        "executable": str(installation.executable),
    }


def _no_update_status(installation: _Installation, manifest: _Manifest) -> str:
    if manifest.version_key < _version_key(installation.version):
        return "current-newer"
    return "up-to-date"


def _download_wheel(
    manifest: _Manifest,
    destination: Path,
    *,
    opener: UrlOpener | None,
    timeout: float,
) -> None:
    digest = hashlib.sha256()
    try:
        with _open_url(manifest.wheel_url, opener=opener, timeout=timeout) as response:
            with destination.open("wb") as wheel_file:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    if not isinstance(chunk, bytes):
                        raise TypeError("wheel response was not bytes")
                    digest.update(chunk)
                    wheel_file.write(chunk)
    except UpdateError:
        raise
    except (OSError, TypeError) as exc:
        raise UpdateError(
            f"could not save the taplctl wheel: {exc}",
            code="download_failed",
        ) from exc
    actual = digest.hexdigest()
    if actual != manifest.wheel_sha256:
        raise UpdateError(
            "downloaded wheel SHA-256 does not match the release manifest",
            code="checksum_mismatch",
            details={"expected": manifest.wheel_sha256, "actual": actual},
        )


def _run(runner: CommandRunner, args: list[str], *, failure_code: str, failure_message: str) -> Any:
    try:
        result = runner(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise UpdateError(f"{failure_message}: {exc}", code=failure_code) from exc
    if getattr(result, "returncode", None) != 0:
        raise UpdateError(failure_message, code=failure_code)
    return result


def _build_candidate(
    candidate: Path,
    wheel_path: Path,
    version: str,
    *,
    python_path: Path,
    runner: CommandRunner,
) -> None:
    _run(
        runner,
        [str(python_path), "-m", "venv", str(candidate)],
        failure_code="venv_creation_failed",
        failure_message="could not create the update virtual environment",
    )
    candidate_python = candidate / "bin" / "python"
    candidate_command = candidate / "bin" / "taplctl"
    _run(
        runner,
        [
            str(candidate_python),
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "--upgrade",
            str(wheel_path),
        ],
        failure_code="wheel_install_failed",
        failure_message="pip could not install the taplctl update",
    )
    result = _run(
        runner,
        [str(candidate_command), "--version"],
        failure_code="candidate_validation_failed",
        failure_message="the updated taplctl executable failed validation",
    )
    if getattr(result, "stdout", "").strip() != f"taplctl {version}":
        raise UpdateError(
            "the updated taplctl executable reported an unexpected version",
            code="candidate_validation_failed",
            details={"expected_version": version},
        )


def _activation_metadata(
    installation: _Installation,
    candidate: Path,
    manifest: _Manifest,
    manifest_url: str,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "method": "curl-sh",
        "manifest_url": manifest_url,
        "version": manifest.version,
        "wheel_url": manifest.wheel_url,
        "wheel_sha256": manifest.wheel_sha256,
        "install_root": str(installation.install_root),
        "bin_dir": str(installation.bin_dir),
        "venv": str(candidate),
        "executable": str(installation.executable),
        "installed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }


def _temporary_path(parent: Path, prefix: str) -> Path:
    descriptor, name = tempfile.mkstemp(prefix=prefix, dir=parent)
    os.close(descriptor)
    path = Path(name)
    path.unlink()
    return path


def _activate_candidate(
    installation: _Installation,
    candidate: Path,
    manifest: _Manifest,
    manifest_url: str,
) -> None:
    old_link_target = os.readlink(installation.executable)
    link_tmp: Path | None = None
    metadata_tmp: Path | None = None
    link_activated = False
    rollback_succeeded = False
    try:
        link_tmp = _temporary_path(installation.bin_dir, ".taplctl.tmp.")
        link_tmp.symlink_to(candidate / "bin" / "taplctl")

        descriptor, metadata_name = tempfile.mkstemp(
            prefix=".install.json.",
            dir=installation.install_root,
        )
        metadata_tmp = Path(metadata_name)
        metadata_bytes = (
            json.dumps(
                _activation_metadata(installation, candidate, manifest, manifest_url),
                indent=2,
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8")
        with os.fdopen(descriptor, "wb") as metadata_file:
            metadata_file.write(metadata_bytes)
            metadata_file.flush()
            os.fsync(metadata_file.fileno())

        os.replace(link_tmp, installation.executable)
        link_tmp = None
        link_activated = True
        try:
            os.replace(metadata_tmp, installation.metadata_path)
            metadata_tmp = None
        except OSError as activation_error:
            rollback_tmp = _temporary_path(installation.bin_dir, ".taplctl.rollback.")
            try:
                rollback_tmp.symlink_to(old_link_target)
                if _resolved_link_target(installation.executable) != candidate / "bin" / "taplctl":
                    raise OSError("taplctl command link changed before rollback")
                os.replace(rollback_tmp, installation.executable)
                rollback_succeeded = True
                link_activated = False
            finally:
                if rollback_tmp.exists() or rollback_tmp.is_symlink():
                    rollback_tmp.unlink()
            raise UpdateError(
                "install metadata could not be activated; the previous command link was restored",
                code="metadata_activation_failed",
            ) from activation_error
    except UpdateError:
        raise
    except OSError as exc:
        raise UpdateError(
            f"could not activate the taplctl update: {exc}",
            code="activation_failed",
            details={
                "candidate_active": link_activated,
                "rollback_succeeded": rollback_succeeded,
            },
        ) from exc
    finally:
        for temporary in (link_tmp, metadata_tmp):
            if temporary is not None:
                try:
                    if temporary.exists() or temporary.is_symlink():
                        temporary.unlink()
                except OSError:
                    pass


def _remove_candidate(candidate: Path) -> None:
    try:
        shutil.rmtree(candidate)
    except OSError:
        # Preserve the primary update error.  This path is never active after a
        # successful rollback or a pre-activation failure.
        pass
