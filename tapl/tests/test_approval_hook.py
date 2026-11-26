"""Codex native edit gate and compaction hook contracts."""

from contextlib import closing
import io
import json
import sys

import pytest

from taplctl import db, execution_evidence, hook_cli, hooks, install
from taplctl.application import WorkflowApplication


SESSION_ID = "codex-approval-hook"


@pytest.fixture
def run_hook(tmp_path, monkeypatch, capsys):
    db_path = db.local_db_path(tmp_path, create_identity=True)

    def invoke(event, *, mode="enforce", session_id=SESSION_ID, **payload):
        hook_input = {
            "cwd": str(tmp_path), "session_id": session_id, "hook_event_name": event, **payload,
        }
        monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(hook_input)))
        assert hook_cli.main([
            "--client", "codex", "--event", event, "--mode", mode, "--db", str(db_path),
        ]) == 0
        output = capsys.readouterr()
        assert not output.err
        return output.out

    return invoke


def test_native_edit_gate_requires_approval_and_started_task(tmp_path, run_hook):
    request = "Update the handler and verify the result."
    run_hook("UserPromptSubmit", prompt=request, turn_id="turn-initial")
    app = WorkflowApplication(tmp_path, session_id=SESSION_ID)
    app.summarize_run("Update the handler", work_type="implementation", workflow_mode="fast")
    app.apply_plan("PLAN-001", title="Update handler", status="Finalized")
    app.create_task("TASK-001", "Edit handler", "PLAN-001", "Fix output", "Edit handler", "Inspect diff")

    edit = {"tool_name": "apply_patch", "tool_input": {"command": "*** Begin Patch\n*** End Patch"}}
    observed = json.loads(run_hook("PreToolUse", mode="observe", **edit))["hookSpecificOutput"]
    assert "approval" in observed["additionalContext"].lower()
    assert "permissionDecision" not in observed
    denied = json.loads(run_hook("PreToolUse", **edit))["hookSpecificOutput"]
    assert denied["hookEventName"] == "PreToolUse"
    assert denied["permissionDecision"] == "deny"
    assert "approval" in denied["permissionDecisionReason"].lower()

    app.record_approval(decision="approved", prompt=request, source="explicit_user")
    denied = json.loads(run_hook("PreToolUse", **edit))["hookSpecificOutput"]
    assert denied["permissionDecision"] == "deny"
    assert "Start a task" in denied["permissionDecisionReason"]

    app.start_task("TASK-001")
    reported = run_hook("PreToolUse", **edit)
    assert "permissionDecision" not in json.loads(reported or "{}").get("hookSpecificOutput", {})
    resume = json.loads(run_hook("SessionStart", source="compact"))["hookSpecificOutput"]
    assert "Started TASKs: TASK-001." in resume["additionalContext"]
    app.settle_task("TASK-001", status="Completed", result="Handler fixed", verification="Inspected diff")
    denied = json.loads(run_hook("PreToolUse", **edit))["hookSpecificOutput"]
    assert "Start a task" in denied["permissionDecisionReason"]

    with closing(db.connect(db.local_db_path(tmp_path), session_id=SESSION_ID)) as conn:
        saved = conn.execute("SELECT payload_json FROM events WHERE event_type = 'UserPromptSubmit'").fetchone()
        assert "prompt" not in json.loads(saved["payload_json"])


def test_only_root_prompt_submits_approval_confirmation(tmp_path, run_hook):
    run_hook("UserPromptSubmit", prompt="Plan the handler update.", turn_id="planning")
    app = WorkflowApplication(tmp_path, session_id=SESSION_ID)
    app.summarize_run("Plan the handler update", work_type="planning")
    app.apply_plan("PLAN-001", title="Update handler", status="Finalized")
    with closing(db.connect(db.local_db_path(tmp_path), session_id=SESSION_ID)) as conn:
        token = execution_evidence.confirmation_command(conn)
    assert token and token.startswith("TAPL-APPROVE ")

    run_hook("UserPromptSubmit", prompt=token, turn_id="helper", agent_id="helper")
    with pytest.raises(ValueError, match="host confirmation"):
        app.record_approval(decision="approved", prompt=token, source="explicit_user")

    run_hook("UserPromptSubmit", prompt=token, turn_id="root-confirmation")
    assert app.record_approval(decision="approved", prompt=token, source="explicit_user")["ok"]


