"""Behavior contracts for smaller MCP entry instructions and lazy rendering."""
from __future__ import annotations

import asyncio
from string import Template
from unittest import mock

from mcp import Client
import pytest

from taplctl import config, db, mcp_server, prompt


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
    for requirement in (
        "including read-only helpers", "`tapl_get_next` once", "complete `workflow_policy`",
        "`subagent_guidance`, and config", "No project work or TAPL mutations",
        "recommendations do not replace", "wait for a concrete request",
        "Omit model-catalog arguments", "after compaction or policy loss",
        "no `known_policy_revision`", "a summary is insufficient",
        "Only tool discovery and required local-instruction discovery may precede policy loading",
        "discover only needed tool declarations", "`result.structuredContent`", "parsed text fallback",
    ):
        assert requirement in entry
    assert "Root alone writes TAPL state" in prompt.mcp_bootstrap_instructions()
    for shape in ("canonical JSON objects", "`Task Profile` {name, match_reason}",
                  "delegation_reason", "when selecting a model",
                  "Existing rationale aliases remain accepted"):
        assert shape in prompt.custom_fields_guidance()
    assert "Group by requested outcome, not file or execution unit" in prompt.request_partition_guidance()
    assert "correct mistaken plan splitting" in prompt.request_partition_guidance()
    assert "the same PLAN and `parallel_group`" in prompt.task_execution_order_guidance()


def test_code_mode_optimization_keeps_decision_and_recovery_gates():
    policy = prompt.mcp_server_instructions()
    for contract in (
        "unique description and full schema", "exact repeated server preamble already retained",
        "reload after loss or change", "Sequentially await", "checking every result",
        "Stop on errors or new decisions", "honor validation before execution",
        "Preserve approval, source checks, verification and dispatch gates",
        "never predict results", "Yield after finish to inspect memory before archive",
        "tapl_get_item(compact=true)", "full formatted bodies remain available",
    ):
        assert contract in policy


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
            assert full["config"] == current.as_dict()
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
