"""Behavior contracts for smaller MCP entry instructions and lazy rendering."""
from __future__ import annotations

import asyncio
from string import Template
from unittest import mock

from mcp import Client
import pytest

from taplctl import config, context, db, execution_evidence, mcp_server, prompt


@pytest.mark.parametrize("template", [
    *[value for key, value in vars(prompt).items() if key.endswith("_TEMPLATE") and isinstance(value, str)],
    "", "  literal  ", "$entry_guidance ${entry_guidance}",
    "$$entry_guidance $missing ${missing} $", "${invalid ${} $9",
    "$custom ${entry_guidance} $task_field_contract",
])
@pytest.mark.parametrize("overrides", [{}, {"entry_guidance": 42, "custom": None}])
def test_lazy_render_is_identical_to_complete_dictionary(template, overrides):
    expected = Template(template).safe_substitute(prompt.template_variables(**overrides)).strip()
    assert prompt.render(template, **overrides) == expected


def test_unused_overridden_and_repeated_providers_are_not_evaluated():
    with mock.patch.object(prompt, "field_contract_section", side_effect=AssertionError("unused")), \
            mock.patch.object(prompt, "entry_guidance", return_value="fresh") as provider:
        assert prompt.session_start_guidance() == prompt.SESSION_START_GUIDANCE_TEMPLATE
        assert prompt.render("$entry_guidance", entry_guidance="override") == "override"
        provider.assert_not_called()
        assert prompt.render("$entry_guidance ${entry_guidance}") == "fresh fresh"
        provider.assert_called_once_with()
        provider.return_value = "changed"
        assert prompt.render("$entry_guidance") == "changed"


def test_transport_entry_gate_keeps_policy_required_and_legacy_bootstrap():
    entry = prompt.mcp_entry_instructions()
    assert len(entry) < 900
    # Formatting must be known before the first entry call can double a large
    # policy response. Keep it visible in both transport and developer hooks.
    assert entry.index("`result.structuredContent`") < entry.index("call `tapl_get_next`")
    assert prompt.entry_guidance().startswith("Code mode: emit `result.structuredContent` only")
    assert "never print the full tool catalog" in prompt.entry_guidance()
    for requirement in (
        "including read-only helpers", "`tapl_get_next` once", "complete `workflow_policy`",
        "`subagent_guidance`, and config", "No project work or TAPL mutations",
        "recommendations do not replace", "wait for a concrete request",
        "Omit model-catalog arguments", "after compaction or policy loss",
        "no `known_policy_revision`", "a summary is insufficient",
        "Only tool discovery and required local-instruction discovery may precede policy loading",
        "discover needed tools by exact name together", "`result.structuredContent`", "parsed text fallback",
    ):
        assert requirement in entry
    assert "Root alone writes TAPL state" in prompt.mcp_bootstrap_instructions()
    for shape in ("canonical JSON objects", "`Task Profile` {name, match_reason}",
                  "delegation_reason", "when selecting a model",
                  "Existing rationale aliases remain accepted"):
        assert shape in prompt.custom_fields_guidance(authoring_detail="precise")
    assert "Group by requested outcome, not file or execution unit" in prompt.request_partition_guidance()
    assert "correct mistaken plan splitting" in prompt.request_partition_guidance()
    assert "the same PLAN and `parallel_group`" in prompt.task_execution_order_guidance()


def test_compact_history_guidance_keeps_workflow_gates():
    policy = prompt.mcp_server_instructions()
    for contract in (
        "never print the full tool catalog",
        "Execution approval is required",
        "Treat design direction, agreement, and plan edits as planning",
        "Ask only when scope is materially ambiguous",
        "the exact current user request as `prompt`",
        "inspect original sources", "atomic `tapl_dispatch_tasks`",
        "Finish, inspect memory, then archive separately",
        "tapl_get_item(compact=true)", "full formatted bodies remain available",
    ):
        assert contract in policy


def test_active_run_context_leaves_request_interpretation_to_agent(tmp_path):
    workspace = db.initialize_workspace(tmp_path)
    settings = config.load(start=tmp_path)
    with db.connect(workspace["db"], session_id="root") as conn:
        db.ensure_active_run(conn)
        db.update_active_run_summary(conn, request_summary="Plan API changes", work_type="planning")
        db.upsert_plan(conn, plan_id="PLAN-001", title="Plan API changes", status="Draft")
        same = context.build_context(
            conn, event="UserPromptSubmit", settings=settings, payload={"prompt": "Plan API changes"},
        )
        follow_up = context.build_context(
            conn, event="UserPromptSubmit", settings=settings, payload={"prompt": "이 설계에 오류 응답도 넣자"},
        )
    assert same["next_actions"] == follow_up["next_actions"]
    assert prompt.active_run_request_next_action() in follow_up["next_actions"]
    assert "Ask only if it is unclear" in context.format_context(follow_up)
    assert "TAPL-APPROVE" not in context.format_context(follow_up)


