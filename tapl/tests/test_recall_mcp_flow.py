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
