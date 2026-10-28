"""Force-discard is explicit, owner-scoped and atomic, including damaged state."""
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import threading
from unittest import mock

from mcp import Client
import pytest

from taplctl import db, mcp_server, recall
from taplctl.application import WorkflowApplication


@pytest.fixture
def app(tmp_path: Path) -> WorkflowApplication:
    (tmp_path / ".git").mkdir()
    db.initialize_workspace(tmp_path)
    return WorkflowApplication(tmp_path, session_id="owner")


def make_run(app: WorkflowApplication) -> str:
    with app._connection() as conn:
        return str(db.ensure_active_run(conn)["id"])


def make_task(app: WorkflowApplication, number: int = 1) -> int:
    app.apply_plan("PLAN-001", title="Plan")
    result = app.create_task(f"TASK-{number:03d}", "Task", "PLAN-001", "Goal", "Action", "Verify")
    return result["item"]["id"]


def execution(conn, run_id, item_id, *, batch="batch", execution="execution", state="running", batch_state="active"):
    now = "2026-01-01T00:00:00+00:00"
    conn.execute("INSERT INTO execution_batches(id,run_id,parallel_group,state,created_at) VALUES(?,?,'group',?,?)",
                 (batch, run_id, batch_state, now))
    conn.execute("INSERT INTO task_executions(id,batch_id,task_item_id,state,started_at) VALUES(?,?,?,?,?)",
                 (execution, batch, item_id, state, now))
    conn.execute("UPDATE items SET status='In Progress' WHERE id=?", (item_id,))
    db.update_task_timing(conn, item_id, "Pending", "In Progress", now=now)
    conn.commit()


@pytest.mark.parametrize("confirmed", [False, 1, "true", None])
def test_discard_requires_literal_confirmation(app, confirmed):
    run_id = make_run(app)
    with pytest.raises(ValueError, match="confirmation"):
        app.discard_run(run_id=run_id, confirmed=confirmed, confirmation_run_id=run_id)
    with app._connection() as conn:
        assert db.active_run(conn)["id"] == run_id
        assert not conn.execute("SELECT * FROM archives").fetchall()


def test_wrong_owner_and_stale_replay_never_select_another_run(app):
    run_id = make_run(app)
    other = WorkflowApplication(app.workspace_root, session_id="other")
    other_id = make_run(other)
    with pytest.raises(ValueError, match="another session"):
        other.discard_run(run_id=run_id, confirmed=True, confirmation_run_id=run_id)
    app.discard_run(run_id=run_id, confirmed=True, confirmation_run_id=run_id)
    replacement = make_run(app)
    with pytest.raises(ValueError, match="stale_run|not found"):
        app.discard_run(run_id=run_id, confirmed=True, confirmation_run_id=run_id)
    assert app.get_status()["active_run"]["id"] == replacement
    assert other.get_status()["active_run"]["id"] == other_id


