"""Observed reads and explicit usage for an existing owned RUN.

This is separate from memory reinforcement. HistoryReader and Viewer never call
the writer. Current projection loads three indexed state rows and at most 200
references. Session proof lookup streams original observed events separately;
used-state snapshots can never become proof that a source was opened.
"""
from __future__ import annotations

import heapq
import json
from pathlib import Path
import sqlite3
from typing import Any

from . import db


EVENT_TYPE = "run_references_updated"
USED_EVENT_TYPE = "run_references_used"
MAX_REFERENCES = 200
MAX_USES = 50
TITLE_LIMIT = 160
USAGE_LIMIT = 500
STAGE_RANK = {"retrieved": 0, "opened": 1, "used": 2}


def limits() -> dict[str, int]:
    return {"max_references": MAX_REFERENCES, "title_characters": TITLE_LIMIT, "event_rows_scanned": 3}


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
    if kind not in ("memory", "history") or stage not in ("retrieved", "opened", "used"):
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
    if stage == "used":
        usage = value.get("usage")
        if not isinstance(usage, str) or not 1 <= len(usage.strip()) <= USAGE_LIMIT:
            return None
        result["usage"] = usage.strip()
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
            elif target == "memory":
                # An invalid item pointer must never degrade into RUN-level
                # proof; the stored original is an exact identity.
                return None
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
            if STAGE_RANK[ref["stage"]] > STAGE_RANK[previous["stage"]]:
                merged[key] = ref
        elif len(merged) < MAX_REFERENCES:
            merged[key] = ref
        elif ref["stage"] != "retrieved":
            # Details take precedence over search exposure. Dict order preserves
            # first-seen age; all-opened state evicts its oldest identity.
            eligible = [identity for identity, value in merged.items()
                        if STAGE_RANK[value["stage"]] <= STAGE_RANK[ref["stage"]]]
            if eligible:
                victim = min(eligible, key=lambda identity: STAGE_RANK[merged[identity]["stage"]])
                del merged[victim]
                merged[key] = ref
    return list(merged.values())


def _payload_references(row: Any) -> list[dict[str, Any]]:
    if row is None:
        return []
    try:
        payload = json.loads(row["payload_json"])
        return payload["references"][:MAX_REFERENCES] if isinstance(payload, dict) and isinstance(payload.get("references"), list) else []
    except (ValueError, TypeError, KeyError):
        return []


def _latest(conn: sqlite3.Connection, run_id: str, event_type: str) -> Any:
    return conn.execute("SELECT id,payload_json FROM events WHERE run_id=? AND event_type=? ORDER BY id DESC LIMIT 1",
                        (run_id, event_type)).fetchone()


def _read_observed(conn: sqlite3.Connection, run_id: str | None) -> list[dict[str, Any]]:
    if run_id is None:
        return []
    rows = []
    for event_type in (EVENT_TYPE, "memory_recall_attempted"):
        row = _latest(conn, run_id, event_type)
        if row is not None:
            rows.append((row, event_type))
    refs = []
    for row, event_type in sorted(rows, key=lambda value: value[0]["id"]):
        # Tracking events contain a complete retained observed state. Never
        # recirculate used references, even from malformed historical events.
        observed = [ref for value in _payload_references(row)
                    if (ref := _validated(value)) is not None and ref["stage"] != "used"]
        refs = merge([] if event_type == EVENT_TYPE else refs, observed)
    return refs


def _read_used(conn: sqlite3.Connection, run_id: str) -> list[dict[str, Any]]:
    return merge([], [ref for value in _payload_references(_latest(conn, run_id, USED_EVENT_TYPE))
                      if (ref := _validated(value)) is not None and ref["stage"] == "used"])


def read(conn: sqlite3.Connection, run_id: str | None) -> list[dict[str, Any]]:
    if run_id is None:
        return []
    return merge(_read_observed(conn, run_id), _read_used(conn, run_id))


class ReferenceUseError(ValueError):
    """Invalid usage claims cannot partially change a RUN's projection."""

    def __init__(self, message: str, code: str = "invalid_reference") -> None:
        self.code = code
        super().__init__(f"{code}: {message}")


