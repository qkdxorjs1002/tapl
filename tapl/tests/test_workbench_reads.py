"""Exact RUN navigation and literal, source-aware record library contracts."""
from __future__ import annotations

import asyncio
from contextlib import closing
from pathlib import Path
import sqlite3
from unittest import mock

import pytest
from mcp import Client

from taplctl import db, history, identity, mcp_server, recall, viewer
from taplctl.application import WorkflowApplication


def seed(path: Path, label: str, count: int = 61):
    with closing(db.connect(path, session_id="owner")) as conn:
        run = db.ensure_active_run(conn, request_summary=label, work_type="analysis", workflow_mode="fast")
        run_id = run["id"]
        for index in range(count):
            db.upsert_item(conn, kind="finding", stable_id=f"FIND-{index:03}", title=f"{label} common {index}",
                           body="literal 50%_\\ marker" if index == 0 else "body match", custom_fields={"original": True})
        db.update_active_run_summary(conn, result_summary="Verified original source")
        memories = recall.finish_memories(conn, run_id=run_id, candidates=[
            {"slot": 1, "cue": ["original source", "verified result", "exact run"], "note": "Check the original RUN.", "source_run_id": run_id},
            {"slot": 2, "cue": ["original item", "record source", "exact item"], "note": "Check the original item.", "source_run_id": run_id, "source_item_id": 1},
        ])
        archive = db.archive_active_run(conn, slug="original", memory_review_enabled=False)
        active = db.ensure_active_run(conn, request_summary="Current replacement", work_type="answer", workflow_mode="fast")
        return run_id, active["id"], archive["id"], [entry["memory_id"] for entry in memories["captures"]]


@pytest.fixture
def library(tmp_path):
    local = db.default_db_path(tmp_path)
    first = seed(local, "local")
    peer = tmp_path / ".tapl/tapl-peer.db"
    second = seed(peer, "peer", 3)
    return tmp_path, local, peer, first, second, history.HistoryReader(tmp_path, session_id="owner")


def fingerprint(paths):
    return {path: (path.stat().st_mtime_ns, path.read_bytes()) for path in paths}


def test_exact_archived_and_empty_run_do_not_follow_replacement_owner(library):
    _, local, peer, first, second, reader = library
    original = reader.get_run(first[0])
    assert original["run"]["id"] == first[0] != first[1]
    assert original["run"]["status"] == "archived" and original["readonly"] is True
    assert original["run"]["session_id"] == "owner"
    assert original["run"]["work_type"] == "analysis" and "difficulty" not in original["run"]
    assert original["run"]["source_db"] == local.name
    assert len(original["findings"]) == 61
    assert all(row["run_id"] == first[0] and row["source_db"] == local.name for row in original["findings"])
    assert original["findings"][0]["custom_fields"] == {"original": True}
    empty = reader.get_run(first[1])
    assert empty["readonly"] is False and empty["findings"] == [] and empty["tasks"] == []
    assert set(empty["task_counts"].values()) == {0}
    assert reader.get_run(second[1], source_db=peer.name)["readonly"] is True
    assert history.HistoryReader(reader.workspace_root, session_id="other").get_run(first[1])["readonly"] is True


def test_filter_scope_before_pagination_and_exact_totals(library):
    _, local, peer, first, second, reader = library
    # No hybrid-search cap can hide a match in a requested RUN or later page.
    with mock.patch.object(history.embeddings, "search", side_effect=AssertionError("hybrid search must not run")):
        scoped = reader.list_records("common", scope="run", run_id=first[0], limit=2, offset=59)
        assert scoped["total"] == 61 and len(scoped["records"]) == 2
        assert scoped["runs"][0]["record_count"] == 61
        assert all(row["run_id"] == first[0] and row["source_db"] == local.name for row in scoped["records"])
        assert reader.list_records("common", scope="run", run_id=second[0], source_db=peer.name)["total"] == 3
        assert reader.list_records("common", source_db=peer.name)["total"] == 64
        assert reader.list_records("FIND-060", scope="run", run_id=first[0])["total"] == 1
    assert reader.list_records("50%_\\")["total"] == 2
    assert reader.list_records("50%_X")["total"] == 0
    assert reader.list_records("COMMON")["total"] == 64
    assert reader.list_records(scope="run", run_id=first[1])["total"] == 0
    assert reader.list_records(scope="run", run_id=first[1])["runs"][0]["record_count"] == 0


def test_federated_pages_and_composite_ids_remain_stable(library):
    _, local, peer, first, second, reader = library
    pages = [reader.list_records(limit=7, offset=offset) for offset in range(0, 70, 7)]
    rows = [row for page in pages for row in page["records"]]
    assert len(rows) == len({(row["source_db"], row["id"]) for row in rows}) == 64
    assert {row["source_db"] for row in rows if row["id"] == 1} == {local.name, peer.name}
    assert all(page["total"] == 64 for page in pages)
    assert rows[:7] == reader.list_records(limit=7)["records"]
    assert {(run["source_db"], run["id"], run["record_count"]) for run in pages[0]["runs"]} == {
        (local.name, first[0], 61), (local.name, first[1], 0), (peer.name, second[0], 3), (peer.name, second[1], 0),
    }