def test_discard_settles_children_timing_fts_and_preserves_terminal_history(app):
    run_id = make_run(app)
    live, completed, sequential, pending = [make_task(app, n) for n in range(1, 5)]
    app.add_finding("Evidence", finding="Retain finding")
    with app._connection() as conn:
        execution(conn, run_id, live)
        execution(conn, run_id, completed, batch="done-batch", execution="done-execution", state="completed", batch_state="completed")
        conn.execute("UPDATE items SET status='Completed' WHERE id=?", (completed,))
        conn.execute("UPDATE tasks SET result='historical result' WHERE item_id=?", (completed,))
        conn.execute("UPDATE task_executions SET result='historical execution',finished_at='2026-01-02' WHERE id='done-execution'")
        conn.execute("UPDATE execution_batches SET finished_at='2026-01-02' WHERE id='done-batch'")
        conn.execute("UPDATE items SET status='In Progress' WHERE id=?", (sequential,))
        conn.execute("UPDATE items SET raw_text='Original user section',custom_fields_json=? WHERE id=?",
                     (json.dumps({"owner": "user-defined"}), live))
        db.update_task_timing(conn, sequential, "Pending", "In Progress", now="2026-01-01T00:00:00+00:00")
        conn.commit()
    receipt = app.discard_run(run_id=run_id, confirmed=True, confirmation_run_id=run_id)
    assert receipt["cancelled_execution_ids"] == ["execution"]
    assert receipt["cancelled_batch_ids"] == ["batch"]
    with app._connection() as conn:
        items = conn.execute("SELECT * FROM items WHERE run_id=?", (run_id,)).fetchall()
        assert {row["kind"] for row in items} == {"plan", "task", "finding"}
        assert all(row["archived"] for row in items)
        statuses = {row["id"]: row["status"] for row in items}
        assert statuses[live] == statuses[sequential] == "Blocked"
        assert statuses[completed] == "Completed" and statuses[pending] == "Pending"
        assert conn.execute("SELECT result FROM tasks WHERE item_id=?", (completed,)).fetchone()[0] == "historical result"
        terminal = conn.execute("SELECT * FROM task_executions WHERE id='done-execution'").fetchone()
        assert terminal["state"] == "completed" and terminal["result"] == "historical execution"
        assert terminal["finished_at"] == "2026-01-02"
        timing = conn.execute("SELECT * FROM task_timing").fetchall()
        assert len(timing) == 3 and all(row["running_since"] is None and row["finished_at"] for row in timing)
        for item_id in (live, sequential):
            body = conn.execute("SELECT body FROM items WHERE id=?", (item_id,)).fetchone()[0]
            assert "discarded" in body
            assert conn.execute("SELECT body FROM items_fts WHERE rowid=?", (item_id,)).fetchone()[0].startswith(body)
        custom = conn.execute("SELECT raw_text,custom_fields_json FROM items WHERE id=?", (live,)).fetchone()
        assert custom["raw_text"] == "Original user section"
        assert json.loads(custom["custom_fields_json"]) == {"owner": "user-defined"}
        fts = conn.execute("SELECT body FROM items_fts WHERE rowid=?", (live,)).fetchone()[0]
        assert "Original user section" in fts and "user-defined" in fts
        event = conn.execute("SELECT * FROM events WHERE event_type='run_discarded'").fetchone()
        assert event["run_id"] is None
        payload = json.loads(event["payload_json"])
        assert event["session_id"] == "owner" and payload["source"] == "viewer_user"
        assert payload["confirmed"] is True and payload["requested_run_id"] == run_id
        assert db.active_run(conn) is None
        archived_at = conn.execute("SELECT archived_at FROM workflow_runs WHERE id=?", (run_id,)).fetchone()[0]
        assert event["created_at"] == archived_at == receipt["archives"][0]["created_at"]


def test_queued_split_scope_and_no_automatic_activation(app):
    run_id = make_run(app)
    split = app.split_run([{"key": key, "summary": key, "work_type": "implementation", "workflow_mode": "strict"}
                           for key in ("first", "second", "third")])
    sibling_ids = [row["id"] for row in split["queued_runs"]]
    other = WorkflowApplication(app.workspace_root, session_id="other")
    other_id = make_run(other)
    with app._connection() as conn:
        for identifier, owner, group in (("unrelated", "owner", "elsewhere"), ("foreign-queued", "other", split["split_group_id"])):
            conn.execute("INSERT INTO workflow_runs(id,session_id,slug,status,split_group_id,created_at,updated_at) VALUES(?,?,?,'queued',?,?,?)",
                         (identifier, owner, identifier, group, db.utc_now(), db.utc_now()))
        conn.execute("INSERT INTO items(run_id,stable_id,kind,title,created_at,updated_at) VALUES(?,'FIND-001','finding','queued child',?,?)",
                     (sibling_ids[0], db.utc_now(), db.utc_now()))
        conn.commit()
    result = app.discard_run(run_id=run_id, confirmed=True, confirmation_run_id=run_id)
    assert result["archived_run_ids"] == [sibling_ids[0]]
    assert result["deleted_run_ids"] == [run_id, sibling_ids[1]]
    with app._connection() as conn:
        assert db.active_run(conn) is None
        states = dict(conn.execute("SELECT id,status FROM workflow_runs"))
        assert states["unrelated"] == states["foreign-queued"] == "queued"
        assert states[other_id] == "active"
        assert all(states[value] == "archived" for value in result["archived_run_ids"])
        assert conn.execute("SELECT archived FROM items WHERE run_id=?", (sibling_ids[0],)).fetchone()[0] == 1


