"""In-process application boundary for TAPL workflow clients.

The MCP server, viewer, and other agent-facing adapters use this module instead
of invoking :mod:`taplctl.cli` in a child process.  Every public call owns one
SQLite connection so callers may safely run methods in worker threads.
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from . import config, context as tapl_context, db, embeddings, recommendations, validation


UNSET = object()


class WorkflowApplicationError(RuntimeError):
    """An actionable application-layer failure suitable for an MCP tool error."""


class WorkflowApplication:
    """Typed, synchronous workflow use cases bound to one workspace."""

    def __init__(self, workspace_root: Path) -> None:
        self.workspace_root = workspace_root.expanduser().resolve()
        self.db_path = self.workspace_root / db.DEFAULT_DB_RELATIVE

    @contextmanager
    def _connection(self) -> Iterator[Any]:
        conn = db.connect(self.db_path)
        try:
            yield conn
        finally:
            conn.close()

    def _settings(self) -> config.TaplConfig:
        return config.load(start=self.workspace_root)

    @staticmethod
    def _field(existing: Any, name: str, value: Any, default: str = "") -> str:
        if value is not UNSET and value is not None:
            return str(value)
        if existing is None:
            return default
        stored = existing[name]
        return "" if stored is None else str(stored)

    @staticmethod
    def _active_execution_id(conn: Any, task_id: str) -> str | None:
        run = db.active_run(conn)
        if run is None:
            return None
        row = conn.execute(
            """
            SELECT te.id
            FROM task_executions te
            JOIN items i ON i.id = te.task_item_id
            WHERE i.run_id = ? AND i.kind = 'task' AND i.stable_id = ?
              AND te.state IN ('dispatched', 'running')
            LIMIT 1
            """,
            (run["id"], task_id),
        ).fetchone()
        return str(row["id"]) if row is not None else None

    def get_status(
        self,
        *,
        full: bool = False,
        include_events: bool = False,
        events_limit: int = 12,
    ) -> dict[str, Any]:
        with self._connection() as conn:
            state = db.status_payload(conn)
            check = validation.validate_plan_task_execute(conn)
        fields = (
            "id", "stable_id", "kind", "title", "status", "source",
            "archived", "created_at", "updated_at", "custom_fields",
        )
        project = lambda items: items if full else [
            {key: item[key] for key in fields if key in item} for item in items
        ]
        payload = {
            "ok": True,
            "schema": state.get("schema") or {},
            "active_run": state.get("active_run"),
            "task_counts": state.get("task_counts") or {},
            "incomplete_tasks": state.get("incomplete_tasks", 0),
            "counts": {
                "plans": len(state.get("plans") or []),
                "tasks": len(state.get("tasks") or []),
                "findings": len(state.get("findings") or []),
                "archives": int(state.get("archive_count") or 0),
                "active_batches": len(state.get("active_batches") or []),
                "active_executions": len(state.get("active_executions") or []),
            },
            "plans": project(state.get("plans") or []),
            "tasks": project(state.get("tasks") or []),
            "findings": project(state.get("findings") or []),
            "active_batches": state.get("active_batches") or [],
            "active_executions": state.get("active_executions") or [],
            "approvals": state.get("approvals") or {},
            "config": self._settings().as_dict(),
            "plan_task_execute": check,
        }
        if include_events:
            event_fields = ("id", "run_id", "event_type", "tool_name", "mode", "message", "created_at")
            payload["recent_events"] = [
                {key: event[key] for key in event_fields if key in event}
                for event in state.get("recent_events", [])[: max(events_limit, 0)]
            ]
        return payload

    def get_next(self) -> dict[str, Any]:
        with self._connection() as conn:
            state = db.status_payload(conn)
            check = validation.validate_plan_task_execute(conn)
        return {"ok": True, "recommendations": recommendations.next_recommendations(state, check)}

    def validate_state(self) -> dict[str, Any]:
        with self._connection() as conn:
            meta = db.get_meta(conn)
            check = validation.validate_plan_task_execute(conn)
            return {
                "ok": meta.get("schema_version") == str(db.SCHEMA_VERSION) and check["ok"],
                "schema_version": meta.get("schema_version"),
                "active_run": db.workflow_run_to_dict(db.active_run(conn)),
                "incomplete_tasks": db.incomplete_task_count(conn),
                "config": self._settings().as_dict(),
                "plan_task_execute": check,
            }

    def get_context(self, *, event: str = "Manual") -> dict[str, Any]:
        with self._connection() as conn:
            return tapl_context.build_context(conn, event=event, settings=self._settings())

    def search_history(self, query: str, *, limit: int | None = None) -> dict[str, Any]:
        settings = self._settings()
        selected_limit = limit if limit is not None else settings.search.max_results
        with self._connection() as conn:
            payload = embeddings.search(conn, query, limit=selected_limit, search_config=settings.search)
        return {"ok": True, **payload}

    def get_item(self, item_id: int) -> dict[str, Any]:
        with self._connection() as conn:
            item = db.item_detail(conn, item_id)
        if item is None:
            raise WorkflowApplicationError(f"item not found: {item_id}")
        return {"ok": True, "item": item}

    def list_archives(self, *, limit: int | None = None) -> dict[str, Any]:
        """List archived workflow runs for native viewers and MCP clients."""

        with self._connection() as conn:
            archives = db.list_archives(conn, limit=limit)
        return {"ok": True, "archives": archives}

    def get_archive(self, archive_id: str) -> dict[str, Any]:
        """Return one archive and its items/events without a CLI hop."""

        with self._connection() as conn:
            detail = db.archive_detail(conn, archive_id)
        if detail is None:
            raise WorkflowApplicationError(f"archive not found: {archive_id}")
        return {"ok": True, **detail}

    def summarize_run(
        self,
        summary: str,
        *,
        work_type: str = db.DEFAULT_WORK_TYPE,
        workflow_mode: str = db.DEFAULT_WORKFLOW_MODE,
    ) -> dict[str, Any]:
        if not summary.strip():
            raise WorkflowApplicationError("summary must not be empty")
        with self._connection() as conn:
            if db.active_run(conn) is None:
                db.ensure_active_run(
                    conn,
                    request_summary=summary,
                    work_type=work_type,
                    workflow_mode=workflow_mode,
                )
            run = db.update_active_run_summary(
                conn,
                request_summary=summary,
                work_type=work_type,
                workflow_mode=workflow_mode,
            )
        return {"ok": True, "active_run": db.workflow_run_to_dict(run)}

    def finish_run(self, result: str) -> dict[str, Any]:
        if not result.strip():
            raise WorkflowApplicationError("result must not be empty")
        with self._connection() as conn:
            run = db.update_active_run_summary(conn, result_summary=result)
        return {"ok": True, "active_run": db.workflow_run_to_dict(run)}

    def apply_plan(self, plan_id: str = "PLAN-001", **values: Any) -> dict[str, Any]:
        with self._connection() as conn:
            input_check = validation.validate_plan_input(plan_id=plan_id)
            if not input_check["ok"]:
                raise WorkflowApplicationError(_validation_message(input_check))
            existing = db.get_active_plan(conn, plan_id)
            item = db.upsert_plan(
                conn,
                plan_id=plan_id,
                title=self._field(existing, "title", values.get("title", UNSET), "Plan"),
                status=self._field(existing, "status", values.get("status", UNSET), "Draft"),
                summary=self._field(existing, "summary", values.get("summary", UNSET)),
                objective=self._field(existing, "objective", values.get("objective", UNSET)),
                requirements_trace=self._field(existing, "requirements_trace", values.get("requirements_trace", UNSET)),
                selected_approach=self._field(existing, "selected_approach", values.get("selected_approach", UNSET)),
                affected_files=self._field(existing, "affected_files", values.get("affected_files", UNSET)),
                execution_order=self._field(existing, "execution_order", values.get("execution_order", UNSET)),
                risks=self._field(existing, "risks", values.get("risks", UNSET)),
                validation=self._field(existing, "validation", values.get("validation", UNSET)),
                approval_needs=self._field(existing, "approval_needs", values.get("approval_needs", UNSET)),
                notes=self._field(existing, "notes", values.get("notes", UNSET)),
                custom_fields=None if values.get("custom_fields", UNSET) is UNSET else values["custom_fields"],
            )
            check = validation.validate_plan_task_execute(conn)
        return {"ok": True, "item": db.row_to_dict(item), "plan_task_execute": check}

    def create_task(self, task_id: str, title: str, spec_id: str, goal: str, action: str, verification_text: str, **values: Any) -> dict[str, Any]:
        return self._write_task(
            task_id,
            title=title,
            status="Pending",
            spec_id=spec_id,
            goal=goal,
            action=action,
            verification=verification_text,
            **values,
        )

    def start_task(self, task_id: str, *, custom_fields: dict[str, Any] | None = None) -> dict[str, Any]:
        return self._write_task(task_id, status="In Progress", custom_fields=custom_fields)

    def _write_task(self, task_id: str, **values: Any) -> dict[str, Any]:
        with self._connection() as conn:
            existing = db.get_active_task(conn, task_id)
            if existing is None and (values.get("title") is None or values.get("status") is None):
                raise WorkflowApplicationError(
                    f"{task_id} does not exist and requires title and status"
                )
            status = self._field(existing, "status", values.get("status", UNSET))
            spec_id = self._field(existing, "spec_id", values.get("spec_id", UNSET))
            input_check = validation.validate_task_input(
                task_id=task_id, status=status, spec_id=spec_id
            )
            if not input_check["ok"]:
                raise WorkflowApplicationError(_validation_message(input_check))
            item = db.upsert_task(
                conn,
                task_id=task_id,
                title=self._field(existing, "title", values.get("title", UNSET)),
                status=status,
                spec_id=spec_id,
                goal=self._field(existing, "goal", values.get("goal", UNSET)),
                action=self._field(existing, "action", values.get("action", UNSET)),
                verification=self._field(existing, "verification", values.get("verification", UNSET)),
                result=self._field(existing, "result", values.get("result", UNSET)),
                blocker=self._field(existing, "blocker", values.get("blocker", UNSET)),
                next_action=self._field(existing, "next_action", values.get("next_action", UNSET)),
                custom_fields=None if values.get("custom_fields", UNSET) is UNSET else values["custom_fields"],
                execution_mode=None if values.get("execution_mode", UNSET) is UNSET else values["execution_mode"],
                executor_kind=None if values.get("executor_kind", UNSET) is UNSET else values["executor_kind"],
                parallel_group=None if values.get("parallel_group", UNSET) is UNSET else values["parallel_group"],
                owned_paths=None if values.get("owned_paths", UNSET) is UNSET else values["owned_paths"],
                depends_on=None if values.get("depends_on", UNSET) is UNSET else values["depends_on"],
            )
            check = validation.validate_plan_task_execute(conn)
        return {"ok": True, "item": db.row_to_dict(item), "plan_task_execute": check}

    def dispatch_tasks(self, task_ids: list[str], *, batch_id: str | None = None, failure_policy: str = db.DEFAULT_FAILURE_POLICY, execution_metadata: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
        with self._connection() as conn:
            manifest = db.dispatch_tasks(
                conn, task_ids, batch_id=batch_id, failure_policy=failure_policy,
                execution_metadata=execution_metadata,
            )
        return {"ok": True, **manifest}

    def settle_task(self, task_id: str, *, status: str, execution_id: str | None = None, **values: Any) -> dict[str, Any]:
        with self._connection() as conn:
            active_id = self._active_execution_id(conn, task_id)
            if active_id is not None and execution_id is None:
                raise WorkflowApplicationError(
                    f"{task_id} has an active parallel execution; pass the exact execution_id"
                )
            if execution_id is not None:
                receipt = db.settle_task_execution(
                    conn, execution_id, task_status=status, task_id=task_id,
                    verification=values.get("verification"), result=values.get("result"),
                    blocker=values.get("blocker"), next_action=values.get("next_action"),
                    custom_fields=values.get("custom_fields"),
                )
                return {"ok": True, "settled_execution_id": execution_id, **receipt}
        return self._write_task(task_id, status=status, **values)

    def cancel_batch(self, batch_id: str, *, reason: str, block_tasks: bool = True) -> dict[str, Any]:
        with self._connection() as conn:
            receipt = db.cancel_execution_batch(
                conn, batch_id, reason=reason, recover_pending=not block_tasks
            )
        return {"ok": True, **receipt}

    def recover_batch(self, batch_id: str, *, reason: str) -> dict[str, Any]:
        with self._connection() as conn:
            receipt = db.recover_execution_batch(conn, batch_id, reason=reason)
        return {"ok": True, **receipt}

    def add_finding(self, title: str, *, source: str = "", finding: str = "", impact: str = "", related_ids: str = "") -> dict[str, Any]:
        with self._connection() as conn:
            item = db.add_finding(
                conn, title=title, source=source, finding=finding,
                impact=impact, related_ids=related_ids,
            )
        return {"ok": True, "item": db.row_to_dict(item)}

    def record_approval(self, *, decision: str, prompt: str, source: str) -> dict[str, Any]:
        with self._connection() as conn:
            row = db.record_approval(
                conn, kind=db.DEFAULT_APPROVAL_KIND, decision=decision,
                prompt=prompt, source=source,
            )
        return {"ok": True, "approval": db.row_to_dict(row)}

    def finish_archive(self, slug: str, *, summary: str = "") -> dict[str, Any]:
        with self._connection() as conn:
            row = db.archive_active_run(conn, slug=slug, summary=summary)
        return {"ok": True, "archive": db.row_to_dict(row)}


def _validation_message(payload: dict[str, Any]) -> str:
    issues = payload.get("issues") or payload.get("errors") or []
    if issues and isinstance(issues[0], dict):
        issue = issues[0]
        return " ".join(
            part for part in (str(issue.get("message") or ""), str(issue.get("remediation") or ""))
            if part
        )
    return "workflow input validation failed"
