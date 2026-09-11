from __future__ import annotations

import asyncio
import inspect
import tempfile
from pathlib import Path
from unittest import mock

from mcp import Client

from taplctl import config, db, prompt
from taplctl import mcp_server


def _workspace(tmp: str) -> Path:
    root = Path(tmp) / "workspace"
    (root / ".git").mkdir(parents=True)
    db.initialize_workspace(root)
    (root / ".tapl/config.toml").write_text("[subagents]\nenabled = false\n", encoding="utf-8")
    return root


def test_mcp_module_has_no_cli_subprocess_data_plane() -> None:
    source = inspect.getsource(mcp_server)
    assert "create_subprocess_exec" not in source
    assert "run_taplctl" not in source
    assert "TaplCliError" not in source
    assert not hasattr(mcp_server, "run_taplctl")
    assert not hasattr(mcp_server, "run_taplctl_write")


def test_mcp_bootstrap_loads_full_policy_and_supports_explicit_retention() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = _workspace(tmp)
        with mock.patch.object(mcp_server, "MCPServer", wraps=mcp_server.MCPServer) as factory:
            server = mcp_server.create_server(workspace_root=root)
        assert factory.call_args.kwargs["instructions"] == prompt.mcp_bootstrap_instructions()

        async def exercise() -> None:
            async with Client(server) as client:
                full = (await client.call_tool("tapl_get_next", {})).structured_content
                expected = prompt.mcp_server_instructions(subagents=config.load(start=root).subagents)
                assert full["workflow_policy"] == expected
                assert full["policy_unchanged"] is False
                cached = (await client.call_tool("tapl_get_next", {"known_policy_revision": full["policy_revision"]})).structured_content
                assert cached["policy_unchanged"] is True
                assert "workflow_policy" not in cached
                assert cached["recommendations"] == full["recommendations"]
                reloaded = (await client.call_tool("tapl_get_next", {})).structured_content
                assert reloaded["workflow_policy"] == expected
            async with Client(server) as fresh_client:
                fresh = (await fresh_client.call_tool("tapl_get_next", {})).structured_content
                assert fresh["workflow_policy"] == expected

        asyncio.run(exercise())


def test_mcp_custom_instructions_remain_authoritative_in_full_policy() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        custom = "Custom host policy"
        with mock.patch.object(mcp_server, "MCPServer", wraps=mcp_server.MCPServer) as factory:
            server = mcp_server.create_server(workspace_root=_workspace(tmp), instructions=custom)
        assert factory.call_args.kwargs["instructions"] == custom

        async def exercise() -> None:
            async with Client(server) as client:
                full = (await client.call_tool("tapl_get_next", {})).structured_content
                assert full["workflow_policy"] == custom

        asyncio.run(exercise())


def test_mcp_exposes_native_application_tools() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        tools = asyncio.run(mcp_server.create_server(workspace_root=_workspace(tmp)).list_tools())

    by_name = {tool.name: tool for tool in tools}
    assert len(tools) == 29
    assert "tapl_get_context" in by_name
    assert "tapl_list_archives" in by_name
    assert "tapl_get_archive" in by_name
    assert "tapl_split_run" in by_name
    assert by_name["tapl_get_context"].annotations.read_only_hint
    assert set(by_name["tapl_create_task"].input_schema["required"]) == {
        "task_id",
        "title",
        "spec_id",
        "goal",
        "action",
        "verification",
    }
    split_schema = by_name["tapl_split_run"].input_schema
    assert split_schema["required"] == ["requests"]
    assert split_schema["properties"]["requests"]["minItems"] == 2
    assert set(split_schema["$defs"]["SplitRunRequest"]["required"]) == {
        "key",
        "summary",
        "work_type",
        "workflow_mode",
    }


def test_mcp_split_run_queues_and_activates_dependent_request() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        server = mcp_server.create_server(workspace_root=_workspace(tmp))

        async def exercise() -> list[object]:
            async with Client(server) as client:
                split = await client.call_tool(
                    "tapl_split_run",
                    {
                        "requests": [
                            {
                                "key": "conversation-title",
                                "summary": "Generate conversation titles asynchronously",
                                "work_type": "implementation",
                                "workflow_mode": "standard",
                            },
                            {
                                "key": "suggestion-chips",
                                "summary": "Build suggestion chips from conversation titles",
                                "work_type": "implementation",
                                "workflow_mode": "standard",
                                "depends_on": ["conversation-title"],
                            },
                        ]
                    },
                )
                finished = await client.call_tool(
                    "tapl_finish_run",
                    {"result": "Conversation title generation is complete."},
                )
                archived = await client.call_tool(
                    "tapl_finish_archive",
                    {"slug": "conversation-title"},
                )
                return [split, finished, archived]

        split, finished, archived = asyncio.run(exercise())

    assert not split.is_error
    assert split.structured_content["operation"] == "run_split"
    assert split.structured_content["active_run"]["split_key"] == "conversation-title"
    assert split.structured_content["queued_runs"][0]["waiting_on"] == [
        "conversation-title"
    ]
    assert finished.structured_content["operation"] == "run_finish"
    assert archived.structured_content["next_active_run"]["split_key"] == "suggestion-chips"
    assert "request_summary" not in archived.structured_content["next_active_run"]


