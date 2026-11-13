"""Exposure tracking must never weaken the read-only source boundary."""
from contextlib import closing
import json
import sqlite3
from unittest import mock

import pytest

from taplctl import db, history, recall, run_references, viewer
from taplctl.application import WorkflowApplication


def seed(path, label):
    with closing(db.connect(path, session_id="owner")) as conn:
        run = db.ensure_active_run(conn, request_summary=label, work_type="answer", workflow_mode="fast")
        item = db.upsert_plan(conn, plan_id="PLAN-001", title=f"SQLite migration {label}",
                              status="Finalized", summary="PRIVATE-BODY", source="original-source")
        db.update_active_run_summary(conn, result_summary="Verified migration")
        result = recall.finish_memories(conn, run_id=run["id"], candidates=[{
            "slot": 1, "cue": ["sqlite migration", "transaction", "schema"],
            "note": f"PRIVATE-NOTE {label}", "source_run_id": run["id"],
        }])
        archive = db.archive_active_run(conn, slug=label, memory_review_enabled=False)
        return {"run_id": run["id"], "item_id": item["id"], "archive_id": archive["id"],
                "memory_id": result["captures"][0]["memory_id"]}


@pytest.fixture
def setup(tmp_path):
    (tmp_path / ".git").mkdir()
    local = db.default_db_path(tmp_path)
    peer = tmp_path / ".tapl/tapl-peer.db"
    first, second = seed(local, "local"), seed(peer, "foreign")
    (tmp_path / ".tapl/config.toml").write_text('[search]\nmode="bm25"\n[subagents]\nenabled=false\n')
    app = WorkflowApplication(tmp_path, session_id="owner")
    app._db_path = local
    with closing(db.connect(local, session_id="owner")) as conn:
        run = db.ensure_active_run(conn, request_summary="current", work_type="answer", workflow_mode="fast")
    return app, local, peer, first, second, run["id"]


def events(path):
    with closing(db.connect_readonly(path, session_id="owner")) as conn:
        return [dict(row) for row in conn.execute("SELECT * FROM events WHERE event_type=?", (run_references.EVENT_TYPE,))]


def refs(path, run_id):
    with closing(db.connect_readonly(path, session_id="owner")) as conn:
        return db.run_snapshot(conn, run_id)["references"]


def test_empty_workspace_reads_create_nothing(tmp_path):
    (tmp_path / ".git").mkdir()
    app = WorkflowApplication(tmp_path, session_id="owner")
    with mock.patch.object(db, "default_db_path", side_effect=AssertionError("creating path")):
        assert app.search_history("PRIVATE-QUERY")["results"] == []
        assert app.recall()["memories"] == []
    assert not (tmp_path / ".tapl").exists()


def test_non_owner_and_no_active_run_do_not_track(setup):
    app, local, peer, first, second, run_id = setup
    foreign_owner = WorkflowApplication(app.workspace_root, session_id="other")
    foreign_owner._db_path = local
    before = local.read_bytes()
    assert foreign_owner.get_item(second["item_id"], source_db=peer.name)["ok"]
    assert not events(local)
    assert local.read_bytes() == before
    with closing(db.connect(local, session_id="owner")) as conn:
        db.archive_active_run(conn, slug="current", memory_review_enabled=False)
    assert app.get_run(first["run_id"])["ok"]
    assert not events(local)


def test_source_identity_stage_promotion_and_private_data(setup):
    app, local, peer, first, second, run_id = setup
    before = peer.read_bytes()
    app.search_history("sqlite migration", limit=10)
    initial = refs(local, run_id)
    assert len(initial) == 2
    assert {ref["source_db"] for ref in initial} == {local.name, peer.name}
    assert all(ref["stage"] == "retrieved" for ref in initial)
    app.search_history("sqlite migration", limit=10)
    assert len(events(local)) == 1
    app.get_item(second["item_id"], source_db=peer.name)
    app.get_item(second["item_id"], source_db=peer.name)
    current = refs(local, run_id)
    assert len(current) == 2
    assert {ref["source_db"]: ref["stage"] for ref in current} == {local.name: "retrieved", peer.name: "opened"}
    assert len(events(local)) == 2
    assert peer.read_bytes() == before
    encoded = json.dumps(events(local))
    assert "PRIVATE-BODY" not in encoded and "PRIVATE-NOTE" not in encoded
    assert "sqlite migration" not in encoded
    with closing(db.connect_readonly(local, session_id="owner")) as conn:
        assert conn.execute("SELECT count(*) FROM events WHERE event_type='memory_reinforced'").fetchone()[0] == 0


