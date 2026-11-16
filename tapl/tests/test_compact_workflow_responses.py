"""Execution projections and their policy identity stay independent of settings UI."""
from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path

from mcp import Client
import pytest

from taplctl import clients, config, db, mcp_server, prompt
from taplctl.application import WorkflowApplication


@pytest.fixture
def application(tmp_path: Path) -> WorkflowApplication:
    (tmp_path / ".git").mkdir()
    db.initialize_workspace(tmp_path)
    return WorkflowApplication(tmp_path)


def selected_settings(app: WorkflowApplication) -> config.TaplConfig:
    profiles = [
        {"name": "specific-custom-profile", "description": "Preserve exact routing evidence",
         "characteristics": "Independent implementation", "delegation_bias": "inherit",
         "candidates": [{"model": "selected-runtime", "reasoning_effort": "high"},
                        {"model": "selected-runtime", "reasoning_effort": "low"}]},
        {"name": "second-custom-profile", "characteristics": "Broader implementation",
         "delegation_bias": "avoid", "candidates": []},
    ]
    return config.from_mapping({"subagents": {
        "setup_complete": True, "enabled": True, "strategy": "aggressive",
        "preference": "Preserve this unique confirmed priority.",
        "models": {"selected-runtime": ["high", "low"]}, "profiles": profiles,
        "available_models": {"selected-runtime": ["high", "low"], "unselected-runtime": ["high"]},
    }}, path=app.workspace_root / ".tapl/config.toml")


def test_execution_values_live_once_in_structured_config_and_hooks_remain_complete(application, monkeypatch):
    settings = selected_settings(application)
    monkeypatch.setattr(application, "_settings", lambda: settings)
    result = application.get_next()
    runtime = result["config"]["subagents"]
    assert runtime["profiles"] == [profile.as_dict() for profile in settings.subagents.profiles]
    assert runtime["models"] == {"selected-runtime": ["high", "low"]}
    assert runtime["strategy"] == "aggressive"
    assert runtime["preference"] == settings.subagents.preference
    assert "available_models" not in runtime
    for text in (result["workflow_policy"], result["subagent_guidance"]):
        for actual_value in (settings.subagents.preference, "selected-runtime", "specific-custom-profile"):
            assert actual_value not in text
    assert "most specific wins, order breaks ties" in result["subagent_guidance"]
    assert "bias inherit=global strategy" in result["subagent_guidance"]
    standalone = prompt.subagent_delegation_guidance(settings.subagents)
    assert settings.subagents.preference in standalone
    assert "selected-runtime" in standalone and "specific-custom-profile" in standalone
    # Detailed application/settings/Viewer reads preserve the full serializer.
    assert application.get_status()["config"] == settings.as_dict()
    assert "available_models" in settings.as_dict()["subagents"]


@pytest.mark.parametrize("field,value", [
    ("search", config.SearchConfig(mode="word", max_results=77)),
    ("viewer", config.ViewerConfig(language="ko", layout="large", mcp_path="other-mcp")),
    ("catalog", (config.SubagentModelConfig("different-catalog-only", ("high",)),)),
])
def test_omitted_settings_do_not_invalidate_policy_revision(application, monkeypatch, field, value):
    settings = selected_settings(application)
    monkeypatch.setattr(application, "_settings", lambda: settings)
    before = application.get_next()
    settings = (replace(settings, subagents=replace(settings.subagents, available_models=value))
                if field == "catalog" else replace(settings, **{field: value}))
    after = application.get_next(known_policy_revision=before["policy_revision"])
    assert after["policy_unchanged"]
    assert after["policy_revision"] == before["policy_revision"]
    assert "config" not in after and "workflow_policy" not in after


@pytest.mark.parametrize("field,value", [
    ("path", "other-effective-config.toml"), ("exists", False),
    ("workflow", config.WorkflowConfig(authoring_detail="minimal")),
    ("recall", config.RecallConfig(enabled=False)),
    ("strategy", "conservative"), ("preference", "Changed confirmed priority"),
    ("models", (config.SubagentModelConfig("selected-runtime", ("high",)),)),
    ("profiles", ()), ("enabled", False), ("setup_complete", False),
])
def test_delivered_settings_invalidate_policy_revision(application, monkeypatch, field, value):
    settings = selected_settings(application)
    monkeypatch.setattr(application, "_settings", lambda: settings)
    before = application.get_next()
    settings = (replace(settings, **{field: value}) if field in {"path", "exists", "workflow", "recall"}
                else replace(settings, subagents=replace(settings.subagents, **{field: value})))
    after = application.get_next(known_policy_revision=before["policy_revision"])
    assert not after["policy_unchanged"]
    assert after["policy_revision"] != before["policy_revision"]
    assert {"config", "workflow_policy", "subagent_guidance"} <= after.keys()


