import json
import os
from pathlib import Path
from unittest.mock import Mock

import pytest

from taplctl import auto_reindex, cli, config, updater


def test_config_schedules_after_changed_edits_only(tmp_path, monkeypatch, capsys):
    config_path = tmp_path / "settings.toml"
    database = tmp_path / "local.db"
    config_path.write_text('[search]\nmode = "word"\n', encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    observed = []

    def schedule(*, config_path, database, python):
        observed.append((Path.cwd(), config_path, database, python, config.load(config_path).search.mode))
        return {"status": "scheduled"}

    monkeypatch.setattr(auto_reindex, "schedule", schedule)
    arguments = ["--config", str(config_path), "--db", str(database), "config"]

    for edit in (["set", "search.mode", "semantic"], ["unset", "search.mode"]):
        assert cli.main([*arguments, *edit, "--json"]) == 0
        edited = json.loads(capsys.readouterr().out)
        assert edited["changed"] is True
        assert edited["reindex"] == {"status": "scheduled"}

        assert cli.main([*arguments, *edit, "--json"]) == 0
        unchanged = json.loads(capsys.readouterr().out)
        assert unchanged["changed"] is False
        assert "reindex" not in unchanged

    assert cli.main([*arguments, "get", "search.mode", "--json"]) == 0
    assert "reindex" not in json.loads(capsys.readouterr().out)
    assert cli.main([*arguments, "set", "search.mode", "invalid-mode", "--json"]) == 1
    assert "reindex" not in json.loads(capsys.readouterr().out)
    assert observed == [
        (tmp_path, config_path, database, None, "semantic"),
        (tmp_path, config_path, database, None, config.DEFAULT_SEARCH_MODE),
    ]


def test_failed_schedule_keeps_config_edit_successful(tmp_path, monkeypatch, capsys):
    config_path = tmp_path / "settings.toml"
    receipt = {"status": "failed", "error": "worker unavailable"}
    monkeypatch.setattr(auto_reindex, "schedule", Mock(return_value=receipt))

    assert cli.main(["--config", str(config_path), "config", "set", "search.mode", "semantic", "--agent"]) == 0
    output = capsys.readouterr().out
    assert "<ok>true</ok>" in output
    assert "<reindex>" in output and "<status>failed</status>" in output
    assert "<error>worker unavailable</error>" in output
    assert config.load(config_path).search.mode == "semantic"


@pytest.mark.parametrize(("launcher_name", "python_path"), [
    ("taplctl", "bin/python"),
    ("taplctl.cmd", "Scripts/python.exe"),
])
def test_update_schedules_with_activated_runtime(tmp_path, monkeypatch, capsys, launcher_name, python_path):
    venv = tmp_path / "versions" / "next"
    python = venv / python_path
    if os.name != "nt":
        base_python = tmp_path / "base-python"
        base_python.touch()
        python.parent.mkdir(parents=True)
        python.symlink_to(base_python)
    activated = {
        "ok": True, "status": "updated", "updated": True,
        "previous_version": "1.0.0", "current_version": "1.1.0",
        "venv": str(venv), "executable": str(tmp_path / "bin" / launcher_name),
    }
    update = Mock(return_value=activated)
    schedule = Mock(return_value={"status": "scheduled"})
    monkeypatch.setattr(updater, "update_installation", update)
    monkeypatch.setattr(auto_reindex, "schedule", schedule)
    config_path = tmp_path / "settings.toml"
    database = tmp_path / "local.db"

    assert cli.main(["--config", str(config_path), "--db", str(database), "update"]) == 0
    update.assert_called_once_with()
    schedule.assert_called_once_with(config_path=config_path, database=database, python=python)
    assert capsys.readouterr().out == (
        "Updated taplctl: 1.0.0 → 1.1.0.\nSemantic index check scheduled.\n"
    )


def test_update_checks_noop_and_errors_never_schedule(tmp_path, monkeypatch, capsys):
    release = {"ok": True, "status": "update-available", "venv": str(tmp_path / "current")}
    current = {**release, "status": "up-to-date", "updated": False}
    check = Mock(return_value=release)
    update = Mock(return_value=current)
    schedule = Mock()
    monkeypatch.setattr(updater, "check_for_update", check)
    monkeypatch.setattr(updater, "update_installation", update)
    monkeypatch.setattr(auto_reindex, "schedule", schedule)

    assert cli.main(["update", "--check", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == release
    check.assert_called_once_with()
    update.assert_not_called()
    assert cli.main(["update", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == current

    update.side_effect = updater.UpdateError(
        "activation failed", code="metadata_activation_failed", details={"candidate_active": True},
    )
    assert cli.main(["update", "--json"]) == 1
    error = json.loads(capsys.readouterr().out)
    assert error["error"]["code"] == "metadata_activation_failed"
    assert "reindex" not in error
    schedule.assert_not_called()
