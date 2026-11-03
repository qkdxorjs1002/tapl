from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import os
import io
from contextlib import redirect_stdout
from pathlib import Path
import sqlite3
import subprocess
import sys
import uuid

import pytest

from taplctl import cli, db, identity, install, uninstall


def test_identity_is_persistent_uuid4_and_independent_of_config():
    assert identity.installation_id() is None
    value = identity.installation_id(create=True)
    assert uuid.UUID(value).version == 4
    settings = identity.installation_id_path().with_name("config.toml")
    settings.write_text("[search]\nmax_results=5\n")
    settings.unlink()
    assert identity.installation_id(create=True) == value


def test_identity_concurrent_process_creation_has_one_complete_value():
    script = "from taplctl.identity import installation_id; print(installation_id(create=True))"
    env = {**os.environ, "PYTHONPATH": str(Path(db.__file__).parents[1])}
    with ThreadPoolExecutor(max_workers=12) as pool:
        values = list(pool.map(lambda _: subprocess.check_output(
            [sys.executable, "-c", script], env=env, text=True).strip(), range(24)))
    assert len(set(values)) == 1
    assert values[0] == identity.installation_id()
    assert not list(identity.installation_id_path().parent.glob(".installation_id-*"))


@pytest.mark.parametrize("value", ["", "broken", str(uuid.uuid1()), str(uuid.uuid4()).upper(), "../peer"])
def test_invalid_identity_is_never_replaced(value):
    path = identity.installation_id_path()
    path.parent.mkdir(parents=True)
    path.write_text(value)
    with pytest.raises(ValueError, match="Restore the original"):
        identity.installation_id(create=True)
    assert path.read_text() == value


def test_symlink_identity_is_not_followed(tmp_path):
    outside = tmp_path / "outside-id"
    outside.write_text(str(uuid.uuid4()))
    path = identity.installation_id_path()
    path.parent.mkdir(parents=True)
    path.symlink_to(outside)
    with pytest.raises(ValueError, match="Refusing symlink"):
        identity.installation_id(create=True)
    assert outside.read_text() == path.read_text()


def test_symlink_database_directory_is_not_followed(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "tapl-peer.db").touch()
    (root / ".tapl").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="Refusing symlink"):
        db.discover_db_paths(root)
    with pytest.raises(ValueError, match="Refusing symlink"):
        db.default_db_path(root)
    assert not identity.installation_id_path().exists()


