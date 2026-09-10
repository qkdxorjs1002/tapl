import json
from threading import Thread
from urllib.request import Request, urlopen

import pytest

from taplctl import db, recall, viewer


@pytest.fixture
def memory_workspace(tmp_path):
    db.initialize_workspace(tmp_path)
    path = tmp_path / db.DEFAULT_DB_RELATIVE
    conn = db.connect(path)
    run = db.ensure_active_run(conn, request_summary="SQLite migration")
    db.update_active_run_summary(conn, result_summary="Verified original migration result.")
    run_id = run["id"]
    conn.execute("INSERT INTO items(run_id,stable_id,kind,title,body,created_at,updated_at) VALUES(?, 'FINDING-001', 'finding', 'Original evidence', 'Original body', '2026-01-01', '2026-01-01')", (run_id,))
    item_id = conn.execute("SELECT id FROM items").fetchone()[0]
    conn.commit()
    result = recall.finish_memories(conn, run_id=run_id, candidates=[
        {"slot": 1, "source_run_id": run_id, "cue": ["sqlite", "migration", "backup"], "note": "Inspect the original migration result."},
        {"slot": 2, "source_run_id": run_id, "source_item_id": item_id, "cue": ["evidence", "transaction", "atomic"], "note": "Inspect the original transaction evidence."},
    ])
    assert not result["errors"]
    ids = [capture["memory_id"] for capture in result["captures"]]
    conn.close()
    return tmp_path, path, ids


def test_memory_list_detail_and_both_original_kinds(memory_workspace):
    workspace, path, ids = memory_workspace
    app = viewer.ViewerApplication(default_workspace=workspace)
    assert app.handle_message({"command": "ready"})["capabilities"] == {"associativeMemory": True}
    listing = app.handle_message({"command": "memories"})
    assert listing["view"]["total"] == 2
    assert listing["view"]["limit"] == 50
    assert app.handle_message({"command": "memories", "offset": 1})["view"]["memories"][0]["id"] == ids[0]
    detail = app.handle_message({"command": "openMemory", "memoryId": ids[0]})["view"]
    assert detail["memory"]["last_reinforced_at"] is None
    run_source = app.handle_message({"command": "openMemorySource", "memoryId": ids[0]})["view"]
    assert run_source["type"] == "memorySource"
    assert run_source["run"]["result_summary"] == "Verified original migration result."
    item_source = app.handle_message({"command": "openMemorySource", "memoryId": ids[1]})["view"]
    assert item_source["type"] == "searchItem"
    assert item_source["detail"]["body"] == "Original body"
    # Explicit database mode uses the same read-only memory protocol.
    assert viewer.ViewerApplication(default_db=path).handle_message({"command": "memories"})["view"]["total"] == 2


def test_refresh_keeps_query_and_reloads_agent_changes(memory_workspace):
    workspace, path, ids = memory_workspace
    app = viewer.ViewerApplication(default_workspace=workspace)
    listed = app.handle_message({"command": "refresh", "viewType": "memories", "query": "sqlite", "offset": 0})["view"]
    assert listed["query"] == "sqlite" and listed["total"] == 1
    conn = db.connect(path)
    recall.update_memory(conn, ids[0], expected_revision=1, note="Updated by the instructed agent.")
    refreshed = app.handle_message({"command": "refresh", "viewType": "memory", "memoryId": ids[0]})["view"]
    assert refreshed["memory"]["note"] == "Updated by the instructed agent."
    recall.delete_memory(conn, ids[0], expected_revision=2)
    conn.close()
    for view_type in ("memory", "memorySource"):
        refreshed = app.handle_message({"command": "refresh", "viewType": view_type, "memoryId": ids[0]})["view"]
        assert refreshed == {"type": "memory", "memoryId": ids[0], "memory": None}


@pytest.mark.parametrize("payload", [
    {"command": "memories", "offset": True}, {"command": "memories", "offset": -1},
    {"command": "memories", "query": []}, {"command": "openMemory"},
])
def test_invalid_memory_reads_fail_cleanly(memory_workspace, payload):
    assert viewer.ViewerApplication(default_workspace=memory_workspace[0]).handle_message(payload)["type"] == "error"


def test_http_memory_protocol_cannot_mutate_or_reinforce(memory_workspace):
    workspace, path, ids = memory_workspace
    app = viewer.ViewerApplication(default_workspace=workspace)
    conn = db.connect(path)
    before = [tuple(row) for row in conn.execute("SELECT * FROM memories")]
    source_before = tuple(conn.execute("SELECT body,updated_at FROM items").fetchone())
    events_before = conn.execute("SELECT count(*) FROM events").fetchone()[0]
    server = viewer.ViewerHTTPServer(("127.0.0.1", 0), app)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        for command in ("memories", "openMemory", "openMemorySource", "updateMemory", "deleteMemory", "tapl_delete_memory"):
            request = Request(server.browser_origin + "/api/message", data=json.dumps({"command": command, "memoryId": ids[0], "expected_revision": 1, "note": "Overwrite"}).encode(), headers={"Content-Type": "application/json"})
            with urlopen(request) as response:
                payload = json.load(response)
            assert payload["type"] == ("error" if command in {"updateMemory", "deleteMemory", "tapl_delete_memory"} else "view:update")
        assert [tuple(row) for row in conn.execute("SELECT * FROM memories")] == before
        assert tuple(conn.execute("SELECT body,updated_at FROM items").fetchone()) == source_before
        assert conn.execute("SELECT count(*) FROM events").fetchone()[0] == events_before
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
        conn.close()
