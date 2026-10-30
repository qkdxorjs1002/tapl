"""Auto authoring resolves only from the selected RUN snapshot."""
from __future__ import annotations

from copy import deepcopy
import tomllib
from unittest.mock import patch

import pytest

from taplctl import config, db, hooks, install, prompt, validation
from taplctl.application import WorkflowApplication


@pytest.mark.parametrize("mode,effective", [("fast", "minimal"), ("standard", "normal"), ("strict", "precise")])
def test_auto_maps_each_workflow_mode(mode, effective):
    assert config.resolve_authoring_detail("auto", mode) == effective
    assert config.authoring_policy("auto", mode) == {
        "configured": "auto", "effective": effective, "workflow_mode": mode,
    }


@pytest.mark.parametrize("mode", ["fast", "standard", "strict"])
@pytest.mark.parametrize("detail", config.EFFECTIVE_AUTHORING_DETAILS)
def test_explicit_levels_override_all_modes(detail, mode):
    assert config.resolve_authoring_detail(detail, mode) == detail
    assert config.authoring_policy(detail, mode)["configured"] == detail


def test_no_run_falls_back_to_normal_without_changing_configured_value():
    settings = config.from_mapping({}, path="missing.toml")
    assert settings.workflow.authoring_detail == "auto"
    assert config.authoring_policy("auto") == {
        "configured": "auto", "effective": "normal", "workflow_mode": None,
    }
    for detail in config.EFFECTIVE_AUTHORING_DETAILS:
        assert config.resolve_authoring_detail(detail) == detail
    assert settings.as_dict()["workflow"]["authoring_detail"] == "auto"


@pytest.mark.parametrize("mode", ["unknown", "STRICT", "", False, 1, [], {}])
@pytest.mark.parametrize("detail", config.AUTHORING_DETAILS)
def test_invalid_nonnull_mode_never_silently_falls_back(detail, mode):
    with pytest.raises(ValueError, match="Unknown workflow mode"):
        config.resolve_authoring_detail(detail, mode)
    with pytest.raises(ValueError, match="Unknown workflow mode"):
        config.authoring_policy(detail, mode)


@pytest.mark.parametrize("detail", ["unknown", "AUTO", "", None, True, [], {}])
def test_invalid_detail_is_rejected(detail):
    with pytest.raises(ValueError, match="Unknown authoring detail"):
        config.resolve_authoring_detail(detail)


@pytest.mark.parametrize("fallback", [False, True])
def test_generated_install_config_defaults_to_auto(tmp_path, fallback):
    if fallback:
        with patch.object(install, "template_text", return_value=None):
            template = install.default_config_text()
    else:
        template = install.default_config_text()
    assert tomllib.loads(template)["workflow"]["authoring_detail"] == "auto"
    destination = tmp_path / ".tapl/config.toml"
    install.write_tapl_config(destination, template, force=False, dry_run=False,
                              previous_version=None, tapl_config_policy="merge")
    assert config.load(destination).workflow.authoring_detail == "auto"


@pytest.mark.parametrize("detail", config.EFFECTIVE_AUTHORING_DETAILS)
def test_install_merge_preserves_existing_explicit_detail(tmp_path, detail):
    destination = tmp_path / "config.toml"
    destination.write_text(f'[workflow]\nauthoring_detail = "{detail}"\n')
    install.write_tapl_config(destination, install.default_config_text(), force=False, dry_run=False,
                              previous_version="old", tapl_config_policy="merge")
    assert config.load(destination).workflow.authoring_detail == detail


AUTHORING_PROVIDERS = (
    prompt.plan_detail_guidance, prompt.record_writing_guidance, prompt.plan_format_guidance,
    prompt.custom_fields_guidance, prompt.task_granularity_guidance, prompt.task_format_guidance,
)


@pytest.mark.parametrize("provider", AUTHORING_PROVIDERS)
def test_standalone_providers_resolve_auto_with_normal_fallback(provider):
    assert provider() == provider(authoring_detail="normal")
    with pytest.raises(ValueError):
        provider(authoring_detail="unknown")


@pytest.mark.parametrize("detail", config.EFFECTIVE_AUTHORING_DETAILS)
def test_template_providers_bind_every_selected_level_including_precise(detail):
    values = prompt.template_variables(authoring_detail=detail)
    assert values["plan_detail_guidance"] == prompt.plan_detail_guidance(authoring_detail=detail)
    assert values["plan_format_guidance"] == prompt.plan_format_guidance(authoring_detail=detail)
    assert values["task_fields_guidance"] == prompt.task_format_guidance(authoring_detail=detail)
    assert values["custom_fields_guidance"] == prompt.custom_fields_guidance(authoring_detail=detail)
    assert values["record_writing_guidance"] == prompt.record_writing_guidance(authoring_detail=detail)
    assert prompt.plan_detail_guidance(authoring_detail=detail) in prompt.mcp_server_instructions(authoring_detail=detail)


def test_standalone_policy_and_delegation_use_normal_fallback():
    assert prompt.mcp_server_instructions() == prompt.mcp_server_instructions(authoring_detail="normal")
    assert prompt.template_variables() == prompt.template_variables(authoring_detail="normal")
    settings = config.SubagentsConfig(enabled=True, setup_complete=True)
    assert prompt.subagent_current_guidance(settings) == prompt.subagent_current_guidance(settings, authoring_detail="normal")
    assert prompt.subagent_delegation_guidance(settings) == prompt.subagent_delegation_guidance(settings, authoring_detail="normal")
    assert "record executable-task decisions in canonical task fields" in prompt.subagent_current_guidance(settings, authoring_detail="precise")
    for detail in config.EFFECTIVE_AUTHORING_DETAILS:
        with patch.object(prompt, "subagent_delegation_guidance", wraps=prompt.subagent_delegation_guidance) as provider:
            prompt.mcp_server_instructions(subagents=settings, authoring_detail=detail)
        assert provider.call_args.kwargs["authoring_detail"] == detail


