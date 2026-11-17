"""Exposure tracking must never weaken the read-only source boundary."""
from contextlib import closing
import json
import sqlite3
from unittest import mock

import pytest

from taplctl import db, history, recall, run_references, viewer
from taplctl.application import WorkflowApplication, WorkflowApplicationError


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
    memories[0]["note"] = "X" * (recall.AUTOMATIC_RECALL_MAX_BYTES + 1)
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
    assert len([query for query in statements if "FROM events" in query]) == 3


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


def claim(source, target, identity, usage="Applied the verified migration decision"):
    return {"kind": "memory" if target == "memory" else "history", "source_db": source,
            "target_type": target, f"{target}_id": identity, "usage": usage}


def next_run(local):
    with closing(db.connect(local, session_id="owner")) as conn:
        db.archive_active_run(conn, slug="previous-observer", memory_review_enabled=False)
        return db.ensure_active_run(conn, request_summary="reuse retained knowledge", work_type="answer", workflow_mode="fast")["id"]


def used_events(local):
    with closing(db.connect_readonly(local, session_id="owner")) as conn:
        return conn.execute("SELECT * FROM events WHERE event_type=?", (run_references.USED_EVENT_TYPE,)).fetchall()


def test_same_session_prior_run_memory_reuse_without_fetch_and_compact_idempotent_receipts(setup):
    app, local, peer, _, second, previous = setup
    app.get_memory(second["memory_id"], source_db=peer.name)
    app.get_item(second["item_id"], source_db=peer.name)  # unrelated opened child must not be copied
    current = next_run(local)
    before = peer.read_bytes()
    entry = claim(peer.name, "memory", second["memory_id"], "  Used the original migration constraints  ")
    with mock.patch.object(history.HistoryReader, "get_memory", side_effect=AssertionError("refetch")), \
         mock.patch.object(history.HistoryReader, "get_run", side_effect=AssertionError("refetch")):
        receipt = app.use_references(expected_run_id=current, references=[entry, entry])
        repeated = app.use_references(expected_run_id=current, references=[{**entry, "usage": "Different reason"}])
    assert receipt == {"ok": True, "run_id": current,
                       "outcomes": [{"index": 0, "status": "recorded"}, {"index": 1, "status": "unchanged"}],
                       "counts": {"recorded": 1, "unchanged": 1}}
    assert repeated["counts"] == {"recorded": 0, "unchanged": 1}
    assert len(used_events(local)) == 1
    projected = app.get_status()["references"]
    assert projected == app.get_run(current)["references"]
    assert len(projected) == 2 and {ref["target_type"] for ref in projected} == {"memory", "run"}
    assert all(ref["stage"] == "used" and ref["usage"] == entry["usage"].strip() for ref in projected)
    assert all(ref["stage"] == "opened" for ref in refs(local, previous))
    assert peer.read_bytes() == before


def test_used_promotes_existing_card_and_source_collisions_stay_distinct(setup):
    app, local, peer, first, second, run_id = setup
    assert first["item_id"] == second["item_id"]
    app.search_history("sqlite migration")
    app.get_item(first["item_id"], source_db=local.name)
    app.get_item(second["item_id"], source_db=peer.name)
    app.use_references(expected_run_id=run_id, references=[claim(local.name, "item", first["item_id"]), claim(peer.name, "item", second["item_id"])])
    app.search_history("sqlite migration")
    app.get_item(second["item_id"], source_db=peer.name)
    assert len(refs(local, run_id)) == 2
    assert {ref["source_db"] for ref in refs(local, run_id)} == {local.name, peer.name}
    assert all(ref["stage"] == "used" for ref in refs(local, run_id))


def test_batch_rejects_stale_or_unproven_claim_atomically(setup):
    app, local, peer, _, second, previous = setup
    app.get_item(second["item_id"], source_db=peer.name)
    current = next_run(local)
    valid = claim(peer.name, "item", second["item_id"])
    for expected, entries, error in ((previous, [valid], "stale_run"),
                                      (current, [valid, claim(peer.name, "run", "missing")], "invalid_proof")):
        with pytest.raises(WorkflowApplicationError, match=error):
            app.use_references(expected_run_id=expected, references=entries)
        assert not used_events(local)
        assert refs(local, current) == []


