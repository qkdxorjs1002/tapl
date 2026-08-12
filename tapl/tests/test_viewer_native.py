from __future__ import annotations

import tempfile
from pathlib import Path

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
