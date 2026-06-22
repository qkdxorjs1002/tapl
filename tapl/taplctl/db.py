"""SQLite storage for tapl workflow state."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


SCHEMA_VERSION = 2
DEFAULT_DB_RELATIVE = Path(".tapl") / "tapl.db"
DEFAULT_EMBEDDING_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
DEFAULT_EMBEDDING_DIMENSION = 384
TASK_STATUSES = ("Pending", "In Progress", "Completed", "Blocked", "Skipped")
DEFAULT_APPROVAL_KIND = "execution"
APPROVAL_DECISIONS = ("approved", "rejected")
DEFAULT_REQUEST_SUMMARY = "New request"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def find_repo_root(start: Path | None = None) -> Path:
    current = (start or Path.cwd()).resolve()
    if current.is_file():
        current = current.parent
    candidates = [current, *current.parents]

    for path in candidates:
        if (path / ".git").exists():
            return path

    for path in candidates:
        if (path / ".codex").exists() and (path / "README.md").exists():
            return path

    return current


def default_db_path(start: Path | None = None) -> Path:
    return find_repo_root(start) / DEFAULT_DB_RELATIVE


def connect(path: Path | str | None = None) -> sqlite3.Connection:
    db_path = Path(path) if path else default_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    migrate(conn)
    return conn


def migrate(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS meta (
          key TEXT PRIMARY KEY,
          value TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS workflow_runs (
          id TEXT PRIMARY KEY,
          slug TEXT NOT NULL,
          status TEXT NOT NULL,
          request_summary TEXT NOT NULL DEFAULT '',
          result_summary TEXT NOT NULL DEFAULT '',
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          archived_at TEXT
        );

        CREATE TABLE IF NOT EXISTS items (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          run_id TEXT NOT NULL REFERENCES workflow_runs(id) ON DELETE CASCADE,
          stable_id TEXT NOT NULL,
          kind TEXT NOT NULL,
          title TEXT NOT NULL,
          body TEXT NOT NULL DEFAULT '',
          raw_text TEXT NOT NULL DEFAULT '',
          status TEXT,
          source TEXT,
          archived INTEGER NOT NULL DEFAULT 0,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          UNIQUE(run_id, kind, stable_id)
        );

        CREATE TABLE IF NOT EXISTS tasks (
          item_id INTEGER PRIMARY KEY REFERENCES items(id) ON DELETE CASCADE,
          task_id TEXT NOT NULL,
          spec_id TEXT,
          goal TEXT NOT NULL DEFAULT '',
          action TEXT NOT NULL DEFAULT '',
          required_subagent TEXT NOT NULL DEFAULT '',
          verification TEXT NOT NULL DEFAULT '',
          result TEXT NOT NULL DEFAULT '',
          blocker TEXT NOT NULL DEFAULT '',
          next_action TEXT NOT NULL DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS findings (
          item_id INTEGER PRIMARY KEY REFERENCES items(id) ON DELETE CASCADE,
          related_ids TEXT NOT NULL DEFAULT '',
          impact TEXT NOT NULL DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS approvals (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          run_id TEXT REFERENCES workflow_runs(id) ON DELETE SET NULL,
          kind TEXT NOT NULL,
          prompt TEXT NOT NULL DEFAULT '',
          decision TEXT NOT NULL DEFAULT '',
          decided_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS archives (
          id TEXT PRIMARY KEY,
          run_id TEXT NOT NULL REFERENCES workflow_runs(id) ON DELETE CASCADE,
          slug TEXT NOT NULL,
          summary TEXT NOT NULL DEFAULT '',
          created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS events (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          run_id TEXT REFERENCES workflow_runs(id) ON DELETE SET NULL,
          event_type TEXT NOT NULL,
          tool_name TEXT,
          mode TEXT NOT NULL DEFAULT 'observe',
          payload_json TEXT NOT NULL DEFAULT '{}',
          message TEXT NOT NULL DEFAULT '',
          created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS embedding_jobs (
          item_id INTEGER PRIMARY KEY REFERENCES items(id) ON DELETE CASCADE,
          content_hash TEXT NOT NULL,
          state TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );

        CREATE VIRTUAL TABLE IF NOT EXISTS items_fts
          USING fts5(stable_id, kind, title, body);

        CREATE INDEX IF NOT EXISTS idx_items_kind_status ON items(kind, status);
        CREATE INDEX IF NOT EXISTS idx_items_run_kind ON items(run_id, kind);
        CREATE INDEX IF NOT EXISTS idx_runs_status ON workflow_runs(status);
        CREATE INDEX IF NOT EXISTS idx_events_created_at ON events(created_at);
        """
    )

    ensure_column(conn, "workflow_runs", "result_summary", "TEXT NOT NULL DEFAULT ''")
    dedupe_active_runs(conn)
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_single_active_run ON workflow_runs(status) WHERE status = 'active'"
    )
    set_meta(conn, "schema_version", str(SCHEMA_VERSION))
    set_meta(conn, "embedding_model", DEFAULT_EMBEDDING_MODEL)
    set_meta(conn, "embedding_dimension", str(DEFAULT_EMBEDDING_DIMENSION))
    conn.commit()


def ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        """
        INSERT INTO meta(key, value) VALUES(?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """,
        (key, value),
    )


def get_meta(conn: sqlite3.Connection) -> dict[str, str]:
    return {row["key"]: row["value"] for row in conn.execute("SELECT key, value FROM meta")}


def active_run(conn: sqlite3.Connection) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT * FROM workflow_runs
        WHERE status = 'active'
        ORDER BY updated_at DESC, created_at DESC
        LIMIT 1
        """
    ).fetchone()


def dedupe_active_runs(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        """
        SELECT r.*,
          (SELECT COUNT(*) FROM items i WHERE i.run_id = r.id) AS item_count
        FROM workflow_runs r
        WHERE r.status = 'active'
        ORDER BY item_count DESC, r.updated_at DESC, r.created_at DESC
        """
    ).fetchall()
    if len(rows) <= 1:
        return

    now = utc_now()
    for row in rows[1:]:
        conn.execute(
            "UPDATE workflow_runs SET status = 'archived', archived_at = ?, updated_at = ? WHERE id = ?",
            (now, now, row["id"]),
        )


def ensure_active_run(
    conn: sqlite3.Connection,
    *,
    slug: str = "active",
    request_summary: str = DEFAULT_REQUEST_SUMMARY,
) -> sqlite3.Row:
    existing = active_run(conn)
    if existing:
        if request_summary and not existing["request_summary"]:
            conn.execute(
                "UPDATE workflow_runs SET request_summary = ?, updated_at = ? WHERE id = ?",
                (request_summary, utc_now(), existing["id"]),
            )
            conn.commit()
            return active_run(conn)  # type: ignore[return-value]
        return existing

    now = utc_now()
    run_id = str(uuid.uuid4())
    try:
        conn.execute(
            """
            INSERT INTO workflow_runs(id, slug, status, request_summary, created_at, updated_at)
            VALUES(?, ?, 'active', ?, ?, ?)
            """,
            (run_id, slug, request_summary, now, now),
        )
    except sqlite3.IntegrityError:
        existing = active_run(conn)
        if existing:
            return existing
        raise
    conn.commit()
    return active_run(conn)  # type: ignore[return-value]


def update_active_run_summary(
    conn: sqlite3.Connection,
    *,
    request_summary: str | None = None,
    result_summary: str | None = None,
) -> sqlite3.Row:
    run = active_run(conn)
    if not run:
        raise ValueError("no active workflow run to update")

    updates: list[str] = []
    params: list[Any] = []
    if request_summary is not None:
        updates.append("request_summary = ?")
        params.append(request_summary.strip())
    if result_summary is not None:
        updates.append("result_summary = ?")
        params.append(result_summary.strip())
    if not updates:
        return run

    updates.append("updated_at = ?")
    params.append(utc_now())
    params.append(run["id"])
    conn.execute(
        f"UPDATE workflow_runs SET {', '.join(updates)} WHERE id = ?",
        tuple(params),
    )
    conn.commit()
    return active_run(conn)  # type: ignore[return-value]


def create_run(
    conn: sqlite3.Connection,
    *,
    slug: str,
    status: str,
    request_summary: str = "",
) -> sqlite3.Row:
    now = utc_now()
    run_id = str(uuid.uuid4())
    conn.execute(
        """
        INSERT INTO workflow_runs(id, slug, status, request_summary, created_at, updated_at, archived_at)
        VALUES(?, ?, ?, ?, ?, ?, ?)
        """,
        (run_id, slug, status, request_summary, now, now, now if status == "archived" else None),
    )
    conn.commit()
    return conn.execute("SELECT * FROM workflow_runs WHERE id = ?", (run_id,)).fetchone()


def upsert_item(
    conn: sqlite3.Connection,
    *,
    kind: str,
    stable_id: str,
    title: str,
    body: str = "",
    raw_text: str = "",
    status: str | None = None,
    source: str | None = None,
    run_id: str | None = None,
    archived: bool = False,
) -> sqlite3.Row:
    run = conn.execute("SELECT * FROM workflow_runs WHERE id = ?", (run_id,)).fetchone() if run_id else ensure_active_run(conn)
    now = utc_now()
    conn.execute(
        """
        INSERT INTO items(run_id, stable_id, kind, title, body, raw_text, status, source, archived, created_at, updated_at)
        VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(run_id, kind, stable_id) DO UPDATE SET
          title = excluded.title,
          body = excluded.body,
          raw_text = excluded.raw_text,
          status = excluded.status,
          source = excluded.source,
          archived = excluded.archived,
          updated_at = excluded.updated_at
        """,
        (run["id"], stable_id, kind, title, body, raw_text, status, source, 1 if archived else 0, now, now),
    )
    item = conn.execute(
        "SELECT * FROM items WHERE run_id = ? AND kind = ? AND stable_id = ?",
        (run["id"], kind, stable_id),
    ).fetchone()
    refresh_item_fts(conn, item)
    conn.commit()
    return item


def get_active_task(conn: sqlite3.Connection, task_id: str) -> sqlite3.Row | None:
    run = active_run(conn)
    if not run:
        return None
    return conn.execute(
        """
        SELECT i.*, t.spec_id, t.goal, t.action, t.required_subagent, t.verification, t.result, t.blocker, t.next_action
        FROM items i
        LEFT JOIN tasks t ON t.item_id = i.id
        WHERE i.run_id = ? AND i.kind = 'task' AND i.stable_id = ?
        LIMIT 1
        """,
        (run["id"], task_id),
    ).fetchone()


def upsert_task(
    conn: sqlite3.Connection,
    *,
    task_id: str,
    title: str,
    status: str,
    spec_id: str = "",
    goal: str = "",
    action: str = "",
    required_subagent: str = "",
    verification: str = "",
    result: str = "",
    blocker: str = "",
    next_action: str = "",
) -> sqlite3.Row:
    if status not in TASK_STATUSES:
        raise ValueError(f"invalid task status: {status}")

    body = "\n\n".join(
        part
        for part in [
            f"### Goal\n{goal}" if goal else "",
            f"### Action\n{action}" if action else "",
            f"### Verification\n{verification}" if verification else "",
            f"### Result\n{result}" if result else "",
            f"### Blocker\n{blocker}" if blocker else "",
            f"### Next action\n{next_action}" if next_action else "",
        ]
        if part
    )
    item = upsert_item(
        conn,
        kind="task",
        stable_id=task_id,
        title=title,
        body=body,
        status=status,
    )
    conn.execute(
        """
        INSERT INTO tasks(item_id, task_id, spec_id, goal, action, required_subagent, verification, result, blocker, next_action)
        VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(item_id) DO UPDATE SET
          spec_id = excluded.spec_id,
          goal = excluded.goal,
          action = excluded.action,
          required_subagent = excluded.required_subagent,
          verification = excluded.verification,
          result = excluded.result,
          blocker = excluded.blocker,
          next_action = excluded.next_action
        """,
        (item["id"], task_id, spec_id, goal, action, required_subagent, verification, result, blocker, next_action),
    )
    conn.commit()
    return item


def add_finding(
    conn: sqlite3.Connection,
    *,
    title: str,
    source: str = "",
    finding: str = "",
    impact: str = "",
    related_ids: str = "",
) -> sqlite3.Row:
    stable_id = next_stable_id(conn, "finding", "FINDING")
    body = finding
    item = upsert_item(
        conn,
        kind="finding",
        stable_id=stable_id,
        title=title,
        body=body,
        source=source,
    )
    conn.execute(
        """
        INSERT INTO findings(item_id, related_ids, impact)
        VALUES(?, ?, ?)
        ON CONFLICT(item_id) DO UPDATE SET
          related_ids = excluded.related_ids,
          impact = excluded.impact
        """,
        (item["id"], related_ids, impact),
    )
    conn.commit()
    return item


def record_approval(
    conn: sqlite3.Connection,
    *,
    kind: str = DEFAULT_APPROVAL_KIND,
    decision: str,
    prompt: str = "",
    run_id: str | None = None,
) -> sqlite3.Row:
    if decision not in APPROVAL_DECISIONS:
        raise ValueError(f"invalid approval decision: {decision}")

    run = conn.execute("SELECT * FROM workflow_runs WHERE id = ?", (run_id,)).fetchone() if run_id else active_run(conn)
    if not run:
        raise ValueError("no active workflow run for approval")

    now = utc_now()
    conn.execute(
        """
        INSERT INTO approvals(run_id, kind, prompt, decision, decided_at)
        VALUES(?, ?, ?, ?, ?)
        """,
        (run["id"], kind, prompt, decision, now),
    )
    conn.commit()
    return conn.execute("SELECT * FROM approvals WHERE id = last_insert_rowid()").fetchone()


def latest_approval(
    conn: sqlite3.Connection,
    *,
    kind: str = DEFAULT_APPROVAL_KIND,
    run_id: str | None = None,
) -> sqlite3.Row | None:
    run = conn.execute("SELECT * FROM workflow_runs WHERE id = ?", (run_id,)).fetchone() if run_id else active_run(conn)
    if not run:
        return None
    return conn.execute(
        """
        SELECT *
        FROM approvals
        WHERE run_id = ? AND kind = ?
        ORDER BY decided_at DESC, id DESC
        LIMIT 1
        """,
        (run["id"], kind),
    ).fetchone()


def approval_status(
    conn: sqlite3.Connection,
    *,
    kind: str = DEFAULT_APPROVAL_KIND,
    run_id: str | None = None,
) -> dict[str, Any]:
    run = conn.execute("SELECT * FROM workflow_runs WHERE id = ?", (run_id,)).fetchone() if run_id else active_run(conn)
    if not run:
        return {
            "kind": kind,
            "state": "not_applicable",
            "approved": False,
            "decision": "",
            "prompt": "",
            "decided_at": "",
        }

    row = latest_approval(conn, kind=kind, run_id=run["id"])
    if row is None:
        return {
            "kind": kind,
            "state": "missing",
            "approved": False,
            "decision": "",
            "prompt": "",
            "decided_at": "",
        }

    decision = row["decision"]
    return {
        "id": row["id"],
        "kind": row["kind"],
        "state": decision,
        "approved": decision == "approved",
        "decision": decision,
        "prompt": row["prompt"],
        "decided_at": row["decided_at"],
    }


def list_approvals(
    conn: sqlite3.Connection,
    *,
    kind: str | None = None,
    run_id: str | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    run = conn.execute("SELECT * FROM workflow_runs WHERE id = ?", (run_id,)).fetchone() if run_id else active_run(conn)
    if not run:
        return []

    sql = """
        SELECT *
        FROM approvals
        WHERE run_id = ?
    """
    params: list[Any] = [run["id"]]
    if kind:
        sql += " AND kind = ?"
        params.append(kind)
    sql += " ORDER BY decided_at DESC, id DESC"
    if limit is not None:
        sql += " LIMIT ?"
        params.append(limit)
    return [row_to_dict(row) for row in conn.execute(sql, tuple(params))]


def next_stable_id(conn: sqlite3.Connection, kind: str, prefix: str) -> str:
    rows = conn.execute(
        "SELECT stable_id FROM items WHERE kind = ? AND stable_id LIKE ?",
        (kind, f"{prefix}-%"),
    ).fetchall()
    highest = 0
    pattern = re.compile(rf"^{re.escape(prefix)}-(\d+)$")
    for row in rows:
        match = pattern.match(row["stable_id"])
        if match:
            highest = max(highest, int(match.group(1)))
    return f"{prefix}-{highest + 1:03d}"


def refresh_item_fts(conn: sqlite3.Connection, item: sqlite3.Row) -> None:
    conn.execute("DELETE FROM items_fts WHERE rowid = ?", (item["id"],))
    conn.execute(
        "INSERT INTO items_fts(rowid, stable_id, kind, title, body) VALUES(?, ?, ?, ?, ?)",
        (
            item["id"],
            item["stable_id"],
            item["kind"],
            item["title"],
            "\n".join(part for part in [item["body"], item["raw_text"]] if part),
        ),
    )


def record_event(
    conn: sqlite3.Connection,
    *,
    event_type: str,
    tool_name: str | None = None,
    mode: str = "observe",
    payload: dict[str, Any] | None = None,
    message: str = "",
    run_id: str | None = None,
) -> None:
    run = active_run(conn)
    conn.execute(
        """
        INSERT INTO events(run_id, event_type, tool_name, mode, payload_json, message, created_at)
        VALUES(?, ?, ?, ?, ?, ?, ?)
        """,
        (
            run_id or (run["id"] if run else None),
            event_type,
            tool_name,
            mode,
            json.dumps(payload or {}, ensure_ascii=False, sort_keys=True),
            message,
            utc_now(),
        ),
    )
    conn.commit()


def archive_active_run(conn: sqlite3.Connection, *, slug: str, summary: str = "") -> sqlite3.Row:
    run = active_run(conn)
    if not run:
        raise ValueError("no active workflow run to archive")

    archive_id = utc_now().replace(":", "").replace("+0000", "Z") + "-" + slug
    now = utc_now()
    conn.execute(
        "UPDATE workflow_runs SET status = 'archived', archived_at = ?, updated_at = ? WHERE id = ?",
        (now, now, run["id"]),
    )
    conn.execute("UPDATE items SET archived = 1, updated_at = ? WHERE run_id = ?", (now, run["id"]))
    conn.execute(
        "INSERT INTO archives(id, run_id, slug, summary, created_at) VALUES(?, ?, ?, ?, ?)",
        (archive_id, run["id"], slug, summary, now),
    )
    conn.commit()
    return conn.execute("SELECT * FROM archives WHERE id = ?", (archive_id,)).fetchone()


def status_payload(conn: sqlite3.Connection) -> dict[str, Any]:
    run = active_run(conn)
    run_id = run["id"] if run else None
    task_counts = {status: 0 for status in TASK_STATUSES}
    tasks: list[dict[str, Any]] = []
    plans: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []

    if run_id:
        for row in conn.execute(
            """
            SELECT i.*, t.spec_id, t.goal, t.action, t.required_subagent, t.verification, t.result, t.blocker, t.next_action
            FROM items i
            LEFT JOIN tasks t ON t.item_id = i.id
            WHERE i.run_id = ? AND i.kind = 'task'
            ORDER BY i.stable_id
            """,
            (run_id,),
        ):
            task_counts[row["status"]] = task_counts.get(row["status"], 0) + 1
            tasks.append(row_to_dict(row))

        plans = [
            row_to_dict(row)
            for row in conn.execute(
                "SELECT * FROM items WHERE run_id = ? AND kind = 'plan' ORDER BY stable_id",
                (run_id,),
            )
        ]
        findings = [
            row_to_dict(row)
            for row in conn.execute(
                "SELECT * FROM items WHERE run_id = ? AND kind = 'finding' ORDER BY stable_id",
                (run_id,),
            )
        ]

    archives = list_archives(conn, limit=8)
    archive_count = int(conn.execute("SELECT COUNT(*) FROM archives").fetchone()[0])
    recent_events = [
        row_to_dict(row)
        for row in conn.execute(
            "SELECT * FROM events ORDER BY id DESC LIMIT 12",
        )
    ]
    incomplete = sum(task_counts[status] for status in ("Pending", "In Progress", "Blocked"))

    return {
        "schema": get_meta(conn),
        "active_run": row_to_dict(run) if run else None,
        "approvals": {
            DEFAULT_APPROVAL_KIND: approval_status(conn, kind=DEFAULT_APPROVAL_KIND, run_id=run_id),
        },
        "task_counts": task_counts,
        "incomplete_tasks": incomplete,
        "plans": plans,
        "tasks": tasks,
        "findings": findings,
        "archives": archives,
        "archive_count": archive_count,
        "recent_events": recent_events,
    }


def list_archives(conn: sqlite3.Connection, limit: int | None = None) -> list[dict[str, Any]]:
    sql = """
        SELECT a.*, r.request_summary, r.result_summary
        FROM archives a
        JOIN workflow_runs r ON r.id = a.run_id
        ORDER BY a.created_at DESC
    """
    params: tuple[Any, ...] = ()
    if limit is not None:
        sql += " LIMIT ?"
        params = (limit,)
    return [row_to_dict(row) for row in conn.execute(sql, params)]


def archive_detail(conn: sqlite3.Connection, archive_id_or_slug: str) -> dict[str, Any] | None:
    archive = conn.execute(
        """
        SELECT
          a.id,
          a.run_id,
          a.slug,
          a.summary,
          a.created_at,
          r.request_summary,
          r.result_summary,
          r.slug AS run_slug,
          r.created_at AS run_created_at,
          r.updated_at AS run_updated_at,
          r.archived_at AS run_archived_at
        FROM archives a
        JOIN workflow_runs r ON r.id = a.run_id
        WHERE a.id = ? OR a.slug = ?
        ORDER BY a.created_at DESC
        LIMIT 1
        """,
        (archive_id_or_slug, archive_id_or_slug),
    ).fetchone()
    if archive is None:
        return None

    run_id = archive["run_id"]
    items = [
        row_to_dict(row)
        for row in conn.execute(
            """
            SELECT
              i.*,
              t.spec_id,
              t.goal,
              t.action,
              t.required_subagent,
              t.verification,
              t.result,
              t.blocker,
              t.next_action,
              f.related_ids,
              f.impact
            FROM items i
            LEFT JOIN tasks t ON t.item_id = i.id
            LEFT JOIN findings f ON f.item_id = i.id
            WHERE i.run_id = ?
            ORDER BY
              CASE i.kind
                WHEN 'plan' THEN 0
                WHEN 'task' THEN 1
                WHEN 'finding' THEN 2
                ELSE 3
              END,
              i.stable_id
            """,
            (run_id,),
        )
    ]
    events = [
        row_to_dict(row)
        for row in conn.execute(
            """
            SELECT id, run_id, event_type, tool_name, mode, message, created_at
            FROM events
            WHERE run_id = ?
            ORDER BY id
            """,
            (run_id,),
        )
    ]
    return {
        "archive": row_to_dict(archive),
        "items": items,
        "events": events,
    }


def item_detail(conn: sqlite3.Connection, item_id: int) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT
          i.*,
          r.slug AS run_slug,
          r.status AS run_status,
          r.request_summary,
          a.id AS archive_id,
          a.slug AS archive_slug,
          a.created_at AS archive_created_at,
          t.spec_id,
          t.goal,
          t.action,
          t.required_subagent,
          t.verification,
          t.result,
          t.blocker,
          t.next_action,
          f.related_ids,
          f.impact
        FROM items i
        JOIN workflow_runs r ON r.id = i.run_id
        LEFT JOIN archives a ON a.run_id = i.run_id
        LEFT JOIN tasks t ON t.item_id = i.id
        LEFT JOIN findings f ON f.item_id = i.id
        WHERE i.id = ?
        LIMIT 1
        """,
        (item_id,),
    ).fetchone()
    return row_to_dict(row)


