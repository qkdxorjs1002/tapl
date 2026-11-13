"""Keep Codex hook storage at the selected workspace without trusting other sessions."""

from __future__ import annotations

import io
import json
import os
import sqlite3
import sys
from pathlib import Path
from unittest import mock

import pytest

from taplctl import db, hook_cli, session_workspace


SESSION_ID = "session-selected-workspace"


def _metadata(root: Path, **updates: object) -> dict[str, object]:
    return {"type": "session_meta", "payload": {"id": SESSION_ID, "cwd": str(root), **updates}}


def _transcript(tmp_path: Path, record: object) -> Path:
    path = tmp_path / "rollout.jsonl"
    path.write_text(json.dumps(record) + "\n", encoding="utf-8")
    return path


def _payload(cwd: Path, transcript: Path) -> dict[str, object]:
    return {"session_id": SESSION_ID, "cwd": str(cwd), "transcript_path": str(transcript)}


def test_selected_workspace_is_metadata_cwd_even_inside_a_parent_repository(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    selected = tmp_path / "selected"
    child = selected / "child"
    child.mkdir(parents=True)
    transcript = _transcript(tmp_path, _metadata(selected))
    payload = _payload(child, transcript)

    assert session_workspace.resolve_hook_workspace(payload, client="codex", fallback=child) == selected
    assert payload["cwd"] == str(child)
    assert not (selected / ".tapl").exists()
    assert not (child / ".tapl").exists()


@pytest.mark.parametrize(
    "case",
    [
        "not-object", "wrong-type", "missing-payload", "non-object-payload",
        "missing-id", "other-id", "numeric-id", "session-id-alias",
        "empty-cwd", "missing-cwd", "relative-cwd", "absent-cwd", "file-cwd", "nul-cwd",
    ],
)
def test_invalid_metadata_never_redirects(tmp_path: Path, case: str) -> None:
    child = tmp_path / "child"
    child.mkdir()
    record = _metadata(tmp_path)
    metadata = record["payload"]
    if case == "not-object":
        record = []
    elif case == "wrong-type":
        record["type"] = "event_msg"
    elif case == "missing-payload":
        del record["payload"]
    elif case == "non-object-payload":
        record["payload"] = []
    elif case == "missing-id":
        del metadata["id"]
    elif case == "other-id":
        metadata["id"] = "different-session"
    elif case == "numeric-id":
        metadata["id"] = 1
    elif case == "session-id-alias":
        metadata["session_id"] = metadata.pop("id")
    elif case == "missing-cwd":
        del metadata["cwd"]
    else:
        file = tmp_path / "ordinary-file"
        file.touch()
        metadata["cwd"] = {
            "empty-cwd": "", "relative-cwd": ".", "absent-cwd": str(tmp_path / "absent"),
            "file-cwd": str(file), "nul-cwd": str(tmp_path) + "\0",
        }[case]
    transcript = _transcript(tmp_path, record)

    assert session_workspace.resolve_hook_workspace(
        _payload(child, transcript), client="codex", fallback=child,
    ) == child


@pytest.mark.parametrize("first_line", [b"", b"\n", b"{broken\n", b"\xff\n", b"[" * 1500 + b"]" * 1500 + b"\n"])
def test_bad_first_record_does_not_scan_for_later_metadata(tmp_path: Path, first_line: bytes) -> None:
    child = tmp_path / "child"
    child.mkdir()
    transcript = tmp_path / "rollout.jsonl"
    # An empty file stays empty; all other cases have a tempting valid second row.
    transcript.write_bytes(first_line + (json.dumps(_metadata(tmp_path)).encode() if first_line else b""))

    assert session_workspace.resolve_hook_workspace(
        _payload(child, transcript), client="codex", fallback=child,
    ) == child


def test_only_first_record_is_parsed_and_read_is_bounded(tmp_path: Path) -> None:
    child = tmp_path / "child"
    child.mkdir()
    transcript = _transcript(tmp_path, _metadata(tmp_path))
    with transcript.open("ab") as stream:
        stream.write(b"not a JSON conversation record\n")
    original_fdopen = os.fdopen
    original_loads = json.loads
    reads: list[int] = []

    def fdopen(*args: object, **kwargs: object) -> object:
        stream = original_fdopen(*args, **kwargs)
        wrapped = mock.Mock(wraps=stream)
        wrapped.fileno.side_effect = stream.fileno
        wrapped.readline.side_effect = lambda size: (reads.append(size), stream.readline(size))[1]
        manager = mock.MagicMock()
        manager.__enter__.return_value = wrapped
        manager.__exit__.side_effect = lambda *_: stream.close()
        return manager

    with mock.patch.object(session_workspace.os, "fdopen", side_effect=fdopen), \
            mock.patch.object(session_workspace.json, "loads", wraps=original_loads) as parse:
        assert session_workspace.resolve_hook_workspace(
            _payload(child, transcript), client="codex", fallback=child,
        ) == tmp_path
    assert reads == [session_workspace.MAX_SESSION_META_BYTES + 1]
    parse.assert_called_once()
    assert b"conversation" not in parse.call_args.args[0]


@pytest.mark.parametrize("extra_bytes", [0, 1])
def test_metadata_size_limit_includes_first_record_delimiter(tmp_path: Path, extra_bytes: int) -> None:
    child = tmp_path / "child"
    child.mkdir()
    record = _metadata(tmp_path, base_instructions="")
    empty = json.dumps(record).encode() + b"\n"
    record["payload"]["base_instructions"] = "x" * (
        session_workspace.MAX_SESSION_META_BYTES - len(empty) + extra_bytes
    )
    transcript = _transcript(tmp_path, record)
    assert transcript.stat().st_size == session_workspace.MAX_SESSION_META_BYTES + extra_bytes

    assert session_workspace.resolve_hook_workspace(
        _payload(child, transcript), client="codex", fallback=child,
    ) == (child if extra_bytes else tmp_path)


@pytest.mark.parametrize("case", ["missing", "relative", "directory", "symlink", "fifo"])
def test_ineligible_transcript_is_never_opened(tmp_path: Path, case: str) -> None:
    child = tmp_path / "child"
    child.mkdir()
    transcript = tmp_path / "rollout.jsonl"
    if case == "relative":
        transcript = Path("rollout.jsonl")
    elif case == "directory":
        transcript.mkdir()
    elif case == "symlink":
        target = _transcript(tmp_path, _metadata(tmp_path))
        transcript = tmp_path / "linked.jsonl"
        transcript.symlink_to(target)
    elif case == "fifo":
        if not hasattr(os, "mkfifo"):
            pytest.skip("named pipes require os.mkfifo")
        os.mkfifo(transcript)
    with mock.patch.object(session_workspace.os, "open", side_effect=AssertionError("must not open")):
        assert session_workspace.resolve_hook_workspace(
            _payload(child, transcript), client="codex", fallback=child,
        ) == child


@pytest.mark.parametrize("error", [PermissionError, FileNotFoundError])
def test_unreadable_or_disappearing_transcript_falls_back(tmp_path: Path, error: type[OSError]) -> None:
    child = tmp_path / "child"
    child.mkdir()
    transcript = _transcript(tmp_path, _metadata(tmp_path))
    with mock.patch.object(session_workspace.os, "open", side_effect=error):
        assert session_workspace.resolve_hook_workspace(
            _payload(child, transcript), client="codex", fallback=child,
        ) == child


@pytest.mark.parametrize("replacement_kind", ["regular", "symlink", "fifo"])
def test_file_replacement_before_open_falls_back(tmp_path: Path, replacement_kind: str) -> None:
    child = tmp_path / "child"
    child.mkdir()
    transcript = _transcript(tmp_path, _metadata(tmp_path))
    replacement = tmp_path / "replacement.jsonl"
    if replacement_kind == "fifo":
        if not hasattr(os, "mkfifo"):
            pytest.skip("named pipes require os.mkfifo")
        os.mkfifo(replacement)
    elif replacement_kind == "symlink":
        target = tmp_path / "target.jsonl"
        target.write_text(json.dumps(_metadata(tmp_path)), encoding="utf-8")
        replacement.symlink_to(target)
    else:
        replacement.write_text(json.dumps(_metadata(tmp_path)), encoding="utf-8")
    original_open = os.open

    def replaced_open(path: Path, flags: int) -> int:
        replacement.replace(path)
        return original_open(path, flags)

    with mock.patch.object(session_workspace.os, "open", side_effect=replaced_open):
        assert session_workspace.resolve_hook_workspace(
            _payload(child, transcript), client="codex", fallback=child,
        ) == child


@pytest.mark.parametrize("client,changes", [
    ("claude-code", {}), ("codex", {"session_id": ""}), ("codex", {"session_id": None}),
    ("codex", {"transcript_path": None}), ("codex", {"transcript_path": 1}),
])
def test_other_client_and_legacy_payloads_do_not_read_metadata(
    tmp_path: Path, client: str, changes: dict[str, object],
) -> None:
    child = tmp_path / "child"
    child.mkdir()
    transcript = _transcript(tmp_path, _metadata(tmp_path))
    payload = {**_payload(child, transcript), **changes}
    with mock.patch.object(session_workspace, "_read_session_metadata", side_effect=AssertionError("must not read")):
        assert session_workspace.resolve_hook_workspace(payload, client=client, fallback=child) == child


@pytest.mark.parametrize("cwd", [None, "relative", "absent"])
def test_valid_metadata_does_not_bypass_event_cwd_validation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], cwd: str | None,
) -> None:
    transcript = _transcript(tmp_path, _metadata(tmp_path))
    payload = _payload(tmp_path, transcript)
    payload["cwd"] = str(tmp_path / "absent") if cwd == "absent" else cwd
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    with mock.patch.object(hook_cli, "resolve_hook_workspace") as resolve, \
            mock.patch.object(hook_cli.db, "local_db_path") as local_db:
        assert hook_cli.main(["--client", "codex", "--event", "SessionStart", "--json"]) == 1
    resolve.assert_not_called()
    local_db.assert_not_called()
    assert json.loads(capsys.readouterr().out)["ok"] is False


