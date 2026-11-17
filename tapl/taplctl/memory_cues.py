"""Reusable cue labels. Callers own transactions; reads never create a catalog."""
from __future__ import annotations

import json
import unicodedata


def display_label(cue: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", cue).split())


def normalize_key(cue: str) -> str:
    return display_label(cue).casefold()


def _compact(key: str) -> str:
    return "".join(key.split())


def _has_catalog(conn) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='memory_cues'").fetchone() is not None


def _has_aliases(conn) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='memory_cue_aliases'").fetchone() is not None


def ensure_catalog(conn, *, backfill=False):
    conn.execute("""CREATE TABLE IF NOT EXISTS memory_cues (
        id INTEGER PRIMARY KEY, cue TEXT NOT NULL,
        normalized_key TEXT NOT NULL UNIQUE, compact_key TEXT NOT NULL
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS memory_cue_aliases (
        normalized_key TEXT PRIMARY KEY, cue TEXT NOT NULL, compact_key TEXT NOT NULL,
        cue_id INTEGER NOT NULL REFERENCES memory_cues(id) ON DELETE CASCADE
    )""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_memory_cue_aliases_cue ON memory_cue_aliases(cue_id)")
    conn.execute("""CREATE TABLE IF NOT EXISTS memory_cue_links (
        memory_row_id INTEGER NOT NULL REFERENCES memories(id) ON DELETE CASCADE,
        cue_id INTEGER NOT NULL REFERENCES memory_cues(id),
        position INTEGER NOT NULL,
        PRIMARY KEY(memory_row_id, cue_id)
    )""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_memory_cue_links_cue ON memory_cue_links(cue_id)")
    if backfill:
        for row in conn.execute("SELECT id,cues_json FROM memories WHERE state!='deleted' ORDER BY id"):
            bind_cues(conn, row["id"], _valid_cues(row["cues_json"]))


def _valid_cues(raw):
    try:
        cues = json.loads(raw)
    except (TypeError, ValueError):
        return []
    if not isinstance(cues, list):
        return []
    return [c for c in cues if isinstance(c, str) and 1 <= len(c.strip()) <= 80]


def _existing(conn, cue):
    key = normalize_key(cue)
    row = conn.execute("SELECT id,cue FROM memory_cues WHERE normalized_key=?", (key,)).fetchone()
    if row is None and _has_aliases(conn):
        row = conn.execute("""SELECT c.id,c.cue FROM memory_cue_aliases a
            JOIN memory_cues c ON c.id=a.cue_id WHERE a.normalized_key=?""", (key,)).fetchone()
    return row


def resolve_existing(conn, cues):
    """Resolve normalized identities and explicit aliases, never fuzzy matches."""
    result = []
    for cue in cues:
        row = _existing(conn, cue)
        result.append(row["cue"] if row else display_label(cue))
    return result


def bind_cues(conn, memory_row_id, cues):
    """Register successful writes and replace their links in the caller's transaction."""
    conn.execute("DELETE FROM memory_cue_links WHERE memory_row_id=?", (memory_row_id,))
    result = []
    for position, cue in enumerate(cues):
        key = normalize_key(cue)
        row = _existing(conn, cue)
        if row is None:
            conn.execute("INSERT INTO memory_cues(cue,normalized_key,compact_key) VALUES(?,?,?)",
                         (display_label(cue), key, _compact(key)))
            row = _existing(conn, cue)
        conn.execute("INSERT OR IGNORE INTO memory_cue_links(memory_row_id,cue_id,position) VALUES(?,?,?)",
                     (memory_row_id, row["id"], position))
        result.append(row["cue"])
    return result


def merge_cues(conn, *, target_cue, cues):
    """Merge explicit existing concepts; the caller owns a write transaction."""
    def existing_label(value):
        if not isinstance(value, str) or not 1 <= len(value.strip()) <= 80 or not 1 <= len(display_label(value)) <= 80:
            raise ValueError("each cue must contain 1–80 characters")
        row = _existing(conn, value)
        if row is None:
            raise ValueError("cue does not exist: " + display_label(value))
        return row

    if not isinstance(cues, list) or not 1 <= len(cues) <= 20:
        raise ValueError("cues must contain 1–20 strings")
    target = existing_label(target_cue)
    sources = {}
    for cue in cues:
        row = existing_label(cue)
        if row["id"] != target["id"]:
            sources.setdefault(row["id"], row["cue"])
    result = {"target_cue": target["cue"], "merged_cues": list(sources.values()),
              "affected_memories": 0, "status": "unchanged"}
    if not sources:
        return result
    placeholders = ",".join("?" for _ in sources)
    ids = tuple(sources)
    result["affected_memories"] = conn.execute(
        f"SELECT count(DISTINCT memory_row_id) FROM memory_cue_links WHERE cue_id IN ({placeholders})", ids,
    ).fetchone()[0]
    # Preserve the earliest association when a memory already uses the target,
    # or several source labels. Historical cues_json and FTS remain untouched.
    conn.execute(f"""INSERT INTO memory_cue_links(memory_row_id,cue_id,position)
        SELECT memory_row_id,?,min(position) FROM memory_cue_links
        WHERE cue_id IN ({placeholders}) GROUP BY memory_row_id
        ON CONFLICT(memory_row_id,cue_id) DO UPDATE SET position=min(position,excluded.position)""",
                 (target["id"], *ids))
    conn.execute(f"DELETE FROM memory_cue_links WHERE cue_id IN ({placeholders})", ids)
    conn.execute(f"UPDATE memory_cue_aliases SET cue_id=? WHERE cue_id IN ({placeholders})", (target["id"], *ids))
    conn.execute(f"""INSERT INTO memory_cue_aliases(normalized_key,cue,compact_key,cue_id)
        SELECT normalized_key,cue,compact_key,? FROM memory_cues WHERE id IN ({placeholders})""",
                 (target["id"], *ids))
    conn.execute(f"DELETE FROM memory_cues WHERE id IN ({placeholders})", ids)
    return {**result, "status": "merged"}


def list_cues(conn, *, query="", limit=20, offset=0):
    if not isinstance(query, str) or len(query) > 200:
        raise ValueError("query must be a string of at most 200 characters")
    if type(limit) is not int or not 1 <= limit <= 50:
        raise ValueError("limit must be an integer from 1 to 50")
    if type(offset) is not int or offset < 0:
        raise ValueError("offset must be a nonnegative integer")
    key = normalize_key(query)
    compact = _compact(key)
    if _has_catalog(conn):
        # instr treats %, _, quotes and punctuation as literal label characters.
        where = "WHERE instr(c.normalized_key,?)>0 OR instr(c.compact_key,?)>0"
        params = [key, compact]
        exact = "c.normalized_key=?"
        spaced = "c.compact_key=?"
        rank_params = [key, compact]
        if _has_aliases(conn):
            where += " OR EXISTS(SELECT 1 FROM memory_cue_aliases a WHERE a.cue_id=c.id AND (instr(a.normalized_key,?)>0 OR instr(a.compact_key,?)>0))"
            params.extend((key, compact))
            exact += " OR EXISTS(SELECT 1 FROM memory_cue_aliases a WHERE a.cue_id=c.id AND a.normalized_key=?)"
            spaced += " OR EXISTS(SELECT 1 FROM memory_cue_aliases a WHERE a.cue_id=c.id AND a.compact_key=?)"
            rank_params = [key, key, compact, compact]
        total = conn.execute("SELECT count(*) FROM memory_cues c " + where, params).fetchone()[0]
        rows = conn.execute("""SELECT c.cue,count(DISTINCT m.id) AS usage_count
            FROM memory_cues c LEFT JOIN memory_cue_links l ON l.cue_id=c.id
            LEFT JOIN memories m ON m.id=l.memory_row_id AND m.state!='deleted' """ + where + """
            GROUP BY c.id ORDER BY CASE WHEN """ + exact + " THEN 0 WHEN " + spaced + """
            THEN 1 ELSE 2 END,usage_count DESC,c.normalized_key,c.id
            LIMIT ? OFFSET ?""", (*params, *rank_params, limit, offset))
        cues = [dict(r) for r in rows]
    else:
        # Schema 14 remains readable, including foreign workspace databases.
        labels = {}
        for row in conn.execute("SELECT cues_json FROM memories WHERE state!='deleted' ORDER BY id"):
            seen = set()
            for cue in _valid_cues(row["cues_json"]):
                normal = normalize_key(cue)
                if normal in seen:
                    continue
                seen.add(normal)
                label = labels.setdefault(normal, {"cue": display_label(cue), "usage_count": 0})
                label["usage_count"] += 1
        matches = [(k, v) for k, v in labels.items() if key in k or compact in _compact(k)]
        matches.sort(key=lambda item: (0 if item[0] == key else 1 if _compact(item[0]) == compact else 2,
                                       -item[1]["usage_count"], item[0]))
        total = len(matches)
        cues = [v for _, v in matches[offset:offset + limit]]
    return {"query": query, "limit": limit, "offset": offset, "total": total, "cues": cues}
