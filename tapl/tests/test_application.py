from __future__ import annotations

import tempfile
from pathlib import Path
from unittest import mock

from taplctl import db, hooks, mcp_server, prompt, validation
from taplctl.application import WorkflowApplication


def workspace(tmp: str) -> tuple[Path, WorkflowApplication]:
    root = Path(tmp) / "workspace"
    (root / ".git").mkdir(parents=True)
    db.initialize_workspace(root)
    (root / ".tapl/config.toml").write_text(
        '[subagents.models]\n"gpt-5.6-sol" = ["xhigh"]\n"gpt-5.6-terra" = ["high"]\n"gpt-5.6-luna" = ["xhigh"]\n',
        encoding="utf-8",
    )
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


def test_next_policy_revision_requires_explicit_retention_and_keeps_actions_fresh() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        _, app = workspace(tmp)
        app.summarize_run("Read the workflow")
        full = app.get_next()
        assert full["workflow_policy"] == prompt.mcp_server_instructions(subagents=app._settings().subagents)
        assert not full["policy_unchanged"]
        revision = full["policy_revision"]
        cached = app.get_next(known_policy_revision=revision)
        assert cached["policy_unchanged"]
        assert cached["policy_revision"] == revision
        assert cached["recommendations"] == full["recommendations"]
        assert not {"workflow_policy", "config", "subagent_guidance"} & cached.keys()
        app.apply_plan("PLAN-001", title="Plan")
        advanced = app.get_next(known_policy_revision=revision)
        assert advanced["policy_unchanged"]
        assert advanced["recommendations"] != cached["recommendations"]
        assert advanced["recommendations"] == app.get_next_actions()["recommendations"]
        for known in (None, "", "unknown"):
            restored = app.get_next(known_policy_revision=known)
            assert not restored["policy_unchanged"]
            for key in ("workflow_policy", "config", "subagent_guidance"):
                assert restored[key] == full[key]
        assert not WorkflowApplication(app.workspace_root).get_next()["policy_unchanged"]


def test_next_policy_revision_invalidates_every_delivered_policy_component() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root, app = workspace(tmp)
        full = app.get_next()
        revision = full["policy_revision"]
        for renderer in ("mcp_server_instructions", "subagent_current_guidance"):
            with mock.patch.object(prompt, renderer, return_value="Updated policy text"):
                changed = app.get_next(known_policy_revision=revision)
                assert not changed["policy_unchanged"]
                assert changed["policy_revision"] != revision
        config_file = root / ".tapl/config.toml"
        config_file.write_text('[subagents]\nenabled=false\nsetup_complete=true\n', encoding="utf-8")
        changed = app.get_next(known_policy_revision=revision)
        assert not changed["policy_unchanged"]
        assert changed["policy_revision"] != revision
        assert changed["config"]["subagents"]["enabled"] is False
        assert "disabled" in changed["subagent_guidance"]


def test_next_catalog_changes_resend_policy_even_with_matching_revision() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        _, app = workspace(tmp)
        catalog = {"model-a": ["high"]}
        app.configure_subagents(user_confirmed=True, enabled=True, strategy="balanced", models=catalog, available_models=catalog)
        full = app.get_next(available_models=catalog)
        same = app.get_next(available_models=catalog, known_policy_revision=full["policy_revision"])
        assert same["policy_unchanged"]
        assert not same["model_changes"]["changed"]
        changed = app.get_next(available_models={"model-a": ["high", "xhigh"]}, known_policy_revision=full["policy_revision"])
        assert not changed["policy_unchanged"]
        assert changed["model_changes"]["changed"]
        assert changed["workflow_policy"] == full["workflow_policy"]
        assert changed["config"] == full["config"]
        assert changed["recommendations"][0]["name"] == "review-subagent-models"


