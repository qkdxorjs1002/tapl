"""Seed an isolated workspace and serve the repository's current Viewer assets."""
from __future__ import annotations

import argparse
from contextlib import closing
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'tapl'))
from taplctl import db, recall, viewer


def seed(workspace: Path) -> None:
    path = workspace / '.tapl' / 'tapl.db'
    path.parent.mkdir(parents=True, exist_ok=True)
    # Settings UI tests must never fall through to the developer's user config.
    config_path = path.parent / 'config.toml'
    if not config_path.exists():
        config_path.write_text('# Isolated Viewer fixture\n[search]\nmax_results = 12\n\n[custom]\nkeep = "fixture"\n', encoding='utf-8')
    if path.exists():
        return
    with closing(db.connect(path)) as conn:
        db.ensure_active_run(conn, request_summary='Archived design', work_type='analysis', workflow_mode='standard')
        original = db.upsert_item(conn, kind='finding', stable_id='FINDING-001', title='Archived contrast finding', body='Original archived record', status='Resolved')
        db.update_active_run_summary(conn, result_summary='Verified archived interface evidence')
        recall.finish_memories(conn, run_id=original['run_id'], candidates=[
            {'slot': 1, 'cue': ['contrast review', 'original finding', 'interface evidence'], 'note': 'Check the original contrast finding before selecting status colors.', 'source_run_id': original['run_id'], 'source_item_id': original['id']},
            {'slot': 2, 'cue': ['archived design', 'source run', 'interface evidence'], 'note': 'Read the original RUN to retain the design decision context.', 'source_run_id': original['run_id']},
        ])
        db.archive_active_run(conn, slug='archived-design', memory_review_enabled=False)
        db.ensure_active_run(conn, request_summary='Viewer redesign', work_type='implementation', workflow_mode='strict')
        for index in range(1, 4):
            db.upsert_plan(conn, plan_id=f'PLAN-{index:03}', title=f'Interface plan {index}', objective='A concise overview of the proposed interface.', requirements_trace='Readable details and preserved source identity.', selected_approach='Use a shared reading layout.', validation='Verify the original record and both Viewer hosts.', status='Finalized')
        conn.execute("UPDATE items SET body = body || ? WHERE stable_id = 'PLAN-001' AND kind = 'plan'", ('\n\nLegacy PLAN body repeats the structured fields.',))
        for index in range(1, 25):
            state = ['Pending', 'In Progress', 'Blocked', 'Completed'][index % 4]
            db.upsert_task(conn, task_id=f'TASK-{index:03}', title=f'Interface task {index}', spec_id='PLAN-001', goal=f'Make interface task {index} readable.', action='Keep the actual data and source context.', verification='Check both locales and responsive layouts.', result='Verified interface output.' if state == 'Completed' else '', blocker='Waiting for source verification.' if state == 'Blocked' else '', next_action='Read the original record.' if state == 'Blocked' else '', custom_fields={'owner': 'Design team', 'zero': 0, 'enabled': False, 'optional': None, 'nested': {'values': [0, False, None]}}, status=state)
        db.upsert_task(conn, task_id='TASK-001', title='Interface task 1', spec_id='PLAN-001', goal='Make interface task 1 readable.', action='\n'.join(['Keep the actual data and source context.'] * 12), verification='Check both locales and responsive layouts.', depends_on=['TASK-004'], custom_fields={'owner': 'Design team', 'zero': 0, 'enabled': False, 'optional': None, 'nested': {'values': [0, False, None]}}, status='In Progress')
        db.upsert_item(conn, kind='finding', stable_id='FINDING-001', title='Readable contrast', body='## Observation\nCurrent interface finding.\n\n```html\n<script>window.untrusted = true</script>\n```', status='Open')
        for index, event in enumerate(['SessionStart', 'PreToolUse', 'PostToolUse']):
            db.record_event(conn, event_type=event, tool_name='tapl_get_next', mode='strict', message=('Review actual source context. ' * (index + 1)), payload={'stage': {'step': index, 'ok': True}})
        conn.commit()

    with closing(db.connect(path, session_id='second-owner')) as conn:
        db.ensure_active_run(conn, request_summary='Second active RUN', work_type='investigation', workflow_mode='fast')
        db.upsert_item(conn, kind='task', stable_id='TASK-001', title='Second RUN task', status='Pending')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--workspace', type=Path, required=True)
    parser.add_argument('--port', type=int, default=8768)
    parser.add_argument('--seed-only', action='store_true')
    parser.add_argument('--without-default', action='store_true')
    args = parser.parse_args()
    seed(args.workspace)
    if not args.seed_only:
        viewer.serve(default_workspace=None if args.without_default else args.workspace, port=args.port)
