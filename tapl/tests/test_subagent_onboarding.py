from __future__ import annotations

import asyncio
from pathlib import Path

from mcp import Client
import pytest

from taplctl import config, db, mcp_server
from taplctl.application import WorkflowApplication, WorkflowApplicationError


def fresh_workspace(tmp_path: Path) -> tuple[Path, WorkflowApplication]:
    root = tmp_path / "workspace"
    (root / ".git").mkdir(parents=True)
    db.initialize_workspace(root)
    return root, WorkflowApplication(root)


def test_first_use_requires_an_answer_and_does_not_create_a_config(tmp_path: Path) -> None:
    root, app = fresh_workspace(tmp_path)
    path = root / ".tapl/config.toml"
    next_action = app.get_next(available_models={"future-runtime": ["careful"]})
    assert next_action["recommendations"][0]["name"] == "configure-subagents"
    assert not path.exists()
    session = app.get_context(event="SessionStart")
    assert "first concrete user request" in " ".join(session["workflow_guidance"])
    request = app.get_context(event="UserPromptSubmit")
    assert "Wait for the actual answer" in " ".join(request["workflow_guidance"])
    assert "Only after the user completes setup" in " ".join(request["workflow_guidance"])
    with pytest.raises(WorkflowApplicationError, match="Ask the user"):
        app.configure_subagents(
            user_confirmed=False, enabled=True, strategy="balanced",
            models={"future-runtime": ["careful"]},
        )
    assert not path.exists()
    with pytest.raises(WorkflowApplicationError, match="completed, enabled setup"):
        app.dispatch_tasks(["TASK-001", "TASK-002"])


def test_model_catalog_changes_are_read_only_and_keep_acknowledges_them(tmp_path: Path) -> None:
    root, app = fresh_workspace(tmp_path)
    catalog = {"future-runtime": ["careful", "quick"], "small-runtime": ["quick"]}
    selection = dict(
        user_confirmed=True, enabled=True, strategy="balanced",
        models={"future-runtime": ["careful"]}, preference="품질 우선", profiles=[],
    )
    saved = app.configure_subagents(**selection, available_models=catalog)
    assert saved["subagents"]["setup_complete"]
    assert "품질 우선" in saved["subagent_guidance"]
    path = root / ".tapl/config.toml"
    original = path.read_bytes()
    same = app.get_next(available_models={"small-runtime": ["quick"], "future-runtime": ["quick", "careful"]})
    assert not same["model_changes"]["changed"]
    current = {"future-runtime": ["careful", "deep"], "new-runtime": ["quick"]}
    updated = app.get_next(available_models=current)
    assert updated["model_changes"] == {
        "baseline_recorded": True, "changed": True,
        "added": ["new-runtime"], "removed": ["small-runtime"],
        "reasoning_efforts_changed": ["future-runtime"],
    }
    assert updated["recommendations"][0]["name"] == "review-subagent-models"
    assert path.read_bytes() == original
    app.configure_subagents(**selection, available_models=current)
    assert not app.get_next(available_models=current)["model_changes"]["changed"]
    assert app.get_status()["config"]["subagents"]["models"] == selection["models"]
    assert config.load(path).subagents.profiles == ()
    # Ordinary preference writes and setup updates without a new catalog keep
    # the last confirmed baseline, even across process restarts.
    app.configure_subagents(**selection)
    restarted = WorkflowApplication(root)
    assert not restarted.get_next(available_models=current)["model_changes"]["changed"]


def test_catalog_empty_and_missing_are_distinct(tmp_path: Path) -> None:
    _, app = fresh_workspace(tmp_path)
    catalog = {"future-runtime": ["careful"]}
    app.configure_subagents(
        user_confirmed=True, enabled=True, strategy="balanced", models=catalog,
        available_models=catalog,
    )
    assert "model_changes" not in app.get_next()
    empty = app.get_next(available_models={})
    assert empty["model_changes"]["removed"] == ["future-runtime"]
    assert empty["model_changes"]["changed"]


