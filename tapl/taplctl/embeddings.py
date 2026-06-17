"""Optional semantic search support for tapl."""

from __future__ import annotations

import contextlib
import importlib.util
import os
import sqlite3
import sys
from collections.abc import Iterator
from typing import Any

from . import config as tapl_config, db

_MODEL_LOAD_PROGRESS_MARKERS = ("Loading weights:",)


def dependency_status() -> dict[str, Any]:
    return {
        "sqlite_vec": importlib.util.find_spec("sqlite_vec") is not None,
        "sentence_transformers": importlib.util.find_spec("sentence_transformers") is not None,
        "numpy": importlib.util.find_spec("numpy") is not None,
    }


def reindex(conn: sqlite3.Connection, *, dry_run: bool = False) -> dict[str, Any]:
    items = conn.execute(
        """
        SELECT id, stable_id, kind, title, body, raw_text, run_id
        FROM items
        ORDER BY id
        """
    ).fetchall()

    status = dependency_status()
    payload: dict[str, Any] = {
        "dry_run": dry_run,
        "items": len(items),
        "dependencies": status,
        "embedding_model": db.DEFAULT_EMBEDDING_MODEL,
        "embedding_dimension": db.DEFAULT_EMBEDDING_DIMENSION,
    }
    if dry_run:
        payload["ok"] = True
        return payload

    missing = [name for name, available in status.items() if not available]
    if missing:
        payload["ok"] = False
        payload["error"] = f"missing optional dependencies: {', '.join(missing)}"
        return payload

    import numpy as np
    import sqlite_vec

    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    conn.execute(
        f"""
        CREATE VIRTUAL TABLE IF NOT EXISTS item_embeddings
        USING vec0(embedding float[{db.DEFAULT_EMBEDDING_DIMENSION}], kind text, run_id text)
        """
    )
    conn.execute("DELETE FROM item_embeddings")

    if not items:
        conn.commit()
        payload["ok"] = True
        payload["indexed"] = 0
        return payload

    model = load_model(prefer_local=True)
    texts = [item_text(item) for item in items]
    vectors = model.encode(texts, normalize_embeddings=True)

    for item, vector in zip(items, vectors, strict=True):
        blob = np.asarray(vector, dtype=np.float32).tobytes()
        conn.execute(
            "INSERT INTO item_embeddings(rowid, embedding, kind, run_id) VALUES(?, ?, ?, ?)",
            (item["id"], blob, item["kind"], item["run_id"]),
        )
        conn.execute(
            """
            INSERT INTO embedding_jobs(item_id, content_hash, state, updated_at)
            VALUES(?, ?, 'indexed', ?)
            ON CONFLICT(item_id) DO UPDATE SET
              content_hash = excluded.content_hash,
              state = excluded.state,
              updated_at = excluded.updated_at
            """,
            (
                item["id"],
                db.content_hash([item["stable_id"], item["title"], item["body"], item["raw_text"]]),
                db.utc_now(),
            ),
        )
    conn.commit()
    payload["ok"] = True
    payload["indexed"] = len(items)
    return payload


def search(
    conn: sqlite3.Connection,
    query: str,
    *,
    limit: int = tapl_config.DEFAULT_SEARCH_MAX_RESULTS,
    search_config: tapl_config.SearchConfig | None = None,
) -> dict[str, Any]:
    settings = search_config or tapl_config.SearchConfig()
    payload: dict[str, Any] = {
        "query": query,
        "limit": limit,
        "configured_mode": settings.mode,
        "search_config": settings.as_dict(),
    }

    if settings.mode == "semantic":
        semantic = semantic_search(conn, query, limit=limit)
        if semantic is not None:
            payload.update({"mode": "semantic", "results": semantic})
            return payload
        payload.update(
            {
                "mode": "bm25",
                "fallback_reason": "semantic search unavailable; used bm25",
                "results": db.search_bm25(conn, query, limit=limit),
            }
        )
        return payload

    if settings.mode == "bm25":
        payload.update({"mode": "bm25", "results": db.search_bm25(conn, query, limit=limit)})
        return payload

    if settings.mode == "word":
        payload.update({"mode": "word", "results": db.search_word(conn, query, limit=limit)})
        return payload

    semantic = semantic_search(conn, query, limit=max(limit * 2, limit))
    bm25 = db.search_bm25(conn, query, limit=max(limit * 2, limit))
    if semantic is None:
        payload.update(
            {
                "mode": "hybrid",
                "fallback_reason": "semantic search unavailable; hybrid used bm25 only",
                "results": bm25[:limit],
            }
        )
        return payload

    payload.update(
        {
            "mode": "hybrid",
            "results": hybrid_results(
                semantic,
                bm25,
                limit=limit,
                semantic_ratio=settings.hybrid_semantic_ratio,
            ),
        }
    )
    return payload


