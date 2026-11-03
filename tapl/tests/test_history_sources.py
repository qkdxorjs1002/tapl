"""Colliding source ids, partial failures, and read-only federation boundaries."""
from __future__ import annotations

import asyncio
import json
from contextlib import closing
from pathlib import Path
import sqlite3
from unittest import mock

import pytest
from mcp import Client

from taplctl import config, db, embeddings, history, identity, mcp_server, recall
from taplctl.application import WorkflowApplication, WorkflowApplicationError


def seed(path: Path, label: str, *, count: int = 1) -> list[dict]:
    records = []
    with closing(db.connect(path, session_id="owner")) as conn:
        for index in range(count):
            run = db.ensure_active_run(conn, request_summary=f"{label} {index}", work_type="answer", workflow_mode="fast")
            item = db.upsert_plan(conn, plan_id="PLAN-001", title=f"SQLite migration {label} {index}",
                                  status="Finalized", summary="sqlite migration transaction", source="original-source")
            db.update_active_run_summary(conn, result_summary=f"Verified {label} {index}")
            result = recall.finish_memories(conn, run_id=run["id"], candidates=[{
                "slot": 1, "cue": ["sqlite migration", "transaction", "schema"],
                "note": f"Check atomic migration {label} {index}.", "source_run_id": run["id"],
            }], now="2020-01-01T00:00:00+00:00")
            archive = db.archive_active_run(conn, slug=f"same-{index}", memory_review_enabled=False)
            records.append({"run_id": run["id"], "item_id": item["id"], "archive_id": archive["id"],
                            "memory_id": result["captures"][0]["memory_id"]})
    return records


@pytest.fixture
def sources(tmp_path):
    local = db.default_db_path(tmp_path)
    peer = tmp_path / ".tapl/tapl-peer.db"
    first, second = seed(local, "local", count=3), seed(peer, "foreign", count=3)
    settings = config.from_mapping({"search": {"mode": "bm25"}}, path="unused")
    return tmp_path, local, peer, first, second, history.HistoryReader(tmp_path, local_db_path=local, settings=settings)


def fingerprint(path):
    return path.stat().st_mtime_ns, path.read_bytes()


def test_collisions_route_details_to_exact_source_and_preserve_original_source(sources):
    _, local, peer, first, second, reader = sources
    assert first[0]["item_id"] == second[0]["item_id"]
    assert "local" in reader.get_item(first[0]["item_id"])["item"]["title"]
    foreign = reader.get_item(first[0]["item_id"], source_db=peer.name)["item"]
    assert "foreign" in foreign["title"] and foreign["source"] == "original-source"
    assert foreign["source_db"] == peer.name and foreign["run_id"] == second[0]["run_id"]
    assert "local" in reader.get_archive("same-0")["archive"]["request_summary"]
    detail = reader.get_archive("same-0", source_db=peer.name)
    assert detail["archive"]["run_id"] == second[0]["run_id"]
    assert {item["source_db"] for item in detail["items"]} == {peer.name}
    memory = reader.get_memory(second[0]["memory_id"], source_db=peer.name)["memory"]
    assert memory["source"]["source_db"] == memory["source_record"]["run"]["source_db"] == peer.name
    assert memory["source"]["run_id"] == second[0]["run_id"]
    assert reader.get_memory(second[0]["memory_id"])["memory"] is None


