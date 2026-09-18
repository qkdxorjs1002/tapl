"""Small, deterministic associative memory storage; no model or search daemon."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import math
import re
import sqlite3
import unicodedata
import uuid

from . import db, memory_search


class MemoryError(ValueError):
    def __init__(self, message: str, code: str = "invalid"):
        super().__init__(message)
        self.code = code


def _time(now=None):
    value = now if now is not None else datetime.now(timezone.utc)
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise MemoryError("now must be an ISO timestamp") from exc
    if not isinstance(value, datetime):
        raise MemoryError("now must be a datetime or ISO timestamp")
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _stamp(now):
    return now.isoformat()


@contextmanager
def _transaction(conn, *, write=False):
    if conn.in_transaction:
        savepoint = "memory_" + uuid.uuid4().hex
        conn.execute("SAVEPOINT " + savepoint)
        try:
            yield
            conn.execute("RELEASE " + savepoint)
        except BaseException:
            conn.execute("ROLLBACK TO " + savepoint)
            conn.execute("RELEASE " + savepoint)
            raise
        return
    conn.execute("BEGIN IMMEDIATE" if write else "BEGIN")
    try:
        yield
        conn.commit()
    except BaseException:
        conn.rollback()
        raise


def _normal(text):
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def _hash(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def _content(note, cue):
    if not isinstance(note, str) or not note.strip() or len(note.strip()) > 240:
        raise MemoryError("note must contain 1–240 characters")
    note = note.strip()
    if not isinstance(cue, list) or not 3 <= len(cue) <= 5:
        raise MemoryError("cue must contain 3–5 strings")
    if any(not isinstance(c, str) or not c.strip() or len(c.strip()) > 80 for c in cue):
        raise MemoryError("each cue must contain 1–80 characters")
    cue = [c.strip() for c in cue]
    if len({_normal(c) for c in cue}) != len(cue):
        raise MemoryError("cue strings must be distinct")
    return note, cue, _hash([_normal(note), sorted(_normal(c) for c in cue)])


def _run(conn, run_id):
    if not isinstance(run_id, str) or not run_id:
        raise MemoryError("run_id must be a nonempty string")
    row = conn.execute("SELECT * FROM workflow_runs WHERE id=?", (run_id,)).fetchone()
    if row is None:
        raise MemoryError("source or current run does not exist", "not_found")
    return row


def _current_run(conn, run_id):
    row = _run(conn, run_id)
    if row["status"] != "active":
        raise MemoryError("current run changed or was archived", "conflict")
    return row


def _source(conn, run_id, item_id):
    run = _run(conn, run_id)
    item = None
    if item_id is not None:
        if type(item_id) is not int or item_id <= 0:
            raise MemoryError("source_item_id must be a positive integer")
        item = conn.execute("SELECT * FROM items WHERE id=? AND run_id=?", (item_id, run_id)).fetchone()
        if item is None:
            raise MemoryError("source item does not belong to the source run", "not_found")
    elif not run["result_summary"].strip():
        raise MemoryError("run-only source requires an existing result_summary")
    return run, item


def _row(conn, memory_id):
    if not isinstance(memory_id, str) or not memory_id:
        raise MemoryError("memory_id must be a nonempty string")
    row = conn.execute("SELECT * FROM memories WHERE memory_id=? AND state!='deleted'", (memory_id,)).fetchone()
    if row is None:
        raise MemoryError("memory does not exist", "not_found")
    return row


def _revision(row, revision):
    if type(revision) is not int or revision < 1:
        raise MemoryError("expected revision must be a positive integer")
    if row["revision"] != revision:
        raise MemoryError("memory revision changed", "conflict")


def _event(conn, run_id, event_type, payload, now):
    conn.execute("INSERT INTO events(run_id,event_type,payload_json,created_at) VALUES(?,?,?,?)",
                 (run_id, event_type, json.dumps(payload, ensure_ascii=False), _stamp(now)))


def _dto(conn, row, now, *, matched=None, original=False):
    run = conn.execute("SELECT * FROM workflow_runs WHERE id=?", (row["source_run_id"],)).fetchone()
    item = conn.execute("SELECT * FROM items WHERE id=? AND run_id=?", (row["source_item_id"], row["source_run_id"])).fetchone() if row["source_item_id"] else None
    archive = conn.execute("SELECT id FROM archives WHERE run_id=? ORDER BY created_at DESC,id LIMIT 1", (row["source_run_id"],)).fetchone()
    age = max(0., (now - _time(row["last_reinforced_at"] or row["content_updated_at"])).total_seconds() / 86400)
    result = {
        "id": row["memory_id"], "note": row["note"], "cue": json.loads(row["cues_json"]),
        "state": row["state"], "revision": row["revision"],
        "source": {"run_id": row["source_run_id"], "item_id": row["source_item_id"],
                   "archive_id": archive["id"] if archive else None,
                   "title": item["title"] if item else (run["request_summary"] or run["slug"] if run else ""),
                   "kind": "item" if row["source_item_id"] else "run"},
        "created_at": row["created_at"], "updated_at": row["content_updated_at"],
        "last_reinforced_at": row["last_reinforced_at"], "half_life_days": row["half_life_days"],
        "strength": math.pow(2, -age / row["half_life_days"]), "matched_cues": matched or [],
        "source_available": bool(run is not None and (item is not None if row["source_item_id"] else run["result_summary"].strip())),
    }
    if original:
        result["source_record"] = {"kind": result["source"]["kind"], "item": db.row_to_dict(item), "run": db.workflow_run_to_dict(run)}
    return result


def _query(query):
    if not isinstance(query, str) or len(query) > 2000:
        raise MemoryError("query must be a string of at most 2000 characters")
    return " ".join(re.findall(r"[\w가-힣]+", _normal(query), flags=re.UNICODE)[:8])


_STOP = {"the", "and", "for", "with", "this", "that", "from", "into", "are", "was", "is", "to", "of", "in", "on", "a", "an", "및", "또는", "대한", "위한", "있는", "합니다"}


def _matches(row, query, spacing_aliases, spacing_phrases):
    cues = json.loads(row["cues_json"])
    query_tokens = query.split()
    meaningful = {t for t in query_tokens if len(t) > 1 and t not in _STOP}
    matched = [c for c in cues if (" " + _query(c) + " ") in (" " + query + " ")
               or (spacing_aliases & memory_search.korean_aliases(c)
                   and memory_search.spacing_key(c) in spacing_phrases)]
    content_tokens = set(re.findall(r"[\w가-힣]+", _normal(row["note"] + " " + " ".join(cues))))
    # A joined query can stand for two original cue words, but a single long
    # word (e.g. 트랜잭션) must not bypass the existing two-word approval gate.
    spaced_words = any(alias in spacing_aliases and len({w for w in words if len(w) > 1 and w not in _STOP}) >= 2
                       for cue in cues for alias, words in memory_search.joined_word_spans(cue))
    return matched, bool(matched or len(meaningful & content_tokens) >= 2 or spaced_words)


def _fts_queries(query, spacing_aliases):
    queries = db.build_fts_queries(query)
    if not queries or not spacing_aliases:
        return queries
    aliases = " OR ".join(f'"{alias}"' for alias in sorted(spacing_aliases))
    # Exact aliases precede prefix/OR fallbacks so broad hits cannot exhaust the
    # automatic candidate budget first. Manual pagination uses the final union.
    exact_count = 2 if len(query.split()) > 1 else 1
    expanded = [*queries[:exact_count], aliases, *queries[exact_count:-1],
                f"({queries[-1]}) OR ({aliases})"]
    return list(dict.fromkeys(expanded))


def _recall(conn, *, query, current_run_id, automatic, limit, offset, now):
    bounded_query = _query(query)
    spacing_aliases = memory_search.korean_aliases(query)
    spacing_phrases = memory_search.query_phrases(query) if spacing_aliases else set()
    if type(limit) is not int or not 1 <= limit <= 50 or type(offset) is not int or offset < 0 or offset > 1000000:
        raise MemoryError("limit must be 1–50 and offset must be 0–1000000")
    if automatic:
        limit, offset = min(limit, 3), 0
    where = ["m.state='active'" if automatic else "m.state!='deleted'",
             "EXISTS(SELECT 1 FROM workflow_runs r WHERE r.id=m.source_run_id AND (m.source_item_id IS NOT NULL OR length(trim(r.result_summary))>0))",
             "(m.source_item_id IS NULL OR EXISTS(SELECT 1 FROM items i WHERE i.id=m.source_item_id AND i.run_id=m.source_run_id))"]
    params = []
    if automatic and current_run_id is not None:
        where.append("m.created_run_id!=?")
        params.append(current_run_id)
    clause = " AND ".join(where)
    ranked = []
    total = 0
    if bounded_query:
        # Each fallback is bounded before materialization; OR never scans Python-side history.
        queries = _fts_queries(bounded_query, spacing_aliases)
        seen = set()
        for priority, fts_query in enumerate(queries):
            sql = "FROM memory_fts JOIN memories m ON m.id=memory_fts.rowid WHERE memory_fts MATCH ? AND " + clause
            if not automatic:
                # Manual results use the broadest safe FTS query for stable count/pagination.
                if priority != len(queries) - 1:
                    continue
                total = conn.execute("SELECT count(*) " + sql, [fts_query, *params]).fetchone()[0]
            rows = conn.execute("SELECT m.*,bm25(memory_fts) AS relevance " + sql + " ORDER BY relevance,m.id LIMIT ? OFFSET ?",
                                [fts_query, *params, 24 - len(seen) if automatic else limit, 0 if automatic else offset]).fetchall()
            for row in rows:
                if row["id"] in seen:
                    continue
                seen.add(row["id"])
                matched, accepted = _matches(row, bounded_query, spacing_aliases, spacing_phrases)
                if automatic and not accepted:
                    continue
                memory = _dto(conn, row, now, matched=matched)
                ranked.append((priority, row["relevance"], -memory["strength"], memory))
            if automatic and len(seen) >= 24:
                break
        ranked.sort(key=lambda entry: entry[:3])
        memories = [entry[3] for entry in ranked[:limit]]
        if automatic:
            total = len(ranked)
    elif automatic:
        memories = []
    else:
        total = conn.execute("SELECT count(*) FROM memories m WHERE " + clause, params).fetchone()[0]
        rows = conn.execute("SELECT m.* FROM memories m WHERE " + clause + " ORDER BY m.content_updated_at DESC,m.id DESC LIMIT ? OFFSET ?", [*params, limit, offset]).fetchall()
        memories = [_dto(conn, row, now) for row in rows]
    result = {"memories": memories, "total": total, "query": bounded_query, "offset": offset, "limit": limit,
              "diagnostics": diagnostics(conn, matched_count=total)}
    if automatic:
        # Injection needs a hint and its original pointer, not Viewer metadata.
        result["memories"] = [
            {"id": m["id"], "revision": m["revision"], "note": m["note"],
             "matched_cues": m["matched_cues"],
             "source": {key: value for key, value in m["source"].items() if key != "title"}}
            for m in memories
        ]
        _budget(result)
    return result


def _budget(payload):
    # Budget the entire UTF-8 response, preserving each included source pointer.
    candidates, payload["memories"] = payload["memories"], []
    # Keep full errors on manual reads; automatic hints prioritize original pointers.
    if "diagnostics" in payload:
        payload["diagnostics"].pop("last_capture_error", None)
        payload["diagnostics"]["injected_count"] = 0
    if len(json.dumps(payload, ensure_ascii=False).encode("utf-8")) > 1200:
        payload["query"] = ""
    for memory in candidates:
        payload["memories"].append(memory)
        if len(json.dumps(payload, ensure_ascii=False).encode("utf-8")) > 1200:
            payload["memories"].pop()
    if "diagnostics" in payload:
        payload["diagnostics"]["injected_count"] = len(payload["memories"])


def recall_memories(conn, *, query="", current_run_id=None, automatic=False, limit=3, offset=0, now=None):
    with _transaction(conn):
        return _recall(conn, query=query, current_run_id=current_run_id, automatic=automatic, limit=limit, offset=offset, now=_time(now))


def emit_recall_once(conn, *, run_id, query, now=None):
    now = _time(now)
    with _transaction(conn, write=True):
        _current_run(conn, run_id)
        if conn.execute("SELECT 1 FROM events WHERE run_id=? AND event_type='memory_recall_attempted'", (run_id,)).fetchone():
            return {"status": "already_attempted", "memories": []}
        result = _recall(conn, query=query, current_run_id=run_id, automatic=True, limit=3, offset=0, now=now)
        result["status"] = "recalled" if result["memories"] else "empty"
        _budget(result)
        if not result["memories"]:
            result["status"] = "empty"
        _event(conn, run_id, "memory_recall_attempted", {"memory_ids": [m["id"] for m in result["memories"]]}, now)
        return result


def get_memory(conn, memory_id, *, now=None):
    with _transaction(conn):
        return _dto(conn, _row(conn, memory_id), _time(now), original=True)


def _fingerprint_exists(conn, fingerprint, *, exclude=None):
    row = conn.execute("SELECT memory_id FROM memories WHERE fingerprint=? AND (? IS NULL OR memory_id!=?) LIMIT 1", (fingerprint, exclude, exclude)).fetchone()
    if row:
        return row["memory_id"]
    row = conn.execute("SELECT json_extract(payload_json,'$.memory_id') AS memory_id FROM events WHERE event_type IN ('memory_capture','memory_deleted','memory_updated') AND json_extract(payload_json,'$.fingerprint')=? AND (? IS NULL OR json_extract(payload_json,'$.memory_id')!=?) LIMIT 1", (fingerprint, exclude, exclude)).fetchone()
    return row["memory_id"] if row else None


def _index(conn, row_id, cue, note):
    conn.execute("DELETE FROM memory_fts WHERE rowid=?", (row_id,))
    conn.execute("INSERT INTO memory_fts(rowid,cue,note) VALUES(?,?,?)", (row_id, memory_search.indexed_cues(cue), note))


def update_memory(conn, memory_id, *, expected_revision, note=None, cue=None, state=None, now=None):
    now = _time(now)
    with _transaction(conn, write=True):
        row = _row(conn, memory_id)
        _revision(row, expected_revision)
        if state is not None and state not in ("active", "superseded"):
            raise MemoryError("state must be active or superseded; use delete_memory to delete")
        note, cue, fingerprint = _content(row["note"] if note is None else note, json.loads(row["cues_json"]) if cue is None else cue)
        if _fingerprint_exists(conn, fingerprint, exclude=memory_id):
            raise MemoryError("content duplicates an existing or deleted memory", "conflict")
        conn.execute("UPDATE memories SET note=?,cues_json=?,fingerprint=?,state=?,revision=revision+1,content_updated_at=?,half_life_days=7,last_reinforced_at=NULL WHERE id=?",
                     (note, json.dumps(cue, ensure_ascii=False), fingerprint, state or row["state"], _stamp(now), row["id"]))
        _index(conn, row["id"], cue, note)
        _event(conn, row["created_run_id"], "memory_updated", {"memory_id": memory_id, "fingerprint": fingerprint}, now)
        return _dto(conn, _row(conn, memory_id), now)


def delete_memory(conn, memory_id, *, expected_revision, now=None):
    now = _time(now)
    with _transaction(conn, write=True):
        row = _row(conn, memory_id)
        _revision(row, expected_revision)
        conn.execute("UPDATE memories SET note='',cues_json='[]',state='deleted',revision=revision+1,content_updated_at=? WHERE id=?", (_stamp(now), row["id"]))
        conn.execute("DELETE FROM memory_fts WHERE rowid=?", (row["id"],))
        _event(conn, row["created_run_id"], "memory_deleted", {"memory_id": memory_id, "fingerprint": row["fingerprint"]}, now)
        return {"id": memory_id, "state": "deleted", "revision": row["revision"] + 1}


def _capture(conn, run_id, candidate, now):
    if not isinstance(candidate, dict):
        raise MemoryError("candidate must be an object")
    if type(candidate.get("slot")) is not int or candidate["slot"] not in (1, 2):
        raise MemoryError("candidate slot must be 1 or 2")
    note, cue, fingerprint = _content(candidate.get("note"), candidate.get("cue"))
    source_run_id, source_item_id = candidate.get("source_run_id"), candidate.get("source_item_id")
    replaces = candidate.get("replaces_memory_id")
    if replaces is not None and (not isinstance(replaces, str) or not replaces):
        raise MemoryError("replaces_memory_id must be a nonempty string")
    payload_hash = _hash([fingerprint, source_run_id, source_item_id, replaces])
    with _transaction(conn, write=True):
        _current_run(conn, run_id)
        receipt = conn.execute("SELECT payload_json FROM events WHERE event_type='memory_capture' AND run_id=? AND json_extract(payload_json,'$.slot')=?", (run_id, candidate["slot"])).fetchone()
        if receipt:
            data = json.loads(receipt["payload_json"])
            if data["payload_hash"] != payload_hash:
                raise MemoryError("capture slot already has different content", "conflict")
            return {"slot": candidate["slot"], "memory_id": data["memory_id"], "status": "already_captured"}
        _source(conn, source_run_id, source_item_id)
        existing = _fingerprint_exists(conn, fingerprint)
        memory_id = existing or str(uuid.uuid4())
        if existing is None:
            previous = _row(conn, replaces) if replaces else None
            if previous is not None and previous["state"] != "active":
                raise MemoryError("replacement target must be active", "conflict")
            cursor = conn.execute("INSERT INTO memories(memory_id,created_run_id,slot,source_run_id,source_item_id,cues_json,note,fingerprint,replaces_memory_id,created_at,content_updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                                 (memory_id, run_id, candidate["slot"], source_run_id, source_item_id, json.dumps(cue, ensure_ascii=False), note, fingerprint, replaces, _stamp(now), _stamp(now)))
            _index(conn, cursor.lastrowid, cue, note)
            if previous is not None:
                conn.execute("UPDATE memories SET state='superseded',revision=revision+1 WHERE id=?", (previous["id"],))
        _event(conn, run_id, "memory_capture", {"created_run_id": run_id, "slot": candidate["slot"], "memory_id": memory_id, "fingerprint": fingerprint, "payload_hash": payload_hash}, now)
        return {"slot": candidate["slot"], "memory_id": memory_id, "status": "deduplicated" if existing else "captured"}


def _reinforce(conn, run_id, use, now):
    if not isinstance(use, dict):
        raise MemoryError("use must be an object")
    if use.get("source_checked") is not True or not isinstance(use.get("usage"), str) or not use["usage"].strip():
        raise MemoryError("reinforcement requires source_checked=true and actual usage")
    if len(use["usage"]) > 2000:
        raise MemoryError("usage must be at most 2000 characters")
    with _transaction(conn, write=True):
        _current_run(conn, run_id)
        row = _row(conn, use.get("memory_id"))
        _revision(row, use.get("revision"))
        _source(conn, row["source_run_id"], row["source_item_id"])
        if row["state"] != "active":
            raise MemoryError("only active memories may be reinforced", "conflict")
        if run_id in (row["created_run_id"], row["last_reinforced_run_id"]):
            return {"memory_id": row["memory_id"], "status": "skipped", "reason": "same_run"}
        baseline = max(_time(row["content_updated_at"]), _time(row["last_reinforced_at"] or row["content_updated_at"]))
        if (now - baseline).total_seconds() < 86400:
            return {"memory_id": row["memory_id"], "status": "skipped", "reason": "cooldown"}
        half_life = min(90., row["half_life_days"] * 2)
        conn.execute("UPDATE memories SET half_life_days=?,last_reinforced_at=?,last_reinforced_run_id=? WHERE id=?", (half_life, _stamp(now), run_id, row["id"]))
        _event(conn, run_id, "memory_reinforced", {"memory_id": row["memory_id"], "revision": row["revision"]}, now)
        return {"memory_id": row["memory_id"], "status": "reinforced", "half_life_days": half_life}


def validate_review(review, candidates=None):
    if review is None:
        return None
    if not isinstance(review, dict) or set(review) - {"decision", "reason"}:
        raise MemoryError("memory_review must contain decision and optional reason")
    decision, reason = review.get("decision"), review.get("reason")
    if decision not in ("capture", "skip"):
        raise MemoryError("memory_review.decision must be capture or skip")
    if reason is not None and (not isinstance(reason, str) or not reason.strip() or len(reason.strip()) > 240):
        raise MemoryError("memory_review.reason must contain 1–240 characters")
    if decision == "skip" and not reason:
        raise MemoryError("memory_review.skip requires a concise reason")
    if decision == "skip" and candidates:
        raise MemoryError("memory_candidates contradict memory_review.skip")
    return {"decision": decision, **({"reason": reason.strip()} if reason else {})}


def review_state(conn, run_id):
    """Latest compact lifecycle checkpoint; legacy runs need no inferred review."""
    row = conn.execute("SELECT payload_json FROM events WHERE run_id=? AND event_type='memory_review' ORDER BY id DESC LIMIT 1", (run_id,)).fetchone()
    state = json.loads(row[0]) if row else {"status": "not_started", "decision": None, "pending_errors": []}
    state["capture_count"] = conn.execute("SELECT count(*) FROM events WHERE run_id=? AND event_type='memory_capture'", (run_id,)).fetchone()[0]
    return state


def require_review(conn, run_id, *, candidates=None, uses=None, now=None):
    """Call in the same transaction as the result, closing the archive race."""
    state = review_state(conn, run_id)
    state["attempt_token"] = uuid.uuid4().hex
    state["attempt_operations"] = []
    for kind, entries, maximum in (("candidate", candidates, 2), ("use", uses, 50)):
        if entries is None:
            continue
        entries = entries if isinstance(entries, list) and len(entries) <= maximum else [None]
        for index, entry in enumerate(entries):
            identity = _identity(kind, entry, index)
            state["attempt_operations"].append(identity)
            if not any(all(e.get(k) == v for k, v in identity.items()) for e in state["pending_errors"]):
                state["pending_errors"].append({**identity, "code": "processing_pending",
                    "message": "Submitted memory operation has not completed; retry it or skip with a reason.", "attempts": 0})
    state["status"] = "review_required"
    _event(conn, run_id, "memory_review", state, _time(now))
    return state


def diagnostics(conn, *, matched_count=0):
    """Stored means nondeleted and source-available, irrespective of search/state."""
    count = conn.execute("""SELECT count(*) FROM memories m WHERE m.state!='deleted'
        AND EXISTS(SELECT 1 FROM workflow_runs r WHERE r.id=m.source_run_id AND
          (m.source_item_id IS NOT NULL OR length(trim(r.result_summary))>0))
        AND (m.source_item_id IS NULL OR EXISTS(SELECT 1 FROM items i
          WHERE i.id=m.source_item_id AND i.run_id=m.source_run_id))""").fetchone()[0]
    row = conn.execute("SELECT run_id,payload_json,created_at FROM events WHERE event_type='memory_finish_error' AND json_extract(payload_json,'$.kind') IN ('candidate','internal') ORDER BY id DESC LIMIT 1").fetchone()
    error = None
    if row:
        data = json.loads(row["payload_json"])
        error = {"run_id": row["run_id"], "code": data["code"], "message": data["message"], "created_at": row["created_at"]}
        if "slot" in data:
            error["slot"] = data["slot"]
    return {"stored_count": count, "matched_count": matched_count, "last_capture_error": error}


def record_internal_failure(conn, run_id, *, expected_token=None, now=None):
    # Never persist raw exception text: database/SDK exceptions can contain secrets.
    with _transaction(conn, write=True):
        _current_run(conn, run_id)
        state = review_state(conn, run_id)
        if expected_token is not None and state.get("attempt_token") != expected_token:
            raise MemoryError("Memory finish was superseded; inspect current review before retrying.", "stale_attempt")
        operations = state.get("attempt_operations") or [{"kind": "internal"}]
        pending = list(state["pending_errors"])
        if not state.get("attempt_operations") and not any(e["kind"] == "internal" for e in pending):
            pending.append({"kind": "internal", "attempts": 0})
        state["pending_errors"] = []
        for entry in pending:
            if not any(all(entry.get(k) == v for k, v in identity.items()) for identity in operations):
                state["pending_errors"].append(entry)
                continue
            error = {**entry, "code": "memory_unavailable",
                     "message": "Memory processing failed; retry the same operation once or skip with a reason.",
                     "attempts": min(entry.get("attempts", 0) + 1, 2)}
            state["pending_errors"].append(error)
            _event(conn, run_id, "memory_finish_error", error, _time(now))
        state["status"] = "partial" if state["capture_count"] or state.get("had_success") else "failed"
        _event(conn, run_id, "memory_review", state, _time(now))
        return state


def _identity(kind, entry, index):
    identity = {"kind": kind}
    if isinstance(entry, dict) and kind == "candidate" and type(entry.get("slot")) is int and entry["slot"] in (1, 2):
        identity["slot"] = entry["slot"]
    elif isinstance(entry, dict) and kind == "use" and isinstance(entry.get("memory_id"), str) and len(entry["memory_id"]) <= 100:
        identity["memory_id"] = entry["memory_id"]
    else:
        identity["index"] = index
    return identity


def finish_memories(conn, *, run_id, candidates=None, uses=None, review=None, expected_token=None, now=None):
    now = _time(now)
    review = validate_review(review, candidates)
    result = {"captures": [], "reinforcements": [], "errors": []}
    with _transaction(conn, write=True):
        try:
            _current_run(conn, run_id)
        except MemoryError as exc:
            return {**result, "status": "failed", "errors": [{"kind": "internal", "code": exc.code, "message": str(exc)}]}
        state = (require_review(conn, run_id, candidates=candidates, uses=uses, now=now)
                 if expected_token is None else review_state(conn, run_id))
        if expected_token is not None and state.get("attempt_token") != expected_token:
            raise MemoryError("Memory finish was superseded; inspect current review before retrying.", "stale_attempt")
        pending = state["pending_errors"]
        if review and review["decision"] == "skip":
            pending = []
            state.update(review)
        elif candidates:
            state.update({"decision": "capture"})
            state.pop("reason", None)
        elif review:
            state.update(review)
        for kind, entries, maximum, function, output in (("candidate", candidates, 2, _capture, "captures"), ("use", uses, 50, _reinforce, "reinforcements")):
            if entries is None:
                continue
            malformed = not isinstance(entries, list) or len(entries) > maximum
            for index, entry in enumerate([None] if malformed else entries):
                identity = _identity(kind, entry, index)
                previous = next((e for e in pending if all(e.get(k) == v for k, v in identity.items())), None)
                attempts = previous.get("attempts", 0) if previous else 0
                try:
                    saved_slot = kind == "candidate" and "slot" in identity and conn.execute(
                        "SELECT 1 FROM events WHERE run_id=? AND event_type='memory_capture' AND json_extract(payload_json,'$.slot')=?",
                        (run_id, identity["slot"]),
                    ).fetchone()
                    if attempts >= 2 and not saved_slot:
                        raise MemoryError("Retry limit reached; use memory_review.skip with a reason to acknowledge this failure.", "retry_exhausted")
                    if malformed:
                        raise MemoryError(f"{kind}s must be a list with at most {maximum} entries")
                    result[output].append(function(conn, run_id, entry, now))
                    pending = [e for e in pending if not all(e.get(k) == v for k, v in identity.items())]
                except Exception as exc:
                    error = {**identity, "code": exc.code if isinstance(exc, MemoryError) else "memory_unavailable",
                             "message": str(exc) if isinstance(exc, MemoryError) else "Memory processing failed; retry once or skip with a reason.",
                             "attempts": min(attempts + 1, 2)}
                    pending = [e for e in pending if not all(e.get(k) == v for k, v in identity.items())] + [error]
                    _event(conn, run_id, "memory_finish_error", error, now)
        state["had_success"] = bool(state.get("had_success") or result["captures"] or result["reinforcements"])
        state["capture_count"] = review_state(conn, run_id)["capture_count"]
        state["pending_errors"] = pending
        state["status"] = (("partial" if state["capture_count"] or state["had_success"] else "failed") if pending else
                           "ok" if state.get("decision") == "skip" or (state.get("decision") == "capture" and state["capture_count"]) else "review_required")
        _event(conn, run_id, "memory_review", state, now)
        result.update({"status": state["status"], "errors": pending, "review": state})
    return result
