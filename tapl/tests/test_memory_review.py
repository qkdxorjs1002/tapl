from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest import mock
import json

import pytest

from taplctl import db, recall
from taplctl.application import WorkflowApplication


@pytest.fixture
def app(tmp_path):
    (tmp_path / '.git').mkdir()
    db.initialize_workspace(tmp_path)
    (tmp_path / '.tapl/config.toml').write_text('[subagents]\nenabled=false\n')
    return WorkflowApplication(tmp_path)


def start(app):
    return app.summarize_run('SQLite migrations', work_type='answer', workflow_mode='fast')['active_run']['id']


def candidate(run_id, slot=1, **changes):
    return {'slot': slot, 'note': 'Check migration boundaries. Verify rollback. Preserve prior rows.',
            'cue': ['sqlite', 'migration', 'rollback'], 'source_run_id': run_id, **changes}


def finish(app, run_id, **kw):
    return app.finish_run('Verified migration rollback', expected_run_id=run_id, **kw)['memory']


def skip(app, run_id):
    return finish(app, run_id, memory_review={'decision': 'skip', 'reason': 'No additional verified reusable lesson.'})


def test_review_required_persists_and_reasoned_skip_resolves(app):
    run_id = start(app)
    assert finish(app, run_id)['status'] == 'review_required'
    assert app.get_status()['active_run']['result_summary']
    assert app.get_next()['memory_review']['status'] == 'review_required'
    assert app.get_next()['recommendations'][0]['name'] == 'review-memory'
    with pytest.raises(ValueError, match='memory review pending'):
        app.finish_archive('blocked')
    assert finish(app, run_id)['status'] == 'review_required'
    assert skip(app, run_id)['status'] == 'ok'
    app.finish_archive('reviewed')


@pytest.mark.parametrize('review,candidates', [({'decision': 'skip'}, None), ({'decision': 'skip', 'reason': ' '}, None),
    ({'decision': 'skip', 'reason': 'x' * 241}, None), ({'decision': 'bad'}, None),
    ({'decision': 'skip', 'reason': 'No lesson'}, [{'slot': 1}])])
def test_invalid_review_does_not_write_result(app, review, candidates):
    run_id = start(app)
    with pytest.raises(ValueError):
        finish(app, run_id, memory_review=review, memory_candidates=candidates)
    assert not app.get_status()['active_run']['result_summary']


def test_failure_persists_noop_retry_and_skip_keeps_success(app):
    run_id = start(app)
    good, bad = candidate(run_id), candidate(run_id, slot=2, note='x' * 241)
    response = finish(app, run_id, memory_candidates=[good, bad])
    assert response['status'] == 'partial'
    memory_id = response['captures'][0]['memory_id']
    assert response['errors'][0]['slot'] == 2
    assert finish(app, run_id)['errors'][0]['attempts'] == 1
    assert app.get_status()['memory_review']['status'] == 'partial'
    with pytest.raises(ValueError, match='same slot'):
        app.finish_archive('blocked')
    assert skip(app, run_id)['status'] == 'ok'
    assert app.get_memory(memory_id)['memory']['note'] == good['note']
    diagnostics = app.recall(query='unrelated')['diagnostics']
    assert diagnostics['stored_count'] == 1 and diagnostics['matched_count'] == 0
    assert diagnostics['last_capture_error']['slot'] == 2
    app.finish_archive('acknowledged')


def test_corrected_failed_slot_retry_and_exhaustion(app):
    run_id = start(app)
    bad = candidate(run_id, note='x' * 241)
    assert finish(app, run_id, memory_candidates=[bad])['status'] == 'failed'
    fixed = candidate(run_id)
    assert finish(app, run_id, memory_candidates=[fixed])['status'] == 'ok'
    # A completed slot always replays idempotently, even after conflicting attempts.
    finish(app, run_id, memory_candidates=[bad])
    finish(app, run_id, memory_candidates=[bad])
    assert finish(app, run_id, memory_candidates=[fixed])['captures'][0]['status'] == 'already_captured'
    bad2 = candidate(run_id, slot=2, note='x' * 241)
    finish(app, run_id, memory_candidates=[bad2])
    finish(app, run_id, memory_candidates=[bad2])
    response = finish(app, run_id, memory_candidates=[candidate(run_id, slot=2, note='A second verified lesson.')])
    assert response['errors'][0]['code'] == 'retry_exhausted'
    assert skip(app, run_id)['status'] == 'ok'


def test_legacy_and_disabled_runs_can_archive(app):
    run_id = start(app)
    with app._connection() as conn:
        db.update_active_run_summary(conn, result_summary='legacy result')
    app.finish_archive('legacy')
    run_id = start(app)
    finish(app, run_id)
    (app.workspace_root / '.tapl/config.toml').write_text('[subagents]\nenabled=false\n[recall]\nenabled=false\n')
    assert app.get_status()['memory_review']['status'] == 'disabled'
    assert finish(app, run_id)['status'] == 'disabled'
    app.finish_archive('disabled')


