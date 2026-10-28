"""Confirmed viewer mutations use captured owners, never the selected RUN."""

from contextlib import closing, contextmanager
from http.client import HTTPConnection
import json
import threading

import pytest

from taplctl import db, viewer
from taplctl.application import WorkflowApplication


@pytest.fixture
def workspace(tmp_path):
    root = tmp_path / "workspace"
    db.initialize_workspace(root)
    runs = {}
    for owner in ("a", "b"):
        app = WorkflowApplication(root, session_id=owner)
        runs[owner] = app.summarize_run(f"Work {owner}")["active_run"]["id"]
        app.apply_plan("PLAN-001", title=f"Plan {owner}", requirements_trace="REQ-001", validation="Read plan")
    return root, runs


def request(root, runs, **overrides):
    return {"command": "discardRun", "workspace": str(root), "sessionId": "a",
            "targetSessionId": "b", "runId": runs["b"], "confirmed": True,
            "confirmationRunId": runs["b"], **overrides}


def active(root):
    with closing(db.connect(root / db.DEFAULT_DB_RELATIVE)) as conn:
        return {row["session_id"]: row["id"] for row in db.active_runs(conn)}


def test_discard_unselected_owner_keeps_selected_board_and_archived_history(workspace):
    root, runs = workspace
    app = viewer.ViewerApplication(default_workspace=root)
    result = app.handle_message(request(root, runs))
    assert result["discardResult"] == {"runId": runs["b"], "ok": True}
    assert result["capabilities"]["discardRun"] is True
    assert result["view"]["status"]["active_run"]["id"] == runs["a"]
    assert result["view"]["status"]["session_id"] == "a"
    assert active(root) == {"a": runs["a"]}
    with closing(db.connect(root / db.DEFAULT_DB_RELATIVE)) as conn:
        assert conn.execute("SELECT status FROM workflow_runs WHERE id=?", (runs["b"],)).fetchone()[0] == "archived"
        assert conn.execute("SELECT COUNT(*) FROM items WHERE run_id=? AND archived=1", (runs["b"],)).fetchone()[0] == 1


def test_discard_selected_owner_falls_back_to_remaining_run_only_for_read(workspace):
    root, runs = workspace
    result = viewer.ViewerApplication(default_workspace=root).handle_message(
        request(root, runs, targetSessionId="a", runId=runs["a"], confirmationRunId=runs["a"]))
    assert result["discardResult"]["ok"] is True
    assert result["view"]["status"]["session_id"] == "b"
    assert active(root) == {"b": runs["b"]}


@pytest.mark.parametrize("overrides", [
    {"confirmed": False}, {"confirmed": 1}, {"confirmed": "true"}, {"confirmed": None},
    {"runId": ""}, {"runId": "stale", "confirmationRunId": "stale"}, {"runId": "   "},
    {"targetSessionId": None}, {"targetSessionId": "a"}, {"targetSessionId": "b\n"},
    {"workspace": ""}, {"workspace": None}, {"sessionId": "a\n"},
])
def test_discard_rejects_invalid_or_stale_target_without_mutation(workspace, overrides):
    root, runs = workspace
    result = viewer.ViewerApplication(default_workspace=root).handle_message(request(root, runs, **overrides))
    assert result["type"] == "error"
    assert result["discardResult"]["ok"] is False
    assert active(root) == runs


def test_discard_requires_explicit_owner_and_confirmation(workspace):
    root, runs = workspace
    app = viewer.ViewerApplication(default_workspace=root)
    for missing in ("targetSessionId", "confirmed", "confirmationRunId", "workspace"):
        payload = request(root, runs)
        del payload[missing]
        assert app.handle_message(payload)["discardResult"]["ok"] is False
    assert active(root) == runs


