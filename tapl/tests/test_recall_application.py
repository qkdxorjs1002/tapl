from __future__ import annotations

import asyncio
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
    assert 'memory' not in app.finish_run('legacy completion')
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
    app.finish_run('first done')
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
    assert result['ok'] and result['memory']['status'] == 'error'
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


def test_archive_race_after_result_commit_skips_memory_and_keeps_bound_run(app):
    first = app.summarize_run('first', work_type='answer', workflow_mode='fast')['active_run']['id']
    original_update = db.update_active_run_summary

    def archive_after_commit(conn, **kwargs):
        saved = original_update(conn, **kwargs)
        app.finish_archive('raced-finish')
        return saved

    with mock.patch.object(db, 'update_active_run_summary', side_effect=archive_after_commit):
        result = app.finish_run('saved before archive', expected_run_id=first, memory_candidates=[candidate(first)])
    assert result['ok'] and result['active_run']['id'] == first
    assert result['active_run']['result_summary'] == 'saved before archive'
    assert result['memory']['status'] == 'stale_run'
    assert app.recall()['total'] == 0
