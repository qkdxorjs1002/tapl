"""The viewer reads installation histories without acquiring a write identity."""

from contextlib import closing
from pathlib import Path
import sqlite3
from unittest import mock

import pytest

from taplctl import db, identity, recall, viewer
from taplctl.application import WorkflowApplication


@pytest.fixture
def sources(tmp_path):
    root = tmp_path / "workspace"
    db.initialize_workspace(root)
    app = WorkflowApplication(root, session_id="owner")
    app.summarize_run("Shared evidence")
    app.apply_plan("PLAN-001", title="Shared local evidence")
    local = db.local_db_path(root, create_identity=False)
    with closing(db.connect(local, session_id="owner")) as conn:
        run = db.active_run(conn)
        db.update_active_run_summary(conn, result_summary="Captured source evidence.")
        result = recall.finish_memories(conn, run_id=run["id"], candidates=[{
            "slot": 1, "source_run_id": run["id"],
            "cue": ["shared", "evidence", "source"], "note": "Shared local memory evidence.",
        }])
        assert not result["errors"], result
    archive = app.finish_archive("shared-history")["archive"]
    app.summarize_run("Shared active run")
    app.apply_plan("PLAN-002", title="Local active board")
    peer = local.with_name("tapl-11111111-2222-4333-8444-555555555555.db")
    with closing(sqlite3.connect(local)) as src, closing(sqlite3.connect(peer)) as dst:
        src.backup(dst)
        dst.execute("UPDATE items SET title=replace(title, 'local', 'peer')")
        dst.execute("UPDATE items SET title=replace(title, 'Local', 'Peer')")
        dst.execute("UPDATE memories SET note='Shared peer memory evidence.'")
        dst.commit()
    return root, local, peer, archive


def test_aggregate_sources_and_route_colliding_item_archive_memory_ids(sources):
    root, local, peer, archive = sources
    before = {path.name: path.read_bytes() for path in (local, peer)}
    app = viewer.ViewerApplication(default_workspace=root)
    ready = app.handle_message({"command": "ready"})["view"]
    assert {run["source_db"] for run in ready["status"]["active_runs"]} == {local.name, peer.name}
    assert {entry["source_db"] for entry in ready["archives"]} == {local.name, peer.name}
    search = app.handle_message({"command": "search", "query": "Shared"})["view"]["search"]
    assert {item["source_db"] for item in search["results"]} == {local.name, peer.name}
    peer_item = next(item for item in search["results"] if item["source_db"] == peer.name)
    detail = app.handle_message({"command": "openSearchResult", "itemId": peer_item["id"], "source_db": peer.name})["view"]
    assert "peer" in detail["detail"]["title"]
    assert detail["result"]["source_db"] == peer.name
    archived = app.handle_message({"command": "openArchive", "archiveId": archive["id"], "source_db": peer.name})["view"]
    assert archived["archive"]["source_db"] == peer.name
    assert "peer" in archived["detail"]["items"][0]["title"]
    memories = app.handle_message({"command": "memories"})["view"]
    assert memories["total"] == 2
    memory = next(entry for entry in memories["memories"] if entry["source_db"] == peer.name)
    opened = app.handle_message({"command": "openMemory", "memoryId": memory["id"], "source_db": peer.name})["view"]
    assert opened["memory"]["note"] == "Shared peer memory evidence."
    refreshed = app.handle_message({"command": "refresh", "viewType": "memory", "memoryId": memory["id"], "source_db": peer.name})["view"]
    assert refreshed["source_db"] == peer.name
    source = app.handle_message({"command": "openMemorySource", "memoryId": memory["id"], "source_db": peer.name})["view"]
    assert source["source_db"] == peer.name
    assert {path.name: path.read_bytes() for path in (local, peer)} == before


