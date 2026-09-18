from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
import sqlite3
import unicodedata

import pytest

from taplctl import db, recall


T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


def run(conn, name, *, summary="A verified result"):
    conn.execute("UPDATE workflow_runs SET status='archived' WHERE status='active'")
    conn.execute("INSERT INTO workflow_runs(id,slug,status,request_summary,result_summary,created_at,updated_at) VALUES(?,?,'active',?,?,?,?)", (name, name, name, summary, T0.isoformat(), T0.isoformat()))
    conn.commit()
    return name


@pytest.fixture
def conn(tmp_path):
    connection = db.connect(tmp_path / "test.db")
    run(connection, "r1")
    yield connection
    connection.close()


def candidate(*, slot=1, source="r1", note="Use SQLite transactions to keep updates atomic.", cue=None, **extra):
    return {"slot": slot, "source_run_id": source, "note": note, "cue": cue or ["SQLite transactions", "atomic updates", "storage safety"], **extra}


def capture(conn, *, current="r1", now=T0, **kwargs):
    result = recall.finish_memories(conn, run_id=current, candidates=[candidate(**kwargs)], now=now)
    assert not result["errors"], result
    return result["captures"][0]["memory_id"]


def use(memory_id, revision=1, **extra):
    return {"memory_id": memory_id, "revision": revision, "source_checked": True, "usage": "Applied its transaction boundary to the write path.", **extra}


def test_capture_dto_original_and_idempotency(conn):
    memory_id = capture(conn)
    first = recall.get_memory(conn, memory_id, now=T0)
    assert first["half_life_days"] == 7
    assert first["strength"] == 1
    assert first["last_reinforced_at"] is None
    assert first["source"]["run_id"] == "r1"
    assert first["source_record"]["run"]["result_summary"] == "A verified result"
    assert first["source_available"]
    repeated = recall.finish_memories(conn, run_id="r1", candidates=[candidate()], now=T0)
    assert repeated["captures"][0]["status"] == "already_captured"
    conflict = recall.finish_memories(conn, run_id="r1", candidates=[candidate(note="Different content.")])
    assert conflict["errors"][0]["code"] == "conflict"
    assert conn.execute("SELECT count(*) FROM memories").fetchone()[0] == 1


def test_normalized_dedup_consumes_receipt_slot(conn):
    memory_id = capture(conn)
    run(conn, "r2")
    duplicate = candidate(source="r1", note=" USE SQLite  transactions to keep updates atomic. ", cue=[" storage safety ", "ATOMIC UPDATES", "SQLite transactions"])
    result = recall.finish_memories(conn, run_id="r2", candidates=[duplicate])
    assert result["captures"] == [{"slot": 1, "memory_id": memory_id, "status": "deduplicated"}]
    assert recall.finish_memories(conn, run_id="r2", candidates=[candidate(note="New content.")])["errors"][0]["code"] == "conflict"


@pytest.mark.parametrize("change", [{"slot": True}, {"slot": 3}, {"cue": ["a", "b"]}, {"cue": ["a", "A", "b"]}, {"note": "x" * 241}, {"source_item_id": True}, {"source_run_id": "missing"}])
def test_candidate_validation(conn, change):
    value = candidate()
    value.update(change)
    result = recall.finish_memories(conn, run_id="r1", candidates=[value])
    assert result["errors"]
    assert conn.execute("SELECT count(*) FROM memories").fetchone()[0] == 0
    assert conn.execute("SELECT count(*) FROM memory_fts").fetchone()[0] == 0


def test_max_two_candidates(conn):
    result = recall.finish_memories(conn, run_id="r1", candidates=[candidate()] * 3)
    assert result["errors"][0]["code"] == "invalid"
    assert not result["captures"]