def test_inconsistent_execution_state_cannot_block_force_discard(app):
    run_id = make_run(app)
    live, terminal = make_task(app), make_task(app, 2)
    with app._connection() as conn:
        execution(conn, run_id, live, batch_state="completed")
        conn.execute("UPDATE items SET status='Pending' WHERE id=?", (live,))
        execution(conn, run_id, terminal, batch="terminal", execution="terminal-execution")
        conn.execute("UPDATE items SET status='Completed' WHERE id=?", (terminal,))
        conn.execute("INSERT INTO execution_batches(id,run_id,parallel_group,state,created_at) VALUES('empty',?,'g','active',?)", (run_id, db.utc_now()))
        conn.commit()
    result = app.discard_run(run_id=run_id, confirmed=True, confirmation_run_id=run_id)
    assert result["cancelled_batch_ids"] == ["batch", "empty", "terminal"]
    with app._connection() as conn:
        assert set(row[0] for row in conn.execute("SELECT state FROM execution_batches")) == {"cancelled"}
        assert conn.execute("SELECT status FROM items WHERE id=?", (live,)).fetchone()[0] == "Blocked"
        assert conn.execute("SELECT status FROM items WHERE id=?", (terminal,)).fetchone()[0] == "Completed"


@pytest.mark.parametrize("review_status", ["review_required", "failed", "partial"])
def test_force_archive_preserves_pending_review_and_rejects_late_memory(app, review_status):
    run_id = make_run(app)
    with app._connection() as conn:
        checkpoint = recall.require_review(conn, run_id)
        checkpoint["status"] = review_status
        conn.execute("UPDATE events SET payload_json=? WHERE event_type='memory_review'", (json.dumps(checkpoint),))
        conn.commit()
        before = recall.review_state(conn, run_id)
    app.discard_run(run_id=run_id, confirmed=True, confirmation_run_id=run_id)
    with app._connection() as conn:
        assert recall.review_state(conn, run_id) == before
        late = recall.finish_memories(conn, run_id=run_id, review={"decision": "skip", "reason": "Late result"}, expected_token=checkpoint["attempt_token"])
        assert late["status"] == "failed" and late["errors"][0]["code"] == "conflict"
        assert recall.review_state(conn, run_id) == before


def test_discard_rolls_back_settlement_archive_timing_and_audit_on_failure(app):
    run_id = make_run(app)
    item_id = make_task(app)
    with app._connection() as conn:
        execution(conn, run_id, item_id)
        conn.execute("CREATE TRIGGER fail_discard BEFORE INSERT ON events WHEN NEW.event_type='run_discarded' BEGIN SELECT RAISE(ABORT,'injected audit failure'); END")
        conn.commit()
    with pytest.raises(Exception, match="injected audit failure"):
        app.discard_run(run_id=run_id, confirmed=True, confirmation_run_id=run_id)
    with app._connection() as conn:
        assert db.active_run(conn)["id"] == run_id
        assert conn.execute("SELECT state FROM task_executions").fetchone()[0] == "running"
        assert conn.execute("SELECT running_since FROM task_timing").fetchone()[0]
        assert not conn.execute("SELECT * FROM archives").fetchall()
        assert not conn.execute("SELECT * FROM items WHERE archived=1").fetchall()
        assert conn.execute("SELECT status FROM items WHERE id=?", (item_id,)).fetchone()[0] == "In Progress"
        assert "discarded" not in conn.execute("SELECT body FROM items_fts WHERE rowid=?", (item_id,)).fetchone()[0]


def test_concurrent_settle_and_discard_have_one_serialized_outcome(app):
    run_id = make_run(app)
    item_id = make_task(app)
    with app._connection() as conn:
        execution(conn, run_id, item_id)
    barrier = threading.Barrier(2)

    def settle():
        barrier.wait(timeout=10)
        try:
            app.settle_task("TASK-001", status="Completed", execution_id="execution", result="won race")
            return True
        except ValueError as exc:
            assert "active workflow run" in str(exc)
            return False

    def discard():
        barrier.wait(timeout=10)
        return app.discard_run(run_id=run_id, confirmed=True, confirmation_run_id=run_id)

    with ThreadPoolExecutor(max_workers=2) as pool:
        settlement, discarded = pool.submit(settle), pool.submit(discard)
        settled = settlement.result(timeout=20)
        assert discarded.result(timeout=20)["ok"]
    with app._connection() as conn:
        row = conn.execute("SELECT state,result FROM task_executions").fetchone()
        assert row["state"] == ("completed" if settled else "cancelled")
        assert conn.execute("SELECT archived FROM items WHERE id=?", (item_id,)).fetchone()[0] == 1
        assert conn.execute("SELECT running_since FROM task_timing").fetchone()[0] is None
        assert db.active_run(conn) is None