def test_manual_memory_hint_and_checked_original_can_be_reused_without_detail_fetch(setup):
    app, local, peer, _, second, old = setup
    hints = app.recall("sqlite migration", limit=50)["memories"]
    assert any(memory["id"] == second["memory_id"] and memory["note"] for memory in hints)
    app.get_run(second["run_id"], source_db=peer.name)
    current = next_run(local)
    with mock.patch.object(history.HistoryReader, "get_memory", side_effect=AssertionError("unnecessary detail fetch")):
        result = app.use_references(expected_run_id=current, references=[claim(peer.name, "memory", second["memory_id"])])
    assert result["counts"] == {"recorded": 1, "unchanged": 0}
    assert len(refs(local, current)) == 2 and all(ref["stage"] == "used" for ref in refs(local, current))


@pytest.mark.parametrize("retained", [True, False])
def test_automatic_memory_hint_requires_retention_and_prior_same_session_original(setup, retained):
    app, local, peer, _, second, old = setup
    app.get_run(second["run_id"], source_db=peer.name)
    memory = next(value for value in app._history().recall(limit=50)["memories"] if value["id"] == second["memory_id"])
    if not retained:
        memory["note"] = "X" * (recall.AUTOMATIC_RECALL_MAX_BYTES + 1)
    current = next_run(local)
    with closing(db.connect(local, session_id="owner")) as conn:
        emitted = recall.emit_recall_once(conn, run_id=current, query="sqlite migration",
                                         recall_reader=lambda **kwargs: {"memories": [memory], "query": "sqlite migration"})
    assert bool(emitted["memories"]) is retained
    entry = claim(peer.name, "memory", second["memory_id"])
    if retained:
        with mock.patch.object(history.HistoryReader, "get_memory", side_effect=AssertionError("unnecessary detail fetch")):
            assert app.use_references(expected_run_id=current, references=[entry])["counts"]["recorded"] == 1
        assert len(refs(local, current)) == 2 and all(ref["stage"] == "used" for ref in refs(local, current))
    else:
        with pytest.raises(WorkflowApplicationError, match="invalid_proof"):
            app.use_references(expected_run_id=current, references=[entry])
        assert not used_events(local)


@pytest.mark.parametrize("operation,target", [("search_history", "item"), ("list_records", "item"), ("recall", "memory")])
def test_search_and_list_exposure_never_prove_usage(setup, operation, target):
    app, local, peer, _, second, run_id = setup
    getattr(app, operation)("sqlite migration")
    with pytest.raises(WorkflowApplicationError, match="invalid_proof"):
        app.use_references(expected_run_id=run_id, references=[claim(peer.name, target, second[f"{target}_id"])])
    assert not used_events(local)


def test_missing_memory_original_or_wrong_source_does_not_qualify(setup):
    app, local, peer, _, second, run_id = setup
    response = app._history().get_memory(second["memory_id"], source_db=peer.name)
    response["memory"]["source_record"] = None
    run_references.record(run_references.capture(app), "get_memory", response)
    # Same original RUN id in another database does not prove this source.
    wrong = {"ok": True, "run": {"id": second["run_id"], "source_db": local.name}}
    run_references.record(run_references.capture(app), "get_run", wrong)
    with pytest.raises(WorkflowApplicationError, match="exact original"):
        app.use_references(expected_run_id=run_id, references=[claim(peer.name, "memory", second["memory_id"])])
    app.get_run(second["run_id"], source_db=peer.name)
    assert app.use_references(expected_run_id=run_id, references=[claim(peer.name, "memory", second["memory_id"])])["counts"]["recorded"] == 1