def test_capture_rechecks_same_owned_run_after_read(setup):
    app, local, peer, _, second, run_id = setup
    original = history.HistoryReader.get_item
    def switch(reader, *args, **kwargs):
        result = original(reader, *args, **kwargs)
        with closing(db.connect(local, session_id="owner")) as conn:
            db.archive_active_run(conn, slug="switched", memory_review_enabled=False)
            db.ensure_active_run(conn, request_summary="new")
        return result
    with mock.patch.object(history.HistoryReader, "get_item", switch):
        assert app.get_item(second["item_id"], source_db=peer.name)["ok"]
    assert refs(local, run_id) == []
    assert not events(local)


def test_memory_detail_opens_actual_original_only_and_run_detail_has_no_children(setup):
    app, local, peer, first, second, run_id = setup
    app.recall(limit=50)
    assert {ref["kind"] for ref in refs(local, run_id)} == {"memory"}
    app.get_memory(second["memory_id"], source_db=peer.name)
    current = refs(local, run_id)
    assert len(current) == 3
    assert next(ref for ref in current if ref["kind"] == "memory" and ref["memory_id"] == second["memory_id"])["stage"] == "opened"
    assert [(ref["target_type"], ref["run_id"]) for ref in current if ref["kind"] == "history"] == [("run", second["run_id"])]
    app.get_run(second["run_id"], source_db=peer.name)
    app.get_archive(second["archive_id"], source_db=peer.name)
    assert len(refs(local, run_id)) == 3
    assert len(events(local)) == 2
    # Missing original rows cannot imply a successful original read.
    response = app._history().get_memory(first["memory_id"])
    response["memory"]["source_record"] = {"kind": "item", "item": None, "run": response["memory"]["source_record"]["run"]}
    assert len(run_references.from_result("get_memory", response)) == 1


def test_current_run_is_excluded_but_foreign_run_id_collision_is_retained(setup):
    app, local, peer, _, second, run_id = setup
    app.get_run(run_id)
    assert not events(local)
    # A foreign source with the same run id is a distinct target.
    result = app._history().get_run(second["run_id"], source_db=peer.name)
    result["run"]["id"] = run_id
    captured = run_references.capture(app)
    run_references.record(captured, "get_run", result)
    assert refs(local, run_id)[0]["source_db"] == peer.name


def test_item_backed_memory_opens_only_returned_source_item(setup):
    app, local, peer, _, second, run_id = setup
    with closing(db.connect(peer, session_id="owner")) as conn:
        conn.execute("UPDATE memories SET source_item_id=? WHERE memory_id=?", (second["item_id"], second["memory_id"]))
        conn.commit()
    before = peer.read_bytes()
    result = app.get_memory(second["memory_id"], source_db=peer.name)
    assert result["memory"]["source_record"]["item"]["id"] == second["item_id"]
    current = refs(local, run_id)
    assert {ref["target_type"] for ref in current} == {"memory", "item"}
    assert all(ref["stage"] == "opened" and ref["source_db"] == peer.name for ref in current)
    assert peer.read_bytes() == before


def test_library_results_are_retrieved_and_missing_memory_has_no_trace(setup):
    app, local, peer, first, second, run_id = setup
    assert app.get_memory("missing")["memory"] is None
    assert not events(local)
    app.list_records()
    assert len(refs(local, run_id)) == 2
    assert all(ref["stage"] == "retrieved" for ref in refs(local, run_id))
    with closing(db.connect(local, session_id="owner")) as conn:
        own_item = db.upsert_plan(conn, plan_id="PLAN-001", title="Current", status="Finalized")
    app.get_item(own_item["id"])
    assert len(refs(local, run_id)) == 2


def test_automatic_recall_tracks_only_memories_retained_after_final_budget(setup):
    app, local, peer, first, second, run_id = setup
    memories = app._history().recall(limit=50)["memories"]
    memories[0]["note"] = "X" * 2000
    with closing(db.connect(local, session_id="owner")) as conn:
        result = recall.emit_recall_once(conn, run_id=run_id, query="sqlite migration",
                                        recall_reader=lambda **kwargs: {"memories": memories, "query": "sqlite migration"})
        emitted = json.loads(conn.execute("SELECT payload_json FROM events WHERE run_id=? AND event_type='memory_recall_attempted'", (run_id,)).fetchone()[0])
    assert len(result["memories"]) == 1
    assert [ref["memory_id"] for ref in refs(local, run_id)] == [memory["id"] for memory in result["memories"]]
    assert [entry["memory_id"] for entry in emitted["memory_sources"]] == [memory["id"] for memory in result["memories"]]
    assert all(0 < len(ref["title"]) <= run_references.TITLE_LIMIT for ref in emitted["references"])
    assert "PRIVATE-BODY" not in json.dumps(emitted)