def test_inspection_validates_one_snapshot_and_preserves_blockers() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        _, app = workspace(tmp)
        app.summarize_run("Unapproved work")
        app.apply_plan("PLAN-001", summary="REQ-001", validation="Check approvals")
        for number in (1, 2):
            app.create_task(f"TASK-{number:03d}", "Task", "PLAN-001", "Goal", "Edit", "Verify")
        with app._connection() as conn:
            expected = validation.validate_plan_task_execute(conn)
        assert any(issue["code"] == "execution_approval_missing" for issue in expected["issues"])
        for inspect in (app.get_status, app.get_context, app.get_next, app.get_next_actions):
            with mock.patch.object(db, "status_payload", wraps=db.status_payload) as snapshots:
                result = inspect()
            assert snapshots.call_count == 1
            if "plan_task_execute" in result:
                assert result["plan_task_execute"] == expected
            if "recommendations" in result:
                assert result["recommendations"][0]["name"] == "approve-execution"
        with app._connection() as conn:
            with mock.patch.object(db, "status_payload", wraps=db.status_payload) as snapshots:
                stopped = hooks.handle_event(conn, event="Stop", mode="enforce", tool=None, payload={})
            assert snapshots.call_count == 1
            assert stopped["block"] is True


def test_status_snapshot_is_consistent_during_a_concurrent_commit() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        _, app = workspace(tmp)
        app.summarize_run("Before")
        app.apply_plan("PLAN-001", title="Snapshot fixture")
        app.create_task("TASK-001", "Before", "PLAN-001", "Goal", "Edit", "Verify")
        with app._connection() as reader, app._connection() as writer:
            original = db.active_run
            updated = False

            def concurrent_update(conn):
                nonlocal updated
                run = original(conn)
                if conn is reader and not updated:
                    updated = True
                    writer.execute("UPDATE workflow_runs SET request_summary = 'After' WHERE id = ?", (run["id"],))
                    writer.execute("UPDATE items SET title = 'After' WHERE run_id = ? AND kind = 'task'", (run["id"],))
                    writer.commit()
                return run

            with mock.patch.object(db, "active_run", side_effect=concurrent_update):
                state = db.status_payload(reader)
            assert state["active_run"]["request_summary"] == "Before"
            assert state["tasks"][0]["title"] == "Before"
            assert not reader.in_transaction
            fresh = db.status_payload(reader)
            assert fresh["active_run"]["request_summary"] == "After"
            assert fresh["tasks"][0]["title"] == "After"


def test_status_snapshot_preserves_caller_transaction_and_cleans_up_failure() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        _, app = workspace(tmp)
        with app._connection() as conn:
            conn.execute("INSERT INTO meta(key, value) VALUES('pending-fixture', 'value')")
            db.status_payload(conn)
            assert conn.in_transaction
            conn.rollback()
            assert conn.execute("SELECT value FROM meta WHERE key = 'pending-fixture'").fetchone() is None
            with mock.patch.object(db, "active_run", side_effect=RuntimeError("read failed")):
                try:
                    db.status_payload(conn)
                except RuntimeError as error:
                    assert str(error) == "read failed"
                else:
                    raise AssertionError("read failure must propagate")
            assert not conn.in_transaction


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


def test_application_splits_independent_requests_into_separate_runs() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        _, app = workspace(tmp)

        split = app.split_run(
            [
                {
                    "key": "docs",
                    "summary": "Update the documentation",
                    "work_type": "implementation",
                    "workflow_mode": "standard",
                    "depends_on": [],
                },
                {
                    "key": "billing",
                    "summary": "Investigate the billing report",
                    "work_type": "investigation",
                    "workflow_mode": "fast",
                    "depends_on": [],
                },
            ]
        )

        assert split["active_run"]["split_key"] == "docs"
        assert split["active_run"]["request_summary"] == "Update the documentation"
        assert len(split["queued_runs"]) == 1
        queued = split["queued_runs"][0]
        assert queued["split_key"] == "billing"
        assert queued["status"] == "queued"
        assert queued["depends_on"] == []
        assert queued["ready"] is True
        assert queued["record_mode"] == "lightweight"
        assert queued["id"] != split["active_run"]["id"]