@pytest.mark.parametrize("event", ["SessionStart", "UserPromptSubmit", "Stop"])
@pytest.mark.parametrize("mode,effective", [(None, "normal"), ("fast", "minimal"), ("standard", "normal"), ("strict", "precise")])
def test_context_guidance_uses_the_provided_run_snapshot(event, mode, effective):
    state = {"active_run": {"workflow_mode": mode}} if mode else {"active_run": None}
    rendered = "\n".join(prompt.context_workflow_guidance(event=event, state=state))
    assert f"PLAN/TASK authoring detail: {effective}" in rendered


def state_with_one_task(mode, status="Pending"):
    return {
        "active_run": {"record_mode": "planned", "workflow_mode": mode},
        "plans": [{"stable_id": "PLAN-001", "status": "Finalized", "body": "REQ-001 Validation: verify"}],
        "tasks": [{"stable_id": "TASK-001", "spec_id": "PLAN-001", "status": status,
                   "goal": "Correct output", "action": "Update handler", "verification": "Focused tests",
                   "result": "Corrected", "blocker": "Unavailable dependency", "next_action": "Retry later"}],
    }


def issue_codes(result):
    return {issue["code"] for issue in result["issues"]}


@pytest.mark.parametrize("mode,effective", [("fast", "minimal"), ("standard", "normal"), ("strict", "precise")])
def test_validation_resolves_input_snapshot_for_checks_and_guidance(mode, effective):
    state = state_with_one_task(mode)
    original = deepcopy(state)
    result = validation.validate_workflow_state(state, include_guidance=True)
    assert result["authoring_policy"] == config.authoring_policy("auto", mode)
    assert result["guidance"] == validation.guidance(authoring_detail=effective)
    assert ("task_granularity_too_coarse" in issue_codes(result)) == (effective == "precise")
    assert state == original


def test_validation_without_run_exposes_normal_fallback():
    result = validation.validate_workflow_state({"active_run": None}, include_guidance=True)
    assert result["ok"]
    assert result["authoring_policy"] == config.authoring_policy("auto")
    assert result["guidance"] == validation.guidance(authoring_detail="normal")


@pytest.mark.parametrize("status", db.TERMINAL_TASK_STATUSES)
def test_strict_escalation_does_not_repartition_settled_history(status):
    state = state_with_one_task("strict", status=status)
    result = validation.validate_workflow_state(state)
    assert "task_granularity_too_coarse" not in issue_codes(result)
    assert "strict_plan_evidence_missing" not in issue_codes(result)


@pytest.mark.parametrize("status", [None, "Pending", "In Progress"])
def test_strict_warns_only_on_missing_typed_evidence_for_current_finalized_work(status):
    state = state_with_one_task("strict")
    if status is None:
        state["tasks"] = []
    else:
        state["tasks"][0]["status"] = status
    result = validation.validate_workflow_state(state)
    warnings = [issue for issue in result["warnings"] if issue["code"] == "strict_plan_evidence_missing"]
    assert len(warnings) == 1
    assert all(field in warnings[0]["message"] for field in ("risks", "affected_files", "validation"))
    assert "rollback/recovery" in warnings[0]["remediation"]
    assert "semantic" in warnings[0]["remediation"]
    state["plans"][0].update(risks="No external writes", affected_files="handler.py", validation="Focused tests")
    assert "strict_plan_evidence_missing" not in issue_codes(validation.validate_workflow_state(state))


def test_strict_evidence_excludes_drafts_archives_and_settled_plans_individually():
    state = state_with_one_task("strict", status="Completed")
    state["plans"].extend([
        {"stable_id": "PLAN-002", "status": "Draft"},
        {"stable_id": "PLAN-003", "status": "Finalized", "archived": True},
        {"stable_id": "PLAN-004", "status": "Finalized"},
    ])
    result = validation.validate_workflow_state(state)
    warnings = [issue for issue in result["warnings"] if issue["code"] == "strict_plan_evidence_missing"]
    assert [issue["stable_id"] for issue in warnings] == ["PLAN-004"]


@pytest.mark.parametrize("mode", ["fast", "standard"])
def test_non_strict_run_never_gets_strict_evidence_warning(mode):
    assert "strict_plan_evidence_missing" not in issue_codes(validation.validate_workflow_state(state_with_one_task(mode)))


@pytest.mark.parametrize("mode,effective", [("fast", "minimal"), ("standard", "normal"), ("strict", "precise")])
def test_fresh_active_hooks_resolve_auto_without_creating_records(tmp_path, mode, effective):
    (tmp_path / ".git").mkdir()
    db.initialize_workspace(tmp_path)
    (tmp_path / ".tapl/config.toml").write_text('[workflow]\nauthoring_detail="auto"\n[recall]\nenabled=false\n[subagents]\nenabled=false\nsetup_complete=true\n')
    app = WorkflowApplication(tmp_path)
    app.summarize_run("Inspect handler behavior", work_type="investigation", workflow_mode=mode)
    for event in ("SessionStart", "UserPromptSubmit"):
        with app._connection() as conn:
            result = hooks.handle_event(conn, event=event, mode="observe", tool=None, payload={}, tapl_settings=app._settings())
            assert f"PLAN/TASK authoring detail: {effective}" in result["message"]
            assert result["context"]["authoring_policy"] == config.authoring_policy("auto", mode)
            state = db.status_payload(conn)
            assert state["plans"] == [] and state["tasks"] == []
