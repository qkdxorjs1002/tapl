"""Resolve live authoring policy once per owner-scoped runtime snapshot."""
from __future__ import annotations

import asyncio
from copy import deepcopy
from unittest import mock

from mcp import Client
import pytest

from taplctl import config, db, hooks, mcp_server, prompt
from taplctl.application import WorkflowApplication


def set_detail(root, detail=None):
    workflow = '' if detail is None else f'[workflow]\nauthoring_detail="{detail}"\n'
    (root / '.tapl/config.toml').write_text(
        workflow + '[recall]\nenabled=false\n[subagents]\nenabled=false\nsetup_complete=true\n',
        encoding='utf-8',
    )


@pytest.fixture
def workspace(tmp_path):
    (tmp_path / '.git').mkdir()
    db.initialize_workspace(tmp_path)
    set_detail(tmp_path)
    return tmp_path


def expected(detail, mode):
    return config.authoring_policy(detail, mode)


@pytest.mark.parametrize('mode,effective', [('fast', 'minimal'), ('standard', 'normal'), ('strict', 'precise')])
def test_auto_mapping_reaches_all_runtime_surfaces(workspace, mode, effective):
    app = WorkflowApplication(workspace, session_id='owner')
    app.summarize_run('Analyze current behavior', work_type='analysis', workflow_mode=mode)
    for payload in (app.get_status(), app.get_next(), app.get_next_actions(), app.validate_state(), app.get_context()):
        assert payload['authoring_policy'] == expected('auto', mode)
        assert payload['authoring_policy']['effective'] == effective
        if 'plan_task_execute' in payload:
            assert payload['plan_task_execute']['authoring_policy'] == payload['authoring_policy']
    policy = app.get_next()
    assert policy['config']['workflow']['authoring_detail'] == 'auto'
    assert policy['workflow_policy'] == prompt.mcp_server_instructions(
        subagents=app._settings().subagents, authoring_detail=effective,
    )
    with app._connection() as conn:
        startup = hooks.handle_event(conn, event='SessionStart', mode='enforce', tool=None,
                                     payload={}, tapl_settings=app._settings())
    assert startup['authoring_policy'] == expected('auto', mode)
    assert startup['context']['authoring_policy'] == expected('auto', mode)
    assert f'PLAN/TASK authoring detail: {effective}' in startup['message']


@pytest.mark.parametrize('detail', ['precise', 'normal', 'minimal'])
def test_explicit_detail_wins_and_mode_changes_still_refresh(workspace, detail):
    set_detail(workspace, detail)
    app = WorkflowApplication(workspace)
    app.summarize_run('Review behavior', work_type='analysis', workflow_mode='fast')
    before = app.get_next()
    changed = app.summarize_run('Review public contract', work_type='analysis', workflow_mode='strict')
    assert changed['policy_refresh_required']
    assert changed['authoring_policy'] == expected(detail, 'strict')
    after = app.get_next(known_policy_revision=before['policy_revision'])
    assert not after['policy_unchanged']
    assert after['authoring_policy']['effective'] == detail


def test_status_and_next_resolve_from_one_snapshot_without_second_run_read(workspace):
    app = WorkflowApplication(workspace)
    app.summarize_run('Known task', workflow_mode='strict')
    for inspect in (app.get_status, app.get_next, app.get_next_actions, app.validate_state, app.get_context):
        with mock.patch.object(db, 'status_payload', wraps=db.status_payload) as read_state:
            result = inspect()
        assert read_state.call_count == 1
        assert result['authoring_policy'] == expected('auto', 'strict')


def test_next_actions_omit_policy_rendering_and_keep_fresh_state(workspace):
    app = WorkflowApplication(workspace)
    app.summarize_run('Short answer', work_type='answer', workflow_mode='fast')
    with mock.patch.object(prompt, 'mcp_server_instructions', side_effect=AssertionError('policy rendered')):
        actions = app.get_next_actions()
    assert actions['authoring_policy'] == expected('auto', 'fast')
    assert actions['state_summary']['active_run']['workflow_mode'] == 'fast'
    assert 'workflow_policy' not in actions and 'config' not in actions