def test_application_keeps_topic_plans_and_task_references_in_one_run() -> None:
    topics = (
        "불규칙 호스트 정규식 필터링",
        "기본 Codex CLI 분석 환경",
        "모델 추론 레벨 설정",
        "웹 페이지 요소 광고 탐지",
    )
    with tempfile.TemporaryDirectory() as tmp:
        _, app = workspace(tmp)
        run = app.summarize_run(
            "주제별 기능 개선", work_type="implementation", workflow_mode="standard"
        )["active_run"]
        for number, topic in enumerate(topics, start=1):
            app.apply_plan(
                f"PLAN-{number:03d}",
                title=topic,
                summary=f"REQ-{number:03d}: {topic}",
                validation=f"{topic} 검증",
            )

        before = app.get_status(full=True)
        assert before["tasks"] == []
        assert before["queued_runs"] == []
        assert len(before["plans"]) == len(topics)
        assert {plan["run_id"] for plan in before["plans"]} == {run["id"]}
        assert [plan["title"] for plan in before["plans"]] == list(topics)
        assert before["approvals"]["execution"]["approved"] is False

        app.apply_plan("PLAN-003", selected_approach="모델별 지원 추론 레벨 표시")
        after = app.get_status(full=True)
        for original, updated in zip(before["plans"], after["plans"], strict=True):
            if original["stable_id"] == "PLAN-003":
                assert updated["id"] == original["id"]
                assert updated["title"] == original["title"]
                assert updated["validation"] == original["validation"]
                assert updated["selected_approach"] == "모델별 지원 추론 레벨 표시"
            else:
                assert updated == original

        task_plans = {}
        for number, topic in enumerate(topics, start=1):
            for step in range(2):
                task_id = f"TASK-{number * 2 - 1 + step:03d}"
                plan_id = f"PLAN-{number:03d}"
                task_plans[task_id] = plan_id
                app.create_task(task_id, topic, plan_id, topic, "구현" if step == 0 else "검증", "검증 통과")
        app.record_approval(decision="approved", prompt="모든 주제 구현·검증", source="explicit_user")
        for task_id in task_plans:
            app.start_task(task_id)
            app.settle_task(task_id, status="Completed", result="완료", verification="검증 통과")

        completed = app.get_status(full=True)
        assert completed["active_run"]["id"] == run["id"]
        assert completed["plan_task_execute"]["ok"] is True
        assert completed["incomplete_tasks"] == 0
        app.finish_run("모든 주제 완료")
        app.finish_archive("topic-plans")
        items = app.get_archive("topic-plans")["items"]
        assert [item["title"] for item in items if item["kind"] == "plan"] == list(topics)
        assert {item["stable_id"]: item["spec_id"] for item in items if item["kind"] == "task"} == task_plans


def test_application_activates_dependent_run_only_after_finished_archive() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        _, app = workspace(tmp)
        app.split_run(
            [
                {
                    "key": "conversation-title",
                    "summary": "Generate conversation titles asynchronously",
                    "work_type": "implementation",
                    "workflow_mode": "standard",
                    "depends_on": [],
                },
                {
                    "key": "suggestion-chips",
                    "summary": "Build suggestion chips from conversation titles",
                    "work_type": "implementation",
                    "workflow_mode": "standard",
                    "depends_on": ["conversation-title"],
                },
            ]
        )

        app.finish_run("Conversation title generation is complete.")
        archived = app.finish_archive("conversation-title")

        assert archived["next_active_run"]["split_key"] == "suggestion-chips"
        status = app.get_status()
        assert status["active_run"]["request_summary"] == (
            "Build suggestion chips from conversation titles"
        )
        assert status["plans"] == []
        assert status["tasks"] == []
        assert status["queued_runs"] == []


def test_application_keeps_dependency_queued_when_predecessor_is_archived_unfinished() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        _, app = workspace(tmp)
        app.split_run(
            [
                {
                    "key": "first",
                    "summary": "Complete the prerequisite",
                    "work_type": "implementation",
                    "workflow_mode": "standard",
                    "depends_on": [],
                },
                {
                    "key": "second",
                    "summary": "Consume the prerequisite",
                    "work_type": "implementation",
                    "workflow_mode": "standard",
                    "depends_on": ["first"],
                },
            ]
        )

        archived = app.finish_archive("unfinished-first")

        assert archived["next_active_run"] is None
        assert archived["queued_runs"][0]["waiting_on"] == ["first"]
        next_action = app.get_next()["recommendations"][0]
        assert next_action["name"] == "inspect-status"