def test_enforce_allows_waiting_for_user_with_pending_planned_task(tmp_path, run_hook):
    run_hook("UserPromptSubmit", prompt="Plan the handler update.", turn_id="planning")
    app = WorkflowApplication(tmp_path, session_id=SESSION_ID)
    run = app.summarize_run("Plan the handler update", work_type="planning")["active_run"]
    app.apply_plan("PLAN-001", title="Update handler", status="Finalized")
    app.create_task("TASK-001", "Edit handler", "PLAN-001", "Fix output", "Edit handler", "Inspect diff")

    assert not run_hook("Stop", last_assistant_message="Please confirm the plan before execution.")
    state = app.get_status()
    assert state["active_run"]["id"] == run["id"]
    assert state["tasks"][0]["status"] == "Pending"


@pytest.mark.parametrize(
    "command,writes",
    [
        ("git -C '/tmp/test repo' -c user.name=Test branch -M topic", True),
        ("git -C /tmp branch -D topic", True),
        ("git status && git add path", True),
        ("git status;\n/usr/bin/git commit -m '--help'", True),
        ("cd repo\n/usr/bin/git push", True),
        ("git remote set-url origin example", True),
        ("git -C '/tmp/test repo' status --short", False),
        ("git branch -a", False),
        ("git branch --list test", False),
        ("git worktree list --porcelain", False),
        ("git stash list", False),
        ("echo 'git commit -m example' && git log", False),
        ("git status # git commit -m example", False),
        ("printf '>'", False),
        ("printf data > result.txt", True),
        ("git status 2>/dev/null", False),
        ("printf data | tee result.txt", True),
        ("python3 -c 'from pathlib import Path; Path(\"a\").touch()'", True),
        ("node script.js", True),
        ("python3 --version", False),
    ],
)
def test_bash_classifies_direct_write_commands(command, writes):
    assert hooks.is_durable_tool("Bash", {"tool_input": {"command": command}}) is writes


def test_native_git_inspection_remains_available_before_approval(run_hook):
    def git(command):
        return run_hook("PreToolUse", tool_name="Bash", tool_input={"command": command})

    assert git("git -C /tmp status --short") == ""
    denied = json.loads(git("git -C /tmp branch -M main"))["hookSpecificOutput"]
    assert denied["permissionDecision"] == "deny"


def test_enforce_denies_durable_edit_when_approval_cannot_be_read(run_hook, monkeypatch):
    def unavailable(*args, **kwargs):
        raise OSError("approval database unavailable")

    monkeypatch.setattr(hook_cli.db, "connect", unavailable)
    response = run_hook("PreToolUse", tool_name="apply_patch", tool_input={"command": "*** Begin Patch"})
    specific = json.loads(response)["hookSpecificOutput"]
    assert specific["permissionDecision"] == "deny"
    assert "approval database unavailable" in specific["permissionDecisionReason"]


@pytest.mark.parametrize("trigger", ["manual", "auto"])
def test_compaction_records_event_and_injects_compact_session_scope(tmp_path, run_hook, trigger):
    with closing(db.connect(db.local_db_path(tmp_path), session_id=SESSION_ID)) as conn:
        run_id = db.ensure_active_run(conn)["id"]
    with closing(db.connect(db.local_db_path(tmp_path), session_id="other-session")) as conn:
        other_run_id = db.ensure_active_run(conn)["id"]

    assert run_hook("PostCompact", trigger=trigger, turn_id="turn-compacted") == ""
    specific = json.loads(run_hook("SessionStart", source="compact"))["hookSpecificOutput"]
    assert specific["hookEventName"] == "SessionStart"
    message = specific["additionalContext"]
    assert "`tapl_get_next` without `known_policy_revision`" in message
    assert SESSION_ID in message and run_id in message
    assert other_run_id not in message
    assert len(message) < 500

    with closing(db.connect(db.local_db_path(tmp_path), session_id=SESSION_ID)) as conn:
        event = conn.execute("SELECT * FROM events WHERE event_type = 'PostCompact'").fetchone()
        assert event["session_id"] == SESSION_ID and event["run_id"] == run_id
        assert json.loads(event["payload_json"])["trigger"] == trigger
        assert event["message"] == message


@pytest.mark.parametrize("use_template", [True, False])
def test_installer_registers_compaction_hooks(monkeypatch, use_template):
    if not use_template:
        monkeypatch.setattr(install, "template_hooks_config", lambda **kwargs: None)
    config = install.build_hooks_config(taplctl_command="taplctl", mode="enforce")["hooks"]
    assert config["SessionStart"][0]["matcher"] == "^compact$"
    for event in ("PostCompact", "SessionStart"):
        command = config[event][0]["hooks"][0]["command"]
        assert event in command
