"""Bind execution approval to the current RUN and its finalized plans."""

from __future__ import annotations

from contextlib import nullcontext
import hashlib
import json
import sqlite3
from typing import Any

from . import db


# Ordinary host hook events use observe/enforce. Internal evidence is written
# only by the corresponding transition, in the same transaction as its subject.
_MODE = "execution_evidence"
_TURN = "execution_user_turn"
_HOLD = "execution_scope_held"
_BINDING = "execution_approval_bound"
_START = "execution_task_started"
HELD_WORK_TYPES = ("analysis", "planning")


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _event(conn: sqlite3.Connection, run: sqlite3.Row, name: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT id, payload_json FROM events WHERE session_id=? AND run_id=? AND mode=? "
        "AND event_type=? ORDER BY id DESC LIMIT 1", (run["session_id"], run["id"], _MODE, name),
    ).fetchone()


def _write(conn: sqlite3.Connection, run: sqlite3.Row, name: str, data: dict) -> None:
    conn.execute(
        "INSERT INTO events(session_id,run_id,event_type,mode,payload_json,created_at) "
        "VALUES(?,?,?,?,?,?)",
        (run["session_id"], run["id"], name, _MODE, json.dumps(data), db.utc_now()),
    )


def is_held(conn: sqlite3.Connection, run: sqlite3.Row) -> bool:
    if run["work_type"] in HELD_WORK_TYPES or _event(conn, run, _HOLD) is not None:
        return True
    return run["work_type"] in db.LIGHTWEIGHT_WORK_TYPES and conn.execute(
        "SELECT 1 FROM items WHERE run_id=? AND kind='plan' LIMIT 1", (run["id"],),
    ).fetchone() is not None


def mark_hold(conn: sqlite3.Connection, run: sqlite3.Row, *, renew: bool = False) -> None:
    if renew or _event(conn, run, _HOLD) is None:
        _write(conn, run, _HOLD, {})


def inherit_archive_hold(conn: sqlite3.Connection, run: sqlite3.Row) -> None:
    if is_held(conn, run):
        mark_hold(conn, run)
        return
    previous = conn.execute(
        "SELECT r.* FROM workflow_runs r LEFT JOIN archives a ON a.run_id=r.id "
        "WHERE r.session_id=? AND r.status='archived' "
        "ORDER BY r.archived_at DESC, a.rowid DESC, r.rowid DESC LIMIT 1", (run["session_id"],),
    ).fetchone()
    if previous is not None and is_held(conn, previous):
        approval = db.latest_approval(conn, run_id=previous["id"])
        if not effective(conn, previous, approval):
            mark_hold(conn, run)


def _managed(conn: sqlite3.Connection, run: sqlite3.Row) -> bool:
    return is_held(conn, run) or conn.execute(
        "SELECT 1 FROM events WHERE session_id=? AND (event_type='UserPromptSubmit' "
        "OR (event_type=? AND mode=?)) LIMIT 1", (run["session_id"], _TURN, _MODE),
    ).fetchone() is not None


def _scope(conn: sqlite3.Connection, run: sqlite3.Row) -> str | None:
    plans = conn.execute(
        "SELECT i.status,i.stable_id,i.title,i.raw_text,i.custom_fields_json,p.summary,p.objective,"
        "p.requirements_trace,p.selected_approach,p.affected_files,p.execution_order,p.risks,"
        "p.validation,p.approval_needs,p.notes FROM items i JOIN plans p ON p.item_id=i.id "
        "WHERE i.run_id=? AND i.kind='plan' ORDER BY i.stable_id", (run["id"],),
    ).fetchall()
    if not plans or any(str(row["status"]).lower() != "finalized" for row in plans):
        return None
    rejection = conn.execute(
        "SELECT max(id) FROM approvals WHERE run_id=? AND kind=? AND decision='rejected'",
        (run["id"], db.DEFAULT_APPROVAL_KIND),
    ).fetchone()[0]
    hold = _event(conn, run, _HOLD)
    material = [run["session_id"], run["id"], rejection, hold["id"] if hold else None,
                [list(row)[1:] for row in plans]]
    return _digest(json.dumps(material, ensure_ascii=False, separators=(",", ":")))


