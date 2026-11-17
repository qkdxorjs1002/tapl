from __future__ import annotations

import asyncio
import json
from unittest import mock

import pytest
from mcp import Client

from taplctl import config, config_editor, db, mcp_server, prompt, recall
from taplctl.application import WorkflowApplication, WorkflowApplicationError


@pytest.fixture
def app(tmp_path):
    (tmp_path / '.git').mkdir()
    db.initialize_workspace(tmp_path)
    (tmp_path / '.tapl/config.toml').write_text('[subagents]\nenabled=false\n')
    return WorkflowApplication(tmp_path)


def candidate(run_id, slot=1):
    return {'slot': slot, 'cue': ['sqlite', 'migration', 'transaction'],
            'note': 'Verify the migration transaction before deployment.', 'source_run_id': run_id}


def capture(app):
    run_id = app.summarize_run('SQLite migration')['active_run']['id']
    result = app.finish_run('Verified migration', expected_run_id=run_id,
                            memory_candidates=[candidate(run_id)])
    return result['memory']['captures'][0]['memory_id']


def test_optional_finish_keeps_old_result_and_returns_entry_errors(app):
    run_id = app.summarize_run('migration')['active_run']['id']
    assert app.finish_run('legacy completion')['memory']['status'] == 'review_required'
    result = app.finish_run('verified', expected_run_id=run_id,
                            memory_candidates=[candidate(run_id), {'slot': 2}])
    assert result['ok'] and result['active_run']['result_summary'] == 'verified'
    assert result['memory']['status'] == 'partial'
    assert len(result['memory']['captures']) == len(result['memory']['errors']) == 1


def test_expected_run_required_and_stale_retry_does_not_touch_next_run(app):
    split = app.split_run([
        {'key': 'first', 'summary': 'first', 'work_type': 'answer', 'workflow_mode': 'fast'},
        {'key': 'second', 'summary': 'second', 'work_type': 'answer', 'workflow_mode': 'fast'},
    ])
    first = split['active_run']['id']
    with pytest.raises(WorkflowApplicationError, match='expected_run_id'):
        app.finish_run('must not save', memory_candidates=[])
    assert not app.get_status()['active_run']['result_summary']
    app.finish_run('first done', expected_run_id=first, memory_review={'decision': 'skip', 'reason': 'No reusable lesson.'})
    app.finish_archive('first')
    second = app.get_status()['active_run']
    assert second['id'] != first
    with pytest.raises(WorkflowApplicationError, match='stale_run'):
        app.finish_run('stale overwrite', expected_run_id=first, memory_candidates=[])
    assert app.get_status()['active_run']['result_summary'] == second['result_summary']


def test_optional_memory_failure_does_not_fail_committed_result(app):
    run_id = app.summarize_run('migration')['active_run']['id']
    with mock.patch.object(recall, 'finish_memories', side_effect=RuntimeError('busy')):
        result = app.finish_run('committed', expected_run_id=run_id, memory_candidates=[])
    assert result['ok'] and result['memory']['status'] == 'failed'
    assert app.get_status()['active_run']['result_summary'] == 'committed'


def test_recall_runs_once_and_only_on_summarize(app):
    assert app.summarize_run('migration')['recall']['status'] == 'empty'
    assert app.summarize_run('migration again')['recall']['status'] == 'already_attempted'
    with mock.patch.object(recall, 'emit_recall_once', side_effect=AssertionError('unexpected recall')):
        app.get_status()
        app.get_next()
        app.get_context()
    with mock.patch.object(recall, 'emit_recall_once', side_effect=RuntimeError('busy')):
        result = app.summarize_run('saved despite recall error', recall_query='migration')
    assert result['ok'] and result['recall']['status'] == 'error'
    assert result['active_run']['request_summary'] == 'saved despite recall error'


@pytest.mark.parametrize('cue,query', [('연상 기억', '연상기억'), ('연상기억', '연상 기억')])
def test_korean_spacing_in_automatic_run_recall_and_manual_api(app, cue, query):
    run_id = app.summarize_run('검색 단서 저장', work_type='answer', workflow_mode='fast')['active_run']['id']
    memory = candidate(run_id)
    memory.update(cue=[cue, 'memory index', 'finish_run'], note='A verified spacing lesson.')
    result = app.finish_run('Verified', expected_run_id=run_id, memory_candidates=[memory])
    memory_id = result['memory']['captures'][0]['memory_id']
    app.finish_archive('spacing-source')
    result = app.summarize_run(query, work_type='answer', workflow_mode='fast')
    assert result['recall']['status'] == 'recalled'
    assert result['recall']['memories'][0]['id'] == memory_id
    assert result['recall']['memories'][0]['matched_cues'] == [cue]
    assert app.recall(query=query)['memories'][0]['id'] == memory_id