def test_source_identity_and_original_unchanged(conn):
    conn.execute("INSERT INTO items(run_id,stable_id,kind,title,body,created_at,updated_at) VALUES('r1','PLAN-1','plan','Plan','Original',?,?)", (T0.isoformat(), T0.isoformat()))
    item_id = conn.execute("SELECT id FROM items").fetchone()[0]
    conn.commit()
    run(conn, "r2", summary="")
    result = recall.finish_memories(conn, run_id="r2", candidates=[candidate(source="r2", source_item_id=item_id)])
    assert result["errors"][0]["code"] == "not_found"
    assert recall.finish_memories(conn, run_id="r2", candidates=[candidate(source="r2")])["errors"]
    recall.finish_memories(conn, run_id="r2", review={"decision": "skip", "reason": "Acknowledge failed source validation examples."})
    memory_id = capture(conn, current="r2", source_item_id=item_id)
    original = recall.get_memory(conn, memory_id)["source_record"]["item"]
    recall.update_memory(conn, memory_id, expected_revision=1, note="Updated memory.")
    assert original["body"] == "Original"
    assert conn.execute("SELECT body FROM items WHERE id=?", (item_id,)).fetchone()[0] == "Original"


def test_source_cascade_cannot_reuse_capture_slot(conn):
    run(conn, "r2")
    memory_id = capture(conn, current="r2")
    conn.execute("DELETE FROM workflow_runs WHERE id='r1'")
    conn.commit()
    assert conn.execute("SELECT count(*) FROM memories").fetchone()[0] == 0
    assert conn.execute("SELECT count(*) FROM memory_fts").fetchone()[0] == 0
    result = recall.finish_memories(conn, run_id="r2", candidates=[candidate()])
    assert result["captures"][0]["memory_id"] == memory_id
    assert result["captures"][0]["status"] == "already_captured"
    assert recall.finish_memories(conn, run_id="r2", candidates=[candidate(source="r2", note="Changed.")])["errors"][0]["code"] == "conflict"


def test_deleted_content_removed_and_recreation_suppressed(conn):
    memory_id = capture(conn)
    deleted = recall.delete_memory(conn, memory_id, expected_revision=1, now=T0)
    assert deleted == {"id": memory_id, "state": "deleted", "revision": 2}
    row = conn.execute("SELECT * FROM memories").fetchone()
    assert row["note"] == "" and row["cues_json"] == "[]"
    assert conn.execute("SELECT count(*) FROM memory_fts").fetchone()[0] == 0
    with pytest.raises(recall.MemoryError) as err:
        recall.get_memory(conn, memory_id)
    assert err.value.code == "not_found"
    conn.execute("DELETE FROM workflow_runs WHERE id='r1'")
    conn.commit()
    run(conn, "r2")
    result = recall.finish_memories(conn, run_id="r2", candidates=[candidate(source="r2")])
    assert result["captures"][0]["status"] == "deduplicated"
    assert conn.execute("SELECT count(*) FROM memories").fetchone()[0] == 0


def test_edited_deleted_fingerprint_survives_source_cascade(conn):
    memory_id = capture(conn)
    recall.update_memory(conn, memory_id, expected_revision=1, note="An edited note.")
    recall.delete_memory(conn, memory_id, expected_revision=2)
    conn.execute("DELETE FROM workflow_runs WHERE id='r1'")
    conn.commit()
    run(conn, "r2")
    result = recall.finish_memories(conn, run_id="r2", candidates=[candidate(source="r2", note="An edited note.")])
    assert result["captures"][0]["status"] == "deduplicated"


def test_revision_edit_reset_and_read_no_changes(conn):
    memory_id = capture(conn)
    run(conn, "r2")
    recall.finish_memories(conn, run_id="r2", uses=[use(memory_id)], now=T0 + timedelta(days=1))
    before = conn.total_changes
    recall.get_memory(conn, memory_id, now=T0 + timedelta(days=2))
    recall.recall_memories(conn, query="SQLite", now=T0 + timedelta(days=2))
    assert conn.total_changes == before
    edited = recall.update_memory(conn, memory_id, expected_revision=1, note="Revised SQLite transactions note.", now=T0 + timedelta(days=2))
    assert edited["revision"] == 2 and edited["half_life_days"] == 7
    assert edited["last_reinforced_at"] is None and edited["strength"] == 1
    assert recall.finish_memories(conn, run_id="r2", uses=[use(memory_id, 2)], now=T0 + timedelta(days=4))["reinforcements"][0]["reason"] == "same_run"
    with pytest.raises(recall.MemoryError) as err:
        recall.delete_memory(conn, memory_id, expected_revision=1)
    assert err.value.code == "conflict"
    assert recall.recall_memories(conn, query="Revised")["total"] == 1


