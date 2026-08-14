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


SCHEMA_VERSION = 9
DEFAULT_DB_RELATIVE = Path(".tapl") / "tapl.db"
DEFAULT_EMBEDDING_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
DEFAULT_EMBEDDING_DIMENSION = 384
TASK_STATUSES = ("Pending", "In Progress", "Completed", "Blocked", "Skipped")
EXECUTION_MODES = ("sequential", "parallel")
EXECUTOR_KINDS = ("main", "subagent")
ACTIVE_EXECUTION_STATES = ("dispatched", "running")
TERMINAL_TASK_STATUSES = ("Completed", "Blocked", "Skipped")
DEFAULT_FAILURE_POLICY = "continue"
DEFAULT_CANCELLED_NEXT_ACTION = (
    "Review the cancelled batch, then replan or dispatch the task again."
)
SQLITE_BUSY_TIMEOUT_MS = 5_000
DEFAULT_APPROVAL_KIND = "execution"
APPROVAL_DECISIONS = ("approved", "rejected")
APPROVAL_SOURCES = ("explicit_user", "request_user_input", "unspecified")
DEFAULT_APPROVAL_SOURCE = "explicit_user"
DEFAULT_REQUEST_SUMMARY = "New request"
WORK_TYPES = ("answer", "investigation", "analysis", "planning", "implementation", "mixed")
DEFAULT_WORK_TYPE = "mixed"
WORKFLOW_MODES = ("fast", "standard", "strict")
DEFAULT_WORKFLOW_MODE = "standard"
RECORD_MODES = ("lightweight", "planned")
DEFAULT_RECORD_MODE = "planned"
LIGHTWEIGHT_WORK_TYPES = ("answer", "investigation", "analysis", "planning")
WORKFLOW_RUN_OUTPUT_FIELDS = (
    "id",
    "slug",
    "status",
    "request_summary",
    "result_summary",
    "work_type",
    "workflow_mode",
    "record_mode",
    "created_at",
    "updated_at",
    "archived_at",
)


def derive_record_mode(work_type: str, workflow_mode: str) -> str:
    if work_type not in WORK_TYPES:
        raise ValueError(f"invalid work_type: {work_type}")
    if workflow_mode not in WORKFLOW_MODES:
        raise ValueError(f"invalid workflow_mode: {workflow_mode}")
    if workflow_mode == "fast" and work_type in LIGHTWEIGHT_WORK_TYPES:
        return "lightweight"
    return "planned"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def ancestor_paths(start: Path | None = None) -> list[Path]:
    current = (start or Path.cwd()).resolve()
    if current.is_file():
        current = current.parent
    return [current, *current.parents]


def find_workspace_root(start: Path | None = None) -> Path | None:
    for path in ancestor_paths(start):
        if (path / DEFAULT_DB_RELATIVE).is_file():
            return path
    return None


def find_repo_root(start: Path | None = None) -> Path:
    candidates = ancestor_paths(start)

    workspace_root = find_workspace_root(start)
    if workspace_root is not None:
        return workspace_root

    for path in candidates:
        if (path / ".git").exists():
            return path

    for path in candidates:
        if (path / ".codex").exists() and (path / "README.md").exists():
            return path

    return candidates[0]


def initialize_workspace(root: Path | str) -> dict[str, Any]:
    workspace_root = Path(root).expanduser().resolve()
    workspace_root.mkdir(parents=True, exist_ok=True)
    db_path = workspace_root / DEFAULT_DB_RELATIVE
    db_existed = db_path.exists()
    conn = connect(db_path)
    conn.close()
    return {
        "workspace_root": str(workspace_root),
        "db": str(db_path),
        "db_action": "unchanged" if db_existed else "created",
    }


def default_db_path(start: Path | None = None) -> Path:
    return find_repo_root(start) / DEFAULT_DB_RELATIVE


def connect(path: Path | str | None = None) -> sqlite3.Connection:
    db_path = Path(path) if path else default_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=SQLITE_BUSY_TIMEOUT_MS / 1_000)
    conn.row_factory = sqlite3.Row
    conn.execute(f"PRAGMA busy_timeout = {SQLITE_BUSY_TIMEOUT_MS}")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    migrate(conn)
    return conn


