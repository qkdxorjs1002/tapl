from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, contextmanager
import json
from pathlib import Path
import sqlite3
from threading import Thread
from unittest import mock
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener

import pytest

from taplctl import auto_reindex, config, db, mcp_server, settings, viewer


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setenv("TAPL_CLIENT", "codex")


@contextmanager
def browser_server(app: viewer.ViewerApplication) -> Iterator[viewer.ViewerHTTPServer]:
    server = viewer.create_server(app, port=0)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def browser_post(server: viewer.ViewerHTTPServer, payload: dict, origin: str | None) -> tuple[int, dict]:
    headers = {"Content-Type": "application/json"}
    if origin is not None:
        headers["Origin"] = origin
    request = Request(f"{server.browser_origin}/api/message", data=json.dumps(payload).encode(), headers=headers)
    try:
        response = build_opener(ProxyHandler({})).open(request, timeout=5)
    except HTTPError as exc:
        response = exc
    with response:
        return response.code, json.load(response)


def test_settings_schedule_after_commit_and_only_on_changed_save_or_reset(tmp_path, monkeypatch):
    root = tmp_path / "workspace"
    root.mkdir()
    pinned = tmp_path / "pinned.toml"
    service = settings.SettingsService(root, config_path=pinned)
    original = service.get()
    models = []

    def schedule(workspace, *, config_path):
        assert workspace == root and config_path == pinned

        def read_model():
            assert settings._WRITE_LOCK.acquire(blocking=False)
            try:
                return config.load(config_path, start=workspace).search.model
            finally:
                settings._WRITE_LOCK.release()

        with ThreadPoolExecutor() as executor:
            models.append(executor.submit(read_model).result(timeout=5))
        return {"status": "scheduled"}

    monkeypatch.setattr(auto_reindex, "schedule", schedule)
    unchanged = service.save({}, original["revision"])
    assert unchanged["changed"] is False and "reindex" not in unchanged
    changed = service.save({"search.model": "multilingual-e5-small-int8"}, original["revision"])
    assert changed["reindex"] == {"status": "scheduled"}
    with pytest.raises(settings.SettingsConflict):
        service.save({}, original["revision"], reset_all=True)
    with mock.patch("taplctl.config_editor._atomic_write", side_effect=OSError("config is read-only")):
        with pytest.raises(OSError, match="config is read-only"):
            service.save({}, changed["settings"]["revision"], reset_all=True)
    assert models == ["multilingual-e5-small-int8"]
    reset = service.save({}, changed["settings"]["revision"], reset_all=True)
    assert reset["reindex"] == {"status": "scheduled"}
    assert models == ["multilingual-e5-small-int8", config.DEFAULT_SEARCH_MODEL]


def test_mcp_homebrew_startup_checks_only_bound_workspace(tmp_path, monkeypatch):
    root = tmp_path / "workspace"
    root.mkdir()
    monkeypatch.chdir(root)
    refresh = mock.Mock()
    schedule = mock.Mock(return_value=None)
    runtime = mock.Mock(return_value=False)
    monkeypatch.setattr(mcp_server.tapl_install, "auto_install_if_needed", refresh)
    monkeypatch.setattr(auto_reindex, "is_homebrew_runtime", runtime)
    monkeypatch.setattr(auto_reindex, "schedule", schedule)
    mcp_server.create_server(refresh_install=True)
    schedule.assert_not_called()
    runtime.return_value = True
    mcp_server.create_server(workspace_root=root)
    schedule.assert_not_called()
    mcp_server.create_server(refresh_install=True)
    refresh.assert_called_with(start=root)
    schedule.assert_called_once_with(root)
    assert list(root.iterdir()) == []


def test_homebrew_browser_checks_workspace_only_on_first_allowed_open(tmp_path, monkeypatch):
    root = tmp_path / "workspace"
    db.initialize_workspace(root)
    linked = tmp_path / "bookmark 한글 "
    db.initialize_workspace(linked)
    linked_db = db.local_db_path(linked)
    with closing(db.connect(linked_db, session_id="bookmark-owner")) as conn:
        run = db.ensure_active_run(conn, request_summary="Bookmark RUN")
    pinned = tmp_path / "pinned.toml"
    pinned.write_text("[search]\nmode = 'hybrid'\n", encoding="utf-8")
    app = viewer.ViewerApplication(default_workspace=root, config_path=pinned)
    runtime = mock.Mock(return_value=False)
    schedule = mock.Mock(side_effect=[{"status": "failed", "error": "worker startup failed"}, None,
                                     {"status": "scheduled"}])
    monkeypatch.setattr(auto_reindex, "is_homebrew_runtime", runtime)
    monkeypatch.setattr(auto_reindex, "schedule", schedule)
    ready = {"command": "ready"}
    selection = {"command": "selectWorkspace", "workspace": str(root)}
    bookmark = {"command": "ready", "workspace": str(linked), "runId": run["id"], "source_db": linked_db.name}
    with browser_server(app) as server:
        origin = server.browser_origin
        assert browser_post(server, ready, origin)[1]["view"]["type"] == "overview"
        runtime.return_value = True
        for request in (ready, selection, bookmark):
            assert browser_post(server, request, None)[0] == 200
            assert browser_post(server, request, "https://untrusted.example")[0] == 403
        for request in ({"command": "revision"}, {"command": "refresh", "viewType": "overview"},
                        {"command": "getSettings", "requestId": "read"},
                        {"command": "selectWorkspace", "workspace": str(tmp_path / "missing")}):
            assert browser_post(server, request, origin)[0] == 200
        schedule.assert_not_called()

        assert browser_post(server, ready, origin)[1]["view"]["type"] == "overview"
        assert browser_post(server, selection, origin)[1]["view"]["type"] == "overview"
        assert browser_post(server, ready, origin)[1]["view"]["type"] == "overview"
        assert browser_post(server, bookmark, origin)[1]["view"]["type"] == "run"
        assert browser_post(server, bookmark, origin)[1]["view"]["type"] == "run"
        assert schedule.call_args_list == [mock.call(root, config_path=pinned), mock.call(root, config_path=pinned),
                                           mock.call(linked, config_path=pinned)]


def test_homebrew_browser_bookmark_does_not_reindex_a_peer_database(tmp_path, monkeypatch):
    root = tmp_path / "peer-only"
    peer = root / ".tapl" / "tapl-11111111-2222-4333-8444-555555555555.db"
    peer.parent.mkdir(parents=True)
    with closing(db.connect(peer, session_id="peer-owner")) as conn:
        run = db.ensure_active_run(conn, request_summary="Peer RUN")
    with closing(sqlite3.connect(peer)) as conn:
        conn.execute("PRAGMA journal_mode=DELETE")
    original = peer.read_bytes()
    monkeypatch.setattr(auto_reindex, "is_homebrew_runtime", lambda: True)
    schedule = mock.Mock(wraps=auto_reindex.schedule)
    monkeypatch.setattr(auto_reindex, "schedule", schedule)
    start_worker = mock.Mock()
    monkeypatch.setattr(auto_reindex.subprocess, "Popen", start_worker)

    app = viewer.ViewerApplication()
    with browser_server(app) as server:
        status, response = browser_post(server, {"command": "ready", "workspace": str(root), "runId": run["id"],
                                              "source_db": peer.name}, server.browser_origin)
        assert status == 200 and response["view"]["type"] == "run"
    assert peer.read_bytes() == original
    assert list(peer.parent.iterdir()) == [peer]
    assert list(Path.home().iterdir()) == []
    schedule.assert_called_once_with(root, config_path=None)
    start_worker.assert_not_called()
