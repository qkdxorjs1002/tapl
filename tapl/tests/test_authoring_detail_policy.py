"""Authoring preferences change writing/decomposition without relaxing safety gates."""
from __future__ import annotations

import asyncio
from copy import deepcopy

from mcp import Client
import pytest

from taplctl import config, db, hooks, mcp_server, prompt, validation
from taplctl.application import WorkflowApplication


def workspace(tmp_path, detail="precise"):
    (tmp_path / ".git").mkdir()
    db.initialize_workspace(tmp_path)
    set_detail(tmp_path, detail)
    return WorkflowApplication(tmp_path)


def set_detail(root, detail):
    (root / ".tapl/config.toml").write_text(
        f'[workflow]\nauthoring_detail="{detail}"\n'
        '[recall]\nenabled=false\n[subagents]\nenabled=false\nsetup_complete=true\n',
        encoding="utf-8",
    )


def populate(app):
    app.summarize_run("Update the handler", work_type="implementation", workflow_mode="standard")
    app.apply_plan("PLAN-001", objective="Correct the handler", requirements_trace="REQ-001",
                   selected_approach="Update handler and focused tests", validation="Run focused tests")
    return app.create_task("TASK-001", "Update handler", "PLAN-001", "Correct output",
                           "Update handler and regression test", "Run focused tests")


def codes(result):
    return {issue["code"] for issue in result["issues"]}


def test_precise_preserves_explicit_policy_and_validation():
    precise = "precise"
    assert prompt.task_granularity_guidance(authoring_detail=precise) == "Split every independent edit, migration, and verification step."
    assert prompt.template_variables(authoring_detail=precise)["plan_detail_guidance"] == prompt.plan_detail_guidance(authoring_detail=precise)
    state = {"active_run": {"record_mode": "planned", "workflow_mode": "strict"},
             "plans": [{"stable_id": "PLAN-001"}],
             "tasks": [{"stable_id": "TASK-001", "spec_id": "PLAN-001", "status": "Pending"}]}
    assert "task_granularity_too_coarse" in codes(validation.validate_workflow_state(state))
    assert "task_granularity_too_coarse" in codes(validation.validate_workflow_state(state, authoring_detail=precise))


def test_lower_policy_replaces_verbose_requirements_without_count_or_length_targets():
    policies = {detail: prompt.mcp_server_instructions(authoring_detail=detail)
                for detail in config.AUTHORING_DETAILS}
    assert len(policies["minimal"]) < len(policies["normal"]) < len(policies["precise"])
    for detail in ("normal", "minimal"):
        policy = policies[detail]
        assert prompt.task_granularity_guidance(authoring_detail="precise") not in policy
        assert prompt.custom_fields_guidance(authoring_detail="precise") not in policy
        assert prompt.task_format_guidance(authoring_detail=detail) in policy
        assert "Routine root work needs no advisory filler" in policy
        assert "explicit user confirmation" in policy
        assert "Strict retains risks, interfaces, rollback and validation boundaries" in policy
        # Inspect authoring instructions, not unrelated safety/status policy numbers.
        authoring = " ".join(provider(authoring_detail=detail) for provider in (
            prompt.plan_detail_guidance, prompt.plan_format_guidance, prompt.task_granularity_guidance,
            prompt.task_format_guidance, prompt.custom_fields_guidance,
        ))
        assert not any(character.isdigit() for character in authoring)
        assert "optional filler" in authoring
        assert "verification" in authoring.lower()
        assert "ownership" in authoring
    assert "Separate substantive verification" in policies["normal"]
    assert "reference shared plan facts" in policies["minimal"].lower()


def test_lower_delegation_guidance_does_not_require_routine_root_metadata():
    settings = config.SubagentsConfig(setup_complete=True, enabled=True)
    precise = prompt.subagent_current_guidance(settings, authoring_detail="precise")
    for detail in ("normal", "minimal"):
        selected = prompt.subagent_current_guidance(settings, authoring_detail=detail)
        assert "Routine root work needs no advisory filler" in selected
        assert "record executable-task decisions in canonical task fields" not in selected
        for gate in ("completed/enabled setup", "live delegation-tool catalog", "owned_paths", "execution_id"):
            assert gate in precise and gate in selected


@pytest.mark.parametrize("detail", ["normal", "minimal"])
def test_lower_levels_accept_coherent_task_and_do_not_cap_many_tasks(detail):
    plans = [{"stable_id": "PLAN-001"}]
    task = {"stable_id": "TASK-001", "status": "Pending"}
    assert validation.validate_task_granularity(plans, [task], authoring_detail=detail) == []
    assert validation.validate_task_granularity(plans, [task] * 100, authoring_detail=detail) == []
    assert validation.validate_task_granularity(plans, [task], authoring_detail="precise")[0]["severity"] == "error"


