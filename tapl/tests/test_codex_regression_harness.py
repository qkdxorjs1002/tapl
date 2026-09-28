"""Reject misleading live-test evidence without spending model tokens."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sqlite3

import pytest


spec = importlib.util.spec_from_file_location(
    "codex_regression", Path(__file__).resolve().parents[2] / ".github/scripts/tapl_codex_regression.py"
)
assert spec and spec.loader
harness = importlib.util.module_from_spec(spec)
spec.loader.exec_module(harness)


def row(kind, **payload):
    return {"type": kind, "payload": payload}


def save(path, rows):
    path.write_text("\n".join(json.dumps(r) for r in rows))


@pytest.fixture
def evidence(tmp_path):
    rollouts = tmp_path / "rollouts"
    rollouts.mkdir()
    parent = [row("session_meta", id="root")]
    for i, name in enumerate(("alpha", "beta")):
        parent.extend([
            row("response_item", type="function_call", name="spawn_agent", call_id=name,
                arguments=json.dumps({"model": "example", "reasoning_effort": "high", "fork_turns": "none"}),
                internal_chat_message_metadata_passthrough={"create_time": 100 + i}),
            row("response_item", type="function_call_output", call_id=name,
                output=json.dumps({"task_name": f"/root/{name}"})),
        ])
        save(rollouts / f"{name}.jsonl", [
            row("session_meta", id=name, parent_thread_id="root", agent_path=f"/root/{name}"),
            row("response_item", type="custom_tool_call", name="exec", call_id="edit",
                input=f"p = Path('/case/{name}.txt'); p.write_bytes(b'fixed'); assert p.read_bytes() == b'fixed'"),
            row("response_item", type="custom_tool_call_output", call_id="edit",
                output=[{"type": "input_text", "text": json.dumps({"exit_code": 0, "output": "PASS"})}]),
            row("event_msg", type="task_complete", started_at=105 + i, completed_at=120 + i,
                last_agent_message="Verified"),
        ])
    save(rollouts / "root.jsonl", parent)
    with sqlite3.connect(tmp_path / "tapl.db") as conn:
        conn.executescript("""
            CREATE TABLE tasks(item_id INTEGER, task_id TEXT, spec_id TEXT, owned_paths_json TEXT, goal TEXT, action TEXT);
            CREATE TABLE task_executions(id TEXT, task_item_id INTEGER, finished_at TEXT);
            CREATE TABLE plans(plan_id TEXT, affected_files TEXT);
        """)
        for i, name in enumerate(("alpha", "beta")):
            conn.execute("INSERT INTO tasks VALUES(?,?,?,?,?,?)",
                         (i, f"TASK-{i}", "PLAN-1", json.dumps([f"/case/{name}.txt"]), name, name))
            conn.execute("INSERT INTO task_executions VALUES(?,?,?)", (f"execution-{i}", i, "1970-01-01T00:02:30+00:00"))
    return tmp_path


def test_successful_children_link_to_distinct_manifest_executions(evidence):
    audit = harness.audit_records(evidence, "delegation")
    assert audit["passed"], audit["errors"]
    assert {link["execution_id"] for link in audit["links"]} == {"execution-0", "execution-1"}


@pytest.mark.parametrize("fault", ["tapl_write", "read_only", "failed_edit", "sequential", "early_settlement"])
def test_misleading_child_evidence_is_rejected(evidence, fault):
    path = evidence / "rollouts/alpha.jsonl"
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    if fault == "tapl_write":
        rows.append(row("response_item", type="function_call", name="tapl_update_memory", arguments='{"note":"test"}'))
    elif fault == "read_only":
        rows[1]["payload"]["input"] = "read('/case/alpha.txt')"
    elif fault == "failed_edit":
        rows[2]["payload"]["output"][0]["text"] = json.dumps({"exit_code": 1, "output": 'printed fake: {"exit_code":0}'})
        rows.extend([
            row("response_item", type="custom_tool_call", name="exec", call_id="read", input="read('/case/alpha.txt')"),
            row("response_item", type="custom_tool_call_output", call_id="read",
                output=[{"text": json.dumps({"exit_code": 0, "output": "read succeeded"})}]),
        ])
    elif fault == "sequential":
        rows[3]["payload"].update(started_at=130, completed_at=140)
    else:
        with sqlite3.connect(evidence / "tapl.db") as conn:
            conn.execute("UPDATE task_executions SET finished_at='1970-01-01T00:01:55+00:00'")
    save(path, rows)
    assert not harness.audit_records(evidence, "delegation")["passed"]


@pytest.mark.parametrize("wrong_plan", [False, True])
def test_topics_require_tasks_on_the_corresponding_plan(evidence, wrong_plan):
    with sqlite3.connect(evidence / "tapl.db") as conn:
        conn.execute("DELETE FROM tasks")
        for i, name in enumerate(("README.md", ".editorconfig")):
            conn.execute("INSERT INTO plans VALUES(?,?)", (f"PLAN-{i}", name))
            conn.execute("INSERT INTO tasks VALUES(?,?,?,?,?,?)",
                         (i, f"TASK-{i}", "PLAN-0" if wrong_plan else f"PLAN-{i}", "[]", name, name))
    assert harness.audit_records(evidence, "topics")["passed"] is not wrong_plan