def test_item_backed_memory_requires_exact_item_not_just_its_run(setup):
    app, local, peer, _, second, run_id = setup
    with closing(db.connect(peer, session_id="owner")) as conn:
        conn.execute("UPDATE memories SET source_item_id=? WHERE memory_id=?", (second["item_id"], second["memory_id"]))
        conn.commit()
    detail = app._history().get_memory(second["memory_id"], source_db=peer.name)
    detail["memory"]["source_record"] = None
    run_references.record(run_references.capture(app), "get_memory", detail)
    app.get_run(second["run_id"], source_db=peer.name)
    entry = claim(peer.name, "memory", second["memory_id"])
    with pytest.raises(WorkflowApplicationError, match="exact original"):
        app.use_references(expected_run_id=run_id, references=[entry])
    app.get_item(second["item_id"], source_db=peer.name)
    app.use_references(expected_run_id=run_id, references=[entry])
    assert {ref["target_type"] for ref in refs(local, run_id) if ref["stage"] == "used"} == {"memory", "item"}


def test_same_memory_id_in_distinct_sources_has_distinct_usage_and_originals(setup):
    app, local, peer, first, second, run_id = setup
    with closing(db.connect(peer, session_id="owner")) as conn:
        conn.execute("UPDATE memories SET memory_id=? WHERE memory_id=?", (first["memory_id"], second["memory_id"]))
        conn.commit()
    for path in (local, peer):
        app.get_memory(first["memory_id"], source_db=path.name)
    before = peer.read_bytes()
    receipt = app.use_references(expected_run_id=run_id, references=[claim(path.name, "memory", first["memory_id"]) for path in (local, peer)])
    assert receipt["counts"]["recorded"] == 2
    assert len(refs(local, run_id)) == 4
    assert peer.read_bytes() == before


@pytest.mark.parametrize("pointer", [0, -1, True, "1", [], {}])
def test_malformed_memory_original_pointer_cannot_fall_back_to_run_proof(setup, pointer):
    app, local, peer, _, second, run_id = setup
    memory = app._history().get_memory(second["memory_id"], source_db=peer.name)["memory"]
    ref = run_references.memory_reference(memory, "opened")
    ref["source"]["item_id"] = pointer
    with closing(db.connect(local, session_id="owner")) as conn:
        db.record_event(conn, run_id=run_id, event_type=run_references.EVENT_TYPE, payload={"references": [ref]})
    app.get_run(second["run_id"], source_db=peer.name)
    with pytest.raises(WorkflowApplicationError, match="invalid_proof"):
        app.use_references(expected_run_id=run_id, references=[claim(peer.name, "memory", second["memory_id"])])
    assert not used_events(local)


def test_session_and_observer_run_owner_both_must_match(setup):
    app, local, peer, _, second, run_id = setup
    app.get_item(second["item_id"], source_db=peer.name)
    other = WorkflowApplication(app.workspace_root, session_id="other")
    other._db_path = local
    with closing(db.connect(local, session_id="other")) as conn:
        other_run = db.ensure_active_run(conn, request_summary="another conversation")["id"]
    entry = claim(peer.name, "item", second["item_id"])
    with pytest.raises(WorkflowApplicationError, match="stale_run"):
        other.use_references(expected_run_id=run_id, references=[entry])
    with pytest.raises(WorkflowApplicationError, match="invalid_proof"):
        other.use_references(expected_run_id=other_run, references=[entry])
    # An event claiming the caller's session cannot borrow a different owner's RUN.
    with closing(db.connect(local, session_id="other")) as conn:
        conn.execute("UPDATE events SET session_id='other' WHERE run_id=? AND event_type=?", (run_id, run_references.EVENT_TYPE))
        conn.commit()
    with pytest.raises(WorkflowApplicationError, match="invalid_proof"):
        other.use_references(expected_run_id=other_run, references=[entry])
    assert not used_events(local)


