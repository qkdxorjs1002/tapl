"""Viewer and agent transports share stored owner keys, never authority."""

import asyncio
from contextlib import closing
import os
from pathlib import Path
import sqlite3
import sys
from unittest import mock

from mcp import Client
from mcp.client.stdio import StdioServerParameters, stdio_client
import pytest

from taplctl import db, identity, mcp_server, viewer
from taplctl.application import WorkflowApplication


@pytest.fixture
def mixed(tmp_path):
    local = db.default_db_path(tmp_path)
    owners = ("native", "claude-code:native", "")
    ids = {}
    for owner in owners:
        app = WorkflowApplication(tmp_path, session_id=owner)
        ids[owner] = app.summarize_run(f"Board {owner}")["active_run"]["id"]
        app.apply_plan("PLAN-001", title=f"Plan {owner}", objective="Verify mixed-owner selection")
    claude = WorkflowApplication(tmp_path, session_id=owners[1])
    with closing(db.connect(local, session_id=owners[1])) as conn:
        for _ in range(18):
            db.record_event(conn, event_type="old_run_event")
    archived = ids[owners[1]]
    claude.finish_archive("original")
    ids[owners[1]] = claude.summarize_run("Claude successor")["active_run"]["id"]
    claude.apply_plan("PLAN-002", title="Successor plan")
    peer = local.with_name("tapl-peer.db")
    with closing(sqlite3.connect(local)) as src, closing(sqlite3.connect(peer)) as dst:
        src.backup(dst)
        dst.execute("UPDATE items SET title = 'Peer ' || title")
        dst.commit()
    return local, peer, ids, archived


def test_viewer_stdio_negotiates_profile_reads_mixed_history_and_confirms_discard(tmp_path, mixed):
    local, peer, ids, archived = mixed
    params = StdioServerParameters(command=sys.executable, args=["-m", "taplctl.mcp_server"], cwd=tmp_path,
                                   env={"TAPL_MCP_MODE": "viewer", "TAPL_CLIENT": "claude-code",
                                        "HOME": str(Path.home()), "USERPROFILE": str(Path.home()),
                                        "CODEX_HOME": os.environ["CODEX_HOME"]})
    peer_before = peer.read_bytes()

    async def exercise():
        async with Client(stdio_client(params)) as client:
            async def ok(name, **args):
                result = await client.call_tool(name, args)
                assert not result.is_error, result.content
                return result.structured_content

            tools = {tool.name: tool for tool in (await client.list_tools()).tools}
            status_tool, discard_tool = "tapl_viewer_get_status", "tapl_viewer_discard_run"
            assert set(tools) == {status_tool, discard_tool, "tapl_get_run", "tapl_get_item",
                                  "tapl_list_records", "tapl_search_history", "tapl_get_archive",
                                  "tapl_list_archives", "tapl_recall", "tapl_get_memory",
                                  "tapl_get_settings", "tapl_save_settings"}
            assert tools[status_tool].annotations.read_only_hint
            assert tools[discard_tool].annotations.destructive_hint
            assert set(tools[discard_tool].input_schema["required"]) == {
                "source_db", "run_id", "target_session_id", "confirmed", "confirmation_run_id"}
            assert (await client.call_tool("tapl_discard_run", {})).is_error
            overview = await ok(status_tool)
            assert overview["active_run"]["source_db"] == local.name
            assert {(r["source_db"], r["session_id"], r["id"]) for r in overview["active_runs"]} == {
                (path.name, owner, run_id) for path in (peer, local) for owner, run_id in ids.items()}
            for owner, run_id in ids.items():
                for path in (local, peer):
                    status = await ok(status_tool, source_db=path.name, run_id=run_id)
                    assert (status["active_run"]["id"], status["session_id"]) == (run_id, owner)
                    assert status["active_run"]["writable"] is (path == local)
                    assert status["plans"][0]["title"].startswith("Peer ") is (path == peer)
                    assert "body" not in status["plans"][0]
                    snapshot = await ok("tapl_get_run", source_db=path.name, run_id=run_id)
                    assert snapshot["readonly"] is (path == peer)
            board = await ok(status_tool, run_id=archived, source_db=local.name, full=True,
                             include_events=True, events_limit=16)
            assert board["session_id"] == "claude-code:native"
            assert board["active_run"]["id"] == archived and board["active_run"]["status"] == "archived"
            assert board["active_run"]["writable"] is False
            assert board["plans"][0]["title"] == "Plan claude-code:native" and board["plans"][0]["body"]
            assert len(board["recent_events"]) == 16
            assert {e["run_id"] for e in board["recent_events"]} == {archived}
            assert (await ok(status_tool, run_id=archived, source_db=local.name,
                             include_events=True, events_limit=0))["recent_events"] == []
            for bad in ({"run_id": "absent"}, {"source_db": "../" + local.name},
                        {"source_db": "missing.db"}, {"run_id": archived, "events_limit": 101}):
                assert (await client.call_tool(status_tool, bad)).is_error
            assert (await ok("tapl_get_run", source_db=local.name, run_id=archived))["readonly"]
            item_id = board["plans"][0]["id"]
            assert (await ok("tapl_get_item", source_db=peer.name, item_id=item_id))["item"]["title"].startswith("Peer")
            assert (await ok("tapl_list_records", scope="run", source_db=local.name, run_id=archived))["total"] == 1
            assert (await ok("tapl_search_history", query="Successor plan"))["results"]
            assert (await ok("tapl_list_archives"))["archives"]
            assert (await ok("tapl_get_archive", archive_id="original", source_db=peer.name))["archive"]["run_id"] == archived
            assert (await ok("tapl_recall"))["memories"] == []
            assert (await ok("tapl_get_memory", memory_id="absent", source_db=local.name))["memory"] is None
            with closing(db.connect_readonly(local)) as conn:
                assert conn.execute("SELECT count(*) FROM events WHERE event_type='run_references_updated'").fetchone()[0] == 0

            run_id = ids["claude-code:native"]
            target = dict(run_id=run_id, source_db=local.name, target_session_id="claude-code:native",
                          confirmed=True, confirmation_run_id=run_id)
            for change in ({"target_session_id": "native"}, {"source_db": peer.name}, {"confirmed": 1},
                           {"confirmed": False}, {"confirmation_run_id": run_id[:-1]},
                           {"run_id": archived, "confirmation_run_id": archived}):
                assert (await client.call_tool(discard_tool, {**target, **change})).is_error
            for missing in target:
                assert (await client.call_tool(discard_tool, {k: v for k, v in target.items() if k != missing})).is_error
            assert (await ok(status_tool, run_id=run_id, source_db=local.name))["active_run"]["status"] == "active"
            assert (await ok(discard_tool, **target))["archived_run_ids"] == [run_id]
            assert (await client.call_tool(discard_tool, target)).is_error
            assert (await ok(status_tool, run_id=run_id, source_db=local.name))["active_run"]["status"] == "archived"
            legacy_id = ids[""]
            await ok(discard_tool, **{**target, "target_session_id": "", "confirmation_run_id": legacy_id, "run_id": legacy_id})
            remaining = (await ok(status_tool))["active_runs"]
            assert [(r["session_id"], r["id"]) for r in remaining if r["source_db"] == local.name] == [("native", ids["native"])]

    asyncio.run(exercise())
    assert peer.read_bytes() == peer_before


