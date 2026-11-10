"""Seed an isolated workspace and serve the repository's current Viewer assets."""
from __future__ import annotations

import argparse
from contextlib import closing
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'tapl'))
from taplctl import db, viewer


def seed(workspace: Path) -> None:
    path = workspace / '.tapl' / 'tapl.db'
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        return
    with closing(db.connect(path)) as conn:
        db.ensure_active_run(conn, request_summary='Archived design', work_type='analysis', workflow_mode='standard')
        db.upsert_item(conn, kind='finding', stable_id='FINDING-001', title='Archived contrast finding', body='Original archived record', status='Resolved')
        db.archive_active_run(conn, slug='archived-design', memory_review_enabled=False)
        db.ensure_active_run(conn, request_summary='Viewer redesign', work_type='implementation', workflow_mode='strict')
        for index in range(1, 4):
            db.upsert_item(conn, kind='plan', stable_id=f'PLAN-{index:03}', title=f'Interface plan {index}', body='A concise overview of the proposed interface.', status='Finalized')
        for index in range(1, 25):
            state = ['Pending', 'In Progress', 'Blocked', 'Completed'][index % 4]
            db.upsert_item(conn, kind='task', stable_id=f'TASK-{index:03}', title=f'Interface task {index}', body=f'Implementation details for task {index}.', status=state)
        db.upsert_item(conn, kind='finding', stable_id='FINDING-001', title='Readable contrast', body='Current interface finding.', status='Open')
    with closing(db.connect(path, session_id='second-owner')) as conn:
        db.ensure_active_run(conn, request_summary='Second active RUN', work_type='investigation', workflow_mode='fast')
        db.upsert_item(conn, kind='task', stable_id='TASK-001', title='Second RUN task', status='Pending')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--workspace', type=Path, required=True)
    parser.add_argument('--port', type=int, default=8768)
    args = parser.parse_args()
    seed(args.workspace)
    viewer.serve(default_workspace=args.workspace, port=args.port)