def test_mcp_requires_explicit_owner_and_strict_confirmation_including_legacy(app):
    run_id = make_run(app)
    legacy = WorkflowApplication(app.workspace_root, session_id="")
    legacy_id = make_run(legacy)
    server = mcp_server.create_server(workspace_root=app.workspace_root)

    async def exercise():
        tools = await server.list_tools()
        schema = next(tool.input_schema for tool in tools if tool.name == "tapl_discard_run")
        assert next(tool.annotations for tool in tools if tool.name == "tapl_discard_run").destructive_hint
        assert set(schema["required"]) == {"run_id", "confirmed", "confirmation_run_id", "session_id"}
        async with Client(server) as client:
            for arguments in (
                {"run_id": run_id, "confirmed": True, "session_id": "owner"},
                {"run_id": run_id, "confirmation_run_id": run_id[:8], "confirmed": True, "session_id": "owner"},
                {"run_id": run_id, "confirmation_run_id": run_id.upper(), "confirmed": True, "session_id": "owner"},
                {"run_id": run_id, "confirmation_run_id": run_id, "confirmed": True},
                {"run_id": run_id, "confirmation_run_id": run_id, "confirmed": True, "session_id": "other"},
                *({"run_id": run_id, "confirmation_run_id": run_id, "confirmed": value, "session_id": "owner"} for value in (1, "true", False)),
            ):
                assert (await client.call_tool("tapl_discard_run", arguments)).is_error
            # The dedicated explicit empty owner is supported while ordinary
            # session-aware write guards still reject omitted ownership.
            assert (await client.call_tool("tapl_finish_archive", {"slug": "wrong"})).is_error
            for identifier, owner in ((legacy_id, ""), (run_id, "owner")):
                result = await client.call_tool("tapl_discard_run", {"run_id": identifier, "confirmation_run_id": identifier, "confirmed": True, "session_id": owner})
                assert not result.is_error, result.content
                assert result.structured_content["deleted_run_ids"] == [identifier]
                assert result.structured_content["archives"] == []

    asyncio.run(exercise())


@pytest.mark.parametrize("proof", [None, "", "partial", "uppercase", "padded"])
def test_typed_proof_is_exact_and_checked_before_connection(app, proof):
    run_id = make_run(app)
    value = {"partial": run_id[:8], "uppercase": run_id.upper(), "padded": f" {run_id}"}.get(proof, proof)
    with mock.patch.object(app, "_connection", side_effect=AssertionError("must not open a connection")):
        with pytest.raises(ValueError, match="confirmation_run_id"):
            app.discard_run(run_id=run_id, confirmed=True, confirmation_run_id=value)
        with pytest.raises(TypeError):
            app.discard_run(run_id=run_id, confirmed=True)
    with app._connection() as conn:
        with pytest.raises(ValueError, match="confirmation_run_id"):
            db.discard_run(conn, run_id=run_id, confirmed=True, confirmation_run_id=value)
        assert not conn.in_transaction
        assert db.active_run(conn)["id"] == run_id


def test_empty_run_deletes_routine_history_approvals_but_keeps_one_audit(app):
    run_id = make_run(app)
    app.record_approval(decision="approved", prompt="Routine approval", source="explicit_user")
    with app._connection() as conn:
        for event_type in ("SessionStart", "UserPromptSubmit", "run_summary", "memory_recall_attempted"):
            db.record_event(conn, run_id=run_id, event_type=event_type)
    result = app.discard_run(run_id=run_id, confirmed=True, confirmation_run_id=run_id)
    assert result["deleted_run_ids"] == [run_id]
    assert result["archives"] == result["archived_run_ids"] == []
    with app._connection() as conn:
        assert not conn.execute("SELECT * FROM workflow_runs").fetchall()
        assert not conn.execute("SELECT * FROM archives").fetchall()
        assert not conn.execute("SELECT * FROM approvals").fetchall()
        events = conn.execute("SELECT * FROM events").fetchall()
        assert len(events) == 1 and events[0]["event_type"] == "run_discarded" and events[0]["run_id"] is None
        audit = json.loads(events[0]["payload_json"])
        assert audit["confirmation_run_id"] == run_id and audit["deleted_run_ids"] == [run_id]
        assert events[0]["session_id"] == "owner"
        assert not conn.execute("PRAGMA foreign_key_check").fetchall()


