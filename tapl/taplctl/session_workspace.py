"""Resolve a Codex hook's selected workspace from its own session metadata."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from typing import Any


# Session metadata can include substantial base instructions. Bound this first
# record independently of the transcript's total size and never scan later rows.
MAX_SESSION_META_BYTES = 1024 * 1024


def resolve_hook_workspace(
    payload: dict[str, Any], *, client: str, fallback: Path,
) -> Path:
    """Return Codex's selected folder, or the already validated event cwd.

    Only the supplied transcript's first session_meta record is eligible. A
    missing or invalid record must not borrow another session or a parent repo.
    """
    if client != "codex":
        return fallback
    session_id = payload.get("session_id")
    transcript = payload.get("transcript_path")
    if not isinstance(session_id, str) or not session_id:
        return fallback
    if not isinstance(transcript, str) or not transcript:
        return fallback
    try:
        path = Path(transcript)
        if not path.is_absolute():
            return fallback
        metadata = _read_session_metadata(path)
        if metadata is None or not _matches_hook_session(
            metadata, session_id=session_id, agent_id=payload.get("agent_id"),
        ):
            return fallback
        cwd = metadata.get("cwd")
        if not isinstance(cwd, str) or not cwd or not Path(cwd).is_absolute():
            return fallback
        root = Path(cwd).resolve()
        return root if root.is_dir() else fallback
    except (OSError, ValueError, RuntimeError):
        # Metadata is an optional hint. Keep legacy hooks working if the file
        # disappears, access is denied, or a path cannot be resolved.
        return fallback


def _matches_hook_session(
    metadata: dict[str, Any], *, session_id: str, agent_id: Any,
) -> bool:
    if metadata.get("id") == session_id:
        return True
    # Codex owns a subagent hook with the parent session ID, while the
    # supplied transcript belongs to the child. Require both identities and
    # the explicit direct-parent link; never infer an ancestor or scan logs.
    if (
        not isinstance(agent_id, str) or not agent_id or agent_id == session_id
        or metadata.get("id") != agent_id
    ):
        return False
    source = metadata.get("source")
    subagent = source.get("subagent") if isinstance(source, dict) else None
    spawn = subagent.get("thread_spawn") if isinstance(subagent, dict) else None
    if not isinstance(spawn, dict) or spawn.get("parent_thread_id") != session_id:
        return False
    return "parent_thread_id" not in metadata or metadata["parent_thread_id"] == session_id


def _read_session_metadata(path: Path) -> dict[str, Any] | None:
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode):
        return None
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    descriptor = os.open(path, flags)
    with os.fdopen(descriptor, "rb") as stream:
        opened = os.fstat(stream.fileno())
        after = path.lstat()
        if (
            not stat.S_ISREG(opened.st_mode)
            or not stat.S_ISREG(after.st_mode)
            or (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino)
            or (after.st_dev, after.st_ino) != (opened.st_dev, opened.st_ino)
        ):
            return None
        # Parse only this bounded first line. Subsequent conversation records
        # are never inspected, logged, or retained by the workspace resolver.
        first_record = stream.readline(MAX_SESSION_META_BYTES + 1)
    if len(first_record) > MAX_SESSION_META_BYTES:
        return None
    try:
        record = json.loads(first_record)
    except (ValueError, RecursionError):
        return None
    if not isinstance(record, dict) or record.get("type") != "session_meta":
        return None
    metadata = record.get("payload")
    return metadata if isinstance(metadata, dict) else None
