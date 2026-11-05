"""Claude selection capabilities and the real TAPL parallel lifecycle."""
from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from taplctl import clients, config, config_editor, db, prompt
from taplctl.application import WorkflowApplication, WorkflowApplicationError


CODEX = '''# Existing Codex preferences must survive Claude setup.
[subagents]
enabled = true
setup_complete = true
strategy = "conservative"
preference = "Quality first"
profiles = []
[subagents.models]
codex-model = ["high"]
'''


def test_claude_setup_and_editor_preserve_independent_codex_settings(tmp_path: Path) -> None:
    path = tmp_path / 'config.toml'
    path.write_text(CODEX)
    with clients.client_scope('claude-code'):
        pending = config.load(path)
        assert not pending.subagents.setup_complete
        assert pending.as_dict()['client'] == 'claude-code'
        assert pending.as_dict()['subagents_config_key'] == 'clients.claude-code.subagents'
        assert pending.subagents.models == ()
        configured = config_editor.configure_subagents(
            path, enabled=True, strategy='balanced', models={'sonnet': []},
            available_models={'sonnet': []}, preference='Prefer speed',
            profiles=[{'name': 'routine', 'candidates': [{'model': 'sonnet'}]}],
        )
        assert configured.config.as_dict()['models'] == {'sonnet': []}
        assert 'unspecified' in configured.config.as_dict()['selection_semantics']['empty_reasoning_efforts'].lower()
        config_editor.set_value(path, 'subagents.preference', '"Cost first"')
        assert config.load(path).subagents.preference == 'Cost first'
        # Omission preserves the last host-confirmed catalog snapshot.
        config_editor.configure_subagents(path, enabled=True, strategy='balanced', models={'inherit': []})
        assert config.load(path).subagents.as_dict()['available_models'] == {'sonnet': []}
    parsed = tomllib.loads(path.read_text())
    assert parsed['subagents'] == tomllib.loads(CODEX)['subagents']
    assert config.load(path).subagents.preference == 'Quality first'
    assert config.load(path).subagents.as_dict()['models'] == {'codex-model': ['high']}
    assert 'client' not in config.load(path).as_dict()  # Legacy Codex public shape.
    assert '# Existing Codex preferences' in path.read_text()


def test_explicit_claude_edits_work_from_codex_scope_and_preserve_dotted_model_id(tmp_path: Path) -> None:
    path = tmp_path / 'config.toml'
    path.write_text(CODEX)
    config_editor.set_value(path, 'clients.claude-code.subagents.models.custom.model', '[]')
    config_editor.set_value(path, 'clients.claude-code.subagents.strategy', 'balanced')
    with clients.client_scope('claude-code'):
        assert config.load(path).subagents.as_dict()['models'] == {'custom.model': []}
        config_editor.unset_value(path, 'subagents.preference')
    assert tomllib.loads(path.read_text())['subagents'] == tomllib.loads(CODEX)['subagents']


def test_claude_inline_custom_settings_and_profiles_survive_setup(tmp_path: Path) -> None:
    path = tmp_path / 'config.toml'
    path.write_text(CODEX + '\n[clients.claude-code]\nsubagents = { enabled = false, custom = "keep", available_models = { sonnet = [] } }\n')
    with clients.client_scope('claude-code'):
        config_editor.configure_subagents(path, enabled=True, strategy='balanced', models={'sonnet': []})
    target = tomllib.loads(path.read_text())['clients']['claude-code']['subagents']
    assert target['custom'] == 'keep'
    assert target['available_models'] == {'sonnet': []}
    assert target['models'] == {'sonnet': []}
    assert tomllib.loads(path.read_text())['subagents'] == tomllib.loads(CODEX)['subagents']


