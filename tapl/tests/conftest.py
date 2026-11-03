"""Keep every test and inherited subprocess away from real user state."""

import pytest


@pytest.fixture(autouse=True)
def isolated_user_and_working_directory(tmp_path_factory, monkeypatch):
    home = tmp_path_factory.mktemp("isolated-home")
    workspace = tmp_path_factory.mktemp("isolated-workspace")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("CODEX_HOME", str(home / ".codex"))
    monkeypatch.chdir(workspace)
