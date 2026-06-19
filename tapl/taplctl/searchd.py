"""Persistent semantic embedding daemon for tapl search."""

from __future__ import annotations

import base64
import gc
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from . import config as tapl_config, db


MAX_LINE_BYTES = 1024 * 1024
SOCKET_ENV = "TAPL_SEARCHD_SOCKET"
DEFAULT_CONNECT_TIMEOUT_MS = 250
DEFAULT_START_TIMEOUT_MS = 15000
DEFAULT_EMBED_TIMEOUT_MS = 30000


class SearchdError(RuntimeError):
    """Base searchd failure."""


class SearchdUnavailable(SearchdError):
    """Raised when no usable daemon is listening."""


def default_socket_path() -> Path:
    if value := os.environ.get(SOCKET_ENV):
        return Path(value).expanduser()
    return Path.home() / ".tapl" / "searchd.sock"


def resolve_socket_path(socket_path: str | Path | None = None) -> Path:
    if socket_path:
        return Path(socket_path).expanduser()
    return default_socket_path()


def configured_socket_path() -> Path:
    return resolve_socket_path()


def status(
    settings: tapl_config.SearchConfig,
    *,
    socket_path: str | Path | None = None,
    timeout_ms: int | None = None,
) -> dict[str, Any]:
    path = resolve_socket_path(socket_path)
    try:
        response = request(
            path,
            {"op": "ping", "model": db.DEFAULT_EMBEDDING_MODEL},
            timeout_ms=timeout_ms or DEFAULT_CONNECT_TIMEOUT_MS,
        )
    except SearchdError as exc:
        return {
            "ok": False,
            "running": False,
            "socket_path": str(path),
            "error": str(exc),
        }
    response["running"] = bool(response.get("ok"))
    response["socket_path"] = str(path)
    return response


def start(
    settings: tapl_config.SearchConfig,
    *,
    socket_path: str | Path | None = None,
    model_idle_timeout_seconds: int | None = None,
    timeout_ms: int | None = None,
    wait: bool = True,
) -> dict[str, Any]:
    path = resolve_socket_path(socket_path)
    existing = status(settings, socket_path=path)
    if existing.get("ok"):
        existing["started"] = False
        existing["already_running"] = True
        return existing

    remove_stale_socket(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    model_idle_timeout = (
        settings.searchd_model_idle_timeout_seconds
        if model_idle_timeout_seconds is None
        else model_idle_timeout_seconds
    )
    command = [
        sys.executable,
        "-m",
        "taplctl",
        "searchd",
        "run",
        "--socket",
        str(path),
        "--idle-timeout",
        str(model_idle_timeout),
    ]
    process = subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
        start_new_session=True,
    )
    payload: dict[str, Any] = {
        "ok": True,
        "running": True,
        "started": True,
        "already_running": False,
        "pid": process.pid,
        "socket_path": str(path),
        "model_idle_timeout_seconds": model_idle_timeout,
    }
    if not wait:
        return payload

    ready = wait_for_status(
        settings,
        socket_path=path,
        process=process,
        timeout_ms=timeout_ms or DEFAULT_START_TIMEOUT_MS,
    )
    ready["started"] = ready.get("ok", False)
    ready["already_running"] = False
    ready["pid"] = ready.get("pid") or process.pid
    return ready


def wait_for_status(
    settings: tapl_config.SearchConfig,
    *,
    socket_path: Path,
    process: subprocess.Popen[Any] | None = None,
    timeout_ms: int,
) -> dict[str, Any]:
    deadline = time.monotonic() + (timeout_ms / 1000.0)
    last_error = ""
    while time.monotonic() < deadline:
        if process is not None and process.poll() is not None:
            return {
                "ok": False,
                "running": False,
                "socket_path": str(socket_path),
                "error": f"searchd exited early with code {process.returncode}",
            }
        current = status(settings, socket_path=socket_path)
        if current.get("ok"):
            return current
        last_error = str(current.get("error") or "")
        time.sleep(0.1)
    return {
        "ok": False,
        "running": False,
        "socket_path": str(socket_path),
        "error": last_error or f"searchd did not become ready within {timeout_ms}ms",
    }


def stop(
    settings: tapl_config.SearchConfig,
    *,
    socket_path: str | Path | None = None,
    timeout_ms: int | None = None,
) -> dict[str, Any]:
    path = resolve_socket_path(socket_path)
    try:
        response = request(
            path,
            {"op": "shutdown", "model": db.DEFAULT_EMBEDDING_MODEL},
            timeout_ms=timeout_ms or DEFAULT_CONNECT_TIMEOUT_MS,
        )
    except SearchdUnavailable:
        return {"ok": True, "running": False, "stopped": False, "socket_path": str(path)}
    except SearchdError as exc:
        return {"ok": False, "running": False, "stopped": False, "socket_path": str(path), "error": str(exc)}
    response["running"] = False
    response["stopped"] = True
    response["socket_path"] = str(path)
    return response