@pytest.mark.parametrize("db_location", ["selected", "child", "sibling"])
def test_explicit_db_is_checked_against_selected_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], db_location: str,
) -> None:
    child = tmp_path / "child"
    child.mkdir()
    sibling = tmp_path / "sibling"
    sibling.mkdir()
    transcript = _transcript(tmp_path, _metadata(tmp_path))
    selected_db = db.local_db_path(tmp_path, create_identity=True)
    candidates = {"selected": selected_db, "child": db.local_db_path(child), "sibling": db.local_db_path(sibling)}
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(_payload(child, transcript))))
    with mock.patch.object(hook_cli.tapl_install, "auto_install_if_needed") as refresh:
        code = hook_cli.main([
            "--client", "codex", "--event", "SessionStart", "--db", str(candidates[db_location]), "--json",
        ])
    refresh.assert_not_called()
    output = json.loads(capsys.readouterr().out)
    if db_location == "selected":
        assert code == 0 and output["ok"] is True
        assert selected_db.is_file()
    else:
        assert code == 1
        assert "selected workspace database" in output["error"]
        assert not selected_db.exists()
    assert not (child / ".tapl").exists()
    assert not (sibling / ".tapl").exists()


@pytest.mark.parametrize("client,matching", [("codex", True), ("codex", False), ("claude-code", True)])
def test_hook_stores_original_event_cwd_with_correct_client_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], client: str, matching: bool,
) -> None:
    child = tmp_path / "child"
    child.mkdir()
    transcript = _transcript(tmp_path, _metadata(tmp_path, id=SESSION_ID if matching else "other-session"))
    payload = _payload(child, transcript)
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    with mock.patch.object(hook_cli.tapl_install, "auto_install_if_needed"):
        assert hook_cli.main(["--client", client, "--event", "SessionStart", "--json"]) == 0
    output = json.loads(capsys.readouterr().out)
    selected = tmp_path if client == "codex" and matching else child
    assert output["workspace"]["workspace_root"] == str(selected)
    with sqlite3.connect(db.local_db_path(selected)) as conn:
        row = conn.execute("SELECT session_id, payload_json FROM events WHERE event_type = 'SessionStart'").fetchone()
    assert row[0] == (f"claude-code:{SESSION_ID}" if client == "claude-code" else SESSION_ID)
    assert json.loads(row[1]) == payload
    unused = child if selected == tmp_path else tmp_path
    assert not (unused / ".tapl").exists()