def validate_use(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ReferenceUseError("reference must be an object")
    kind, target = value.get("kind"), value.get("target_type")
    if kind not in ("memory", "history") or target not in (("memory",) if kind == "memory" else ("item", "run")):
        raise ReferenceUseError("kind and target_type must match memory, history item, or history run")
    identity = {"memory": "memory_id", "item": "item_id", "run": "run_id"}[target]
    if set(value) != {"kind", "source_db", "target_type", identity, "usage"}:
        raise ReferenceUseError("reference requires only kind, source_db, target_type, its matching id, and usage")
    source = value["source_db"]
    if not isinstance(source, str) or not 1 <= len(source) <= 256 or Path(source).name != source or source in (".", "..") or "\\" in source:
        raise ReferenceUseError("source_db must be an exact source database filename")
    target_id = value[identity]
    invalid_id = (type(target_id) is not int or target_id < 1) if target == "item" else (not isinstance(target_id, str) or not 1 <= len(target_id) <= 256)
    if invalid_id:
        raise ReferenceUseError("reference id must match its target_type")
    usage = value["usage"]
    if not isinstance(usage, str) or not 1 <= len(usage.strip()) <= USAGE_LIMIT:
        raise ReferenceUseError("usage must contain 1–500 characters after trimming")
    return {**value, "usage": usage.strip()}


def _read_proofs(conn: sqlite3.Connection, identities: set[tuple]) -> dict[tuple, dict[str, Any]]:
    """A returned memory note plus its opened original proves more than exposure alone."""
    found: dict[tuple, dict[str, Any]] = {}
    if not identities:
        return found
    owner = db.connection_session_id(conn)
    query = (
        "SELECT e.id,e.event_type,e.payload_json FROM events e JOIN workflow_runs r ON r.id=e.run_id "
        "WHERE e.session_id=? AND e.event_type=? AND r.session_id=? "
        "AND NOT EXISTS (SELECT 1 FROM events discarded, "
        "json_each(CASE WHEN json_valid(discarded.payload_json) THEN discarded.payload_json ELSE '{}' END, '$.archived_run_ids') ids "
        "WHERE discarded.session_id=? AND discarded.event_type='run_discarded' AND ids.value=r.id) ORDER BY e.id DESC"
    )
    event_types = (EVENT_TYPE, "memory_recall_attempted") if any(key[0] == "memory" for key in identities) else (EVENT_TYPE,)
    cursors = []
    try:
        for event_type in event_types:
            cursors.append(conn.execute(query, (owner, event_type, owner, owner)))
        # Merge indexed streams without sorting/materializing the session's payloads.
        for row in heapq.merge(*cursors, key=lambda entry: entry["id"], reverse=True):
            for value in _payload_references(row):
                ref = _validated(value)
                if ref is None:
                    continue
                eligible = ref["stage"] == "opened" or (ref["kind"] == "memory" and ref["stage"] == "retrieved")
                if row["event_type"] == "memory_recall_attempted":
                    eligible = ref["kind"] == "memory" and ref["stage"] == "retrieved"
                key = _key(ref)
                if eligible and key in identities and key not in found:
                    found[key] = ref
            if identities <= found.keys():
                break
    finally:
        for cursor in cursors:
            cursor.close()
    return found


def use(conn: sqlite3.Connection, *, expected_run_id: str, references: Any) -> dict[str, Any]:
    """Validate a whole batch under the caller's local write transaction."""
    if not conn.in_transaction:
        raise ReferenceUseError("reference usage requires a local write transaction")
    owner = db.connection_session_id(conn)
    run = db.active_run(conn)
    if not owner:
        raise ReferenceUseError("session_id is required for exact conversation reference usage", "session_required")
    if run is None or run["id"] != expected_run_id or run["session_id"] != owner:
        raise ReferenceUseError("expected_run_id must match the active owned run", "stale_run")
    if not isinstance(references, list) or not 1 <= len(references) <= MAX_USES:
        raise ReferenceUseError("references must contain 1–50 entries")
    claims = [validate_use(value) for value in references]
    proofs = _read_proofs(conn, {_key(claim) for claim in claims})
    source_keys: dict[tuple, tuple] = {}
    for claim in claims:
        key = _key(claim)
        proof = proofs.get(key)
        if proof is None:
            raise ReferenceUseError("reference has no qualifying read in this exact session", "invalid_proof")
        if claim["kind"] == "memory":
            source = proof.get("source")
            if not source:
                raise ReferenceUseError("memory has no observed original-source pointer", "invalid_proof")
            item_id = source.get("item_id")
            source_keys[key] = ("history", source["source_db"], "item" if item_id else "run", item_id or source["run_id"])
    originals = _read_proofs(conn, set(source_keys.values()))
    for key, source_key in source_keys.items():
        original = originals.get(source_key)
        if original is None or original["run_id"] != proofs[key]["source"]["run_id"]:
            raise ReferenceUseError("memory's exact original source was not opened in this session", "invalid_proof")
    previous = _read_used(conn, expected_run_id)
    current = {_key(ref): ref for ref in previous}
    outcomes = []
    for index, claim in enumerate(claims):
        key = _key(claim)
        selected = [proofs[key]]
        if key in source_keys:
            selected.append(originals[source_keys[key]])
        changed = False
        for ref in selected:
            identity = _key(ref)
            if identity not in current:
                current[identity] = {**ref, "stage": "used", "usage": claim["usage"]}
                changed = True
        outcomes.append({"index": index, "status": "recorded" if changed else "unchanged"})
    if len(current) > MAX_REFERENCES:
        raise ReferenceUseError(
            f"used_count={len(previous)}, proposed_count={len(current)}, limit={MAX_REFERENCES}; "
            "distinct used references include memory originals", "reference_limit")
    retained = list(current.values())
    if retained != previous:
        conn.execute("INSERT INTO events(run_id,session_id,event_type,tool_name,payload_json,created_at) VALUES(?,?,?,?,?,?)",
                     (expected_run_id, owner, USED_EVENT_TYPE, "use_references", json.dumps({"references": retained}, ensure_ascii=False), db.utc_now()))
    return {"ok": True, "run_id": expected_run_id, "outcomes": outcomes,
            "counts": {status: sum(outcome["status"] == status for outcome in outcomes) for status in ("recorded", "unchanged")}}


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
        previous = _read_observed(conn, run_id)
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