def test_selectors_never_follow_paths_symlinks_or_undiscovered_files(sources, tmp_path):
    root, local, peer, *_rest, reader = sources
    link = root / ".tapl/tapl-link.db"
    link.symlink_to(peer)
    unrelated = root / ".tapl/other.db"
    unrelated.write_bytes(peer.read_bytes())
    for selector in (str(peer), "../tapl-peer.db", "./tapl-peer.db", link.name, unrelated.name, "missing.db"):
        with pytest.raises(history.HistoryError):
            reader.get_item(1, source_db=selector)
    assert reader.discover_sources() == sorted([local, peer])
    other_root = tmp_path / "linked-root"
    other_root.mkdir()
    (other_root / ".tapl").symlink_to(root / ".tapl", target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        history.HistoryReader(other_root, settings=reader.settings)


def test_peer_reads_never_migrate_write_or_change_database_bytes(sources):
    _, local, peer, first, second, reader = sources
    before = {path: fingerprint(path) for path in (local, peer)}
    with mock.patch.object(db, "connect", side_effect=AssertionError("writable connection")), \
         mock.patch.object(db, "migrate", side_effect=AssertionError("migration")):
        assert len(reader.search("sqlite migration", limit=4)["results"]) == 4
        assert len(reader.list_archives(limit=4)["archives"]) == 4
        assert reader.recall(limit=50)["total"] == 6
        reader.get_item(second[0]["item_id"], source_db=peer.name)
        reader.get_archive(second[0]["archive_id"], source_db=peer.name)
        reader.get_memory(second[0]["memory_id"], source_db=peer.name)
    assert {path: fingerprint(path) for path in (local, peer)} == before


def test_bad_sources_are_reported_without_hiding_healthy_results(sources):
    root, _, peer, _, _, reader = sources
    broken = root / ".tapl/tapl-corrupt.db"
    broken.write_bytes(b"not a sqlite database")
    old = root / ".tapl/tapl-old.db"
    old.write_bytes(peer.read_bytes())
    with sqlite3.connect(old) as conn:
        conn.execute("UPDATE meta SET value='1' WHERE key='schema_version'")
    before = fingerprint(old)
    for payload in (reader.search("sqlite migration"), reader.list_archives(), reader.recall(limit=50)):
        assert {error["source_db"] for error in payload["source_errors"]} == {broken.name, old.name}
        assert payload.get("results") or payload.get("archives") or payload.get("memories")
    assert fingerprint(old) == before
    for path in (broken, old):
        with pytest.raises(history.HistoryError, match=path.name):
            reader.get_item(1, source_db=path.name)


def test_federated_search_uses_rank_fusion_and_keeps_colliding_ids():
    results = embeddings.federated_results([
        ("tapl-b.db", [{"id": 1, "score": -999}, {"id": 2, "score": -998}]),
        ("tapl-a.db", [{"id": 1, "score": 0.01}, {"id": 2, "score": 0.02}]),
    ], limit=3)
    assert [(row["source_db"], row["id"]) for row in results] == [
        ("tapl-a.db", 1), ("tapl-b.db", 1), ("tapl-a.db", 2)]
    assert results[0]["score"] == results[1]["score"]
    assert results[1]["source_score"] == -999


@pytest.mark.parametrize("query", ["", "sqlite migration"])
def test_memory_pagination_applies_one_global_offset_limit_with_no_duplicates(sources, query):
    *_, reader = sources
    full = reader.recall(query, limit=50)
    pages = [reader.recall(query, limit=1, offset=index) for index in range(6)]
    pointers = lambda rows: [(row["source_db"], row["id"]) for row in rows]
    assert pointers(full["memories"]) == pointers([page["memories"][0] for page in pages])
    assert all(page["total"] == 6 for page in pages)
    assert reader.recall(query, limit=1, offset=6)["memories"] == []


def test_foreign_only_read_never_creates_installation_or_local_database(tmp_path):
    peer = tmp_path / ".tapl/tapl-any-suffix.db"
    seed(peer, "only foreign")
    assert identity.installation_id(create=False) is None
    reader = history.HistoryReader(tmp_path, settings=config.from_mapping({}, path="unused"))
    assert reader.search("sqlite migration")["results"][0]["source_db"] == peer.name
    assert reader.recall()["total"] == 1
    assert identity.installation_id(create=False) is None
    assert db.discover_db_paths(tmp_path) == [peer]
    with pytest.raises(history.HistoryError, match="local TAPL history"):
        reader.get_item(1)


def test_automatic_foreign_hint_and_finish_use_never_reinforce_a_colliding_local_memory(tmp_path):
    local, peer = db.default_db_path(tmp_path), tmp_path / ".tapl/tapl-foreign.db"
    local_record, foreign_record = seed(local, "local")[0], seed(peer, "foreign")[0]
    # Collision is intentional: source_db remains the only safe routing key.
    for path in (local, peer):
        with sqlite3.connect(path) as conn:
            conn.execute("UPDATE memories SET memory_id='collision'")
    with sqlite3.connect(local) as conn:
        conn.execute("UPDATE memories SET state='superseded'")
    app = WorkflowApplication(tmp_path, session_id="current")
    before_peer = fingerprint(peer)
    result = app.summarize_run("sqlite migration", work_type="answer", workflow_mode="fast")
    hint = result["recall"]["memories"][0]
    assert hint["source_db"] == hint["source"]["source_db"] == peer.name
    assert hint["source"]["run_id"] == foreign_record["run_id"]
    use = {"memory_id": "collision", "revision": 1, "source_checked": True, "usage": "Checked migration evidence"}
    missing = app.finish_run("done", expected_run_id=result["active_run"]["id"], memory_uses=[use])
    assert "source_db" in missing["memory"]["errors"][0]["message"]
    finished = app.finish_run("done", expected_run_id=result["active_run"]["id"],
                              memory_uses=[{**use, "source_db": peer.name}],
                              memory_review={"decision": "skip", "reason": "No new lesson"})
    assert finished["memory"]["reinforcements"] == [{"memory_id": "collision", "source_db": peer.name,
                                                        "status": "skipped", "reason": "foreign_source_read_only"}]
    assert fingerprint(peer) == before_peer
    with sqlite3.connect(local) as conn:
        assert conn.execute("SELECT last_reinforced_at FROM memories").fetchone()[0] is None
    assert app.summarize_run("sqlite migration")["recall"]["status"] == "already_attempted"


def test_status_foreign_selection_is_read_only_and_never_changes_local_session(sources):
    root, local, peer, *_ = sources
    app = WorkflowApplication(root, session_id="owner")
    local_run = app.summarize_run("local current")["active_run"]["id"]
    with closing(db.connect(peer, session_id="owner")) as conn:
        foreign_run = db.ensure_active_run(conn, request_summary="foreign current")["id"]
    before = fingerprint(peer)
    inventory = app.get_status()
    assert inventory["active_run"]["id"] == local_run
    assert {(row["id"], row["writable"]) for row in inventory["active_runs"]} == {(local_run, True), (foreign_run, False)}
    selected = app.get_status(source_db=peer.name)
    assert selected["active_run"]["id"] == foreign_run and selected["writable"] is False
    with pytest.raises(WorkflowApplicationError, match="read-only"):
        app.discard_run(run_id=foreign_run, confirmed=True, confirmation_run_id=foreign_run, source_db=peer.name)
    assert app.get_status()["active_run"]["id"] == local_run and fingerprint(peer) == before


def test_mcp_source_selector_reads_the_original_foreign_record(sources):
    root, _, peer, _, second, _ = sources
    server = mcp_server.create_server(workspace_root=root)
    tools = {tool.name: tool for tool in asyncio.run(server.list_tools())}
    for name in ("tapl_get_item", "tapl_get_archive", "tapl_get_memory", "tapl_get_status"):
        assert "source_db" in tools[name].input_schema["properties"]

    async def exercise():
        async with Client(server) as client:
            for name, args in (
                ("tapl_get_item", {"item_id": second[0]["item_id"], "compact": True}),
                ("tapl_get_archive", {"archive_id": "same-0"}),
                ("tapl_get_memory", {"memory_id": second[0]["memory_id"]}),
            ):
                result = await client.call_tool(name, {**args, "source_db": peer.name})
                assert not result.is_error and result.structured_content["source_db"] == peer.name
            bad = await client.call_tool("tapl_get_item", {"item_id": 1, "source_db": str(peer)})
            assert bad.is_error
    asyncio.run(exercise())


def test_automatic_recall_budgets_many_source_errors_and_retains_full_manual_errors(tmp_path):
    local = db.default_db_path(tmp_path)
    peer = tmp_path / ".tapl/tapl-peer.db"
    seed(peer, "foreign")
    for index in range(20):
        (peer.parent / f"tapl-corrupt-{index}.db").write_bytes(b"corrupt")
    app = WorkflowApplication(tmp_path)
    hint = app.summarize_run("sqlite migration", work_type="answer", workflow_mode="fast")["recall"]
    assert len(json.dumps(hint, ensure_ascii=False).encode("utf-8")) <= 1200
    assert hint["source_errors_omitted"] > 0
    assert hint["memories"][0]["source_db"] == peer.name
    assert len(app.recall()["source_errors"]) == 20


def test_memory_mutations_reject_explicit_foreign_sources(sources):
    root, local, peer, first, second, _ = sources
    app = WorkflowApplication(root)
    before = {path: fingerprint(path) for path in (local, peer)}
    with pytest.raises(WorkflowApplicationError, match="read-only"):
        app.update_memory(first[0]["memory_id"], expected_revision=1, note="Change the lesson", source_db=peer.name)
    with pytest.raises(WorkflowApplicationError, match="read-only"):
        app.delete_memory(first[0]["memory_id"], expected_revision=1, source_db=peer.name)
    assert before == {path: fingerprint(path) for path in (local, peer)}


def test_manual_memory_collision_requires_selector_and_explicit_local_use_stays_local(tmp_path):
    local, peer = db.default_db_path(tmp_path), tmp_path / ".tapl/tapl-peer.db"
    seed(local, "local")
    seed(peer, "foreign")
    for path in (local, peer):
        with sqlite3.connect(path) as conn:
            conn.execute("UPDATE memories SET memory_id='collision'")
    app = WorkflowApplication(tmp_path)
    current = app.summarize_run("unrelated request")["active_run"]["id"]
    assert len(app.recall("sqlite migration")["memories"]) == 2
    use = {"memory_id": "collision", "revision": 1, "source_checked": True, "usage": "Reviewed original lesson"}
    before = fingerprint(peer)
    rejected = app.finish_run("done", expected_run_id=current, memory_uses=[use])
    assert "source_db" in rejected["memory"]["errors"][0]["message"]
    result = app.finish_run("done", expected_run_id=current, memory_uses=[{**use, "source_db": local.name}],
                            memory_review={"decision": "skip", "reason": "No new lesson"})
    assert result["memory"]["reinforcements"][0]["status"] == "reinforced"
    assert fingerprint(peer) == before


def test_foreign_run_id_is_never_used_to_filter_local_recall_scope(sources):
    _, local, peer, _, foreign, reader = sources
    with closing(db.connect_readonly(local)) as conn:
        payload = reader.automatic_recall(local_conn=conn, run_id=foreign[0]["run_id"],
                                          query="sqlite migration", now=recall._time())
    assert any(memory["source_db"] == peer.name and memory["source"]["run_id"] == foreign[0]["run_id"]
               for memory in payload["memories"])