def test_internal_failure_safe_result_and_corrected_retry(app):
    run_id = start(app)
    with mock.patch.object(recall, 'finish_memories', side_effect=RuntimeError('secret token=never-store')):
        assert finish(app, run_id, memory_candidates=[candidate(run_id)])['status'] == 'failed'
    assert app.get_status()['active_run']['result_summary']
    with app._connection() as conn:
        assert 'never-store' not in json.dumps([dict(r) for r in conn.execute('SELECT * FROM events')])
    assert finish(app, run_id, memory_candidates=[candidate(run_id)])['status'] == 'ok'
    app.finish_archive('recovered')


@pytest.mark.parametrize('previous', ['none', 'capture', 'skip'])
def test_archive_cannot_race_result_checkpoint(app, previous):
    run_id = start(app)
    if previous == 'capture':
        finish(app, run_id, memory_candidates=[candidate(run_id)])
    elif previous == 'skip':
        skip(app, run_id)
    original = recall.finish_memories
    reached, resume = Event(), Event()
    def paused(*args, **kwargs):
        reached.set()
        assert resume.wait(5)
        return original(*args, **kwargs)
    with mock.patch.object(recall, 'finish_memories', side_effect=paused), ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(finish, app, run_id, memory_candidates=[candidate(run_id)])
        try:
            assert reached.wait(5)
            with pytest.raises(ValueError, match='memory review pending'):
                app.finish_archive('raced')
        finally:
            resume.set()
        assert future.result()['status'] == 'ok'
    assert app.recall()['diagnostics']['stored_count'] == 1


def test_pending_use_failure_survives_noop_and_can_be_retried(app):
    run_id = start(app)
    capture = finish(app, run_id, memory_candidates=[candidate(run_id)])
    memory_id = capture['captures'][0]['memory_id']
    uses = [{'memory_id': memory_id, 'revision': 1, 'source_checked': False, 'usage': 'Applied after source review.'}]
    assert finish(app, run_id, memory_uses=uses)['status'] == 'partial'
    assert finish(app, run_id)['errors'][0]['memory_id'] == memory_id
    uses[0]['source_checked'] = True
    assert finish(app, run_id, memory_uses=uses)['status'] == 'ok'


@pytest.mark.parametrize('abandon', [False, True])
def test_later_finish_fences_inflight_capture_without_silent_loss(app, abandon):
    run_id = start(app)
    original = recall.finish_memories
    reached, resume = Event(), Event()
    def paused(*args, **kwargs):
        if kwargs.get('candidates'):
            reached.set()
            assert resume.wait(5)
        return original(*args, **kwargs)
    with mock.patch.object(recall, 'finish_memories', side_effect=paused), ThreadPoolExecutor(max_workers=1) as pool:
        first = pool.submit(finish, app, run_id, memory_candidates=[candidate(run_id)])
        try:
            assert reached.wait(5)
            if abandon:
                assert skip(app, run_id)['status'] == 'ok'
                app.finish_archive('explicit-abandon')
            else:
                assert finish(app, run_id)['errors'][0]['code'] == 'processing_pending'
                with pytest.raises(ValueError, match='memory review pending'):
                    app.finish_archive('must-wait')
        finally:
            resume.set()
        assert first.result()['status'] == 'failed'
    assert app.recall()['total'] == 0
    if not abandon:
        assert finish(app, run_id, memory_candidates=[candidate(run_id)])['status'] == 'ok'
        app.finish_archive('recovered-inflight')


def test_unrelated_success_cannot_clear_internal_capture_failure(app):
    run_id = start(app)
    with mock.patch.object(recall, 'finish_memories', side_effect=RuntimeError('temporary')):
        finish(app, run_id, memory_candidates=[candidate(run_id)])
    other = candidate(run_id, slot=2, note='Another verified lesson about rollback diagnostics.')
    result = finish(app, run_id, memory_candidates=[other])
    assert result['status'] == 'partial'
    assert result['errors'][0]['slot'] == 1
    assert finish(app, run_id)['errors'][0]['slot'] == 1
    assert finish(app, run_id, memory_candidates=[candidate(run_id)])['status'] == 'ok'


def test_use_partial_success_survives_noop(app):
    first = start(app)
    memory_id = finish(app, first, memory_candidates=[candidate(first)])['captures'][0]['memory_id']
    app.finish_archive('original')
    current = start(app)
    uses = [
        {'memory_id': memory_id, 'revision': 1, 'source_checked': True, 'usage': 'Checked original rollback guidance.'},
        {'memory_id': 'missing', 'revision': 1, 'source_checked': True, 'usage': 'Invalid reference.'},
    ]
    assert finish(app, current, memory_uses=uses, memory_review={'decision': 'skip', 'reason': 'No new lesson.'})['status'] == 'partial'
    assert finish(app, current)['status'] == 'partial'
