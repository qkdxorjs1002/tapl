from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from unittest import mock

import pytest

from mcp import Client

from taplctl import db, mcp_server
from taplctl.application import WorkflowApplication


def at(value: str):
    return mock.patch.object(db, "utc_now", return_value=f"2026-01-01T00:{value}+00:00")


def task(conn, task_id: str, status: str, **extra):
    return db.upsert_task(
        conn, task_id=task_id, title=task_id, status=status, spec_id="PLAN-001",
        goal="Goal", action="Act", verification="Verify", **extra,
    )


def test_sequential_timing_counts_only_running_intervals_and_surfaces_in_reads() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        conn = db.connect(Path(tmp) / ".tapl" / "tapl.db")
        with at("00:00"):
            db.ensure_active_run(conn)
            db.upsert_plan(conn, plan_id="PLAN-001", title="Plan", status="Finalized")
            item = task(conn, "TASK-001", "Pending")
        with at("01:00"):
            task(conn, "TASK-001", "In Progress")
        with at("02:00"):
            task(conn, "TASK-001", "In Progress", result="Same status edit")
        with at("03:00"):
            running = db.status_payload(conn)["tasks"][0]["execution_timing"]
        assert running == {
            "started_at": "2026-01-01T00:01:00+00:00", "finished_at": None,
            "elapsed_seconds": 120.0, "running_since": "2026-01-01T00:01:00+00:00",
            "as_of": "2026-01-01T00:03:00+00:00",
        }
        with at("04:00"):
            task(conn, "TASK-001", "Blocked")
        with at("09:00"):
            blocked = db.item_detail(conn, item["id"])["execution_timing"]
        assert blocked["elapsed_seconds"] == 180.0
        assert blocked["running_since"] is None
        assert blocked["finished_at"] == "2026-01-01T00:04:00+00:00"
        with at("10:00"):
            task(conn, "TASK-001", "In Progress")
        with at("12:00"):
            task(conn, "TASK-001", "Completed")
        with at("20:00"):
            fixed = db.item_detail(conn, item["id"])["execution_timing"]
        assert fixed["elapsed_seconds"] == 300.0
        assert fixed["finished_at"] == "2026-01-01T00:12:00+00:00"
        assert fixed["running_since"] is None
        with at("21:00"):
            task(conn, "TASK-001", "Completed", result="Edited")
        assert db.item_detail(conn, item["id"])["execution_timing"]["elapsed_seconds"] == 300.0
        with at("22:00"):
            compact = WorkflowApplication(Path(tmp)).get_status()["tasks"][0]
            archive = db.archive_active_run(conn, slug="timing", memory_review_enabled=False)
            archived = db.archive_detail(conn, archive["id"])["items"]
        assert compact["execution_timing"]["elapsed_seconds"] == 300.0
        assert next(row for row in archived if row["kind"] == "task")["execution_timing"]["elapsed_seconds"] == 300.0
        conn.close()


def test_parallel_dispatch_cancel_restart_and_settle_share_timing() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        conn = db.connect(Path(tmp) / "tapl.db")
        with at("00:00"):
            db.ensure_active_run(conn)
            db.upsert_plan(conn, plan_id="PLAN-001", title="Plan", status="Finalized")
            for task_id in ("TASK-001", "TASK-002"):
                task(conn, task_id, "Pending", execution_mode="parallel",
                     executor_kind="subagent", parallel_group="group")
            db.record_approval(conn, decision="approved")
        with at("01:00"):
            first = db.dispatch_tasks(conn, ["TASK-001", "TASK-002"], batch_id="first")
        with at("03:00"):
            db.cancel_execution_batch(conn, "first", reason="Pause", recover_pending=True)
        with at("10:00"):
            second = db.dispatch_tasks(conn, ["TASK-001", "TASK-002"], batch_id="second")
        with at("12:00"):
            for execution in second["executions"]:
                db.settle_task_execution(
                    conn, execution["execution_id"], task_status="Completed",
                    task_id=execution["task_id"], result="Done", verification="Verified",
                )
        with at("20:00"):
            tasks = db.status_payload(conn)["tasks"]
        assert all(row["execution_timing"]["elapsed_seconds"] == 240.0 for row in tasks)
        assert all(row["execution_timing"]["finished_at"] == "2026-01-01T00:12:00+00:00" for row in tasks)
        assert all(row["execution_timing"]["running_since"] is None for row in tasks)
        conn.close()


