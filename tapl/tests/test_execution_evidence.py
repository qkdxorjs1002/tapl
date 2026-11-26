import asyncio
from pathlib import Path

from mcp import Client
import pytest

from taplctl import clients, db, execution_evidence as evidence, mcp_server
from taplctl.application import WorkflowApplication


def application(root: Path, session: str = "thread-A") -> WorkflowApplication:
    (root / ".git").mkdir(exist_ok=True)
    db.initialize_workspace(root)
    return WorkflowApplication(root, session_id=session)


def user(app, message):
    with app._connection() as conn:
        db.ensure_active_run(conn)
        evidence.observe_user_prompt(conn, {"prompt": message})


def prepare(app, work_type="analysis", text="Inspect this change"):
    user(app, text)
    app.summarize_run(text, work_type=work_type)
    app.apply_plan("PLAN-001", title="Scope", status="Finalized", affected_files="a.py")
    app.create_task("TASK-001", "Work", "PLAN-001", "Goal", "Edit a.py", "Verify")


def approve(app, text="Work in the plan", source="explicit_user", *, approval_scope=None):
    return app.record_approval(decision="approved", prompt=text, source=source,
                               approval_scope=approval_scope)


def question_scope(app):
    return app.get_next()["state_summary"]["execution_confirmation"]["scope"]


def approve_from_question(app, scope=None):
    return approve(app, source="request_user_input",
                   approval_scope=question_scope(app) if scope is None else scope)


def test_held_run_requires_scoped_question_approval_for_current_finalized_plan(tmp_path):
    app = application(tmp_path)
    prepare(app)
    original = question_scope(app)
    next_state = app.get_next()["state_summary"]["execution_confirmation"]
    assert next_state == {"state": "awaiting_user", "scope": original}
    app.summarize_run("Implement this change", work_type="implementation")
    assert question_scope(app) == original
    with pytest.raises(ValueError, match="approval_scope"):
        approve(app, source="request_user_input")
    with pytest.raises(ValueError, match="verified direct user request"):
        approve(app, approval_scope=original)
    with pytest.raises(ValueError, match="execution approval"):
        app.start_task("TASK-001")
    for message in ("Show me the plan", "yes", "TAPL-APPROVE " + original):
        user(app, message)
        with pytest.raises(ValueError, match="request_user_input"):
            approve(app, message)
    with pytest.raises(ValueError, match="approval_scope"):
        approve_from_question(app, original)
    current = question_scope(app)
    receipt = approve_from_question(app, current)
    assert receipt["approval"]["source"] == "request_user_input"
    assert receipt["approval"]["prompt"] == "Work in the plan"
    assert approve_from_question(app, current) == receipt
    with app._connection() as conn, pytest.raises(ValueError, match="Start a task"):
        evidence.require_active_execution(conn)
    app.start_task("TASK-001")
    with app._connection() as conn:
        evidence.require_active_execution(conn)
    app.apply_plan("PLAN-001", affected_files="b.py")
    assert app.get_next()["state_summary"]["execution_approval"] == {"state": "stale", "approved": False}
    with app._connection() as conn, pytest.raises(ValueError, match="execution approval"):
        evidence.require_active_execution(conn)
    changed = question_scope(app)
    assert changed != current
    with pytest.raises(ValueError, match="approval_scope"):
        approve_from_question(app, current)
    approve_from_question(app, changed)
    app.record_approval(decision="rejected", prompt="Pause", source="explicit_user")
    assert question_scope(app) not in (original, current, changed)
    with pytest.raises(ValueError, match="approval_scope"):
        approve_from_question(app, changed)