@pytest.mark.parametrize("retain", [False, True])
def test_discarded_observer_proof_is_ineligible_and_reopening_creates_fresh_proof(setup, retain):
    app, local, peer, _, second, old = setup
    app.get_item(second["item_id"], source_db=peer.name)
    with closing(db.connect(local, session_id="owner")) as conn:
        if retain:
            db.update_active_run_summary(conn, result_summary="retained substantive work")
        result = db.discard_run(conn, run_id=old, confirmation_run_id=old, confirmed=True)
        assert old in result["archived_run_ids" if retain else "deleted_run_ids"]
        current = db.ensure_active_run(conn, request_summary="current")["id"]
    entry = claim(peer.name, "item", second["item_id"])
    with pytest.raises(WorkflowApplicationError, match="invalid_proof"):
        app.use_references(expected_run_id=current, references=[entry])
    app.get_item(second["item_id"], source_db=peer.name)
    assert app.use_references(expected_run_id=current, references=[entry])["counts"]["recorded"] == 1


def test_used_snapshots_never_become_original_proof_and_reopening_is_observed(setup):
    app, local, peer, first, second, proof_run = setup
    app.get_item(second["item_id"], source_db=peer.name)
    use_run = next_run(local)
    entry = claim(peer.name, "item", second["item_id"])
    app.use_references(expected_run_id=use_run, references=[entry])
    app.get_item(first["item_id"], source_db=local.name)
    with closing(db.connect(local, session_id="owner")) as conn:
        # Simulate removal of the original retained evidence; used events survive.
        conn.execute("DELETE FROM events WHERE run_id=? AND event_type=?", (proof_run, run_references.EVENT_TYPE))
        conn.commit()
    with pytest.raises(WorkflowApplicationError, match="invalid_proof"):
        app.use_references(expected_run_id=use_run, references=[entry])
    assert all(second["run_id"] not in event["payload_json"] for event in events(local))
    app.get_item(second["item_id"], source_db=peer.name)
    assert any(second["run_id"] in event["payload_json"] for event in events(local))
    assert app.use_references(expected_run_id=use_run, references=[entry])["counts"]["unchanged"] == 1
    current = next_run(local)
    assert app.use_references(expected_run_id=current, references=[entry])["counts"]["recorded"] == 1


def test_long_session_old_proof_survives_projection_eviction_and_read_is_three_rows(setup):
    app, local, peer, _, second, previous = setup
    app.get_item(second["item_id"], source_db=peer.name)
    with closing(db.connect(local, session_id="owner")) as conn:
        # Even hundreds of newer snapshots that no longer retain it must not
        # hide a genuine old read. Proof search has no arbitrary history cutoff.
        conn.executemany("INSERT INTO events(run_id,session_id,event_type,payload_json,created_at) VALUES(?,?,?,?,?)",
                         [(previous, "owner", run_references.EVENT_TYPE, '{"references":[]}', db.utc_now())] * 600)
        conn.commit()
    current = next_run(local)
    app.use_references(expected_run_id=current, references=[claim(peer.name, "item", second["item_id"])])
    with closing(db.connect_readonly(local, session_id="owner")) as conn:
        queries = []
        conn.set_trace_callback(queries.append)
        assert run_references.read(conn, current)[0]["stage"] == "used"
    assert len([query for query in queries if "FROM events" in query]) == 3


@pytest.mark.parametrize("change", [{"usage": "   "}, {"usage": "x" * 501}, {"source_db": "../other.db"},
                                   {"source_db": ""}, {"title": "caller metadata"}, {"item_id": True},
                                   {"run_id": "extra"}, {"target_type": "memory"}])
def test_usage_input_contract_rejects_invalid_batch(setup, change):
    app, local, peer, _, second, run_id = setup
    app.get_item(second["item_id"], source_db=peer.name)
    entry = claim(peer.name, "item", second["item_id"])
    with pytest.raises(WorkflowApplicationError, match="invalid_reference"):
        app.use_references(expected_run_id=run_id, references=[entry, {**entry, **change}])
    assert not used_events(local)


