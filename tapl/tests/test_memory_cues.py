from concurrent.futures import ThreadPoolExecutor
import sqlite3
from unittest import mock

import pytest

from taplctl import db, memory_cues, recall
from test_recall import candidate, capture, conn, run


def legacy_database(tmp_path):
    path = tmp_path / 'legacy.db'
    connection = db.connect(path)
    run(connection, 'r1')
    capture(connection, cue=['연상 기억', 'SQLite  Transactions', 'ＡＰＩ'])
    connection.executescript("DROP TABLE memory_cue_aliases; DROP TABLE memory_cue_links; DROP TABLE memory_cues; UPDATE meta SET value='14' WHERE key='schema_version';")
    return path, connection


def snapshot(connection):
    return ([tuple(r) for r in connection.execute('SELECT * FROM memories ORDER BY id')],
            [tuple(r) for r in connection.execute('SELECT rowid,* FROM memory_fts ORDER BY rowid')])


def test_migration_preserves_memory_and_wal_backup(tmp_path):
    path, old = legacy_database(tmp_path)
    before = snapshot(old)
    with db.connect_readonly(path) as reader:
        assert memory_cues.list_cues(reader, query='연상기억')['cues'] == [{'cue': '연상 기억', 'usage_count': 1}]
        assert not memory_cues._has_catalog(reader)
    migrated = db.connect(path)
    assert snapshot(migrated) == before
    assert memory_cues.list_cues(migrated)['total'] == 3
    assert memory_cues.resolve_existing(migrated, [' api ', 'sqlite transactions']) == ['API', 'SQLite Transactions']
    backup = sqlite3.connect(str(path) + '.pre-v15.bak')
    assert backup.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0] == '14'
    assert backup.execute('SELECT count(*) FROM memories').fetchone()[0] == 1
    backup.close()
    stamp = (path.parent / (path.name + '.pre-v15.bak')).stat().st_mtime_ns
    migrated.close()
    old.close()
    for _ in range(2):
        reopened = db.connect(path)
        assert reopened.execute('SELECT count(*) FROM memory_cue_links').fetchone()[0] == 3
        assert snapshot(reopened) == before
        reopened.close()
    assert (path.parent / (path.name + '.pre-v15.bak')).stat().st_mtime_ns == stamp


def test_migration_failure_rolls_back_catalog_and_version(tmp_path):
    path, old = legacy_database(tmp_path)
    before = snapshot(old)
    original = memory_cues.ensure_catalog
    def fail(connection, **kwargs):
        original(connection, **kwargs)
        raise RuntimeError('simulated migration failure')
    with mock.patch.object(memory_cues, 'ensure_catalog', side_effect=fail), pytest.raises(RuntimeError):
        db.connect(path)
    assert snapshot(old) == before
    assert db.get_meta(old)['schema_version'] == '14'
    assert not memory_cues._has_catalog(old)
    old.close()


def test_concurrent_migration_is_idempotent(tmp_path):
    path, old = legacy_database(tmp_path)
    old.close()
    def migrate(_):
        connection = db.connect(path)
        result = memory_cues.list_cues(connection)
        connection.close()
        return result
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(migrate, range(2)))
    assert results[0] == results[1]
    assert results[0]['total'] == 3


def test_catalog_normalization_suggestions_paging_and_retention(conn):
    memory_id = capture(conn)
    row_id = conn.execute('SELECT id FROM memories WHERE memory_id=?', (memory_id,)).fetchone()[0]
    with conn:
        labels = memory_cues.bind_cues(conn, row_id, ['Asset  ID', '자산 목록', 'literal%_value'])
    assert labels == ['Asset ID', '자산 목록', 'literal%_value']
    assert memory_cues.resolve_existing(conn, ['asset id', '자산목록', '새 개념']) == ['Asset ID', '자산목록', '새 개념']
    assert memory_cues.list_cues(conn, query='자산목록')['cues'] == [{'cue': '자산 목록', 'usage_count': 1}]
    assert memory_cues.list_cues(conn, query='%_')['total'] == 1
    assert memory_cues.list_cues(conn, limit=1, offset=1)['cues']
    with conn:
        memory_cues.bind_cues(conn, row_id, [])
    assert all(c['usage_count'] == 0 for c in memory_cues.list_cues(conn)['cues'])


