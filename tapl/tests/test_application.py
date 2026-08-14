from __future__ import annotations

import tempfile
from pathlib import Path

from taplctl import db, mcp_server
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


def test_application_derives_record_mode_from_work_type_and_workflow_mode() -> None:
    cases = (
        ("answer", "fast", "lightweight"),
        ("implementation", "fast", "planned"),
        ("analysis", "standard", "planned"),
        ("planning", "strict", "planned"),
    )
    for work_type, workflow_mode, expected_record_mode in cases:
        with tempfile.TemporaryDirectory() as tmp:
            _, app = workspace(tmp)
            summarized = app.summarize_run(
                "classify workflow state",
                work_type=work_type,
                workflow_mode=workflow_mode,
            )
            run = summarized["active_run"]
            assert run["work_type"] == work_type
            assert run["workflow_mode"] == workflow_mode
            assert run["record_mode"] == expected_record_mode


def test_applying_plan_promotes_only_record_mode() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        _, app = workspace(tmp)
        app.summarize_run(
            "investigate a small issue",
            work_type="investigation",
            workflow_mode="fast",
        )
        app.apply_plan("PLAN-001", title="Escalated investigation", status="Finalized")

        run = app.get_status()["active_run"]
        assert run["work_type"] == "investigation"
        assert run["workflow_mode"] == "fast"
        assert run["record_mode"] == "planned"


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


def test_plan_without_tasks_offers_execution_or_non_execution_completion() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        _, app = workspace(tmp)
        app.summarize_run("analyze and report without implementation")
        app.apply_plan(
            "PLAN-001",
            title="Analysis plan",
            status="Completed",
            summary="REQ-001: explain the current behavior",
            objective="Report findings without durable edits.",
            requirements_trace="REQ-001",
            selected_approach="Inspect the relevant code path.",
            affected_files="None",
            execution_order="Inspect, summarize.",
            risks="None",
            validation="Cite the decisive code path.",
        )

        next_payload = app.get_next()
        assert next_payload["recommendations"] == [
            {
                "name": "decide-after-plan",
                "reason": (
                    "The plan has no executable tasks. Finish the run for analysis, planning, or reporting scope; "
                    "create a task only when execution was explicitly requested."
                ),
            }
        ]

        mcp_payload = mcp_server.mcp_next_recommendations(next_payload)
        assert mcp_payload["recommendations"][0]["tool"] == [
            "tapl_create_task",
            "tapl_finish_run",
        ]


def test_application_missing_item_has_actionable_error() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        _, app = workspace(tmp)
        try:
            app.get_item(999)
        except RuntimeError as exc:
            assert str(exc) == "item not found: 999"
        else:
            raise AssertionError("missing item must fail")


def test_application_dispatches_and_settles_an_approved_parallel_batch() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        _, app = workspace(tmp)
        app.summarize_run("parallel application workflow")
        app.apply_plan(
            "PLAN-001",
            title="Parallel plan",
            status="Finalized",
            summary="REQ-001: dispatch independent tasks.",
            objective="Exercise the native parallel execution boundary.",
            requirements_trace="REQ-001",
            selected_approach="Dispatch two owned-path tasks.",
            affected_files="src/a.py, src/b.py",
            execution_order="approve, dispatch, settle",
            risks="Execution ids must remain paired with their task.",
            validation="Focused application test.",
        )
        for task_id, owned_path in (("TASK-001", "src/a.py"), ("TASK-002", "src/b.py")):
            app.create_task(
                task_id,
                f"Parallel {task_id}",
                "PLAN-001",
                f"Complete {task_id}",
                f"Implement {task_id}",
                f"Verify {task_id}",
                execution_mode="parallel",
                executor_kind="subagent",
                parallel_group="workers",
                owned_paths=[owned_path],
            )
        app.record_approval(
            decision="approved", prompt="Execute parallel tasks", source="explicit_user"
        )

        manifest = app.dispatch_tasks(["TASK-001", "TASK-002"], batch_id="BATCH-001")
        executions = {row["task_id"]: row["execution_id"] for row in manifest["executions"]}
        assert set(executions) == {"TASK-001", "TASK-002"}

        for task_id, execution_id in executions.items():
            receipt = app.settle_task(
                task_id,
                status="Completed",
                execution_id=execution_id,
                verification=f"Verified {task_id}",
                result=f"Completed {task_id}",
            )
            assert receipt["settled_execution_id"] == execution_id

        assert app.get_status(full=True)["active_batches"] == []
