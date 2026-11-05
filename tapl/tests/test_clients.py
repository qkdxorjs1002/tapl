from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context

import pytest

from taplctl import clients


def test_same_native_session_is_isolated_and_codex_is_compatible():
    assert clients.session_key("same", "codex") == "same"
    assert clients.session_key("same", "claude-code") == "claude-code:same"
    assert clients.session_key("claude-code:same", "claude-code") == "claude-code:same"
    with pytest.raises(ValueError, match="different TAPL client"):
        clients.validate_session_key("same", "claude-code")
    with pytest.raises(ValueError, match="different TAPL client"):
        clients.validate_session_key("claude-code:same", "codex")
    with pytest.raises(ValueError, match="different TAPL client"):
        clients.session_key("claude-code:same", "codex")


def test_context_restores_and_propagates_to_workers(monkeypatch):
    monkeypatch.delenv("TAPL_CLIENT", raising=False)
    assert clients.current_client() == "codex"
    with clients.client_scope("claude-code"):
        with ThreadPoolExecutor() as pool:
            assert pool.submit(copy_context().run, clients.current_client).result() == "claude-code"
        with clients.client_scope("codex"):
            assert clients.current_client() == "codex"
        assert clients.current_client() == "claude-code"
    assert clients.current_client() == "codex"


def test_invalid_context_and_namespaced_length_are_rejected():
    with pytest.raises(ValueError, match="Unsupported TAPL client"):
        clients.resolve_client("unknown")
    with pytest.raises(ValueError, match="256"):
        clients.session_key("x" * 250, "claude-code")
    assert clients.session_key(None, "claude-code") == ""