def test_new_selections_must_be_in_the_observed_catalog(tmp_path: Path) -> None:
    root, app = fresh_workspace(tmp_path)
    with pytest.raises(WorkflowApplicationError, match="current delegation-tool catalog"):
        app.configure_subagents(
            user_confirmed=True, enabled=True, strategy="balanced",
            models={"invented-model": ["high"]}, available_models={"actual-model": ["high"]},
        )
    assert not (root / ".tapl/config.toml").exists()


def test_disabled_choice_is_complete_and_legacy_allowlists_are_preserved(tmp_path: Path) -> None:
    root, app = fresh_workspace(tmp_path)
    app.configure_subagents(
        user_confirmed=True, enabled=False, strategy="conservative", models={},
        available_models={}, preference="root만 사용", profiles=[],
    )
    assert app.get_status()["config"]["subagents"]["setup_complete"]
    assert not any(item["name"] in {"configure-subagents", "review-subagent-models"}
                   for item in app.get_next(available_models={"new": ["high"]})["recommendations"])
    with pytest.raises(WorkflowApplicationError, match="completed, enabled setup"):
        app.dispatch_tasks(["TASK-001", "TASK-002"])
    path = root / ".tapl/config.toml"
    legacy = '[subagents.models]\n"legacy-choice" = ["high"]\n'
    path.write_text(legacy, encoding="utf-8")
    state = app.get_next(available_models={"current-runtime": ["careful"]})
    assert state["config"]["subagents"]["setup_complete"]
    assert not state["model_changes"]["baseline_recorded"]
    assert not state["model_changes"]["changed"]
    assert path.read_text(encoding="utf-8") == legacy


def test_setup_uses_effective_path_and_preserves_other_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root, app = fresh_workspace(tmp_path)
    global_path = tmp_path / "user-config.toml"
    global_path.write_text('# keep this comment\n[search]\nmode = "bm25"\n', encoding="utf-8")
    monkeypatch.setattr(config, "user_config_path", lambda home=None: global_path)
    result = app.configure_subagents(
        user_confirmed=True, enabled=False, strategy="conservative", models={}, available_models={},
    )
    assert result["path"] == str(global_path)
    assert '# keep this comment\n[search]\nmode = "bm25"\n' in global_path.read_text(encoding="utf-8")
    assert not (root / ".tapl/config.toml").exists()
    local_path = root / ".tapl/config.toml"
    local_path.write_text('[search]\nmode = "word"\n', encoding="utf-8")
    assert app.get_next()["config"]["path"] == str(local_path)


def test_mcp_setup_and_catalog_refresh_take_effect_without_restarting(tmp_path: Path) -> None:
    root, _ = fresh_workspace(tmp_path)
    server = mcp_server.create_server(workspace_root=root)

    async def exercise() -> None:
        async with Client(server) as client:
            before = await client.call_tool("tapl_get_next", {})
            assert before.structured_content["recommendations"][0]["tool"] == "request_user_input"
            args = dict(
                user_confirmed=False, enabled=True, strategy="balanced",
                models={"runtime-a": ["high"]}, available_models={"runtime-a": ["high"]},
                preference="quality", profiles=[],
            )
            rejected = await client.call_tool("tapl_configure_subagents", args)
            assert rejected.is_error
            assert not (root / ".tapl/config.toml").exists()
            args["user_confirmed"] = True
            saved = await client.call_tool("tapl_configure_subagents", args)
            assert not saved.is_error
            assert saved.structured_content["operation"] == "subagents_configure"
            assert "runtime-a[high]" in saved.structured_content["subagent_guidance"]
            assert saved.structured_content["subagents"]["available_models"] == args["available_models"]
            next_action = await client.call_tool("tapl_get_next", {"available_models": {"runtime-b": ["deep"]}})
            assert next_action.structured_content["recommendations"][0]["tool"] == "request_user_input"
            assert next_action.structured_content["model_changes"]["changed"]

    asyncio.run(exercise())