def test_identical_run_and_item_ids_in_two_sources_remain_distinct(tmp_path):
    local = db.default_db_path(tmp_path)
    original, *_ = seed(local, "local", 1)
    peer = tmp_path / ".tapl/tapl-peer.db"
    peer.write_bytes(local.read_bytes())
    with sqlite3.connect(peer) as conn:
        conn.execute("UPDATE workflow_runs SET request_summary='Peer snapshot' WHERE id=?", (original,))
        conn.execute("UPDATE items SET title='Peer record'")
    reader = history.HistoryReader(tmp_path)
    assert reader.get_run(original)["run"]["request_summary"] == "local"
    assert reader.get_run(original, source_db=peer.name)["run"]["request_summary"] == "Peer snapshot"
    assert reader.list_records(scope="run", run_id=original, source_db=peer.name)["records"][0]["title"] == "Peer record"
    groups = reader.list_records()["runs"]
    assert {(run["source_db"], run["record_count"]) for run in groups if run["id"] == original} == {(local.name, 1), (peer.name, 1)}


def test_reject_invalid_bounds_selectors_and_report_partial_sources(library):
    root, _, peer, first, _, reader = library
    broken = root / ".tapl/tapl-broken.db"
    broken.write_bytes(b"not sqlite")
    result = reader.list_records()
    assert result["total"] == 64
    assert [error["source_db"] for error in result["source_errors"]] == [broken.name]
    assert reader.get_run(first[0])["source_errors"][0]["source_db"] == broken.name
    link = root / ".tapl/tapl-link.db"
    link.symlink_to(peer)
    for selector in (str(peer), "../tapl-peer.db", "./tapl-peer.db", link.name, "missing.db", broken.name):
        with pytest.raises(history.HistoryError):
            reader.get_run(first[0], source_db=selector)
        with pytest.raises(history.HistoryError):
            reader.list_records(scope="run", run_id=first[0], source_db=selector)
    for kwargs in ({"scope": "unknown"}, {"scope": "run"}, {"offset": -1}, {"offset": True},
                   {"offset": 1000001}, {"limit": 0}, {"limit": 51}, {"query": "a" * 501}):
        with pytest.raises(history.HistoryError):
            reader.list_records(**kwargs)
    with pytest.raises(history.HistoryError, match="run not found"):
        reader.list_records(scope="run", run_id="missing")


def test_reads_leave_bytes_owner_and_installation_unchanged(tmp_path):
    peer = tmp_path / ".tapl/tapl-peer.db"
    original, active, _, _ = seed(peer, "foreign", 1)
    assert identity.installation_id(create=False) is None
    before = fingerprint([peer])
    app = WorkflowApplication(tmp_path, session_id="unrelated")
    with mock.patch.object(db, "default_db_path", side_effect=AssertionError("identity/migration")), \
         mock.patch.object(db, "connect", side_effect=AssertionError("writable connection")):
        assert app.get_run(original, source_db=peer.name)["readonly"] is True
        assert app.list_records()["total"] == 1
    assert fingerprint([peer]) == before and identity.installation_id(create=False) is None
    with sqlite3.connect(peer) as conn:
        assert conn.execute("SELECT session_id FROM workflow_runs WHERE id=?", (active,)).fetchone()[0] == "owner"


def test_browser_navigation_refresh_and_memory_original_context(library):
    root, local, peer, first, second, _ = library
    app = viewer.ViewerApplication(default_workspace=root)
    before = fingerprint([local, peer])
    def view(command, **kwargs):
        result = app.handle_message({"command": command, "sessionId": "owner", **kwargs})
        assert result["type"] == "view:update", result
        return result["view"]
    assert view("openRun", runId=first[0])["snapshot"]["run"]["id"] == first[0]
    assert view("refresh", viewType="run", runId=second[0], source_db=peer.name)["snapshot"]["run"]["id"] == second[0]
    records = view("records", scope="run", runId=first[0], query="common", offset=59, limit=2)
    assert records["context"]["run"]["id"] == first[0] and records["total"] == 61
    assert view("refresh", viewType="records", scope="run", runId=first[0], query="common", offset=59, limit=2)["records"] == records["records"]
    item = view("openSearchResult", itemId=1, source_db=peer.name)
    assert item["result"]["run_id"] == item["context"]["run"]["id"] == second[0]
    archive = view("openArchive", archiveId=second[2], source_db=peer.name)
    assert archive["context"]["run"]["id"] == second[0]
    for memory_id in second[3]:
        source = view("openMemorySource", memoryId=memory_id, source_db=peer.name)
        assert source["type"] in ("searchItem", "memorySource")
        assert source["context"]["run"]["id"] == second[0]
        assert source["context"]["readonly"] is True
    assert fingerprint([local, peer]) == before