def test_reinforcement_requires_actual_use_and_source_revision(conn):
    memory_id = capture(conn)
    run(conn, "r2")
    for value in [use(memory_id, source_checked=False), use(memory_id, usage=" "), use(memory_id, 2)]:
        assert recall.finish_memories(conn, run_id="r2", uses=[value], now=T0 + timedelta(days=2))["errors"]
    assert recall.get_memory(conn, memory_id)["half_life_days"] == 7


def test_reinforcement_cooldown_age_and_cap(conn):
    memory_id = capture(conn)
    assert recall.get_memory(conn, memory_id, now=T0 + timedelta(days=7))["strength"] == .5
    assert recall.finish_memories(conn, run_id="r1", uses=[use(memory_id)], now=T0 + timedelta(days=4))["reinforcements"][0]["reason"] == "same_run"
    run(conn, "r2")
    assert recall.finish_memories(conn, run_id="r2", uses=[use(memory_id)], now=T0 + timedelta(hours=23, minutes=59))["reinforcements"][0]["reason"] == "cooldown"
    for day, expected in enumerate([14, 28, 56, 90, 90], 1):
        if day > 1:
            run(conn, f"r{day+1}")
        result = recall.finish_memories(conn, run_id=f"r{day+1}", uses=[use(memory_id)], now=T0 + timedelta(days=day))
        assert result["reinforcements"][0]["half_life_days"] == expected
    final = recall.get_memory(conn, memory_id, now=T0 + timedelta(days=5))
    assert final["strength"] == 1 and final["updated_at"] == T0.isoformat()


def test_stale_run_rejected_and_empty_recall_once(conn):
    run(conn, "r2")
    result = recall.finish_memories(conn, run_id="r1", candidates=[candidate()])
    assert result["errors"][0]["code"] == "conflict"
    first = recall.emit_recall_once(conn, run_id="r2", query="nothing")
    assert first["status"] == "empty"
    assert recall.emit_recall_once(conn, run_id="r2", query="anything")["status"] == "already_attempted"
    assert conn.execute("SELECT count(*) FROM events WHERE event_type='memory_recall_attempted'").fetchone()[0] == 1


def test_automatic_gates_same_creation_run_or_singleton_and_retains_old(conn):
    memory_id = capture(conn)
    assert not recall.recall_memories(conn, query="SQLite transactions", current_run_id="r1", automatic=True)["memories"]
    run(conn, "r2")
    assert not recall.recall_memories(conn, query="SQLite banana", current_run_id="r2", automatic=True)["memories"]
    exact = recall.recall_memories(conn, query="SQLite transactions", current_run_id="r2", automatic=True, now=T0 + timedelta(days=3650))
    assert exact["memories"][0]["id"] == memory_id
    assert exact["memories"][0]["matched_cues"] == ["SQLite transactions"]
    assert recall.recall_memories(conn, query="SQLite atomic", automatic=True)["memories"]


def test_korean_budget_and_malformed_fts(conn):
    memory_id = capture(conn, note="배포 전에 SQLite 트랜잭션 경계를 확인한다.", cue=["배포 확인", "트랜잭션 경계", "원본 기록"])
    run(conn, "r2")
    result = recall.emit_recall_once(conn, run_id="r2", query='트랜잭션 경계 " OR : *')
    assert result["memories"][0]["id"] == memory_id
    assert len(json.dumps(result, ensure_ascii=False).encode()) <= 1200
    with pytest.raises(recall.MemoryError):
        recall.recall_memories(conn, query="x" * 2001)
    assert recall.recall_memories(conn, query='" : * AND OR ()')["memories"] == []


@pytest.mark.parametrize("cue,query", [
    ("연상 기억", "연상기억"),
    ("연상기억", "연상 기억"),
    ("TAPL 연상 기억", "오늘 연상기억 회상 확인"),
    ("연상 기억 회상", "연상기억 회상"),
    ("연상기억회상", "연상 기억 회상"),
    ("연상 기 억", "연 상기 억"),
    ("연상\t기억", "연상기억"),
    (unicodedata.normalize("NFD", "연상 기억"), "연상기억"),
])
def test_korean_spacing_recall_preserves_original_and_read_only(conn, cue, query):
    memory_id = capture(conn, note="A verified spacing lesson.", cue=[cue, "memory index", "finish_run"])
    run(conn, "reader")
    before = recall.get_memory(conn, memory_id, now=T0)
    changes = conn.total_changes
    for automatic in (False, True):
        result = recall.recall_memories(conn, query=query, automatic=automatic, current_run_id="reader", now=T0)
        assert [m["id"] for m in result["memories"]] == [memory_id]
        assert result["memories"][0]["matched_cues"] == ([] if cue.startswith("TAPL") else [cue])
    assert conn.total_changes == changes
    assert recall.get_memory(conn, memory_id, now=T0) == before


