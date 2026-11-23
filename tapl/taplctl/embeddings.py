"""Optional semantic search support for TAPL."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache
import importlib.util
from itertools import zip_longest
from pathlib import Path
import sqlite3
from typing import Any

from . import config as tapl_config, db, embedding_model, searchd


# Pre-ONNX clients issue unguarded KNN queries against item_embeddings.
# Keep their vectors and metadata isolated, including when both clients run.
_INDEX_TABLE = "item_embeddings_onnx"
_ITEMS_SQL = """
    SELECT id, stable_id, kind, title, body, raw_text, custom_fields_json, run_id
    FROM items ORDER BY id
"""
_BATCH_SIZE = 32


def dependency_status() -> dict[str, bool]:
    return {name: importlib.util.find_spec(name) is not None
            for name in ("sqlite_vec", "numpy", "onnxruntime", "tokenizers")}


@lru_cache(maxsize=1)
def _local_model(model: str, cache_root: Path) -> embedding_model.Encoder:
    return embedding_model.Encoder(model, cache_root)


def _load_vec(conn: sqlite3.Connection) -> None:
    import sqlite_vec

    conn.enable_load_extension(True)
    try:
        sqlite_vec.load(conn)
    finally:
        conn.enable_load_extension(False)


@contextmanager
def _index_transaction(conn: sqlite3.Connection) -> Iterator[None]:
    # A savepoint also works inside the reader's existing read-only snapshot.
    conn.execute("SAVEPOINT tapl_semantic_index")
    try:
        yield
        conn.execute("RELEASE tapl_semantic_index")
    except BaseException:
        conn.execute("ROLLBACK TO tapl_semantic_index")
        conn.execute("RELEASE tapl_semantic_index")
        raise


def _index_identity(conn: sqlite3.Connection) -> tuple[str | None, str | None]:
    tables = {row[0] for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name IN (?, 'item_embeddings')",
        (_INDEX_TABLE,),
    )}
    meta = db.get_meta(conn)
    if _INDEX_TABLE in tables:
        return meta.get("onnx_embedding_model"), meta.get("onnx_embedding_fingerprint")
    if "item_embeddings" in tables:
        return meta.get("embedding_model") or "legacy", None
    return None, None


def reindex(
    conn: sqlite3.Connection, *, model: str = embedding_model.DEFAULT_MODEL, dry_run: bool = False,
) -> dict[str, Any]:
    spec = embedding_model.MODELS[model]
    status = dependency_status()
    with _index_transaction(conn):
        indexed_model, indexed_fingerprint = _index_identity(conn)
        items = conn.execute(_ITEMS_SQL).fetchall()
        source_hash = db.content_hash(
            db.content_hash((str(item["id"]), item["run_id"], item_text(item))) for item in items
        )
        stored_hash = conn.execute("SELECT value FROM meta WHERE key='onnx_embedding_source_hash'").fetchone()
    payload = {
        "dry_run": dry_run, "items": len(items), "dependencies": status,
        "embedding_model": model, "embedding_dimension": embedding_model.DIMENSION,
        "embedding_fingerprint": spec.fingerprint,
        "indexed_model": indexed_model, "indexed_fingerprint": indexed_fingerprint,
        "needs_reindex": ((indexed_model, indexed_fingerprint) != (model, spec.fingerprint)
                          or stored_hash is None or stored_hash[0] != source_hash),
    }
    if dry_run:
        return {**payload, "ok": True}
    missing = [name for name, available in status.items() if not available]
    if missing:
        return {**payload, "ok": False, "error": f"missing optional dependencies: {', '.join(missing)}"}

    try:
        _load_vec(conn)
        vectors = []
        if items:
            encoder = _local_model(model, embedding_model.cache_root())
            for offset in range(0, len(items), _BATCH_SIZE):
                batch = items[offset:offset + _BATCH_SIZE]
                vectors.extend(encoder.encode([item_text(item) for item in batch], query=False))

        with _index_transaction(conn):
            # Take the write lock only after downloads and inference. Confirm
            # exactly the inputs used above before publishing this generation.
            db.set_meta(conn, "onnx_embedding_model", model)
            if any(before != after for before, after in zip_longest(items, conn.execute(_ITEMS_SQL))):
                raise ValueError("indexed items changed during the rebuild; retry taplctl reindex")
            conn.execute(f"""
                CREATE VIRTUAL TABLE IF NOT EXISTS {_INDEX_TABLE}
                USING vec0(embedding float[{embedding_model.DIMENSION}], kind text, run_id text)
            """)
            conn.execute(f"DELETE FROM {_INDEX_TABLE}")
            conn.executemany(
                f"INSERT INTO {_INDEX_TABLE}(rowid, embedding, kind, run_id) VALUES(?, ?, ?, ?)",
                ((item["id"], vector, item["kind"], item["run_id"])
                 for item, vector in zip(items, vectors, strict=True)),
            )
            now = db.utc_now()
            conn.executemany(
                """INSERT INTO embedding_jobs(item_id, content_hash, state, updated_at)
                   VALUES(?, ?, 'indexed', ?)
                   ON CONFLICT(item_id) DO UPDATE SET content_hash=excluded.content_hash,
                     state=excluded.state, updated_at=excluded.updated_at""",
                ((item["id"], db.content_hash([item["stable_id"], item["title"], item["body"],
                                               item["raw_text"], db.custom_fields_search_text(item["custom_fields_json"])]),
                  now) for item in items),
            )
            db.set_meta(conn, "onnx_embedding_fingerprint", spec.fingerprint)
            db.set_meta(conn, "onnx_embedding_source_hash", source_hash)
    except Exception as exc:
        return {**payload, "ok": False, "error": f"semantic reindex failed: {exc}"}
    return {**payload, "ok": True, "items": len(items), "indexed": len(items), "needs_reindex": False,
            "indexed_model": model, "indexed_fingerprint": spec.fingerprint}


def search(
    conn: sqlite3.Connection,
    query: str,
    *,
    limit: int = tapl_config.DEFAULT_SEARCH_MAX_RESULTS,
    search_config: tapl_config.SearchConfig | None = None,
) -> dict[str, Any]:
    settings = search_config or tapl_config.SearchConfig()
    payload = {"query": query, "limit": limit, "configured_mode": settings.mode,
               "search_config": settings.as_dict()}
    if settings.mode == "bm25":
        return {**payload, "mode": "bm25", "results": db.search_bm25(conn, query, limit=limit)}
    if settings.mode == "word":
        return {**payload, "mode": "word", "results": db.search_word(conn, query, limit=limit)}

    hybrid = settings.mode == "hybrid"
    pool_size = limit * 2 if hybrid else limit
    try:
        semantic = semantic_search(conn, query, limit=pool_size, search_config=settings)
    except Exception as exc:
        return {**payload, "mode": "hybrid" if hybrid else "bm25",
                "fallback_reason": f"Semantic search unavailable: {exc}. Used BM25.",
                "results": db.search_bm25(conn, query, limit=limit)}
    if hybrid:
        semantic = hybrid_results(semantic, db.search_bm25(conn, query, limit=pool_size),
                                  limit=limit, semantic_ratio=settings.hybrid_semantic_ratio)
    return {**payload, "mode": settings.mode, "results": semantic}


def semantic_search(
    conn: sqlite3.Connection,
    query: str,
    *,
    limit: int,
    search_config: tapl_config.SearchConfig | None = None,
) -> list[dict[str, Any]]:
    settings = search_config or tapl_config.SearchConfig()
    model = settings.model
    with _index_transaction(conn):
        indexed_model, fingerprint = _index_identity(conn)
        if indexed_model is None:
            raise ValueError(f"no semantic index for {model}; run taplctl reindex")
        if (indexed_model, fingerprint) != (model, embedding_model.MODELS[model].fingerprint):
            raise ValueError(f"index for {indexed_model} is incompatible with {model}; run taplctl reindex")
        _load_vec(conn)
        if not conn.execute(f"SELECT 1 FROM {_INDEX_TABLE} LIMIT 1").fetchone():
            raise ValueError("semantic index is empty; run taplctl reindex after adding items")

        blob = query_embedding_blob(query, settings)
        rows = conn.execute(
            f"""SELECT i.*, v.distance AS score FROM {_INDEX_TABLE} v
                JOIN items i ON i.id = v.rowid
                WHERE v.embedding MATCH ? AND k = ? ORDER BY v.distance""",
            (blob, limit),
        ).fetchall()
    return [db.search_row(row, "semantic") for row in rows]


def query_embedding_blob(query: str, settings: tapl_config.SearchConfig) -> bytes:
    if settings.semantic_provider != "local":
        try:
            return searchd.embed_query(query, settings)
        except searchd.SearchdUnavailable:
            pass
        except searchd.SearchdError:
            if settings.semantic_provider == "daemon":
                raise
    return local_query_embedding_blob(query, settings.model)


def local_query_embedding_blob(query: str, model: str) -> bytes:
    return _local_model(model, embedding_model.cache_root()).encode([query], query=True)[0]


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


def federated_results(
    sources: list[tuple[str, list[dict[str, Any]]]], *, limit: int,
    preserve_score: bool = False,
) -> list[dict[str, Any]]:
    """Fuse independent database rankings without comparing their raw scores.

    Equal reciprocal ranks tie by filename and record id. A database-local id
    never deduplicates a record from a different source.
    """
    ranked = []
    multiple = len(sources) > 1
    for source_db, records in sources:
        for rank, record in enumerate(records, 1):
            item = {**record, "source_db": source_db}
            score = 1.0 / (60 + rank)
            if multiple and not preserve_score:
                item.update({"source_score": item.get("score"), "score": score,
                             "rank_fusion": "reciprocal_rank"})
            ranked.append((score, source_db, str(item.get("id", "")), item))
    ranked.sort(key=lambda entry: (-entry[0], entry[1], entry[2]))
    return [entry[3] for entry in ranked[:limit]]


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
            db.custom_fields_search_text(row["custom_fields_json"]),
        ]
        if part
    )
