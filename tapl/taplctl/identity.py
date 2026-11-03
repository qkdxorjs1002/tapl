"""Persistent TAPL installation identity, independent of settings and Codex."""

from __future__ import annotations

import os
from pathlib import Path
import tempfile
import uuid


def installation_id_path() -> Path:
    return Path.home() / ".tapl" / "installation_id"


def installation_id(*, create: bool = False) -> str | None:
    """Read an identity, or atomically publish a complete UUIDv4 on first use."""
    path = installation_id_path()
    if path.is_symlink() or path.parent.is_symlink():
        raise ValueError(f"Refusing symlink TAPL installation identity: {path}")
    try:
        value = path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        if not create:
            return None
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(prefix=".installation_id-", dir=path.parent)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(str(uuid.uuid4()) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            try:
                # A losing creator never replaces the winner or exposes a
                # partly written identity to another process.
                os.link(temporary, path)
            except FileExistsError:
                pass
        finally:
            Path(temporary).unlink(missing_ok=True)
        return installation_id()
    except UnicodeError as exc:
        raise ValueError(_invalid_identity_message(path)) from exc
    try:
        parsed = uuid.UUID(value)
    except ValueError as exc:
        raise ValueError(_invalid_identity_message(path)) from exc
    if parsed.version != 4 or str(parsed) != value:
        raise ValueError(_invalid_identity_message(path))
    return value


def _invalid_identity_message(path: Path) -> str:
    return (
        f"Invalid TAPL installation UUID in {path}. Restore the original canonical "
        "UUIDv4 from a backup or your local tapl-<UUID>.db filename; do not delete "
        "or regenerate it, because it identifies your local history."
    )
