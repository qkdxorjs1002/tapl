from pathlib import Path

import pytest

from taplctl import db, execution_evidence as evidence
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


def approve(app, text="Work in the plan", source="explicit_user"):
    return app.record_approval(decision="approved", prompt=text, source=source)


def command(app):
    with app._connection() as conn:
        return evidence.confirmation_command(conn)


def test_held_scope_requires_host_turn_for_current_finalized_plan(tmp_path):
    app = application(tmp_path)
    prepare(app)
    original = command(app)
    assert original.startswith("TAPL-APPROVE ")
    app.summarize_run("Implement this change", work_type="implementation")
    assert command(app) == original
    for source in ("request_user_input", "explicit_user"):
        with pytest.raises(ValueError, match=original):
            approve(app, original, source)
    with pytest.raises(ValueError, match="execution approval"):
        app.start_task("TASK-001")
    for message in ("Show me the plan", "yes", "example: " + original, original + "\nPlease wait"):
        user(app, message)
        with pytest.raises(ValueError, match=original):
            approve(app, message)
    user(app, original)
    assert app.get_next()["state_summary"]["execution_confirmation"] == {"state": "confirmed"}
    approval = approve(app)
    assert original not in str(approval)
    with app._connection() as conn, pytest.raises(ValueError, match="Start a task"):
        evidence.require_active_execution(conn)
    app.start_task("TASK-001")
    with app._connection() as conn:
        evidence.require_active_execution(conn)
    app.apply_plan("PLAN-001", affected_files="b.py")
    assert app.get_next()["state_summary"]["execution_approval"] == {"state": "stale", "approved": False}
    with app._connection() as conn, pytest.raises(ValueError, match="execution approval"):
        evidence.require_active_execution(conn)
    changed = command(app)
    assert changed and changed != original
    user(app, original)
    with pytest.raises(ValueError, match=changed):
        approve(app)
    user(app, changed)
    approve(app)
    app.record_approval(decision="rejected", prompt="Pause", source="explicit_user")
    assert command(app) not in (original, changed)
    with pytest.raises(ValueError, match="host confirmation"):
        approve(app, changed)


def test_direct_first_request_binds_digest_and_rejects_fabricated_or_stale_text(tmp_path):
    app = application(tmp_path)
    prepare(app, work_type="implementation", text="Implement change A")
    with pytest.raises(ValueError, match="host confirmation"):
        approve(app, "Implement change B")
    with pytest.raises(ValueError, match="host confirmation"):
        approve(app, "Implement change A", "request_user_input")
    receipt = approve(app, "Implement change A")
    assert "Implement change A" not in str(receipt)
    assert approve(app, "Implement change A") == receipt
    app.start_task("TASK-001")
    with app._connection() as conn:
        payloads = conn.execute("SELECT payload_json FROM events WHERE mode='execution_evidence'").fetchall()
        assert all("Implement change A" not in row[0] for row in payloads)
    app.apply_plan("PLAN-001", objective="Different scope")
    with pytest.raises(ValueError, match="host confirmation"):
        approve(app, "Implement change A")
    other = application(tmp_path, "thread-B")
    prepare(other, work_type="implementation", text="Implement a different task")
    user(other, "Wait")
    with pytest.raises(ValueError, match="host confirmation"):
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
    with pytest.raises(ValueError, match=command(app)):
        approve(app, "Review possible improvements")
    first = command(app)
    with app._connection() as conn:
        assert all(evidence.is_held(conn, row) for row in conn.execute(
            "SELECT * FROM workflow_runs WHERE session_id='thread-A' AND status IN ('active','queued')"))
    other = application(tmp_path, "thread-B")
    prepare(other, "implementation", "Implement B")
    approve(other, "Implement B")
    other.apply_plan("PLAN-001", affected_files="other.py")
    user(other, first)
    with pytest.raises(ValueError, match=command(other)):
        approve(other, first)


def test_dispatch_idempotent_retry_revalidates_approval(tmp_path):
    app = application(tmp_path)
    prepare(app)
    with app._connection() as conn:
        for task in ("TASK-001", "TASK-002"):
            db.upsert_task(conn, task_id=task, title=task, status="Pending", spec_id="PLAN-001",
                           execution_mode="parallel", executor_kind="subagent", parallel_group="pair",
                           owned_paths=[task + ".py"])
    user(app, command(app))
    approve(app)
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


def test_standalone_held_scope_still_needs_host_acknowledgment(tmp_path):
    app = application(tmp_path)
    app.summarize_run("Plan only", work_type="planning")
    app.apply_plan("PLAN-001", title="Planned work", status="Finalized")
    with pytest.raises(ValueError, match=command(app)):
        approve(app)


@pytest.mark.parametrize("archived_type,approved", [("answer", False), ("investigation", False), ("planning", True)])
def test_completed_non_durable_answer_and_confirmed_planning_allow_next_direct_request(tmp_path, archived_type, approved):
    app = application(tmp_path)
    user(app, "Earlier request")
    run = app.summarize_run("Earlier request", work_type=archived_type, workflow_mode="fast")["active_run"]
    if approved:
        app.apply_plan("PLAN-001", title="Proceed", status="Finalized")
        user(app, command(app))
        approve(app)
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
    user(app, command(app))
    approve(app)
    with app._connection() as conn, pytest.raises(ValueError, match="Start a task"):
        evidence.require_active_execution(conn)
    app.start_task("TASK-001")
    with app._connection() as conn:
        evidence.require_active_execution(conn)
        conn.execute("UPDATE items SET archived=1 WHERE kind='task'")
        with pytest.raises(ValueError, match="Start a task"):
            evidence.require_active_execution(conn)