def test_resolving_selected_workspace_preserves_existing_child_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    child = tmp_path / "child"
    child.mkdir()
    child_db = Path(db.initialize_workspace(child)["db"])
    original = child_db.read_bytes()
    transcript = _transcript(tmp_path, _metadata(tmp_path))
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(_payload(child, transcript))))
    with mock.patch.object(hook_cli.tapl_install, "auto_install_if_needed"):
        assert hook_cli.main(["--client", "codex", "--event", "SessionStart", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["workspace"]["workspace_root"] == str(tmp_path)
    assert child_db.read_bytes() == original
    assert db.local_db_path(tmp_path).is_file()


AGENT_ID = "child-selected-workspace"


def _subagent_metadata(root: Path) -> dict[str, object]:
    return _metadata(root, id=AGENT_ID, parent_thread_id=SESSION_ID, source={
        "subagent": {"thread_spawn": {"parent_thread_id": SESSION_ID, "depth": 1}},
    })


@pytest.mark.parametrize("outer_parent", [True, False])
def test_verified_subagent_uses_original_workspace(tmp_path: Path, outer_parent: bool) -> None:
    selected = tmp_path / "project"
    skill = tmp_path / "skill"
    selected.mkdir(); skill.mkdir()
    record = _subagent_metadata(selected)
    if not outer_parent:
        del record["payload"]["parent_thread_id"]
    transcript = _transcript(tmp_path, record)
    payload = {**_payload(skill, transcript), "agent_id": AGENT_ID}

    assert session_workspace.resolve_hook_workspace(payload, client="codex", fallback=skill) == selected
    assert payload["session_id"] == SESSION_ID
    assert payload["cwd"] == str(skill)
    assert not (selected / ".tapl").exists()
    assert not (skill / ".tapl").exists()


@pytest.mark.parametrize("case", [
    "missing-agent", "empty-agent", "numeric-agent", "other-agent", "parent-as-agent",
    "missing-source", "source-string", "source-list", "missing-subagent", "subagent-string",
    "missing-spawn", "spawn-string", "missing-parent", "other-parent", "nested-ancestor",
    "outer-other-parent", "outer-null-parent", "outer-empty-parent", "outer-numeric-parent",
])
def test_unverified_subagent_never_redirects(tmp_path: Path, case: str) -> None:
    skill = tmp_path / "skill"
    skill.mkdir()
    record = _subagent_metadata(tmp_path)
    metadata = record["payload"]
    source = metadata["source"]
    spawn = source["subagent"]["thread_spawn"]
    payload = {"session_id": SESSION_ID, "cwd": str(skill), "agent_id": AGENT_ID}
    if case == "missing-agent":
        del payload["agent_id"]
    elif case in {"empty-agent", "numeric-agent", "other-agent", "parent-as-agent"}:
        payload["agent_id"] = {"empty-agent": "", "numeric-agent": 1,
                               "other-agent": "unrelated-child", "parent-as-agent": SESSION_ID}[case]
    elif case == "missing-source":
        del metadata["source"]
    elif case in {"source-string", "source-list"}:
        metadata["source"] = "subagent" if case == "source-string" else []
    elif case == "missing-subagent":
        del source["subagent"]
    elif case == "subagent-string":
        source["subagent"] = "thread_spawn"
    elif case == "missing-spawn":
        del source["subagent"]["thread_spawn"]
    elif case == "spawn-string":
        source["subagent"]["thread_spawn"] = SESSION_ID
    elif case == "missing-parent":
        del spawn["parent_thread_id"]
    elif case in {"other-parent", "nested-ancestor"}:
        spawn["parent_thread_id"] = "another-parent"
        if case == "nested-ancestor":
            metadata["parent_thread_id"] = "another-parent"
            spawn["depth"] = 2
    else:
        metadata["parent_thread_id"] = {
            "outer-other-parent": "unrelated-parent", "outer-null-parent": None,
            "outer-empty-parent": "", "outer-numeric-parent": 1,
        }[case]
    payload["transcript_path"] = str(_transcript(tmp_path, record))

    assert session_workspace.resolve_hook_workspace(payload, client="codex", fallback=skill) == skill
    assert not (tmp_path / ".tapl").exists()


@pytest.mark.parametrize("cwd", ["relative", "missing", "file"])
def test_verified_subagent_still_requires_existing_absolute_workspace(tmp_path: Path, cwd: str) -> None:
    skill = tmp_path / "skill"; skill.mkdir()
    ordinary = tmp_path / "ordinary"; ordinary.touch()
    record = _subagent_metadata(tmp_path)
    record["payload"]["cwd"] = {"relative": ".", "missing": str(tmp_path / "absent"), "file": str(ordinary)}[cwd]
    payload = {**_payload(skill, _transcript(tmp_path, record)), "agent_id": AGENT_ID}
    assert session_workspace.resolve_hook_workspace(payload, client="codex", fallback=skill) == skill


def test_main_session_precedence_preserves_existing_hints_contract(tmp_path: Path) -> None:
    skill = tmp_path / "skill"; skill.mkdir()
    record = _metadata(tmp_path, parent_thread_id="another-parent", source="cli")
    payload = {**_payload(skill, _transcript(tmp_path, record)), "agent_id": AGENT_ID}
    assert session_workspace.resolve_hook_workspace(payload, client="codex", fallback=skill) == tmp_path


@pytest.mark.parametrize("existing_skill_database", [False, True])
def test_observe_subagent_hook_initializes_only_original_project_and_keeps_parent_owner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], existing_skill_database: bool,
) -> None:
    selected = tmp_path / "project"; selected.mkdir()
    skill = tmp_path / "skill"; skill.mkdir()
    previous_database = Path(db.initialize_workspace(skill)["db"]) if existing_skill_database else None
    previous_bytes = previous_database.read_bytes() if previous_database else None
    payload = {**_payload(skill, _transcript(tmp_path, _subagent_metadata(selected))),
               "agent_id": AGENT_ID, "agent_type": "default", "tool_name": "Bash",
               "tool_input": {"command": "nl -ba SKILL.md"}}
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    with mock.patch.object(hook_cli.tapl_install, "auto_install_if_needed"):
        assert hook_cli.main(["--client", "codex", "--event", "PreToolUse", "--mode", "observe", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["workspace"]["workspace_root"] == str(selected)
    with sqlite3.connect(db.local_db_path(selected)) as conn:
        row = conn.execute("SELECT session_id, payload_json FROM events WHERE event_type = 'PreToolUse'").fetchone()
        assert row[0] == SESSION_ID
        assert json.loads(row[1]) == payload
        assert conn.execute("SELECT count(*) FROM workflow_runs").fetchone()[0] == 0
    if previous_database:
        assert previous_database.read_bytes() == previous_bytes
        assert list((skill / ".tapl").iterdir()) == [previous_database]
    else:
        assert not (skill / ".tapl").exists()


@pytest.mark.parametrize("mode", ["observe", "enforce"])
def test_subagent_routing_does_not_grant_execution_approval(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], mode: str,
) -> None:
    selected = tmp_path / "project"; selected.mkdir()
    skill = tmp_path / "skill"; skill.mkdir()
    path = db.local_db_path(selected, create_identity=True)
    conn = db.connect(path, session_id=SESSION_ID)
    try:
        db.ensure_active_run(conn, work_type="implementation", workflow_mode="fast")
        db.upsert_plan(conn, plan_id="PLAN-001", title="Parent plan", status="Finalized")
        db.upsert_task(conn, task_id="TASK-001", title="Parent task", spec_id="PLAN-001",
                       goal="Change a file", action="Write it", verification="Read it", status="Pending")
    finally:
        conn.close()
    payload = {**_payload(skill, _transcript(tmp_path, _subagent_metadata(selected))),
               "agent_id": AGENT_ID, "tool_name": "Write", "tool_input": {"file_path": str(selected / "new.txt")}}
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    with mock.patch.object(hook_cli.tapl_install, "auto_install_if_needed"):
        code = hook_cli.main(["--client", "codex", "--event", "PreToolUse", "--mode", mode, "--json"])
    result = json.loads(capsys.readouterr().out)
    assert result["block"] is (mode == "enforce")
    assert code == (2 if mode == "enforce" else 0)
    assert "execution_approval_missing" in result["message"]
    assert not (selected / "new.txt").exists()
    assert not (skill / ".tapl").exists()