def observe_user_prompt(conn: sqlite3.Connection, payload: dict[str, Any]) -> None:
    """Called only by the root UserPromptSubmit hook. Never retain prompt text."""
    with (nullcontext() if conn.in_transaction else conn):
        if not conn.in_transaction:
            conn.execute("BEGIN IMMEDIATE")
        run = db.active_run(conn)
        if run is None:
            raise ValueError("no active RUN for host user turn")
        inherit_archive_hold(conn, run)
        prompt = payload.get("prompt")
        data: dict[str, str] = {}
        if isinstance(prompt, str) and prompt.strip():
            data["prompt_digest"] = _digest(prompt)
        turn_id = payload.get("turn_id")
        if isinstance(turn_id, str) and turn_id:
            data["turn_id"] = turn_id
            previous = _event(conn, run, _TURN)
            if previous is not None and json.loads(previous["payload_json"]) == data:
                return
        _write(conn, run, _TURN, data)


def effective(conn: sqlite3.Connection, run: sqlite3.Row, approval: sqlite3.Row | None) -> bool:
    if approval is None or approval["decision"] != "approved":
        return False
    if not _managed(conn, run):
        return True
    binding = _event(conn, run, _BINDING)
    if binding is None:
        return False
    data = json.loads(binding["payload_json"])
    return data["approval_id"] == approval["id"] and data["scope"] == _scope(conn, run)


def _direct_turn(conn: sqlite3.Connection, run: sqlite3.Row, turn: sqlite3.Row | None) -> bool:
    if turn is None or is_held(conn, run) or run["work_type"] not in ("implementation", "mixed"):
        return False
    if run["request_summary"] == db.DEFAULT_REQUEST_SUMMARY or db.latest_approval(conn, run_id=run["id"]):
        return False
    first_id = conn.execute(
        "SELECT min(id) FROM events WHERE run_id=? AND event_type=? AND mode=?",
        (run["id"], _TURN, _MODE),
    ).fetchone()[0]
    return turn["id"] == first_id and bool(json.loads(turn["payload_json"]).get("prompt_digest"))


def confirmation_state(conn: sqlite3.Connection) -> dict[str, str] | None:
    run = db.active_run(conn)
    if run is None or run["request_summary"] == db.DEFAULT_REQUEST_SUMMARY or not _managed(conn, run):
        return None
    if effective(conn, run, db.latest_approval(conn, run_id=run["id"])):
        return None
    turn = _event(conn, run, _TURN)
    if _direct_turn(conn, run, turn):
        return None
    scope = _scope(conn, run)
    if not scope:
        return {"state": "finalize_plan"}
    return {"state": "awaiting_user", "scope": _question_scope(scope, turn)}


def _question_scope(scope: str, turn: sqlite3.Row | None) -> str:
    return _digest(json.dumps([scope, turn["id"] if turn is not None else None]))


def approval_proof(
    conn: sqlite3.Connection, run: sqlite3.Row, prompt: str, source: str, approval_scope: str | None,
) -> dict[str, Any] | None:
    if not _managed(conn, run):
        return None
    if run["status"] != "active":
        raise ValueError("execution approval requires the active RUN")
    scope = _scope(conn, run)
    if not scope:
        raise ValueError("Finalize the current RUN's plans before recording execution approval.")
    turn = _event(conn, run, _TURN)
    if source == "request_user_input":
        if approval_scope != _question_scope(scope, turn):
            raise ValueError("Execution approval needs the current approval_scope captured before the question. "
                             "Ask the user again with request_user_input if the scope changed.")
        # The Agent records the user's real tool answer. This check binds its
        # record to the plans and turn, independent of the source of the answer.
        return {"scope": scope}
    if turn:
        data = json.loads(turn["payload_json"])
        direct = False
        if source == "explicit_user" and data.get("prompt_digest") == _digest(prompt):
            direct = _direct_turn(conn, run, turn)
            if not direct:
                previous = _event(conn, run, _BINDING)
                direct = (previous is not None and json.loads(previous["payload_json"])["turn_event_id"] == turn["id"]
                          and effective(conn, run, db.latest_approval(conn, run_id=run["id"])))
        if direct:
            return {"turn_event_id": turn["id"], "scope": scope}
    raise ValueError("Execution approval requires a verified direct user request or the user's "
                     "request_user_input approval for this RUN and plan.")