def test_application_rejects_split_dependencies_that_do_not_reference_earlier_requests() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        _, app = workspace(tmp)

        try:
            app.split_run(
                [
                    {
                        "key": "first",
                        "summary": "First request",
                        "work_type": "answer",
                        "workflow_mode": "fast",
                        "depends_on": ["second"],
                    },
                    {
                        "key": "second",
                        "summary": "Second request",
                        "work_type": "answer",
                        "workflow_mode": "fast",
                        "depends_on": [],
                    },
                ]
            )
        except ValueError as exc:
            assert "dependencies must reference earlier requests" in str(exc)
        else:
            raise AssertionError("forward split dependency must fail")


def test_application_rejects_split_after_plan_records_exist() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        _, app = workspace(tmp)
        app.summarize_run("One cohesive request")
        app.apply_plan("PLAN-001", title="Existing plan")

        try:
            app.split_run(
                [
                    {
                        "key": "first",
                        "summary": "First request",
                        "work_type": "analysis",
                        "workflow_mode": "standard",
                        "depends_on": [],
                    },
                    {
                        "key": "second",
                        "summary": "Second request",
                        "work_type": "analysis",
                        "workflow_mode": "standard",
                        "depends_on": [],
                    },
                ]
            )
        except ValueError as exc:
            assert "must be split before plans" in str(exc)
        else:
            raise AssertionError("run with an existing plan must not be split")


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


def test_non_planning_plan_without_tasks_offers_execution_or_completion() -> None:
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
                    "Ensure all topic plans are stored before task design. Finish the run for analysis or reporting scope; "
                    "create a task only when execution was explicitly requested."
                ),
            }
        ]

        mcp_payload = mcp_server.mcp_next_recommendations(next_payload)
        assert mcp_payload["recommendations"][0]["tool"] == [
            "tapl_create_task",
            "tapl_finish_run",
        ]


def test_planning_plan_without_tasks_requires_user_confirmation() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        _, app = workspace(tmp)
        app.summarize_run(
            "draft an implementation plan",
            work_type="planning",
            workflow_mode="standard",
        )
        app.apply_plan(
            "PLAN-001",
            title="Implementation plan",
            status="Finalized",
            summary="REQ-001: describe the implementation",
            objective="Provide a plan without executing it.",
            requirements_trace="REQ-001",
            selected_approach="Describe the intended changes.",
            affected_files="Example module",
            execution_order="Plan only.",
            risks="None",
            validation="Review the plan.",
        )

        next_payload = app.get_next()
        recommendation = next_payload["recommendations"][0]
        assert recommendation["name"] == "confirm-after-plan"
        assert "Do not finish or archive before the user chooses" in recommendation["reason"]

        mcp_payload = mcp_server.mcp_next_recommendations(next_payload)
        assert mcp_payload["recommendations"][0]["tool"] == "request_user_input"


