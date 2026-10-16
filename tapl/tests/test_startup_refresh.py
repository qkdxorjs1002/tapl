"""Startup refresh boundaries for the MCP and Codex hook entry points."""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path
from unittest import mock

import pytest

from taplctl import config, db, hook_cli, mcp_server


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    db.initialize_workspace(repo)
    return repo


def _hook_input(monkeypatch: pytest.MonkeyPatch, repo: Path) -> None:
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"cwd": str(repo)})))


def test_mcp_refresh_precedes_application_creation_and_uses_explicit_workspace(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    events: list[str] = []
    original_application = mcp_server.WorkflowApplication

    def refresh(*, start: Path) -> list[dict[str, object]]:
        assert start == repo
        events.append("refresh")
        (repo / ".tapl/config.toml").write_text("[search]\nmax_results = 9\n", encoding="utf-8")
        return []

    def construct(root: Path) -> object:
        assert root == repo
        assert config.load(start=root).search.max_results == 9
        events.append("application")
        return original_application(root)

    with mock.patch.object(mcp_server.tapl_install, "auto_install_if_needed", side_effect=refresh), \
            mock.patch.object(mcp_server, "WorkflowApplication", side_effect=construct):
        mcp_server.create_server(workspace_root=repo, refresh_install=True)

    assert events == ["refresh", "application"]


def test_mcp_server_factory_does_not_refresh_by_default(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    with mock.patch.object(mcp_server.tapl_install, "auto_install_if_needed") as refresh:
        mcp_server.create_server(workspace_root=repo)
    refresh.assert_not_called()


def test_mcp_main_refreshes_and_startup_error_stays_on_stderr(capsys: pytest.CaptureFixture[str]) -> None:
    server = mock.Mock()
    with mock.patch.object(mcp_server, "create_server", return_value=server) as create:
        mcp_server.main()
    create.assert_called_once_with(refresh_install=True)
    server.run.assert_called_once_with()
    assert capsys.readouterr().out == ""

    with mock.patch.object(mcp_server, "create_server", side_effect=RuntimeError("refresh failed")):
        with pytest.raises(SystemExit) as stopped:
            mcp_server.main()
    assert stopped.value.code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "tapl-mcp startup failed: refresh failed" in captured.err


@pytest.mark.parametrize("event", ["SessionStart", "UserPromptSubmit"])
def test_hook_refreshes_after_workspace_init_before_config_load(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], event: str,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _hook_input(monkeypatch, repo)
    events: list[str] = []
    original_load = hook_cli.tapl_config.load

    def refresh(*, start: Path, mode: str) -> list[dict[str, object]]:
        assert start == repo
        assert mode == "enforce"
        assert (repo / db.DEFAULT_DB_RELATIVE).is_file()
        events.append("refresh")
        (repo / ".tapl/config.toml").write_text("[search]\nmax_results = 9\n", encoding="utf-8")
        return []

    def load(*args: object, **kwargs: object) -> config.TaplConfig:
        events.append("load")
        settings = original_load(*args, **kwargs)
        assert settings.search.max_results == 9
        return settings

    with mock.patch.object(hook_cli.tapl_install, "auto_install_if_needed", side_effect=refresh), \
            mock.patch.object(hook_cli.tapl_config, "load", side_effect=load):
        assert hook_cli.main(["--event", event, "--mode", "enforce", "--json"]) == 0
    assert events == ["refresh", "load"]
    assert json.loads(capsys.readouterr().out)["ok"] is True


def test_hook_unmarked_first_use_does_not_enroll_repo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    repo = tmp_path / "repo"
    repo.mkdir()
    _hook_input(monkeypatch, repo)
    with mock.patch.object(Path, "home", return_value=home):
        assert hook_cli.main(["--event", "SessionStart", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["ok"] is True
    assert (repo / db.DEFAULT_DB_RELATIVE).is_file()
    assert not (repo / ".codex").exists()
    assert not (repo / ".tapl/version").exists()
    assert not (home / ".codex").exists()


@pytest.mark.parametrize("explicit", ["db", "config"])
def test_hook_explicit_path_skips_refresh(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], explicit: str,
) -> None:
    repo = _repo(tmp_path)
    _hook_input(monkeypatch, repo)
    value = repo / db.DEFAULT_DB_RELATIVE if explicit == "db" else repo / ".tapl/config.toml"
    if explicit == "config":
        value.write_text("[search]\nmax_results = 9\n", encoding="utf-8")
    with mock.patch.object(hook_cli.tapl_install, "auto_install_if_needed") as refresh:
        assert hook_cli.main(["--event", "SessionStart", f"--{explicit}", str(value), "--json"]) == 0
    refresh.assert_not_called()
    assert json.loads(capsys.readouterr().out)["ok"] is True


def test_hook_refresh_failure_reports_error_before_config_load(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _hook_input(monkeypatch, repo)
    with mock.patch.object(hook_cli.tapl_install, "auto_install_if_needed", side_effect=RuntimeError("refresh failed")), \
            mock.patch.object(hook_cli.tapl_config, "load") as load:
        assert hook_cli.main(["--event", "UserPromptSubmit", "--json"]) == 1
    load.assert_not_called()
    assert json.loads(capsys.readouterr().out) == {"ok": False, "error": "refresh failed"}
