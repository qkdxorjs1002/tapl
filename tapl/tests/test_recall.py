from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
import sqlite3

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


@pytest.mark.parametrize("change", [{"slot": True}, {"slot": 3}, {"cue": ["a", "b"]}, {"cue": ["a", "A", "b"]}, {"note": "x" * 241}, {"note": "One. Two. Three."}, {"source_item_id": True}, {"source_run_id": "missing"}])
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
    with pytest.raises(sqlite3.IntegrityError):
        capture(conn, current="r2", note="New note.", replaces_memory_id=memory_id)
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