def semantic_search(conn: sqlite3.Connection, query: str, *, limit: int) -> list[dict[str, Any]] | None:
    if not all(dependency_status().values()):
        return None

    try:
        import numpy as np
        import sqlite_vec

        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)

        has_table = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'item_embeddings'"
        ).fetchone()
        if not has_table:
            return None

        count = conn.execute("SELECT COUNT(*) AS count FROM item_embeddings").fetchone()["count"]
        if not count:
            return None

        model = load_model(prefer_local=True)
        vector = model.encode([query], normalize_embeddings=True)[0]
        blob = np.asarray(vector, dtype=np.float32).tobytes()
        rows = conn.execute(
            """
            SELECT i.*, item_embeddings.distance AS score
            FROM item_embeddings
            JOIN items i ON i.id = item_embeddings.rowid
            WHERE item_embeddings.embedding MATCH ? AND k = ?
            ORDER BY item_embeddings.distance
            """,
            (blob, limit),
        ).fetchall()
        return [db.search_row(row, "semantic") for row in rows]
    except Exception:
        return None


def hybrid_results(
    semantic: list[dict[str, Any]],
    bm25: list[dict[str, Any]],
    *,
    limit: int,
    semantic_ratio: float,
) -> list[dict[str, Any]]:
    bm25_ratio = 1.0 - semantic_ratio
    merged: dict[Any, dict[str, Any]] = {}

    add_ranked_results(merged, semantic, source="semantic", weight=semantic_ratio)
    add_ranked_results(merged, bm25, source="bm25", weight=bm25_ratio)

    ordered = sorted(
        merged.values(),
        key=lambda item: (-float(item.get("score") or 0.0), str(item.get("stable_id") or "")),
    )
    return ordered[:limit]


def add_ranked_results(
    merged: dict[Any, dict[str, Any]],
    results: list[dict[str, Any]],
    *,
    source: str,
    weight: float,
) -> None:
    if weight == 0.0 or not results:
        return

    for rank, result in enumerate(results, start=1):
        item_id = result.get("id")
        if item_id is None:
            item_id = (result.get("kind"), result.get("stable_id"), result.get("title"))

        item = merged.setdefault(
            item_id,
            {
                **result,
                "score": 0.0,
                "search_source": "hybrid",
                "hybrid_sources": [],
                "source_scores": {},
            },
        )
        item["score"] = float(item["score"]) + weight * (1.0 / rank)
        if source not in item["hybrid_sources"]:
            item["hybrid_sources"].append(source)
        item["source_scores"][source] = result.get("score")


def item_text(row: sqlite3.Row) -> str:
    return "\n".join(
        part
        for part in [
            row["stable_id"],
            row["kind"],
            row["title"],
            row["body"],
            row["raw_text"],
        ]
        if part
    )


def load_model(*, prefer_local: bool):
    from sentence_transformers import SentenceTransformer

    if prefer_local:
        try:
            with suppress_model_load_progress():
                return SentenceTransformer(db.DEFAULT_EMBEDDING_MODEL, local_files_only=True)
        except Exception:
            pass
    with suppress_model_load_progress():
        return SentenceTransformer(db.DEFAULT_EMBEDDING_MODEL)


@contextlib.contextmanager
def suppress_model_load_progress() -> Iterator[None]:
    stdout = sys.stdout
    stderr = sys.stderr
    stdout_filter = _ModelLoadProgressFilter(stdout)
    stderr_filter = _ModelLoadProgressFilter(stderr)
    with contextlib.ExitStack() as stack:
        stack.enter_context(_suppress_stream_fd(stdout))
        stack.enter_context(_suppress_stream_fd(stderr))
        stack.enter_context(contextlib.redirect_stdout(stdout_filter))
        stack.enter_context(contextlib.redirect_stderr(stderr_filter))
        yield


@contextlib.contextmanager
def _suppress_stream_fd(stream: Any) -> Iterator[None]:
    try:
        fd = stream.fileno()
    except (AttributeError, OSError, ValueError):
        yield
        return

    stream.flush()
    saved_fd = os.dup(fd)
    try:
        with open(os.devnull, "w", encoding="utf-8") as devnull:
            os.dup2(devnull.fileno(), fd)
            yield
    finally:
        stream.flush()
        os.dup2(saved_fd, fd)
        os.close(saved_fd)


class _ModelLoadProgressFilter:
    def __init__(self, stream: Any) -> None:
        self.stream = stream
        self._suppress_until_newline = False

    def write(self, text: str) -> int:
        should_suppress = self._suppress_until_newline or any(
            marker in text for marker in _MODEL_LOAD_PROGRESS_MARKERS
        )
        if should_suppress:
            self._suppress_until_newline = "\n" not in text
            return len(text)

        self.stream.write(text)
        return len(text)

    def flush(self) -> None:
        self.stream.flush()