def bind_approval(conn: sqlite3.Connection, run: sqlite3.Row, approval_id: int, proof: dict) -> None:
    _write(conn, run, _BINDING, {"approval_id": approval_id, **proof})


def require_approval(
    conn: sqlite3.Connection, run: sqlite3.Row, *, allow_unmanaged_start: bool = False,
) -> sqlite3.Row | None:
    approval = db.latest_approval(conn, run_id=run["id"])
    if allow_unmanaged_start and approval is None and not _managed(conn, run):
        return None
    if not effective(conn, run, approval):
        raise ValueError("Execution requires current execution approval for the active RUN and finalized plan.")
    return approval


# Eligible tasks must point to a current finalized plan in the same RUN. Both
# start and the durable-tool hook recheck dependencies against the same snapshot.
_READY_TASKS = """
    SELECT i.id, i.status, t.execution_mode, t.executor_kind, p.id AS plan_item_id
    FROM items i JOIN tasks t ON t.item_id=i.id
    JOIN items p ON p.run_id=i.run_id AND p.kind='plan' AND p.stable_id=t.spec_id
    JOIN plans ON plans.item_id=p.id
    WHERE i.run_id=? AND i.kind='task' AND i.archived=0 AND p.archived=0
      AND lower(p.status)='finalized' AND NOT EXISTS (
        SELECT 1 FROM task_dependencies td JOIN items dep ON dep.id=td.dependency_item_id
        WHERE td.task_item_id=i.id AND (dep.run_id<>i.run_id OR dep.archived<>0 OR dep.status<>'Completed')
      )
"""


def bind_task_start(conn: sqlite3.Connection, run: sqlite3.Row, task_id: str) -> None:
    approval = require_approval(conn, run, allow_unmanaged_start=True)
    if not _managed(conn, run):
        return
    task = conn.execute(_READY_TASKS + " AND i.stable_id=?", (run["id"], task_id)).fetchone()
    if task is None or task["status"] not in ("Pending", "In Progress"):
        raise ValueError("Task start requires a Pending task linked to a finalized plan with completed dependencies.")
    if task["execution_mode"] != "sequential" or task["executor_kind"] != "main":
        raise ValueError("Use parallel dispatch for subagent tasks.")
    _write(conn, run, _START, {"approval_id": approval["id"], "task_item_id": task["id"],
                              "plan_item_id": task["plan_item_id"]})


def require_active_execution(conn: sqlite3.Connection) -> None:
    with (nullcontext() if conn.in_transaction else conn):
        if not conn.in_transaction:
            conn.execute("BEGIN")
        _require_active_execution(conn)


def _require_active_execution(conn: sqlite3.Connection) -> None:
    run = db.active_run(conn)
    if run is None:
        raise ValueError("Durable changes require an active RUN with execution approval.")
    approval = require_approval(conn, run)
    if _managed(conn, run):
        started = conn.execute(_READY_TASKS + """
            AND i.status='In Progress' AND (
                (t.execution_mode='sequential' AND t.executor_kind='main' AND EXISTS (
                    SELECT 1 FROM events e WHERE e.run_id=i.run_id AND e.mode=? AND e.event_type=?
                    AND json_extract(e.payload_json,'$.approval_id')=?
                    AND json_extract(e.payload_json,'$.task_item_id')=i.id
                    AND json_extract(e.payload_json,'$.plan_item_id')=p.id
                )) OR (t.execution_mode='parallel' AND t.executor_kind='subagent' AND EXISTS (
                    SELECT 1 FROM task_executions x JOIN execution_batches b ON b.id=x.batch_id
                    WHERE x.task_item_id=i.id AND b.run_id=i.run_id AND b.approval_id=? AND b.state='active'
                    AND x.state IN ('dispatched','running')
                ))
            ) LIMIT 1""", (run["id"], _MODE, _START, approval["id"], approval["id"])).fetchone()
    else:
        started = conn.execute(
            "SELECT 1 FROM items WHERE run_id=? AND kind='task' AND archived=0 AND status='In Progress' LIMIT 1",
            (run["id"],),
        ).fetchone()
    if started is None:
        raise ValueError("Start a task or dispatch its batch under the current execution approval before making durable changes.")