def test_direct_first_request_binds_digest_and_rejects_fabricated_or_stale_text(tmp_path):
    app = application(tmp_path)
    prepare(app, work_type="implementation", text="Implement change A")
    with pytest.raises(ValueError, match="Execution approval"):
        approve(app, "Implement change B")
    with pytest.raises(ValueError, match="Execution approval"):
        approve(app, "Implement change A", "request_user_input")
    receipt = approve(app, "Implement change A")
    assert "Implement change A" not in str(receipt)
    assert approve(app, "Implement change A") == receipt
    app.start_task("TASK-001")
    with app._connection() as conn:
        payloads = conn.execute("SELECT payload_json FROM events WHERE mode='execution_evidence'").fetchall()
        assert all("Implement change A" not in row[0] for row in payloads)
    app.apply_plan("PLAN-001", objective="Different scope")
    with pytest.raises(ValueError, match="Execution approval"):
        approve(app, "Implement change A")
    other = application(tmp_path, "thread-B")
    prepare(other, work_type="implementation", text="Implement a different task")
    user(other, "Wait")
    with pytest.raises(ValueError, match="Execution approval"):
        approve(other, "Implement a different task")


def test_unapproved_archive_carries_hold_across_split_and_scopes_to_owner(tmp_path):
    app = application(tmp_path)
    user(app, "Investigate")
    run = app.summarize_run("Inspect", work_type="analysis", workflow_mode="fast")["active_run"]
    app.finish_run("Analysis delivered", expected_run_id=run["id"],
                   memory_review={"decision": "skip", "reason": "Fixture."})
    app.finish_archive("findings")
    user(app, "Review possible improvements")
    app.split_run([dict(key=k, summary=k, work_type="implementation", workflow_mode="standard")
                   for k in ("one", "two")])
    app.apply_plan("PLAN-001", title="Current plan", status="Draft")
    with pytest.raises(ValueError, match="Finalize"):
        approve(app, "Review possible improvements")
    app.apply_plan("PLAN-001", status="Finalized")
    with pytest.raises(ValueError, match="request_user_input"):
        approve(app, "Review possible improvements")
    first = question_scope(app)
    with app._connection() as conn:
        assert all(evidence.is_held(conn, row) for row in conn.execute(
            "SELECT * FROM workflow_runs WHERE session_id='thread-A' AND status IN ('active','queued')"))
    other = application(tmp_path, "thread-B")
    prepare(other, "implementation", "Implement B")
    approve(other, "Implement B")
    other.apply_plan("PLAN-001", affected_files="other.py")
    user(other, "Proceed with the revised plan?")
    with pytest.raises(ValueError, match="approval_scope"):
        approve_from_question(other, first)


def test_dispatch_idempotent_retry_revalidates_approval(tmp_path):
    app = application(tmp_path)
    prepare(app)
    with app._connection() as conn:
        for task in ("TASK-001", "TASK-002"):
            db.upsert_task(conn, task_id=task, title=task, status="Pending", spec_id="PLAN-001",
                           execution_mode="parallel", executor_kind="subagent", parallel_group="pair",
                           owned_paths=[task + ".py"])
    approve_from_question(app)
    with app._connection() as conn:
        db.dispatch_tasks(conn, ["TASK-001", "TASK-002"], batch_id="pair-1")
    app.apply_plan("PLAN-001", selected_approach="Changed")
    with app._connection() as conn:
        for batch_id in ("pair-1", "new"):
            with pytest.raises(ValueError):
                db.dispatch_tasks(conn, ["TASK-001", "TASK-002"], batch_id=batch_id)


def test_postcompact_invalidates_older_policy_even_when_event_scrolls_off(tmp_path):
    app = application(tmp_path)
    before = app.get_next()["policy_revision"]
    with app._connection() as conn:
        db.record_event(conn, event_type="PostCompact")
        for _ in range(16):
            db.record_event(conn, event_type="PostToolUse")
    after = app.get_next(known_policy_revision=before)
    assert after["policy_revision"] != before
    assert not after["policy_unchanged"] and "workflow_policy" in after
    assert app.get_next(known_policy_revision=after["policy_revision"])["policy_unchanged"]


def test_agent_can_record_scoped_question_answer_without_a_host_hook(tmp_path):
    app = application(tmp_path)
    app.summarize_run("Plan only", work_type="planning")
    app.apply_plan("PLAN-001", title="Planned work", status="Finalized")
    with pytest.raises(ValueError, match="request_user_input"):
        approve(app)
    assert approve_from_question(app)["ok"]