def test_viewer_settings_without_install_or_agent_identity(tmp_path):
    with mock.patch.object(mcp_server.tapl_install, "auto_install_if_needed") as install, \
         mock.patch.object(mcp_server.auto_reindex, "schedule", return_value={"state": "scheduled"}) as schedule:
        server = mcp_server.create_server(workspace_root=tmp_path, client="claude-code", viewer_mode=True, refresh_install=True)
        install.assert_not_called()
        schedule.assert_not_called()

        async def exercise():
            async with Client(server) as client:
                empty = (await client.call_tool("tapl_viewer_get_status", {})).structured_content
                assert empty["active_run"] is None and empty["active_runs"] == []
                settings = (await client.call_tool("tapl_get_settings", {})).structured_content["settings"]
                args = {"values": {"viewer.language": "ko"}, "expected_revision": settings["revision"]}
                saved = (await client.call_tool("tapl_save_settings", args)).structured_content
                assert saved["changed"] and saved["reindex"] == {"state": "scheduled"}
                assert (await client.call_tool("tapl_save_settings", args)).structured_content["code"] == "settings_conflict"
        asyncio.run(exercise())
        schedule.assert_called_once()
    assert db.discover_db_paths(tmp_path) == [] and identity.installation_id(create=False) is None


def test_native_select_and_refresh_use_exact_source_and_run(mixed, tmp_path):
    local, peer, ids, archived = mixed
    app = viewer.ViewerApplication(default_workspace=tmp_path)
    for source in (peer, local):
        pointer = {"sessionId": "native", "runId": archived, "source_db": source.name}
        for command in ({"command": "selectRun"}, {"command": "refresh", "viewType": "overview"},
                        {"command": "refresh", "viewType": "debug"}):
            status = app.handle_message({**command, **pointer})["view"]["status"]
            assert status["session_id"] == "claude-code:native"
            assert status["active_run"]["id"] == archived and status["active_run"]["writable"] is False
            assert status["plans"][0]["title"].startswith("Peer") is (source == peer)
        assert app.handle_message({"command": "selectRun", **pointer, "runId": "missing"})["type"] == "error"
    current = app.handle_message({"command": "selectRun", "sessionId": "claude-code:native"})["view"]["status"]
    assert current["active_run"]["id"] == ids["claude-code:native"]
