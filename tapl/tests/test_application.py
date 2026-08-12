from __future__ import annotations

import tempfile
from pathlib import Path

from taplctl import db
from taplctl.application import WorkflowApplication


def workspace(tmp: str) -> tuple[Path, WorkflowApplication]:
    root = Path(tmp) / "workspace"
    (root / ".git").mkdir(parents=True)
    db.initialize_workspace(root)
    return root, WorkflowApplication(root)


def test_application_runs_sequential_workflow_without_cli_process() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        _, app = workspace(tmp)
        summarized = app.summarize_run("native application workflow")
        assert summarized["active_run"]["request_summary"] == "native application workflow"

        app.apply_plan(
            "PLAN-001",
            title="Native plan",
            status="Finalized",
            summary="REQ-001: direct calls",
            objective="Remove the CLI data plane",
            requirements_trace="REQ-001",
            selected_approach="WorkflowApplication",
            affected_files="application.py",
            execution_order="implement, verify",
            risks="compatibility",
            validation="pytest",
        )
        app.create_task(
            "TASK-001",
            "Native task",
            "PLAN-001",
            "exercise direct writes",
            "call the application",
            "state is complete",
            custom_fields={"owner": "mcp", "remove": "later"},
        )
        app.start_task("TASK-001")
        completed = app.settle_task(
            "TASK-001",
            status="Completed",
            verification="focused test passed",
            result="done",
            custom_fields={"remove": None},
        )
        assert completed["item"]["status"] == "Completed"
        task = app.get_status(full=True)["tasks"][0]
        assert task["custom_fields"] == {"owner": "mcp"}
        assert app.get_context()["active_run"]["present"] is True


def test_application_uses_fresh_connection_for_each_call() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        _, app = workspace(tmp)
        app.summarize_run("connection lifecycle")
        first = app.get_status()
        second = app.get_status()
        assert first["active_run"]["id"] == second["active_run"]["id"]


def test_application_partial_updates_preserve_omitted_fields_and_nested_null_deletes() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        _, app = workspace(tmp)
        app.summarize_run("partial update semantics")
        app.apply_plan(
            "PLAN-001",
            title="Original title",
            objective="Keep this objective",
            custom_fields={"keep": "value", "remove": "old"},
        )

        app.apply_plan(
            "PLAN-001",
            summary="Only this field changes",
            title=None,
            custom_fields={"remove": None},
        )

        plan = app.get_status(full=True)["plans"][0]
        assert plan["title"] == "Original title"
        assert plan["objective"] == "Keep this objective"
        assert plan["summary"] == "Only this field changes"
        assert plan["custom_fields"] == {"keep": "value"}


def test_application_missing_item_has_actionable_error() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        _, app = workspace(tmp)
        try:
            app.get_item(999)
        except RuntimeError as exc:
            assert str(exc) == "item not found: 999"
        else:
            raise AssertionError("missing item must fail")