def test_context_surfaces_current_host_confirmation_without_changing_it(tmp_path):
    workspace = db.initialize_workspace(tmp_path)
    settings = config.load(start=tmp_path)
    with db.connect(workspace["db"], session_id="root") as conn:
        db.ensure_active_run(conn)
        db.update_active_run_summary(conn, request_summary="Analyze API changes", work_type="analysis")
        db.upsert_plan(conn, plan_id="PLAN-001", title="API changes", status="Finalized")
        packet = context.build_context(conn, event="UserPromptSubmit", settings=settings)
        command = execution_evidence.confirmation_command(conn)
        assert command and command.startswith("TAPL-APPROVE ")
        assert context.format_context(packet).count(command) == 1
        assert "If the user explicitly requests execution" in context.format_context(packet)
        helper = context.build_context(
            conn, event="UserPromptSubmit", settings=settings, payload={"agent_id": "helper"},
        )
        assert helper["next_actions"] == []
        assert command not in context.format_context(helper)
        execution_evidence.observe_user_prompt(conn, {"prompt": command})
        acknowledged = context.build_context(
            conn, event="UserPromptSubmit", settings=settings, payload={"prompt": command},
        )
    assert "host confirmed the current plan" in context.format_context(acknowledged)
    assert command not in context.format_context(acknowledged)


def test_new_unsummarized_run_context_skips_host_execution_guard(tmp_path):
    workspace = db.initialize_workspace(tmp_path)
    settings = config.load(start=tmp_path)
    with db.connect(workspace["db"], session_id="root") as conn:
        db.ensure_active_run(conn)
        execution_evidence.observe_user_prompt(conn, {"prompt": "Explain this term"})
        packet = context.build_context(conn, event="UserPromptSubmit", settings=settings)
    assert "Execution is on hold" not in context.format_context(packet)
    assert "TAPL-APPROVE" not in context.format_context(packet)


def test_short_policy_reload_and_task_stage_notice_guidance():
    reload = prompt.post_compact_guidance()
    assert "`tapl_get_next` without `known_policy_revision`" in reload
    assert "complete `workflow_policy`, `subagent_guidance`, and config" in reload
    notice = prompt.mcp_tool_result_display_guidance()
    assert "verification notice once on entering that stage, after successful" in notice
    assert "`tapl_start_task` or `tapl_dispatch_tasks`" in notice
    assert "Skip repeats on retries" in notice


@pytest.mark.parametrize("search", ["bm25", "word", "semantic", "hybrid"])
@pytest.mark.parametrize("recall", [False, True])
@pytest.mark.parametrize("delegation", ["pending", "disabled", "conservative", "balanced", "aggressive"])
@pytest.mark.parametrize("profiles", ["default", "empty", "custom"])
def test_entry_options_keep_complete_policy_and_fresh_state(tmp_path, search, recall, delegation, profiles):
    # pytest creates a separate directory/DB/config for every condition.
    root = tmp_path / "workspace"
    (root / ".git").mkdir(parents=True)
    db.initialize_workspace(root)
    settings = (
        f'[search]\nmode="{search}"\n[recall]\nenabled={str(recall).lower()}\n'
        f'[subagents]\nsetup_complete={str(delegation != "pending").lower()}\n'
        f'enabled={str(delegation != "disabled").lower()}\n'
        f'strategy="{delegation if delegation in {"conservative", "balanced", "aggressive"} else "balanced"}"\n'
        'preference="보존 우선"\n'
    )
    if profiles == "empty":
        settings += "profiles=[]\n"
    elif profiles == "custom":
        settings += ('[[subagents.profiles]]\nname="small"\ndescription="Routine"\n'
                     'characteristics="Independent"\ndelegation_bias="prefer"\n'
                     'candidates=[{model="example",reasoning_effort="high"}]\n')
    settings += '[subagents.models]\nexample=["high"]\n'
    (root / ".tapl/config.toml").write_text(settings)

    async def exercise():
        async with Client(mcp_server.create_server(workspace_root=root)) as client:
            full = (await client.call_tool("tapl_get_next", {})).structured_content
            current = config.load(start=root)
            assert full["workflow_policy"] == prompt.mcp_server_instructions(subagents=current.subagents)
            assert full["subagent_guidance"] == prompt.subagent_current_guidance(current.subagents)
            runtime = full["config"]
            assert set(runtime) == {"path", "exists", "workflow", "recall", "subagents"}
            assert runtime["path"] == current.path and runtime["exists"] == current.exists
            assert runtime["workflow"] == current.workflow.as_dict()
            assert runtime["recall"] == current.recall.as_dict()
            if current.subagents.setup_complete and current.subagents.enabled:
                assert runtime["subagents"] == {
                    **{key: value for key, value in current.subagents.as_dict().items()
                       if key != "available_models"},
                    "profiles": [profile.as_dict() for profile in current.subagents.profiles],
                }
            else:
                assert runtime["subagents"] == {"enabled": current.subagents.enabled,
                                                 "setup_complete": current.subagents.setup_complete}
            assert "model_changes" not in full
            cached = (await client.call_tool("tapl_get_next", {"known_policy_revision": full["policy_revision"]})).structured_content
            assert cached["policy_unchanged"] and "workflow_policy" not in cached
            assert cached["state_summary"] == full["state_summary"]
            assert cached["recommendations"] == full["recommendations"]
            lost = (await client.call_tool("tapl_get_next", {"known_policy_revision": "stale"})).structured_content
            assert lost == full
            incomplete = (await client.call_tool("tapl_get_next", {"available_models": {}})).structured_content
            assert incomplete["model_changes"]["comparison_status"] == "incomplete"
            assert not incomplete["model_changes"]["changed"]
            assert incomplete["workflow_policy"] == full["workflow_policy"]
            for detailed, events, limit in ((False, False, 12), (True, True, 0), (True, True, 100)):
                status = (await client.call_tool("tapl_get_status", {
                    "full": detailed, "include_events": events, "events_limit": limit,
                })).structured_content
                assert status["ok"]
                assert ("recent_events" in status) is events
                if events:
                    assert len(status["recent_events"]) <= limit
    asyncio.run(exercise())