def migrate(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS meta (
          key TEXT PRIMARY KEY,
          value TEXT NOT NULL
        )
        """
    )
    schema_version_row = conn.execute(
        "SELECT value FROM meta WHERE key = 'schema_version'"
    ).fetchone()
    if schema_version_row is not None:
        try:
            stored_schema_version = int(schema_version_row["value"])
        except (TypeError, ValueError) as exc:
            raise RuntimeError("database schema_version is not a valid integer") from exc
        if stored_schema_version > SCHEMA_VERSION:
            raise RuntimeError(
                "database schema version "
                f"{stored_schema_version} is newer than supported version {SCHEMA_VERSION}"
            )

    migrated_legacy_record_mode = migrate_legacy_workflow_mode(conn)

    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS workflow_runs (
          id TEXT PRIMARY KEY,
          slug TEXT NOT NULL,
          status TEXT NOT NULL,
          request_summary TEXT NOT NULL DEFAULT '',
          result_summary TEXT NOT NULL DEFAULT '',
          work_type TEXT NOT NULL DEFAULT 'mixed'
            CHECK (work_type IN ('answer', 'investigation', 'analysis', 'planning', 'implementation', 'mixed')),
          workflow_mode TEXT NOT NULL DEFAULT 'standard'
            CHECK (workflow_mode IN ('fast', 'standard', 'strict')),
          record_mode TEXT NOT NULL DEFAULT 'planned'
            CHECK (record_mode IN ('lightweight', 'planned')),
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
          custom_fields_json TEXT NOT NULL DEFAULT '{}',
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
          verification TEXT NOT NULL DEFAULT '',
          result TEXT NOT NULL DEFAULT '',
          blocker TEXT NOT NULL DEFAULT '',
          next_action TEXT NOT NULL DEFAULT '',
          execution_mode TEXT NOT NULL DEFAULT 'sequential'
            CHECK (execution_mode IN ('sequential', 'parallel')),
          executor_kind TEXT NOT NULL DEFAULT 'main'
            CHECK (executor_kind IN ('main', 'subagent')),
          parallel_group TEXT NOT NULL DEFAULT '',
          owned_paths_json TEXT NOT NULL DEFAULT '[]'
        );

        CREATE TABLE IF NOT EXISTS plans (
          item_id INTEGER PRIMARY KEY REFERENCES items(id) ON DELETE CASCADE,
          plan_id TEXT NOT NULL,
          summary TEXT NOT NULL DEFAULT '',
          objective TEXT NOT NULL DEFAULT '',
          requirements_trace TEXT NOT NULL DEFAULT '',
          selected_approach TEXT NOT NULL DEFAULT '',
          affected_files TEXT NOT NULL DEFAULT '',
          execution_order TEXT NOT NULL DEFAULT '',
          risks TEXT NOT NULL DEFAULT '',
          validation TEXT NOT NULL DEFAULT '',
          approval_needs TEXT NOT NULL DEFAULT '',
          notes TEXT NOT NULL DEFAULT ''
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
          source TEXT NOT NULL DEFAULT 'unspecified',
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

        CREATE TABLE IF NOT EXISTS task_dependencies (
          task_item_id INTEGER NOT NULL REFERENCES tasks(item_id) ON DELETE CASCADE,
          dependency_item_id INTEGER NOT NULL REFERENCES tasks(item_id) ON DELETE CASCADE,
          PRIMARY KEY(task_item_id, dependency_item_id),
          CHECK(task_item_id <> dependency_item_id)
        );

        CREATE TABLE IF NOT EXISTS execution_batches (
          id TEXT PRIMARY KEY,
          run_id TEXT NOT NULL REFERENCES workflow_runs(id) ON DELETE CASCADE,
          parallel_group TEXT NOT NULL,
          state TEXT NOT NULL,
          failure_policy TEXT NOT NULL DEFAULT 'continue',
          approval_id INTEGER REFERENCES approvals(id) ON DELETE SET NULL,
          created_at TEXT NOT NULL,
          finished_at TEXT
        );

        CREATE TABLE IF NOT EXISTS task_executions (
          id TEXT PRIMARY KEY,
          batch_id TEXT NOT NULL REFERENCES execution_batches(id) ON DELETE CASCADE,
          task_item_id INTEGER NOT NULL REFERENCES tasks(item_id) ON DELETE CASCADE,
          state TEXT NOT NULL,
          executor_ref TEXT NOT NULL DEFAULT '',
          model TEXT NOT NULL DEFAULT '',
          reasoning_effort TEXT NOT NULL DEFAULT '',
          result TEXT NOT NULL DEFAULT '',
          error TEXT NOT NULL DEFAULT '',
          started_at TEXT NOT NULL,
          finished_at TEXT,
          UNIQUE(batch_id, task_item_id)
        );

        CREATE VIRTUAL TABLE IF NOT EXISTS items_fts
          USING fts5(stable_id, kind, title, body);

        CREATE INDEX IF NOT EXISTS idx_items_kind_status ON items(kind, status);
        CREATE INDEX IF NOT EXISTS idx_items_run_kind ON items(run_id, kind);
        CREATE INDEX IF NOT EXISTS idx_runs_status ON workflow_runs(status);
        CREATE INDEX IF NOT EXISTS idx_events_created_at ON events(created_at);
        CREATE INDEX IF NOT EXISTS idx_task_dependencies_dependency
          ON task_dependencies(dependency_item_id);
        CREATE INDEX IF NOT EXISTS idx_execution_batches_run_state
          ON execution_batches(run_id, state);
        CREATE INDEX IF NOT EXISTS idx_task_executions_batch_state
          ON task_executions(batch_id, state);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_task_executions_active_task
          ON task_executions(task_item_id)
          WHERE state IN ('dispatched', 'running');
        """
    )

    ensure_column(conn, "workflow_runs", "result_summary", "TEXT NOT NULL DEFAULT ''")
    ensure_column(
        conn,
        "workflow_runs",
        "work_type",
        "TEXT NOT NULL DEFAULT 'mixed' CHECK (work_type IN ('answer', 'investigation', 'analysis', 'planning', 'implementation', 'mixed'))",
    )
    ensure_column(
        conn,
        "workflow_runs",
        "workflow_mode",
        "TEXT NOT NULL DEFAULT 'standard' CHECK (workflow_mode IN ('fast', 'standard', 'strict'))",
    )
    ensure_column(
        conn,
        "workflow_runs",
        "record_mode",
        "TEXT NOT NULL DEFAULT 'planned' CHECK (record_mode IN ('lightweight', 'planned'))",
    )
    if migrated_legacy_record_mode:
        conn.execute(
            """
            UPDATE workflow_runs
            SET work_type = CASE record_mode WHEN 'lightweight' THEN 'answer' ELSE 'mixed' END,
                workflow_mode = CASE record_mode WHEN 'lightweight' THEN 'fast' ELSE 'standard' END
            """
        )
    ensure_column(conn, "approvals", "source", "TEXT NOT NULL DEFAULT 'unspecified'")
    ensure_column(conn, "items", "custom_fields_json", "TEXT NOT NULL DEFAULT '{}'")
    ensure_column(
        conn,
        "tasks",
        "execution_mode",
        "TEXT NOT NULL DEFAULT 'sequential' CHECK (execution_mode IN ('sequential', 'parallel'))",
    )
    ensure_column(
        conn,
        "tasks",
        "executor_kind",
        "TEXT NOT NULL DEFAULT 'main' CHECK (executor_kind IN ('main', 'subagent'))",
    )
    ensure_column(conn, "tasks", "parallel_group", "TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "tasks", "owned_paths_json", "TEXT NOT NULL DEFAULT '[]'")
    drop_column(conn, "tasks", "required_subagent")
    backfill_plan_rows(conn)
    dedupe_active_runs(conn)
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_single_active_run ON workflow_runs(status) WHERE status = 'active'"
    )
    set_schema_version(conn, SCHEMA_VERSION)
    set_meta(conn, "embedding_model", DEFAULT_EMBEDDING_MODEL)
    set_meta(conn, "embedding_dimension", str(DEFAULT_EMBEDDING_DIMENSION))
    conn.commit()


def ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in existing:
        try:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
        except sqlite3.OperationalError as exc:
            if "duplicate column name" not in str(exc).lower():
                raise


def migrate_legacy_workflow_mode(conn: sqlite3.Connection) -> bool:
    table = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'workflow_runs'"
    ).fetchone()
    if table is None:
        return False
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(workflow_runs)")}
    if "record_mode" in columns or "workflow_mode" not in columns:
        return False
    values = {
        str(row["workflow_mode"])
        for row in conn.execute("SELECT DISTINCT workflow_mode FROM workflow_runs")
    }
    if not values.issubset(set(RECORD_MODES)):
        return False
    conn.execute("ALTER TABLE workflow_runs RENAME COLUMN workflow_mode TO record_mode")
    return True


def drop_column(conn: sqlite3.Connection, table: str, column: str) -> None:
    existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column in existing:
        conn.execute(f"ALTER TABLE {table} DROP COLUMN {column}")