@pytest.mark.parametrize("enabled,complete", [(True, False), (False, False), (False, True)])
def test_pending_and_disabled_omit_inactive_routing_settings(application, monkeypatch, enabled, complete):
    settings = selected_settings(application)
    settings = replace(settings, subagents=replace(settings.subagents, enabled=enabled, setup_complete=complete))
    monkeypatch.setattr(application, "_settings", lambda: settings)
    result = application.get_next()
    assert result["config"]["subagents"] == {"enabled": enabled, "setup_complete": complete}
    assert "selected-runtime" not in result["subagent_guidance"]
    assert "root agent" in result["subagent_guidance"]
    assert "read `tapl_get_settings` or `taplctl config get`" in result["subagent_guidance"]
    assert "preserve unrelated saved values" in result["subagent_guidance"]
    assert "never guess them" in result["subagent_guidance"]
    assert application.get_status()["config"]["subagents"]["models"] == {"selected-runtime": ["high", "low"]}
    assert application.get_status()["config"]["subagents"]["preference"] == settings.subagents.preference
    if not complete:
        assert "config.subagents.setup_complete" in result["subagent_guidance"]
        assert result["recommendations"][0]["name"] == "configure-subagents"


@pytest.mark.parametrize("enabled,complete", [(True, False), (False, True)])
def test_inactive_routing_changes_do_not_invalidate_execution_policy(application, monkeypatch, enabled, complete):
    settings = selected_settings(application)
    settings = replace(settings, subagents=replace(settings.subagents, enabled=enabled, setup_complete=complete))
    monkeypatch.setattr(application, "_settings", lambda: settings)
    before = application.get_next()
    settings = replace(settings, subagents=replace(
        settings.subagents, strategy="conservative", preference="Inactive saved priority changed",
        models=(config.SubagentModelConfig("different-inactive-runtime", ("high",)),), profiles=(),
    ))
    after = application.get_next(known_policy_revision=before["policy_revision"])
    assert after["policy_unchanged"]
    assert after["policy_revision"] == before["policy_revision"]
    assert "config" not in after


def test_claude_catalog_deltas_distinguish_absence_from_unspecified_effort(application):
    with clients.client_scope("claude-code"):
        application.configure_subagents(
            user_confirmed=True, enabled=True, strategy="balanced", models={"inherit": []}, profiles=[],
            available_models={"removed-alias": [], "changed-alias": []},
        )
        before = application.get_next()
        runtime = before["config"]
        assert runtime["client"] == "claude-code"
        assert runtime["subagents_config_key"] == "clients.claude-code.subagents"
        assert runtime["subagents"]["models"] == {"inherit": []}
        assert runtime["subagents"]["profiles"] == []
        assert "selection_semantics" in runtime["subagents"]
        assert "For inherit omit Agent.model" in before["subagent_guidance"]
        assert "For [] omit Agent.effort" in before["subagent_guidance"]
        assert "must not be rejected for catalog absence" in before["subagent_guidance"]
        result = application.get_next(
            available_models={"added-alias": [], "changed-alias": ["high"]}, catalog_complete=True,
            known_policy_revision=before["policy_revision"],
        )
    assert result["model_changes"] == {
        "baseline_recorded": True, "comparison_status": "compared", "changed": True,
        "changes": [{"model": "added-alias", "before": None, "after": []},
                    {"model": "changed-alias", "before": [], "after": ["high"]},
                    {"model": "removed-alias", "before": [], "after": None}],
    }
    assert not result["policy_unchanged"]
    assert result["policy_revision"] == before["policy_revision"]
    assert result["config"] == before["config"]
    assert "available_models" not in result["config"]["subagents"]


def test_claude_configure_receipt_applies_current_settings_without_another_entry(application):
    async def exercise():
        async with Client(mcp_server.create_server(workspace_root=application.workspace_root,
                                                  client="claude-code")) as client:
            args = {"session_id": "claude-code:compact-response-test"}
            await client.call_tool("tapl_get_next", args)
            saved = (await client.call_tool("tapl_configure_subagents", {
                **args, "user_confirmed": True, "enabled": True, "strategy": "conservative",
                "models": {"sonnet": []}, "available_models": {"sonnet": []}, "profiles": [],
                "preference": "Keep current Claude priorities.",
            })).structured_content
            assert saved["client"] == "claude-code"
            assert saved["subagents_config_key"] == "clients.claude-code.subagents"
            assert saved["subagents"]["setup_complete"]
            assert saved["subagents"]["models"] == {"sonnet": []}
            assert saved["subagents"]["profiles"] == []
            assert saved["subagents"]["available_models"] == {"sonnet": []}
            assert "selection_semantics" in saved["subagents"]
            assert "`subagents`" in saved["subagent_guidance"]
            assert "config.subagents" not in saved["subagent_guidance"]
            assert "Keep current Claude priorities." not in saved["subagent_guidance"]
    asyncio.run(exercise())