@pytest.mark.parametrize('kwargs', [{'limit': 0}, {'limit': 51}, {'limit': True}, {'offset': -1}, {'query': 'x'*201}])
def test_catalog_validates_arguments(conn, kwargs):
    with pytest.raises(ValueError):
        memory_cues.list_cues(conn, **kwargs)


def test_capture_reuses_labels_and_registers_only_new_concepts(conn):
    first = capture(conn, cue=['Asset  ID', '자산 목록', 'Inventory'])
    run(conn, 'r2')
    second = capture(conn, current='r2', source='r2', note='Another verified result.',
                     cue=['asset id', '자산 목록', 'New concept'])
    from taplctl import recall
    assert recall.get_memory(conn, first)['cue'] == ['Asset ID', '자산 목록', 'Inventory']
    assert recall.get_memory(conn, second)['cue'] == ['Asset ID', '자산 목록', 'New concept']
    assert memory_cues.list_cues(conn, query='assetid')['cues'] == [{'cue': 'Asset ID', 'usage_count': 2}]
    assert memory_cues.list_cues(conn)['total'] == 4


def test_failed_capture_retry_dedup_and_stale_edit_leave_catalog_unchanged(conn):
    from taplctl import recall
    first = capture(conn)
    baseline = memory_cues.list_cues(conn)
    run(conn, 'r2')
    failed = recall.finish_memories(conn, run_id='r2', candidates=[candidate(source='missing', cue=['Unused one', 'Unused two', 'Unused three'])])
    assert failed['errors']
    assert memory_cues.list_cues(conn) == baseline
    repeated = recall.finish_memories(conn, run_id='r2', candidates=[candidate(source='r1')])
    assert repeated['captures'][0]['status'] == 'deduplicated'
    assert memory_cues.list_cues(conn) == baseline
    assert recall.finish_memories(conn, run_id='r2', candidates=[candidate(source='r1')])['captures'][0]['status'] == 'already_captured'
    with pytest.raises(recall.MemoryError):
        recall.update_memory(conn, first, expected_revision=2, cue=['Unused one', 'Unused two', 'Unused three'])
    assert memory_cues.list_cues(conn) == baseline
    run(conn, 'r3')
    original = memory_cues.bind_cues
    def fail(connection, *args):
        original(connection, *args)
        raise recall.MemoryError('simulated bind failure')
    with mock.patch.object(memory_cues, 'bind_cues', side_effect=fail):
        result = recall.finish_memories(conn, run_id='r3', candidates=[candidate(source='r3', cue=['Unused one', 'Unused two', 'Unused three'])])
    assert result['errors']
    assert memory_cues.list_cues(conn) == baseline
    assert conn.execute('SELECT count(*) FROM memories').fetchone()[0] == 1
    assert conn.execute('SELECT count(*) FROM memory_fts').fetchone()[0] == 1


def test_edit_delete_cascade_and_note_only_legacy_preservation(conn):
    from taplctl import recall
    first = capture(conn)
    conn.execute('UPDATE memories SET cues_json=? WHERE memory_id=?', ('["SQLite  transactions", "atomic updates", "storage safety"]', first))
    conn.commit()
    result = recall.update_memory(conn, first, expected_revision=1, note='Updated verified note.')
    assert result['cue'][0] == 'SQLite  transactions'
    result = recall.update_memory(conn, first, expected_revision=2, cue=['sqlite transactions', 'new cue', 'new concept'])
    assert result['cue'][0] == 'SQLite transactions'
    recall.delete_memory(conn, first, expected_revision=3)
    assert conn.execute('SELECT count(*) FROM memory_cue_links').fetchone()[0] == 0
    assert memory_cues.list_cues(conn)['total'] == 5
    assert all(row['usage_count'] == 0 for row in memory_cues.list_cues(conn)['cues'])
    run(conn, 'r2')
    capture(conn, current='r2', source='r2', note='A second verified note.')
    conn.execute("DELETE FROM workflow_runs WHERE id='r2'")
    conn.commit()
    assert conn.execute('SELECT count(*) FROM memory_cue_links').fetchone()[0] == 0
    assert memory_cues.list_cues(conn)['total'] == 5