def test_lightweight_planning_run_requires_user_confirmation_before_archive() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        _, app = workspace(tmp)
        app.summarize_run(
            "draft a short plan",
            work_type="planning",
            workflow_mode="fast",
        )

        before_result = app.get_next()
        assert before_result["recommendations"][0]["name"] == "confirm-after-plan"

        app.finish_run("The requested plan was reported.")
        after_result = app.get_next()
        assert after_result["recommendations"][0]["name"] == "confirm-after-plan"
        assert mcp_server.mcp_next_recommendations(after_result)["recommendations"][0]["tool"] == "request_user_input"


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
                custom_fields={"Existing": "preserved"} if task_id == "TASK-001" else None,
            )
        app.record_approval(
            decision="approved", prompt="Execute parallel tasks", source="explicit_user"
        )

        execution_metadata = {
            "TASK-001": {
                "executor_ref": "agent-a",
                "model": "gpt-5.6-sol",
                "reasoning_effort": "xhigh",
            },
            "TASK-002": {
                "executor_ref": "agent-b",
                "model": "gpt-5.6-terra",
                "reasoning_effort": "high",
            },
        }
        settings = app._settings()
        catalog = {entry.name: list(entry.reasoning_efforts) for entry in settings.subagents.models}
        app.configure_subagents(
            user_confirmed=True, enabled=True, strategy=settings.subagents.strategy,
            models=catalog, available_models=catalog,
        )
        manifest = app.dispatch_tasks(
            ["TASK-001", "TASK-002"],
            batch_id="BATCH-001",
            execution_metadata=execution_metadata,
        )
        executions = {row["task_id"]: row for row in manifest["executions"]}
        assert set(executions) == {"TASK-001", "TASK-002"}

        full_policy = app.get_next()
        retained = app.get_next(known_policy_revision=full_policy["policy_revision"])
        assert retained["policy_unchanged"]
        assert retained["recommendations"] == full_policy["recommendations"]
        assert retained["recommendations"][0]["name"] == "settle-parallel-task"
        # Catalog review must not displace an active batch's settlement/recovery.
        reviewed = app.get_next(
            available_models={**catalog, "new-runtime": ["high"]},
            known_policy_revision=full_policy["policy_revision"],
        )
        assert reviewed["model_changes"]["changed"]
        assert not reviewed["policy_unchanged"]
        assert reviewed["recommendations"][0]["name"] == "settle-parallel-task"
        assert not any(action["name"] == "review-subagent-models" for action in reviewed["recommendations"])

        dispatched_status = app.get_status(full=True)
        dispatched_tasks = {
            task["stable_id"]: task for task in dispatched_status["tasks"]
        }
        advisory_codes = {
            issue["code"]
            for issue in dispatched_status["plan_task_execute"]["warnings"]
        }
        assert "advisory_execution_decision_missing" in advisory_codes
        assert "advisory_model_rationale_missing" in advisory_codes
        assert "advisory_task_profile_missing" in advisory_codes
        assert dispatched_status["plan_task_execute"]["ok"] is True
        assert any(
            item["name"] == "review-advisory-selection-context"
            for item in app.get_next()["recommendations"]
        )
        assert dispatched_tasks["TASK-001"]["custom_fields"] == {
            "Existing": "preserved",
            "SubAgent Model": "gpt-5.6-sol (xhigh)",
        }
        assert dispatched_tasks["TASK-002"]["custom_fields"] == {
            "SubAgent Model": "gpt-5.6-terra (high)",
        }

        for task_id, execution in executions.items():
            metadata = execution_metadata[task_id]
            assert execution["model"] == metadata["model"]
            assert execution["reasoning_effort"] == metadata["reasoning_effort"]
            receipt = app.settle_task(
                task_id,
                status="Completed",
                execution_id=execution["execution_id"],
                verification=f"Verified {task_id}",
                result=f"Completed {task_id}",
            )
            assert receipt["settled_execution_id"] == execution["execution_id"]

        status = app.get_status(full=True)
        assert status["active_batches"] == []
        tasks = {task["stable_id"]: task for task in status["tasks"]}
        assert tasks["TASK-001"]["custom_fields"]["SubAgent Model"] == "gpt-5.6-sol (xhigh)"
        assert tasks["TASK-001"]["custom_fields"]["Existing"] == "preserved"
        assert tasks["TASK-002"]["custom_fields"]["SubAgent Model"] == "gpt-5.6-terra (high)"