@pytest.mark.parametrize('prefix', [
    'clients = { claude-code = { subagents = { enabled = false, custom = "keep" }, sibling = 7 }, other = { value = 9 } }',
    '[clients]\nclaude-code = { subagents = { enabled = false, custom = "keep" }, sibling = 7 }',
])
def test_inline_client_ancestors_support_setup_set_and_unset(tmp_path: Path, prefix: str) -> None:
    path = tmp_path / 'config.toml'
    path.write_text('# preserve comment\n' + prefix + '\n')
    with clients.client_scope('claude-code'):
        config_editor.configure_subagents(path, enabled=True, strategy='balanced',
                                         models={'sonnet': []}, available_models={'sonnet': []})
        config_editor.set_value(path, 'subagents.preference', '"Updated"')
        config_editor.unset_value(path, 'subagents.preference')
        settings = config.load(path).subagents
    data = tomllib.loads(path.read_text())
    assert data['clients']['claude-code']['sibling'] == 7
    assert data['clients']['claude-code']['subagents']['custom'] == 'keep'
    assert settings.setup_complete and settings.as_dict()['models'] == {'sonnet': []}
    assert 'preserve comment' in path.read_text()


def test_unspecified_effort_and_inherit_are_selection_semantics_only() -> None:
    with pytest.raises(ValueError, match='at least one reasoning effort'):
        config.parse_subagent_models({'sonnet': []}, enabled=True, client='codex')
    with clients.client_scope('claude-code'):
        assert config.parse_subagent_models({'sonnet': []}, enabled=True)[0].reasoning_efforts == ()
        assert config.parse_subagent_models({'inherit': []}, enabled=True)[0].name == 'inherit'
        with pytest.raises(ValueError, match='selection mode, not a catalog model'):
            config.parse_subagent_models({'inherit': []}, enabled=False, key='available_models')
        with pytest.raises(ValueError, match='inherited selection requires an empty effort array'):
            config.parse_subagent_models({'inherit': ['high']}, enabled=True)
        with pytest.raises(ValueError, match='at least one model'):
            config.parse_subagent_models({}, enabled=True)
        with pytest.raises(ValueError, match='not allowed'):
            config.parse_subagent_profiles(
                [{'name': 'wrong', 'candidates': [{'model': 'sonnet', 'reasoning_effort': 'invented'}]}],
                models=config.parse_subagent_models({'sonnet': []}, enabled=True),
            )


def test_claude_confirmation_rejects_unobserved_models_even_without_effort(tmp_path: Path) -> None:
    (tmp_path / '.git').mkdir()
    db.initialize_workspace(tmp_path)
    with clients.client_scope('claude-code'):
        app = WorkflowApplication(tmp_path, session_id=clients.session_key('approval'))
        with pytest.raises(WorkflowApplicationError, match='current delegation-tool catalog'):
            app.configure_subagents(user_confirmed=True, enabled=True, strategy='balanced',
                                    models={'unknown': []}, available_models={'sonnet': []})
        chosen = app.configure_subagents(user_confirmed=True, enabled=True, strategy='balanced',
                                       models={'inherit': []}, available_models={})
        assert chosen['subagents']['models'] == {'inherit': []}
        assert chosen['subagents']['available_models'] == {}


def test_claude_renderer_has_host_tools_and_complete_parallel_protocol() -> None:
    with clients.client_scope('claude-code'):
        settings = config.from_mapping(
            {'clients': {'claude-code': {'subagents': {
                'models': {'sonnet': [], 'inherit': []}, 'setup_complete': True,
            }}}}, path='config.toml',
        ).subagents
        rendered = '\n'.join((prompt.mcp_entry_instructions(), prompt.mcp_bootstrap_instructions(),
                              prompt.mcp_server_instructions(subagents=settings),
                              prompt.subagent_current_guidance(settings),
                              prompt.user_prompt_submit_guidance(subagents=settings),
                              prompt.session_routing_guidance()))
    for required in ('AskUserQuestion', 'Agent', 'tapl_get_next', 'parent', 'execution_id',
                     'tapl_dispatch_tasks', 'tapl_complete_task', 'tapl_block_task', 'tapl_skip_task',
                     'tapl_recover_batch', 'owned_paths',
                     'claude-code:', 'v2.1.292', 'CLAUDE_CODE_EFFORT_LEVEL', 'unspecified effort',
                     'workspace context', 'Root alone', 'at most three targeted read-only local lookups'):
        assert required in rendered
    for leak in ('Code mode:', 'CODEX_THREAD_ID', 'Codex', 'fork_turns=', 'autoResolutionMs=',
                 'UserPromptSubmit developer context', 'AskUserQuestion source'):
        assert leak not in rendered
    assert 'source `request_user_input`' in rendered
    assert 'root-only fallback is a limitation' in rendered