def test_disable_automatic_memory_keeps_manual_management(app):
    memory_id = capture(app)
    path = app.workspace_root / '.tapl/config.toml'
    config_editor.set_value(path, 'recall.enabled', 'false')
    with mock.patch.object(recall, 'emit_recall_once', side_effect=AssertionError('disabled')):
        result = app.summarize_run('new summary')
    assert result['recall']['status'] == 'disabled'
    finished = app.finish_run('done', expected_run_id=result['active_run']['id'], memory_uses=[])
    assert finished['memory']['status'] == 'disabled'
    assert app.recall(limit=50)['total'] == 1
    memory = app.get_memory(memory_id)['memory']
    assert memory['source_record']['run']['id'] == result['active_run']['id']
    updated = app.update_memory(memory_id, expected_revision=memory['revision'], note='Check SQLite migration atomicity before deployment.')
    assert updated['memory']['revision'] == memory['revision'] + 1
    deleted = app.delete_memory(memory_id, expected_revision=updated['memory']['revision'])
    assert deleted['memory']['state'] == 'deleted'
    assert app.recall()['total'] == 0
    config_editor.unset_value(path, 'recall.enabled')
    assert config.load(path).recall.enabled


def test_manual_revision_errors_surface(app):
    memory_id = capture(app)
    with pytest.raises(recall.MemoryError) as error:
        app.update_memory(memory_id, expected_revision=999, note='Do not overwrite.')
    assert error.value.code == 'conflict'
    assert app.get_memory(memory_id)['memory']['revision'] == 1


def test_config_boolean_validation_and_receipt_scope(app):
    assert config.from_mapping({}, path='unused').recall.enabled
    for value in ('false', 0, None):
        with pytest.raises(ValueError, match='recall.enabled'):
            config.from_mapping({'recall': {'enabled': value}}, path='unused')
    payload = {'ok': True, 'recall': {'status': 'empty', 'memories': []}, 'memory': {'status': 'ok'}}
    assert 'recall' in mcp_server.mcp_write_receipt(payload, operation='run_summarize')
    assert 'memory' in mcp_server.mcp_write_receipt(payload, operation='run_finish')
    assert set(mcp_server.mcp_write_receipt(payload, operation='task_start')) == {'ok', 'operation'}


def test_memory_mcp_schema_annotations_and_validation(app):
    server = mcp_server.create_server(workspace_root=app.workspace_root)
    tools = {tool.name: tool for tool in asyncio.run(server.list_tools())}
    assert tools['tapl_recall'].annotations.read_only_hint
    assert tools['tapl_get_memory'].annotations.read_only_hint
    merge = tools['tapl_merge_memory_cues']
    assert not merge.annotations.read_only_hint
    assert not merge.annotations.destructive_hint
    assert merge.annotations.idempotent_hint
    assert not merge.annotations.open_world_hint
    assert merge.input_schema['required'] == ['target_cue', 'cues']
    assert merge.input_schema['properties']['cues']['maxItems'] == 20
    assert app.get_status()['viewer_capabilities'] == {'associativeMemory': True, 'discardRun': True}
    for name in ('tapl_update_memory', 'tapl_delete_memory'):
        assert not tools[name].annotations.read_only_hint
        assert tools[name].annotations.destructive_hint
        assert 'explicit user request' in tools[name].description
    assert tools['tapl_finish_run'].input_schema['required'] == ['result']
    assert 'recall_query' in tools['tapl_summarize_run'].input_schema['properties']

    async def exercise():
        async with Client(server) as client:
            summarized = await client.call_tool('tapl_summarize_run', {'summary': 'sqlite migration', 'work_type': 'answer', 'workflow_mode': 'fast'})
            assert summarized.structured_content['recall']['status'] == 'empty'
            bad = await client.call_tool('tapl_finish_run', {'result': 'bad', 'memory_candidates': [{'slot': 3}]})
            assert bad.is_error
            missing_id = await client.call_tool('tapl_finish_run', {'result': 'bad', 'memory_candidates': []})
            assert missing_id.is_error
    asyncio.run(exercise())
    assert not app.get_status()['active_run']['result_summary']


def test_memory_policy_is_authoritative_not_hook_injection():
    policy = prompt.mcp_server_instructions()
    assert 'memory_candidates' not in prompt.CONTEXT_INJECTION_PROMPT_TEMPLATE
    assert '240 characters' in policy
    assert 'untrusted data' in policy
    assert 'explicit user instruction' in policy
    assert 'tapl_merge_memory_cues' in policy