@pytest.mark.parametrize("evidence", ["result", "batch", "archive", "memory_event"])
def test_itemless_runs_with_substantive_history_are_archived(app, evidence):
    run_id = make_run(app)
    with app._connection() as conn:
        if evidence == "result":
            conn.execute("UPDATE workflow_runs SET result_summary='Useful result' WHERE id=?", (run_id,))
        elif evidence == "batch":
            conn.execute("INSERT INTO execution_batches(id,run_id,parallel_group,state,created_at) VALUES('empty',?,'g','active',?)", (run_id, db.utc_now()))
        elif evidence == "archive":
            conn.execute("INSERT INTO archives(id,run_id,slug,summary,created_at) VALUES(?,?,'past','Keep',?)", (f"discard-{run_id}", run_id, db.utc_now()))
        else:
            db.record_event(conn, run_id=run_id, event_type="memory_reinforced", payload={"memory_id": "historical"})
        conn.commit()
    result = app.discard_run(run_id=run_id, confirmed=True, confirmation_run_id=run_id)
    assert result["archived_run_ids"] == [run_id] and result["deleted_run_ids"] == []
    with app._connection() as conn:
        if evidence == "result":
            assert conn.execute("SELECT result_summary FROM workflow_runs WHERE id=?", (run_id,)).fetchone()[0] == "Useful result"
        elif evidence == "archive":
            assert conn.execute("SELECT summary FROM archives WHERE id=?", (f"discard-{run_id}",)).fetchone()[0] == "Keep"
            assert len(conn.execute("SELECT * FROM archives WHERE run_id=?", (run_id,)).fetchall()) == 2
        elif evidence == "batch":
            assert conn.execute("SELECT state FROM execution_batches WHERE id='empty'").fetchone()[0] == "cancelled"
        else:
            assert conn.execute("SELECT COUNT(*) FROM events WHERE event_type='memory_reinforced'").fetchone()[0] == 1


@pytest.mark.parametrize("reference", ["created_run_id", "source_run_id", "last_reinforced_run_id"])
@pytest.mark.parametrize("memory_state", ["active", "deleted"])
def test_all_memory_references_prevent_physical_deletion(app, reference, memory_state):
    run_id = make_run(app)
    other = WorkflowApplication(app.workspace_root, session_id="other")
    other_id = make_run(other)
    values = {"created_run_id": other_id, "source_run_id": other_id, "last_reinforced_run_id": None}
    values[reference] = run_id
    with app._connection() as conn:
        conn.execute(
            "INSERT INTO memories(memory_id,created_run_id,slot,source_run_id,note,fingerprint,state,created_at,content_updated_at,last_reinforced_run_id) "
            "VALUES('memory',?,1,?,'Keep memory','fingerprint',?,?,?,?)",
            (values["created_run_id"], values["source_run_id"], memory_state, db.utc_now(), db.utc_now(), values["last_reinforced_run_id"]),
        )
        memory = dict(conn.execute("SELECT * FROM memories").fetchone())
        conn.execute("INSERT INTO memory_fts(rowid,cue,note) VALUES(?,'cue','Keep memory')", (memory["id"],))
        conn.commit()
    result = app.discard_run(run_id=run_id, confirmed=True, confirmation_run_id=run_id)
    assert result["archived_run_ids"] == [run_id] and not result["deleted_run_ids"]
    with app._connection() as conn:
        assert dict(conn.execute("SELECT * FROM memories").fetchone()) == memory
        assert conn.execute("SELECT note FROM memory_fts").fetchone()[0] == "Keep memory"
        assert conn.execute("SELECT status FROM workflow_runs WHERE id=?", (other_id,)).fetchone()[0] == "active"
        assert not conn.execute("PRAGMA foreign_key_check").fetchall()