@pytest.mark.parametrize("proof_kind", ["missing", "nonstring", "empty", "partial", "wrongcase", "leading_space", "trailing_space"])
def test_discard_requires_complete_exact_run_id_proof_without_mutation(workspace, proof_kind):
    root, runs = workspace
    proof = {"nonstring": 1, "empty": "", "partial": runs["b"][:-1], "wrongcase": runs["b"].swapcase(),
             "leading_space": " " + runs["b"], "trailing_space": runs["b"] + " "}.get(proof_kind)
    payload = request(root, runs, confirmationRunId=proof)
    if proof_kind == "missing":
        del payload["confirmationRunId"]
    result = viewer.ViewerApplication(default_workspace=root).handle_message(payload)
    assert result["type"] == "error"
    assert result["discardResult"]["ok"] is False
    assert active(root) == runs


def test_discard_uses_explicit_chosen_workspace_and_leaves_default_untouched(workspace, tmp_path):
    root, runs = workspace
    other = tmp_path / "other"
    db.initialize_workspace(other)
    other_runs = {}
    for owner in ("a", "b"):
        owner_app = WorkflowApplication(other, session_id=owner)
        other_runs[owner] = owner_app.summarize_run(f"Other {owner}")["active_run"]["id"]
        owner_app.apply_plan("PLAN-001", title=f"Other plan {owner}", requirements_trace="REQ-001", validation="Read plan")
    app = viewer.ViewerApplication(default_workspace=root)
    chosen = app.handle_message({"command": "selectWorkspace", "workspace": str(other), "sessionId": "a"})
    assert chosen["view"]["status"]["active_run"]["id"] == other_runs["a"]
    assert chosen["workspace"] == str(other)
    stale = app.handle_message(request(root, runs, workspace=str(other)))
    assert stale["discardResult"]["ok"] is False
    assert active(root) == runs
    assert active(other) == other_runs
    result = app.handle_message(
        request(root, runs, workspace=str(other), runId=other_runs["b"], confirmationRunId=other_runs["b"]))
    assert result["discardResult"]["ok"] is True
    assert result["workspace"] == str(other)
    assert result["view"]["status"]["active_run"]["id"] == other_runs["a"]
    assert active(root) == runs
    assert active(other) == {"a": other_runs["a"]}


def test_discard_supports_explicit_legacy_owner(workspace):
    root, runs = workspace
    legacy = WorkflowApplication(root, session_id="").summarize_run("Legacy")["active_run"]["id"]
    result = viewer.ViewerApplication(default_workspace=root).handle_message(
        request(root, runs, targetSessionId="", runId=legacy, confirmationRunId=legacy))
    assert result["discardResult"]["ok"] is True
    assert result["view"]["status"]["session_id"] == "a"
    assert active(root) == runs


@contextmanager
def server_for(root):
    server = viewer.create_server(viewer.ViewerApplication(default_workspace=root), port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def post(server, payload, origin=None, content_type="application/json"):
    with closing(HTTPConnection(*server.server_address[:2])) as connection:
        headers = {"Content-Type": content_type}
        if origin is not None:
            headers["Origin"] = origin
        connection.request("POST", "/api/message", json.dumps(payload), headers)
        response = connection.getresponse()
        return response.status, json.loads(response.read())


def test_http_mutations_require_allowed_origin_json_and_exact_confirmation(workspace):
    root, runs = workspace
    with server_for(root) as server:
        payload = request(root, runs)
        assert post(server, {"command": "ready"})[0] == 200
        for origin in (None, "null", "https://attacker.example", server.browser_origin + "/path"):
            assert post(server, payload, origin)[0] == 403
            assert active(root) == runs
        assert post(server, payload, server.browser_origin, "text/plain")[0] == 415
        for value in (False, "true", 1, None):
            code, result = post(server, {**payload, "confirmed": value}, server.browser_origin)
            assert code == 200
            assert result["discardResult"]["ok"] is False
            assert active(root) == runs
        for proof in (None, 1, "", runs["b"][:-1], runs["b"].swapcase(), runs["b"] + " "):
            code, result = post(server, {**payload, "confirmationRunId": proof}, server.browser_origin)
            assert code == 200
            assert result["discardResult"]["ok"] is False
            assert active(root) == runs
        code, result = post(server, payload, server.browser_origin)
        assert code == 200
        assert result["discardResult"]["ok"] is True
        assert active(root) == {"a": runs["a"]}