def test_actual_mcp_cache_mode_upgrade_and_lightweight_defaults(workspace):
    async def exercise():
        async with Client(mcp_server.create_server(workspace_root=workspace)) as client:
            async def call(name, **args):
                result = await client.call_tool(name, {'session_id': 'owner', **args})
                assert not result.is_error, result.content
                return result.structured_content

            initial = await call('tapl_get_next')
            assert initial['authoring_policy'] == expected('auto', None)
            full = await call('tapl_get_next')  # A revision alone never proves content retention.
            assert 'workflow_policy' in full
            fast = await call('tapl_summarize_run', summary='Answer a bounded question',
                              work_type='answer', workflow_mode='fast')
            assert fast['authoring_policy'] == expected('auto', 'fast')
            assert fast['active_run']['record_mode'] == 'lightweight'
            assert fast['policy_refresh_required']
            assert fast['recommendations'][0]['tool'] == 'tapl_get_next'
            status = await call('tapl_get_status')
            assert status['plans'] == status['tasks'] == []
            selected = await call('tapl_get_next', known_policy_revision=initial['policy_revision'])
            assert not selected['policy_unchanged']
            cached = await call('tapl_get_next', known_policy_revision=selected['policy_revision'])
            assert cached['policy_unchanged'] and 'workflow_policy' not in cached
            assert cached['authoring_policy'] == expected('auto', 'fast')
            strict = await call('tapl_summarize_run', summary='Review interface and risk boundaries',
                                work_type='analysis', workflow_mode='strict')
            assert strict['policy_refresh_required']
            reason = strict['recommendations'][0]['reason']
            for word in ('PLAN', 'unfinished TASK', 'risk', 'interface', 'rollback', 'verification', 'custom_fields'):
                assert word in reason
            upgraded = await call('tapl_get_next', known_policy_revision=selected['policy_revision'])
            assert not upgraded['policy_unchanged']
            assert upgraded['policy_revision'] != selected['policy_revision']
            assert upgraded['authoring_policy'] == expected('auto', 'strict')
            unchanged = await call('tapl_summarize_run', summary='Clarify the same strict request',
                                  work_type='analysis', workflow_mode='strict')
            assert not unchanged.get('policy_refresh_required', False)

    asyncio.run(exercise())


def test_compact_receipt_preserves_refresh_when_next_lookup_fails(workspace):
    app = WorkflowApplication(workspace, session_id='owner')
    app.summarize_run('Small request', work_type='analysis', workflow_mode='fast')

    async def exercise():
        with mock.patch.object(app, 'get_next_actions', side_effect=RuntimeError('lookup unavailable')):
            receipt = await mcp_server.call_application_write(
                app, app.summarize_run, 'Review strict interface', work_type='analysis', workflow_mode='strict',
                operation='run_summarize', session_id='owner',
            )
        assert receipt['ok'] and receipt['policy_refresh_required']
        assert receipt['authoring_policy'] == expected('auto', 'strict')
        assert receipt['recommendations'][0]['name'] == 'refresh-authoring-policy'
        assert receipt['recommendations'][0]['tool'] == 'tapl_get_next'
        assert receipt['recommendations'][1]['name'] == 'inspect-status'

    asyncio.run(exercise())


def test_strict_upgrade_preserves_completed_records_and_custom_fields(workspace):
    app = WorkflowApplication(workspace)
    app.summarize_run('Update one bounded handler', workflow_mode='standard')
    app.apply_plan('PLAN-001', status='Finalized', objective='Correct output', requirements_trace='REQ-001',
                   selected_approach='Change handler', validation='Focused regression', custom_fields={'note': 'original'})
    app.create_task('TASK-001', 'Correct handler', 'PLAN-001', 'Correct output', 'Update handler',
                    'Focused regression', custom_fields={'note': 'original task'})
    app.record_approval(decision='approved', prompt='Implement handler', source='explicit_user')
    app.start_task('TASK-001')
    app.settle_task('TASK-001', status='Completed', result='Corrected', verification='Regression passed')
    def recorded_items():
        status = app.get_status(full=True)
        for task in status['tasks']:
            if task.get('execution_timing'):
                # Snapshot time changes on reads; persisted timing must stay intact.
                task['execution_timing'].pop('as_of')
        return deepcopy((status['plans'], status['tasks']))

    original_items = recorded_items()
    changed = app.summarize_run('Review completed handler public contract', workflow_mode='strict')
    assert changed['policy_refresh_required']
    after = app.get_status(full=True)
    assert recorded_items() == original_items
    assert after['plan_task_execute']['ok']
    assert 'task_granularity_too_coarse' not in {x['code'] for x in after['plan_task_execute']['issues']}