@pytest.mark.parametrize("query", [
    "기억", "연상", "연상기", "상기억", "비연상기억", "연상기억X",
    "연상/기억", "연상_기억", "연상 a 기억",
    "one two three four five six seven eight 연상기억",
])
def test_spacing_does_not_promote_short_partial_or_nonspace_matches(conn, query):
    capture(conn, note="A verified spacing lesson.", cue=["연상기억", "memory index", "finish_run"])
    assert not recall.recall_memories(conn, query=query, automatic=True)["memories"]


@pytest.mark.parametrize("cues", [
    ["연상/기억", "memory index", "finish_run"],
    ["연상_기억", "memory index", "finish_run"],
    ["연상 v2 기억", "memory index", "finish_run"],
    ["연상", "기억", "finish_run"],
])
def test_spacing_aliases_do_not_cross_punctuation_identifiers_or_cues(conn, cues):
    capture(conn, note="A verified spacing lesson.", cue=cues)
    assert recall.recall_memories(conn, query="연상기억")["total"] == 0


def test_spacing_is_cue_scoped_and_preserves_english_identifiers(conn):
    memory_id = capture(conn, note="연상 기억 설명.", cue=["memory recall", "finish_run", "Developer ID"])
    assert not recall.recall_memories(conn, query="연상기억")["memories"]
    for query in ("memory recall", "finish_run", "Developer ID"):
        assert recall.recall_memories(conn, query=query, automatic=True)["memories"][0]["id"] == memory_id
    for query in ("memoryrecall", "finishrun", "DeveloperID"):
        assert not recall.recall_memories(conn, query=query, automatic=True)["memories"]


@pytest.mark.parametrize("cue,query", [
    ("프로젝트 alpha", "프로젝트 beta"),
    ("트랜잭션 경계", "트랜잭션 실패"),
    ("프로젝트 배포", "프로젝트"),
    ("프로젝트 finish_연상 기억", "프로젝트 finish_연상기억"),
    ("프로젝트 v2연상 기억", "프로젝트 v2연상기억"),
])
def test_single_long_korean_word_does_not_bypass_automatic_gate(conn, cue, query):
    capture(conn, note="A verified lesson.", cue=[cue, "memory index", "finish_run"])
    assert recall.recall_memories(conn, query=query)["memories"]
    assert not recall.recall_memories(conn, query=query, automatic=True)["memories"]


def test_spacing_alias_precedes_broad_prefix_candidate_budget(conn):
    for index in range(26):
        run(conn, f"noise{index}")
        capture(conn, current=f"noise{index}", source=f"noise{index}",
                note=f"Unrelated case {index}.", cue=["연상안내", "기억안내", "noise entry"])
    run(conn, "target")
    memory_id = capture(conn, current="target", source="target", note="The exact compound.",
                        cue=["연상기억", "memory index", "finish_run"])
    run(conn, "reader")
    result = recall.emit_recall_once(conn, run_id="reader", query="연상 기억")
    assert [m["id"] for m in result["memories"]] == [memory_id]
    assert len(json.dumps(result, ensure_ascii=False).encode()) <= 1200


def test_spacing_manual_pagination_and_update_delete(conn):
    ids = []
    for index, cue in enumerate(("연상기억", "연상 기억", "연상기억", "연상 기억")):
        run(conn, f"source{index}")
        ids.append(capture(conn, current=f"source{index}", source=f"source{index}",
                           note=f"Verified case {index}.", cue=[cue, "memory index", "finish_run"]))
    for query in ("연상기억", "연상 기억"):
        first = recall.recall_memories(conn, query=query, limit=2)
        second = recall.recall_memories(conn, query=query, limit=2, offset=2)
        assert first["total"] == second["total"] == 4
        found = [m["id"] for m in first["memories"] + second["memories"]]
        assert len(found) == len(set(found)) == 4
        assert set(found) == set(ids)
    recall.update_memory(conn, ids[1], expected_revision=1, cue=["배포 확인", "memory index", "finish_run"])
    assert ids[1] not in {m["id"] for m in recall.recall_memories(conn, query="연상기억")["memories"]}
    assert recall.recall_memories(conn, query="배포확인", automatic=True)["memories"][0]["id"] == ids[1]
    recall.delete_memory(conn, ids[1], expected_revision=2)
    assert recall.recall_memories(conn, query="배포확인")["total"] == 0


