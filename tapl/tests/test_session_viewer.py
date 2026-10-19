"""The read-only viewer selects a RUN without changing its ownership."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import closing

from taplctl import db, viewer
from taplctl.application import WorkflowApplication


def test_viewer_selects_independent_runs_and_preserves_ownership(tmp_path):
    root = tmp_path / "workspace"
    db.initialize_workspace(root)
    ids = {}
    for owner in ("a", "b"):
        app = WorkflowApplication(root, session_id=owner)
        ids[owner] = app.summarize_run(f"Work {owner}")["active_run"]["id"]
        app.apply_plan("PLAN-001", title=f"Plan {owner}", requirements_trace="REQ-001", validation="Read the plan")
    app = viewer.ViewerApplication(default_workspace=root)
    overview = app.handle_message({"command": "ready"})["view"]["status"]
    assert len(overview["active_runs"]) == 2
    assert overview["active_run"]["id"] in ids.values()

    def read(owner):
        return app.handle_message({"command": "selectRun", "sessionId": owner})["view"]["status"]

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(read, ("a", "b")))
    for owner, status in zip(("a", "b"), results):
        assert status["session_id"] == owner
        assert status["active_run"]["id"] == ids[owner]
        assert [plan["title"] for plan in status["plans"]] == [f"Plan {owner}"]
    with closing(db.connect(root / db.DEFAULT_DB_RELATIVE)) as conn:
        assert db.active_run(conn) is None
        assert {row["session_id"]: row["id"] for row in db.active_runs(conn)} == ids


def test_viewer_rejects_invalid_session_selection(tmp_path):
    db.initialize_workspace(tmp_path)
    app = viewer.ViewerApplication(default_workspace=tmp_path)
    for payload in ({"command": "selectRun"}, {"command": "selectRun", "sessionId": "a\nb"},
                    {"command": "selectRun", "sessionId": 123}):
        assert app.handle_message(payload)["type"] == "error"


def test_shared_task_ids_do_not_mix_execution_details_between_runs(tmp_path):
    db.initialize_workspace(tmp_path)

    def runner(_path, args):
        if args[0] == "item":
            return {"item": {"id": 22, "kind": "task", "stable_id": "TASK-001", "title": "Session B task", "run_id": "run-b"}}
        assert args[0] == "status"
        return {"tasks": [{"id": 11, "stable_id": "TASK-001", "run_id": "run-a",
                           "depends_on": ["TASK-002"], "active_execution": {"execution_id": "execution-a"}}]}

    app = viewer.ViewerApplication(default_workspace=tmp_path, json_runner=runner)
    detail = app.handle_message({"command": "openSearchResult", "itemId": 22, "sessionId": "a"})["view"]["detail"]
    assert detail["run_id"] == "run-b"
    assert detail.get("active_execution") is None
    assert not detail.get("depends_on")