def incomplete_task_count(conn: sqlite3.Connection) -> int:
    run = active_run(conn)
    if not run:
        return 0
    row = conn.execute(
        """
        SELECT COUNT(*) AS count
        FROM items
        WHERE run_id = ? AND kind = 'task' AND status IN ('Pending', 'In Progress', 'Blocked')
        """,
        (run["id"],),
    ).fetchone()
    return int(row["count"])


def active_task_count(conn: sqlite3.Connection) -> int:
    run = active_run(conn)
    if not run:
        return 0
    row = conn.execute(
        "SELECT COUNT(*) AS count FROM items WHERE run_id = ? AND kind = 'task'",
        (run["id"],),
    ).fetchone()
    return int(row["count"])


def search_bm25(conn: sqlite3.Connection, query: str, limit: int = 10) -> list[dict[str, Any]]:
    fts_query = build_fts_query(query)
    if not fts_query:
        return search_word(conn, query, limit=limit)

    rows = conn.execute(
        """
        SELECT i.*, bm25(items_fts) AS score
        FROM items_fts
        JOIN items i ON i.id = items_fts.rowid
        WHERE items_fts MATCH ?
        ORDER BY score
        LIMIT ?
        """,
        (fts_query, limit),
    ).fetchall()
    return [search_row(row, "bm25") for row in rows]


