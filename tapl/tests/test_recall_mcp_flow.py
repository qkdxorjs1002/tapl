"""Exercise retained automatic hints through actual MCP reads and use projection."""
from __future__ import annotations

import asyncio
from contextlib import closing
import json

from mcp import Client

from taplctl import db, mcp_server, recall
from taplctl.application import WorkflowApplication


def test_three_intact_hints_open_and_use_exact_sources_once_through_mcp(tmp_path):
    (tmp_path / '.git').mkdir()
    db.initialize_workspace(tmp_path)
    (tmp_path / '.tapl/config.toml').write_text('[subagents]\nenabled=false\n')
    owner = 'recall-wire-test'
    app = WorkflowApplication(tmp_path, session_id=owner)
    originals = {}
    for index in range(3):
        source = app.summarize_run(f'Migration source {index}', work_type='analysis', workflow_mode='standard')['active_run']['id']
        with closing(db.connect(app.db_path, session_id=owner)) as conn:
            item = db.upsert_item(conn, kind='finding', stable_id='FINDING-001',
                                  title=f'Migration original {index}', body='Verified source evidence.', status='Resolved')
        note = ('한글원문보존' * 40)[:239] + str(index)
        captured = app.finish_run('Verified migration evidence.', expected_run_id=source, memory_candidates=[{
            'slot': 1, 'cue': ['sqlite migration', 'transaction boundary', f'original case {index}'],
            'note': note, 'source_run_id': source, 'source_item_id': item['id'],
        }])
        memory_id = captured['memory']['captures'][0]['memory_id']
        originals[memory_id] = {'note': note, 'run_id': source, 'item_id': item['id']}
        app.finish_archive(f'migration-source-{index}')
    server = mcp_server.create_server(workspace_root=tmp_path)

    async def exercise():
        async with Client(server) as client:
            result = await client.call_tool('tapl_summarize_run', {
                'session_id': owner, 'summary': 'Inspect the migration transaction boundary.',
                'work_type': 'answer', 'workflow_mode': 'fast', 'recall_query': 'sqlite migration',
            })
            assert not result.is_error
            payload = result.structured_content
            block = payload['recall']
            assert len(block['memories']) == 3
            assert len(json.dumps(block, ensure_ascii=False).encode()) <= recall.AUTOMATIC_RECALL_MAX_BYTES
            refs = []
            for memory in block['memories']:
                original = originals[memory['id']]
                assert memory['note'] == original['note'] and len(memory['note']) == 240
                assert memory['source']['item_id'] == original['item_id']
                assert memory['source']['run_id'] == original['run_id']
                assert 'source_db' not in memory['source'] and 'archive_id' not in memory['source']
                opened = await client.call_tool('tapl_get_item', {
                    'session_id': owner, 'item_id': original['item_id'],
                    'source_db': memory['source_db'], 'compact': True,
                })
                assert not opened.is_error
                refs.append({'kind': 'memory', 'target_type': 'memory', 'memory_id': memory['id'],
                             'source_db': memory['source_db'], 'usage': 'Applied its verified migration transaction boundary.'})
            args = {'session_id': owner, 'expected_run_id': payload['active_run']['id'], 'references': refs}
            used = await client.call_tool('tapl_use_references', args)
            assert not used.is_error
            before = app.get_status()['references']
            assert len(before) == 6 and all(ref['stage'] == 'used' for ref in before)
            repeated = await client.call_tool('tapl_use_references', args)
            assert not repeated.is_error
            assert app.get_status()['references'] == before
            again = await client.call_tool('tapl_summarize_run', {
                'session_id': owner, 'summary': 'The same run continues.',
                'work_type': 'answer', 'workflow_mode': 'fast', 'recall_query': 'sqlite migration',
            })
            assert again.structured_content['recall'] == {'status': 'already_attempted', 'memories': []}

    asyncio.run(exercise())


def test_catalog_selection_then_capture_through_mcp(tmp_path):
    (tmp_path / '.git').mkdir()
    db.initialize_workspace(tmp_path)
    (tmp_path / '.tapl/config.toml').write_text('[subagents]\nenabled=false\n')
    owner = 'catalog-wire-test'
    app = WorkflowApplication(tmp_path, session_id=owner)
    source = app.summarize_run('Inventory source')['active_run']['id']
    app.finish_run('Verified inventory.', expected_run_id=source, memory_candidates=[{
        'slot': 1, 'cue': ['자산 목록', 'Asset ID', 'inventory'], 'note': 'Verify inventory identifiers.', 'source_run_id': source,
    }])
    app.finish_archive('inventory-source')
    server = mcp_server.create_server(workspace_root=tmp_path)

    async def exercise():
        async with Client(server) as client:
            result = await client.call_tool('tapl_summarize_run', {'session_id': owner, 'summary': 'A new inventory task', 'work_type': 'answer', 'workflow_mode': 'fast', 'recall_query': 'unmatched'})
            run_id = result.structured_content['active_run']['id']
            before = app.get_status()['references']
            listed = await client.call_tool('tapl_list_memory_cues', {'session_id': owner, 'query': '자산목록'})
            assert not listed.is_error
            payload = listed.structured_content
            assert payload['source_db'] == app.db_path.name
            assert payload['cues'] == [{'cue': '자산 목록', 'usage_count': 1}]
            assert app.get_status()['references'] == before
            assert 'note' not in json.dumps(payload) and 'memory_id' not in json.dumps(payload)
            selected = payload['cues'][0]['cue']
            captured = await client.call_tool('tapl_finish_run', {
                'session_id': owner, 'result': 'Verified a second inventory procedure.', 'expected_run_id': run_id,
                'memory_candidates': [{'slot': 1, 'cue': [selected, 'asset id', 'new inventory concept'],
                                       'note': 'Reuse the inventory vocabulary for identifiers.', 'source_run_id': run_id}],
            })
            assert not captured.is_error
            memory_id = captured.structured_content['memory']['captures'][0]['memory_id']
            opened = await client.call_tool('tapl_get_memory', {'session_id': owner, 'memory_id': memory_id})
            assert opened.structured_content['memory']['cue'] == ['자산 목록', 'Asset ID', 'new inventory concept']
            again = await client.call_tool('tapl_list_memory_cues', {'session_id': owner, 'query': '자산목록'})
            assert again.structured_content['cues'] == [{'cue': selected, 'usage_count': 2}]
    asyncio.run(exercise())


