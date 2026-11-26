"""Schedule local semantic index rebuilds without delaying the calling command."""

from __future__ import annotations

import argparse
from contextlib import closing
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
from threading import Thread
import time
from typing import Any

from . import config, db, embeddings


def is_homebrew_runtime() -> bool:
    parts = Path(sys.prefix).resolve().parts
    return any(parent == "Cellar" and formula in {"taplctl", "taplctl-pre", "taplctl-semantic"}
               for parent, formula in zip(parts, parts[1:]))


def _existing_database(workspace: Path, explicit: Path | None) -> Path | None:
    local = db.local_db_path(workspace)
    if local is None or not local.is_file():
        local = workspace / db.DEFAULT_DB_RELATIVE
        if not local.is_file() or local.is_symlink():
            return None
    if explicit is not None and (workspace / explicit.expanduser()).resolve() != local:
        return None
    return local


def _selected_model(workspace: Path, config_path: Path | None) -> str | None:
    search = config.load(config_path, start=workspace).search
    return search.model if search.mode in {"hybrid", "semantic"} else None


def _needs_update(path: Path, model: str) -> bool:
    with closing(db.connect_readonly(path)) as conn:
        return embeddings.index_model_mismatch(conn, model)


def schedule(
    workspace: Path | None = None, *, config_path: Path | None = None,
    database: Path | None = None, python: Path | None = None,
) -> dict[str, str] | None:
    """Start a detached worker for an existing local mismatch, if any.

    After an updater switches installations, the new runtime checks its own
    model fingerprints and dependencies in the worker instead.
    """
    try:
        root = db.find_repo_root(workspace)
        path = _existing_database(root, database)
        if path is None:
            return None
        if python is None:
            model = _selected_model(root, config_path)
            if model is None or not _needs_update(path, model) or not all(embeddings.dependency_status().values()):
                return None
        command = [str(python or sys.executable)]
        if python is not None:
            command.append("-I")
        command.extend(["-m", "taplctl.auto_reindex", str(path)])
        if config_path is not None:
            command.extend(["--config", str(config_path.expanduser().resolve())])
        options = ({"creationflags": subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP}
                   if os.name == "nt" else {"start_new_session": True})
        process = subprocess.Popen(command, cwd=root, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL, **options)
    except (OSError, ValueError, sqlite3.Error) as exc:
        return {"status": "failed", "error": str(exc)}
    # Reap the worker in long-lived Viewer and MCP processes. The worker can
    # continue when a short-lived management command exits.
    try:
        Thread(target=process.wait, daemon=True).start()
    except RuntimeError:
        pass  # The worker has already started; Popen can reap it later.
    return {"status": "scheduled"}


def _rebuild(path: Path, workspace: Path, config_path: Path | None) -> bool:
    if _existing_database(workspace, path) is None:
        return True
    model = _selected_model(workspace, config_path)
    if model is None or not _needs_update(path, model) or not all(embeddings.dependency_status().values()):
        return True
    lock_path = path.with_name(f".{path.name}.reindex-lock")
    if lock_path.is_symlink():
        return False
    # A separate SQLite lock serializes workers without blocking normal TAPL
    # writes during downloads or inference. SQLite releases it on process exit.
    with closing(sqlite3.connect(lock_path, timeout=120)) as lock:
        lock.execute("BEGIN EXCLUSIVE")
        for attempt in range(3):
            model = _selected_model(workspace, config_path)
            if model is None or not _needs_update(path, model):
                return True
            with closing(sqlite3.connect(path.as_uri() + "?mode=rw", uri=True,
                                         timeout=db.SQLITE_BUSY_TIMEOUT_MS / 1_000)) as conn:
                conn.row_factory = sqlite3.Row
                conn.execute("PRAGMA foreign_keys = ON")
                result = embeddings.reindex(conn, model=model,
                                             should_publish=lambda: _selected_model(workspace, config_path) == model)
            if result["ok"] and _selected_model(workspace, config_path) == model:
                return True
            if not result["ok"] and not result.get("retryable"):
                return False
            if attempt < 2:
                time.sleep(0.25 * (attempt + 1))
    return False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("database", type=Path)
    parser.add_argument("--config", type=Path)
    args = parser.parse_args()
    try:
        return 0 if _rebuild(args.database, Path.cwd(), args.config) else 1
    except (OSError, ValueError, sqlite3.Error):
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