def search_word(conn: sqlite3.Connection, query: str, limit: int = 10) -> list[dict[str, Any]]:
    like = f"%{query}%"
    rows = conn.execute(
        """
        SELECT *, 0.0 AS score
        FROM items
        WHERE title LIKE ? OR body LIKE ? OR raw_text LIKE ? OR stable_id LIKE ?
        ORDER BY updated_at DESC
        LIMIT ?
        """,
        (like, like, like, like, limit),
    ).fetchall()
    return [search_row(row, "word") for row in rows]


def search_fts(conn: sqlite3.Connection, query: str, limit: int = 10) -> list[dict[str, Any]]:
    return search_bm25(conn, query, limit=limit)


def build_fts_query(query: str) -> str:
    terms = re.findall(r"[\w가-힣]+", query, flags=re.UNICODE)
    return " OR ".join(f'"{term}"' for term in terms[:8])


def search_row(row: sqlite3.Row, source: str) -> dict[str, Any]:
    data = row_to_dict(row)
    return {
        "id": data.get("id"),
        "stable_id": data.get("stable_id"),
        "kind": data.get("kind"),
        "title": data.get("title"),
        "status": data.get("status"),
        "source": data.get("source"),
        "score": data.get("score"),
        "search_source": source,
        "snippet": make_snippet(data.get("body") or data.get("raw_text") or ""),
    }


def make_snippet(text: str, length: int = 180) -> str:
    compact = re.sub(r"\s+", " ", text).strip()
    return compact[:length] + ("..." if len(compact) > length else "")


def content_hash(parts: Iterable[str]) -> str:
    digest = hashlib.sha256()
    for part in parts:
        digest.update(part.encode("utf-8", errors="replace"))
        digest.update(b"\0")
    return digest.hexdigest()


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {key: row[key] for key in row.keys()}
