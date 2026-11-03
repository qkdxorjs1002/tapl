"""Read-only history across the regular TAPL databases in one workspace.

Integer item ids, archive slugs, and memory ids are scoped to a database. A
selector is an exact discovered filename; omission always selects local history.
"""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import sqlite3
from typing import Any, Iterator

from . import config, db, embeddings, recall as memory_store


class HistoryError(ValueError):
    """An invalid selector or an unavailable explicitly selected history."""


def _annotate(record: dict[str, Any] | None, source_db: str) -> dict[str, Any] | None:
    return {**record, "source_db": source_db} if record is not None else None


def _memory(record: dict[str, Any], source_db: str) -> dict[str, Any]:
    result = {**record, "source_db": source_db,
              "source": {**record["source"], "source_db": source_db}}
    if "source_record" in record:
        original = record["source_record"]
        result["source_record"] = {
            **original, "source_db": source_db,
            "run": _annotate(original.get("run"), source_db),
            "item": _annotate(original.get("item"), source_db),
        }
    return result


class HistoryReader:
    def __init__(
        self, workspace_root: Path, *, local_db_path: Path | None = None,
        settings: config.TaplConfig | None = None, session_id: str | None = None,
    ) -> None:
        self.workspace_root = Path(workspace_root).expanduser().resolve()
        self.local_db_path = (Path(local_db_path).expanduser().absolute() if local_db_path is not None
                              else db.local_db_path(self.workspace_root, create_identity=False))
        if self.local_db_path is not None and not self.local_db_path.is_symlink():
            self.local_db_path = self.local_db_path.resolve()
        self.settings = settings or config.load(start=self.workspace_root)
        self.session_id = session_id

    def discover_sources(self) -> list[Path]:
        """Existing regular files only; discovering histories never creates an id."""
        directory = self.workspace_root / ".tapl"
        if directory.is_symlink():
            return []
        return [path for path in db.discover_db_paths(self.workspace_root)
                if path.parent == directory and path.resolve().parent == directory
                and not path.is_symlink() and path.is_file()]

    def select_source(self, source_db: str | None = None) -> Path:
        sources = self.discover_sources()
        if source_db is not None:
            if not isinstance(source_db, str) or not source_db or Path(source_db).name != source_db:
                raise HistoryError("source_db must be an exact discovered TAPL database filename")
            selected = next((path for path in sources if path.name == source_db), None)
            if selected is None:
                raise HistoryError(f"history source not found: {source_db}")
            return selected
        if self.local_db_path is not None:
            selected = next((path for path in sources if path == self.local_db_path), None)
            if selected is not None:
                return selected
        raise HistoryError("local TAPL history is unavailable; select a discovered source_db")

    @contextmanager
    def _connection(self, path: Path) -> Iterator[sqlite3.Connection]:
        # Recheck immediately before opening; never resolve a symlink into an
        # unrelated database. The shared helper opens mode=ro and validates schema.
        if path not in self.discover_sources():
            raise HistoryError(f"history source not found: {path.name}")
        conn = db.connect_readonly(path, session_id=self.session_id)
        try:
            yield conn
        finally:
            conn.close()

    @staticmethod
    def _error(path: Path, exc: Exception) -> dict[str, str]:
        return {"source_db": path.name, "code": "history_unavailable", "error": str(exc)}

    def _detail(self, source_db: str | None, reader: Any) -> tuple[Path, Any]:
        path = self.select_source(source_db)
        try:
            with self._connection(path) as conn:
                return path, reader(conn)
        except (sqlite3.Error, OSError) as exc:
            raise HistoryError(f"Cannot read {path.name}: {exc}") from exc

    def search(self, query: str, limit: int | None = None) -> dict[str, Any]:
        limit = self.settings.search.max_results if limit is None else limit
        if type(limit) is not int or limit < 1:
            raise HistoryError("limit must be a positive integer")
        payloads, errors = [], []
        for path in self.discover_sources():
            try:
                with self._connection(path) as conn:
                    payload = embeddings.search(conn, query, limit=limit, search_config=self.settings.search)
                payloads.append((path.name, payload))
            except (sqlite3.Error, OSError, ValueError) as exc:
                errors.append(self._error(path, exc))
        base = ({key: value for key, value in payloads[0][1].items() if key != "results"}
                if payloads else {"query": query, "limit": limit, "mode": self.settings.search.mode,
                                  "configured_mode": self.settings.search.mode,
                                  "search_config": self.settings.search.as_dict()})
        ranked = [(name, payload["results"]) for name, payload in payloads]
        results = embeddings.federated_results(ranked, limit=limit)
        return {"ok": True, **base, "results": results, "source_errors": errors}

    def get_item(self, item_id: int, source_db: str | None = None) -> dict[str, Any]:
        path, item = self._detail(source_db, lambda conn: db.item_detail(conn, item_id))
        if item is None:
            raise HistoryError(f"item not found: {item_id}")
        return {"ok": True, "item": _annotate(item, path.name), "source_db": path.name}

    def list_archives(self, limit: int | None = None) -> dict[str, Any]:
        if limit is not None and (type(limit) is not int or limit < 1):
            raise HistoryError("limit must be a positive integer")
        archives, errors = [], []
        for path in self.discover_sources():
            try:
                with self._connection(path) as conn:
                    records = db.list_archives(conn, limit=limit)
                archives.extend(_annotate(record, path.name) for record in records)
            except (sqlite3.Error, OSError, ValueError) as exc:
                errors.append(self._error(path, exc))
        archives.sort(key=lambda row: (str(row.get("created_at") or ""), row["source_db"], str(row["id"])), reverse=True)
        return {"ok": True, "archives": archives if limit is None else archives[:limit], "source_errors": errors}

    def get_archive(self, archive_id: str, source_db: str | None = None) -> dict[str, Any]:
        path, detail = self._detail(source_db, lambda conn: db.archive_detail(conn, archive_id))
        if detail is None:
            raise HistoryError(f"archive not found: {archive_id}")
        return {"ok": True, **detail, "archive": _annotate(detail["archive"], path.name),
                "items": [_annotate(item, path.name) for item in detail["items"]],
                "events": [_annotate(event, path.name) for event in detail["events"]], "source_db": path.name}

    def get_memory(self, memory_id: str, source_db: str | None = None) -> dict[str, Any]:
        def read(conn: sqlite3.Connection) -> dict[str, Any] | None:
            try:
                return memory_store.get_memory(conn, memory_id)
            except memory_store.MemoryError as exc:
                if exc.code != "not_found":
                    raise
                return None
        path, memory = self._detail(source_db, read)
        return {"ok": True, "memory": _memory(memory, path.name) if memory else None, "source_db": path.name}

    def memory_sources(self, memory_id: str) -> list[str]:
        """Find healthy source pointers for collision-safe local reinforcement."""
        sources = []
        for path in self.discover_sources():
            try:
                with self._connection(path) as conn:
                    found = conn.execute("SELECT 1 FROM memories WHERE memory_id=? AND state!='deleted'", (memory_id,)).fetchone()
                if found:
                    sources.append(path.name)
            except (sqlite3.Error, OSError, ValueError):
                # Errors are surfaced on history listing; this lookup merely
                # detects positive collisions, never treats failures as peers.
                continue
        return sources

    def recall(self, query: str = "", limit: int = 3, offset: int = 0) -> dict[str, Any]:
        return {"ok": True, **self._recall(query=query, limit=limit, offset=offset)}

    def automatic_recall(self, *, local_conn: sqlite3.Connection, run_id: str, query: str, now: Any) -> dict[str, Any]:
        """Use the caller's local snapshot; foreign run ids never scope local work."""
        return self._recall(query=query, limit=3, offset=0, automatic=True,
                            local_conn=local_conn, run_id=run_id, now=now)

    def _recall(self, *, query: str, limit: int, offset: int, automatic: bool = False,
                local_conn: sqlite3.Connection | None = None, run_id: str | None = None, now: Any = None) -> dict[str, Any]:
        normalized = memory_store._query(query)
        if type(limit) is not int or not 1 <= limit <= 50 or type(offset) is not int or not 0 <= offset <= 1000000:
            raise memory_store.MemoryError("limit must be 1–50 and offset must be 0–1000000")
        ranked, errors, total, diagnostics = [], [], 0, []
        needed = offset + limit
        for path in self.discover_sources():
            def read(conn: sqlite3.Connection) -> tuple[list[dict[str, Any]], dict[str, Any]]:
                if automatic:
                    payload = memory_store.recall_memories(
                        conn, query=query, current_run_id=run_id if conn is local_conn else None,
                        automatic=True, limit=3, now=now,
                    )
                    return payload["memories"], payload
                records, position, payload = [], 0, {}
                while position < needed:
                    payload = memory_store.recall_memories(conn, query=query, limit=min(50, needed-position), offset=position, now=now)
                    records.extend(payload["memories"])
                    position += len(payload["memories"])
                    if not payload["memories"] or position >= payload["total"]:
                        break
                return records, payload
            try:
                if local_conn is not None and path == self.local_db_path:
                    records, payload = read(local_conn)
                else:
                    with self._connection(path) as conn:
                        records, payload = read(conn)
                ranked.append((path.name, [_memory(record, path.name) for record in records]))
                total += payload["total"]
                diagnostics.append({**payload["diagnostics"], "source_db": path.name})
            except (sqlite3.Error, OSError, ValueError) as exc:
                errors.append(self._error(path, exc))
        if normalized:
            memories = embeddings.federated_results(ranked, limit=needed, preserve_score=True)
        else:
            # Preserve each database's native ordering for equal timestamps;
            # sorting random memory ids would make a later page reorder page 1.
            ordered = [(record, rank) for _, records in ranked for rank, record in enumerate(records)]
            ordered.sort(key=lambda pair: (-memory_store._time(pair[0]["updated_at"]).timestamp(),
                                          pair[0]["source_db"], pair[1]))
            memories = [record for record, _ in ordered]
        result = {"memories": memories[offset:needed], "total": total, "query": normalized,
                  "limit": limit, "offset": offset, "source_errors": errors,
                  "diagnostics": {"stored_count": sum(entry["stored_count"] for entry in diagnostics),
                                  "matched_count": total, "last_capture_error": next((
                                      {**entry["last_capture_error"], "source_db": entry["source_db"]}
                                      for entry in diagnostics if entry.get("last_capture_error")), None)}}
        if automatic:
            memory_store._budget(result)
        return result
