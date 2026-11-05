"""Claude command-hook protocol and host-scoped MCP workflow boundaries."""

from __future__ import annotations

import asyncio
from contextlib import closing
import io
import json
from pathlib import Path
import sys
from unittest import mock

from mcp import Client
import pytest

from taplctl import clients, config, db, hook_cli, hooks, mcp_server
from taplctl.application import WorkflowApplication


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.delenv("TAPL_CLIENT", raising=False)
    (tmp_path / ".git").mkdir()
    db.initialize_workspace(tmp_path)
    (tmp_path / ".tapl/config.toml").write_text(
        "[recall]\nenabled=false\n"
        "[subagents]\nenabled=false\nsetup_complete=true\nstrategy='conservative'\n"
        "[clients.claude-code.subagents]\nenabled=false\nsetup_complete=true\nstrategy='aggressive'\n",
        encoding="utf-8",
    )
    return tmp_path


def run_hook(workspace: Path, monkeypatch, capsys, event: str, *, mode="enforce", diagnostic=False, **payload):
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({
        "cwd": str(workspace), "session_id": "native", "hook_event_name": event, **payload,
    })))
    args = ["--client", "claude-code", "--event", event, "--mode", mode,
            "--db", str(db.default_db_path(workspace))]
    code = hook_cli.main(args + (["--json"] if diagnostic else []))
    output = capsys.readouterr()
    return code, json.loads(output.out) if output.out.strip() else None, output.err


def test_same_native_id_isolates_claude_and_codex_hook_runs(workspace, monkeypatch, capsys):
    path = db.default_db_path(workspace)
    ids = {}
    for client in ("codex", "claude-code", "claude-code", "codex"):
        monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({
            "cwd": str(workspace), "session_id": "native", "prompt": client,
        })))
        assert hook_cli.main(["--client", client, "--event", "UserPromptSubmit", "--db", str(path), "--json"]) == 0
        payload = json.loads(capsys.readouterr().out)
        owner = clients.session_key("native", client)
        assert payload["session_id"] == owner
        run_id = payload["context"]["active_run"]["id"]
        assert ids.setdefault(client, run_id) == run_id
    assert ids["codex"] != ids["claude-code"]
    with closing(db.connect(path)) as conn:
        assert db.active_run(conn) is None


@pytest.mark.parametrize("event", ["SessionStart", "UserPromptSubmit"])
def test_claude_context_is_native_event_additional_context(workspace, monkeypatch, capsys, event):
    code, output, error = run_hook(workspace, monkeypatch, capsys, event, prompt="Investigate")
    assert code == 0 and not error
    specific = output["hookSpecificOutput"]
    assert specific["hookEventName"] == event
    assert "claude-code:native" in specific["additionalContext"]
    assert "permissionDecision" not in specific


@pytest.mark.parametrize("mode,decision", [("enforce", "deny"), ("observe", None)])
@pytest.mark.parametrize("tool", ["Write", "NotebookEdit", "Bash"])
def test_pretool_deny_preserves_native_permission_flow(workspace, monkeypatch, capsys, mode, decision, tool):
    code, output, error = run_hook(workspace, monkeypatch, capsys, "PreToolUse", mode=mode,
                                   tool_name=tool, tool_input={"command": "echo data > file"})
    assert code == 0 and not error
    specific = output["hookSpecificOutput"]
    assert specific["hookEventName"] == "PreToolUse"
    assert specific.get("permissionDecision") == decision
    assert "plan" in specific["additionalContext"].lower()


def test_pretool_valid_state_never_auto_allows(workspace, monkeypatch, capsys):
    code, output, error = run_hook(workspace, monkeypatch, capsys, "PreToolUse",
                                   tool_name="Read", tool_input={"file_path": "README.md"})
    assert code == 0 and output is None and not error


def test_pretool_approved_durable_work_never_auto_allows(workspace, monkeypatch, capsys):
    app = WorkflowApplication(workspace, session_id="claude-code:native")
    app.summarize_run("Update file", workflow_mode="fast")
    app.apply_plan("PLAN-001", title="Update file")
    app.create_task("TASK-001", "Edit file", "PLAN-001", "Change one file", "Edit file", "Inspect diff")
    app.record_approval(decision="approved", prompt="Implement this change", source="explicit_user")
    code, output, error = run_hook(workspace, monkeypatch, capsys, "PreToolUse", tool_name="Write",
                                   tool_input={"file_path": "file", "content": "updated"})
    assert code == 0 and not error
    assert output is None or "permissionDecision" not in output.get("hookSpecificOutput", {})


@pytest.mark.parametrize("tool,tool_input", [("WebSearch", {"query": "docs"}), ("WebFetch", {"url": "https://example.com"}),
                                              ("mcp__docs__lookup", {"query": "API"})])
def test_posttool_findings_guidance_reaches_claude_context(workspace, monkeypatch, capsys, tool, tool_input):
    code, output, error = run_hook(workspace, monkeypatch, capsys, "PostToolUse", tool_name=tool, tool_input=tool_input)
    assert code == 0 and not error
    assert output["hookSpecificOutput"] == {
        "hookEventName": "PostToolUse", "additionalContext": hooks.tapl_context.external_findings_guidance(),
    }


