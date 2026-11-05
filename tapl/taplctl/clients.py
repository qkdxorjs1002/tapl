"""Explicit host context shared by installers, hooks and MCP calls.

Codex keeps its existing owner identifiers. Claude owners occupy a reserved
namespace so identical native session IDs cannot share workflow state.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator

from .sessions import normalize_session_id

CLIENTS = ("codex", "claude-code")
CLAUDE_SESSION_PREFIX = "claude-code:"
_client: ContextVar[str | None] = ContextVar("tapl_client", default=None)


def resolve_client(value: str | None = None) -> str:
    selected = value if value is not None else (_client.get() or os.environ.get("TAPL_CLIENT", "codex"))
    if selected not in CLIENTS:
        raise ValueError(f"Unsupported TAPL client: {selected!r}; choose codex or claude-code")
    return selected


def current_client() -> str:
    return resolve_client()


@contextmanager
def client_scope(client: str) -> Iterator[None]:
    token = _client.set(resolve_client(client))
    try:
        yield
    finally:
        _client.reset(token)


def session_key(value: str | None, client: str | None = None) -> str:
    """Normalize a hook owner once; never select another session implicitly."""
    owner = normalize_session_id(value)
    selected = resolve_client(client)
    if selected == "codex" and owner.startswith(CLAUDE_SESSION_PREFIX):
        raise ValueError("session_id belongs to a different TAPL client; use this client's hook session_id")
    if not owner or selected == "codex":
        return owner
    if not owner.startswith(CLAUDE_SESSION_PREFIX):
        owner = CLAUDE_SESSION_PREFIX + owner
    return normalize_session_id(owner)


def validate_session_key(value: str | None, client: str | None = None) -> str:
    """Check an MCP argument already supplied from this host's hook context."""
    owner = normalize_session_id(value)
    if owner:
        is_claude = owner.startswith(CLAUDE_SESSION_PREFIX)
        if is_claude != (resolve_client(client) == "claude-code"):
            raise ValueError("session_id belongs to a different TAPL client; use this client's hook session_id")
    return owner