def test_auto_full_response_budget_and_manual_pagination(conn):
    for index in range(5):
        if index:
            run(conn, f"r{index+1}")
        capture(conn, current=f"r{index+1}", source=f"r{index+1}", note=f"SQLite transactions need atomic updates in case {index}.")
    run(conn, "reader")
    auto = recall.emit_recall_once(conn, run_id="reader", query="SQLite transactions")
    assert 0 < len(auto["memories"]) <= 3
    assert len(json.dumps(auto, ensure_ascii=False).encode()) <= 1200
    first = recall.recall_memories(conn, query="SQLite", limit=2)
    second = recall.recall_memories(conn, query="SQLite", limit=2, offset=2)
    assert first["total"] == second["total"] == 5
    assert not ({m["id"] for m in first["memories"]} & {m["id"] for m in second["memories"]})
    assert recall.recall_memories(conn, limit=50)["total"] == 5
    with pytest.raises(recall.MemoryError):
        recall.recall_memories(conn, limit=51)


def test_long_original_title_does_not_displace_a_useful_hint(conn):
    memory_id = capture(conn, note="트랜잭션 경계를 확인하고 원본 구현을 다시 읽는다.")
    conn.execute("UPDATE workflow_runs SET request_summary=? WHERE id='r1'", ("긴 원본 설명 " * 1000,))
    conn.commit()
    run(conn, "reader")
    hint = recall.emit_recall_once(conn, run_id="reader", query="SQLite transactions")
    assert hint["memories"][0]["id"] == memory_id
    assert hint["memories"][0]["source"]["run_id"] == "r1"
    assert len(json.dumps(hint, ensure_ascii=False).encode()) <= 1200
    assert len(recall.get_memory(conn, memory_id)["source"]["title"]) > 1200


def test_v10_migration_keeps_wal_source_and_one_backup(tmp_path):
    path = tmp_path / "old.db"
    conn = db.connect(path)
    run(conn, "original")
    conn.executescript("DROP TRIGGER memories_delete_fts; DROP TABLE memory_fts; DROP TABLE memories; UPDATE meta SET value='10' WHERE key='schema_version';")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("UPDATE workflow_runs SET result_summary='Committed in WAL',updated_at='unchanged' WHERE id='original'")
    conn.commit()
    migrated = db.connect(path)
    assert db.get_meta(migrated)["schema_version"] == str(db.SCHEMA_VERSION)
    assert tuple(migrated.execute("SELECT result_summary,updated_at FROM workflow_runs WHERE id='original'").fetchone()) == ("Committed in WAL", "unchanged")
    assert migrated.execute("SELECT count(*) FROM memories").fetchone()[0] == 0
    migrated.close()
    backup = path.with_name(path.name + ".pre-v11.bak")
    before = backup.stat().st_mtime_ns
    with sqlite3.connect(backup) as original:
        assert original.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0] == "10"
        assert original.execute("SELECT result_summary FROM workflow_runs WHERE id='original'").fetchone()[0] == "Committed in WAL"
    db.connect(path).close()
    assert backup.stat().st_mtime_ns == before
    conn.close()


def prepare_v11_index(conn):
    """Restore the previous release's derived index without changing memories."""
    conn.execute("DELETE FROM memory_fts")
    for row in conn.execute("SELECT id,cues_json,note FROM memories WHERE state!='deleted'"):
        conn.execute("INSERT INTO memory_fts(rowid,cue,note) VALUES(?,?,?)",
                     (row["id"], " ".join(json.loads(row["cues_json"])), row["note"]))
    conn.execute("UPDATE meta SET value='11' WHERE key='schema_version'")
    conn.commit()