def backfill_plan_rows(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        INSERT INTO plans(item_id, plan_id, notes)
        SELECT i.id, i.stable_id, i.body
        FROM items i
        LEFT JOIN plans p ON p.item_id = i.id
        WHERE i.kind = 'plan'
          AND p.item_id IS NULL
        """
    )


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        """
        INSERT INTO meta(key, value) VALUES(?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """,
        (key, value),
    )


def set_schema_version(conn: sqlite3.Connection, version: int) -> None:
    conn.execute(
        """
        INSERT INTO meta(key, value) VALUES('schema_version', ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
        WHERE CAST(meta.value AS INTEGER) < CAST(excluded.value AS INTEGER)
        """,
        (str(version),),
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
    work_type: str = DEFAULT_WORK_TYPE,
    workflow_mode: str = DEFAULT_WORKFLOW_MODE,
) -> sqlite3.Row:
    if work_type not in WORK_TYPES:
        raise ValueError(f"invalid work_type: {work_type}")
    if workflow_mode not in WORKFLOW_MODES:
        raise ValueError(f"invalid workflow_mode: {workflow_mode}")
    record_mode = derive_record_mode(work_type, workflow_mode)
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
            INSERT INTO workflow_runs(
              id, slug, status, request_summary, work_type, workflow_mode, record_mode,
              created_at, updated_at
            )
            VALUES(?, ?, 'active', ?, ?, ?, ?, ?, ?)
            """,
            (run_id, slug, request_summary, work_type, workflow_mode, record_mode, now, now),
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
    work_type: str | None = None,
    workflow_mode: str | None = None,
) -> sqlite3.Row:
    run = active_run(conn)
    if not run:
        raise ValueError("no active workflow run to update")
    if result_summary is not None:
        execution_state = active_execution_state(conn, run_id=str(run["id"]))
        if execution_state["active_batches"]:
            raise ValueError(
                "cannot finish workflow run while an execution batch is active; "
                "settle every execution or recover/cancel the batch first"
            )
    if work_type is not None and work_type not in WORK_TYPES:
        raise ValueError(f"invalid work_type: {work_type}")
    if workflow_mode is not None and workflow_mode not in WORKFLOW_MODES:
        raise ValueError(f"invalid workflow_mode: {workflow_mode}")

    updates: list[str] = []
    params: list[Any] = []
    if request_summary is not None:
        updates.append("request_summary = ?")
        params.append(request_summary.strip())
    if result_summary is not None:
        updates.append("result_summary = ?")
        params.append(result_summary.strip())
    if work_type is not None:
        updates.append("work_type = ?")
        params.append(work_type)
    if workflow_mode is not None:
        updates.append("workflow_mode = ?")
        params.append(workflow_mode)
    if work_type is not None or workflow_mode is not None:
        next_work_type = work_type or str(run["work_type"])
        next_workflow_mode = workflow_mode or str(run["workflow_mode"])
        updates.append("record_mode = ?")
        params.append(derive_record_mode(next_work_type, next_workflow_mode))
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


def upsert_item(
    conn: sqlite3.Connection,
    *,
    kind: str,
    stable_id: str,
    title: str,
    body: str = "",
    raw_text: str = "",
    custom_fields: dict[str, Any] | None = None,
    status: str | None = None,
    source: str | None = None,
    run_id: str | None = None,
    archived: bool = False,
) -> sqlite3.Row:
    run = conn.execute("SELECT * FROM workflow_runs WHERE id = ?", (run_id,)).fetchone() if run_id else ensure_active_run(conn)
    existing = conn.execute(
        "SELECT custom_fields_json FROM items WHERE run_id = ? AND kind = ? AND stable_id = ?",
        (run["id"], kind, stable_id),
    ).fetchone()
    merged_custom_fields = merge_custom_fields(
        existing["custom_fields_json"] if existing is not None else None,
        custom_fields,
    )
    now = utc_now()
    conn.execute(
        """
        INSERT INTO items(
          run_id, stable_id, kind, title, body, raw_text, custom_fields_json,
          status, source, archived, created_at, updated_at
        )
        VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(run_id, kind, stable_id) DO UPDATE SET
          title = excluded.title,
          body = excluded.body,
          raw_text = excluded.raw_text,
          custom_fields_json = excluded.custom_fields_json,
          status = excluded.status,
          source = excluded.source,
          archived = excluded.archived,
          updated_at = excluded.updated_at
        """,
        (
            run["id"],
            stable_id,
            kind,
            title,
            body,
            raw_text,
            serialize_custom_fields(merged_custom_fields),
            status,
            source,
            1 if archived else 0,
            now,
            now,
        ),
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
        SELECT
          i.*,
          t.spec_id,
          t.goal,
          t.action,
          t.verification,
          t.result,
          t.blocker,
          t.next_action,
          t.execution_mode,
          t.executor_kind,
          t.parallel_group,
          t.owned_paths_json
        FROM items i
        LEFT JOIN tasks t ON t.item_id = i.id
        WHERE i.run_id = ? AND i.kind = 'task' AND i.stable_id = ?
        LIMIT 1
        """,
        (run["id"], task_id),
    ).fetchone()


def get_active_plan(conn: sqlite3.Connection, plan_id: str) -> sqlite3.Row | None:
    run = active_run(conn)
    if not run:
        return None
    return conn.execute(
        """
        SELECT
          i.*,
          p.plan_id,
          p.summary,
          p.objective,
          p.requirements_trace,
          p.selected_approach,
          p.affected_files,
          p.execution_order,
          p.risks,
          p.validation,
          p.approval_needs,
          p.notes
        FROM items i
        LEFT JOIN plans p ON p.item_id = i.id
        WHERE i.run_id = ? AND i.kind = 'plan' AND i.stable_id = ?
        LIMIT 1
        """,
        (run["id"], plan_id),
    ).fetchone()


def render_markdown_sections(fields: Iterable[tuple[str, str]]) -> str:
    parts = []
    for label, value in fields:
        text = str(value or "").strip()
        if text:
            parts.append(f"### {label}\n{text}")
    return "\n\n".join(parts)


def parse_custom_fields(value: Any) -> dict[str, Any]:
    if value is None or value == "":
        return {}
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid custom_fields JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError("custom_fields must be a JSON object")

    normalized: dict[str, Any] = {}
    for key, field_value in value.items():
        if not isinstance(key, str) or not key.strip():
            raise ValueError("custom_fields keys must be non-empty strings")
        normalized[key] = field_value
    try:
        json.dumps(normalized, ensure_ascii=False, sort_keys=True, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"custom_fields contains a non-JSON value: {exc}") from exc
    return normalized


def merge_custom_fields(existing: Any, patch: Any) -> dict[str, Any]:
    current = parse_custom_fields(existing)
    if patch is None:
        return current
    for key, value in parse_custom_fields(patch).items():
        if value is None:
            current.pop(key, None)
        else:
            current[key] = value
    return current


def serialize_custom_fields(value: Any) -> str:
    return json.dumps(
        parse_custom_fields(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def parse_owned_paths(value: Any) -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid owned_paths JSON: {exc}") from exc
    if not isinstance(value, list) or any(
        not isinstance(path, str) or not path.strip() for path in value
    ):
        raise ValueError("owned_paths must be an array of non-empty strings")
    return value


def serialize_owned_paths(value: Any) -> str:
    return json.dumps(
        parse_owned_paths(value),
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    )


def markdown_body_fields(record: str) -> tuple[tuple[str, str], ...]:
    from . import prompt as tapl_prompt

    return tapl_prompt.markdown_body_fields(record)


def render_plan_body(
    *,
    summary: str = "",
    objective: str = "",
    requirements_trace: str = "",
    selected_approach: str = "",
    affected_files: str = "",
    execution_order: str = "",
    risks: str = "",
    validation: str = "",
    approval_needs: str = "",
    notes: str = "",
) -> str:
    values = {
        "summary": summary,
        "objective": objective,
        "requirements_trace": requirements_trace,
        "selected_approach": selected_approach,
        "affected_files": affected_files,
        "execution_order": execution_order,
        "risks": risks,
        "validation": validation,
        "approval_needs": approval_needs,
        "notes": notes,
    }
    return render_markdown_sections((label, values[key]) for label, key in markdown_body_fields("plan"))


def render_task_body(
    *,
    goal: str = "",
    action: str = "",
    verification: str = "",
    result: str = "",
    blocker: str = "",
    next_action: str = "",
) -> str:
    values = {
        "goal": goal,
        "action": action,
        "verification": verification,
        "result": result,
        "blocker": blocker,
        "next_action": next_action,
    }
    return render_markdown_sections((label, values[key]) for label, key in markdown_body_fields("task"))


def upsert_plan(
    conn: sqlite3.Connection,
    *,
    plan_id: str,
    title: str,
    status: str,
    summary: str = "",
    objective: str = "",
    requirements_trace: str = "",
    selected_approach: str = "",
    affected_files: str = "",
    execution_order: str = "",
    risks: str = "",
    validation: str = "",
    approval_needs: str = "",
    notes: str = "",
    custom_fields: dict[str, Any] | None = None,
    raw_text: str = "",
    source: str | None = None,
    run_id: str | None = None,
    archived: bool = False,
) -> sqlite3.Row:
    body = render_plan_body(
        summary=summary,
        objective=objective,
        requirements_trace=requirements_trace,
        selected_approach=selected_approach,
        affected_files=affected_files,
        execution_order=execution_order,
        risks=risks,
        validation=validation,
        approval_needs=approval_needs,
        notes=notes,
    )
    item = upsert_item(
        conn,
        kind="plan",
        stable_id=plan_id,
        title=title,
        body=body,
        raw_text=raw_text,
        custom_fields=custom_fields,
        status=status,
        source=source,
        run_id=run_id,
        archived=archived,
    )
    conn.execute(
        """
        INSERT INTO plans(
          item_id,
          plan_id,
          summary,
          objective,
          requirements_trace,
          selected_approach,
          affected_files,
          execution_order,
          risks,
          validation,
          approval_needs,
          notes
        )
        VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(item_id) DO UPDATE SET
          plan_id = excluded.plan_id,
          summary = excluded.summary,
          objective = excluded.objective,
          requirements_trace = excluded.requirements_trace,
          selected_approach = excluded.selected_approach,
          affected_files = excluded.affected_files,
          execution_order = excluded.execution_order,
          risks = excluded.risks,
          validation = excluded.validation,
          approval_needs = excluded.approval_needs,
          notes = excluded.notes
        """,
        (
            item["id"],
            plan_id,
            summary,
            objective,
            requirements_trace,
            selected_approach,
            affected_files,
            execution_order,
            risks,
            validation,
            approval_needs,
            notes,
        ),
    )
    conn.execute(
        "UPDATE workflow_runs SET record_mode = 'planned', updated_at = ? WHERE id = ?",
        (utc_now(), item["run_id"]),
    )
    conn.commit()
    return item


def upsert_task(
    conn: sqlite3.Connection,
    *,
    task_id: str,
    title: str,
    status: str,
    spec_id: str = "",
    goal: str = "",
    action: str = "",
    verification: str = "",
    result: str = "",
    blocker: str = "",
    next_action: str = "",
    custom_fields: dict[str, Any] | None = None,
    execution_mode: str | None = None,
    executor_kind: str | None = None,
    parallel_group: str | None = None,
    owned_paths: Iterable[str] | None = None,
    depends_on: Iterable[str] | None = None,
) -> sqlite3.Row:
    if status not in TASK_STATUSES:
        raise ValueError(f"invalid task status: {status}")

    existing_task = get_active_task(conn, task_id)
    resolved_execution_mode = (
        execution_mode
        if execution_mode is not None
        else (existing_task["execution_mode"] if existing_task is not None else "sequential")
    )
    resolved_executor_kind = (
        executor_kind
        if executor_kind is not None
        else (existing_task["executor_kind"] if existing_task is not None else "main")
    )
    resolved_parallel_group = (
        parallel_group
        if parallel_group is not None
        else (existing_task["parallel_group"] if existing_task is not None else "")
    )
    resolved_owned_paths = (
        parse_owned_paths(list(owned_paths))
        if owned_paths is not None
        else parse_owned_paths(
            existing_task["owned_paths_json"] if existing_task is not None else []
        )
    )
    if resolved_execution_mode not in EXECUTION_MODES:
        raise ValueError(f"invalid execution_mode: {resolved_execution_mode}")
    if resolved_executor_kind not in EXECUTOR_KINDS:
        raise ValueError(f"invalid executor_kind: {resolved_executor_kind}")
    if resolved_execution_mode == "parallel" and not str(resolved_parallel_group).strip():
        raise ValueError("parallel tasks require a non-empty parallel_group")

    body = render_task_body(
        goal=goal,
        action=action,
        verification=verification,
        result=result,
        blocker=blocker,
        next_action=next_action,
    )
    item = upsert_item(
        conn,
        kind="task",
        stable_id=task_id,
        title=title,
        body=body,
        custom_fields=custom_fields,
        status=status,
    )
    conn.execute(
        """
        INSERT INTO tasks(
          item_id, task_id, spec_id, goal, action, verification, result, blocker, next_action,
          execution_mode, executor_kind, parallel_group, owned_paths_json
        )
        VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(item_id) DO UPDATE SET
          spec_id = excluded.spec_id,
          goal = excluded.goal,
          action = excluded.action,
          verification = excluded.verification,
          result = excluded.result,
          blocker = excluded.blocker,
          next_action = excluded.next_action,
          execution_mode = excluded.execution_mode,
          executor_kind = excluded.executor_kind,
          parallel_group = excluded.parallel_group,
          owned_paths_json = excluded.owned_paths_json
        """,
        (
            item["id"],
            task_id,
            spec_id,
            goal,
            action,
            verification,
            result,
            blocker,
            next_action,
            resolved_execution_mode,
            resolved_executor_kind,
            str(resolved_parallel_group),
            serialize_owned_paths(resolved_owned_paths),
        ),
    )
    conn.commit()
    if depends_on is not None:
        replace_task_dependencies(conn, task_id, depends_on)
    return item


def _begin_immediate(conn: sqlite3.Connection) -> None:
    if conn.in_transaction:
        raise RuntimeError("cannot start an atomic workflow operation inside an open transaction")
    conn.execute("BEGIN IMMEDIATE")


def get_task_dependencies(conn: sqlite3.Connection, task_id: str) -> list[str]:
    run = active_run(conn)
    if not run:
        raise ValueError("no active workflow run")
    task = conn.execute(
        """
        SELECT i.id
        FROM items i
        JOIN tasks t ON t.item_id = i.id
        WHERE i.run_id = ? AND i.kind = 'task' AND i.stable_id = ?
        """,
        (run["id"], task_id),
    ).fetchone()
    if task is None:
        raise ValueError(f"unknown task in active run: {task_id}")
    return [
        row["stable_id"]
        for row in conn.execute(
            """
            SELECT dependency.stable_id
            FROM task_dependencies td
            JOIN items dependency ON dependency.id = td.dependency_item_id
            WHERE td.task_item_id = ?
            ORDER BY dependency.stable_id
            """,
            (task["id"],),
        )
    ]


def replace_task_dependencies(
    conn: sqlite3.Connection,
    task_id: str,
    dependency_task_ids: Iterable[str],
) -> list[str]:
    dependencies = list(dict.fromkeys(str(value).strip() for value in dependency_task_ids))
    if any(not dependency for dependency in dependencies):
        raise ValueError("dependency task ids must be non-empty")
    if task_id in dependencies:
        raise ValueError(f"task cannot depend on itself: {task_id}")

    _begin_immediate(conn)
    try:
        run = active_run(conn)
        if not run:
            raise ValueError("no active workflow run")
        task = conn.execute(
            """
            SELECT i.id
            FROM items i
            JOIN tasks t ON t.item_id = i.id
            WHERE i.run_id = ? AND i.kind = 'task' AND i.stable_id = ?
            """,
            (run["id"], task_id),
        ).fetchone()
        if task is None:
            raise ValueError(f"unknown task in active run: {task_id}")

        dependency_rows: dict[str, sqlite3.Row] = {}
        if dependencies:
            placeholders = ", ".join("?" for _ in dependencies)
            rows = conn.execute(
                f"""
                SELECT i.id, i.stable_id
                FROM items i
                JOIN tasks t ON t.item_id = i.id
                WHERE i.run_id = ?
                  AND i.kind = 'task'
                  AND i.stable_id IN ({placeholders})
                """,
                (run["id"], *dependencies),
            ).fetchall()
            dependency_rows = {row["stable_id"]: row for row in rows}
            unknown = [dependency for dependency in dependencies if dependency not in dependency_rows]
            if unknown:
                raise ValueError(f"unknown dependency task(s) in active run: {', '.join(unknown)}")

        conn.execute("DELETE FROM task_dependencies WHERE task_item_id = ?", (task["id"],))
        conn.executemany(
            """
            INSERT INTO task_dependencies(task_item_id, dependency_item_id)
            VALUES(?, ?)
            """,
            [(task["id"], dependency_rows[dependency]["id"]) for dependency in dependencies],
        )
        cycle = conn.execute(
            """
            WITH RECURSIVE reachable(item_id) AS (
              SELECT dependency_item_id
              FROM task_dependencies
              WHERE task_item_id = ?
              UNION
              SELECT td.dependency_item_id
              FROM task_dependencies td
              JOIN reachable r ON td.task_item_id = r.item_id
            )
            SELECT 1 FROM reachable WHERE item_id = ? LIMIT 1
            """,
            (task["id"], task["id"]),
        ).fetchone()
        if cycle is not None:
            raise ValueError(f"dependency cycle detected for task: {task_id}")
        conn.commit()
    except Exception:
        if conn.in_transaction:
            conn.rollback()
        raise
    return get_task_dependencies(conn, task_id)


def _normalize_owned_path(path: str) -> str:
    normalized_parts: list[str] = []
    for part in path.strip().replace("\\", "/").split("/"):
        if not part or part == ".":
            continue
        if part == ".." and normalized_parts and normalized_parts[-1] != "..":
            normalized_parts.pop()
        else:
            normalized_parts.append(part)
    return "/".join(normalized_parts)


def _owned_paths_overlap(left: str, right: str) -> bool:
    left_path = _normalize_owned_path(left)
    right_path = _normalize_owned_path(right)
    if not left_path or not right_path:
        return False
    return (
        left_path == right_path
        or left_path.startswith(f"{right_path}/")
        or right_path.startswith(f"{left_path}/")
    )


def execution_batch_payload(conn: sqlite3.Connection, batch_id: str) -> dict[str, Any] | None:
    batch = conn.execute(
        "SELECT * FROM execution_batches WHERE id = ?",
        (batch_id,),
    ).fetchone()
    if batch is None:
        return None
    executions: list[dict[str, Any]] = []
    for row in conn.execute(
        """
        SELECT
          te.id AS execution_id,
          te.batch_id,
          te.state AS execution_state,
          te.executor_ref,
          te.model,
          te.reasoning_effort,
          te.result AS execution_result,
          te.error AS execution_error,
          te.started_at,
          te.finished_at,
          i.id AS task_item_id,
          i.stable_id AS task_id,
          i.title,
          i.status AS task_status,
          t.spec_id,
          t.goal,
          t.action,
          t.verification,
          t.execution_mode,
          t.executor_kind,
          t.parallel_group,
          t.owned_paths_json
        FROM task_executions te
        JOIN tasks t ON t.item_id = te.task_item_id
        JOIN items i ON i.id = t.item_id
        WHERE te.batch_id = ?
        ORDER BY i.stable_id
        """,
        (batch_id,),
    ):
        executions.append(row_to_dict(row))
    batch_data = row_to_dict(batch)
    batch_data["batch_id"] = batch_data["id"]
    return {"batch": batch_data, "executions": executions}


def dispatch_tasks(
    conn: sqlite3.Connection,
    task_ids: Iterable[str],
    *,
    batch_id: str | None = None,
    failure_policy: str = DEFAULT_FAILURE_POLICY,
    execution_metadata: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    requested_task_ids = [str(task_id).strip() for task_id in task_ids]
    if len(requested_task_ids) < 2:
        raise ValueError("parallel dispatch requires at least two tasks")
    if any(not task_id for task_id in requested_task_ids):
        raise ValueError("task ids must be non-empty")
    if len(set(requested_task_ids)) != len(requested_task_ids):
        raise ValueError("parallel dispatch task ids must be unique")
    if batch_id is not None and not batch_id.strip():
        raise ValueError("batch_id must be non-empty")
    if not failure_policy.strip():
        raise ValueError("failure_policy must be non-empty")
    metadata = execution_metadata or {}
    if not isinstance(metadata, dict) or any(
        not isinstance(task_metadata, dict) for task_metadata in metadata.values()
    ):
        raise ValueError("execution_metadata must map task ids to JSON objects")

    resolved_batch_id = batch_id.strip() if batch_id is not None else str(uuid.uuid4())
    _begin_immediate(conn)
    try:
        run = active_run(conn)
        if not run:
            raise ValueError("no active workflow run")

        existing_batch = execution_batch_payload(conn, resolved_batch_id)
        if existing_batch is not None:
            if existing_batch["batch"]["run_id"] != run["id"]:
                raise ValueError(f"batch_id belongs to another workflow run: {resolved_batch_id}")
            existing_task_ids = {
                execution["task_id"] for execution in existing_batch["executions"]
            }
            if existing_task_ids != set(requested_task_ids):
                raise ValueError(
                    f"batch_id was already used for a different task set: {resolved_batch_id}"
                )
            conn.commit()
            return existing_batch

        placeholders = ", ".join("?" for _ in requested_task_ids)
        rows = conn.execute(
            f"""
            SELECT
              i.id AS item_id,
              i.stable_id AS task_id,
              i.title,
              i.status,
              t.spec_id,
              t.goal,
              t.action,
              t.verification,
              t.execution_mode,
              t.executor_kind,
              t.parallel_group,
              t.owned_paths_json
            FROM items i
            JOIN tasks t ON t.item_id = i.id
            WHERE i.run_id = ?
              AND i.kind = 'task'
              AND i.stable_id IN ({placeholders})
            """,
            (run["id"], *requested_task_ids),
        ).fetchall()
        rows_by_task_id = {row["task_id"]: row for row in rows}
        unknown = [task_id for task_id in requested_task_ids if task_id not in rows_by_task_id]
        if unknown:
            raise ValueError(f"unknown task(s) in active run: {', '.join(unknown)}")
        ordered_rows = [rows_by_task_id[task_id] for task_id in requested_task_ids]

        spec_ids = {str(row["spec_id"] or "").strip() for row in ordered_rows}
        if len(spec_ids) != 1 or not next(iter(spec_ids)):
            raise ValueError("parallel dispatch tasks must belong to the same plan")
        spec_id = next(iter(spec_ids))
        plan = conn.execute(
            """
            SELECT i.id
            FROM items i
            JOIN plans p ON p.item_id = i.id
            WHERE i.run_id = ? AND i.kind = 'plan' AND i.stable_id = ?
            """,
            (run["id"], spec_id),
        ).fetchone()
        if plan is None:
            raise ValueError(f"parallel dispatch plan is not in the active run: {spec_id}")

        groups = {str(row["parallel_group"] or "").strip() for row in ordered_rows}
        if len(groups) != 1 or not next(iter(groups)):
            raise ValueError("parallel dispatch tasks must have the same non-empty parallel_group")
        parallel_group = next(iter(groups))
        invalid_statuses = [
            f"{row['task_id']}={row['status']}" for row in ordered_rows if row["status"] != "Pending"
        ]
        if invalid_statuses:
            raise ValueError(
                "parallel dispatch requires Pending tasks: " + ", ".join(invalid_statuses)
            )
        invalid_contracts = [
            row["task_id"]
            for row in ordered_rows
            if row["execution_mode"] != "parallel" or row["executor_kind"] != "subagent"
        ]
        if invalid_contracts:
            raise ValueError(
                "parallel dispatch requires execution_mode=parallel and executor_kind=subagent: "
                + ", ".join(invalid_contracts)
            )

        approval = conn.execute(
            """
            SELECT *
            FROM approvals
            WHERE run_id = ? AND kind = ?
            ORDER BY decided_at DESC, id DESC
            LIMIT 1
            """,
            (run["id"], DEFAULT_APPROVAL_KIND),
        ).fetchone()
        if approval is None or approval["decision"] != "approved":
            raise ValueError("parallel dispatch requires execution approval for the active run")

        task_item_ids = [row["item_id"] for row in ordered_rows]
        item_placeholders = ", ".join("?" for _ in task_item_ids)
        unmet_dependencies = conn.execute(
            f"""
            SELECT target.stable_id AS task_id,
                   dependency.stable_id AS dependency_id,
                   dependency.status AS dependency_status,
                   dependency.run_id AS dependency_run_id
            FROM task_dependencies td
            JOIN items target ON target.id = td.task_item_id
            JOIN items dependency ON dependency.id = td.dependency_item_id
            WHERE td.task_item_id IN ({item_placeholders})
              AND (dependency.run_id <> ? OR dependency.status <> 'Completed')
            ORDER BY target.stable_id, dependency.stable_id
            """,
            (*task_item_ids, run["id"]),
        ).fetchall()
        if unmet_dependencies:
            details = ", ".join(
                f"{row['task_id']}->{row['dependency_id']}({row['dependency_status']})"
                for row in unmet_dependencies
            )
            raise ValueError(f"parallel dispatch has unmet dependencies: {details}")

        active_executions = conn.execute(
            f"""
            SELECT i.stable_id AS task_id
            FROM task_executions te
            JOIN items i ON i.id = te.task_item_id
            WHERE te.task_item_id IN ({item_placeholders})
              AND te.state IN ('dispatched', 'running')
            """,
            tuple(task_item_ids),
        ).fetchall()
        if active_executions:
            raise ValueError(
                "task already has an active execution: "
                + ", ".join(row["task_id"] for row in active_executions)
            )

        declared_scopes = [
            (row["task_id"], owned_path)
            for row in ordered_rows
            for owned_path in parse_owned_paths(row["owned_paths_json"])
        ]
        active_scope_rows = conn.execute(
            f"""
            SELECT i.stable_id AS task_id, t.owned_paths_json
            FROM task_executions te
            JOIN execution_batches b ON b.id = te.batch_id
            JOIN tasks t ON t.item_id = te.task_item_id
            JOIN items i ON i.id = t.item_id
            WHERE b.run_id = ?
              AND te.state IN ('dispatched', 'running')
              AND te.task_item_id NOT IN ({item_placeholders})
            """,
            (run["id"], *task_item_ids),
        ).fetchall()
        active_scopes = [
            (row["task_id"], owned_path)
            for row in active_scope_rows
            for owned_path in parse_owned_paths(row["owned_paths_json"])
        ]
        scope_conflicts: list[str] = []
        for index, (left_task, left_path) in enumerate(declared_scopes):
            for right_task, right_path in declared_scopes[index + 1 :] + active_scopes:
                if left_task != right_task and _owned_paths_overlap(left_path, right_path):
                    scope_conflicts.append(
                        f"{left_task}:{left_path} overlaps {right_task}:{right_path}"
                    )
        if scope_conflicts:
            raise ValueError("owned path conflict: " + "; ".join(scope_conflicts))

        now = utc_now()
        conn.execute(
            """
            INSERT INTO execution_batches(
              id, run_id, parallel_group, state, failure_policy, approval_id, created_at
            )
            VALUES(?, ?, ?, 'active', ?, ?, ?)
            """,
            (
                resolved_batch_id,
                run["id"],
                parallel_group,
                failure_policy,
                approval["id"],
                now,
            ),
        )
        for row in ordered_rows:
            updated = conn.execute(
                """
                UPDATE items
                SET status = 'In Progress', updated_at = ?
                WHERE id = ? AND status = 'Pending'
                """,
                (now, row["item_id"]),
            )
            if updated.rowcount != 1:
                raise RuntimeError(f"task status changed during dispatch: {row['task_id']}")
            task_metadata = metadata.get(row["task_id"], {})
            conn.execute(
                """
                INSERT INTO task_executions(
                  id, batch_id, task_item_id, state, executor_ref, model,
                  reasoning_effort, started_at
                )
                VALUES(?, ?, ?, 'dispatched', ?, ?, ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    resolved_batch_id,
                    row["item_id"],
                    str(task_metadata.get("executor_ref") or ""),
                    str(task_metadata.get("model") or ""),
                    str(task_metadata.get("reasoning_effort") or ""),
                    now,
                ),
            )
        conn.execute(
            "UPDATE workflow_runs SET updated_at = ? WHERE id = ?",
            (now, run["id"]),
        )
        payload = execution_batch_payload(conn, resolved_batch_id)
        conn.commit()
        return payload  # type: ignore[return-value]
    except Exception:
        if conn.in_transaction:
            conn.rollback()
        raise


def _recompute_execution_batch(
    conn: sqlite3.Connection,
    batch_id: str,
    *,
    now: str,
) -> str:
    states = [
        row["state"]
        for row in conn.execute(
            "SELECT state FROM task_executions WHERE batch_id = ?",
            (batch_id,),
        )
    ]
    if any(state in ACTIVE_EXECUTION_STATES for state in states):
        batch_state = "active"
        finished_at = None
    elif any(state == "blocked" for state in states):
        batch_state = "blocked"
        finished_at = now
    elif any(state == "cancelled" for state in states):
        batch_state = "cancelled"
        finished_at = now
    else:
        batch_state = "completed"
        finished_at = now
    conn.execute(
        "UPDATE execution_batches SET state = ?, finished_at = ? WHERE id = ?",
        (batch_state, finished_at, batch_id),
    )
    return batch_state


def settle_task_execution(
    conn: sqlite3.Connection,
    execution_id: str,
    *,
    task_status: str,
    task_id: str | None = None,
    verification: str | None = None,
    result: str | None = None,
    blocker: str | None = None,
    next_action: str | None = None,
    error: str = "",
    custom_fields: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if task_status not in TERMINAL_TASK_STATUSES:
        raise ValueError(
            "parallel execution settlement status must be Completed, Blocked, or Skipped"
        )
    execution_state = task_status.lower()
    _begin_immediate(conn)
    try:
        row = conn.execute(
            """
            SELECT
              te.id AS execution_id,
              te.batch_id,
              te.state AS execution_state,
              te.task_item_id,
              b.run_id,
              i.status AS task_status,
              i.stable_id AS task_id,
              i.custom_fields_json,
              t.goal,
              t.action,
              t.verification,
              t.result,
              t.blocker,
              t.next_action
            FROM task_executions te
            JOIN execution_batches b ON b.id = te.batch_id
            JOIN tasks t ON t.item_id = te.task_item_id
            JOIN items i ON i.id = t.item_id
            WHERE te.id = ?
            """,
            (execution_id,),
        ).fetchone()
        if row is None:
            raise ValueError(f"unknown execution_id: {execution_id}")
        run = active_run(conn)
        if run is None or row["run_id"] != run["id"]:
            raise ValueError("execution does not belong to the active workflow run")
        if task_id is not None and row["task_id"] != task_id:
            raise ValueError(
                f"execution_id belongs to {row['task_id']}, not expected task {task_id}"
            )
        if row["execution_state"] not in ACTIVE_EXECUTION_STATES:
            raise ValueError(
                f"execution is no longer active: {execution_id}={row['execution_state']}"
            )
        if row["task_status"] != "In Progress":
            raise ValueError(
                f"execution task is not In Progress: {row['task_id']}={row['task_status']}"
            )

        resolved_verification = row["verification"] if verification is None else verification
        resolved_result = row["result"] if result is None else result
        resolved_blocker = row["blocker"] if blocker is None else blocker
        resolved_next_action = row["next_action"] if next_action is None else next_action
        resolved_custom_fields = merge_custom_fields(
            row["custom_fields_json"],
            custom_fields,
        )
        if task_status in ("Completed", "Skipped") and blocker is None:
            resolved_blocker = ""
        if task_status == "Completed" and next_action is None:
            resolved_next_action = ""
        now = utc_now()
        execution_update = conn.execute(
            """
            UPDATE task_executions
            SET state = ?, result = ?, error = ?, finished_at = ?
            WHERE id = ? AND state IN ('dispatched', 'running')
            """,
            (execution_state, resolved_result, error, now, execution_id),
        )
        if execution_update.rowcount != 1:
            raise RuntimeError(f"execution changed during settlement: {execution_id}")
        conn.execute(
            """
            UPDATE tasks
            SET verification = ?, result = ?, blocker = ?, next_action = ?
            WHERE item_id = ?
            """,
            (
                resolved_verification,
                resolved_result,
                resolved_blocker,
                resolved_next_action,
                row["task_item_id"],
            ),
        )
        body = render_task_body(
            goal=row["goal"],
            action=row["action"],
            verification=resolved_verification,
            result=resolved_result,
            blocker=resolved_blocker,
            next_action=resolved_next_action,
        )
        task_update = conn.execute(
            """
            UPDATE items
            SET status = ?, body = ?, custom_fields_json = ?, updated_at = ?
            WHERE id = ? AND status = 'In Progress'
            """,
            (
                task_status,
                body,
                serialize_custom_fields(resolved_custom_fields),
                now,
                row["task_item_id"],
            ),
        )
        if task_update.rowcount != 1:
            raise RuntimeError(f"task changed during settlement: {row['task_id']}")
        refreshed_item = conn.execute(
            "SELECT * FROM items WHERE id = ?",
            (row["task_item_id"],),
        ).fetchone()
        refresh_item_fts(conn, refreshed_item)
        _recompute_execution_batch(conn, row["batch_id"], now=now)
        conn.execute(
            "UPDATE workflow_runs SET updated_at = ? WHERE id = ?",
            (now, run["id"]),
        )
        payload = execution_batch_payload(conn, row["batch_id"])
        conn.commit()
        return payload  # type: ignore[return-value]
    except Exception:
        if conn.in_transaction:
            conn.rollback()
        raise


def cancel_execution_batch(
    conn: sqlite3.Connection,
    batch_id: str,
    *,
    reason: str = "",
    recover_pending: bool = True,
) -> dict[str, Any]:
    _begin_immediate(conn)
    try:
        batch = conn.execute(
            "SELECT * FROM execution_batches WHERE id = ?",
            (batch_id,),
        ).fetchone()
        if batch is None:
            raise ValueError(f"unknown execution batch: {batch_id}")
        run = active_run(conn)
        if run is None or batch["run_id"] != run["id"]:
            raise ValueError("execution batch does not belong to the active workflow run")
        active_rows = conn.execute(
            """
            SELECT
              te.id AS execution_id,
              te.task_item_id,
              i.stable_id AS task_id,
              i.status AS task_status,
              t.goal,
              t.action,
              t.verification,
              t.result,
              t.blocker,
              t.next_action
            FROM task_executions te
            JOIN tasks t ON t.item_id = te.task_item_id
            JOIN items i ON i.id = t.item_id
            WHERE te.batch_id = ?
              AND te.state IN ('dispatched', 'running')
            ORDER BY i.stable_id
            """,
            (batch_id,),
        ).fetchall()
        if not active_rows:
            if batch["state"] == "cancelled":
                payload = execution_batch_payload(conn, batch_id)
                conn.commit()
                return payload  # type: ignore[return-value]
            raise ValueError(f"execution batch has no active executions: {batch_id}")
        invalid_tasks = [
            f"{row['task_id']}={row['task_status']}"
            for row in active_rows
            if row["task_status"] != "In Progress"
        ]
        if invalid_tasks:
            raise ValueError(
                "cannot recover executions whose tasks are not In Progress: "
                + ", ".join(invalid_tasks)
            )

        now = utc_now()
        cancellation_reason = reason.strip() or "Execution batch cancelled"
        for row in active_rows:
            execution_update = conn.execute(
                """
                UPDATE task_executions
                SET state = 'cancelled', error = ?, finished_at = ?
                WHERE id = ? AND state IN ('dispatched', 'running')
                """,
                (cancellation_reason, now, row["execution_id"]),
            )
            if execution_update.rowcount != 1:
                raise RuntimeError(
                    f"execution changed during batch cancellation: {row['execution_id']}"
                )
            task_status = "Pending" if recover_pending else "Blocked"
            task_blocker = "" if recover_pending else cancellation_reason
            existing_next_action = str(row["next_action"] or "")
            task_next_action = (
                ""
                if recover_pending
                else (
                    existing_next_action
                    if existing_next_action.strip()
                    else DEFAULT_CANCELLED_NEXT_ACTION
                )
            )
            conn.execute(
                """
                UPDATE tasks
                SET blocker = ?, next_action = ?
                WHERE item_id = ?
                """,
                (task_blocker, task_next_action, row["task_item_id"]),
            )
            body = render_task_body(
                goal=row["goal"],
                action=row["action"],
                verification=row["verification"],
                result=row["result"],
                blocker=task_blocker,
                next_action=task_next_action,
            )
            task_update = conn.execute(
                """
                UPDATE items
                SET status = ?, body = ?, updated_at = ?
                WHERE id = ? AND status = 'In Progress'
                """,
                (task_status, body, now, row["task_item_id"]),
            )
            if task_update.rowcount != 1:
                raise RuntimeError(f"task changed during batch cancellation: {row['task_id']}")
            refreshed_item = conn.execute(
                "SELECT * FROM items WHERE id = ?",
                (row["task_item_id"],),
            ).fetchone()
            refresh_item_fts(conn, refreshed_item)
        conn.execute(
            """
            UPDATE execution_batches
            SET state = 'cancelled', finished_at = ?
            WHERE id = ?
            """,
            (now, batch_id),
        )
        conn.execute(
            "UPDATE workflow_runs SET updated_at = ? WHERE id = ?",
            (now, run["id"]),
        )
        payload = execution_batch_payload(conn, batch_id)
        conn.commit()
        return payload  # type: ignore[return-value]
    except Exception:
        if conn.in_transaction:
            conn.rollback()
        raise


def recover_execution_batch(
    conn: sqlite3.Connection,
    batch_id: str,
    *,
    reason: str = "",
) -> dict[str, Any]:
    return cancel_execution_batch(
        conn,
        batch_id,
        reason=reason or "Recovered stale execution batch",
        recover_pending=True,
    )


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
    source: str = DEFAULT_APPROVAL_SOURCE,
    run_id: str | None = None,
) -> sqlite3.Row:
    if decision not in APPROVAL_DECISIONS:
        raise ValueError(f"invalid approval decision: {decision}")
    if source not in APPROVAL_SOURCES:
        raise ValueError(f"invalid approval source: {source}")

    run = conn.execute("SELECT * FROM workflow_runs WHERE id = ?", (run_id,)).fetchone() if run_id else active_run(conn)
    if not run:
        raise ValueError("no active workflow run for approval")

    now = utc_now()
    conn.execute(
        """
        INSERT INTO approvals(run_id, kind, prompt, decision, source, decided_at)
        VALUES(?, ?, ?, ?, ?, ?)
        """,
        (run["id"], kind, prompt, decision, source, now),
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
            "source": "",
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
            "source": "",
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
        "source": row["source"],
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
            "\n".join(
                part
                for part in [item["body"], item["raw_text"], custom_fields_search_text(item["custom_fields_json"])]
                if part
            ),
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
    execution_state = active_execution_state(conn, run_id=str(run["id"]))
    if execution_state["active_batches"]:
        raise ValueError(
            "cannot archive workflow run while an execution batch is active; "
            "settle every execution or recover/cancel the batch first"
        )

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


def active_execution_state(
    conn: sqlite3.Connection,
    *,
    run_id: str | None,
) -> dict[str, list[dict[str, Any]]]:
    """Return active or internally inconsistent execution state for one run."""
    if not run_id:
        return {"active_batches": [], "active_executions": []}

    batch_ids = [
        row["id"]
        for row in conn.execute(
            """
            SELECT DISTINCT b.id, b.created_at
            FROM execution_batches b
            LEFT JOIN task_executions te ON te.batch_id = b.id
            WHERE b.run_id = ?
              AND (
                b.state = 'active'
                OR te.state IN ('dispatched', 'running')
              )
            ORDER BY b.created_at, b.id
            """,
            (run_id,),
        )
    ]
    batches: list[dict[str, Any]] = []
    active_executions: list[dict[str, Any]] = []
    for batch_id in batch_ids:
        payload = execution_batch_payload(conn, batch_id)
        if payload is None:
            continue
        batches.append(payload)
        for execution in payload["executions"]:
            if execution.get("execution_state") in ACTIVE_EXECUTION_STATES:
                active_executions.append(
                    {
                        **execution,
                        "batch_state": payload["batch"].get("state"),
                        "parallel_group": payload["batch"].get("parallel_group"),
                    }
                )
    return {
        "active_batches": batches,
        "active_executions": active_executions,
    }


def status_payload(conn: sqlite3.Connection) -> dict[str, Any]:
    run = active_run(conn)
    run_id = run["id"] if run else None
    task_counts = {status: 0 for status in TASK_STATUSES}
    tasks: list[dict[str, Any]] = []
    plans: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []
    dependency_ids: dict[int, list[str]] = {}

    if run_id:
        for row in conn.execute(
            """
            SELECT td.task_item_id, dependency.stable_id AS dependency_id
            FROM task_dependencies td
            JOIN items target ON target.id = td.task_item_id
            JOIN items dependency ON dependency.id = td.dependency_item_id
            WHERE target.run_id = ?
            ORDER BY target.stable_id, dependency.stable_id
            """,
            (run_id,),
        ):
            dependency_ids.setdefault(int(row["task_item_id"]), []).append(
                str(row["dependency_id"])
            )
        for row in conn.execute(
            """
            SELECT
              i.*,
              t.spec_id,
              t.goal,
              t.action,
              t.verification,
              t.result,
              t.blocker,
              t.next_action,
              t.execution_mode,
              t.executor_kind,
              t.parallel_group,
              t.owned_paths_json
            FROM items i
            LEFT JOIN tasks t ON t.item_id = i.id
            WHERE i.run_id = ? AND i.kind = 'task'
            ORDER BY i.stable_id
            """,
            (run_id,),
        ):
            task_counts[row["status"]] = task_counts.get(row["status"], 0) + 1
            task = row_to_dict(row)
            task["depends_on"] = dependency_ids.get(int(row["id"]), [])
            tasks.append(task)

        plans = [
            row_to_dict(row)
            for row in conn.execute(
                """
                SELECT
                  i.*,
                  p.plan_id,
                  p.summary,
                  p.objective,
                  p.requirements_trace,
                  p.selected_approach,
                  p.affected_files,
                  p.execution_order,
                  p.risks,
                  p.validation,
                  p.approval_needs,
                  p.notes
                FROM items i
                LEFT JOIN plans p ON p.item_id = i.id
                WHERE i.run_id = ? AND i.kind = 'plan'
                ORDER BY i.stable_id
                """,
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
    execution_state = active_execution_state(conn, run_id=run_id)
    executions_by_task = {
        str(execution["task_id"]): execution
        for execution in execution_state["active_executions"]
    }
    for task in tasks:
        task["active_execution"] = executions_by_task.get(str(task.get("stable_id") or ""))

    return {
        "schema": get_meta(conn),
        "active_run": workflow_run_to_dict(run),
        "approvals": {
            DEFAULT_APPROVAL_KIND: approval_status(conn, kind=DEFAULT_APPROVAL_KIND, run_id=run_id),
        },
        "task_counts": task_counts,
        "incomplete_tasks": incomplete,
        "plans": plans,
        "tasks": tasks,
        **execution_state,
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
              t.verification,
              t.result,
              t.blocker,
              t.next_action,
              t.execution_mode,
              t.executor_kind,
              t.parallel_group,
              t.owned_paths_json,
              p.plan_id,
              p.summary,
              p.objective,
              p.requirements_trace,
              p.selected_approach,
              p.affected_files,
              p.execution_order,
              p.risks,
              p.validation,
              p.approval_needs,
              p.notes,
              f.related_ids,
              f.impact
            FROM items i
            LEFT JOIN tasks t ON t.item_id = i.id
            LEFT JOIN plans p ON p.item_id = i.id
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
          t.verification,
          t.result,
          t.blocker,
          t.next_action,
          t.execution_mode,
          t.executor_kind,
          t.parallel_group,
          t.owned_paths_json,
          p.plan_id,
          p.summary,
          p.objective,
          p.requirements_trace,
          p.selected_approach,
          p.affected_files,
          p.execution_order,
          p.risks,
          p.validation,
          p.approval_needs,
          p.notes,
          f.related_ids,
          f.impact
        FROM items i
        JOIN workflow_runs r ON r.id = i.run_id
        LEFT JOIN archives a ON a.run_id = i.run_id
        LEFT JOIN tasks t ON t.item_id = i.id
        LEFT JOIN plans p ON p.item_id = i.id
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
    fts_queries = build_fts_queries(query)
    if not fts_queries:
        return search_word(conn, query, limit=limit)

    results: list[dict[str, Any]] = []
    seen_ids: set[int] = set()
    # Tiers are ordered from strictest to broadest; BM25 ranks within each tier.
    for fts_query in fts_queries:
        rows = conn.execute(
            """
            -- items_fts columns: stable_id, kind, title, body
            SELECT i.*, bm25(items_fts, 6.0, 1.0, 4.0, 1.0) AS score
            FROM items_fts
            JOIN items i ON i.id = items_fts.rowid
            WHERE items_fts MATCH ?
            ORDER BY score
            LIMIT ?
            """,
            (fts_query, limit),
        ).fetchall()
        for row in rows:
            if row["id"] in seen_ids:
                continue
            seen_ids.add(row["id"])
            results.append(search_row(row, "bm25"))
            if len(results) == limit:
                return results
    return results


def search_word(conn: sqlite3.Connection, query: str, limit: int = 10) -> list[dict[str, Any]]:
    like = f"%{query}%"
    rows = conn.execute(
        """
        SELECT *, 0.0 AS score
        FROM items
        WHERE title LIKE ? OR body LIKE ? OR raw_text LIKE ? OR custom_fields_json LIKE ? OR stable_id LIKE ?
        ORDER BY updated_at DESC
        LIMIT ?
        """,
        (like, like, like, like, like, limit),
    ).fetchall()
    return [search_row(row, "word") for row in rows]


def build_fts_query(query: str) -> str:
    terms = re.findall(r"[\w가-힣]+", query, flags=re.UNICODE)
    return " OR ".join(f'"{term}"*' for term in terms[:8])


def build_fts_queries(query: str) -> list[str]:
    terms = re.findall(r"[\w가-힣]+", query, flags=re.UNICODE)[:8]
    if not terms:
        return []

    exact_terms = [f'"{term}"' for term in terms]
    prefix_terms = [f'"{term}"*' for term in terms]
    candidates = []
    if len(terms) > 1:
        candidates.append(f'"{" ".join(terms)}"')
    candidates.extend(
        [
            " AND ".join(exact_terms),
            " AND ".join(prefix_terms),
            build_fts_query(query),
        ]
    )
    return list(dict.fromkeys(candidates))


def search_row(row: sqlite3.Row, source: str) -> dict[str, Any]:
    data = row_to_dict(row)
    custom_fields_text = custom_fields_search_text(data.get("custom_fields"))
    snippet_source = "\n".join(
        part for part in [data.get("body") or data.get("raw_text") or "", custom_fields_text] if part
    )
    return {
        "id": data.get("id"),
        "stable_id": data.get("stable_id"),
        "kind": data.get("kind"),
        "title": data.get("title"),
        "status": data.get("status"),
        "source": data.get("source"),
        "score": data.get("score"),
        "search_source": source,
        "snippet": make_snippet(snippet_source),
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


def custom_fields_search_text(value: Any) -> str:
    custom_fields = parse_custom_fields(value)
    if not custom_fields:
        return ""
    return json.dumps(custom_fields, ensure_ascii=False, sort_keys=True, allow_nan=False)


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    data = {key: row[key] for key in row.keys()}
    if "custom_fields_json" in data:
        data["custom_fields"] = parse_custom_fields(data.pop("custom_fields_json"))
    if "owned_paths_json" in data:
        data["owned_paths"] = parse_owned_paths(data.pop("owned_paths_json"))
    return data


def workflow_run_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    data = row_to_dict(row)
    if data is None:
        return None
    return {field: data.get(field) for field in WORKFLOW_RUN_OUTPUT_FIELDS if field in data}