def test_claude_stop_blocks_once_and_does_not_archive_unfinished_run(workspace, monkeypatch, capsys):
    app = WorkflowApplication(workspace, session_id="claude-code:native")
    app.summarize_run("Unfinished")
    app.apply_plan("PLAN-001", title="Plan")
    app.create_task("TASK-001", "Pending", "PLAN-001", "Goal", "Action", "Check")
    code, output, _ = run_hook(workspace, monkeypatch, capsys, "Stop", stop_hook_active=False)
    assert code == 0 and output["decision"] == "block" and output["reason"]
    code, output, _ = run_hook(workspace, monkeypatch, capsys, "Stop", stop_hook_active=True)
    assert code == 0 and output is None
    assert app.get_status()["tasks"][0]["status"] == "Pending"
    assert app.get_status()["active_run"] is not None


def test_claude_final_assistant_message_can_archive_a_completed_answer(workspace, monkeypatch, capsys):
    app = WorkflowApplication(workspace, session_id="claude-code:native")
    run_id = app.summarize_run("Answer", work_type="answer", workflow_mode="fast")["active_run"]["id"]
    code, output, _ = run_hook(workspace, monkeypatch, capsys, "Stop", last_assistant_message="Verified answer")
    assert code == 0 and output is None
    assert app.get_status()["active_run"] is None
    with closing(db.connect(db.default_db_path(workspace), session_id="claude-code:native")) as conn:
        assert db.list_archives(conn)[0]["run_id"] == run_id


def test_helper_hooks_reuse_parent_owner_without_root_lifecycle(workspace, monkeypatch, capsys):
    code, output, _ = run_hook(workspace, monkeypatch, capsys, "UserPromptSubmit", diagnostic=True,
                               agent_id="worker", prompt="Assigned investigation")
    assert code == 0 and output["session_id"] == "claude-code:native"
    assert output["agent_role"] == "helper"
    assert not output["context"]["active_run"]["present"]
    assert output["context"]["next_actions"] == []
    assert "parent owns run" in output["message"]
    app = WorkflowApplication(workspace, session_id="claude-code:native")
    run_id = app.summarize_run("Parent answer", work_type="answer", workflow_mode="fast")["active_run"]["id"]
    code, output, _ = run_hook(workspace, monkeypatch, capsys, "Stop", agent_id="worker", last_assistant_message="Helper done")
    assert code == 0 and output is None
    assert app.get_status()["active_run"]["id"] == run_id
    # A helper's editing still passes through the parent's workflow gate.
    code, output, _ = run_hook(workspace, monkeypatch, capsys, "PreToolUse", agent_id="worker",
                               tool_name="Write", tool_input={"file_path": "file", "content": "text"})
    assert code == 0 and output["hookSpecificOutput"]["permissionDecision"] == "deny"


