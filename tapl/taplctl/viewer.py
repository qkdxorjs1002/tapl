"""Local browser viewer for workspace-scoped tapl state."""

from __future__ import annotations

import hashlib
import json
import mimetypes
import sqlite3
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.parse import unquote, urlsplit

from . import config, db, embeddings, validation


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000
MAX_REQUEST_BYTES = 64 * 1024
ASSET_ROOT = Path(__file__).with_name("_viewer")
INDEX_PATH = Path("src/webview/index.html")
DEFAULT_STATUS: dict[str, Any] = {
    "active_run": None,
    "task_counts": {},
    "incomplete_tasks": 0,
    "plans": [],
    "tasks": [],
    "findings": [],
    "active_batches": [],
    "active_executions": [],
    "recent_events": [],
    "schema": {},
}


class ViewerError(RuntimeError):
    """Raised when the local viewer cannot be started or queried."""


class WorkspaceRequired(ViewerError):
    """Raised when a browser request has no usable tapl workspace."""


JsonRunner = Callable[[Path, list[str]], dict[str, Any]]


def database_revision(db_path: Path) -> str:
    """Return an opaque revision for the SQLite database and its WAL sidecars.

    The viewer only needs to know whether the on-disk state changed, so hash
    deterministic file metadata rather than exposing paths or timestamps to
    the browser.  SQLite may create or remove WAL sidecars between requests;
    that race is represented as a normal missing file.
    """

    files: list[dict[str, object]] = []
    paths = (
        db_path,
        db_path.with_name(f"{db_path.name}-wal"),
        db_path.with_name(f"{db_path.name}-shm"),
    )
    for path in paths:
        try:
            stat = path.stat()
        except FileNotFoundError:
            files.append(
                {"name": path.name, "exists": False, "mtime_ns": None, "size": None}
            )
        except OSError as exc:
            raise ViewerError(f"Could not read TAPL database revision: {exc}") from exc
        else:
            files.append(
                {
                    "name": path.name,
                    "exists": True,
                    "mtime_ns": stat.st_mtime_ns,
                    "size": stat.st_size,
                }
            )
    serialized = json.dumps(files, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(serialized).hexdigest()


def parse_port(value: str) -> int:
    try:
        port = int(value)
    except ValueError as exc:
        raise ValueError("port must be an integer between 1 and 65535") from exc
    if not 1 <= port <= 65535:
        raise ValueError("port must be between 1 and 65535")
    return port


def parse_allowed_origin(value: str) -> str:
    return config.http_origin(value)


def existing_workspace(start: Path | None = None) -> Path | None:
    """Return the nearest initialized workspace without creating a database."""

    return db.find_workspace_root(start)


def workspace_database(workspace: str | Path) -> tuple[Path, Path]:
    root = Path(workspace).expanduser().resolve()
    if not root.is_dir():
        raise WorkspaceRequired(f"Workspace directory does not exist: {root}")
    db_path = root / db.DEFAULT_DB_RELATIVE
    if not db_path.is_file():
        raise WorkspaceRequired(
            f"No tapl database found at {db_path}. Run `taplctl init --workspace-root {root}` first."
        )
    return root, db_path


class NativeJsonRunner:
    """Run the viewer's small, read-only protocol directly against a database.

    ``ViewerApplication`` retains the command-shaped ``JsonRunner`` seam so its
    browser protocol remains straightforward to test.  This implementation maps
    those commands to the application/database read APIs rather than starting a
    second ``taplctl`` process for every browser request.
    """

    def __call__(self, db_path: Path, args: list[str]) -> dict[str, Any]:
        try:
            return self._run(db_path, args)
        except ViewerError:
            raise
        except (OSError, sqlite3.Error, ValueError) as exc:
            raise ViewerError(f"Could not read TAPL state: {exc}") from exc

    def _run(self, db_path: Path, args: list[str]) -> dict[str, Any]:
        if not args:
            raise ViewerError("Missing viewer data request.")

        command = args[0]
        if command == "status":
            return self._status(
                db_path,
                full="--full" in args,
                include_events="--include-events" in args,
            )
        if args[:2] == ["archive", "list"]:
            return self._archive_list(db_path, args)
        if args[:2] == ["archive", "show"]:
            archive_id = self._option(args, "--id")
            if not archive_id:
                raise ViewerError("Missing archive id.")
            return self._archive_show(db_path, archive_id)
        if args[:2] == ["item", "show"]:
            raw_item_id = self._option(args, "--id")
            try:
                item_id = int(raw_item_id) if raw_item_id is not None else None
            except ValueError as exc:
                raise ViewerError("Invalid item id.") from exc
            if item_id is None:
                raise ViewerError("Missing item id.")
            return self._item_show(db_path, item_id)
        if command == "search" and len(args) >= 2:
            return self._search(db_path, args[1])
        raise ViewerError(f"Unsupported viewer data request: {' '.join(args)}")

    @staticmethod
    def _option(args: list[str], name: str) -> str | None:
        try:
            return args[args.index(name) + 1]
        except (ValueError, IndexError):
            return None

    @staticmethod
    def _workspace_for_database(db_path: Path) -> Path | None:
        resolved = db_path.expanduser().resolve()
        if resolved.parent.name == db.DEFAULT_DB_RELATIVE.parent.name:
            workspace = resolved.parent.parent
            if resolved == workspace / db.DEFAULT_DB_RELATIVE:
                return workspace
        return None

    def _settings(self, db_path: Path) -> config.TaplConfig:
        # A bare --db path is supported by the viewer even when it is not below
        # a workspace.  In that case use the normal config discovery fallback.
        return config.load(start=self._workspace_for_database(db_path))

    def _connection(self, db_path: Path) -> sqlite3.Connection:
        return db.connect(db_path)

    def _status(self, db_path: Path, *, full: bool, include_events: bool) -> dict[str, Any]:
        conn = self._connection(db_path)
        try:
            state = db.status_payload(conn)
            state["plan_task_execute"] = validation.validate_plan_task_execute(conn)
        finally:
            conn.close()
        state["config"] = self._settings(db_path).as_dict()
        return self._status_output(state, full=full, include_events=include_events)

    @staticmethod
    def _status_output(
        state: dict[str, Any], *, full: bool, include_events: bool, events_limit: int = 12
    ) -> dict[str, Any]:
        """Match the workflow status payload returned by the application."""

        plans = list(state.get("plans") or [])
        tasks = list(state.get("tasks") or [])
        findings = list(state.get("findings") or [])
        item_fields = (
            "id",
            "stable_id",
            "kind",
            "title",
            "status",
            "source",
            "archived", "created_at", "updated_at", "custom_fields",
        )
        event_fields = (
            "id",
            "run_id",
            "event_type",
            "tool_name",
            "mode",
            "message",
            "created_at",
        )

        def compact(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
            return [{key: item[key] for key in item_fields if key in item} for item in items]

        payload: dict[str, Any] = {
            "schema": state.get("schema") or {},
            "active_run": state.get("active_run"),
            "task_counts": state.get("task_counts") or {},
            "incomplete_tasks": state.get("incomplete_tasks", 0),
            "counts": {
                "plans": len(plans),
                "tasks": len(tasks),
                "findings": len(findings),
                "archives": int(
                    state.get("archive_count") or len(state.get("archives") or [])
                ),
                "active_batches": len(state.get("active_batches") or []),
                "active_executions": len(state.get("active_executions") or []),
            },
            "plans": plans if full else compact(plans),
            "tasks": tasks if full else compact(tasks),
            "findings": findings if full else compact(findings),
            "active_batches": list(state.get("active_batches") or []),
            "active_executions": list(state.get("active_executions") or []),
        }
        for key in ("config", "plan_task_execute", "approvals"):
            if key in state:
                payload[key] = state[key]
        if include_events:
            payload["recent_events"] = [
                {key: event[key] for key in event_fields if key in event}
                for event in list(state.get("recent_events") or [])[:max(events_limit, 0)]
            ]
        return payload

    def _archive_list(self, db_path: Path, args: list[str]) -> dict[str, Any]:
        raw_limit = self._option(args, "--limit")
        try:
            limit = int(raw_limit) if raw_limit is not None else None
        except ValueError as exc:
            raise ViewerError("Invalid archive limit.") from exc
        conn = self._connection(db_path)
        try:
            return {"ok": True, "archives": db.list_archives(conn, limit=limit)}
        finally:
            conn.close()

    def _archive_show(self, db_path: Path, archive_id: str) -> dict[str, Any]:
        conn = self._connection(db_path)
        try:
            detail = db.archive_detail(conn, archive_id)
        finally:
            conn.close()
        if detail is None:
            raise ViewerError(f"archive not found: {archive_id}")
        return {"ok": True, **detail}

    def _item_show(self, db_path: Path, item_id: int) -> dict[str, Any]:
        conn = self._connection(db_path)
        try:
            item = db.item_detail(conn, item_id)
        finally:
            conn.close()
        if item is None:
            raise ViewerError(f"item not found: {item_id}")
        return {"ok": True, "item": item}

    def _search(self, db_path: Path, query: str) -> dict[str, Any]:
        settings = self._settings(db_path)
        conn = self._connection(db_path)
        try:
            payload = embeddings.search(
                conn,
                query,
                limit=settings.search.max_results,
                search_config=settings.search,
            )
        finally:
            conn.close()
        return {"ok": True, **payload}


def run_native_json(db_path: Path, args: list[str]) -> dict[str, Any]:
    """Compatibility-friendly function form of :class:`NativeJsonRunner`."""

    return NativeJsonRunner()(db_path, args)


class ViewerApplication:
    """Map a small read-only browser protocol to native TAPL read operations."""

    def __init__(
        self,
        *,
        default_db: Path | None = None,
        default_workspace: Path | None = None,
        asset_root: Path | None = None,
        json_runner: JsonRunner | None = None,
    ) -> None:
        self.default_db = default_db.expanduser().resolve() if default_db else None
        self.default_workspace = default_workspace.expanduser().resolve() if default_workspace else None
        self.asset_root = (asset_root or ASSET_ROOT).resolve()
        self.json_runner = json_runner or run_native_json

    def resolve_database(self, raw_workspace: object) -> tuple[Path | None, Path]:
        if isinstance(raw_workspace, str) and raw_workspace.strip():
            workspace, db_path = workspace_database(raw_workspace.strip())
            return workspace, db_path
        if self.default_db is not None:
            if not self.default_db.is_file():
                raise WorkspaceRequired(f"tapl database does not exist: {self.default_db}")
            return self.default_workspace, self.default_db
        if self.default_workspace is not None:
            workspace, db_path = workspace_database(self.default_workspace)
            return workspace, db_path
        raise WorkspaceRequired("Choose a workspace that contains .tapl/tapl.db.")

    def handle_message(self, payload: object) -> dict[str, Any]:
        locale = "en"
        layout = "auto"
        if isinstance(payload, dict):
            locale = "ko" if str(payload.get("locale") or "").lower().startswith("ko") else "en"
            if payload.get("layout") in {"small", "medium", "large"}:
                layout = str(payload["layout"])
        if not isinstance(payload, dict) or not isinstance(payload.get("command"), str):
            return self._error_message("Invalid viewer message.", locale=locale, layout=layout)

        raw_workspace = payload.get("workspace")
        workspace: Path | None = None
        try:
            workspace, db_path = self.resolve_database(raw_workspace)
            if payload["command"] == "revision":
                return {
                    "type": "revision",
                    "revision": database_revision(db_path),
                    "workspace": str(workspace) if workspace else "",
                    "workspaceValid": True,
                    "message": "",
                }
            view = self._build_view(payload, db_path)
            if workspace is not None and view.get("type") == "overview":
                view["workspace"] = str(workspace)
        except WorkspaceRequired as exc:
            if payload["command"] == "revision":
                return {
                    "type": "revision",
                    "revision": "",
                    "workspace": raw_workspace if isinstance(raw_workspace, str) else "",
                    "workspaceValid": False,
                    "message": str(exc),
                }
            view = {
                "type": "workspace",
                "workspace": raw_workspace if isinstance(raw_workspace, str) else "",
                "message": str(exc),
            }
        except ViewerError as exc:
            return self._error_message(str(exc), locale=locale, layout=layout)

        return {
            "type": "hydrate" if payload["command"] == "ready" else "view:update",
            "view": view,
            "locale": locale,
            "layout": layout,
            "workspace": str(workspace) if workspace else "",
        }

    def _build_view(self, payload: dict[str, Any], db_path: Path) -> dict[str, Any]:
        command = str(payload["command"])
        if command in {"ready", "selectWorkspace"}:
            return self._overview(db_path, search_query="")
        if command == "refresh":
            return self._refresh_view(payload, db_path)
        if command == "debug":
            status = self.json_runner(db_path, ["status", "--json", "--include-events"])
            return {"type": "debug", "status": {**DEFAULT_STATUS, **status}}
        if command in {"openArchive", "archiveEvents"}:
            archive_id = self._required_string(payload, "archiveId")
            detail = self.json_runner(db_path, ["archive", "show", "--id", archive_id, "--json"])
            archive = detail.get("archive")
            if not isinstance(archive, dict):
                raise ViewerError("Archive details are unavailable.")
            return {
                "type": "archiveEvents" if command == "archiveEvents" else "archive",
                "archive": archive,
                "detail": {
                    "archive": archive,
                    "items": detail.get("items") if isinstance(detail.get("items"), list) else [],
                    "events": detail.get("events") if isinstance(detail.get("events"), list) else [],
                },
            }
        if command == "search":
            query = self._required_string(payload, "query").strip()
            if not query:
                raise ViewerError("Enter a search query.")
            return {"type": "search", "search": self.json_runner(db_path, ["search", query, "--json"])}
        if command == "openSearchResult":
            raw_item_id = payload.get("itemId")
            if isinstance(raw_item_id, bool):
                raise ViewerError("Invalid item id.")
            try:
                item_id = int(raw_item_id)
            except (TypeError, ValueError) as exc:
                raise ViewerError("Invalid item id.") from exc
            detail_payload = self.json_runner(db_path, ["item", "show", "--id", str(item_id), "--json"])
            detail = detail_payload.get("item")
            if not isinstance(detail, dict):
                raise ViewerError("Item details are unavailable.")
            if detail.get("kind") == "task":
                status = self.json_runner(db_path, ["status", "--json", "--full"])
                matching = next(
                    (
                        item for item in status.get("tasks", [])
                        if isinstance(item, dict) and item.get("stable_id") == detail.get("stable_id")
                    ),
                    None,
                )
                if matching:
                    detail = {**matching, **detail}
            result = {
                "id": item_id,
                "stable_id": str(detail.get("stable_id") or item_id),
                "kind": str(detail.get("kind") or "item"),
                "title": str(detail.get("title") or detail.get("stable_id") or item_id),
                "status": detail.get("status"),
                "source": detail.get("source"),
                "search_source": "native",
            }
            return {"type": "searchItem", "result": result, "detail": detail}
        raise ViewerError(f"Unsupported viewer command: {command}")

    def _refresh_view(self, payload: dict[str, Any], db_path: Path) -> dict[str, Any]:
        view_type = str(payload.get("viewType") or "overview")
        if view_type == "debug":
            return self._build_view({**payload, "command": "debug"}, db_path)
        if view_type in {"archive", "archiveEvents"}:
            return self._build_view(
                {**payload, "command": "archiveEvents" if view_type == "archiveEvents" else "openArchive"},
                db_path,
            )
        if view_type == "search" and isinstance(payload.get("query"), str):
            return self._build_view({**payload, "command": "search"}, db_path)
        if view_type == "searchItem" and payload.get("itemId") is not None:
            return self._build_view({**payload, "command": "openSearchResult"}, db_path)
        return self._overview(db_path, search_query=str(payload.get("query") or ""))

    def _overview(self, db_path: Path, *, search_query: str) -> dict[str, Any]:
        status = self.json_runner(db_path, ["status", "--json", "--full"])
        archives_payload = self.json_runner(db_path, ["archive", "list", "--json", "--limit", "8"])
        archives = archives_payload.get("archives")
        return {
            "type": "overview",
            "status": {**DEFAULT_STATUS, **status},
            "archives": archives if isinstance(archives, list) else [],
            "searchQuery": search_query,
        }

    @staticmethod
    def _required_string(payload: dict[str, Any], key: str) -> str:
        value = payload.get(key)
        if not isinstance(value, str) or not value:
            raise ViewerError(f"Missing {key}.")
        return value

    @staticmethod
    def _error_message(message: str, *, locale: str, layout: str) -> dict[str, Any]:
        return {"type": "error", "message": message, "locale": locale, "layout": layout}


class ViewerHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(
        self,
        server_address: tuple[str, int],
        app: ViewerApplication,
        *,
        allowed_origins: Iterable[str] = (),
    ) -> None:
        configured_origins = {parse_allowed_origin(origin) for origin in allowed_origins}
        self.app = app
        super().__init__(server_address, ViewerRequestHandler)
        host, port = self.server_address[:2]
        local_origins = {f"http://{host}:{port}"}
        if host == DEFAULT_HOST:
            local_origins.add(f"http://localhost:{port}")
        self.allowed_origins = frozenset(local_origins | configured_origins)

    @property
    def browser_origin(self) -> str:
        host, port = self.server_address[:2]
        return f"http://{host}:{port}"


class ViewerRequestHandler(BaseHTTPRequestHandler):
    server: ViewerHTTPServer

    def do_GET(self) -> None:  # noqa: N802
        path = unquote(urlsplit(self.path).path)
        if path.startswith("/api/") or path == "/api":
            self._send_json(HTTPStatus.METHOD_NOT_ALLOWED, {"ok": False, "error": "Use POST /api/message."})
            return
        relative = INDEX_PATH if path in {"", "/"} else Path(path.lstrip("/"))
        self._serve_asset(relative)

    def do_POST(self) -> None:  # noqa: N802
        if urlsplit(self.path).path != "/api/message":
            self._send_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "Not found."})
            return
        if not self._origin_allowed():
            self._send_json(HTTPStatus.FORBIDDEN, {"ok": False, "error": "Origin is not allowed."})
            return
        if self.headers.get_content_type() != "application/json":
            self._send_json(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, {"ok": False, "error": "Expected application/json."})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = -1
        if length < 0 or length > MAX_REQUEST_BYTES:
            self._send_json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"ok": False, "error": "Request is too large."})
            return
        try:
            payload = json.loads(self.rfile.read(length))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "Invalid JSON."})
            return
        self._send_json(HTTPStatus.OK, self.server.app.handle_message(payload))

    def do_OPTIONS(self) -> None:  # noqa: N802
        self._send_json(HTTPStatus.METHOD_NOT_ALLOWED, {"ok": False, "error": "CORS is not enabled."})

    def _origin_allowed(self) -> bool:
        origin = self.headers.get("Origin")
        if not origin:
            return True
        try:
            normalized = parse_allowed_origin(origin)
        except ValueError:
            return False
        return normalized in self.server.allowed_origins

    def _serve_asset(self, relative: Path) -> None:
        root = self.server.app.asset_root
        candidate = (root / relative).resolve()
        if not candidate.is_relative_to(root) or not candidate.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        content_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
        content = candidate.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8" if content_type.startswith("text/") else content_type)
        self.send_header("Content-Length", str(len(content)))
        self._security_headers()
        self.end_headers()
        self.wfile.write(content)

    def _send_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        content = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self._security_headers()
        self.end_headers()
        self.wfile.write(content)

    def _security_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Security-Policy", "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; font-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")

    def log_message(self, _format: str, *_args: object) -> None:
        return