def test_application_dispatch_merges_complete_advisory_selection_context() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        _, app = workspace(tmp)
        app.summarize_run("advisory dispatch metadata")
        app.apply_plan(
            "PLAN-001",
            title="Advisory metadata plan",
            status="Finalized",
            summary="REQ-001: preserve agent routing decisions.",
            objective="Record complete advisory dispatch metadata.",
            requirements_trace="REQ-001",
            selected_approach="Deep merge canonical task custom fields.",
            affected_files="src/a.py, src/b.py",
            execution_order="approve, dispatch, inspect",
            risks="Design-time task metadata must be preserved.",
            validation="Inspect dispatch manifest and validation warnings.",
        )
        for task_id, owned_path in (("TASK-001", "src/a.py"), ("TASK-002", "src/b.py")):
            app.create_task(
                task_id,
                f"Advisory {task_id}",
                "PLAN-001",
                f"Complete {task_id}",
                f"Implement {task_id}",
                f"Verify {task_id}",
                execution_mode="parallel",
                executor_kind="subagent",
                parallel_group="workers",
                owned_paths=[owned_path],
                custom_fields=(
                    {
                        "Existing": "preserved",
                        "Task Profile": {
                            "name": "routine",
                            "match_reason": "design-time match",
                        },
                        "Task Characteristics": {"risk": "low"},
                        "Execution Decision": {"profile_overridden": False},
                    }
                    if task_id == "TASK-001"
                    else None
                ),
            )
        app.record_approval(
            decision="approved", prompt="Execute advisory tasks", source="explicit_user"
        )

        manifest = app.dispatch_tasks(
            ["TASK-001", "TASK-002"],
            batch_id="BATCH-ADVISORY",
            execution_metadata={
                "TASK-001": {
                    "model": "gpt-5.6-terra",
                    "reasoning_effort": "high",
                    "profile": "routine",
                    "profile_match_reason": "runtime match",
                    "task_characteristics": {"parallel_value": "high"},
                    "delegation_reason": "independent owned path",
                    "model_reason": "balanced implementation model",
                    "profile_overridden": False,
                },
                "TASK-002": {
                    "model": "gpt-5.6-luna",
                    "reasoning_effort": "xhigh",
                    "profile": "bounded",
                    "profile_match_reason": "bounded context",
                    "characteristics": {"risk": "low", "scope": "local"},
                    "delegation_reason": "safe parallel work",
                    "model_reason": "fast bounded-work model",
                },
            },
        )

        executions = {row["task_id"]: row for row in manifest["executions"]}
        first = executions["TASK-001"]["custom_fields"]
        second = executions["TASK-002"]["custom_fields"]
        assert first["Existing"] == "preserved"
        assert first["Task Profile"] == {
            "name": "routine",
            "match_reason": "runtime match",
        }
        assert first["Task Characteristics"] == {
            "risk": "low",
            "parallel_value": "high",
        }
        assert first["Execution Decision"]["executor"] == "subagent"
        assert first["Execution Decision"]["model"] == "gpt-5.6-terra"
        assert first["Execution Decision"]["model_reason"] == "balanced implementation model"
        assert first["SubAgent Model"] == "gpt-5.6-terra (high)"
        assert second["Task Profile"]["name"] == "bounded"
        assert second["Task Characteristics"] == {"risk": "low", "scope": "local"}
        assert second["Execution Decision"]["delegation_reason"] == "safe parallel work"
        assert second["SubAgent Model"] == "gpt-5.6-luna (xhigh)"

        status = app.get_status(full=True)
        assert status["plan_task_execute"]["ok"] is True
        assert status["plan_task_execute"]["warnings"] == []


def test_application_dispatch_ignores_incomplete_model_metadata() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        _, app = workspace(tmp)
        app.summarize_run("parallel metadata compatibility")
        app.apply_plan(
            "PLAN-001",
            title="Compatibility plan",
            status="Finalized",
            summary="REQ-001: preserve incomplete metadata behavior.",
            objective="Keep incomplete dispatch metadata backward compatible.",
            requirements_trace="REQ-001",
            selected_approach="Dispatch tasks without a complete model pair.",
            affected_files="src/a.py, src/b.py",
            execution_order="approve, dispatch, inspect",
            risks="Incomplete metadata must not create a misleading model field.",
            validation="Inspect task custom fields after dispatch.",
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
                custom_fields={"Existing": task_id},
            )
        app.record_approval(
            decision="approved", prompt="Execute parallel tasks", source="explicit_user"
        )

        app.dispatch_tasks(
            ["TASK-001", "TASK-002"],
            batch_id="BATCH-001",
            execution_metadata={
                "TASK-001": {"model": "gpt-5.6-sol"},
                "TASK-002": {"model": "", "reasoning_effort": "xhigh"},
            },
        )

        status = app.get_status(full=True)
        tasks = {task["stable_id"]: task for task in status["tasks"]}
        assert tasks["TASK-001"]["custom_fields"] == {"Existing": "TASK-001"}
        assert tasks["TASK-002"]["custom_fields"] == {"Existing": "TASK-002"}