def test_migration_keeps_unknown_sequential_null_and_backfills_known_batch_intervals() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "tapl.db"
        conn = db.connect(path)
        with at("00:00"):
            db.ensure_active_run(conn)
            db.upsert_plan(conn, plan_id="PLAN-001", title="Plan", status="Finalized")
            sequential = task(conn, "TASK-001", "Pending")
            task(conn, "TASK-002", "Pending", execution_mode="parallel",
                 executor_kind="subagent", parallel_group="group")
            task(conn, "TASK-003", "Pending", execution_mode="parallel",
                 executor_kind="subagent", parallel_group="group")
            db.record_approval(conn, decision="approved")
        with at("01:00"):
            batch = db.dispatch_tasks(conn, ["TASK-002", "TASK-003"])
        with at("03:00"):
            for execution in batch["executions"]:
                db.settle_task_execution(conn, execution["execution_id"],
                                         task_status="Completed", task_id=execution["task_id"])
        conn.execute("DROP TABLE task_timing")
        conn.execute("UPDATE meta SET value = '12' WHERE key = 'schema_version'")
        conn.commit()
        conn.close()
        migrated = db.connect(path)
        assert db.get_meta(migrated)["schema_version"] == str(db.SCHEMA_VERSION)
        with at("20:00"):
            rows = {row["stable_id"]: row for row in db.status_payload(migrated)["tasks"]}
        assert rows["TASK-001"]["execution_timing"] is None
        assert rows["TASK-002"]["execution_timing"]["elapsed_seconds"] == 120.0
        assert db.item_detail(migrated, sequential["id"])["execution_timing"] is None
        assert db.archive_detail(migrated, "missing") is None
        migrated.close()
        reopened = db.connect(path)
        assert db.status_payload(reopened)["tasks"][1]["execution_timing"]["elapsed_seconds"] == 120.0
        reopened.close()


def test_legacy_running_task_remains_unknown_until_a_new_running_interval() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        conn = db.connect(Path(tmp) / "tapl.db")
        with at("00:00"):
            db.ensure_active_run(conn)
            db.upsert_plan(conn, plan_id="PLAN-001", title="Plan", status="Finalized")
            item = task(conn, "TASK-001", "In Progress")
        conn.execute("DELETE FROM task_timing WHERE task_item_id = ?", (item["id"],))
        conn.commit()
        with at("01:00"):
            task(conn, "TASK-001", "In Progress", result="Metadata edit")
        with at("02:00"):
            task(conn, "TASK-001", "Blocked")
        assert db.item_detail(conn, item["id"])["execution_timing"] is None
        with at("10:00"):
            task(conn, "TASK-001", "In Progress")
        with at("11:00"):
            task(conn, "TASK-001", "Completed")
        assert db.item_detail(conn, item["id"])["execution_timing"]["elapsed_seconds"] == 60.0
        conn.close()


def test_new_schema_rejects_a_future_database_version() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "tapl.db"
        conn = db.connect(path)
        conn.execute("UPDATE meta SET value = ? WHERE key = 'schema_version'", (str(db.SCHEMA_VERSION + 1),))
        conn.commit()
        conn.close()
        with pytest.raises(RuntimeError, match="newer than supported"):
            db.connect(path)


def test_mcp_reads_preserve_timing_in_status_item_and_archive() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        conn = db.connect(root / ".tapl" / "tapl.db")
        with at("00:00"):
            db.ensure_active_run(conn)
            db.upsert_plan(conn, plan_id="PLAN-001", title="Plan", status="Finalized")
            measured = task(conn, "TASK-001", "Pending")
            task(conn, "TASK-002", "Completed")
        with at("01:00"):
            task(conn, "TASK-001", "In Progress")
        with at("02:00"):
            task(conn, "TASK-001", "Completed")
        server = mcp_server.create_server(workspace_root=root)

        async def check() -> None:
            async with Client(server) as client:
                for full in (False, True):
                    response = await client.call_tool("tapl_get_status", {"full": full})
                    assert not response.is_error
                    rows = response.structured_content["tasks"]
                    assert rows[0]["execution_timing"]["elapsed_seconds"] == 60.0
                    assert rows[1]["execution_timing"] is None
                for compact in (False, True):
                    response = await client.call_tool(
                        "tapl_get_item", {"item_id": measured["id"], "compact": compact}
                    )
                    assert not response.is_error
                    timing = response.structured_content["item"]["execution_timing"]
                    assert timing["elapsed_seconds"] == 60.0
                    assert timing["running_since"] is None
                archive = db.archive_active_run(conn, slug="mcp-timing", memory_review_enabled=False)
                response = await client.call_tool("tapl_get_archive", {"archive_id": archive["id"]})
                assert not response.is_error
                rows = {row["stable_id"]: row for row in response.structured_content["items"]}
                assert rows["TASK-001"]["execution_timing"]["elapsed_seconds"] == 60.0
                assert rows["TASK-002"]["execution_timing"] is None

        with at("20:00"):
            asyncio.run(check())
        conn.close()


def test_archiving_deferred_work_freezes_running_time_without_changing_task_status() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        conn = db.connect(Path(tmp) / "tapl.db")
        with at("00:00"):
            db.ensure_active_run(conn)
            db.upsert_plan(conn, plan_id="PLAN-001", title="Plan", status="Finalized")
            item = task(conn, "TASK-001", "In Progress")
        with at("02:00"):
            archive = db.archive_active_run(conn, slug="deferred", memory_review_enabled=False)
        with at("20:00"):
            detail = db.item_detail(conn, item["id"])
            archived = db.archive_detail(conn, archive["id"])["items"]
        assert detail["status"] == "In Progress"
        assert detail["execution_timing"]["elapsed_seconds"] == 120.0
        assert detail["execution_timing"]["running_since"] is None
        assert detail["execution_timing"]["finished_at"] == "2026-01-01T00:02:00+00:00"
        assert next(row for row in archived if row["kind"] == "task")["execution_timing"] == detail["execution_timing"]
        conn.close()