def create_server(
    app: ViewerApplication,
    *,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    allowed_origins: Iterable[str] = (),
) -> ViewerHTTPServer:
    try:
        return ViewerHTTPServer((host, port), app, allowed_origins=allowed_origins)
    except OSError as exc:
        if getattr(exc, "errno", None) in {48, 98, 10048}:
            raise ViewerError(
                f"Port {port} is already in use on {host}. Choose another port with `taplctl viewer --port PORT`."
            ) from exc
        raise ViewerError(f"Could not start viewer on {host}:{port}: {exc}") from exc


def serve(
    *,
    port: int = DEFAULT_PORT,
    allowed_origins: Iterable[str] = (),
    default_db: Path | None = None,
    default_workspace: Path | None = None,
    asset_root: Path | None = None,
) -> None:
    app = ViewerApplication(
        default_db=default_db,
        default_workspace=default_workspace,
        asset_root=asset_root,
    )
    index_path = app.asset_root / INDEX_PATH
    if not index_path.is_file():
        raise ViewerError(f"Viewer assets are missing: {index_path}")
    server = create_server(app, port=port, allowed_origins=allowed_origins)
    print(f"tapl viewer: {server.browser_origin}", flush=True)
    if default_workspace:
        print(f"workspace: {default_workspace}", flush=True)
    else:
        print("workspace: choose one in the browser", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\ntapl viewer stopped", flush=True)
    finally:
        server.server_close()
