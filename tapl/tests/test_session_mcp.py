"""Exercise session routing at the public application, MCP, and hook boundaries."""

from __future__ import annotations

import asyncio
import io
import json
from contextlib import closing
from pathlib import Path

import pytest
from mcp import Client

from taplctl import db, hook_cli, hooks, mcp_server, sessions
from taplctl.application import WorkflowApplication, WorkflowApplicationError


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    (tmp_path / ".git").mkdir()
    db.initialize_workspace(tmp_path)
    (tmp_path / ".tapl/config.toml").write_text("[subagents]\nenabled = false\n", encoding="utf-8")
    return tmp_path


def test_all_mcp_tools_can_route_a_session(workspace: Path) -> None:
    tools = asyncio.run(mcp_server.create_server(workspace_root=workspace).list_tools())
    assert tools
    for tool in tools:
        assert "session_id" in tool.input_schema["properties"], tool.name
        if tool.name == "tapl_discard_run":
            assert "session_id" in tool.input_schema.get("required", []), tool.name
        else:
            assert "session_id" not in tool.input_schema.get("required", []), tool.name


def test_one_mcp_server_routes_concurrent_sessions_and_write_recommendations(workspace: Path) -> None:
    server = mcp_server.create_server(workspace_root=workspace)

    async def exercise() -> None:
        async with Client(server) as client:
            async def call(name: str, owner: str, **args):
                response = await client.call_tool(name, {"session_id": owner, **args})
                assert not response.is_error, response.content
                return response.structured_content

            receipts = await asyncio.gather(*[
                call("tapl_summarize_run", owner, summary=f"Session {owner}", work_type="implementation", workflow_mode="standard")
                for owner in ("a", "b")
            ])
            ids = {owner: receipt["active_run"]["id"] for owner, receipt in zip(("a", "b"), receipts)}
            assert len(set(ids.values())) == 2
            for owner in ("a", "b"):
                await call("tapl_apply_plan", owner, plan_id="PLAN-001", title=f"Plan {owner}")
                receipt = await call("tapl_create_task", owner, task_id="TASK-001", title=f"Task {owner}",
                                     spec_id="PLAN-001", goal="Goal", action="Action", verification="Check")
                assert receipt["session_id"] == owner
                next_payload = await call("tapl_get_next", owner)
                assert receipt["recommendations"] == next_payload["recommendations"]
                assert next_payload["state_summary"]["active_run"]["id"] == ids[owner]
            approved = await call("tapl_approve_execution", "a", prompt="Execute A")
            assert approved["recommendations"] == (await call("tapl_get_next", "a"))["recommendations"]
            assert (await call("tapl_get_next", "b"))["state_summary"]["execution_approval"]["state"] == "missing"
            for owner in ("b", "a", "b"):
                state = await call("tapl_get_status", owner, full=True)
                assert state["active_run"]["id"] == ids[owner]
                assert state["plans"][0]["title"] == f"Plan {owner}"
                assert state["tasks"][0]["title"] == f"Task {owner}"
        # A new transport session resumes by explicit conversation identity.
        async with Client(server) as reconnected:
            state = await reconnected.call_tool("tapl_get_status", {"session_id": "a"})
            assert state.structured_content["active_run"]["id"] == ids["a"]

    asyncio.run(exercise())


def test_unidentified_mcp_calls_cannot_approve_finish_or_archive_named_run(workspace: Path) -> None:
    app = WorkflowApplication(workspace, session_id="a")
    run_id = app.summarize_run("Owned request")["active_run"]["id"]
    server = mcp_server.create_server(workspace_root=workspace)

    async def exercise() -> None:
        async with Client(server) as client:
            initial = await client.call_tool("tapl_get_status", {})
            assert initial.structured_content["active_run"] is None
            for name, args in (
                ("tapl_approve_execution", {"prompt": "Approve the active request"}),
                ("tapl_finish_run", {"result": "Done", "expected_run_id": run_id}),
                ("tapl_finish_archive", {"slug": "owned"}),
            ):
                result = await client.call_tool(name, args)
                assert result.is_error
            state = await client.call_tool("tapl_get_status", {"session_id": "a"})
            assert state.structured_content["active_run"]["id"] == run_id

    asyncio.run(exercise())
    with closing(db.connect(workspace / ".tapl/tapl.db", session_id="a")) as conn:
        assert db.active_run(conn)["result_summary"] == ""
        assert db.latest_approval(conn) is None
        assert db.list_archives(conn) == []