@pytest.mark.parametrize("raw", ["", "not json", "[]", "{}", '{"session_id":"native","tool_name":"Bash","tool_input":[]}'])
def test_malformed_enforce_payload_fails_closed_in_native_protocol(workspace, monkeypatch, capsys, raw):
    monkeypatch.setattr(sys, "stdin", io.StringIO(raw))
    assert hook_cli.main(["--client", "claude-code", "--event", "PreToolUse", "--mode", "enforce"]) == 0
    output = capsys.readouterr()
    assert json.loads(output.out)["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "TAPL hook failed" in output.out
    assert output.err


def test_failure_observe_diagnostic_and_stop_repeat_protocol(workspace, monkeypatch, capsys):
    code, output, error = run_hook(workspace, monkeypatch, capsys, "PreToolUse", mode="observe", tool_name="Bash")
    assert code == 1 and output is None and error
    code, output, error = run_hook(workspace, monkeypatch, capsys, "PreToolUse", diagnostic=True, tool_name="Bash")
    assert code == 1 and output["ok"] is False
    code, output, error = run_hook(workspace, monkeypatch, capsys, "Stop", session_id=None, stop_hook_active=True)
    assert code == 0 and output is None and error


def test_direct_hook_restores_binding_and_rejects_owner_mismatch(workspace):
    path = db.default_db_path(workspace)
    with closing(db.connect(path)) as conn:
        out = hooks.handle_event(conn, event="UserPromptSubmit", mode="observe", tool=None,
                                 payload={"session_id": "native"}, client="claude-code")
        assert out["session_id"] == "claude-code:native"
        assert db.connection_session_id(conn) == ""
    with closing(db.connect(path, session_id="native")) as conn:
        with pytest.raises(ValueError, match="session"):
            hooks.handle_event(conn, event="UserPromptSubmit", mode="observe", tool=None,
                               payload={"session_id": "native"}, client="claude-code")
        assert db.connection_session_id(conn) == "native"
    with closing(db.connect(path)) as conn:
        with pytest.raises(ValueError, match="different TAPL client"):
            hooks.handle_event(conn, event="UserPromptSubmit", mode="observe", tool=None,
                               payload={"session_id": "claude-code:native"}, client="codex")
        assert db.active_run(conn) is None


def test_mcp_environment_capture_isolates_host_policy_and_owner_every_call(workspace, monkeypatch):
    monkeypatch.setenv("TAPL_CLIENT", "claude-code")
    claude = mcp_server.create_server(workspace_root=workspace)
    codex = mcp_server.create_server(workspace_root=workspace, client="codex")
    # The MCP transport keeps the host chosen at startup, even after the
    # process's ambient environment changes or another host server starts.
    monkeypatch.setenv("TAPL_CLIENT", "codex")

    async def exercise():
        async with Client(claude) as cc, Client(codex) as cx:
            async def initialize(transport, owner, expected_client, strategy):
                receipt = await transport.call_tool("tapl_summarize_run", {
                    "session_id": owner, "summary": expected_client, "work_type": "analysis", "workflow_mode": "fast",
                })
                assert not receipt.is_error, receipt.content
                next_result = await transport.call_tool("tapl_get_next", {"session_id": owner})
                assert not next_result.is_error, next_result.content
                details = next_result.structured_content
                assert details["config"].get("client", "codex") == expected_client
                assert details["config"]["subagents"]["strategy"] == strategy
                return receipt.structured_content["active_run"]["id"]

            ids = await asyncio.gather(
                initialize(cc, "claude-code:native", "claude-code", "aggressive"),
                initialize(cx, "native", "codex", "conservative"),
            )
            assert ids[0] != ids[1]
            for args in ({}, {"session_id": ""}, {"session_id": "native"}):
                result = await cc.call_tool("tapl_get_status", args)
                assert result.is_error
            assert (await cx.call_tool("tapl_get_status", {"session_id": "claude-code:native"})).is_error
            assert (await cc.call_tool("tapl_get_status", {"session_id": "claude-code:native"})).structured_content["active_run"]["id"] == ids[0]
            assert (await cx.call_tool("tapl_get_status", {"session_id": "native"})).structured_content["active_run"]["id"] == ids[1]
            configured = await cc.call_tool("tapl_configure_subagents", {
                "session_id": "claude-code:native", "user_confirmed": True, "enabled": False,
                "strategy": "balanced", "models": {}, "available_models": {},
            })
            assert not configured.is_error, configured.content
            claude_settings = (await cc.call_tool("tapl_get_next", {"session_id": "claude-code:native"})).structured_content["config"]
            codex_settings = (await cx.call_tool("tapl_get_next", {"session_id": "native"})).structured_content["config"]
            assert claude_settings["subagents"]["strategy"] == "balanced"
            assert codex_settings["subagents"]["strategy"] == "conservative"

    asyncio.run(exercise())
    assert clients.current_client() == "codex"


def test_claude_refresh_and_recommendations_use_captured_host(workspace, monkeypatch):
    monkeypatch.setenv("TAPL_CLIENT", "codex")
    with mock.patch.object(mcp_server.tapl_install, "auto_install_if_needed") as refresh:
        mcp_server.create_server(workspace_root=workspace, client="claude-code", refresh_install=True)
    refresh.assert_called_once_with(start=workspace, client="claude-code")
    recommendations = {"recommendations": [{"name": "configure-subagents"}, {"name": "confirm-after-plan"}]}
    assert all(item["tool"] == "AskUserQuestion" for item in mcp_server.mcp_next_recommendations(recommendations, client="claude-code")["recommendations"])
    assert all(item["tool"] == "request_user_input" for item in mcp_server.mcp_next_recommendations(recommendations, client="codex")["recommendations"])


def test_claude_tool_help_registration_uses_explicit_host_scope(workspace):
    seen = []
    original_help = mcp_server.tapl_prompt.field_help

    def field_help(*args, **kwargs):
        seen.append(clients.current_client())
        return original_help(*args, **kwargs)

    with mock.patch.object(mcp_server.tapl_prompt, "field_help", side_effect=field_help):
        mcp_server.create_server(workspace_root=workspace, client="claude-code")
    assert seen and set(seen) == {"claude-code"}
    assert clients.current_client() == "codex"


def test_hook_refresh_load_and_handler_share_claude_scope(workspace, monkeypatch, capsys):
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"cwd": str(workspace), "session_id": "native"})))
    original_load = config.load
    seen = []

    def refresh(**kwargs):
        seen.append(clients.current_client())
        assert kwargs == {"start": workspace, "mode": "observe", "client": "claude-code"}

    def load(*args, **kwargs):
        seen.append(clients.current_client())
        return original_load(*args, **kwargs)

    with mock.patch.object(hook_cli.tapl_install, "auto_install_if_needed", side_effect=refresh), \
            mock.patch.object(hook_cli.tapl_config, "load", side_effect=load):
        assert hook_cli.main(["--client", "claude-code", "--event", "SessionStart", "--json"]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["context"]["config"]["client"] == "claude-code"
    assert seen == ["claude-code", "claude-code"]