def test_mcp_read_contracts_do_not_create_identity(tmp_path):
    peer = tmp_path / ".tapl/tapl-peer.db"
    original, *_ = seed(peer, "foreign", 1)
    before = fingerprint([peer])
    server = mcp_server.create_server(workspace_root=tmp_path)
    assert identity.installation_id(create=False) is None
    async def exercise():
        async with Client(server) as client:
            exact = await client.call_tool("tapl_get_run", {"run_id": original, "source_db": peer.name, "session_id": "other"})
            assert not exact.is_error and exact.structured_content["run"]["id"] == original
            result = await client.call_tool("tapl_list_records", {"scope": "run", "run_id": original, "source_db": peer.name})
            assert not result.is_error and result.structured_content["total"] == 1
            bad = await client.call_tool("tapl_list_records", {"limit": 51})
            assert bad.is_error
    asyncio.run(exercise())
    assert identity.installation_id(create=False) is None and fingerprint([peer]) == before


@pytest.mark.parametrize("query", ["--query", "--scope", "--offset", "--limit", "--run-id"])
def test_browser_record_queries_that_look_like_flags_are_literal(library, query):
    root, local, _, first, _, _ = library
    with sqlite3.connect(local) as conn:
        conn.execute("UPDATE items SET body=? WHERE id=1", (query,))
    conn.close()
    # Both workspace federation and the explicit standalone-db path use pairs.
    bare = root / "explicit.db"
    bare.write_bytes(local.read_bytes())
    for app in (viewer.ViewerApplication(default_workspace=root), viewer.ViewerApplication(default_db=bare)):
        payload = app.handle_message({"command": "records", "query": query, "scope": "run", "runId": first[0], "offset": 0, "limit": 1})
        assert payload["type"] == "view:update", payload
        result = payload["view"]
        assert result["query"] == query and result["scope"] == "run"
        assert result["total"] == 1 and result["records"][0]["id"] == 1


def test_fresh_legacy_only_history_reads_without_adoption_or_identity(tmp_path):
    legacy = tmp_path / ".tapl/tapl.db"
    original, _, archive, memories = seed(legacy, "legacy", 1)
    before = fingerprint([legacy])
    assert identity.installation_id(create=False) is None
    app = WorkflowApplication(tmp_path)
    with mock.patch.object(db, "default_db_path", side_effect=AssertionError("must not adopt legacy")):
        assert app.get_item(1)["source_db"] == legacy.name
        assert app.get_archive(archive)["archive"]["run_id"] == original
        assert app.get_memory(memories[0])["memory"]["source"]["run_id"] == original
        assert app.get_run(original)["readonly"] is True
        assert app.list_records(scope="run", run_id=original)["total"] == 1
    assert identity.installation_id(create=False) is None
    assert db.discover_db_paths(tmp_path) == [legacy] and fingerprint([legacy]) == before


@pytest.mark.parametrize("failure", [viewer.ViewerError("unsupported run read"), AssertionError("old command seam")])
def test_optional_browser_context_failure_preserves_details_without_current_status(library, failure):
    root, _, peer, _, second, _ = library
    calls = []
    def runner(_path, args):
        calls.append(args[0])
        if args[0] == "run":
            raise failure
        if args[0] == "item":
            return {"item": {"id": 1, "run_id": second[0], "kind": "task", "stable_id": "TASK-001", "title": "Original", "source_db": peer.name}}
        if args[0] == "archive":
            return {"archive": {"id": "archive", "run_id": second[0], "source_db": peer.name}, "items": [], "events": []}
        if args[0] == "memory":
            return {"memory": {"source_available": True, "source_db": peer.name, "source_record": {"kind": "run", "run": {"id": second[0]}}}}
        raise AssertionError("must not fall back to another active RUN")
    app = viewer.ViewerApplication(default_workspace=root, json_runner=runner)
    for command, selector in (("openSearchResult", {"itemId": 1}), ("openArchive", {"archiveId": "archive"}),
                              ("openMemorySource", {"memoryId": "memory"})):
        payload = app.handle_message({"command": command, "source_db": peer.name, **selector})
        assert payload["type"] == "view:update", payload
        assert "context" not in payload["view"]
    assert "status" not in calls


def test_legacy_browser_task_enrichment_requires_matching_source(library):
    root, local, peer, *_ = library
    def runner(_path, args):
        if args[0] == "item":
            return {"item": {"id": 1, "kind": "task", "stable_id": "TASK-001", "title": "Foreign", "source_db": peer.name}}
        return {"tasks": [{"id": 1, "source_db": local.name, "active_execution": {"execution_id": "wrong-source"}}]}
    app = viewer.ViewerApplication(default_workspace=root, json_runner=runner)
    view = app.handle_message({"command": "openSearchResult", "itemId": 1, "source_db": peer.name})["view"]
    assert view["detail"]["source_db"] == peer.name and "active_execution" not in view["detail"]
