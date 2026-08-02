"""Local browser viewer for workspace-scoped tapl state."""

from __future__ import annotations

import json
import mimetypes
import subprocess
import sys
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import unquote, urlsplit

from . import db


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000
MAX_REQUEST_BYTES = 64 * 1024
COMMAND_TIMEOUT_SECONDS = 15
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


def parse_port(value: str) -> int:
    try:
        port = int(value)
    except ValueError as exc:
        raise ValueError("port must be an integer between 1 and 65535") from exc
    if not 1 <= port <= 65535:
        raise ValueError("port must be between 1 and 65535")
    return port


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


def run_cli_json(db_path: Path, args: list[str]) -> dict[str, Any]:
    completed = subprocess.run(
        [sys.executable, "-m", "taplctl", "--db", str(db_path), *args],
        text=True,
        capture_output=True,
        check=False,
        timeout=COMMAND_TIMEOUT_SECONDS,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip() or "taplctl command failed"
        raise ViewerError(detail)
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise ViewerError("taplctl returned invalid JSON") from exc
    if not isinstance(payload, dict):
        raise ViewerError("taplctl returned a non-object JSON response")
    if payload.get("ok") is False:
        raise ViewerError(str(payload.get("error") or "taplctl command failed"))
    return payload


class ViewerApplication:
    """Map a small read-only browser protocol to existing taplctl JSON commands."""

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
        self.json_runner = json_runner or run_cli_json

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
            view = self._build_view(payload, db_path)
            if workspace is not None and view.get("type") == "overview":
                view["workspace"] = str(workspace)
        except WorkspaceRequired as exc:
            view = {
                "type": "workspace",
                "workspace": raw_workspace if isinstance(raw_workspace, str) else "",
                "message": str(exc),
            }
        except (ViewerError, subprocess.TimeoutExpired) as exc:
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
                "search_source": "taplctl",
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

    def __init__(self, server_address: tuple[str, int], app: ViewerApplication) -> None:
        self.app = app
        super().__init__(server_address, ViewerRequestHandler)

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
        host, port = self.server.server_address[:2]
        allowed = {f"http://{host}:{port}"}
        if host == DEFAULT_HOST:
            allowed.add(f"http://localhost:{port}")
        return origin in allowed

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


def create_server(app: ViewerApplication, *, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> ViewerHTTPServer:
    try:
        return ViewerHTTPServer((host, port), app)
    except OSError as exc:
        if getattr(exc, "errno", None) in {48, 98, 10048}:
            raise ViewerError(
                f"Port {port} is already in use on {host}. Choose another port with `taplctl viewer --port PORT`."
            ) from exc
        raise ViewerError(f"Could not start viewer on {host}:{port}: {exc}") from exc


def serve(
    *,
    port: int = DEFAULT_PORT,
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
    server = create_server(app, port=port)
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
