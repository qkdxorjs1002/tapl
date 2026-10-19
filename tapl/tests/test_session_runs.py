"""Multiple conversations may share a workspace without sharing workflow ownership."""

from __future__ import annotations

import asyncio
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from threading import Barrier
from unittest import mock

import pytest

from taplctl import db, recall, sessions


def plan_and_task(conn, label: str, *, parallel: bool = False) -> None:
    db.upsert_plan(conn, plan_id="PLAN-001", title=label, status="Finalized")
    db.upsert_task(
        conn, task_id="TASK-001", title=label, status="Pending", spec_id="PLAN-001",
        goal="Independent work", action="Perform work", verification="Check work",
        **({"execution_mode": "parallel", "executor_kind": "subagent", "parallel_group": "group"}
           if parallel else {}),
    )


def split_requests(label: str) -> list[dict]:
    return [
        {"key": "first", "summary": f"{label} first", "work_type": "analysis", "workflow_mode": "standard"},
        {"key": "second", "summary": f"{label} second", "work_type": "analysis", "workflow_mode": "standard", "depends_on": ["first"]},
    ]


def test_same_ids_and_approvals_belong_to_each_session(tmp_path: Path) -> None:
    path = tmp_path / "tapl.db"
    with closing(db.connect(path, session_id="a")) as a, closing(db.connect(path, session_id="b")) as b:
        run_a = db.ensure_active_run(a, request_summary="A")
        run_b = db.ensure_active_run(b, request_summary="B")
        assert run_a["id"] != run_b["id"]
        plan_and_task(a, "A")
        plan_and_task(b, "B")
        db.record_approval(a, decision="approved", prompt="Execute A")
        assert db.latest_approval(b) is None
        db.record_approval(b, decision="rejected", prompt="Do not execute B")
        assert db.latest_approval(a)["decision"] == "approved"
        assert db.latest_approval(b)["decision"] == "rejected"
        for conn, title in ((a, "A"), (b, "B")):
            status = db.status_payload(conn)
            assert [p["title"] for p in status["plans"]] == [title]
            assert [t["title"] for t in status["tasks"]] == [title]
            assert status["tasks"][0]["stable_id"] == "TASK-001"
        assert {run["id"] for run in db.active_runs(a)} == {run_a["id"], run_b["id"]}


@pytest.mark.parametrize("operation", ["plan", "event", "approval"])
def test_foreign_explicit_run_writes_are_rejected(tmp_path: Path, operation: str) -> None:
    path = tmp_path / "tapl.db"
    with closing(db.connect(path, session_id="a")) as a, closing(db.connect(path, session_id="b")) as b:
        foreign_id = db.ensure_active_run(a)["id"]
        db.ensure_active_run(b)
        before = db.status_payload(a)
        with pytest.raises(ValueError):
            if operation == "plan":
                db.upsert_plan(b, plan_id="PLAN-001", title="Intrusion", status="Draft", run_id=foreign_id)
            elif operation == "event":
                db.record_event(b, event_type="Stop", message="Intrusion", run_id=foreign_id)
            else:
                db.record_approval(b, decision="approved", run_id=foreign_id)
        after = db.status_payload(a)
        for key in ("active_run", "plans", "tasks", "recent_events", "approvals"):
            assert after.get(key) == before.get(key)


def test_session_reconnect_and_missing_identity_do_not_adopt_another_run(tmp_path: Path) -> None:
    path = tmp_path / "tapl.db"
    ids = {}
    for owner in ("a", "b", ""):
        with closing(db.connect(path, session_id=owner)) as conn:
            assert db.active_run(conn) is None
            ids[owner] = db.ensure_active_run(conn)["id"]
    assert len(set(ids.values())) == 3
    for owner in ("b", "", "a", "b"):
        with closing(db.connect(path, session_id=owner)) as conn:
            assert db.ensure_active_run(conn)["id"] == ids[owner]
            assert len(db.active_runs(conn)) == 3