@pytest.mark.parametrize("reference", ["incoming_dependency", "outgoing_dependency", "approval"])
def test_external_references_are_preserved_without_touching_other_owner(app, reference):
    run_id = make_run(app)
    other = WorkflowApplication(app.workspace_root, session_id="other")
    other_id = make_run(other)
    with app._connection() as conn:
        if reference == "approval":
            approval = db.record_approval(conn, decision="approved", prompt="Keep", source="explicit_user")
            conn.execute("INSERT INTO execution_batches(id,run_id,parallel_group,state,approval_id,created_at) VALUES('foreign',?,'g','active',?,?)",
                         (other_id, approval["id"], db.utc_now()))
        else:
            edge = (other_id, run_id) if reference == "incoming_dependency" else (run_id, other_id)
            conn.execute("INSERT INTO workflow_run_dependencies(run_id,dependency_run_id) VALUES(?,?)", edge)
        conn.commit()
        before = dict(conn.execute("SELECT * FROM workflow_runs WHERE id=?", (other_id,)).fetchone())
    result = app.discard_run(run_id=run_id, confirmed=True, confirmation_run_id=run_id)
    assert result["archived_run_ids"] == [run_id]
    with app._connection() as conn:
        assert dict(conn.execute("SELECT * FROM workflow_runs WHERE id=?", (other_id,)).fetchone()) == before
        if reference == "approval":
            assert conn.execute("SELECT state FROM execution_batches WHERE id='foreign'").fetchone()[0] == "active"
            assert conn.execute("SELECT run_id FROM approvals").fetchone()[0] == run_id
        else:
            assert tuple(conn.execute("SELECT run_id,dependency_run_id FROM workflow_run_dependencies").fetchone()) == edge
        assert not conn.execute("PRAGMA foreign_key_check").fetchall()


@pytest.mark.parametrize("retain", [True, False])
def test_split_dependency_references_follow_retained_runs(app, retain):
    run_id = make_run(app)
    split = app.split_run([
        {"key": "first", "summary": "first", "work_type": "implementation", "workflow_mode": "strict"},
        {"key": "second", "summary": "second", "work_type": "implementation", "workflow_mode": "strict", "depends_on": ["first"]},
        {"key": "third", "summary": "third", "work_type": "implementation", "workflow_mode": "strict", "depends_on": ["second"]},
    ])
    if retain:
        with app._connection() as conn:
            conn.execute("UPDATE workflow_runs SET result_summary='Retained result' WHERE id=?", (run_id,))
            conn.commit()
    result = app.discard_run(run_id=run_id, confirmed=True, confirmation_run_id=run_id)
    ids = [run_id, *(row["id"] for row in split["queued_runs"])]
    assert result["archived_run_ids"] == (ids if retain else [])
    assert result["deleted_run_ids"] == ([] if retain else ids)
    with app._connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM workflow_run_dependencies").fetchone()[0] == (2 if retain else 0)
        assert not conn.execute("PRAGMA foreign_key_check").fetchall()


def test_mixed_delete_archive_failure_rolls_back_every_disposition(app):
    run_id = make_run(app)
    split = app.split_run([{"key": key, "summary": key, "work_type": "implementation", "workflow_mode": "strict"}
                           for key in ("empty", "retained", "empty-too")])
    retained = split["queued_runs"][0]["id"]
    app.record_approval(decision="approved", prompt="Routine", source="explicit_user")
    with app._connection() as conn:
        conn.execute("UPDATE workflow_runs SET result_summary='Keep result' WHERE id=?", (retained,))
        conn.execute("CREATE TRIGGER fail_discard BEFORE INSERT ON events WHEN NEW.event_type='run_discarded' BEGIN SELECT RAISE(ABORT,'injected audit failure'); END")
        conn.commit()
        before = [dict(row) for row in conn.execute("SELECT * FROM workflow_runs ORDER BY id")]
    with pytest.raises(Exception, match="injected audit failure"):
        app.discard_run(run_id=run_id, confirmed=True, confirmation_run_id=run_id)
    with app._connection() as conn:
        assert [dict(row) for row in conn.execute("SELECT * FROM workflow_runs ORDER BY id")] == before
        assert conn.execute("SELECT COUNT(*) FROM approvals WHERE run_id=?", (run_id,)).fetchone()[0] == 1
        assert not conn.execute("SELECT * FROM archives").fetchall()
        assert not conn.execute("SELECT * FROM events WHERE event_type='run_discarded'").fetchall()
        assert not conn.execute("PRAGMA foreign_key_check").fetchall()
