"""Compact, best-effort exposure telemetry for an existing owned RUN.

This is separate from memory reinforcement. HistoryReader and Viewer never call
the writer. One bounded state event makes reads independent of workflow history
length: at most two indexed event rows and 200 references are loaded.
"""
from __future__ import annotations

import json
from pathlib import Path
import sqlite3
from typing import Any

from . import db


EVENT_TYPE = "run_references_updated"
MAX_REFERENCES = 200
TITLE_LIMIT = 160


def limits() -> dict[str, int]:
    return {"max_references": MAX_REFERENCES, "title_characters": TITLE_LIMIT, "event_rows_scanned": 2}


def _title(value: Any) -> str:
    return " ".join(str(value or "").split())[:TITLE_LIMIT]


def history_reference(record: dict[str, Any], stage: str, *, target_type: str = "item") -> dict[str, Any] | None:
    source_db, run_id = record.get("source_db"), record.get("run_id")
    if target_type == "run":
        run_id = run_id or record.get("id")
    if not isinstance(source_db, str) or not isinstance(run_id, str) or not run_id:
        return None
    ref = {"kind": "history", "stage": stage, "source_db": source_db,
           "target_type": target_type, "run_id": run_id,
           "title": _title(record.get("title") or record.get("request_summary") or record.get("slug"))}
    if target_type == "item":
        if type(record.get("id")) is not int:
            return None
        ref["item_id"] = record["id"]
        for key, origin in (("stable_id", "stable_id"), ("record_kind", "kind")):
            if isinstance(record.get(origin), str):
                ref[key] = record[origin][:256]
    return ref


def memory_reference(memory: dict[str, Any], stage: str, *, source_db: str | None = None) -> dict[str, Any] | None:
    source = memory.get("source") or {}
    selected = memory.get("source_db") or source.get("source_db") or source_db
    if not isinstance(selected, str) or not isinstance(source.get("run_id"), str) or not isinstance(memory.get("id"), str):
        return None
    pointer = {"source_db": selected, "run_id": source["run_id"]}
    for key in ("item_id", "archive_id"):
        value = source.get(key)
        if value is None or (key == "item_id" and type(value) is int) or (key == "archive_id" and isinstance(value, str)):
            pointer[key] = value
    return {"kind": "memory", "stage": stage, "source_db": selected,
            "target_type": "memory", "run_id": source["run_id"], "memory_id": memory["id"],
            "title": _title(memory.get("note") or source.get("title")), "source": pointer}


def from_result(operation: str, result: dict[str, Any]) -> list[dict[str, Any]]:
    """Use only records actually returned; detail containers never expand children."""
    refs = []
    if operation in ("search_history", "list_records"):
        refs = [history_reference(record, "retrieved") for record in result.get(
            "results" if operation == "search_history" else "records", [])[:MAX_REFERENCES]]
    elif operation == "recall":
        refs = [memory_reference(record, "retrieved") for record in result.get("memories", [])[:MAX_REFERENCES]]
    elif operation == "get_memory" and result.get("memory"):
        memory = result["memory"]
        refs = [memory_reference(memory, "opened")]
        original = memory.get("source_record") or {}
        if original.get("kind") == "item" and original.get("item"):
            refs.append(history_reference(original["item"], "opened"))
        elif original.get("kind") == "run" and original.get("run"):
            refs.append(history_reference(original["run"], "opened", target_type="run"))
    elif operation == "get_item" and result.get("item"):
        refs = [history_reference(result["item"], "opened")]
    elif operation == "get_run" and result.get("run"):
        refs = [history_reference(result["run"], "opened", target_type="run")]
    elif operation == "get_archive" and result.get("archive"):
        refs = [history_reference(result["archive"], "opened", target_type="run")]
    return [ref for ref in refs if ref is not None]


def _key(ref: dict[str, Any]) -> tuple:
    return (ref["kind"], ref["source_db"], ref["target_type"],
            ref.get("memory_id") if ref["target_type"] == "memory" else
            ref.get("item_id") if ref["target_type"] == "item" else ref["run_id"])