def catalog_snapshot(connection):
    return {table: [tuple(r) for r in connection.execute(f'SELECT * FROM {table} ORDER BY 1,2')]
            for table in ('memory_cues', 'memory_cue_aliases', 'memory_cue_links')}


def test_merge_overlap_chains_aliases_and_idempotence_preserve_originals(conn):
    first = capture(conn, cue=['Asset inventory', 'Inventory', 'first source'])
    run(conn, 'r2')
    second = capture(conn, current='r2', source='r2', note='A second inventory lesson.',
                     cue=['Asset registry', 'Asset inventory', 'second source'])
    before = snapshot(conn)
    result = recall.merge_memory_cues(conn, target_cue=' inventory ', cues=['Asset inventory'])
    assert result == {'target_cue': 'Inventory', 'merged_cues': ['Asset inventory'],
                      'affected_memories': 2, 'status': 'merged'}
    assert snapshot(conn) == before
    assert memory_cues.list_cues(conn, query='Assetinventory')['cues'] == [{'cue': 'Inventory', 'usage_count': 2}]
    positions = conn.execute("""SELECT m.memory_id,l.position FROM memory_cue_links l
        JOIN memories m ON m.id=l.memory_row_id JOIN memory_cues c ON c.id=l.cue_id
        WHERE c.cue='Inventory' ORDER BY m.memory_id""").fetchall()
    assert dict(positions) == {first: 0, second: 1}
    result = recall.merge_memory_cues(conn, target_cue='Asset registry', cues=['asset INVENTORY', 'Inventory'])
    assert result == {'target_cue': 'Asset registry', 'merged_cues': ['Inventory'],
                      'affected_memories': 2, 'status': 'merged'}
    assert memory_cues.resolve_existing(conn, ['asset inventory', 'Inventory', 'asset registry']) == ['Asset registry'] * 3
    assert conn.execute('SELECT count(DISTINCT cue_id) FROM memory_cue_aliases').fetchone()[0] == 1
    assert memory_cues.list_cues(conn, query='Inventory')['cues'] == [{'cue': 'Asset registry', 'usage_count': 2}]
    assert memory_cues.list_cues(conn)['total'] == 3
    after = catalog_snapshot(conn)
    assert recall.merge_memory_cues(conn, target_cue='Asset inventory', cues=['Inventory', 'Asset registry']) == {
        'target_cue': 'Asset registry', 'merged_cues': [], 'affected_memories': 0, 'status': 'unchanged'}
    assert catalog_snapshot(conn) == after
    assert snapshot(conn) == before
    assert [tuple(r) for r in conn.execute("""SELECT l.position FROM memory_cue_links l
        JOIN memory_cues c ON c.id=l.cue_id WHERE c.cue='Asset registry'""")] == [(0,), (0,)]
    # Rebinding historical labels must resolve aliases instead of recreating them.
    row_id = conn.execute('SELECT id FROM memories WHERE memory_id=?', (first,)).fetchone()[0]
    with conn:
        assert memory_cues.bind_cues(conn, row_id, ['Asset inventory', 'Inventory', 'first source']) == [
            'Asset registry', 'Asset registry', 'first source']
    assert memory_cues.list_cues(conn)['total'] == 3
    assert snapshot(conn) == before


@pytest.mark.parametrize('target,cues', [
    ('missing', ['atomic updates']), ('SQLite transactions', ['atomic updates', 'missing']),
    ('SQLite transactions', []), ('SQLite transactions', ['atomic updates'] * 21),
    ('SQLite transactions', 'atomic updates'), ('SQLite transactions', ['']),
    ('SQLite transactions', [None]), ('SQLite transactions', ['x' * 81]),
    ('', ['atomic updates']), (None, ['atomic updates']),
])
def test_merge_invalid_inputs_are_atomic(conn, target, cues):
    capture(conn)
    before, catalog_before = snapshot(conn), catalog_snapshot(conn)
    with pytest.raises(recall.MemoryError) as error:
        recall.merge_memory_cues(conn, target_cue=target, cues=cues)
    assert error.value.code == 'invalid'
    assert snapshot(conn) == before
    assert catalog_snapshot(conn) == catalog_before