def test_input_validators_receive_effective_detail(workspace):
    from taplctl import validation

    app = WorkflowApplication(workspace)
    app.summarize_run('Bounded edit', workflow_mode='fast')
    with mock.patch.object(validation, 'validate_plan_input', wraps=validation.validate_plan_input) as plan_check:
        app.apply_plan('PLAN-001')
    assert plan_check.call_args.kwargs['authoring_detail'] == 'minimal'
    with mock.patch.object(validation, 'validate_task_input', wraps=validation.validate_task_input) as task_check:
        app.create_task('TASK-001', 'Edit', 'PLAN-001', 'Fix', 'Change handler', 'Regression check')
    assert task_check.call_args.kwargs['authoring_detail'] == 'minimal'


def test_config_reload_and_hooks_follow_owner_without_cross_session_mode_leak(workspace):
    a = WorkflowApplication(workspace, session_id='a')
    b = WorkflowApplication(workspace, session_id='b')
    a.summarize_run('Fast answer', work_type='answer', workflow_mode='fast')
    b.summarize_run('Strict review', work_type='analysis', workflow_mode='strict')
    for app, mode in ((a, 'fast'), (b, 'strict'), (a, 'fast')):
        assert app.get_next()['authoring_policy'] == expected('auto', mode)
        with app._connection() as conn:
            result = hooks.handle_event(conn, event='Stop', mode='enforce', tool=None,
                                         payload={}, tapl_settings=app._settings())
        assert result['authoring_policy'] == expected('auto', mode)
    previous = a.get_next()
    set_detail(workspace, 'normal')
    changed = a.get_next(known_policy_revision=previous['policy_revision'])
    assert not changed['policy_unchanged']
    assert changed['authoring_policy'] == expected('normal', 'fast')
    assert b.get_status()['authoring_policy'] == expected('normal', 'strict')
    set_detail(workspace, 'auto')
    assert a.get_context()['authoring_policy'] == expected('auto', 'fast')
    assert b.validate_state()['authoring_policy'] == expected('auto', 'strict')


def test_actual_mcp_compact_general_receipts_use_each_owner_policy(workspace):
    async def exercise():
        async with Client(mcp_server.create_server(workspace_root=workspace)) as client:
            for owner, mode in [('a', 'fast'), ('b', 'strict')]:
                await client.call_tool('tapl_summarize_run', {
                    'session_id': owner, 'summary': owner, 'work_type': 'implementation', 'workflow_mode': mode,
                })
            for owner, mode in [('a', 'fast'), ('b', 'strict'), ('a', 'fast')]:
                receipt = (await client.call_tool('tapl_apply_plan', {
                    'session_id': owner, 'plan_id': 'PLAN-001', 'title': 'Review current behavior',
                })).structured_content
                assert receipt['authoring_policy'] == expected('auto', mode)
                assert receipt['state_summary']['active_run']['session_id'] == owner
                assert 'workflow_policy' not in receipt and 'config' not in receipt

    asyncio.run(exercise())


