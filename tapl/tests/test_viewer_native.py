from __future__ import annotations

import tempfile
from pathlib import Path
from unittest import mock

import pytest

from taplctl import db, viewer
from taplctl.application import WorkflowApplication


def test_native_runner_maps_viewer_reads_to_database_operations() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(tmp) / "workspace"
        db.initialize_workspace(workspace)
        workflow = WorkflowApplication(workspace)
        workflow.summarize_run("native viewer reads")
        workflow.apply_plan(
            "PLAN-001",
            title="Native viewer plan",
            status="Finalized",
            summary="Read without a CLI child process.",
            objective="Exercise the native viewer runner.",
            requirements_trace="TASK-004",
            selected_approach="Use direct database read APIs.",
            affected_files="taplctl/viewer.py",
            execution_order="read, verify",
            risks="response shape drift",
            validation="viewer native test",
        )

        runner = viewer.NativeJsonRunner()
        db_path = workspace / db.DEFAULT_DB_RELATIVE
        full_status = runner(db_path, ["status", "--json", "--full"])
        plan = full_status["plans"][0]
        native_viewer = viewer.ViewerApplication(default_workspace=workspace)
        overview = native_viewer.handle_message({"command": "ready"})

        assert full_status["active_run"] is not None
        assert plan["stable_id"] == "PLAN-001"
        assert overview["view"]["status"]["plans"][0]["stable_id"] == "PLAN-001"
        assert (
            runner(db_path, ["item", "show", "--id", str(plan["id"])])["item"]["title"]
            == "Native viewer plan"
        )
        assert runner(db_path, ["search", "Native", "--json"])["query"] == "Native"

        archive = workflow.finish_archive("native-viewer", summary="Archived for viewer test")["archive"]
        archives = runner(db_path, ["archive", "list", "--json", "--limit", "8"])
        detail = runner(db_path, ["archive", "show", "--id", archive["id"], "--json"])

        assert archives["archives"][0]["id"] == archive["id"]
        assert detail["archive"]["slug"] == "native-viewer"
        assert detail["items"][0]["stable_id"] == "PLAN-001"


def test_native_runner_supports_an_explicit_database_outside_a_workspace() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "explicit.db"
        db.connect(db_path).close()

        status = viewer.run_native_json(db_path, ["status", "--json", "--include-events"])

        assert status["active_run"] is None
        assert status["recent_events"] == []


def test_native_viewer_validation_uses_selected_authoring_detail(tmp_path) -> None:
    db.initialize_workspace(tmp_path)
    workflow = WorkflowApplication(tmp_path)
    workflow.summarize_run("Update handler", work_type="implementation", workflow_mode="standard")
    workflow.apply_plan("PLAN-001", objective="Fix handler", requirements_trace="REQ-001",
                        selected_approach="Update handler and test", validation="Run regression test")
    workflow.create_task("TASK-001", "Fix handler", "PLAN-001", "Correct output",
                         "Update handler and regression test", "Run regression test")
    runner = viewer.NativeJsonRunner()
    path = tmp_path / db.DEFAULT_DB_RELATIVE
    for detail in ("normal", "minimal", "precise"):
        (tmp_path / ".tapl/config.toml").write_text(
            f'[workflow]\nauthoring_detail = "{detail}"\n', encoding="utf-8",
        )
        status = runner(path, ["status", "--json"])
        issues = {item["code"] for item in status["plan_task_execute"]["issues"]}
        assert ("task_granularity_too_coarse" in issues) == (detail == "precise")
        assert status["config"]["workflow"]["authoring_detail"] == detail


@pytest.mark.parametrize("mode,effective", [("fast", "minimal"), ("standard", "normal"), ("strict", "precise")])
def test_native_viewer_auto_policy_follows_selected_run_snapshot(tmp_path, mode, effective) -> None:
    db.initialize_workspace(tmp_path)
    (tmp_path / ".tapl/config.toml").write_text('[workflow]\nauthoring_detail="auto"\n', encoding="utf-8")
    workflow = WorkflowApplication(tmp_path)
    workflow.summarize_run("Review selected run", work_type="analysis", workflow_mode=mode)
    runner = viewer.NativeJsonRunner()
    for args in (["status", "--json"], ["status", "--json", "--full"]):
        with mock.patch.object(db, "status_payload", wraps=db.status_payload) as snapshots:
            status = runner(tmp_path / db.DEFAULT_DB_RELATIVE, args)
        assert snapshots.call_count == 1
        assert status["authoring_policy"] == {
            "configured": "auto", "effective": effective, "workflow_mode": mode,
        }
        assert status["plan_task_execute"]["authoring_policy"] == status["authoring_policy"]
        assert status["config"]["workflow"]["authoring_detail"] == "auto"


def test_native_viewer_auto_policy_uses_owner_selection_and_empty_fallback(tmp_path) -> None:
    db.initialize_workspace(tmp_path)
    (tmp_path / ".tapl/config.toml").write_text('[workflow]\nauthoring_detail="auto"\n', encoding="utf-8")
    path = tmp_path / db.DEFAULT_DB_RELATIVE
    runner = viewer.NativeJsonRunner()
    assert runner(path, ["status"])["authoring_policy"] == {
        "configured": "auto", "effective": "normal", "workflow_mode": None,
    }
    owner = WorkflowApplication(tmp_path, session_id="strict-owner")
    owner.summarize_run("Review public contract", work_type="analysis", workflow_mode="strict")
    status = runner(path, ["status"])
    assert status["session_id"] == "strict-owner"
    assert status["authoring_policy"]["effective"] == "precise"
    assert status["plan_task_execute"]["authoring_policy"] == status["authoring_policy"]