def test_v11_spacing_backfill_keeps_memories_events_and_backup(conn, tmp_path):
    previous = capture(conn, cue=["연상 기억", "memory index", "finish_run"])
    run(conn, "r2")
    active = capture(conn, current="r2", source="r2", note="Updated lesson.",
                     cue=["연상 기억", "memory index", "finish_run"], replaces_memory_id=previous)
    deleted = capture(conn, current="r2", source="r2", slot=2, note="Remove this lesson.",
                      cue=["배포 확인", "memory index", "finish_run"])
    recall.delete_memory(conn, deleted, expected_revision=1)
    prepare_v11_index(conn)
    before_memories = [tuple(row) for row in conn.execute("SELECT * FROM memories ORDER BY id")]
    before_events = [tuple(row) for row in conn.execute("SELECT * FROM events ORDER BY id")]
    assert recall.recall_memories(conn, query="연상기억")["total"] == 0
    path = tmp_path / "test.db"
    migrated = db.connect(path)
    try:
        assert db.get_meta(migrated)["schema_version"] == str(db.SCHEMA_VERSION)
        assert [tuple(row) for row in migrated.execute("SELECT * FROM memories ORDER BY id")] == before_memories
        assert [tuple(row) for row in migrated.execute("SELECT * FROM events ORDER BY id")] == before_events
        assert {m["id"] for m in recall.recall_memories(migrated, query="연상기억")["memories"]} == {previous, active}
        assert [m["id"] for m in recall.recall_memories(migrated, query="연상기억", automatic=True)["memories"]] == [active]
        assert recall.recall_memories(migrated, query="배포확인")["total"] == 0
        assert migrated.execute("SELECT count(*) FROM memory_fts").fetchone()[0] == 2
        statements = []
        migrated.set_trace_callback(statements.append)
        db.migrate(migrated)
        assert not any(sql.lstrip().startswith("DELETE FROM memory_fts") for sql in statements)
    finally:
        migrated.close()
    backup = path.with_name(path.name + ".pre-v12.bak")
    before_mtime = backup.stat().st_mtime_ns
    with sqlite3.connect(backup) as original:
        assert original.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0] == "11"
        assert original.execute("SELECT count(*) FROM memory_fts WHERE memory_fts MATCH '연상기억'").fetchone()[0] == 0
        assert original.execute("SELECT * FROM memories ORDER BY id").fetchall() == before_memories
    db.connect(path).close()
    assert backup.stat().st_mtime_ns == before_mtime


def test_v11_spacing_backfill_failure_rolls_back_and_can_retry(conn, tmp_path, monkeypatch):
    capture(conn, cue=["연상 기억", "memory index", "finish_run"])
    capture(conn, slot=2, note="Another lesson.", cue=["배포 확인", "memory index", "finish_run"])
    prepare_v11_index(conn)
    before_index = [tuple(row) for row in conn.execute("SELECT rowid,* FROM memory_fts ORDER BY rowid")]
    original_indexed_cues = db.memory_search.indexed_cues
    calls = 0

    def fail_after_one(cues):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("simulated indexing failure")
        return original_indexed_cues(cues)

    path = tmp_path / "test.db"
    with monkeypatch.context() as patch:
        patch.setattr(db.memory_search, "indexed_cues", fail_after_one)
        with pytest.raises(RuntimeError, match="simulated indexing failure"):
            db.connect(path)
    assert db.get_meta(conn)["schema_version"] == "11"
    assert [tuple(row) for row in conn.execute("SELECT rowid,* FROM memory_fts ORDER BY rowid")] == before_index
    migrated = db.connect(path)
    try:
        assert db.get_meta(migrated)["schema_version"] == str(db.SCHEMA_VERSION)
        assert recall.recall_memories(migrated, query="연상기억")["total"] == 1
        assert recall.recall_memories(migrated, query="배포확인")["total"] == 1
    finally:
        migrated.close()


def test_concurrent_v11_spacing_backfill_is_idempotent(conn, tmp_path):
    memory_id = capture(conn, cue=["연상 기억", "memory index", "finish_run"])
    prepare_v11_index(conn)
    path = tmp_path / "test.db"

    def migrate_and_read(_):
        connection = db.connect(path)
        try:
            return [m["id"] for m in recall.recall_memories(connection, query="연상기억")["memories"]]
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(migrate_and_read, range(2))) == [[memory_id], [memory_id]]
    assert conn.execute("SELECT count(*) FROM memory_fts").fetchone()[0] == 1