def _validated(value: Any) -> dict[str, Any] | None:
    """Ignore malformed historical telemetry and retain only contract fields."""
    if not isinstance(value, dict):
        return None
    kind, stage, target = value.get("kind"), value.get("stage"), value.get("target_type")
    if kind not in ("memory", "history") or stage not in ("retrieved", "opened"):
        return None
    if target not in (("memory",) if kind == "memory" else ("item", "run")):
        return None
    if any(not isinstance(value.get(key), str) or not value[key] or len(value[key]) > 256
           for key in ("source_db", "run_id")):
        return None
    if Path(value["source_db"]).name != value["source_db"]:
        return None
    result = {key: value[key] for key in ("kind", "stage", "target_type", "source_db", "run_id")}
    if not isinstance(value.get("title"), str):
        return None
    result["title"] = _title(value["title"])
    if target == "memory":
        if not isinstance(value.get("memory_id"), str) or not 1 <= len(value["memory_id"]) <= 256:
            return None
        result["memory_id"] = value["memory_id"]
    elif target == "item":
        if type(value.get("item_id")) is not int or value["item_id"] < 1:
            return None
        result["item_id"] = value["item_id"]
    for key in ("stable_id", "record_kind"):
        if isinstance(value.get(key), str):
            result[key] = value[key][:256]
    source = value.get("source")
    if isinstance(source, dict) and source.get("source_db") == result["source_db"] and source.get("run_id") == result["run_id"]:
        result["source"] = {key: source[key] for key in ("source_db", "run_id")}
        for key in ("item_id", "archive_id"):
            pointer = source.get(key)
            if pointer is None or (key == "item_id" and type(pointer) is int and pointer > 0) or (key == "archive_id" and isinstance(pointer, str) and len(pointer) <= 256):
                result["source"][key] = pointer
    return result


def merge(existing: list[dict[str, Any]], incoming: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged = {_key(ref): ref for value in existing[:MAX_REFERENCES] if (ref := _validated(value)) is not None}
    for value in incoming[:MAX_REFERENCES]:
        ref = _validated(value)
        if ref is None:
            continue
        key = _key(ref)
        previous = merged.get(key)
        if previous is not None:
            if previous["stage"] != "opened" and ref["stage"] == "opened":
                merged[key] = ref
        elif len(merged) < MAX_REFERENCES:
            merged[key] = ref
        elif ref["stage"] == "opened":
            # Details take precedence over search exposure. Dict order preserves
            # first-seen age; all-opened state evicts its oldest identity.
            victim = next((identity for identity, value in merged.items() if value["stage"] == "retrieved"),
                          next(iter(merged)))
            del merged[victim]
            merged[key] = ref
    return list(merged.values())


def read(conn: sqlite3.Connection, run_id: str | None) -> list[dict[str, Any]]:
    if run_id is None:
        return []
    rows = []
    for event_type in (EVENT_TYPE, "memory_recall_attempted"):
        row = conn.execute("SELECT id,payload_json FROM events WHERE run_id=? AND event_type=? ORDER BY id DESC LIMIT 1",
                           (run_id, event_type)).fetchone()
        if row is not None:
            rows.append((row, event_type))
    refs = []
    for row, event_type in sorted(rows, key=lambda value: value[0]["id"]):
        try:
            payload = json.loads(row["payload_json"])
            if not isinstance(payload, dict) or not isinstance(payload.get("references"), list):
                continue
            # Tracking events contain a complete retained state; older automatic
            # entries must not resurrect an identity evicted from that state.
            refs = merge([] if event_type == EVENT_TYPE else refs, payload["references"])
        except (ValueError, TypeError, KeyError):
            continue
    return refs


def capture(application: Any) -> tuple[Path, str, str] | None:
    """Resolve only an existing local identity; never use the creating db_path."""
    try:
        reader = application._history()
        path = reader.local_db_path
        if path is None or path not in reader.discover_sources():
            return None
        with reader._connection(path) as conn:
            run = db.active_run(conn)
            if run is not None:
                return path, str(run["id"]), db.connection_session_id(conn)
    except (sqlite3.Error, OSError, ValueError):
        pass
    return None


def record(captured: tuple[Path, str, str] | None, operation: str, result: dict[str, Any]) -> None:
    if captured is None or result.get("ok") is False:
        return
    path, run_id, owner = captured
    conn = None
    try:
        refs = [ref for ref in from_result(operation, result)
                if (ref["source_db"], ref["run_id"]) != (path.name, run_id)]
        if not refs or path.is_symlink() or path.parent.is_symlink() or not path.is_file():
            return
        # mode=rw cannot create a missing DB; no migrations or journal changes.
        conn = sqlite3.connect(path.as_uri() + "?mode=rw", uri=True, timeout=0.05, factory=db.WorkflowConnection)
        conn.row_factory = sqlite3.Row
        conn.tapl_session_id = owner
        conn.execute("BEGIN IMMEDIATE")
        run = db.active_run(conn)
        if run is None or str(run["id"]) != run_id or str(run["session_id"]) != owner:
            return
        previous = read(conn, run_id)
        current = merge(previous, refs)
        if previous == current:
            return
        conn.execute("INSERT INTO events(run_id,session_id,event_type,tool_name,payload_json,created_at) VALUES(?,?,?,?,?,?)",
                     (run_id, owner, EVENT_TYPE, operation, json.dumps({"references": current}, ensure_ascii=False), db.utc_now()))
        conn.commit()
    except (sqlite3.Error, OSError, ValueError, TypeError, KeyError):
        # Read success must survive unavailable local telemetry.
        pass
    finally:
        if conn is not None:
            conn.close()