def test_mcp_topic_plans_keep_distinct_ids_and_references() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        server = mcp_server.create_server(workspace_root=_workspace(tmp))

        async def exercise() -> None:
            async with Client(server) as client:
                summarized = await client.call_tool(
                    "tapl_summarize_run",
                    {"summary": "Host patterns and reasoning settings", "work_type": "implementation", "workflow_mode": "standard"},
                )
                run_id = summarized.structured_content["active_run"]["id"]
                for number, topic in enumerate(("Host patterns", "Reasoning settings"), start=1):
                    applied = await client.call_tool(
                        "tapl_apply_plan",
                        {"plan_id": f"PLAN-{number:03d}", "title": topic, "summary": f"REQ-{number:03d}: {topic}", "validation": "Focused regression"},
                    )
                    assert not applied.is_error
                    assert applied.structured_content["item"]["stable_id"] == f"PLAN-{number:03d}"
                    assert "title" not in applied.structured_content["item"]

                status = (await client.call_tool("tapl_get_status", {"full": True})).structured_content
                assert status["active_run"]["id"] == run_id
                assert status["queued_runs"] == []
                assert status["tasks"] == []
                assert [plan["title"] for plan in status["plans"]] == ["Host patterns", "Reasoning settings"]

                created = await client.call_tool(
                    "tapl_create_task",
                    {"task_id": "TASK-001", "title": "Configure reasoning", "spec_id": "PLAN-002", "goal": "Expose reasoning settings", "action": "Implement settings", "verification": "Settings round trip"},
                )
                assert not created.is_error
                status = (await client.call_tool("tapl_get_status", {"full": True})).structured_content
                assert status["tasks"][0]["spec_id"] == "PLAN-002"
                assert {plan["run_id"] for plan in status["plans"]} == {run_id}

        asyncio.run(exercise())


def test_mcp_native_sequential_lifecycle_never_spawns_cli() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        server = mcp_server.create_server(workspace_root=_workspace(tmp))

        async def exercise() -> list[object]:
            async with Client(server) as client:
                return [
                    await client.call_tool(
                        "tapl_summarize_run",
                        {
                            "summary": "Native MCP lifecycle",
                            "work_type": "implementation",
                            "workflow_mode": "standard",
                        },
                    ),
                    await client.call_tool(
                        "tapl_apply_plan",
                        {
                            "plan_id": "PLAN-001",
                            "title": "Native application plan",
                            "summary": "REQ-001: use the direct application boundary.",
                            "objective": "Exercise MCP without a CLI process.",
                            "requirements_trace": "REQ-001 maps to the native lifecycle.",
                            "selected_approach": "Call WorkflowApplication from worker threads.",
                            "affected_files": "Temporary TAPL database only.",
                            "execution_order": "Create, approve, start, complete, archive.",
                            "risks": "Adapter fields could drift from the application API.",
                            "validation": "Run focused native MCP tests.",
                            "status": "Finalized",
                        },
                    ),
                    await client.call_tool(
                        "tapl_create_task",
                        {
                            "task_id": "TASK-001",
                            "title": "Exercise native MCP lifecycle",
                            "spec_id": "PLAN-001",
                            "goal": "Prove the direct MCP data plane.",
                            "action": "Invoke every representative lifecycle adapter.",
                            "verification": "Native MCP calls succeed without subprocesses.",
                            "custom_fields": {"adapter": "native"},
                        },
                    ),
                    await client.call_tool(
                        "tapl_approve_execution",
                        {"prompt": "Execute TASK-001", "source": "explicit_user"},
                    ),
                    await client.call_tool("tapl_start_task", {"task_id": "TASK-001"}),
                    await client.call_tool(
                        "tapl_add_finding",
                        {
                            "title": "Native adapter reached",
                            "finding": "MCP called the application boundary directly.",
                            "related_ids": "TASK-001",
                        },
                    ),
                    await client.call_tool(
                        "tapl_complete_task",
                        {
                            "task_id": "TASK-001",
                            "verification": "Focused native tests passed.",
                            "result": "Direct lifecycle completed.",
                        },
                    ),
                    await client.call_tool("tapl_get_context", {"event": "Manual"}),
                    await client.call_tool("tapl_validate_state", {}),
                    await client.call_tool(
                        "tapl_finish_run",
                        {"result": "Native MCP lifecycle verified."},
                    ),
                    await client.call_tool(
                        "tapl_finish_archive",
                        {"slug": "native-mcp-lifecycle", "summary": "Direct MCP data plane."},
                    ),
                    await client.call_tool("tapl_get_status", {}),
                ]

        with mock.patch.object(
            asyncio,
            "create_subprocess_exec",
            side_effect=AssertionError("MCP must not spawn taplctl"),
        ):
            calls = asyncio.run(exercise())

    failures = [call.content[0].text for call in calls if call.is_error]
    assert failures == []
    assert calls[0].structured_content["operation"] == "run_summarize"
    assert calls[2].structured_content["operation"] == "task_create"
    assert calls[6].structured_content["operation"] == "task_complete"
    assert calls[7].structured_content["active_run"]["present"] is True
    assert calls[-1].structured_content["active_run"] is None
