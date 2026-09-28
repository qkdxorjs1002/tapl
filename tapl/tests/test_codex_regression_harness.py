"""Reject misleading live-test evidence without spending model tokens."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import shlex
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


def test_evidence_backup_includes_committed_wal_with_open_connections(tmp_path):
    source, destination = tmp_path / "source.db", tmp_path / "evidence.db"
    conn = sqlite3.connect(source)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA wal_autocheckpoint=0")
        conn.execute("CREATE TABLE archives(run_id TEXT)")
        conn.commit()
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        conn.execute("INSERT INTO archives VALUES('persisted-run')")
        conn.commit()
        assert source.with_name("source.db-wal").stat().st_size > 0
        harness.export_evidence_db(source, destination)
        with sqlite3.connect(destination) as backup:
            assert backup.execute("SELECT run_id FROM archives").fetchall() == [("persisted-run",)]
            assert backup.execute("PRAGMA integrity_check").fetchone() == ("ok",)
    finally:
        conn.close()


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


@pytest.mark.parametrize("wrong_plan", [False, True])
def test_topic_actions_can_name_the_replacement_without_repeating_the_filename(evidence, wrong_plan):
    with sqlite3.connect(evidence / "tapl.db") as conn:
        conn.execute("DELETE FROM tasks")
        for i, (name, action) in enumerate((("README.md", "transactoin → transaction"), (".editorconfig", "indent_size = 4 → 2"))):
            conn.execute("INSERT INTO plans VALUES(?,?)", (f"PLAN-{i}", name))
            conn.execute("INSERT INTO tasks VALUES(?,?,?,?,?,?)",
                         (i, f"TASK-{i}", "PLAN-0" if wrong_plan else f"PLAN-{i}", "[]", "수정", action))
    assert harness.audit_records(evidence, "topics")["passed"] is not wrong_plan


@pytest.mark.parametrize("fault", [None, "tapl_write", "test", "edit", "nested", "failed_read", "shell_edit", "npm_test"])
def test_observation_helper_evidence_rejects_executable_actions(evidence, fault):
    # Keep one actual linked child; observation does not require a task manifest.
    root = evidence / "rollouts/root.jsonl"
    save(root, [json.loads(line) for line in root.read_text().splitlines()][:3])
    path = evidence / "rollouts/alpha.jsonl"
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    rows[1]["payload"]["input"] = "cat /case/README.md"
    if fault == "failed_read":
        rows[2]["payload"]["output"][0]["text"] = json.dumps({"exit_code": 1})
    elif fault:
        name = {"tapl_write": "tapl_summarize_run", "test": "pytest", "edit": "apply_patch", "nested": "spawn_agent",
                "shell_edit": "sed -i 's/a/b/' README.md", "npm_test": "npm test"}[fault]
        rows.append(row("response_item", type="function_call", name=name, arguments="{}"))
    save(path, rows)
    assert harness.audit_records(evidence, "scout")["passed"] is (fault is None)


@pytest.mark.parametrize("status,code", [("fulfilled", 0), ("fulfilled", 1), ("rejected", 0)])
def test_exit_codes_accept_settled_receipts_without_parsing_command_output(status, code):
    wrapped = {"i": 1, "result": {"status": status, "value": {"exit_code": code, "output": '{"exit_code":0}'}}}
    assert harness.command_exit_codes([{"text": json.dumps(wrapped)}]) == ([code] if status == "fulfilled" else [-1])
    assert harness.command_exit_codes({"output": json.dumps(wrapped)}) == []


@pytest.mark.parametrize("failure", ["exit", "rejected", "unverified"])
def test_one_successful_command_does_not_hide_a_failed_edit_in_the_same_call(evidence, failure):
    path = evidence / "rollouts/alpha.jsonl"
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    rows[2]["payload"]["output"] = [
        {"text": json.dumps({"i": i, "result": {"status": "fulfilled", "value": {"exit_code": code}}})}
        for i, code in enumerate((1, 0))
    ]
    if failure == "rejected":
        rows[2]["payload"]["output"][0] = {"text": json.dumps({"i": 0, "result": {"status": "rejected", "reason": "failed"}})}
    elif failure == "unverified":
        rows[2]["payload"]["output"][0] = {"text": json.dumps({"i": 0, "result": {"status": "fulfilled", "value": {"output": "no receipt"}}})}
    save(path, rows)
    assert not harness.audit_records(evidence, "delegation")["passed"]


def call(tool, arguments=None, result=None):
    if tool == "tapl_get_next" and result is None:
        result = {"workflow_policy": "Complete test policy", "subagent_guidance": "Test guidance", "config": {},
                  "policy_revision": "revision", "policy_unchanged": False}
    return {"type": "item.completed", "item": {"type": "mcp_tool_call", "tool": tool,
            "arguments": arguments or {}, "status": "completed",
            "result": {"structured_content": {"ok": True, **(result or {})}}}}


def command_events(identity, command, exit_code=0):
    return [{"type": "item.started", "item": {"id": identity, "type": "command_execution", "command": command}},
            {"type": "item.completed", "item": {"id": identity, "type": "command_execution", "command": command,
                                                  "exit_code": exit_code, "status": "completed"}}]


@pytest.fixture
def workspace(tmp_path):
    from taplctl import db
    (tmp_path / ".git").mkdir()
    db.initialize_workspace(tmp_path)
    (tmp_path / ".tapl/config.toml").write_text(
        '[search]\nmode="bm25"\n[subagents]\nsetup_complete=true\nenabled=true\n'
        'strategy="aggressive"\n[subagents.models]\nexample=["high"]\n')
    return tmp_path


def export_db(workspace):
    harness.export_evidence_db(workspace / ".tapl/tapl.db", workspace / "tapl.db")


def test_original_eight_conditions_are_preserved():
    assert {"scout", "inspection", "edit", "recall", "planning", "resume", "delegation", "topics"} <= harness.PROMPTS.keys()


@pytest.mark.parametrize("fault", [None, "compact_source", "no_source", "wrong_source", "get_memory_only", "failed_source", "no_recall", "no_use", "failed_verification", "late_source", "early_verification", "substring", "is_error"])
def test_seeded_memory_requires_recall_original_source_and_actual_reuse(workspace, fault):
    from taplctl.application import WorkflowApplication
    from taplctl.mcp_server import compact_item_payload
    seed = harness.seed_memory(workspace)
    app = WorkflowApplication(workspace)
    (workspace / "scenario.json").write_text(json.dumps(seed))
    events = [call("tapl_get_next"),
              call("tapl_summarize_run", result={"recall": {"memories": [{"id": seed["memory_id"]}]}}),
              call("tapl_get_archive", {"archive_id": seed["source_archive_id"]}, result=app.get_archive(seed["source_archive_id"])),
              *command_events("verify", "assert Path('README.md').read_bytes() == b'# Example\\n\\nAn atomic transaction.\\n'"),
              call("tapl_finish_run", {"memory_uses": [{"memory_id": seed["memory_id"], "revision": seed["memory_revision"],
                   "source_checked": True, "usage": "Applied original byte validation contract."}]})]
    if fault == "compact_source":
        events[2] = call("tapl_get_item", {"item_id": seed["source_item_id"], "compact": True},
                         result=compact_item_payload(app.get_item(seed["source_item_id"])))
    elif fault == "no_source":
        del events[2]
    elif fault == "wrong_source":
        events[2]["item"]["arguments"]["archive_id"] = "unrelated-archive"
    elif fault == "get_memory_only":
        events[2] = call("tapl_get_memory", {"memory_id": seed["memory_id"]})
    elif fault == "failed_source":
        events[2]["item"]["result"]["structured_content"]["ok"] = False
    elif fault == "no_recall":
        events[1]["item"]["result"]["structured_content"]["recall"]["memories"] = []
    elif fault == "no_use":
        events[-1]["item"]["arguments"] = {}
    elif fault == "failed_verification":
        events[4]["item"]["exit_code"] = 1
    elif fault == "late_source":
        events.append(events.pop(2))
    elif fault == "early_verification":
        events[2], events[3] = events[3], events[2]
    elif fault == "substring":
        for event in events[3:5]:
            event["item"]["command"] = "assert b'transaction' in Path('README.md').read_bytes()"
    elif fault == "is_error":
        events[2]["item"]["result"]["is_error"] = True
    save(workspace / "events.jsonl", events)
    export_db(workspace)
    result = harness.audit_records(workspace, "memory_reuse")
    assert result["passed"] is (fault in {None, "compact_source"}), result["errors"]


@pytest.mark.parametrize("fault", [None, "readonly_diff", "wrong_batch", "false_completion", "replaced_id", "missing_recovery", "missing_ids", "early_start", "missing_transition", "early_edit", "overlap"])
def test_interrupted_batch_requires_exact_recovery_and_safe_sequential_completion(workspace, fault):
    from taplctl.application import WorkflowApplication
    seed = harness.seed_interrupted_batch(workspace, "example")
    app = WorkflowApplication(workspace)
    assert seed["kind"].startswith("seeded interruption")
    app.recover_batch(seed["batch_id"], reason="Previous process ended before spawning")
    for i, name in enumerate(("alpha", "beta"), 1):
        task = f"TASK-00{i}"
        app.create_task(task, name, "PLAN-001", name, name, name,
                        execution_mode="sequential", executor_kind="main")
        app.start_task(task)
        app.settle_task(task, status="Completed", verification="Exact contents asserted", result="Typo fixed")
    events = [call("tapl_get_next"), call("tapl_get_status", {"full": True}, {"active_batches": [seed]}),
              call("tapl_recover_batch", {"batch_id": seed["batch_id"]}), call("tapl_start_task", {"task_id": "TASK-001"}),
              *command_events("alpha-edit", "Path('alpha.txt').write_text('alpha\\n')"),
              call("tapl_complete_task", {"task_id": "TASK-001"}), call("tapl_start_task", {"task_id": "TASK-002"}),
              *command_events("beta-edit", "Path('beta.txt').write_text('beta\\n')"),
              call("tapl_complete_task", {"task_id": "TASK-002"})]
    if fault == "wrong_batch":
        events[2]["item"]["arguments"]["batch_id"] = "another-batch"
    elif fault == "missing_recovery":
        del events[2]
    elif fault == "missing_ids":
        events[1]["item"]["result"] = {}
    elif fault == "early_start":
        events[2], events[3] = events[3], events[2]
    elif fault == "early_edit":
        events.insert(2, events.pop(4))
    elif fault == "overlap":
        events[6], events[7] = events[7], events[6]
    elif fault == "readonly_diff":
        command = "python - <<'PY'\nfrom pathlib import Path\np = Path('beta.txt')\np.write_bytes(b'beta\\n')\nPY\ngit diff -- alpha.txt beta.txt"
        for event in events:
            if event.get("item", {}).get("id") == "beta-edit":
                event["item"]["command"] = "/bin/bash -lc " + shlex.quote(command)
    export_db(workspace)
    with sqlite3.connect(workspace / "tapl.db") as conn:
        if fault == "false_completion":
            conn.execute("UPDATE task_executions SET state='completed'")
        elif fault == "replaced_id":
            conn.execute("UPDATE task_executions SET id='wrong-' || id")
        elif fault == "missing_transition":
            conn.execute("UPDATE tasks SET execution_mode='parallel',executor_kind='subagent'")
    (workspace / "scenario.json").write_text(json.dumps(seed))
    save(workspace / "events.jsonl", events)
    result = harness.audit_records(workspace, "batch_recovery")
    assert result["passed"] is (fault in {None, "readonly_diff"}), result["errors"]


@pytest.mark.parametrize("tail,expected", [
    ("git diff -- alpha.txt beta.txt", ["beta.txt"]),
    ("printf 'alpha\\n' > alpha.txt", ["alpha.txt", "beta.txt"]),
    ("python - <<'OTHER'\nfrom pathlib import Path\nPath('alpha.txt').write_text('alpha\\n')\nOTHER\n", ["alpha.txt", "beta.txt"]),
])
def test_heredoc_edits_exclude_reads_but_keep_other_writes(tail, expected):
    command = "python - <<'PY'\nfrom pathlib import Path\np = Path('beta.txt')\np.write_bytes(b'beta\\n')\nPY\n" + tail
    assert harness.command_edit_paths(command) == expected
    assert harness.command_edit_paths("/bin/bash -lc " + shlex.quote(command)) == expected


@pytest.mark.parametrize("fault", [None, "same_session", "no_reentry", "retained_revision", "early_work", "missing_setup", "no_persisted_work", "missing_body", "empty_policy", "wrong_record", "late_body"])
def test_context_loss_requires_two_real_sessions_and_full_reentry(workspace, fault):
    from taplctl import db
    from taplctl.application import WorkflowApplication
    app = WorkflowApplication(workspace)
    run_id = app.summarize_run("Stored plan", work_type="implementation", workflow_mode="standard")["active_run"]["id"]
    plan = app.apply_plan("PLAN-001", title="README typo", objective="transactoin to transaction", status="Finalized")
    task = app.create_task("TASK-001", "Typo", "PLAN-001", "README", "Fix typo", "Exact bytes")
    stored = app.get_status(full=True)
    persisted = [{"id": item["id"], "stable_id": item["stable_id"], "kind": item["kind"], "body": item["body"],
                  "fields": {key: item[key] for _, key in db.markdown_body_fields(item["kind"])}}
                 for item in stored["plans"] + stored["tasks"]]
    app.record_approval(decision="approved", prompt="Second session approval", source="explicit_user")
    app.start_task("TASK-001")
    app.settle_task("TASK-001", status="Completed", verification="Exact bytes", result="Fixed")
    app.finish_run("Done", expected_run_id=run_id, memory_review={"decision": "skip", "reason": "Test fixture"})
    app.finish_archive("stored")
    seed = {"run_id": run_id, "setup_unchanged": True, "setup_archives": 0, "setup_items": persisted}
    setup = [{"type": "thread.started", "thread_id": "first"}, call("tapl_get_next"),
             call("tapl_apply_plan", result=plan), call("tapl_create_task", result=task), {"type": "turn.completed"}]
    events = [{"type": "thread.started", "thread_id": "second"}, call("tapl_get_next"),
              call("tapl_get_status", {"full": True}, result=stored),
              {"type": "item.started", "item": {"type": "mcp_tool_call", "tool": "tapl_start_task"}},
              {"type": "turn.completed"}]
    if fault == "same_session":
        events[0]["thread_id"] = "first"
    elif fault == "no_reentry":
        del events[1]
    elif fault == "retained_revision":
        events[1]["item"]["arguments"] = {"known_policy_revision": "previous"}
    elif fault == "early_work":
        events.insert(1, {"type": "item.started", "item": {"type": "command_execution", "command": "cat README.md"}})
    elif fault == "no_persisted_work":
        del setup[3]
    elif fault == "missing_body":
        del events[2]
    elif fault == "empty_policy":
        events[1]["item"]["result"] = {"structured_content": {"ok": True}}
    elif fault == "wrong_record":
        events[2]["item"]["result"]["structured_content"]["tasks"][0]["id"] = -1
    elif fault == "late_body":
        events[2], events[3] = events[3], events[2]
    if fault != "missing_setup":
        save(workspace / "setup-events.jsonl", setup)
    save(workspace / "events.jsonl", events)
    (workspace / "scenario.json").write_text(json.dumps(seed))
    export_db(workspace)
    result = harness.audit_records(workspace, "context_loss")
    assert result["passed"] is (fault is None), result["errors"]


def test_root_metrics_deduplicate_usage_exclude_children_and_separate_cached_input(tmp_path):
    def usage(total, last, cached=50):
        return row("event_msg", type="token_count", info={
            "total_token_usage": {"input_tokens": total, "cached_input_tokens": cached, "output_tokens": 10},
            "last_token_usage": {"input_tokens": last}}, rate_limits={"unrelated_private_field": "must not be returned"})
    rows = [row("session_meta", id="root"), usage(100, 100), usage(100, 100), usage(250, 150, 120),
            row("response_item", type="custom_tool_call", name="exec", call_id="discovery", input="text(ALL_TOOLS)"),
            row("response_item", type="custom_tool_call_output", call_id="discovery", output="한글"),
            row("response_item", type="function_call", name="exec_command", call_id="shell", arguments="{}")]
    save(tmp_path / "root.jsonl", rows)
    save(tmp_path / "child.jsonl", [row("session_meta", id="child", parent_thread_id="root"), usage(99999, 99999)])
    metrics = harness.rollout_metrics(tmp_path)
    assert metrics["model_requests"] == 2
    assert metrics["input_tokens"] == 250 and metrics["cached_input_tokens"] == 120
    assert metrics["max_single_input_tokens"] == 150
    assert metrics["exec_calls"] == 2 and metrics["tool_discovery_calls"] == 1
    assert metrics["tool_discovery_output_bytes"] == len("한글".encode())
    assert "unrelated_private_field" not in json.dumps(metrics)


def test_unknown_cached_input_metrics_are_null(tmp_path):
    save(tmp_path / "root.jsonl", [row("session_meta", id="root"), row("event_msg", type="token_count",
         info={"total_token_usage": {"input_tokens": 100}, "last_token_usage": {"input_tokens": 100}})])
    assert harness.rollout_metrics(tmp_path)["cached_input_tokens"] is None


def test_usage_initialization_and_metadata_enrichment_are_not_model_requests(tmp_path):
    def usage(values):
        return row("event_msg", type="token_count", info={"total_token_usage": values})
    save(tmp_path / "root.jsonl", [row("session_meta", id="root"), usage({"input_tokens": 0, "output_tokens": 0}),
         usage({"input_tokens": 100, "output_tokens": 10}),
         usage({"input_tokens": 100, "output_tokens": 10, "cached_input_tokens": 50}),
         usage({"input_tokens": 200, "output_tokens": 20})])
    metrics = harness.rollout_metrics(tmp_path)
    assert metrics["model_requests"] == 2
    assert metrics["cached_input_tokens"] is None


@pytest.mark.parametrize("command,valid", [
    ("python - <<'PY'\nfrom pathlib import Path\ndata = Path('README.md').read_bytes()\nexpected = b'# Example\\n\\nAn atomic transaction.\\n'\nassert data == expected\nPY", True),
    ("assert b'transaction' in Path('README.md').read_bytes()", False),
    ("echo \"assert Path('README.md').read_bytes() == b'transaction'\"", False),
    ("python - <<'PY'\nprint(\"assert Path('README.md').read_bytes() == b'# Example\\\\n\\\\nAn atomic transaction.\\\\n'\")\nPY", False),
    ("python - <<'PY'\ndef unused():\n    assert Path('README.md').read_bytes() == b'# Example\\n\\nAn atomic transaction.\\n'\nPY", False),
    ('''echo python -c "assert Path('README.md').read_bytes() == b'# Example\\n\\nAn atomic transaction.\\n'"''', False),
    ('''python -c "import pathlib; assert pathlib.Path('README.md').read_bytes() == b'# Example\\n\\nAn atomic transaction.\\n'"''', True),
])
def test_exact_bytes_audit_rejects_printed_or_weaker_claims(command, valid):
    assert harness.exact_byte_verification(command) is valid