def test_merge_catalog_and_store_aliases_through_session_gated_mcp(tmp_path):
    (tmp_path / '.git').mkdir()
    db.initialize_workspace(tmp_path)
    (tmp_path / '.tapl/config.toml').write_text('[subagents]\nenabled=false\n')
    owner = 'merge-wire-test'
    app = WorkflowApplication(tmp_path, session_id=owner)
    source = app.summarize_run('Inventory vocabulary')['active_run']['id']
    seeded = app.finish_run('Verified vocabulary.', expected_run_id=source, memory_candidates=[{
        'slot': 1, 'cue': ['Inventory', 'Asset inventory', 'Original'],
        'note': 'A verified inventory lesson.', 'source_run_id': source,
    }])
    memory_id = seeded['memory']['captures'][0]['memory_id']
    app.finish_archive('vocabulary-source')
    peer = tmp_path / '.tapl/tapl-peer.db'
    db.connect(peer).close()
    peer_before = peer.read_bytes()
    server = mcp_server.create_server(workspace_root=tmp_path)

    async def exercise():
        async with Client(server) as client:
            args = {'target_cue': 'Inventory', 'cues': ['Asset inventory']}
            assert (await client.call_tool('tapl_merge_memory_cues', args)).is_error
            foreign = await client.call_tool('tapl_merge_memory_cues', {
                **args, 'source_db': peer.name, 'session_id': owner})
            assert foreign.is_error and peer.read_bytes() == peer_before
            for cues in ([], ['missing'], ['Asset inventory', 'missing'], [1]):
                assert (await client.call_tool('tapl_merge_memory_cues', {
                    **args, 'cues': cues, 'session_id': owner})).is_error
            listed = await client.call_tool('tapl_list_memory_cues', {'session_id': owner, 'query': 'inventory'})
            assert len(listed.structured_content['cues']) == 2
            merged = await client.call_tool('tapl_merge_memory_cues', {**args, 'session_id': owner})
            assert not merged.is_error
            assert merged.structured_content == {'ok': True, 'session_id': owner, 'source_db': app.db_path.name,
                'target_cue': 'Inventory', 'merged_cues': ['Asset inventory'], 'affected_memories': 1, 'status': 'merged'}
            repeated = await client.call_tool('tapl_merge_memory_cues', {
                'session_id': owner, 'target_cue': 'Asset inventory', 'cues': ['Inventory']})
            assert repeated.structured_content['status'] == 'unchanged'
            assert repeated.structured_content['merged_cues'] == []
            assert app.get_status()['active_run'] is None
            opened = await client.call_tool('tapl_get_memory', {'session_id': owner, 'memory_id': memory_id})
            assert opened.structured_content['memory']['cue'] == ['Inventory', 'Asset inventory', 'Original']
            listed = await client.call_tool('tapl_list_memory_cues', {'session_id': owner, 'query': 'Assetinventory'})
            assert listed.structured_content['cues'] == [{'cue': 'Inventory', 'usage_count': 1}]
            new = await client.call_tool('tapl_summarize_run', {
                'session_id': owner, 'summary': 'Store a new inventory lesson', 'work_type': 'answer', 'workflow_mode': 'fast'})
            run_id = new.structured_content['active_run']['id']
            memory = {'slot': 1, 'cue': ['Inventory', 'Asset inventory', 'Unused'],
                      'note': 'A second verified inventory lesson.', 'source_run_id': run_id}
            failed = await client.call_tool('tapl_finish_run', {'session_id': owner, 'result': 'Verified.',
                'expected_run_id': run_id, 'memory_candidates': [memory]})
            assert failed.structured_content['memory']['errors'][0]['code'] == 'invalid'
            assert app.list_memory_cues(query='Unused')['total'] == 0
            memory['cue'] = ['Asset inventory', 'Original', 'New topic']
            captured = await client.call_tool('tapl_finish_run', {'session_id': owner, 'result': 'Verified.',
                'expected_run_id': run_id, 'memory_candidates': [memory]})
            assert not captured.is_error
            new_id = captured.structured_content['memory']['captures'][0]['memory_id']
            assert app.get_memory(new_id)['memory']['cue'] == ['Inventory', 'Original', 'New topic']
            edited = await client.call_tool('tapl_update_memory', {'session_id': owner, 'memory_id': new_id,
                'expected_revision': 1, 'cue': ['Asset inventory', 'Original', 'Updated topic']})
            assert edited.structured_content['memory']['cue'] == ['Inventory', 'Original', 'Updated topic']
            invalid_edit = await client.call_tool('tapl_update_memory', {'session_id': owner, 'memory_id': new_id,
                'expected_revision': 2, 'cue': ['Asset inventory', 'Inventory', 'Unused']})
            assert invalid_edit.is_error
            assert app.get_memory(new_id)['memory']['revision'] == 2
    asyncio.run(exercise())