def test_application_finish_archive_and_task_settlement_stay_with_owner(workspace: Path) -> None:
    a = WorkflowApplication(workspace, session_id="a")
    b = WorkflowApplication(workspace, session_id="b")
    ids = {}
    for owner, app in (("a", a), ("b", b)):
        ids[owner] = app.summarize_run(owner)["active_run"]["id"]
        app.apply_plan("PLAN-001", title=owner)
        app.create_task("TASK-001", owner, "PLAN-001", "Goal", "Act", "Verify")
    a.settle_task("TASK-001", status="Completed", result="A done", verification="Checked")
    assert b.get_status()["tasks"][0]["status"] == "Pending"
    with pytest.raises(WorkflowApplicationError, match="stale_run"):
        b.finish_run("Wrong request", expected_run_id=ids["a"])
    a.finish_run("A done", expected_run_id=ids["a"], memory_review={"decision": "skip", "reason": "Synthetic fixture"})
    a.finish_archive("a-completed")
    assert a.get_status()["active_run"] is None
    assert b.get_status()["active_run"]["id"] == ids["b"]
    assert b.get_status()["tasks"][0]["status"] == "Pending"


def test_shared_application_resolves_context_per_call_and_restores_after_error(workspace: Path) -> None:
    app = WorkflowApplication(workspace)

    async def call(owner: str) -> str:
        with sessions.session_scope(owner):
            await asyncio.sleep(0)
            initial = await asyncio.to_thread(app.summarize_run, owner)
            await asyncio.sleep(0)
            assert (await asyncio.to_thread(app.get_status))["active_run"]["id"] == initial["active_run"]["id"]
            with pytest.raises(WorkflowApplicationError):
                await asyncio.to_thread(app.finish_run, "Done", expected_run_id="foreign-run")
            assert (await asyncio.to_thread(app.get_context))["session_id"] == owner
            return initial["active_run"]["id"]

    async def exercise() -> list[str]:
        return await asyncio.gather(call("a"), call("b"))

    assert len(set(asyncio.run(exercise()))) == 2
    assert sessions.current_session_id() == ""
    assert app.get_status()["active_run"] is None


def test_hook_payload_owns_prompt_stop_and_events_without_affecting_other_session(workspace: Path) -> None:
    path = workspace / ".tapl/tapl.db"
    with closing(db.connect(path)) as conn:
        for owner in ("a", "b"):
            result = hooks.handle_event(conn, event="UserPromptSubmit", mode="observe", tool=None,
                                        payload={"session_id": owner, "prompt": owner})
            assert result["context"]["session_id"] == owner
            assert db.active_run(conn) is None  # Temporary payload binding was restored.
    a = WorkflowApplication(workspace, session_id="a")
    b = WorkflowApplication(workspace, session_id="b")
    a_id = a.get_status()["active_run"]["id"]
    b_id = b.get_status()["active_run"]["id"]
    a.summarize_run("Answer A", work_type="answer", workflow_mode="fast")
    a.finish_run("A done", expected_run_id=a_id, memory_review={"decision": "skip", "reason": "Synthetic fixture"})
    b.apply_plan("PLAN-001", title="B plan")
    b.create_task("TASK-001", "B unfinished", "PLAN-001", "Goal", "Act", "Check")
    with closing(db.connect(path)) as conn:
        stopped_a = hooks.handle_event(conn, event="Stop", mode="enforce", tool=None, payload={"session_id": "a"})
        assert not stopped_a["block"]
        assert stopped_a["archive"]["run_id"] == a_id
        stopped_b = hooks.handle_event(conn, event="Stop", mode="enforce", tool=None, payload={"session_id": "b"})
        assert stopped_b["block"]
        assert "archive" not in stopped_b
        missing_identity = hooks.handle_event(conn, event="Stop", mode="enforce", tool=None, payload={})
        assert "archive" not in missing_identity
        assert db.active_run(conn) is None
    assert b.get_status()["active_run"]["id"] == b_id
    with closing(db.connect(path, session_id="b")) as conn:
        assert all(row["session_id"] == "b" for row in db.status_payload(conn)["recent_events"])
        with pytest.raises(ValueError):
            hooks.handle_event(conn, event="Stop", mode="enforce", tool=None, payload={"session_id": "a"})
        assert db.active_run(conn)["id"] == b_id


def test_hook_cli_routes_json_payload_session_and_resumes_it(workspace: Path, monkeypatch, capsys) -> None:
    path = workspace / ".tapl/tapl.db"
    ids = {}
    for owner in ("a", "b", "a"):
        monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({
            "cwd": str(workspace), "session_id": owner, "prompt": "Work on this request",
        })))
        assert hook_cli.main(["--event", "UserPromptSubmit", "--db", str(path), "--json"]) == 0
        result = json.loads(capsys.readouterr().out)
        assert result["context"]["session_id"] == owner
        with closing(db.connect(path, session_id=owner)) as conn:
            run_id = db.active_run(conn)["id"]
            if owner in ids:
                assert ids[owner] == run_id
            ids[owner] = run_id
    assert ids["a"] != ids["b"]
    with closing(db.connect(path)) as conn:
        assert db.active_run(conn) is None
        assert db.status_payload(conn)["recent_events"] == []
