"""Persistent semantic embedding daemon for tapl search."""

from __future__ import annotations

import base64
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
    idle_timeout_seconds: int | None = None,
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
    idle_timeout = settings.searchd_idle_timeout_seconds if idle_timeout_seconds is None else idle_timeout_seconds
    command = [
        sys.executable,
        "-m",
        "taplctl",
        "searchd",
        "run",
        "--socket",
        str(path),
        "--idle-timeout",
        str(idle_timeout),
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
        "idle_timeout_seconds": idle_timeout,
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
        timeout_ms=DEFAULT_CONNECT_TIMEOUT_MS,
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


def run_server(
    settings: tapl_config.SearchConfig,
    *,
    socket_path: str | Path | None = None,
    idle_timeout_seconds: int | None = None,
) -> dict[str, Any]:
    path = resolve_socket_path(socket_path)
    existing = status(settings, socket_path=path)
    if existing.get("ok"):
        raise SearchdError(f"searchd already running at {path}")
    remove_stale_socket(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    import numpy as np
    from sentence_transformers import SentenceTransformer

    from .embeddings import suppress_model_load_progress

    with suppress_model_load_progress():
        model = SentenceTransformer(db.DEFAULT_EMBEDDING_MODEL, local_files_only=True)

    reported_dimension = getattr(model, "get_sentence_embedding_dimension", lambda: None)()
    dimension = int(reported_dimension or db.DEFAULT_EMBEDDING_DIMENSION)
    idle_timeout = settings.searchd_idle_timeout_seconds if idle_timeout_seconds is None else idle_timeout_seconds
    started_at = time.monotonic()
    last_activity = started_at

    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
        server.bind(str(path))
        server.listen(16)
        server.settimeout(0.5)
        try:
            while True:
                if idle_timeout > 0 and time.monotonic() - last_activity >= idle_timeout:
                    return {"ok": True, "reason": "idle_timeout", "socket_path": str(path)}
                try:
                    conn, _ = server.accept()
                except socket.timeout:
                    continue
                with conn:
                    try:
                        request_payload = read_request(conn)
                        response, should_stop = handle_request(
                            request_payload,
                            model=model,
                            np=np,
                            started_at=started_at,
                            idle_timeout_seconds=idle_timeout,
                            dimension=dimension,
                        )
                    except SearchdError as exc:
                        response = {"ok": False, "error": str(exc)}
                        should_stop = False
                    conn.sendall(json.dumps(response, separators=(",", ":")).encode("utf-8") + b"\n")
                last_activity = time.monotonic()
                if should_stop:
                    return {"ok": True, "reason": "shutdown", "socket_path": str(path)}
        finally:
            remove_stale_socket(path)


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
    model: Any,
    np: Any,
    started_at: float,
    idle_timeout_seconds: int,
    dimension: int,
) -> tuple[dict[str, Any], bool]:
    op = request_payload.get("op")
    if op == "ping":
        return (
            {
                "ok": True,
                "pid": os.getpid(),
                "model": db.DEFAULT_EMBEDDING_MODEL,
                "dimension": dimension,
                "uptime_seconds": round(time.monotonic() - started_at, 3),
                "idle_timeout_seconds": idle_timeout_seconds,
            },
            False,
        )

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
    vector = model.encode([text], normalize_embeddings=True)[0]
    array = np.asarray(vector, dtype=np.float32)
    return (
        {
            "ok": True,
            "pid": os.getpid(),
            "model": db.DEFAULT_EMBEDDING_MODEL,
            "dimension": int(array.shape[0]),
            "embedding_b64": base64.b64encode(array.tobytes()).decode("ascii"),
        },
        False,
    )