def test_supersession_and_fts_cleanup(conn):
    previous = capture(conn)
    run(conn, "r2")
    newer = capture(conn, current="r2", source="r2", note="SQLite transactions should use a bounded lock.", replaces_memory_id=previous)
    assert recall.get_memory(conn, previous)["state"] == "superseded"
    assert recall.get_memory(conn, previous)["revision"] == 2
    assert recall.recall_memories(conn)["total"] == 2
    auto = recall.recall_memories(conn, query="SQLite transactions", automatic=True)
    assert [m["id"] for m in auto["memories"]] == [newer]
    assert recall.finish_memories(conn, run_id="r2", uses=[use(previous, 2)], now=T0 + timedelta(days=5))["errors"]


def test_concurrent_recall_and_delete_vs_update(conn, tmp_path):
    memory_id = capture(conn)
    run(conn, "r2")
    path = tmp_path / "test.db"

    def attempt(_):
        other = db.connect(path)
        try:
            return recall.emit_recall_once(other, run_id="r2", query="SQLite transactions")["status"]
        finally:
            other.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        statuses = list(executor.map(attempt, range(2)))
    assert sorted(statuses) == ["already_attempted", "recalled"]

    def mutate(delete):
        other = db.connect(path)
        try:
            if delete:
                return recall.delete_memory(other, memory_id, expected_revision=1)["revision"]
            return recall.update_memory(other, memory_id, expected_revision=1, note="Race revision.")["revision"]
        except recall.MemoryError as exc:
            return exc.code
        finally:
            other.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(mutate, [True, False]))
    assert results.count(2) == 1
    assert any(value in ("not_found", "conflict") for value in results)
    if conn.execute("SELECT state FROM memories").fetchone()[0] == "deleted":
        assert conn.execute("SELECT count(*) FROM memory_fts").fetchone()[0] == 0


def test_transaction_rollback_preserves_original_on_capture_failure(conn):
    memory_id = capture(conn)
    run(conn, "r2")
    conn.execute("CREATE TRIGGER fail_capture BEFORE INSERT ON events WHEN NEW.event_type='memory_capture' BEGIN SELECT RAISE(ABORT,'forced'); END")
    conn.commit()
    result = recall.finish_memories(conn, run_id="r2", candidates=[candidate(note="New note.", replaces_memory_id=memory_id)])
    assert result["status"] == "failed"
    assert result["errors"][0]["code"] == "memory_unavailable"
    assert recall.get_memory(conn, memory_id)["state"] == "active"
    assert conn.execute("SELECT count(*) FROM memories").fetchone()[0] == 1
    assert not conn.in_transaction


def test_delete_blocks_late_use_and_update(conn):
    memory_id = capture(conn)
    run(conn, "r2")
    recall.delete_memory(conn, memory_id, expected_revision=1)
    result = recall.finish_memories(conn, run_id="r2", uses=[use(memory_id)], now=T0 + timedelta(days=3))
    assert result["errors"][0]["code"] == "not_found"
    with pytest.raises(recall.MemoryError) as err:
        recall.update_memory(conn, memory_id, expected_revision=1, note="Late edit.")
    assert err.value.code == "not_found"
    assert conn.execute("SELECT count(*) FROM memory_fts").fetchone()[0] == 0


def test_auto_excludes_superseded_before_candidate_limit(conn):
    wanted = capture(conn)
    for index in range(26):
        name = f"history{index}"
        run(conn, name)
        memory_id = capture(conn, current=name, source=name, note=f"SQLite transactions case {index}.")
        recall.update_memory(conn, memory_id, expected_revision=1, state="superseded")
    run(conn, "reader")
    result = recall.recall_memories(conn, query="SQLite transactions", automatic=True, current_run_id="reader")
    assert [memory["id"] for memory in result["memories"]] == [wanted]


def test_concurrent_reinforcement_only_once(conn, tmp_path):
    memory_id = capture(conn)
    run(conn, "r2")
    def reinforce(_):
        other = db.connect(tmp_path / "test.db")
        try:
            return recall.finish_memories(other, run_id="r2", uses=[use(memory_id)], now=T0 + timedelta(days=2))
        finally:
            other.close()
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(reinforce, range(2)))
    assert sorted(result["reinforcements"][0]["status"] for result in results) == ["reinforced", "skipped"]
    assert recall.get_memory(conn, memory_id)["half_life_days"] == 14
