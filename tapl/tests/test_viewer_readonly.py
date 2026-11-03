"""Viewer reads must not initialize, migrate, or take a database write lock."""

from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import threading
from urllib.request import Request, urlopen
from unittest import mock

import pytest

from taplctl import db, viewer
from taplctl.application import WorkflowApplication


def test_readonly_connection_preserves_owner_and_rejects_writes(tmp_path):
    path = tmp_path / "한글 #?% space.db"
    db.connect(path).close()
    with mock.patch.object(db, "migrate", side_effect=AssertionError("migration")):
        with closing(db.connect_readonly(path, session_id="reader")) as conn:
            assert db.connection_session_id(conn) == "reader"
            assert conn.in_transaction
            assert conn.execute("PRAGMA query_only").fetchone()[0] == 1
            assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
            with pytest.raises(sqlite3.OperationalError, match="readonly"):
                conn.execute("UPDATE meta SET value = 'changed'")
            # mode=ro remains the storage boundary even if query_only is reset.
            conn.execute("PRAGMA query_only = OFF")
            with pytest.raises(sqlite3.OperationalError, match="readonly"):
                conn.execute("UPDATE meta SET value = 'changed'")


def test_readonly_connection_does_not_create_missing_database_or_directory(tmp_path):
    path = tmp_path / "missing" / "tapl.db"
    with pytest.raises(sqlite3.OperationalError):
        db.connect_readonly(path)
    assert not path.parent.exists()


@pytest.mark.parametrize("version,expected", [
    (None, "no TAPL schema version"),
    (str(db.SCHEMA_VERSION - 1), "requires migration"),
    (str(db.SCHEMA_VERSION + 1), "Upgrade TAPL"),
    ("invalid", "not a valid integer"),
])
def test_viewer_schema_errors_leave_database_untouched(tmp_path, version, expected):
    path = tmp_path / "tapl.db"
    with closing(sqlite3.connect(path)) as conn:
        if version is not None:
            conn.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
            conn.execute("INSERT INTO meta VALUES ('schema_version', ?)", (version,))
            conn.commit()
    before = path.read_bytes()
    app = viewer.ViewerApplication(default_db=path)
    result = app.handle_message({"command": "ready"})
    assert result["type"] == "error"
    assert expected in result["message"]
    if version in (None, str(db.SCHEMA_VERSION - 1)):
        assert "taplctl --db <database-path> init" in result["message"]
    assert path.read_bytes() == before
    assert list(tmp_path.iterdir()) == [path]


def test_readonly_schema_failure_closes_connection(tmp_path):
    path = tmp_path / "empty.db"
    sqlite3.connect(path).close()
    opened = []
    original = sqlite3.connect

    def track(*args, **kwargs):
        conn = original(*args, **kwargs)
        opened.append(conn)
        return conn

    with mock.patch.object(sqlite3, "connect", side_effect=track):
        with pytest.raises(db.ReadOnlySchemaError):
            db.connect_readonly(path)
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        opened[0].execute("SELECT 1")


def test_all_native_reads_bypass_writable_connection(tmp_path):
    workflow = WorkflowApplication(tmp_path, session_id="owner")
    db.initialize_workspace(tmp_path)
    workflow.summarize_run("Read archived evidence")
    workflow.apply_plan("PLAN-001", title="Evidence")
    path = db.local_db_path(tmp_path, create_identity=False)
    plan = viewer.run_native_json(path, ["status", "--full"])["plans"][0]
    archive = workflow.finish_archive("readonly-evidence")["archive"]
    commands = [
        ["status", "--full", "--include-events"],
        ["archive", "list"], ["archive", "show", "--id", archive["id"]],
        ["item", "show", "--id", str(plan["id"])], ["search", "Evidence"],
        ["memory", "list"], ["memory", "show", "--id", "missing"],
    ]
    with mock.patch.object(db, "connect", side_effect=AssertionError("write connection")):
        with mock.patch.object(db, "migrate", side_effect=AssertionError("migration")):
            for args in commands:
                assert isinstance(viewer.run_native_json(path, args), dict)