def test_merge_catalog_is_local_only_and_does_not_create_run_or_edit_memories(app):
    memory_id = capture(app)
    app.finish_archive('catalog-source')
    with app._connection() as conn:
        original = [tuple(row) for row in conn.execute('SELECT * FROM memories')]
        original_fts = [tuple(row) for row in conn.execute('SELECT rowid,* FROM memory_fts')]
        run_count = conn.execute('SELECT count(*) FROM workflow_runs').fetchone()[0]
    peer = app.workspace_root / '.tapl/tapl-peer.db'
    db.connect(peer).close()
    peer_before = peer.read_bytes()
    with pytest.raises(WorkflowApplicationError, match='read-only'):
        app.merge_memory_cues('sqlite', ['migration'], source_db=peer.name)
    assert peer.read_bytes() == peer_before
    assert app.list_memory_cues()['total'] == 3
    merged = app.merge_memory_cues('sqlite', ['migration'], source_db=app.db_path.name)
    assert merged == {'ok': True, 'source_db': app.db_path.name, 'target_cue': 'sqlite',
                      'merged_cues': ['migration'], 'affected_memories': 1, 'status': 'merged'}
    assert app.list_memory_cues(query='migration')['cues'] == [{'cue': 'sqlite', 'usage_count': 1}]
    assert app.get_memory(memory_id)['memory']['cue'] == ['sqlite', 'migration', 'transaction']
    with app._connection() as conn:
        assert [tuple(row) for row in conn.execute('SELECT * FROM memories')] == original
        assert [tuple(row) for row in conn.execute('SELECT rowid,* FROM memory_fts')] == original_fts
        assert conn.execute('SELECT count(*) FROM workflow_runs').fetchone()[0] == run_count
    assert app.get_status()['active_run'] is None


def test_summarize_receipt_preserves_real_memory_source(app):
    memory_id = capture(app)
    original_run = app.get_memory(memory_id)['memory']['source']['run_id']
    archive = app.finish_archive('migration-memory')
    summarized = app.summarize_run('unrelated summary', recall_query='sqlite migration')
    receipt = mcp_server.mcp_write_receipt(summarized, operation='run_summarize')
    memory = receipt['recall']['memories'][0]
    assert memory['id'] == memory_id
    assert memory['source']['run_id'] == original_run
    assert memory['source']['archive_id'] == archive['archive']['id']
    assert 'result_summary' not in receipt['active_run']



def test_memory_mcp_detail_is_read_only_and_returns_current_source(app):
    memory_id = capture(app)
    server = mcp_server.create_server(workspace_root=app.workspace_root)
    before = app.get_memory(memory_id)['memory']

    async def read():
        async with Client(server) as client:
            first = await client.call_tool('tapl_get_memory', {'memory_id': memory_id})
            second = await client.call_tool('tapl_get_memory', {'memory_id': memory_id})
            missing = await client.call_tool('tapl_get_memory', {'memory_id': 'missing'})
            assert not first.is_error and not second.is_error
            for result in (first, second):
                memory = result.structured_content['memory']
                assert {k: v for k, v in memory.items() if k != 'strength'} == {k: v for k, v in before.items() if k != 'strength'}
                assert memory['strength'] <= before['strength']
            assert first.structured_content['memory']['source_record']['run']['result_summary'] == 'Verified migration'
            assert missing.structured_content['memory'] is None
    asyncio.run(read())
    after = app.get_memory(memory_id)['memory']
    assert {k: v for k, v in after.items() if k != 'strength'} == {k: v for k, v in before.items() if k != 'strength'}
    app.delete_memory(memory_id, expected_revision=before['revision'])

    async def read_deleted():
        async with Client(server) as client:
            result = await client.call_tool('tapl_get_memory', {'memory_id': memory_id})
            assert not result.is_error and result.structured_content['memory'] is None
    asyncio.run(read_deleted())


@pytest.mark.parametrize('explicit,expected_mode', [(None, 'summary'), ('', 'summary'), ('   ', 'explicit')])
def test_empty_recall_query_retains_summary_fallback_contract(app, explicit, expected_mode):
    with mock.patch.object(recall, 'emit_recall_once', return_value={'status': 'empty', 'memories': []}) as emit:
        app.summarize_run('sqlite migration', recall_query=explicit)
    assert emit.call_args.kwargs['selection_mode'] == expected_mode
    assert emit.call_args.kwargs['query'] == ('   ' if expected_mode == 'explicit' else 'sqlite migration')


def test_summary_fallback_keeps_first_eight_terms_and_finalizes_once(app):
    memory_id = capture(app)
    app.finish_archive('original')
    summary = 'Please help me with this work and the context. ' * 10 + ' SQLite migration'
    original = recall.finalize_automatic_recall
    with mock.patch.object(recall, 'finalize_automatic_recall', wraps=original) as finalize:
        result = app.summarize_run(summary)['recall']
    assert finalize.call_count == 1
    assert result['status'] == 'empty'
    assert result['memories'] == []
    assert result['query'] == 'please help me with this work and the'
    with app._connection() as conn:
        event = json.loads(conn.execute(
            "SELECT payload_json FROM events WHERE run_id=? AND event_type='memory_recall_attempted'",
            (app.get_status()['active_run']['id'],)).fetchone()[0])
    assert event['diagnostics']['selection_mode'] == 'summary'
    assert event['diagnostics']['query_truncated']
    assert 'Please help' not in json.dumps(event)


def test_explicit_recall_query_keeps_original_eight_token_boundary(app):
    memory_id = capture(app)
    app.finish_archive('original')
    explicit = 'one two three four five six seven eight sqlite migration'
    result = app.summarize_run('sqlite migration', recall_query=explicit)['recall']
    assert result['query'] == 'one two three four five six seven eight'
    assert result['memories'] == []