def test_merge_database_failure_rolls_back_links_and_aliases(conn):
    capture(conn)
    before = catalog_snapshot(conn)
    conn.execute("""CREATE TEMP TRIGGER fail_alias BEFORE INSERT ON memory_cue_aliases
        BEGIN SELECT RAISE(ABORT,'simulated alias failure'); END""")
    with pytest.raises(sqlite3.IntegrityError, match='simulated alias failure'):
        recall.merge_memory_cues(conn, target_cue='SQLite transactions', cues=['atomic updates'])
    assert catalog_snapshot(conn) == before


def seed_alias(conn):
    first = capture(conn, cue=['Inventory', 'first source', 'first topic'])
    run(conn, 'r2')
    capture(conn, current='r2', source='r2', note='Another vocabulary source.',
            cue=['Asset inventory', 'second source', 'second topic'])
    recall.merge_memory_cues(conn, target_cue='Inventory', cues=['Asset inventory'])
    return first


def test_capture_and_edit_alias_collapses_fail_before_any_writes(conn):
    first = seed_alias(conn)
    run(conn, 'r3')
    before, catalog_before = snapshot(conn), catalog_snapshot(conn)
    cues = ['Inventory', 'Asset inventory', 'unused concept']
    result = recall.finish_memories(conn, run_id='r3', candidates=[candidate(source='r3', cue=cues)])
    assert result['errors'][0]['code'] == 'invalid'
    with pytest.raises(recall.MemoryError, match='distinct'):
        recall.update_memory(conn, first, expected_revision=1, cue=cues)
    assert snapshot(conn) == before
    assert catalog_snapshot(conn) == catalog_before
    assert conn.execute("SELECT count(*) FROM events WHERE run_id='r3' AND event_type='memory_capture'").fetchone()[0] == 0


def test_alias_storage_canonical_retry_dedup_and_deleted_fingerprints(conn):
    first = seed_alias(conn)
    run(conn, 'r3')
    alias_cues = ['Asset inventory', 'new source', 'new topic']
    canonical_cues = ['Inventory', 'new source', 'new topic']
    new = capture(conn, current='r3', source='r3', note='A new verified lesson.', cue=alias_cues)
    assert recall.get_memory(conn, new)['cue'] == canonical_cues
    assert recall.finish_memories(conn, run_id='r3', candidates=[candidate(
        source='r3', note='A new verified lesson.', cue=canonical_cues)])['captures'][0]['status'] == 'already_captured'
    run(conn, 'r4')
    result = recall.finish_memories(conn, run_id='r4', candidates=[candidate(
        source='r3', note='A new verified lesson.', cue=alias_cues)])
    assert result['captures'] == [{'slot': 1, 'memory_id': new, 'status': 'deduplicated'}]
    recall.delete_memory(conn, new, expected_revision=1)
    before, catalog_before = snapshot(conn), catalog_snapshot(conn)
    with pytest.raises(recall.MemoryError) as error:
        recall.update_memory(conn, first, expected_revision=1, note='A new verified lesson.', cue=alias_cues)
    assert error.value.code == 'conflict'
    assert snapshot(conn) == before and catalog_snapshot(conn) == catalog_before
    run(conn, 'r5')
    result = recall.finish_memories(conn, run_id='r5', candidates=[candidate(
        source='r3', note='A new verified lesson.', cue=alias_cues)])
    assert result['captures'] == [{'slot': 1, 'memory_id': new, 'status': 'deduplicated'}]
    assert snapshot(conn) == before and catalog_snapshot(conn) == catalog_before


def test_catalog_usage_ignores_deleted_rows_and_deduplicates_alias_matches(conn):
    first = seed_alias(conn)
    conn.execute("UPDATE memories SET state='deleted' WHERE memory_id=?", (first,))
    conn.commit()
    assert memory_cues.list_cues(conn, query='inventory')['cues'] == [{'cue': 'Inventory', 'usage_count': 1}]


