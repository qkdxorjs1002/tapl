"""Windows integration regressions; platform-independent contracts run everywhere."""
from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import sysconfig
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from taplctl import config, db, embeddings, install, searchd, uninstall, updater
from taplctl.command_runtime import windows_hook_command, windows_hook_tokens


def test_windows_hooks_roundtrip_literal_paths_and_preserve_unrelated_hooks(tmp_path):
    executable = r"C:\Users\O'Neil & 팀\TAPL env\Scripts\tapl-hook.exe"
    command = windows_hook_command(executable, "UserPromptSubmit", "enforce")
    assert windows_hook_tokens(command) == [executable, "--event", "UserPromptSubmit", "--mode", "enforce"]
    assert uninstall.is_tapl_hook_command(command)
    assert not uninstall.is_tapl_hook_command("echo " + command)
    path = tmp_path / "hooks.json"
    unrelated = {"type": "command", "command": "echo unrelated-user-hook"}
    path.write_text(json.dumps({"hooks": {"Stop": [{"hooks": [unrelated, {"type": "command", "command": command}]}]}}), encoding="utf-8")
    assert install.installed_hook_mode(path, "observe") == "enforce"
    remaining = json.loads(uninstall._remove_hooks(path.read_text(encoding="utf-8"), path))
    assert remaining == {"hooks": {"Stop": [{"hooks": [unrelated]}]}}


@pytest.mark.parametrize("suffix", ["; echo unsafe", "\nWrite-Output unsafe", " | Write-Output"])
def test_ownership_never_decodes_arbitrary_powershell(suffix):
    command = windows_hook_command(r"C:\TAPL\tapl-hook.exe", "Stop", "observe")
    prefix, encoded = command.rsplit(" ", 1)
    script = base64.b64decode(encoded).decode("utf-16-le")
    tampered = prefix + " " + base64.b64encode((script + suffix).encode("utf-16-le")).decode("ascii")
    assert windows_hook_tokens(tampered) is None
    assert not uninstall.is_tapl_hook_command(tampered)


def test_windows_resolves_native_executable_before_public_cmd(tmp_path, monkeypatch):
    scripts = tmp_path / "venv with spaces" / "Scripts"
    scripts.mkdir(parents=True)
    native = scripts / "taplctl.exe"
    native.touch()
    monkeypatch.setattr(install, "WINDOWS", True)
    monkeypatch.setattr(sys, "executable", str(scripts / "python.exe"))
    monkeypatch.setattr(install.shutil, "which", lambda name: str(tmp_path / "taplctl.cmd"))
    command = install.resolved_taplctl_command(None)
    assert command == str(native)
    assert install.sibling_tapl_command(command, "tapl-mcp") == str(scripts / "tapl-mcp.exe")
    assert install.resolved_taplctl_command("custom") == "custom"


def test_windows_daemon_is_explicitly_unavailable_and_uses_local_fallback(tmp_path, monkeypatch):
    monkeypatch.setattr(searchd, "WINDOWS", True)
    monkeypatch.setattr(searchd.subprocess, "Popen", mock.Mock(side_effect=AssertionError("must not launch unsupported daemon")))
    settings = config.SearchConfig()
    socket = tmp_path / "searchd.sock"
    socket.write_text("preserve unrelated file", encoding="utf-8")
    result = searchd.start(settings, socket_path=socket, wait=False)
    assert result["ok"] is False and result["running"] is False and result["started"] is False
    assert "Windows" in result["error"] and "local" in result["error"]
    assert not searchd.status(settings, socket_path=socket)["running"]
    with pytest.raises(searchd.SearchdUnavailable, match="Windows"):
        searchd.run_server(settings, socket_path=socket)
    monkeypatch.setattr(embeddings, "local_query_embedding_blob", lambda query: b"portable-local-result")
    assert embeddings.query_embedding_blob("query", settings) == b"portable-local-result"
    assert socket.read_text(encoding="utf-8") == "preserve unrelated file"


def test_connection_is_closed_when_wal_setup_fails(tmp_path, monkeypatch):
    real_connect = sqlite3.connect

    class LockedConnection(db.WorkflowConnection):
        was_closed = False

        def execute(self, sql, *args):
            if sql == "PRAGMA journal_mode = WAL":
                raise sqlite3.OperationalError("database is locked")
            return super().execute(sql, *args)

        def close(self):
            self.was_closed = True
            return super().close()

    opened = []

    def connect(*args, **kwargs):
        kwargs["factory"] = LockedConnection
        connection = real_connect(*args, **kwargs)
        opened.append(connection)
        return connection

    monkeypatch.setattr(db.sqlite3, "connect", connect)
    path = tmp_path / "locked.db"
    with pytest.raises(sqlite3.OperationalError, match="locked"):
        db.connect(path)
    assert opened[0].was_closed
    path.unlink()  # Windows refuses removal when a leaked handle is still open.


def test_updated_windows_venv_inventory_matches_installer_path_format(tmp_path):
    source = tmp_path / "Lib" / "site-packages" / "taplctl" / "cli.py"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"# wheel source\n")
    updater._write_windows_venv_inventory(tmp_path)
    inventory = json.loads((tmp_path / ".tapl-managed-venv.json").read_text(encoding="utf-8"))
    assert inventory["schema_version"] == 1
    assert inventory["files"] == {r"Lib\site-packages\taplctl\cli.py": hashlib.sha256(source.read_bytes()).hexdigest()}
    assert set(inventory["directories"]) == {"Lib", r"Lib\site-packages", r"Lib\site-packages\taplctl"}


@pytest.mark.skipif(os.name != "nt", reason="requires native Windows shells")
def test_encoded_hook_preserves_utf8_stdin_stdout_and_exit_code(tmp_path):
    # Use the real installed hook entry point, not a mocked subprocess. A clean
    # workspace must deny a durable edit in enforce mode through both shells.
    executable = Path(sysconfig.get_path("scripts")) / "tapl-hook.exe"
    assert executable.is_file()
    repo = tmp_path / "native repo 한글 & O'Neil"
    home = tmp_path / "isolated home"
    repo.mkdir()
    home.mkdir()
    env = {key: value for key, value in os.environ.items() if not key.startswith(("TAPL_", "CODEX_"))}
    env.update(HOME=str(home), USERPROFILE=str(home))
    command = windows_hook_command(str(executable), "PreToolUse", "enforce")
    payload = json.dumps({"cwd": str(repo), "tool_name": "Write", "prompt": "유니코드"}, ensure_ascii=False)
    shells = [f'"{env.get("COMSPEC", "cmd.exe")}" /d /s /c "{command}"',
              ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command]]
    for shell in shells:
        result = subprocess.run(shell, env=env, cwd=repo, input=payload,
                                encoding="utf-8", capture_output=True, timeout=60)
        assert result.returncode == 2, (result.stdout, result.stderr)
        assert result.stderr
