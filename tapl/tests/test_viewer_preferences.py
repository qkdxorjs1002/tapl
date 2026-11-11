from __future__ import annotations

import json
from pathlib import Path
import tomllib
from unittest import mock

import pytest

from taplctl import cli, config, db, install, settings, viewer


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: home)
    root = tmp_path / "workspace"
    db.initialize_workspace(root)
    return root


def write_preferences(path: Path, *, language: str = "auto", layout: str = "auto", mcp_path: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("[viewer]\n" + "\n".join(
        f"{key} = {json.dumps(value)}" for key, value in {
            "language": language, "layout": layout, "mcp_path": mcp_path,
        }.items()
    ) + "\n")


def test_explicit_database_keeps_its_workspace_configuration(workspace: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    write_preferences(workspace / ".tapl/config.toml", language="en", layout="large")
    db_path = db.local_db_path(workspace, create_identity=False)
    assert db_path is not None
    app = viewer.ViewerApplication(default_db=db_path)
    message = app.handle_message({"command": "ready", "locale": "ko-KR"})
    assert message["workspace"] == str(workspace)
    assert (message["locale"], message["layout"]) == ("en", "large")
    result = app.handle_message({"command": "getSettings", "requestId": "explicit-db"})
    assert result["ok"] is True
    assert result["settings"]["path"] == str(workspace / ".tapl/config.toml")
    args = cli.build_parser().parse_args(["--db", str(db_path), "viewer"])
    with mock.patch.object(cli.viewer, "serve") as serve:
        cli.cmd_viewer(args)
    assert serve.call_args.kwargs["default_db"] == db_path.resolve()


def test_workspace_chooser_reads_user_display_preferences(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "home"
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.chdir(tmp_path)
    write_preferences(home / ".tapl/config.toml", language="en", layout="small")
    message = viewer.ViewerApplication().handle_message({"command": "ready", "locale": "ko-KR"})
    assert message["view"]["type"] == "workspace"
    assert (message["locale"], message["layout"]) == ("en", "small")


@pytest.mark.parametrize("key,value", [
    ("viewer.language", "ko"), ("viewer.language", "en"), ("viewer.language", "auto"),
    ("viewer.layout", "small"), ("viewer.layout", "medium"), ("viewer.layout", "large"),
    ("viewer.layout", "auto"), ("viewer.mcp_path", "/Applications/TAPL Tools/tapl-mcp"),
    ("viewer.mcp_path", "C:\\Program Files\\TAPL\\tapl-mcp.exe"), ("viewer.mcp_path", ""),
])
def test_cli_preferences_roundtrip(workspace: Path, capsys: pytest.CaptureFixture[str], key: str, value: str) -> None:
    path = workspace / ".tapl/config.toml"
    parser = cli.build_parser()
    args = parser.parse_args(["--config", str(path), "config", "set", key, json.dumps(value), "--json"])
    assert cli.cmd_config_set(args) == 0
    assert json.loads(capsys.readouterr().out)["value"] == value
    args = parser.parse_args(["--config", str(path), "config", "get", key, "--json"])
    assert cli.cmd_config_get(args) == 0
    assert json.loads(capsys.readouterr().out)["value"] == value


@pytest.mark.parametrize("value", [None, True, 1, [], "bad\0path", "bad\npath", "bad\rpath", "bad\tpath", "bad\x7fpath", "bad\x85path"])
def test_mcp_path_rejects_wrong_types_and_controls(value: object) -> None:
    with pytest.raises(ValueError):
        config.from_mapping({"viewer": {"mcp_path": value}}, path="unused.toml")


def test_template_and_packaging_fallback_have_equal_parsed_defaults() -> None:
    template = Path(__file__).resolve().parents[1] / ".tapl/config.toml"
    parsed = tomllib.loads(template.read_text())
    with mock.patch.object(install, "template_text", return_value=None):
        fallback = tomllib.loads(install.default_config_text())
    assert fallback == parsed
    assert parsed["viewer"] == {"language": "auto", "layout": "auto", "mcp_path": "", "allowed_origins": []}


@pytest.mark.parametrize("language,request_locale,expected", [
    ("auto", "ko-KR", "ko"), ("auto", "en-US", "en"),
    ("ko", "en-US", "ko"), ("en", "ko-KR", "en"),
])
def test_hydrate_and_updates_use_config_preferences(workspace: Path, language: str, request_locale: str, expected: str) -> None:
    path = workspace / ".tapl/config.toml"
    executable = "/Applications/TAPL Tools/tapl-mcp"
    write_preferences(path, language=language, layout="medium", mcp_path=executable)
    app = viewer.ViewerApplication(default_workspace=workspace)
    for command in ("ready", "refresh"):
        result = app.handle_message({"command": command, "workspace": str(workspace),
                                     "locale": request_locale, "layout": "large"})
        assert result["type"] == ("hydrate" if command == "ready" else "view:update")
        assert result["locale"] == expected
        assert result["layout"] == "medium"
        assert result["preferences"] == {"language": language, "layout": "medium", "mcp_path": executable}


def test_settings_get_save_and_reset_return_immediate_display_metadata(workspace: Path) -> None:
    app = viewer.ViewerApplication(default_workspace=workspace)
    base = {"workspace": str(workspace), "requestId": "settings", "locale": "ko-KR",
            "sessionId": "not-a-selected-run", "source_db": "irrelevant.db", "runId": "irrelevant"}
    read = app.handle_message({**base, "command": "getSettings"})
    assert read["ok"] is True
    assert read["preferences"] == {"language": "auto", "layout": "auto", "mcp_path": ""}
    assert (read["locale"], read["layout"]) == ("ko", "auto")
    saved = app.handle_message({**base, "command": "saveSettings", "revision": read["settings"]["revision"],
                                "values": {"viewer.language": "en", "viewer.layout": "large", "viewer.mcp_path": "tapl-mcp"}})
    assert saved["ok"] is True
    assert saved["preferences"] == {"language": "en", "layout": "large", "mcp_path": "tapl-mcp"}
    assert (saved["locale"], saved["layout"]) == ("en", "large")
    reset = app.handle_message({**base, "command": "resetSettings", "confirmed": True,
                                "revision": saved["settings"]["revision"]})
    assert reset["ok"] is True and reset["settings"]["overrides"] == []
    assert reset["preferences"] == read["preferences"]
    assert (reset["locale"], reset["layout"]) == ("ko", "auto")


def test_selected_workspace_and_pinned_config_precedence(workspace: Path, tmp_path: Path) -> None:
    other = tmp_path / "other"
    db.initialize_workspace(other)
    write_preferences(workspace / ".tapl/config.toml", language="ko", layout="small")
    write_preferences(other / ".tapl/config.toml", language="en", layout="large")
    app = viewer.ViewerApplication(default_workspace=workspace)
    payload = {"command": "ready", "workspace": str(other), "locale": "ko"}
    assert app.handle_message(payload)["preferences"]["layout"] == "large"
    pinned = viewer.ViewerApplication(default_workspace=workspace, config_path=workspace / ".tapl/config.toml")
    result = pinned.handle_message(payload)
    assert (result["locale"], result["layout"]) == ("ko", "small")
    document = pinned.handle_message({**payload, "command": "getSettings", "requestId": "get"})
    assert document["settings"]["path"] == str(workspace / ".tapl/config.toml")
    assert document["preferences"] == result["preferences"]


def test_revision_tracks_config_content_creation_deletion_and_fallback_without_schema(workspace: Path) -> None:
    app = viewer.ViewerApplication(default_workspace=workspace)
    local = workspace / ".tapl/config.toml"
    home = Path.home() / ".tapl/config.toml"
    payload = {"command": "revision", "workspace": str(workspace), "source_db": "ignored.db"}

    def revision() -> str:
        with mock.patch.object(settings, "settings_fields", side_effect=AssertionError("no schema during polling")), \
                mock.patch.object(config, "from_mapping", side_effect=AssertionError("no config parsing during polling")):
            result = app.handle_message(payload)
        assert result["type"] == "revision"
        return result["revision"]

    revisions = [revision()]
    write_preferences(home, language="ko")
    revisions.append(revision())
    write_preferences(local, language="en")
    revisions.append(revision())
    local.write_text(local.read_text() + "# externally changed\n")
    revisions.append(revision())
    local.unlink()
    assert revision() == revisions[1]
    home.unlink()
    assert revision() == revisions[0]
    assert len(set(revisions)) == len(revisions)


def test_revision_with_pinned_config_ignores_workspace_config(workspace: Path, tmp_path: Path) -> None:
    pinned = tmp_path / "pinned.toml"
    app = viewer.ViewerApplication(default_workspace=workspace, config_path=pinned)
    payload = {"command": "revision", "workspace": str(workspace)}
    first = app.handle_message(payload)["revision"]
    write_preferences(workspace / ".tapl/config.toml", language="ko")
    assert app.handle_message(payload)["revision"] == first
    write_preferences(pinned, language="en")
    assert app.handle_message(payload)["revision"] != first
    pinned.unlink()
    assert app.handle_message(payload)["revision"] == first