def test_wal_reader_sees_commits_without_waiting_for_writer_or_dirty_reads(tmp_path):
    path = tmp_path / "tapl.db"
    with closing(db.connect(path)) as writer:
        db.set_meta(writer, "probe", "first")
        writer.commit()
        with closing(db.connect_readonly(path)) as reader:
            assert db.get_meta(reader)["probe"] == "first"
            db.set_meta(writer, "probe", "second")
            writer.commit()
            assert db.get_meta(reader)["probe"] == "first"
        writer.execute("BEGIN IMMEDIATE")
        db.set_meta(writer, "probe", "uncommitted")
        with closing(db.connect_readonly(path)) as reader:
            assert db.get_meta(reader)["probe"] == "second"
            # The previous Viewer connect() tried to obtain this write lock.
            assert viewer.run_native_json(path, ["status"])["schema"]["probe"] == "second"
        writer.rollback()


requires_permissions = pytest.mark.skipif(
    os.name != "posix" or not hasattr(os, "geteuid") or os.geteuid() == 0,
    reason="requires Unix permissions enforced for a non-root process",
)


@requires_permissions
@pytest.mark.parametrize("journal_mode", ["delete", "wal"])
def test_protected_directory_with_and_without_wal_sidecars(tmp_path, journal_mode):
    path = tmp_path / "tapl.db"
    writer = db.connect(path)
    writer.execute(f"PRAGMA journal_mode = {journal_mode}")
    if journal_mode == "wal":
        db.set_meta(writer, "probe", "committed in WAL")
        writer.commit()
    else:
        writer.close()
    files = list(tmp_path.iterdir())
    before = {p.name: p.read_bytes() for p in files if not p.name.endswith("-shm")}
    try:
        for p in files:
            p.chmod(0o444)
        tmp_path.chmod(0o555)
        with pytest.raises(sqlite3.OperationalError):
            db.connect(path)
        result = viewer.ViewerApplication(default_db=path).handle_message({"command": "ready"})
        assert result["type"] == "hydrate", result
        if journal_mode == "wal":
            assert result["view"]["status"]["schema"]["probe"] == "committed in WAL"
        assert {p.name for p in tmp_path.iterdir()} == {p.name for p in files}
        assert {p.name: p.read_bytes() for p in files if not p.name.endswith("-shm")} == before
    finally:
        tmp_path.chmod(0o755)
        for p in files:
            p.chmod(0o644)
        writer.close()


@requires_permissions
def test_missing_wal_sidecars_in_protected_directory_has_actionable_error(tmp_path):
    path = tmp_path / "tapl.db"
    db.connect(path).close()
    assert list(tmp_path.iterdir()) == [path]
    try:
        path.chmod(0o444)
        tmp_path.chmod(0o555)
        result = viewer.ViewerApplication(default_db=path).handle_message({"command": "ready"})
        assert result["type"] == "error"
        assert "-wal and -shm" in result["message"]
        assert "directory write access" in result["message"]
        assert list(tmp_path.iterdir()) == [path]
    finally:
        tmp_path.chmod(0o755)
        path.chmod(0o644)


@requires_permissions
def test_http_ready_reads_protected_workspace_without_home_database(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    db.initialize_workspace(workspace)
    path = db.local_db_path(workspace, create_identity=False)
    with closing(sqlite3.connect(path)) as conn:
        conn.execute("PRAGMA journal_mode = DELETE")
    monkeypatch.setenv("HOME", str(tmp_path / "no-home-db"))
    server = viewer.create_server(viewer.ViewerApplication(), port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        path.chmod(0o444)
        path.parent.chmod(0o555)
        with urlopen(server.browser_origin) as response:
            assert response.status == 200
        for command, expected in [("revision", "revision"), ("ready", "hydrate")]:
            request = Request(
                server.browser_origin + "/api/message",
                data=json.dumps({"command": command, "workspace": str(workspace)}).encode(),
                headers={"Content-Type": "application/json"},
            )
            with urlopen(request) as response:
                result = json.load(response)
                assert response.status == 200
                assert result["type"] == expected, result
    finally:
        path.parent.chmod(0o755)
        path.chmod(0o644)
        server.shutdown()
        server.server_close()
        thread.join()