@pytest.mark.parametrize('detail', ['auto', 'minimal'])
def test_actual_mcp_split_and_queue_activation_refresh_policy(workspace, detail):
    set_detail(workspace, detail)

    async def exercise():
        async with Client(mcp_server.create_server(workspace_root=workspace)) as client:
            async def call(name, **args):
                result = await client.call_tool(name, {'session_id': 'owner', **args})
                assert not result.is_error, result.content
                return result.structured_content

            await call('tapl_summarize_run', summary='Two separate run lifecycles', work_type='analysis', workflow_mode='fast')
            before = await call('tapl_get_next')
            split = await call('tapl_split_run', requests=[
                {'key': 'review', 'summary': 'Review public contract', 'work_type': 'analysis', 'workflow_mode': 'strict'},
                {'key': 'answer', 'summary': 'Answer a bounded question', 'work_type': 'answer', 'workflow_mode': 'fast'},
            ])
            assert split['policy_refresh_required']
            assert split['authoring_policy'] == expected(detail, 'strict')
            assert split['recommendations'][0]['tool'] == 'tapl_get_next'
            strict = await call('tapl_get_next', known_policy_revision=before['policy_revision'])
            assert not strict['policy_unchanged']
            await call('tapl_finish_run', result='Contract reviewed')
            archived = await call('tapl_finish_archive', slug='reviewed-contract')
            assert archived['policy_refresh_required']
            assert archived['authoring_policy'] == expected(detail, 'fast')
            assert archived['recommendations'][0]['name'] == 'refresh-authoring-policy'
            child = await call('tapl_get_next', known_policy_revision=strict['policy_revision'])
            assert not child['policy_unchanged']
            assert child['state_summary']['counts']['plans'] == 0
            assert child['state_summary']['counts']['tasks'] == 0

    asyncio.run(exercise())


@pytest.mark.parametrize('has_child', [False, True])
def test_stop_auto_archive_reports_current_policy_and_refresh(workspace, has_child):
    app = WorkflowApplication(workspace, session_id='owner')
    if has_child:
        app.split_run([
            {'key': 'answer', 'summary': 'Answer question', 'work_type': 'answer', 'workflow_mode': 'fast'},
            {'key': 'review', 'summary': 'Review contract', 'work_type': 'analysis', 'workflow_mode': 'strict'},
        ])
    else:
        app.summarize_run('Answer question', work_type='answer', workflow_mode='fast')
    app.finish_run('Answered')
    with app._connection() as conn:
        result = hooks.handle_event(conn, event='Stop', mode='enforce', tool=None,
                                    payload={}, tapl_settings=app._settings())
    assert result['ok'] and result['archive']
    assert result['authoring_policy'] == expected('auto', 'strict' if has_child else None)
    assert result['authoring_policy'] == app.get_status()['authoring_policy']
    assert result['policy_refresh_required']
    assert result['recommendations'][0]['tool'] == 'tapl_get_next'
    assert 'Call tapl_get_next without known_policy_revision' in result['message']


def test_archive_refresh_survives_next_action_failure(workspace):
    app = WorkflowApplication(workspace, session_id='owner')
    app.split_run([
        {'key': 'first', 'summary': 'First review', 'work_type': 'analysis', 'workflow_mode': 'standard'},
        {'key': 'second', 'summary': 'Second review', 'work_type': 'analysis', 'workflow_mode': 'strict'},
    ])
    app.finish_run('First review complete')

    async def exercise():
        with mock.patch.object(app, 'get_next_actions', side_effect=RuntimeError('lookup unavailable')):
            result = await mcp_server.call_application_write(
                app, app.finish_archive, 'first-review', operation='archive_finish', session_id='owner',
            )
        assert result['ok'] and result['policy_refresh_required']
        assert result['authoring_policy'] == expected('auto', 'strict')
        assert result['recommendations'][0]['name'] == 'refresh-authoring-policy'

    asyncio.run(exercise())


@pytest.mark.parametrize('operation', ['plan', 'task', 'finding'])
def test_implicit_run_creation_reports_policy_transition(workspace, operation):
    app = WorkflowApplication(workspace)
    if operation == 'plan':
        result = app.apply_plan('PLAN-001')
    elif operation == 'task':
        result = app.create_task('TASK-001', 'Review', 'PLAN-001', 'Goal', 'Action', 'Verify')
    else:
        result = app.add_finding('Observed fact')
    assert result['authoring_policy'] == expected('auto', 'standard')
    assert result['policy_refresh_required']
    assert result['recommendations'][0]['tool'] == 'tapl_get_next'


def test_discard_reverts_to_no_run_policy(workspace):
    app = WorkflowApplication(workspace)
    run = app.summarize_run('Review contract', work_type='analysis', workflow_mode='strict')['active_run']
    result = app.discard_run(run_id=run['id'], confirmed=True, confirmation_run_id=run['id'])
    assert result['authoring_policy'] == expected('auto', None)
    assert result['policy_refresh_required']
    assert app.get_status()['active_run'] is None