def test_peer_run_selection_and_local_only_discard(sources):
    root, local, peer, _ = sources
    app = viewer.ViewerApplication(default_workspace=root)
    chosen = app.handle_message({"command": "selectRun", "sessionId": "owner", "source_db": peer.name})["view"]["status"]
    assert chosen["active_run"]["source_db"] == peer.name
    assert chosen["active_run"]["writable"] is False
    assert chosen["plans"][0]["title"] == "Peer active board"
    run_id = chosen["active_run"]["id"]
    before = peer.read_bytes()
    rejected = app.handle_message({"command": "discardRun", "workspace": str(root), "sessionId": "owner",
        "targetSessionId": "owner", "source_db": peer.name, "runId": run_id, "confirmed": True,
        "confirmationRunId": run_id})
    assert rejected["discardResult"]["ok"] is False
    assert "local installation" in rejected["message"]
    assert peer.read_bytes() == before
    with closing(db.connect_readonly(local, session_id="owner")) as conn:
        assert db.active_run(conn)["id"] == run_id


def test_revisions_include_peer_changes_and_source_additions(sources):
    root, local, peer, _ = sources
    app = viewer.ViewerApplication(default_workspace=root)
    revision = lambda: app.handle_message({"command": "revision"})["revision"]
    before = revision()
    with closing(db.connect(peer)) as conn:
        db.set_meta(conn, "peer_probe", "changed")
        conn.commit()
    assert revision() != before
    changed = revision()
    peer.unlink()
    assert revision() != changed


def test_readonly_sources_without_identity_keep_bytes_and_legacy_filename(sources, monkeypatch, tmp_path):
    root, local, peer, _ = sources
    legacy = local.with_name("tapl.db")
    local.rename(legacy)
    home = tmp_path / "read-only-user"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    paths = [legacy, peer]
    before = {path.name: path.read_bytes() for path in paths}
    with mock.patch.object(db, "connect", side_effect=AssertionError("writable connection")), mock.patch.object(db, "migrate", side_effect=AssertionError("migration")):
        app = viewer.ViewerApplication(default_workspace=root)
        for command in ("ready", "revision", "debug", "memories"):
            assert app.handle_message({"command": command})["type"] != "error"
        assert app.handle_message({"command": "search", "query": "Shared"})["type"] != "error"
        status = app.handle_message({"command": "ready"})["view"]["status"]
        run = status["active_runs"][0]
        rejected = app.handle_message({"command": "discardRun", "workspace": str(root), "sessionId": "owner",
            "targetSessionId": "owner", "source_db": run["source_db"], "runId": run["id"], "confirmed": True,
            "confirmationRunId": run["id"]})
        assert rejected["discardResult"]["ok"] is False
    assert identity.installation_id(create=False) is None
    assert not home.exists()
    assert {path.name: path.read_bytes() for path in paths} == before
    assert legacy.exists() and not local.exists()


@pytest.mark.parametrize("source", ["../tapl.db", "/tmp/tapl.db", "unknown.db", "", 1])
def test_rejects_untrusted_source_names(sources, source):
    root, _, _, archive = sources
    app = viewer.ViewerApplication(default_workspace=root)
    assert app.handle_message({"command": "openArchive", "archiveId": archive["id"], "source_db": source})["type"] == "error"


def test_bad_peer_and_symlink_do_not_hide_healthy_history(sources, tmp_path):
    root, local, peer, _ = sources
    bad = local.with_name("tapl-aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee.db")
    bad.write_bytes(b"malformed sqlite database")
    symlink = local.with_name("tapl-99999999-8888-4777-8666-555555555555.db")
    symlink.symlink_to(peer)
    app = viewer.ViewerApplication(default_workspace=root)
    view = app.handle_message({"command": "ready"})["view"]
    assert {run["source_db"] for run in view["status"]["active_runs"]} == {local.name, peer.name}
    assert view["status"]["source_errors"][0]["source_db"] == bad.name
    assert app.handle_message({"command": "openSearchResult", "itemId": 1, "source_db": symlink.name})["type"] == "error"
    assert bad.read_bytes() == b"malformed sqlite database"