@pytest.mark.parametrize("owners", [("a", "a", "a", "a"), ("a", "b", "c", "d")])
def test_concurrent_connections_create_one_active_run_per_session(tmp_path: Path, owners: tuple[str, ...]) -> None:
    path = tmp_path / "tapl.db"
    with closing(db.connect(path)):
        pass
    barrier = Barrier(len(owners))

    def start(owner: str) -> tuple[str, str]:
        barrier.wait(timeout=10)
        with closing(db.connect(path, session_id=owner)) as conn:
            return owner, str(db.ensure_active_run(conn)["id"])

    with ThreadPoolExecutor(max_workers=len(owners)) as pool:
        results = list(pool.map(start, owners))
    assert len({run_id for _, run_id in results}) == len(set(owners))
    with closing(db.connect(path)) as conn:
        assert len(db.active_runs(conn)) == len(set(owners))
        for owner, run_id in results:
            with closing(db.connect(path, session_id=owner)) as resumed:
                assert db.active_run(resumed)["id"] == run_id


def test_split_archive_activates_only_the_owners_queue_and_history_is_shared(tmp_path: Path) -> None:
    path = tmp_path / "tapl.db"
    with closing(db.connect(path, session_id="a")) as a, closing(db.connect(path, session_id="b")) as b:
        db.ensure_active_run(a)
        run_b = db.ensure_active_run(b)["id"]
        split_a = db.split_active_run(a, split_requests("A"))
        split_b = db.split_active_run(b, split_requests("B"))
        db.update_active_run_summary(a, result_summary="A first complete")
        archive = db.archive_active_run(a, slug="a-first", memory_review_enabled=False)
        assert db.active_run(a)["id"] == split_a["queued_runs"][0]["id"]
        assert db.queued_runs(a) == []
        assert db.active_run(b)["id"] == run_b
        assert db.queued_runs(b)[0]["id"] == split_b["queued_runs"][0]["id"]
        assert db.archive_detail(b, archive["id"])["archive"]["run_id"] == split_a["active_run"]["id"]
        assert any(row["id"] == archive["id"] for row in db.list_archives(b))


@pytest.mark.parametrize("operation", ["settle", "cancel", "recover"])
def test_foreign_execution_cannot_be_settled_cancelled_or_recovered(tmp_path: Path, operation: str) -> None:
    path = tmp_path / "tapl.db"
    with closing(db.connect(path, session_id="a")) as a, closing(db.connect(path, session_id="b")) as b:
        plan_and_task(a, "A", parallel=True)
        plan_and_task(b, "B", parallel=True)
        db.upsert_task(a, task_id="TASK-002", title="A second", status="Pending", spec_id="PLAN-001",
                       goal="Work", action="Act", verification="Verify", execution_mode="parallel",
                       executor_kind="subagent", parallel_group="group")
        db.record_approval(a, decision="approved")
        manifest = db.dispatch_tasks(a, ["TASK-001", "TASK-002"])
        batch_id = manifest["batch"]["id"]
        execution_id = manifest["executions"][0]["execution_id"]
        with pytest.raises(ValueError):
            if operation == "settle":
                db.settle_task_execution(b, execution_id, task_status="Completed")
            elif operation == "cancel":
                db.cancel_execution_batch(b, batch_id, reason="foreign cancellation")
            else:
                db.recover_execution_batch(b, batch_id, reason="foreign recovery")
        assert db.execution_batch_payload(a, batch_id)["batch"]["state"] == "active"
        assert db.get_active_task(a, "TASK-001")["status"] == "In Progress"
        assert db.get_active_task(b, "TASK-001")["status"] == "Pending"


def test_events_without_a_run_and_context_scopes_do_not_leak(tmp_path: Path) -> None:
    path = tmp_path / "tapl.db"
    with closing(db.connect(path)):
        pass

    async def call(owner: str) -> str:
        with sessions.session_scope(owner):
            await asyncio.sleep(0)
            def write() -> str:
                with closing(db.connect(path)) as conn:
                    db.record_event(conn, event_type="SessionStart", message=owner)
                    assert [event["message"] for event in db.status_payload(conn)["recent_events"]] == [owner]
                    return str(db.ensure_active_run(conn)["id"])
            return await asyncio.to_thread(write)

    async def exercise() -> list[str]:
        return await asyncio.gather(call("a"), call("b"))

    assert len(set(asyncio.run(exercise()))) == 2
    assert sessions.current_session_id() == ""
    with closing(db.connect(path)) as legacy:
        assert db.active_run(legacy) is None
        assert db.status_payload(legacy)["recent_events"] == []


