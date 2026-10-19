"""Per-call Codex session scope, propagated safely into worker threads."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator


_session_id: ContextVar[str] = ContextVar("tapl_session_id", default="")


def normalize_session_id(value: str | None) -> str:
    """An empty owner is the isolated legacy namespace, never another session."""
    if value is None:
        return ""
    if not isinstance(value, str) or len(value) > 256:
        raise ValueError("session_id must be a string of at most 256 characters")
    if value != value.strip() or any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ValueError("session_id must not contain surrounding whitespace or control characters")
    return value


def current_session_id() -> str:
    return _session_id.get()


@contextmanager
def session_scope(session_id: str | None) -> Iterator[None]:
    token = _session_id.set(normalize_session_id(session_id))
    try:
        yield
    finally:
        _session_id.reset(token)