def test_usage_batch_bounds_and_capacity_are_atomic_with_repeats_allowed(setup):
    app, local, peer, _, second, run_id = setup
    raw = run_references.history_reference(app._history().get_item(second["item_id"], source_db=peer.name)["item"], "opened")
    evidence = [{**raw, "item_id": index} for index in range(1, 201)]
    with closing(db.connect(local, session_id="owner")) as conn:
        db.record_event(conn, run_id=run_id, event_type=run_references.EVENT_TYPE, payload={"references": evidence})
        db.record_event(conn, run_id=run_id, event_type=run_references.EVENT_TYPE, payload={"references": [{**raw, "item_id": 201}]})
    for offset in range(0, 200, 50):
        app.use_references(expected_run_id=run_id, references=[claim(peer.name, "item", i) for i in range(offset + 1, offset + 51)])
    before = len(used_events(local))
    for entries in ([], [claim(peer.name, "item", 1)] * 51):
        with pytest.raises(WorkflowApplicationError, match="1–50"):
            app.use_references(expected_run_id=run_id, references=entries)
    with pytest.raises(WorkflowApplicationError, match="reference_limit: used_count=200, proposed_count=201, limit=200"):
        app.use_references(expected_run_id=run_id, references=[claim(peer.name, "item", 1), claim(peer.name, "item", 201)])
    assert app.use_references(expected_run_id=run_id, references=[claim(peer.name, "item", 1)] * 2)["counts"] == {"recorded": 0, "unchanged": 2}
    assert len(used_events(local)) == before
    assert len(refs(local, run_id)) == 200 and all(ref["stage"] == "used" for ref in refs(local, run_id))


def test_old_schema_adds_session_proof_index_after_columns_idempotently(tmp_path):
    path = tmp_path / "old.db"
    with closing(db.connect(path)) as conn:
        conn.execute("DROP INDEX idx_events_session_type_id")
        conn.execute("DROP INDEX idx_session_active_run")
        conn.execute("ALTER TABLE events DROP COLUMN session_id")
        conn.execute("ALTER TABLE workflow_runs DROP COLUMN session_id")
        conn.commit()
    for _ in range(2):
        with closing(db.connect(path)) as conn:
            assert [row[2] for row in conn.execute("PRAGMA index_info(idx_events_session_type_id)")] == ["session_id", "event_type", "id"]


@pytest.mark.parametrize("source", ["local", "foreign"])
def test_finish_memory_use_projects_despite_cooldown_or_foreign_reinforcement_skip(setup, source):
    app, local, peer, first, second, old = setup
    path, memory = (local, first) if source == "local" else (peer, second)
    detail = next(value for value in app.recall(limit=50)["memories"] if value["id"] == memory["memory_id"] and value["source_db"] == path.name)
    app.get_run(memory["run_id"], source_db=path.name)
    current = next_run(local)
    foreign_before = peer.read_bytes()
    result = app.finish_run("Done", expected_run_id=current,
                            memory_uses=[{"memory_id": memory["memory_id"], "source_db": path.name,
                                          "revision": detail["revision"], "source_checked": True, "usage": "Used the checked migration rule"}],
                            memory_review={"decision": "skip", "reason": "No additional reusable lesson."})
    assert result["memory"]["reinforcements"][0]["reason"] == ("cooldown" if source == "local" else "foreign_source_read_only")
    assert len(refs(local, current)) == 2 and all(ref["stage"] == "used" for ref in refs(local, current))
    assert peer.read_bytes() == foreign_before


@pytest.mark.parametrize("checked,observed,disabled", [(False, True, False), (True, False, False), (True, True, True)])
def test_finish_invalid_or_disabled_memory_use_does_not_fabricate_links(setup, checked, observed, disabled):
    app, local, peer, _, second, old = setup
    if observed:
        app.get_memory(second["memory_id"], source_db=peer.name)
    current = next_run(local)
    if disabled:
        (app.workspace_root / ".tapl/config.toml").write_text('[recall]\nenabled=false\n[subagents]\nenabled=false\n')
    result = app.finish_run("Durable result", expected_run_id=current,
                            memory_uses=[{"memory_id": second["memory_id"], "source_db": peer.name, "revision": 1,
                                          "source_checked": checked, "usage": "Applied rule"}],
                            memory_review={"decision": "skip", "reason": "No new lesson."})
    assert result["ok"] and result["active_run"]["result_summary"] == "Durable result"
    assert refs(local, current) == []
    if disabled:
        assert result["memory"]["status"] == "disabled"