def test_readonly_discovery_does_not_create_identity(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    assert db.local_db_path(root) is None
    assert db.discover_db_paths(root) == []
    assert db.find_workspace_root(root) is None
    assert not (root / ".tapl").exists()
    directory = root / ".tapl"
    directory.mkdir()
    for name in ("tapl.db", "tapl-alice.db", "tapl-bob.db", "other.db", "tapl-alice.db-wal"):
        (directory / name).touch()
    (directory / "tapl-link.db").symlink_to(directory / "tapl-alice.db")
    assert {path.name for path in db.discover_db_paths(root)} == {"tapl.db", "tapl-alice.db", "tapl-bob.db"}
    assert db.find_workspace_root(root) == root.resolve()
    assert not identity.installation_id_path().exists()


def legacy_database(root):
    path = root / db.DEFAULT_DB_RELATIVE
    connection = db.connect(path)
    connection.execute("INSERT INTO meta(key,value) VALUES('retained_test','retained')")
    connection.commit()
    connection.close()
    return path


def test_legacy_rename_preserves_data_and_peers(tmp_path):
    legacy = legacy_database(tmp_path)
    peer = legacy.with_name("tapl-alice.db")
    peer.write_bytes(b"untouched peer")
    result = db.initialize_workspace(tmp_path)
    target = Path(result["db"])
    assert target == db.local_db_path(tmp_path)
    assert not legacy.exists()
    with sqlite3.connect(target) as conn:
        assert conn.execute("SELECT value FROM meta WHERE key='retained_test'").fetchone()[0] == "retained"
    assert peer.read_bytes() == b"untouched peer"
    assert db.default_db_path(tmp_path) == target


def test_legacy_migration_keeps_uncheckpointed_wal(tmp_path):
    legacy = legacy_database(tmp_path)
    code = """import os, sqlite3, sys
conn = sqlite3.connect(sys.argv[1])
conn.execute('PRAGMA journal_mode=WAL')
conn.execute('PRAGMA wal_autocheckpoint=0')
conn.execute("INSERT INTO meta(key,value) VALUES('wal_only','committed')")
conn.commit()
os._exit(0)
"""
    subprocess.run([sys.executable, "-c", code, str(legacy)], check=True)
    assert Path(str(legacy) + "-wal").stat().st_size > 0
    target = db.default_db_path(tmp_path)
    with sqlite3.connect(target) as conn:
        assert conn.execute("SELECT value FROM meta WHERE key='wal_only'").fetchone()[0] == "committed"
    assert not legacy.exists()
    assert not Path(str(legacy) + "-wal").exists()


def test_legacy_target_collision_preserves_both(tmp_path):
    legacy = legacy_database(tmp_path)
    target = db.local_db_path(tmp_path, create_identity=True)
    target.write_bytes(b"existing local database")
    before = legacy.read_bytes()
    with pytest.raises(FileExistsError, match="Preserve both"):
        db.default_db_path(tmp_path)
    assert target.read_bytes() == b"existing local database"
    assert legacy.read_bytes() == before


def test_legacy_target_sidecar_collision_is_preserved(tmp_path):
    legacy = legacy_database(tmp_path)
    target = db.local_db_path(tmp_path, create_identity=True)
    sidecar = Path(str(target) + "-wal")
    sidecar.write_bytes(b"prior WAL")
    with pytest.raises(FileExistsError):
        db.default_db_path(tmp_path)
    assert legacy.exists()
    assert not target.exists()
    assert sidecar.read_bytes() == b"prior WAL"


def test_busy_legacy_keeps_original_and_does_not_publish(tmp_path):
    legacy = legacy_database(tmp_path)
    writer = sqlite3.connect(legacy)
    try:
        writer.execute("BEGIN IMMEDIATE")
        writer.execute("INSERT INTO meta(key,value) VALUES('pending','writer')")
        with pytest.raises(sqlite3.OperationalError, match="Stop old TAPL"):
            db.default_db_path(tmp_path)
        assert legacy.is_file()
        assert not db.local_db_path(tmp_path).exists()
        writer.commit()
    finally:
        writer.close()
    target = db.default_db_path(tmp_path)
    with sqlite3.connect(target) as conn:
        assert conn.execute("SELECT value FROM meta WHERE key='pending'").fetchone()[0] == "writer"


def test_invalid_legacy_is_retained(tmp_path):
    legacy = tmp_path / db.DEFAULT_DB_RELATIVE
    legacy.parent.mkdir()
    legacy.write_bytes(b"not a SQLite database")
    with pytest.raises(sqlite3.DatabaseError):
        db.default_db_path(tmp_path)
    assert legacy.read_bytes() == b"not a SQLite database"
    assert not db.local_db_path(tmp_path).exists()


def test_failed_publication_retains_legacy(tmp_path, monkeypatch):
    legacy = legacy_database(tmp_path)
    identity.installation_id(create=True)
    def fail_link(*args):
        raise OSError("publication failed")
    monkeypatch.setattr(db.os, "link", fail_link)
    with pytest.raises(OSError, match="publication failed"):
        db.default_db_path(tmp_path)
    assert legacy.exists()
    assert not db.local_db_path(tmp_path).exists()
    with sqlite3.connect(legacy) as conn:
        assert conn.execute("SELECT value FROM meta WHERE key='retained_test'").fetchone()[0] == "retained"


@pytest.mark.parametrize("scope", ["repo", "user"])
def test_purge_preserves_identity_and_peer_history(tmp_path, scope):
    value = identity.installation_id(create=True)
    root = Path.home() if scope == "user" else tmp_path / "repo"
    root.mkdir(exist_ok=True)
    own = db.local_db_path(root)
    own.parent.mkdir(exist_ok=True)
    peer = own.with_name("tapl-peer.db")
    legacy = own.with_name("tapl.db")
    for path in (own, peer, legacy):
        for suffix in ("", "-wal", "-shm", "-journal"):
            Path(str(path) + suffix).write_bytes(b"data")
    (own.parent / "config.toml").write_text("[search]\nmax_results=5\n")
    if scope == "user":
        uninstall.uninstall_user(purge_config=True, purge_db=True)
    else:
        uninstall.uninstall_repo(repo=root, purge_config=True, purge_db=True)
    for suffix in ("", "-wal", "-shm", "-journal"):
        assert not Path(str(own) + suffix).exists()
        assert not Path(str(legacy) + suffix).exists()
        assert Path(str(peer) + suffix).read_bytes() == b"data"
    assert identity.installation_id() == value
    assert db.default_db_path(root) == own


def test_install_dry_run_does_not_create_identity(tmp_path):
    install.install_repo(repo=tmp_path, dry_run=True)
    assert not identity.installation_id_path().exists()
    assert not (tmp_path / ".tapl").exists()


def test_explicit_cli_database_does_not_create_identity(tmp_path):
    custom = tmp_path / "selected.db"
    with redirect_stdout(io.StringIO()):
        assert cli.main(["--db", str(custom), "init", "--json"]) == 0
    assert custom.is_file()
    assert not identity.installation_id_path().exists()


def test_idle_wal_connection_prevents_legacy_rename(tmp_path):
    legacy = legacy_database(tmp_path)
    reader = sqlite3.connect(legacy)
    try:
        reader.execute("SELECT * FROM meta").fetchall()
        with pytest.raises(sqlite3.OperationalError, match="Stop old TAPL"):
            db.default_db_path(tmp_path)
        assert legacy.exists()
        assert not db.local_db_path(tmp_path).exists()
    finally:
        reader.close()
    assert db.default_db_path(tmp_path).exists()