def test_note_only_edit_keeps_historical_alias_cues_and_links(conn):
    cues = ['Inventory', 'Asset inventory', 'Original']
    memory_id = capture(conn, cue=cues)
    recall.merge_memory_cues(conn, target_cue='Inventory', cues=['Asset inventory'])
    before = catalog_snapshot(conn)
    note = 'An updated verified note with historical vocabulary.'
    updated = recall.update_memory(conn, memory_id, expected_revision=1, note=note)
    assert updated['cue'] == cues
    assert conn.execute('SELECT fingerprint FROM memories WHERE memory_id=?', (memory_id,)).fetchone()[0] == recall._content(note, cues)[2]
    assert catalog_snapshot(conn) == before
    with pytest.raises(recall.MemoryError, match='distinct'):
        recall.update_memory(conn, memory_id, expected_revision=2, cue=cues)
    assert recall.get_memory(conn, memory_id)['revision'] == 2
    assert catalog_snapshot(conn) == before


def test_reopen_keeps_aliases_and_does_not_backfill_absorbed_labels(conn):
    seed_alias(conn)
    before, catalog_before = snapshot(conn), catalog_snapshot(conn)
    path = conn.execute('PRAGMA database_list').fetchone()['file']
    reopened = db.connect(path)
    try:
        assert catalog_snapshot(reopened) == catalog_before
        assert snapshot(reopened) == before
        assert memory_cues.resolve_existing(reopened, ['Asset inventory']) == ['Inventory']
    finally:
        reopened.close()


@pytest.mark.parametrize('collapse', [False, True])
@pytest.mark.parametrize('legacy_receipt', [False, True])
def test_successful_capture_retry_survives_later_merges(conn, collapse, legacy_receipt):
    cues = ['Old label', 'Representative' if collapse else 'First topic', 'Original']
    memory_id = capture(conn, cue=cues)
    second = recall.finish_memories(conn, run_id='r1', candidates=[candidate(
        slot=2, cue=['Representative', 'Second topic', 'Second source'], note='Another verified source.')])
    assert not second['errors']
    if legacy_receipt:
        conn.execute("""UPDATE events SET payload_json=json_remove(payload_json,'$.request_hash')
            WHERE event_type='memory_capture'""")
        conn.commit()
    before = snapshot(conn)
    receipts = [tuple(r) for r in conn.execute("SELECT * FROM events WHERE event_type='memory_capture' ORDER BY id")]
    recall.merge_memory_cues(conn, target_cue='Representative', cues=['Old label'])
    assert [tuple(r) for r in conn.execute("SELECT * FROM events WHERE event_type='memory_capture' ORDER BY id")] == receipts
    repeated = recall.finish_memories(conn, run_id='r1', candidates=[candidate(cue=cues)])
    assert repeated['captures'] == [{'slot': 1, 'memory_id': memory_id, 'status': 'already_captured'}]
    different = recall.finish_memories(conn, run_id='r1', candidates=[candidate(cue=cues, note='A different request.')])
    assert different['errors'] and not different['captures']
    assert snapshot(conn) == before
    assert [tuple(r) for r in conn.execute("SELECT * FROM events WHERE event_type='memory_capture' ORDER BY id")] == receipts


def test_alias_exact_and_spacing_matches_rank_before_high_usage_fragments(conn):
    capture(conn, cue=['Z canonical', 'alias exact', 'first source'])
    recall.merge_memory_cues(conn, target_cue='Z canonical', cues=['alias exact'])
    run(conn, 'r2')
    capture(conn, current='r2', source='r2', cue=['Y canonical', 'aliasexact', 'second source'])
    recall.merge_memory_cues(conn, target_cue='Y canonical', cues=['aliasexact'])
    for index in range(2):
        run_id = f'r{index + 3}'
        run(conn, run_id)
        capture(conn, current=run_id, source=run_id, note=f'A fragment lesson {index}.',
                cue=['alias exact expanded', 'aliasexact joined', 'fragment source'])
    assert memory_cues.list_cues(conn, query='alias exact')['cues'] == [
        {'cue': 'Z canonical', 'usage_count': 1}, {'cue': 'Y canonical', 'usage_count': 1},
        {'cue': 'alias exact expanded', 'usage_count': 2}, {'cue': 'aliasexact joined', 'usage_count': 2}]