def test_finish_projection_failure_preserves_result_and_memory_review(setup):
    app, local, peer, _, second, run_id = setup
    app.get_memory(second["memory_id"], source_db=peer.name)
    with mock.patch.object(run_references, "use", side_effect=sqlite3.OperationalError("unavailable telemetry")):
        result = app.finish_run("Durable result", expected_run_id=run_id,
                               memory_uses=[{"memory_id": second["memory_id"], "source_db": peer.name, "revision": 1,
                                             "source_checked": True, "usage": "Applied rule"}],
                               memory_review={"decision": "skip", "reason": "No new lesson."})
    assert result["memory"]["status"] == "ok"
    assert result["active_run"]["result_summary"] == "Durable result"
    assert all(ref["stage"] == "opened" for ref in refs(local, run_id))


def test_native_stdio_use_references_schema_receipt_and_projection(setup, tmp_path):
    """Negotiate the real MCP entrypoint without a model or user credentials."""
    import asyncio
    import sys
    from mcp import Client
    from mcp.client.stdio import StdioServerParameters, stdio_client

    app, local, peer, _, second, previous = setup
    app.recall("sqlite migration", limit=50)
    app.get_run(second["run_id"], source_db=peer.name)
    current = next_run(local)
    before = peer.read_bytes()
    params = StdioServerParameters(
        command=sys.executable,
        args=["-c", (
            "import runpy\nfrom pathlib import Path\nfrom unittest.mock import patch\nfrom taplctl import db\n"
            f"with patch.object(Path, 'home', return_value=Path({str(tmp_path / 'isolated-user')!r})), "
            f"patch.object(db, 'default_db_path', return_value=Path({str(local)!r})):\n"
            "    runpy.run_module('taplctl.mcp_server', run_name='__main__', alter_sys=True)\n"
        )], cwd=app.workspace_root,
    )

    async def exercise():
        async with Client(stdio_client(params)) as client:
            tools = (await client.list_tools()).tools
            tool = next(tool for tool in tools if tool.name == "tapl_use_references")
            assert set(tool.input_schema["required"]) == {"expected_run_id", "references", "session_id"}
            assert tool.input_schema["properties"]["references"]["maxItems"] == 50
            assert not tool.annotations.read_only_hint and tool.annotations.idempotent_hint
            assert set(tool.input_schema["$defs"]["MemoryReferenceUse"]["required"]) == {
                "kind", "target_type", "source_db", "memory_id", "usage"}
            args = {"expected_run_id": current, "session_id": "owner",
                    "references": [claim(peer.name, "memory", second["memory_id"])]}
            for change in ({"session_id": ""}, {"session_id": None}, {"references": []},
                           {"references": [{**args["references"][0], "title": "forged"}]},
                           {"references": [{**args["references"][0], "usage": "   "}]}):
                assert (await client.call_tool("tapl_use_references", {**args, **change})).is_error
            assert (await client.call_tool("tapl_use_references", {key: value for key, value in args.items() if key != "session_id"})).is_error
            receipt = await client.call_tool("tapl_use_references", args)
            repeated = await client.call_tool("tapl_use_references", args)
            assert not receipt.is_error and not repeated.is_error
            assert receipt.structured_content["operation"] == "references_use"
            assert receipt.structured_content["counts"] == {"recorded": 1, "unchanged": 0}
            assert repeated.structured_content["counts"] == {"recorded": 0, "unchanged": 1}
            assert "references" not in receipt.structured_content
            assert "PRIVATE-NOTE" not in json.dumps(receipt.structured_content)
            status = (await client.call_tool("tapl_get_status", {"session_id": "owner"})).structured_content
            detail = (await client.call_tool("tapl_get_run", {"run_id": current, "session_id": "owner"})).structured_content
            assert status["references"] == detail["references"]
            assert len(status["references"]) == 2 and all(ref["stage"] == "used" for ref in status["references"])

    asyncio.run(exercise())
    assert len(used_events(local)) == 1
    assert peer.read_bytes() == before


