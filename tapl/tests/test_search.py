from __future__ import annotations

import tempfile
from pathlib import Path

from taplctl import db, embeddings
from taplctl.application import WorkflowApplication


def workspace(tmp: str, *, mode: str = "bm25") -> WorkflowApplication:
    root = Path(tmp) / "workspace"
    (root / ".git").mkdir(parents=True)
    config_path = root / ".tapl" / "config.toml"
    config_path.parent.mkdir()
    config_path.write_text(f'[search]\nmode = "{mode}"\n', encoding="utf-8")
    db.initialize_workspace(root)
    app = WorkflowApplication(root)
    app.summarize_run("Test search ranking")
    return app


def add_plan(
    app: WorkflowApplication,
    plan_id: str,
    title: str,
    *,
    summary: str | None = None,
) -> None:
    app.apply_plan(
        plan_id,
        title=title,
        summary=summary,
        status="Finalized",
    )


def result_ids(app: WorkflowApplication, query: str) -> list[str]:
    return [item["stable_id"] for item in app.search_history(query)["results"]]


def test_bm25_search_ranks_exact_token_before_prefix_match() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        app = workspace(tmp)
        add_plan(app, "PLAN-001", "Lightweight search plan")
        add_plan(app, "PLAN-002", "Light search plan")

        assert result_ids(app, "light") == ["PLAN-002", "PLAN-001"]


def test_bm25_search_weights_title_above_body() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        app = workspace(tmp)
        add_plan(app, "PLAN-001", "Other plan", summary="Improve search ranking")
        add_plan(app, "PLAN-002", "Search ranking", summary="Other details")

        assert result_ids(app, "search") == ["PLAN-002", "PLAN-001"]


def test_bm25_search_uses_precision_tiers_without_dropping_partial_matches() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        app = workspace(tmp)
        add_plan(app, "PLAN-001", "Search rank")
        add_plan(app, "PLAN-002", "Rank details for search")
        add_plan(app, "PLAN-003", "Searching rankings")
        add_plan(app, "PLAN-004", "Search notes")

        assert result_ids(app, "search rank") == [
            "PLAN-001",
            "PLAN-002",
            "PLAN-003",
            "PLAN-004",
        ]


def test_hybrid_search_preserves_improved_bm25_order_without_semantic_hits(monkeypatch) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        app = workspace(tmp, mode="hybrid")
        add_plan(app, "PLAN-001", "Lightweight search plan")
        add_plan(app, "PLAN-002", "Light search plan")
        monkeypatch.setattr(embeddings, "semantic_search", lambda *args, **kwargs: [])

        result = app.search_history("light")

        assert result["mode"] == "hybrid"
        assert [item["stable_id"] for item in result["results"]] == ["PLAN-002", "PLAN-001"]