def embed_query(query: str, settings: tapl_config.SearchConfig) -> bytes:
    path = configured_socket_path()
    response = request(
        path,
        {
            "op": "embed",
            "model": db.DEFAULT_EMBEDDING_MODEL,
            "dimension": db.DEFAULT_EMBEDDING_DIMENSION,
            "text": query,
        },
        timeout_ms=DEFAULT_EMBED_TIMEOUT_MS,
    )
    if not response.get("ok"):
        raise SearchdError(str(response.get("error") or "searchd embedding failed"))
    dimension = int(response.get("dimension") or 0)
    if dimension != db.DEFAULT_EMBEDDING_DIMENSION:
        raise SearchdError(
            f"searchd dimension mismatch: expected {db.DEFAULT_EMBEDDING_DIMENSION}, got {dimension}"
        )
    encoded = response.get("embedding_b64")
    if not isinstance(encoded, str):
        raise SearchdError("searchd response did not include embedding_b64")
    try:
        return base64.b64decode(encoded)
    except Exception as exc:
        raise SearchdError("searchd response embedding_b64 is invalid") from exc


def request(socket_path: Path, payload: dict[str, Any], *, timeout_ms: int) -> dict[str, Any]:
    if not hasattr(socket, "AF_UNIX"):
        raise SearchdUnavailable("Unix domain sockets are not available on this platform")
    if not socket_path.exists():
        raise SearchdUnavailable(f"searchd socket not found: {socket_path}")

    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(timeout_ms / 1000.0)
            client.connect(str(socket_path))
            client.sendall(json.dumps(payload, separators=(",", ":")).encode("utf-8") + b"\n")
            line = recv_line(client)
    except OSError as exc:
        raise SearchdUnavailable(str(exc)) from exc

    try:
        decoded = json.loads(line.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SearchdError("searchd returned invalid JSON") from exc
    if not isinstance(decoded, dict):
        raise SearchdError("searchd returned a non-object JSON response")
    return decoded


def recv_line(sock: socket.socket) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = sock.recv(4096)
        if not chunk:
            raise SearchdError("searchd closed the connection without a response")
        total += len(chunk)
        if total > MAX_LINE_BYTES:
            raise SearchdError("searchd response exceeded maximum size")
        if b"\n" in chunk:
            before, _, _ = chunk.partition(b"\n")
            chunks.append(before)
            return b"".join(chunks)
        chunks.append(chunk)


def remove_stale_socket(socket_path: Path) -> None:
    try:
        socket_path.unlink()
    except FileNotFoundError:
        return


class ModelState:
    def __init__(
        self,
        *,
        model_idle_timeout_seconds: int,
        now: Any | None = None,
        model_loader: Any | None = None,
        numpy_loader: Any | None = None,
    ) -> None:
        self.model_idle_timeout_seconds = model_idle_timeout_seconds
        self.model: Any | None = None
        self.np: Any | None = None
        self.dimension = db.DEFAULT_EMBEDDING_DIMENSION
        self.loaded_at: float | None = None
        self.last_embed_at: float | None = None
        self._now = now or time.monotonic
        self._model_loader = model_loader or self._default_model_loader
        self._numpy_loader = numpy_loader or self._default_numpy_loader

    @property
    def model_loaded(self) -> bool:
        return self.model is not None

    def status_payload(self, *, started_at: float) -> dict[str, Any]:
        self.unload_if_idle()
        payload: dict[str, Any] = {
            "ok": True,
            "pid": os.getpid(),
            "model": db.DEFAULT_EMBEDDING_MODEL,
            "dimension": self.dimension,
            "uptime_seconds": round(self._now() - started_at, 3),
            "model_loaded": self.model_loaded,
            "model_idle_timeout_seconds": self.model_idle_timeout_seconds,
        }
        if self.loaded_at is not None:
            payload["model_loaded_seconds"] = round(self._now() - self.loaded_at, 3)
        if self.last_embed_at is not None:
            payload["model_idle_seconds"] = round(self._now() - self.last_embed_at, 3)
        return payload

    def unload_if_idle(self) -> bool:
        if not self.model_loaded:
            return False
        if self.model_idle_timeout_seconds <= 0:
            return False
        if self.last_embed_at is None:
            return False
        if self._now() - self.last_embed_at < self.model_idle_timeout_seconds:
            return False
        return self.unload()

    def unload(self) -> bool:
        if not self.model_loaded:
            return False
        self.model = None
        self.np = None
        self.dimension = db.DEFAULT_EMBEDDING_DIMENSION
        self.loaded_at = None
        gc.collect()
        return True

    def embed(self, text: str) -> dict[str, Any]:
        self.unload_if_idle()
        self.load()
        vector = self.model.encode([text], normalize_embeddings=True)[0]
        array = self.np.asarray(vector, dtype=self.np.float32)
        self.last_embed_at = self._now()
        return {
            "dimension": int(array.shape[0]),
            "embedding_b64": base64.b64encode(array.tobytes()).decode("ascii"),
        }

    def load(self) -> None:
        if self.model_loaded:
            return
        self.np = self._numpy_loader()
        self.model = self._model_loader()
        reported_dimension = getattr(self.model, "get_sentence_embedding_dimension", lambda: None)()
        self.dimension = int(reported_dimension or db.DEFAULT_EMBEDDING_DIMENSION)
        self.loaded_at = self._now()

    def _default_numpy_loader(self) -> Any:
        import numpy as np

        return np

    def _default_model_loader(self) -> Any:
        from sentence_transformers import SentenceTransformer

        from .embeddings import suppress_model_load_progress

        with suppress_model_load_progress():
            return SentenceTransformer(db.DEFAULT_EMBEDDING_MODEL, local_files_only=True)


def run_server(
    settings: tapl_config.SearchConfig,
    *,
    socket_path: str | Path | None = None,
    model_idle_timeout_seconds: int | None = None,
) -> dict[str, Any]:
    path = resolve_socket_path(socket_path)
    existing = status(settings, socket_path=path)
    if existing.get("ok"):
        raise SearchdError(f"searchd already running at {path}")
    remove_stale_socket(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    model_idle_timeout = (
        settings.searchd_model_idle_timeout_seconds
        if model_idle_timeout_seconds is None
        else model_idle_timeout_seconds
    )
    model_state = ModelState(model_idle_timeout_seconds=model_idle_timeout)
    started_at = time.monotonic()

    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
        server.bind(str(path))
        server.listen(16)
        server.settimeout(0.5)
        try:
            while True:
                model_state.unload_if_idle()
                try:
                    conn, _ = server.accept()
                except socket.timeout:
                    continue
                with conn:
                    try:
                        request_payload = read_request(conn)
                        response, should_stop = handle_request(
                            request_payload,
                            model_state=model_state,
                            started_at=started_at,
                        )
                    except SearchdError as exc:
                        response = {"ok": False, "error": str(exc)}
                        should_stop = False
                    except Exception as exc:
                        response = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
                        should_stop = False
                    send_response(conn, response)
                if should_stop:
                    return {"ok": True, "reason": "shutdown", "socket_path": str(path)}
        finally:
            remove_stale_socket(path)


def send_response(conn: socket.socket, response: dict[str, Any]) -> bool:
    data = json.dumps(response, separators=(",", ":")).encode("utf-8") + b"\n"
    try:
        conn.sendall(data)
    except OSError:
        return False
    return True


def read_request(conn: socket.socket) -> dict[str, Any]:
    line = recv_line(conn)
    try:
        decoded = json.loads(line.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SearchdError("request was not valid JSON") from exc
    if not isinstance(decoded, dict):
        raise SearchdError("request must be a JSON object")
    return decoded


def handle_request(
    request_payload: dict[str, Any],
    *,
    model_state: ModelState,
    started_at: float,
) -> tuple[dict[str, Any], bool]:
    model_state.unload_if_idle()
    op = request_payload.get("op")
    if op == "ping":
        return (model_state.status_payload(started_at=started_at), False)

    if op == "shutdown":
        return ({"ok": True, "pid": os.getpid(), "message": "searchd shutting down"}, True)

    if op != "embed":
        return ({"ok": False, "error": f"unknown op: {op}"}, False)

    expected_model = request_payload.get("model")
    if expected_model and expected_model != db.DEFAULT_EMBEDDING_MODEL:
        return (
            {
                "ok": False,
                "error": f"model mismatch: expected {db.DEFAULT_EMBEDDING_MODEL}, got {expected_model}",
            },
            False,
        )
    text = request_payload.get("text")
    if not isinstance(text, str):
        return ({"ok": False, "error": "embed request text must be a string"}, False)
    embedding = model_state.embed(text)
    return (
        {
            "ok": True,
            "pid": os.getpid(),
            "model": db.DEFAULT_EMBEDDING_MODEL,
            "dimension": embedding["dimension"],
            "embedding_b64": embedding["embedding_b64"],
            "model_loaded": model_state.model_loaded,
            "model_idle_timeout_seconds": model_state.model_idle_timeout_seconds,
        },
        False,
    )