def test_invalid_item_hint_has_no_event_reference_or_run_proof(setup):
    app, local, peer, _, second, run_id = setup
    memory = next(value for value in app._history().recall(limit=50)['memories'] if value['id'] == second['memory_id'])
    memory['source'].update(kind='item', item_id=0)
    with closing(db.connect(local, session_id='owner')) as conn:
        result = recall.emit_recall_once(conn, run_id=run_id, query='sqlite migration',
                                        recall_reader=lambda **kwargs: {'memories': [memory], 'query': 'sqlite migration'})
        event = json.loads(conn.execute("SELECT payload_json FROM events WHERE run_id=? AND event_type='memory_recall_attempted'",
                                        (run_id,)).fetchone()[0])
    assert result['memories'] == event['memory_ids'] == event['memory_sources'] == event['references'] == []
    assert refs(local, run_id) == []
    with pytest.raises(WorkflowApplicationError, match='invalid_proof'):
        app.use_references(expected_run_id=run_id, references=[claim(peer.name, 'memory', second['memory_id'])])


def test_automatic_hint_excludes_own_original_from_another_creation_run_but_keeps_foreign_same_id(setup):
    app, local, peer, _, second, run_id = setup
    with closing(db.connect(local, session_id='owner')) as conn:
        item = db.upsert_plan(conn, plan_id='PLAN-001', title='Current original', status='Finalized')
    with closing(db.connect(local, session_id='other-owner')) as conn:
        other = db.ensure_active_run(conn, request_summary='Another creation RUN', work_type='answer', workflow_mode='fast')
        captured = recall.finish_memories(conn, run_id=other['id'], candidates=[{
            'slot': 1, 'cue': ['sqlite migration', 'transaction', 'schema'], 'note': 'Another RUN captured this current original.',
            'source_run_id': run_id, 'source_item_id': item['id']}])
        own_memory_id = captured['captures'][0]['memory_id']
    with closing(db.connect(local, session_id='owner')) as conn:
        own_memory = recall.collect_automatic_recall(conn, query='sqlite migration', current_run_id=run_id)['memories']
        own_memory = next(entry for entry in own_memory if entry['id'] == own_memory_id)
        assert own_memory['source']['run_id'] == run_id
        assert conn.execute('SELECT created_run_id FROM memories WHERE memory_id=?', (own_memory_id,)).fetchone()[0] == other['id']
        # run_id equality alone never excludes an independent foreign database.
        foreign = app._history().get_memory(second['memory_id'], source_db=peer.name)['memory']
        foreign['source']['run_id'] = run_id
        result = recall.emit_recall_once(conn, run_id=run_id, query='sqlite migration',
                                        recall_reader=lambda **kwargs: {'memories': [own_memory, foreign], 'query': 'sqlite migration'})
        event = json.loads(conn.execute("SELECT payload_json FROM events WHERE run_id=? AND event_type='memory_recall_attempted'",
                                        (run_id,)).fetchone()[0])
    assert [entry['id'] for entry in result['memories']] == event['memory_ids'] == [second['memory_id']]
    assert [entry['memory_id'] for entry in event['memory_sources']] == [second['memory_id']]
    assert [entry['memory_id'] for entry in event['references']] == [second['memory_id']]
    assert event['references'][0]['source_db'] == peer.name
    assert event['references'][0]['source']['run_id'] == run_id
    assert own_memory_id not in {entry.get('memory_id') for entry in refs(local, run_id)}