def _parallel_app(root: Path) -> WorkflowApplication:
    (root / '.git').mkdir()
    db.initialize_workspace(root)
    (root / '.tapl/config.toml').write_text(CODEX)
    app = WorkflowApplication(root, session_id=clients.session_key('native-owner'))
    app.configure_subagents(user_confirmed=True, enabled=True, strategy='aggressive',
                            models={'sonnet': []}, available_models={'sonnet': []})
    with app._connection() as conn:
        db.ensure_active_run(conn)
        db.upsert_plan(conn, plan_id='PLAN-001', title='Independent changes', status='Finalized')
        for index, path in ((1, 'one.py'), (2, 'two.py')):
            db.upsert_task(conn, task_id=f'TASK-{index:03}', title=path, status='Pending',
                           spec_id='PLAN-001', goal='Implement independent file', action='Edit owned file',
                           verification='Inspect file', execution_mode='parallel', executor_kind='subagent',
                           parallel_group='claude-batch', owned_paths=[path])
        db.record_approval(conn, decision='approved', prompt='Implement both changes', source='explicit_user')
    return app


def test_claude_two_task_dispatch_exact_owner_and_execution_settlement(tmp_path: Path) -> None:
    with clients.client_scope('claude-code'):
        app = _parallel_app(tmp_path)
        metadata = {task: {'model': 'sonnet', 'reasoning_effort': '', 'model_reason': 'Host exposes no effort'}
                    for task in ('TASK-001', 'TASK-002')}
        manifest = app.dispatch_tasks(['TASK-001', 'TASK-002'], execution_metadata=metadata)
        executions = manifest['executions']
        assert len(executions) == 2
        assert len({entry['execution_id'] for entry in executions}) == 2
        assert all(entry['model'] == 'sonnet' and entry['reasoning_effort'] == '' for entry in executions)
        for entry in executions:
            assert entry['custom_fields']['SubAgent Model'] == 'sonnet (effort unspecified)'
            assert entry['custom_fields']['Execution Decision']['reasoning_effort'] == ''
        assert app.get_status()['session_id'] == 'claude-code:native-owner'
        with pytest.raises(WorkflowApplicationError, match='exact execution_id'):
            app.settle_task('TASK-001', status='Completed', result='No identity')
        foreign = WorkflowApplication(tmp_path, session_id=clients.session_key('other-owner'))
        with pytest.raises(ValueError, match='active run|session|execution'):
            foreign.settle_task('TASK-001', status='Completed', execution_id=executions[0]['execution_id'])
        with pytest.raises(ValueError, match='task|execution'):
            app.settle_task('TASK-002', status='Completed', execution_id=executions[0]['execution_id'])
        for entry in executions:
            completed = app.settle_task(entry['task_id'], status='Completed', execution_id=entry['execution_id'],
                                        verification='Independent output reviewed', result='Done')
            assert completed['settled_execution_id'] == entry['execution_id']
        status = app.get_status(full=True)
        assert not status['active_batches']
        assert all(task['status'] == 'Completed' for task in status['tasks'])
        assert status['config']['subagents']['models'] == {'sonnet': []}


def test_claude_recovery_requires_new_execution_ids(tmp_path: Path) -> None:
    with clients.client_scope('claude-code'):
        app = _parallel_app(tmp_path)
        first = app.dispatch_tasks(['TASK-001', 'TASK-002'])
        app.recover_batch(first['batch']['batch_id'], reason='Agent spawn failed before work began')
        second = app.dispatch_tasks(['TASK-001', 'TASK-002'])
        assert {entry['execution_id'] for entry in first['executions']}.isdisjoint(
            entry['execution_id'] for entry in second['executions'])
        stale = first['executions'][0]
        with pytest.raises(ValueError, match='settled|active|execution'):
            app.settle_task(stale['task_id'], status='Completed', execution_id=stale['execution_id'], result='Stale')
        app.cancel_batch(second['batch']['batch_id'], reason='Test cleanup')