def test_viewer_and_history_reader_do_not_track_and_status_passes_through(setup):
    app, local, peer, first, second, run_id = setup
    app.get_item(second["item_id"], source_db=peer.name)
    before = {path: path.read_bytes() for path in (local, peer)}
    runner = viewer.NativeJsonRunner()
    snapshot = runner(local, ["run", "show", "--id", run_id])
    status = runner(local, ["status"])
    app._history().get_run(second["run_id"], source_db=peer.name)
    app._history().get_memory(second["memory_id"], source_db=peer.name)
    assert snapshot["references"] == status["references"] == app.get_status()["references"]
    assert snapshot["references"][0]["source_db"] == peer.name
    assert snapshot["reference_limits"]["max_references"] == 200
    assert {path: path.read_bytes() for path in (local, peer)} == before
    assert len(events(local)) == 1


def test_unavailable_telemetry_never_fails_successful_read(setup):
    app, local, peer, first, second, run_id = setup
    original = sqlite3.connect
    def unavailable(path, *args, **kwargs):
        if "mode=rw" in str(path):
            raise sqlite3.OperationalError("readonly telemetry")
        return original(path, *args, **kwargs)
    with mock.patch.object(sqlite3, "connect", unavailable):
        assert app.get_item(second["item_id"], source_db=peer.name)["ok"]
    assert not events(local)


def test_bounded_state_can_still_promote_existing_reference(setup):
    app, local, peer, _, second, run_id = setup
    ref = run_references.history_reference(app._history().get_item(second["item_id"], source_db=peer.name)["item"], "retrieved")
    full = [{**ref, "item_id": index} for index in range(1, run_references.MAX_REFERENCES + 1)]
    assert len(run_references.merge(full, [{**ref, "item_id": 999}])) == run_references.MAX_REFERENCES
    assert run_references.merge(full, [{**ref, "stage": "opened"}])[0]["stage"] == "opened"
    opened = run_references.merge(full, [{**ref, "item_id": 999, "stage": "opened"}])
    assert len(opened) == run_references.MAX_REFERENCES
    assert opened[-1]["item_id"] == 999 and opened[-1]["stage"] == "opened"
    assert all(entry["item_id"] != 1 for entry in opened)
    all_opened = [{**entry, "stage": "opened"} for entry in full]
    assert run_references.merge(all_opened, [{**ref, "item_id": 999}]) == all_opened
    assert run_references.merge(all_opened, [{**ref, "item_id": 999, "stage": "opened"}])[-1]["item_id"] == 999
    with closing(db.connect_readonly(local, session_id="owner")) as conn:
        statements = []
        conn.set_trace_callback(statements.append)
        assert run_references.read(conn, run_id) == []
    assert len([query for query in statements if "FROM events" in query]) == 2


@pytest.mark.parametrize("payload", [[], None, {"references": None}, {"references": [None, [], {}, {"kind": []}]}])
def test_malformed_telemetry_never_breaks_status_exact_run_or_successful_read(setup, payload):
    app, local, peer, _, second, run_id = setup
    with closing(db.connect(local, session_id="owner")) as conn:
        db.record_event(conn, run_id=run_id, event_type=run_references.EVENT_TYPE)
        conn.execute("UPDATE events SET payload_json=? WHERE event_type=?", (json.dumps(payload), run_references.EVENT_TYPE))
        conn.commit()
    assert app.get_status()["references"] == []
    assert app.get_run(run_id)["references"] == []
    assert app.get_item(second["item_id"], source_db=peer.name)["ok"]
    assert len(refs(local, run_id)) == 1


def test_mixed_invalid_entries_are_skipped_individually_and_extra_fields_removed(setup):
    app, local, peer, _, second, run_id = setup
    valid = run_references.history_reference(app._history().get_item(second["item_id"], source_db=peer.name)["item"], "retrieved")
    with closing(db.connect(local, session_id="owner")) as conn:
        db.record_event(conn, run_id=run_id, event_type=run_references.EVENT_TYPE, payload={
            "references": [None, {"kind": []}, {**valid, "body": "PRIVATE-BODY", "custom_fields": {"secret": True}}, []]})
    assert app.get_status()["references"] == [valid]
    assert app.get_run(run_id)["references"] == [valid]
    app.get_item(second["item_id"], source_db=peer.name)
    assert refs(local, run_id) == [{**valid, "stage": "opened"}]


def test_latest_full_state_does_not_resurrect_evicted_automatic_reference(setup):
    app, local, peer, _, second, run_id = setup
    memory = app._history().get_memory(second["memory_id"], source_db=peer.name)["memory"]
    automatic = run_references.memory_reference(memory, "retrieved")
    ref = run_references.history_reference(app._history().get_item(second["item_id"], source_db=peer.name)["item"], "opened")
    retained = [{**ref, "item_id": index} for index in range(1, run_references.MAX_REFERENCES + 1)]
    with closing(db.connect(local, session_id="owner")) as conn:
        db.record_event(conn, run_id=run_id, event_type="memory_recall_attempted", payload={"references": [automatic]})
        db.record_event(conn, run_id=run_id, event_type=run_references.EVENT_TYPE, payload={"references": retained})
    assert refs(local, run_id) == retained
    assert app.get_status()["references"] == retained