def test_schema13_upgrade_preserves_legacy_owner_and_backs_up(tmp_path: Path) -> None:
    path = tmp_path / "tapl.db"
    with closing(db.connect(path)) as conn:
        legacy_id = db.ensure_active_run(conn, request_summary="Existing conversation")["id"]
        plan_and_task(conn, "Legacy work")
        db.record_event(conn, event_type="UserPromptSubmit", message="Legacy event")
        conn.execute("DROP INDEX idx_session_active_run")
        conn.execute("ALTER TABLE workflow_runs DROP COLUMN session_id")
        conn.execute("ALTER TABLE events DROP COLUMN session_id")
        conn.execute("CREATE UNIQUE INDEX idx_single_active_run ON workflow_runs(status) WHERE status = 'active'")
        conn.execute("UPDATE meta SET value = '13' WHERE key = 'schema_version'")
        conn.commit()
    with closing(db.connect(path, session_id="new-session")) as named:
        assert db.active_run(named) is None
        named_id = db.ensure_active_run(named)["id"]
        assert named_id != legacy_id
    with closing(db.connect(path)) as legacy:
        assert db.active_run(legacy)["id"] == legacy_id
        assert db.get_active_task(legacy, "TASK-001")["title"] == "Legacy work"
        assert db.status_payload(legacy)["recent_events"][0]["message"] == "Legacy event"
        assert len(db.active_runs(legacy)) == 2
    backup = path.with_name(path.name + ".pre-v14.bak")
    assert backup.exists()
    with closing(sqlite3.connect(backup)) as conn:
        assert conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()[0] == "13"
        assert conn.execute("SELECT id FROM workflow_runs WHERE status = 'active'").fetchone()[0] == legacy_id


def test_sessions_can_archive_the_same_slug_at_the_same_time(tmp_path: Path) -> None:
    path = tmp_path / "tapl.db"
    with closing(db.connect(path, session_id="a")) as a, closing(db.connect(path, session_id="b")) as b:
        run_a = db.ensure_active_run(a)["id"]
        run_b = db.ensure_active_run(b)["id"]
        with mock.patch.object(db, "utc_now", return_value="2026-10-19T12:00:00+00:00"):
            archive_a = db.archive_active_run(a, slug="completed", memory_review_enabled=False)
            archive_b = db.archive_active_run(b, slug="completed", memory_review_enabled=False)
        assert archive_a["id"] != archive_b["id"]
        assert {row["run_id"] for row in db.list_archives(a)} == {run_a, run_b}
        assert db.active_run(a) is None
        assert db.active_run(b) is None


@pytest.mark.parametrize("operation", ["recall", "finish"])
def test_run_bound_memory_mutations_reject_foreign_session(tmp_path: Path, operation: str) -> None:
    path = tmp_path / "tapl.db"
    with closing(db.connect(path, session_id="a")) as a, closing(db.connect(path, session_id="b")) as b:
        run_id = db.ensure_active_run(a)["id"]
        db.ensure_active_run(b)
        before = list(a.execute("SELECT * FROM events WHERE run_id = ?", (run_id,)))
        if operation == "recall":
            with pytest.raises((ValueError, recall.MemoryError)):
                recall.emit_recall_once(b, run_id=run_id, query="session routing")
        else:
            result = recall.finish_memories(b, run_id=run_id, review={"decision": "skip", "reason": "Foreign review"})
            assert result["status"] == "failed"
            assert "another session" in result["errors"][0]["message"]
        assert list(a.execute("SELECT * FROM events WHERE run_id = ?", (run_id,))) == before


def test_memory_events_appear_only_in_the_owning_sessions_recent_activity(tmp_path: Path) -> None:
    path = tmp_path / "tapl.db"
    with closing(db.connect(path, session_id="a")) as a, closing(db.connect(path, session_id="b")) as b:
        run_id = db.ensure_active_run(a)["id"]
        db.ensure_active_run(b)
        recall.emit_recall_once(a, run_id=run_id, query="session routing")
        own = db.status_payload(a)["recent_events"]
        assert any(row["event_type"] == "memory_recall_attempted" for row in own)
        assert all(row["session_id"] == "a" for row in own)
        assert db.status_payload(b)["recent_events"] == []
    with closing(db.connect(path)) as legacy:
        assert db.status_payload(legacy)["recent_events"] == []