@pytest.mark.parametrize("detail", ["normal", "minimal"])
def test_lower_levels_preserve_required_content_approval_ownership_and_dependency_checks(tmp_path, detail):
    app = workspace(tmp_path, detail)
    populate(app)
    with app._connection() as conn:
        state = db.status_payload(conn)
    task = state["tasks"][0]
    task.update(status="In Progress", execution_mode="parallel", executor_kind="subagent",
                owned_paths=[], depends_on=["TASK-999"], verification="")
    baseline = validation.validate_workflow_state(deepcopy(state), authoring_detail="precise")
    lower = validation.validate_workflow_state(deepcopy(state), authoring_detail=detail)
    assert lower["issues"] == [item for item in baseline["issues"] if item["code"] != "task_granularity_too_coarse"]
    found = codes(lower)
    assert "task_content_missing_fields" in found
    assert "execution_approval_missing" in found
    assert any("depend" in code for code in found)
    assert any("owned" in code for code in found)


@pytest.mark.parametrize("detail", ["normal", "minimal"])
def test_application_and_hooks_share_live_config_across_writes_and_task_lifecycle(tmp_path, detail):
    app = workspace(tmp_path, detail)
    created = populate(app)
    assert "task_granularity_too_coarse" not in codes(created["plan_task_execute"])
    settings = app._settings()
    for result in (app.get_status(), app.validate_state(), app.get_context()):
        assert "task_granularity_too_coarse" not in codes(result["plan_task_execute"])
    with app._connection() as conn:
        blocked = hooks.handle_event(conn, event="PreToolUse", mode="enforce", tool="Edit", payload={},
                                     tapl_settings=settings)
        assert blocked["block"]  # Authoring detail never grants execution approval.
        assert "execution_approval_missing" in blocked["message"]
    app.record_approval(decision="approved", prompt="Update the handler", source="explicit_user")
    with app._connection() as conn:
        allowed = hooks.handle_event(conn, event="PreToolUse", mode="enforce", tool="Edit", payload={},
                                     tapl_settings=settings)
        assert not allowed["block"]
        startup = hooks.handle_event(conn, event="SessionStart", mode="enforce", tool=None, payload={},
                                     tapl_settings=settings)
        assert startup["context"]["config"]["workflow"]["authoring_detail"] == detail
        assert f"PLAN/TASK authoring detail: {detail}" in startup["message"]
        assert prompt.task_granularity_guidance(authoring_detail=detail) not in startup["message"]
    assert "task_granularity_too_coarse" not in codes(app.start_task("TASK-001")["plan_task_execute"])
    completed = app.settle_task("TASK-001", status="Completed", result="Corrected",
                               verification="Focused regression tests passed")
    assert completed["plan_task_execute"]["ok"]
    assert "task_granularity_too_coarse" not in codes(completed["plan_task_execute"])
    app.finish_run("Corrected and verified")
    with app._connection() as conn:
        stopped = hooks.handle_event(conn, event="Stop", mode="enforce", tool=None, payload={},
                                     tapl_settings=settings)
        assert not stopped["block"]


def test_actual_mcp_reloads_policy_and_revision_after_detail_change(tmp_path):
    workspace(tmp_path)

    async def exercise():
        async with Client(mcp_server.create_server(workspace_root=tmp_path)) as client:
            initial = (await client.call_tool("tapl_get_next", {})).structured_content
            policies = {"precise": initial["workflow_policy"]}
            previous = initial
            for detail in ("normal", "minimal"):
                set_detail(tmp_path, detail)
                selected = (await client.call_tool("tapl_get_next", {
                    "known_policy_revision": previous["policy_revision"],
                })).structured_content
                assert not selected["policy_unchanged"]
                assert selected["policy_revision"] != previous["policy_revision"]
                assert selected["config"]["workflow"]["authoring_detail"] == detail
                assert selected["workflow_policy"] == prompt.mcp_server_instructions(
                    subagents=config.load(start=tmp_path).subagents, authoring_detail=detail,
                )
                policies[detail] = selected["workflow_policy"]
                cached = (await client.call_tool("tapl_get_next", {
                    "known_policy_revision": selected["policy_revision"],
                })).structured_content
                assert cached["policy_unchanged"]
                assert "workflow_policy" not in cached
                previous = selected
            assert len(policies["minimal"]) < len(policies["normal"]) < len(policies["precise"])
            tools = {tool.name: tool for tool in (await client.list_tools()).tools}
            required = tools["tapl_create_task"].input_schema["required"]
            assert {"goal", "action", "verification"} <= set(required)

    asyncio.run(exercise())