@pytest.mark.parametrize(("host", "question_tool"), [
    ("codex", "request_user_input"),
    ("claude-code", "AskUserQuestion"),
])
def test_mcp_routes_plan_approval_to_question_tool_and_records_scope(tmp_path, host, question_tool):
    with clients.client_scope(host):
        app = application(tmp_path, clients.session_key("thread-A"))
        prepare(app)
    args = {"session_id": app.session_id}

    async def exercise():
        async with Client(mcp_server.create_server(workspace_root=tmp_path, client=host)) as client:
            next_result = (await client.call_tool("tapl_get_next", args)).structured_content
            assert f"During analysis and planning, use {question_tool}" in next_result["workflow_policy"]
            assert "source `request_user_input`" in next_result["workflow_policy"]
            approval_action = next(action for action in next_result["recommendations"]
                                   if action["name"] == "await-user-confirmation")
            assert approval_action["tool"] == question_tool
            assert f"use {question_tool} to ask" in approval_action["reason"]
            question = next_result["state_summary"]["execution_confirmation"]
            assert question["state"] == "awaiting_user" and "command" not in question
            approval = {"prompt": "Update only a.py as approved", "source": "request_user_input", **args}
            missing = await client.call_tool("tapl_approve_execution", approval)
            assert missing.is_error
            assert f"Ask the user again with {question_tool}" in str(missing.content)
            recorded = await client.call_tool("tapl_approve_execution", {**approval, "approval_scope": question["scope"]})
            assert not recorded.is_error
            state = recorded.structured_content["state_summary"]
            assert state["execution_approval"]["approved"]
            assert "execution_confirmation" not in state
            assert not (await client.call_tool("tapl_start_task", {"task_id": "TASK-001", **args})).is_error

    asyncio.run(exercise())


@pytest.mark.parametrize("archived_type,approved", [("answer", False), ("investigation", False), ("planning", True)])
def test_completed_non_durable_answer_and_confirmed_planning_allow_next_direct_request(tmp_path, archived_type, approved):
    app = application(tmp_path)
    user(app, "Earlier request")
    run = app.summarize_run("Earlier request", work_type=archived_type, workflow_mode="fast")["active_run"]
    if approved:
        app.apply_plan("PLAN-001", title="Proceed", status="Finalized")
        approve_from_question(app)
    app.finish_run("Done", expected_run_id=run["id"], memory_review={"decision": "skip", "reason": "Fixture."})
    app.finish_archive("done")
    prepare(app, "implementation", "Implement unrelated task B")
    approve(app, "Implement unrelated task B")


def test_managed_start_requires_valid_task_and_current_start_proof(tmp_path):
    app = application(tmp_path)
    prepare(app, "implementation", "Implement A")
    app.create_task("TASK-002", "Dependent", "PLAN-001", "Goal", "Edit", "Check", depends_on=["TASK-001"])
    app.create_task("TASK-003", "Invalid plan", "PLAN-999", "Goal", "Edit", "Check")
    app.create_task("TASK-004", "Parallel", "PLAN-001", "Goal", "Edit", "Check",
                    execution_mode="parallel", executor_kind="subagent", parallel_group="pair")
    approve(app, "Implement A")
    for task_id in ("TASK-002", "TASK-003", "TASK-004"):
        with pytest.raises(ValueError):
            app.start_task(task_id)
    app.start_task("TASK-001")
    with app._connection() as conn:
        evidence.require_active_execution(conn)
    app.record_approval(decision="rejected", prompt="Stop", source="explicit_user")
    approve_from_question(app)
    with app._connection() as conn, pytest.raises(ValueError, match="Start a task"):
        evidence.require_active_execution(conn)
    app.start_task("TASK-001")
    with app._connection() as conn:
        evidence.require_active_execution(conn)
        conn.execute("UPDATE items SET archived=1 WHERE kind='task'")
        with pytest.raises(ValueError, match="Start a task"):
            evidence.require_active_execution(conn)
