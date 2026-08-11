from __future__ import annotations

import contextlib
import concurrent.futures
import hashlib
import io
import argparse
import asyncio
import json
import os
import shlex
import sqlite3
import subprocess
import sys
import tempfile
import tomllib
import types
import unittest
import warnings
from pathlib import Path
from unittest import mock

from mcp import Client
from mcp.client.stdio import StdioServerParameters, stdio_client


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from taplctl import (
    __version__,
    cli as tapl_cli,
    config as tapl_config,
    db as tapl_db,
    embeddings as tapl_embeddings,
    install as tapl_install,
    mcp_server as tapl_mcp,
    prompt as tapl_prompt,
    updater as tapl_updater,
)


class TaplCliTests(unittest.TestCase):
    def tapl_env(self) -> dict[str, str]:
        env = os.environ.copy()
        env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
        return env

    def run_cli(self, db_path: Path, *args: str, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "taplctl", "--db", str(db_path), *args],
            input=input_text,
            text=True,
            capture_output=True,
            check=False,
            env=self.tapl_env(),
        )

    def run_taplctl(
        self,
        *args: str,
        input_text: str | None = None,
        cwd: Path | None = None,
        env_overrides: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        env = self.tapl_env()
        if env_overrides:
            env.update(env_overrides)
        return subprocess.run(
            [sys.executable, "-m", "taplctl", *args],
            input=input_text,
            text=True,
            capture_output=True,
            check=False,
            env=env,
            cwd=str(cwd) if cwd else None,
        )

    def create_parallel_fixture(
        self,
        db_path: Path,
        *,
        task_ids: tuple[str, ...] = ("TASK-001", "TASK-002", "TASK-003"),
        owned_paths: tuple[str, ...] = ("tapl/a.py", "tapl/b.py", "tapl/c.py"),
        dependencies: dict[str, list[str]] | None = None,
        executor_kinds: dict[str, str] | None = None,
    ) -> None:
        plan = self.run_cli(
            db_path, "plan", "set", "--id", "PLAN-001", "--title", "Parallel plan",
            "--status", "Finalized", "--summary", "Dispatch independent subagent tasks.", "--json",
        )
        self.assertEqual(plan.returncode, 0, plan.stderr)
        for index, task_id in enumerate(task_ids):
            payload = {
                "id": task_id,
                "title": f"{task_id} parallel work",
                "spec_id": "PLAN-001",
                "goal": f"Complete {task_id}",
                "action": f"Implement {task_id}",
                "verification": f"Verify {task_id}",
                "execution_mode": "parallel",
                "executor_kind": (executor_kinds or {}).get(task_id, "subagent"),
                "parallel_group": "workers",
                "owned_paths": [owned_paths[index]],
                "depends_on": [],
            }
            task = self.run_cli(
                db_path, "task", "create", "--stdin-json", "--json", input_text=json.dumps(payload)
            )
            self.assertEqual(task.returncode, 0, task.stderr)
        for task_id, task_dependencies in (dependencies or {}).items():
            updated = self.run_cli(
                db_path,
                "task",
                "set",
                "--stdin-json",
                "--json",
                input_text=json.dumps({"id": task_id, "depends_on": task_dependencies}),
            )
            self.assertEqual(updated.returncode, 0, updated.stderr)
        approval = self.run_cli(
            db_path, "approval", "approve", "--prompt", "Execute parallel work", "--json"
        )
        self.assertEqual(approval.returncode, 0, approval.stderr)

    def status_json(self, db_path: Path, *, full: bool = True) -> dict[str, object]:
        result = self.run_cli(db_path, "status", "--json", *( ["--full"] if full else []))
        self.assertEqual(result.returncode, 0, f"{result.stderr}\n{result.stdout}")
        return json.loads(result.stdout)

    def test_version_comes_from_pyproject(self) -> None:
        with (ROOT / "pyproject.toml").open("rb") as pyproject_file:
            pyproject = tomllib.load(pyproject_file)
        expected_version = pyproject["project"]["version"]

        self.assertEqual(__version__, expected_version)

        version = self.run_taplctl("--version")
        self.assertEqual(version.returncode, 0, version.stderr)
        self.assertEqual(version.stdout.strip(), f"taplctl {expected_version}")

    def test_mcp_tools_expose_typed_high_level_contracts(self) -> None:
        server = tapl_mcp.create_server(workspace_root=ROOT)
        tools = asyncio.run(server.list_tools())
        by_name = {tool.name: tool for tool in tools}

        self.assertEqual(len(tools), 20)
        self.assertIn("tapl_get_status", by_name)
        self.assertIn("tapl_apply_plan", by_name)
        self.assertIn("tapl_create_task", by_name)
        self.assertIn("tapl_finish_archive", by_name)
        self.assertTrue(by_name["tapl_get_status"].annotations.read_only_hint)
        self.assertFalse(by_name["tapl_create_task"].annotations.read_only_hint)
        self.assertFalse(by_name["tapl_create_task"].annotations.open_world_hint)

        task_schema = by_name["tapl_create_task"].input_schema
        self.assertEqual(
            set(task_schema["required"]),
            {"task_id", "title", "spec_id", "goal", "action", "verification"},
        )
        self.assertEqual(task_schema["properties"]["task_id"]["pattern"], r"^TASK-\d{3,}$")
        self.assertEqual(
            task_schema["properties"]["execution_mode"]["enum"],
            ["sequential", "parallel"],
        )
        self.assertNotIn("workspace", task_schema["properties"])
        summarize_schema = by_name["tapl_summarize_run"].input_schema
        self.assertEqual(
            summarize_schema["properties"]["workflow_mode"]["enum"],
            ["planned", "lightweight"],
        )
        self.assertEqual(
            summarize_schema["properties"]["workflow_mode"]["default"],
            "planned",
        )

    def test_mcp_tools_map_to_cli_json_and_hide_shell_recipes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            (workspace / ".git").mkdir(parents=True)
            tapl_db.initialize_workspace(workspace)
            server = tapl_mcp.create_server(workspace_root=workspace)

            async def exercise() -> tuple[object, object, object]:
                async with Client(server) as client:
                    summarized = await client.call_tool(
                        "tapl_summarize_run",
                        {"summary": "MCP structured workflow", "workflow_mode": "planned"},
                    )
                    status = await client.call_tool("tapl_get_status", {})
                    next_action = await client.call_tool("tapl_get_next", {})
                    return summarized, status, next_action

            summarized, status, next_action = asyncio.run(exercise())
            self.assertFalse(summarized.is_error)
            summary_receipt = summarized.structured_content
            self.assertEqual(summary_receipt["operation"], "run_summarize")
            self.assertEqual(summary_receipt["active_run"]["workflow_mode"], "planned")
            self.assertNotIn("request_summary", summary_receipt["active_run"])
            self.assertEqual(summary_receipt["recommendations"][0]["tool"], "tapl_apply_plan")
            self.assertNotIn("command", summary_receipt["recommendations"][0])
            self.assertEqual(
                status.structured_content["active_run"]["request_summary"],
                "MCP structured workflow",
            )
            recommendation = next_action.structured_content["recommendations"][0]
            self.assertEqual(recommendation["tool"], "tapl_apply_plan")
            self.assertNotIn("command", recommendation)

    def test_every_mcp_write_tool_routes_through_compact_receipt_with_next(self) -> None:
        server = tapl_mcp.create_server(workspace_root=ROOT)
        calls = (
            ("tapl_summarize_run", {"summary": "Receipt routing"}),
            ("tapl_apply_plan", {}),
            (
                "tapl_create_task",
                {
                    "task_id": "TASK-001",
                    "title": "Route task write",
                    "spec_id": "PLAN-001",
                    "goal": "Exercise the write facade.",
                    "action": "Call the tool.",
                    "verification": "The compact helper is invoked.",
                },
            ),
            ("tapl_start_task", {"task_id": "TASK-001"}),
            ("tapl_dispatch_tasks", {"task_ids": ["TASK-001", "TASK-002"]}),
            (
                "tapl_complete_task",
                {"task_id": "TASK-001", "verification": "Verified", "result": "Done"},
            ),
            (
                "tapl_block_task",
                {"task_id": "TASK-001", "blocker": "Blocked", "next_action": "Resolve"},
            ),
            ("tapl_skip_task", {"task_id": "TASK-001", "result": "Superseded"}),
            ("tapl_cancel_batch", {"batch_id": "BATCH-001", "reason": "Cancelled"}),
            ("tapl_recover_batch", {"batch_id": "BATCH-001", "reason": "Recover"}),
            ("tapl_add_finding", {"title": "Finding"}),
            ("tapl_approve_execution", {"prompt": "Approve"}),
            ("tapl_reject_execution", {"prompt": "Reject"}),
            ("tapl_finish_run", {"result": "Finished"}),
            ("tapl_finish_archive", {"slug": "receipt-routing"}),
        )

        async def fake_write(
            workspace_root: Path,
            *command: str,
            payload: dict[str, object] | None = None,
            operation: str,
        ) -> dict[str, object]:
            del workspace_root, command, payload
            return {
                "ok": True,
                "operation": operation,
                "recommendations": [{"tool": "tapl_get_status"}],
            }

        async def exercise() -> list[object]:
            async with Client(server) as client:
                return [await client.call_tool(name, arguments) for name, arguments in calls]

        with mock.patch.object(
            tapl_mcp,
            "run_taplctl_write",
            new=mock.AsyncMock(side_effect=fake_write),
        ) as write:
            results = asyncio.run(exercise())

        self.assertEqual(write.await_count, len(calls))
        self.assertEqual(len(calls), 15)
        for result in results:
            self.assertFalse(result.is_error)
            self.assertIn("operation", result.structured_content)
            self.assertIn("recommendations", result.structured_content)

    def test_mcp_successful_write_keeps_receipt_when_next_lookup_fails(self) -> None:
        raw_write = {
            "ok": True,
            "active_run": {
                "id": "run-id",
                "slug": "active",
                "status": "active",
                "workflow_mode": "planned",
                "request_summary": "Do not echo this body",
            },
        }
        with mock.patch.object(
            tapl_mcp,
            "run_taplctl",
            new=mock.AsyncMock(
                side_effect=[raw_write, tapl_mcp.TaplCliError("next unavailable")]
            ),
        ):
            receipt = asyncio.run(
                tapl_mcp.run_taplctl_write(
                    ROOT,
                    "run",
                    "summarize",
                    payload={"summary": "Compact"},
                    operation="run_summarize",
                )
            )

        self.assertTrue(receipt["ok"])
        self.assertNotIn("request_summary", receipt["active_run"])
        self.assertEqual(receipt["recommendations"][0]["tool"], "tapl_get_status")

    def test_mcp_cli_errors_are_returned_as_actionable_tool_errors(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            (workspace / ".git").mkdir(parents=True)
            tapl_db.initialize_workspace(workspace)
            server = tapl_mcp.create_server(workspace_root=workspace)

            async def exercise() -> object:
                async with Client(server) as client:
                    return await client.call_tool("tapl_get_item", {"item_id": 999})

            result = asyncio.run(exercise())
            self.assertTrue(result.is_error)
            self.assertIn("item not found: 999", result.content[0].text)

    def test_taplctl_mcp_stdio_entrypoint_negotiates_and_calls_tools(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            (workspace / ".git").mkdir(parents=True)
            tapl_db.initialize_workspace(workspace)
            params = StdioServerParameters(
                command=sys.executable,
                args=["-m", "taplctl", "mcp"],
                cwd=workspace,
            )

            async def exercise() -> tuple[object, object]:
                async with Client(stdio_client(params)) as client:
                    tools = await client.list_tools()
                    result = await client.call_tool(
                        "tapl_summarize_run",
                        {"summary": "stdio MCP smoke test"},
                    )
                    return tools, result

            tools, result = asyncio.run(exercise())
            self.assertEqual(len(tools.tools), 20)
            self.assertFalse(result.is_error)
            receipt = result.structured_content
            self.assertEqual(receipt["operation"], "run_summarize")
            self.assertEqual(receipt["active_run"]["workflow_mode"], "planned")
            self.assertNotIn("request_summary", receipt["active_run"])
            self.assertEqual(receipt["recommendations"][0]["tool"], "tapl_apply_plan")

    def test_mcp_tools_complete_a_sequential_workflow_lifecycle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            (workspace / ".git").mkdir(parents=True)
            tapl_db.initialize_workspace(workspace)
            server = tapl_mcp.create_server(workspace_root=workspace)

            async def exercise() -> list[object]:
                async with Client(server) as client:
                    calls = [
                        await client.call_tool("tapl_summarize_run", {"summary": "MCP lifecycle"}),
                        await client.call_tool(
                            "tapl_apply_plan",
                            {
                                "plan_id": "PLAN-001",
                                "title": "MCP lifecycle plan",
                                "summary": "REQ-001: exercise the typed MCP lifecycle.",
                                "objective": "Verify the MCP facade end to end.",
                                "requirements_trace": "REQ-001: map typed calls to taplctl JSON.",
                                "selected_approach": "Use the in-memory MCP client against a temporary workspace.",
                                "affected_files": "Temporary TAPL database only.",
                                "execution_order": "Plan, task, approve, execute, verify, archive.",
                                "risks": "Subprocess mapping could diverge from the CLI contract.",
                                "validation": "Require every MCP result to succeed.",
                                "status": "Finalized",
                            },
                        ),
                        await client.call_tool(
                            "tapl_create_task",
                            {
                                "task_id": "TASK-001",
                                "title": "Exercise MCP lifecycle",
                                "spec_id": "PLAN-001",
                                "goal": "Complete one sequential MCP-managed task.",
                                "action": "Call the typed lifecycle tools in order.",
                                "verification": "All returned tool results are successful.",
                            },
                        ),
                        await client.call_tool(
                            "tapl_create_task",
                            {
                                "task_id": "TASK-002",
                                "title": "Verify MCP lifecycle",
                                "spec_id": "PLAN-001",
                                "goal": "Validate the completed MCP-managed state.",
                                "action": "Run TAPL validation after implementation settlement.",
                                "verification": "tapl_validate_state succeeds.",
                                "depends_on": ["TASK-001"],
                            },
                        ),
                        await client.call_tool(
                            "tapl_approve_execution",
                            {"prompt": "Execute TASK-001 from PLAN-001", "source": "explicit_user"},
                        ),
                        await client.call_tool("tapl_start_task", {"task_id": "TASK-001"}),
                        await client.call_tool(
                            "tapl_add_finding",
                            {
                                "title": "MCP mapping exercised",
                                "source": "automated test",
                                "finding": "Typed calls reached the CLI JSON handlers.",
                                "impact": "The facade follows the existing lifecycle implementation.",
                                "related_ids": "PLAN-001, TASK-001",
                            },
                        ),
                        await client.call_tool(
                            "tapl_complete_task",
                            {
                                "task_id": "TASK-001",
                                "verification": "Every prior MCP call succeeded.",
                                "result": "Sequential workflow completed.",
                            },
                        ),
                        await client.call_tool("tapl_start_task", {"task_id": "TASK-002"}),
                        await client.call_tool("tapl_validate_state", {}),
                        await client.call_tool(
                            "tapl_complete_task",
                            {
                                "task_id": "TASK-002",
                                "verification": "The MCP lifecycle state validated successfully.",
                                "result": "Verification task completed.",
                            },
                        ),
                        await client.call_tool("tapl_validate_state", {}),
                        await client.call_tool(
                            "tapl_finish_run",
                            {"result": "MCP sequential lifecycle verified."},
                        ),
                        await client.call_tool(
                            "tapl_finish_archive",
                            {"slug": "mcp-sequential-lifecycle", "summary": "End-to-end MCP lifecycle."},
                        ),
                        await client.call_tool("tapl_get_status", {}),
                    ]
                    return calls

            calls = asyncio.run(exercise())
            failures = [
                call.content[0].text
                for call in calls
                if call.is_error
            ]
            self.assertEqual(failures, [])
            read_call_indexes = {9, 11, 14}
            for index, call in enumerate(calls):
                if index not in read_call_indexes:
                    self.assertIn("operation", call.structured_content)
                    self.assertIn("recommendations", call.structured_content)
            self.assertIsNone(calls[-1].structured_content["active_run"])

    def test_mcp_lightweight_run_finishes_without_plan_or_tasks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            (workspace / ".git").mkdir(parents=True)
            tapl_db.initialize_workspace(workspace)
            server = tapl_mcp.create_server(workspace_root=workspace)

            async def exercise() -> list[object]:
                async with Client(server) as client:
                    summarized = await client.call_tool(
                        "tapl_summarize_run",
                        {"summary": "Answer a simple question", "workflow_mode": "lightweight"},
                    )
                    finished = await client.call_tool(
                        "tapl_finish_run",
                        {"result": "Answered directly."},
                    )
                    archived = await client.call_tool(
                        "tapl_finish_archive",
                        {"slug": "lightweight-question"},
                    )
                    return [summarized, finished, archived]

            summarized, finished, archived = asyncio.run(exercise())
            self.assertEqual(
                summarized.structured_content["active_run"]["workflow_mode"],
                "lightweight",
            )
            self.assertEqual(
                summarized.structured_content["recommendations"][0]["tool"],
                "tapl_finish_run",
            )
            self.assertEqual(
                finished.structured_content["recommendations"][0]["tool"],
                "tapl_finish_archive",
            )
            self.assertEqual(archived.structured_content["operation"], "archive_finish")
            for call in (summarized, finished, archived):
                self.assertFalse(call.is_error)
                self.assertIn("recommendations", call.structured_content)

    def test_mcp_parallel_receipt_preserves_dispatch_contract_and_settlement_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            (workspace / ".git").mkdir(parents=True)
            initialized = tapl_db.initialize_workspace(workspace)
            db_path = Path(initialized["db"])
            self.create_parallel_fixture(
                db_path,
                task_ids=("TASK-001", "TASK-002"),
                owned_paths=("src/a.py", "src/b.py"),
            )
            server = tapl_mcp.create_server(workspace_root=workspace)

            async def exercise() -> tuple[object, list[object]]:
                async with Client(server) as client:
                    dispatched = await client.call_tool(
                        "tapl_dispatch_tasks",
                        {
                            "task_ids": ["TASK-001", "TASK-002"],
                            "batch_id": "BATCH-MCP",
                            "execution_metadata": {
                                "TASK-001": {
                                    "executor_ref": "agent-a",
                                    "model": "gpt-5.6-terra",
                                    "reasoning_effort": "high",
                                }
                            },
                        },
                    )
                    executions = {
                        item["task_id"]: item
                        for item in dispatched.structured_content["executions"]
                    }
                    settled = []
                    for task_id in ("TASK-001", "TASK-002"):
                        settled.append(
                            await client.call_tool(
                                "tapl_complete_task",
                                {
                                    "task_id": task_id,
                                    "execution_id": executions[task_id]["execution_id"],
                                    "verification": f"Verified {task_id}",
                                    "result": f"Completed {task_id}",
                                },
                            )
                        )
                    return dispatched, settled

            dispatched, settled = asyncio.run(exercise())
            manifest = dispatched.structured_content
            self.assertEqual(manifest["operation"], "task_dispatch")
            self.assertEqual(manifest["batch"]["batch_id"], "BATCH-MCP")
            self.assertNotIn("id", manifest["batch"])
            self.assertIn("recommendations", manifest)
            self.assertEqual(len(manifest["executions"]), 2)
            for execution in manifest["executions"]:
                self.assertIn("execution_id", execution)
                self.assertIn("goal", execution)
                self.assertIn("action", execution)
                self.assertIn("verification", execution)
                self.assertIn("owned_paths", execution)
                self.assertNotIn("started_at", execution)
                self.assertNotIn("task_item_id", execution)

            execution_ids = {
                item["task_id"]: item["execution_id"] for item in manifest["executions"]
            }
            for task_id, call in zip(("TASK-001", "TASK-002"), settled, strict=True):
                receipt = call.structured_content
                self.assertEqual(receipt["settled_execution_id"], execution_ids[task_id])
                self.assertIn("recommendations", receipt)
                self.assertNotIn("goal", receipt["executions"][0])

    def test_workspace_db_takes_priority_over_nested_git(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            child_repo = workspace / "services" / "child"
            nested_dir = child_repo / "src"
            (workspace / ".git").mkdir(parents=True)
            (child_repo / ".git").mkdir(parents=True)
            nested_dir.mkdir()

            self.assertEqual(tapl_db.find_repo_root(nested_dir), child_repo.resolve())

            initialized = tapl_db.initialize_workspace(workspace)

            self.assertEqual(initialized["workspace_root"], str(workspace.resolve()))
            self.assertEqual(initialized["db_action"], "created")
            self.assertEqual(tapl_db.find_workspace_root(nested_dir), workspace.resolve())
            self.assertEqual(tapl_db.find_repo_root(nested_dir), workspace.resolve())
            self.assertTrue((workspace / tapl_db.DEFAULT_DB_RELATIVE).is_file())

    def test_nearest_workspace_db_takes_priority(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            child_repo = workspace / "child"
            child_repo.mkdir(parents=True)
            (workspace / ".git").mkdir()
            (child_repo / ".git").mkdir()
            tapl_db.initialize_workspace(workspace)
            tapl_db.initialize_workspace(child_repo)

            self.assertEqual(
                tapl_db.default_db_path(child_repo),
                child_repo.resolve() / tapl_db.DEFAULT_DB_RELATIVE,
            )

    def test_init_workspace_root_is_explicit_and_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            workspace = base / "workspace"
            outside = base / "outside"
            home = base / "home"
            outside.mkdir()
            home.mkdir()
            env = {"HOME": str(home)}

            initialized = self.run_taplctl(
                "init",
                "--workspace-root",
                str(workspace),
                "--json",
                cwd=outside,
                env_overrides=env,
            )
            self.assertEqual(initialized.returncode, 0, initialized.stderr)
            payload = json.loads(initialized.stdout)
            self.assertEqual(payload["workspace_root"], str(workspace.resolve()))
            self.assertEqual(payload["db_action"], "created")
            self.assertTrue((workspace / tapl_db.DEFAULT_DB_RELATIVE).is_file())
            self.assertNotIn("workspace_marker", payload)
            self.assertNotIn("workspace_marker_action", payload)
            self.assertFalse((outside / ".tapl").exists())

            repeated = self.run_taplctl(
                "init",
                "--workspace-root",
                str(workspace),
                "--json",
                cwd=outside,
                env_overrides=env,
            )
            self.assertEqual(repeated.returncode, 0, repeated.stderr)
            repeated_payload = json.loads(repeated.stdout)
            self.assertEqual(repeated_payload["db_action"], "unchanged")

            conflict = self.run_taplctl(
                "--db",
                str(base / "custom.db"),
                "init",
                "--workspace-root",
                str(workspace),
            )
            self.assertEqual(conflict.returncode, 1)
            self.assertIn("--workspace-root cannot be combined with --db", conflict.stderr)

    def test_init_task_status_and_search(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "tapl.db"
            init = self.run_cli(db_path, "init", "--json")
            self.assertEqual(init.returncode, 0, init.stderr)
            self.assertTrue(json.loads(init.stdout)["ok"])

            task = self.run_cli(
                db_path,
                "task",
                "set",
                "--id",
                "TASK-001",
                "--title",
                "Build tapl harness",
                "--status",
                "In Progress",
                "--goal",
                "Create DB-backed workflow state",
                "--json",
            )
            self.assertEqual(task.returncode, 0, task.stderr)

            status = self.run_cli(db_path, "status", "--json")
            payload = json.loads(status.stdout)
            self.assertEqual(payload["task_counts"]["In Progress"], 1)
            self.assertEqual(payload["counts"]["tasks"], 1)
            self.assertEqual(payload["counts"]["archives"], 0)
            self.assertNotIn("recent_events", payload)
            self.assertNotIn("archives", payload)
            self.assertNotIn("body", payload["tasks"][0])
            self.assertNotIn("goal", payload["tasks"][0])

            agent_status = self.run_cli(db_path, "status", "--agent")
            self.assertEqual(agent_status.returncode, 0, agent_status.stderr)
            self.assertIn("<tapl_status>", agent_status.stdout)
            self.assertIn("<tasks>1</tasks>", agent_status.stdout)
            self.assertIn("<incomplete_tasks>1</incomplete_tasks>", agent_status.stdout)
            self.assertIn("<in_progress>1</in_progress>", agent_status.stdout)
            self.assertIn("<goal>Create DB-backed workflow state</goal>", agent_status.stdout)
            self.assertIn("<code>execution_approval_missing</code>", agent_status.stdout)
            self.assertNotIn("<schema>", agent_status.stdout)
            self.assertNotIn("<config>", agent_status.stdout)
            self.assertNotIn("<created_at>", agent_status.stdout)
            self.assertNotIn("<body>", agent_status.stdout)

            full_status = self.run_cli(db_path, "status", "--json", "--full")
            self.assertEqual(full_status.returncode, 0, full_status.stderr)
            full_payload = json.loads(full_status.stdout)
            self.assertNotIn("recent_events", full_payload)
            self.assertNotIn("archives", full_payload)
            self.assertIn("body", full_payload["tasks"][0])
            self.assertEqual(full_payload["tasks"][0]["goal"], "Create DB-backed workflow state")
            self.assertIn("### Goal\nCreate DB-backed workflow state", full_payload["tasks"][0]["body"])

            event = self.run_cli(
                db_path,
                "hook-event",
                "--event",
                "PreToolUse",
                "--mode",
                "observe",
                "--tool",
                "Bash",
                "--json",
                input_text='{"tool_input": {"command": "taplctl status --json"}}',
            )
            self.assertEqual(event.returncode, 0, event.stderr)
            event_status = self.run_cli(db_path, "status", "--json", "--include-events")
            self.assertEqual(event_status.returncode, 0, event_status.stderr)
            event_payload = json.loads(event_status.stdout)
            self.assertEqual(event_payload["recent_events"][0]["event_type"], "PreToolUse")
            self.assertNotIn("archives", event_payload)
            self.assertNotIn("payload_json", event_payload["recent_events"][0])

            status_text = self.run_cli(db_path, "status")
            self.assertEqual(status_text.returncode, 0, status_text.stderr)
            self.assertIn("active run:", status_text.stdout)
            self.assertIn("incomplete tasks: 1", status_text.stdout)
            self.assertNotEqual(status_text.stdout.strip(), "no archives")

            search = self.run_cli(db_path, "search", "workflow", "--json")
            results = json.loads(search.stdout)["results"]
            self.assertEqual(results[0]["stable_id"], "TASK-001")

            agent_search = self.run_cli(db_path, "search", "workflow", "--agent")
            self.assertEqual(agent_search.returncode, 0, agent_search.stderr)
            self.assertIn("<tapl_search>", agent_search.stdout)
            self.assertIn("<query>workflow</query>", agent_search.stdout)
            self.assertIn("<stable_id>TASK-001</stable_id>", agent_search.stdout)
            self.assertNotIn("search_config", agent_search.stdout)
            self.assertNotIn("source_scores", agent_search.stdout)

            detail = self.run_cli(db_path, "item", "show", "--id", str(results[0]["id"]), "--json")
            self.assertEqual(detail.returncode, 0, detail.stderr)
            item = json.loads(detail.stdout)["item"]
            self.assertEqual(item["stable_id"], "TASK-001")
            self.assertEqual(item["goal"], "Create DB-backed workflow state")

            agent_detail = self.run_cli(db_path, "item", "show", "--id", str(results[0]["id"]), "--agent")
            self.assertEqual(agent_detail.returncode, 0, agent_detail.stderr)
            self.assertIn("<tapl_item>", agent_detail.stdout)
            self.assertIn("<stable_id>TASK-001</stable_id>", agent_detail.stdout)
            self.assertIn("<goal>Create DB-backed workflow state</goal>", agent_detail.stdout)
            self.assertNotIn("<body>", agent_detail.stdout)
            self.assertNotIn("<created_at>", agent_detail.stdout)

            conflict = self.run_cli(db_path, "status", "--json", "--agent")
            self.assertEqual(conflict.returncode, 2)
            self.assertIn("not allowed with argument", conflict.stderr)

            item_conflict = self.run_cli(db_path, "item", "show", "--id", str(results[0]["id"]), "--json", "--agent")
            self.assertEqual(item_conflict.returncode, 2)
            self.assertIn("not allowed with argument", item_conflict.stderr)

            missing_agent_detail = self.run_cli(db_path, "item", "show", "--id", "999", "--agent")
            self.assertEqual(missing_agent_detail.returncode, 1)
            self.assertIn("<tapl_error>", missing_agent_detail.stdout)
            self.assertIn("<message>item not found: 999</message>", missing_agent_detail.stdout)

            search_conflict = self.run_cli(db_path, "search", "workflow", "--json", "--agent")
            self.assertEqual(search_conflict.returncode, 2)
            self.assertIn("not allowed with argument", search_conflict.stderr)

    def test_active_run_output_filters_legacy_columns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "tapl.db"
            config_path = Path(tmp) / "config.toml"
            config_path.write_text("[search]\nmode = \"bm25\"\n", encoding="utf-8")
            init = self.run_cli(db_path, "init", "--json")
            self.assertEqual(init.returncode, 0, init.stderr)

            plan = self.run_cli(
                db_path,
                "--config",
                str(config_path),
                "plan",
                "set",
                "--id",
                "PLAN-001",
                "--title",
                "Legacy run field filter",
                "--status",
                "Finalized",
                "--summary",
                "REQ-001: filter active run output",
                "--objective",
                "Keep status and validate output stable when old DB columns exist.",
                "--validation",
                "Run status and validate agent output checks.",
                "--json",
            )
            self.assertEqual(plan.returncode, 0, plan.stderr)

            legacy_column = "auto" + "_archive_policy"
            with sqlite3.connect(db_path) as conn:
                conn.execute(f"ALTER TABLE workflow_runs ADD COLUMN {legacy_column} TEXT DEFAULT 'auto'")
                conn.execute(f"UPDATE workflow_runs SET {legacy_column} = 'manual'")

            status_json = self.run_cli(db_path, "status", "--json")
            self.assertEqual(status_json.returncode, 0, status_json.stderr)
            self.assertNotIn(legacy_column, json.dumps(json.loads(status_json.stdout)))

            status_agent = self.run_cli(db_path, "status", "--agent")
            self.assertEqual(status_agent.returncode, 0, status_agent.stderr)
            self.assertNotIn(legacy_column, status_agent.stdout)

            validate_agent = self.run_cli(db_path, "--config", str(config_path), "validate", "--agent")
            self.assertEqual(validate_agent.returncode, 0, validate_agent.stderr)
            self.assertNotIn(legacy_column, validate_agent.stdout)

    def test_workflow_mode_migrates_defaults_and_promotes_lightweight_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "tapl.db"
            summarized = self.run_cli(
                db_path,
                "run",
                "summarize",
                "--summary",
                "Legacy workflow mode migration",
                "--json",
            )
            self.assertEqual(summarized.returncode, 0, summarized.stderr)

            with sqlite3.connect(db_path) as conn:
                conn.execute("ALTER TABLE workflow_runs DROP COLUMN workflow_mode")
                conn.execute("UPDATE meta SET value = '7' WHERE key = 'schema_version'")
                conn.commit()

            migrated = self.run_cli(db_path, "status", "--json")
            self.assertEqual(migrated.returncode, 0, migrated.stderr)
            migrated_payload = json.loads(migrated.stdout)
            self.assertEqual(migrated_payload["active_run"]["workflow_mode"], "planned")
            with sqlite3.connect(db_path) as conn:
                columns = {row[1] for row in conn.execute("PRAGMA table_info(workflow_runs)")}
                version = conn.execute(
                    "SELECT value FROM meta WHERE key = 'schema_version'"
                ).fetchone()[0]
            self.assertIn("workflow_mode", columns)
            self.assertEqual(version, str(tapl_db.SCHEMA_VERSION))

            lightweight = self.run_cli(
                db_path,
                "run",
                "summarize",
                "--stdin-json",
                "--json",
                input_text=json.dumps(
                    {"summary": "Answer one simple question", "workflow_mode": "lightweight"}
                ),
            )
            self.assertEqual(lightweight.returncode, 0, lightweight.stderr)
            self.assertEqual(
                json.loads(lightweight.stdout)["active_run"]["workflow_mode"],
                "lightweight",
            )
            validation = self.run_cli(db_path, "validate", "--json")
            self.assertEqual(validation.returncode, 0, validation.stderr)
            self.assertTrue(json.loads(validation.stdout)["plan_task_execute"]["ok"])
            next_action = self.run_cli(db_path, "next", "--json")
            self.assertEqual(
                json.loads(next_action.stdout)["recommendations"][0]["name"],
                "finish-run",
            )

            plan_payload = {
                "id": "PLAN-001",
                "title": "Promoted plan",
                "summary": "REQ-001: promote when complexity grows.",
                "objective": "Promote the lightweight run.",
                "requirements_trace": "REQ-001: applying a plan changes workflow mode.",
                "selected_approach": "Persist a detailed plan.",
                "affected_files": "Temporary database only.",
                "execution_order": "Apply the plan, then inspect status.",
                "risks": "Mode could remain lightweight.",
                "validation": "Status reports planned mode.",
                "status": "Finalized",
            }
            promoted = self.run_cli(
                db_path,
                "plan",
                "apply",
                "--stdin-json",
                "--json",
                input_text=json.dumps(plan_payload),
            )
            self.assertEqual(promoted.returncode, 0, promoted.stderr)
            status = self.status_json(db_path)
            self.assertEqual(status["active_run"]["workflow_mode"], "planned")  # type: ignore[index]

            invalid = self.run_cli(
                db_path,
                "run",
                "summarize",
                "--stdin-json",
                "--json",
                input_text=json.dumps({"summary": "Bad mode", "workflow_mode": "automatic"}),
            )
            self.assertEqual(invalid.returncode, 1)
            self.assertIn("invalid workflow_mode", json.loads(invalid.stdout)["error"])

    def test_agent_output_for_workflow_commands_keeps_json_available(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "tapl.db"
            init = self.run_cli(db_path, "init", "--agent")
            self.assertEqual(init.returncode, 0, init.stderr)
            self.assertIn("<tapl_output>", init.stdout)
            self.assertIn("<db>", init.stdout)
            self.assertNotIn("<schema>", init.stdout)

            doctor = self.run_cli(db_path, "doctor", "--agent")
            self.assertEqual(doctor.returncode, 0, doctor.stderr)
            self.assertIn("<tapl_output>", doctor.stdout)
            self.assertIn("<version>", doctor.stdout)
            self.assertNotIn("<config>", doctor.stdout)
            self.assertNotIn("<schema>", doctor.stdout)

            run_error = self.run_cli(db_path, "run", "set", "--agent")
            self.assertEqual(run_error.returncode, 1)
            self.assertIn("<tapl_output>", run_error.stdout)
            self.assertIn(
                "<error>provide --summary, --result, --workflow-mode, or a combination</error>",
                run_error.stdout,
            )

            plan = self.run_cli(
                db_path,
                "plan",
                "set",
                "--id",
                "PLAN-001",
                "--title",
                "Agent plan",
                "--status",
                "Finalized",
                "--summary",
                "REQ-001: agent output",
                "--objective",
                "Expose compact agent output",
                "--validation",
                "Run focused checks",
                "--agent",
            )
            self.assertEqual(plan.returncode, 0, plan.stderr)
            self.assertIn("<tapl_output>", plan.stdout)
            self.assertIn("<operation>plan_set</operation>", plan.stdout)
            self.assertIn("<kind>plan</kind>", plan.stdout)
            self.assertIn("<stable_id>PLAN-001</stable_id>", plan.stdout)
            self.assertIn("<field>objective</field>", plan.stdout)
            self.assertNotIn("Expose compact agent output", plan.stdout)
            self.assertNotIn("REQ-001: agent output", plan.stdout)
            self.assertNotIn("<objective>", plan.stdout)
            self.assertNotIn("<body>", plan.stdout)
            self.assertNotIn("<created_at>", plan.stdout)

            task = self.run_cli(
                db_path,
                "task",
                "set",
                "--id",
                "TASK-001",
                "--title",
                "Agent task",
                "--status",
                "In Progress",
                "--spec-id",
                "PLAN-001",
                "--goal",
                "Use agent output",
                "--action",
                "Run workflow commands with --agent",
                "--verification",
                "Agent output includes needed task fields",
                "--agent",
            )
            self.assertEqual(task.returncode, 0, task.stderr)
            self.assertIn("<operation>task_set</operation>", task.stdout)
            self.assertIn("<stable_id>TASK-001</stable_id>", task.stdout)
            self.assertIn("<status>In Progress</status>", task.stdout)
            self.assertIn("<field>goal</field>", task.stdout)
            self.assertNotIn("Use agent output", task.stdout)
            self.assertNotIn("Run workflow commands with --agent", task.stdout)
            self.assertNotIn("<goal>", task.stdout)
            self.assertIn("<code>execution_approval_missing</code>", task.stdout)
            self.assertNotIn("<config>", task.stdout)

            companion_task = self.run_cli(
                db_path,
                "task",
                "set",
                "--id",
                "TASK-002",
                "--title",
                "Agent verification task",
                "--status",
                "Completed",
                "--spec-id",
                "PLAN-001",
                "--verification",
                "Agent output includes needed task fields",
                "--result",
                "Verification recorded",
                "--agent",
            )
            self.assertEqual(companion_task.returncode, 0, companion_task.stderr)

            missing_approval = self.run_cli(db_path, "validate", "--agent")
            self.assertEqual(missing_approval.returncode, 1)
            self.assertIn("<tapl_output>", missing_approval.stdout)
            self.assertIn("<code>execution_approval_missing</code>", missing_approval.stdout)
            self.assertIn("tapl_approve_execution", missing_approval.stdout)
            self.assertNotIn("<config>", missing_approval.stdout)

            approval = self.run_cli(
                db_path,
                "approval",
                "set",
                "--decision",
                "approved",
                "--prompt",
                "Execute agent task",
                "--agent",
            )
            self.assertEqual(approval.returncode, 0, approval.stderr)
            self.assertIn("<operation>approval_set</operation>", approval.stdout)
            self.assertIn("<decision>approved</decision>", approval.stdout)
            self.assertNotIn("Execute agent task", approval.stdout)
            self.assertNotIn("<prompt>", approval.stdout)

            run = self.run_cli(db_path, "run", "set", "--summary", "Agent run", "--agent")
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertIn("<operation>run_set</operation>", run.stdout)
            self.assertIn("<field>request_summary</field>", run.stdout)
            self.assertNotIn("Agent run", run.stdout)
            self.assertNotIn("<request_summary>", run.stdout)

            finding = self.run_cli(
                db_path,
                "finding",
                "add",
                "--title",
                "Agent finding",
                "--finding",
                "Useful fact",
                "--impact",
                "Affects implementation",
                "--agent",
            )
            self.assertEqual(finding.returncode, 0, finding.stderr)
            self.assertIn("<operation>finding_add</operation>", finding.stdout)
            self.assertIn("<kind>finding</kind>", finding.stdout)
            self.assertIn("<field>finding</field>", finding.stdout)
            self.assertNotIn("Useful fact", finding.stdout)
            self.assertNotIn("Affects implementation", finding.stdout)
            self.assertNotIn("<impact>", finding.stdout)

            context = self.run_cli(db_path, "context", "--event", "UserPromptSubmit", "--agent")
            self.assertEqual(context.returncode, 0, context.stderr)
            self.assertIn("<tapl_context>", context.stdout)
            self.assertIn("tapl_get_next", context.stdout)
            self.assertIn("Do not run `taplctl --help`", context.stdout)
            self.assertNotIn("taplctl status --agent", context.stdout)
            self.assertNotIn("taplctl approval set --help", context.stdout)
            self.assertNotIn("taplctl approval set --decision approved", context.stdout)
            self.assertNotIn("<config>", context.stdout)

            validate = self.run_cli(db_path, "validate", "--agent")
            self.assertEqual(validate.returncode, 0, validate.stdout)
            self.assertIn("<tapl_output>", validate.stdout)
            self.assertIn("<incomplete_tasks>1</incomplete_tasks>", validate.stdout)
            self.assertNotIn("<config>", validate.stdout)

            json_status = self.run_cli(db_path, "status", "--json")
            self.assertEqual(json_status.returncode, 0, json_status.stderr)
            json_payload = json.loads(json_status.stdout)
            self.assertIn("config", json_payload)
            self.assertEqual(json_payload["active_run"]["request_summary"], "Agent run")

            conflict = self.run_cli(db_path, "plan", "set", "--id", "PLAN-001", "--json", "--agent")
            self.assertEqual(conflict.returncode, 2)
            self.assertIn("not allowed with argument", conflict.stderr)

            reindex = self.run_cli(db_path, "reindex", "--dry-run", "--agent")
            self.assertEqual(reindex.returncode, 0, reindex.stderr)
            self.assertIn("<tapl_output>", reindex.stdout)

            missing_workflow = Path(tmp) / "missing-workflow"
            imported = self.run_cli(db_path, "import-md", "--path", str(missing_workflow), "--dry-run", "--agent")
            self.assertEqual(imported.returncode, 0, imported.stderr)
            self.assertIn("<tapl_output>", imported.stdout)
            self.assertIn("<exists>false</exists>", imported.stdout)

            searchd_status = self.run_cli(
                db_path,
                "searchd",
                "status",
                "--socket",
                str(Path(tmp) / "missing.sock"),
                "--agent",
            )
            self.assertEqual(searchd_status.returncode, 0, searchd_status.stderr)
            self.assertIn("<tapl_output>", searchd_status.stdout)
            self.assertIn("<running>false</running>", searchd_status.stdout)
            self.assertNotIn("<config>", searchd_status.stdout)

            hook = self.run_cli(
                db_path,
                "hook-event",
                "--event",
                "UserPromptSubmit",
                "--mode",
                "observe",
                "--agent",
                input_text='{"prompt": "Agent hook"}',
            )
            self.assertEqual(hook.returncode, 0, hook.stderr)
            self.assertIn("<tapl_hook_event>", hook.stdout)
            self.assertIn("<event>UserPromptSubmit</event>", hook.stdout)

            codex_home = Path(tmp) / "codex-home"
            install_user = self.run_cli(
                db_path,
                "install",
                "user",
                "--codex-home",
                str(codex_home),
                "--dry-run",
                "--agent",
            )
            self.assertEqual(install_user.returncode, 0, install_user.stderr)
            self.assertIn("<tapl_output>", install_user.stdout)

            repo = Path(tmp) / "repo"
            repo.mkdir()
            install_repo = self.run_cli(
                db_path,
                "install",
                "repo",
                "--repo",
                str(repo),
                "--dry-run",
                "--agent",
            )
            self.assertEqual(install_repo.returncode, 0, install_repo.stderr)
            self.assertIn("<tapl_output>", install_repo.stdout)

            archive = self.run_cli(
                db_path,
                "archive",
                "create",
                "--slug",
                "agent-receipt",
                "--summary",
                "Archived agent receipt run",
                "--agent",
            )
            self.assertEqual(archive.returncode, 0, archive.stderr)
            self.assertIn("<operation>archive_create</operation>", archive.stdout)
            self.assertIn("<slug>agent-receipt</slug>", archive.stdout)
            self.assertIn("<field>summary</field>", archive.stdout)
            self.assertNotIn("Archived agent receipt run", archive.stdout)
            self.assertNotIn("<summary>", archive.stdout)

    def test_plan_set_uses_structured_fields_and_partial_updates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "tapl.db"
            created = self.run_cli(
                db_path,
                "plan",
                "set",
                "--id",
                "PLAN-001",
                "--title",
                "Structured plan",
                "--status",
                "Draft",
                "--summary",
                "REQ-001: structured plan records, rendered markdown, focused validation.",
                "--objective",
                "Store plan fields separately from rendered markdown.",
                "--requirements-trace",
                "REQ-001: plan fields use CLI arguments.",
                "--selected-approach",
                "Render `items.body` from the plan template.",
                "--affected-files",
                "tapl/taplctl/db.py and tapl/taplctl/cli.py",
                "--execution-order",
                "1. Add schema. 2. Update CLI. 3. Run tests.",
                "--risks",
                "Existing body-only plans need a migration fallback.",
                "--validation",
                "Run `uv run pytest`.",
                "--approval-needs",
                "Execution approval before durable edits.",
                "--json",
            )
            self.assertEqual(created.returncode, 0, created.stderr)

            status = self.run_cli(db_path, "status", "--json", "--full")
            self.assertEqual(status.returncode, 0, status.stderr)
            plan = json.loads(status.stdout)["plans"][0]
            self.assertEqual(plan["summary"], "REQ-001: structured plan records, rendered markdown, focused validation.")
            self.assertEqual(plan["objective"], "Store plan fields separately from rendered markdown.")
            self.assertEqual(plan["requirements_trace"], "REQ-001: plan fields use CLI arguments.")
            self.assertIn("### Objective\nStore plan fields separately from rendered markdown.", plan["body"])
            self.assertIn("### Requirements trace\nREQ-001: plan fields use CLI arguments.", plan["body"])
            self.assertIn("### Validation\nRun `uv run pytest`.", plan["body"])

            conn = sqlite3.connect(db_path)
            row = conn.execute(
                "SELECT plan_id, objective, validation FROM plans WHERE plan_id = 'PLAN-001'",
            ).fetchone()
            conn.close()
            self.assertEqual(row, ("PLAN-001", "Store plan fields separately from rendered markdown.", "Run `uv run pytest`."))

            updated = self.run_cli(
                db_path,
                "plan",
                "set",
                "--id",
                "PLAN-001",
                "--status",
                "Finalized",
                "--validation",
                "Run focused CLI and unit tests.",
                "--json",
            )
            self.assertEqual(updated.returncode, 0, updated.stderr)

            status = self.run_cli(db_path, "status", "--json", "--full")
            plan = json.loads(status.stdout)["plans"][0]
            self.assertEqual(plan["title"], "Structured plan")
            self.assertEqual(plan["status"], "Finalized")
            self.assertEqual(plan["objective"], "Store plan fields separately from rendered markdown.")
            self.assertEqual(plan["validation"], "Run focused CLI and unit tests.")
            self.assertIn("### Validation\nRun focused CLI and unit tests.", plan["body"])

    def test_plan_migration_backfills_existing_body_only_items(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "tapl.db"
            init = self.run_cli(db_path, "init", "--json")
            self.assertEqual(init.returncode, 0, init.stderr)

            conn = sqlite3.connect(db_path)
            now = "2026-06-22T00:00:00+00:00"
            run_id = "legacy-active-run"
            conn.execute(
                """
                INSERT INTO workflow_runs(id, slug, status, request_summary, created_at, updated_at)
                VALUES(?, 'active', 'active', 'Legacy plan migration', ?, ?)
                """,
                (run_id, now, now),
            )
            conn.execute(
                """
                INSERT INTO items(run_id, stable_id, kind, title, body, raw_text, status, created_at, updated_at)
                VALUES(?, 'PLAN-001', 'plan', 'Legacy body plan', 'Legacy body-only plan text', '', 'Draft', ?, ?)
                """,
                (run_id, now, now),
            )
            conn.commit()
            conn.close()

            status = self.run_cli(db_path, "status", "--json", "--full")
            self.assertEqual(status.returncode, 0, status.stderr)
            plan = json.loads(status.stdout)["plans"][0]
            self.assertEqual(plan["plan_id"], "PLAN-001")
            self.assertEqual(plan["notes"], "Legacy body-only plan text")

    def test_task_set_allows_partial_update_for_existing_task(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "tapl.db"
            created = self.run_cli(
                db_path,
                "task",
                "set",
                "--id",
                "TASK-001",
                "--title",
                "Implement partial updates",
                "--status",
                "In Progress",
                "--spec-id",
                "SPEC-001",
                "--goal",
                "Preserve unchanged fields",
                "--action",
                "Merge supplied task fields with stored values",
                "--verification",
                "Run focused tests",
                "--json",
            )
            self.assertEqual(created.returncode, 0, created.stderr)

            updated = self.run_cli(
                db_path,
                "task",
                "set",
                "--id",
                "TASK-001",
                "--status",
                "Completed",
                "--result",
                "Focused tests passed",
                "--json",
            )
            self.assertEqual(updated.returncode, 0, updated.stderr)

            status = self.run_cli(db_path, "status", "--json", "--full")
            self.assertEqual(status.returncode, 0, status.stderr)
            task = json.loads(status.stdout)["tasks"][0]
            self.assertEqual(task["title"], "Implement partial updates")
            self.assertEqual(task["status"], "Completed")
            self.assertEqual(task["spec_id"], "SPEC-001")
            self.assertEqual(task["goal"], "Preserve unchanged fields")
            self.assertEqual(task["action"], "Merge supplied task fields with stored values")
            self.assertEqual(task["verification"], "Run focused tests")
            self.assertEqual(task["result"], "Focused tests passed")

    def test_task_schema_migration_removes_legacy_subagent_column_without_data_loss(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "tapl.db"
            created = self.run_cli(
                db_path,
                "task",
                "set",
                "--id",
                "TASK-001",
                "--title",
                "Preserve task data",
                "--status",
                "Completed",
                "--spec-id",
                "PLAN-001",
                "--verification",
                "Migration smoke",
                "--result",
                "Done",
                "--json",
            )
            self.assertEqual(created.returncode, 0, created.stderr)

            with sqlite3.connect(db_path) as conn:
                conn.execute("ALTER TABLE tasks ADD COLUMN required_subagent TEXT NOT NULL DEFAULT ''")
                conn.execute("UPDATE tasks SET required_subagent = '@senior-worker'")
                conn.execute("UPDATE meta SET value = '4' WHERE key = 'schema_version'")

            status = self.run_cli(db_path, "status", "--json", "--full")
            self.assertEqual(status.returncode, 0, status.stderr)
            task = json.loads(status.stdout)["tasks"][0]
            self.assertEqual(task["stable_id"], "TASK-001")
            self.assertEqual(task["verification"], "Migration smoke")
            self.assertEqual(task["result"], "Done")
            self.assertNotIn("required_subagent", task)

            with sqlite3.connect(db_path) as conn:
                columns = {row[1] for row in conn.execute("PRAGMA table_info(tasks)")}
                schema_version = conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()[0]
            self.assertNotIn("required_subagent", columns)
            self.assertEqual(schema_version, str(tapl_db.SCHEMA_VERSION))

    def test_custom_fields_cli_preserves_types_merges_deletes_and_reaches_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "tapl.db"
            plan_payload = {
                "id": "PLAN-001",
                "title": "Custom field plan",
                "status": "Draft",
                "custom_fields": {
                    "Type": "feature",
                    "Count": 2,
                    "Enabled": False,
                    "Tags": ["history", 3, None],
                    "Choice": {"selected": "merge", "confirmed": True},
                    "Delete me": "obsolete",
                    "raw_text": "kept as custom metadata",
                },
            }
            created_plan = self.run_cli(
                db_path,
                "plan",
                "apply",
                "--stdin-json",
                "--agent",
                input_text=json.dumps(plan_payload),
            )
            self.assertEqual(created_plan.returncode, 0, created_plan.stderr)
            self.assertIn("<field>custom_fields</field>", created_plan.stdout)
            self.assertNotIn("obsolete", created_plan.stdout)

            updated_plan = self.run_cli(
                db_path,
                "plan",
                "apply",
                "--stdin-json",
                "--json",
                input_text=json.dumps(
                    {
                        "id": "PLAN-001",
                        "custom_fields": {
                            "Type": "enhancement",
                            "Delete me": None,
                            "User choices": ["merge", {"reason": "preserve history"}],
                        },
                    }
                ),
            )
            self.assertEqual(updated_plan.returncode, 0, updated_plan.stderr)

            task_payload = {
                "id": "TASK-001",
                "title": "Custom field task",
                "spec_id": "PLAN-001",
                "goal": "Store task metadata",
                "action": "Exercise lifecycle custom fields",
                "verification": "Inspect structured outputs",
                "custom_fields": {"Type": "implementation", "Score": 5},
            }
            created_task = self.run_cli(
                db_path,
                "task",
                "create",
                "--stdin-json",
                "--json",
                input_text=json.dumps(task_payload),
            )
            self.assertEqual(created_task.returncode, 0, created_task.stderr)

            started_task = self.run_cli(
                db_path,
                "task",
                "start",
                "TASK-001",
                "--stdin-json",
                "--json",
                input_text=json.dumps({"custom_fields": {"Score": None, "Phase": {"name": "execution"}}}),
            )
            self.assertEqual(started_task.returncode, 0, started_task.stderr)

            status = self.run_cli(db_path, "status", "--json")
            self.assertEqual(status.returncode, 0, status.stderr)
            payload = json.loads(status.stdout)
            plan = payload["plans"][0]
            self.assertEqual(
                plan["custom_fields"],
                {
                    "Choice": {"confirmed": True, "selected": "merge"},
                    "Count": 2,
                    "Enabled": False,
                    "Tags": ["history", 3, None],
                    "Type": "enhancement",
                    "User choices": ["merge", {"reason": "preserve history"}],
                    "raw_text": "kept as custom metadata",
                },
            )
            self.assertEqual(
                payload["tasks"][0]["custom_fields"],
                {"Phase": {"name": "execution"}, "Type": "implementation"},
            )

            agent_status = self.run_cli(db_path, "status", "--agent")
            self.assertEqual(agent_status.returncode, 0, agent_status.stderr)
            self.assertIn("<custom_fields>", agent_status.stdout)
            self.assertIn("<Type>enhancement</Type>", agent_status.stdout)
            self.assertIn("<User_choices>", agent_status.stdout)
            self.assertIn("<Phase>", agent_status.stdout)
            self.assertIn("<raw_text>kept as custom metadata</raw_text>", agent_status.stdout)

            item_id = plan["id"]
            item = self.run_cli(db_path, "item", "show", "--id", str(item_id), "--json")
            self.assertEqual(item.returncode, 0, item.stderr)
            self.assertEqual(json.loads(item.stdout)["item"]["custom_fields"], plan["custom_fields"])

            archived = self.run_cli(
                db_path,
                "archive",
                "create",
                "--slug",
                "custom-fields",
                "--summary",
                "Custom field archive",
                "--json",
            )
            self.assertEqual(archived.returncode, 0, archived.stderr)
            archive_id = json.loads(archived.stdout)["archive"]["id"]
            archive = self.run_cli(db_path, "archive", "show", "--id", archive_id, "--json")
            self.assertEqual(archive.returncode, 0, archive.stderr)
            archived_items = json.loads(archive.stdout)["items"]
            archived_plan = next(item for item in archived_items if item["kind"] == "plan")
            self.assertEqual(archived_plan["custom_fields"], plan["custom_fields"])

    def test_custom_fields_rejects_non_object_and_empty_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "tapl.db"
            for custom_fields in ([], None, {" ": "invalid"}):
                invalid = self.run_cli(
                    db_path,
                    "plan",
                    "apply",
                    "--stdin-json",
                    "--json",
                    input_text=json.dumps(
                        {"id": "PLAN-001", "title": "Invalid custom fields", "custom_fields": custom_fields}
                    ),
                )
                self.assertEqual(invalid.returncode, 1)
                self.assertIn("custom_fields", json.loads(invalid.stdout)["error"])

            invalid_flag = self.run_cli(
                db_path,
                "task",
                "set",
                "--id",
                "TASK-001",
                "--custom-fields",
                '["not", "an", "object"]',
            )
            self.assertEqual(invalid_flag.returncode, 2)
            self.assertIn("custom_fields must be a JSON object", invalid_flag.stderr)

    def test_custom_fields_schema_migration_backfills_empty_object(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "tapl.db"
            created = self.run_cli(
                db_path,
                "plan",
                "set",
                "--id",
                "PLAN-001",
                "--title",
                "Legacy plan",
                "--status",
                "Draft",
                "--json",
            )
            self.assertEqual(created.returncode, 0, created.stderr)

            with sqlite3.connect(db_path) as conn:
                conn.execute("ALTER TABLE items DROP COLUMN custom_fields_json")
                conn.execute("UPDATE meta SET value = '5' WHERE key = 'schema_version'")

            status = self.run_cli(db_path, "status", "--json", "--full")
            self.assertEqual(status.returncode, 0, status.stderr)
            payload = json.loads(status.stdout)
            self.assertEqual(payload["plans"][0]["custom_fields"], {})
            self.assertEqual(payload["schema"]["schema_version"], str(tapl_db.SCHEMA_VERSION))
            with sqlite3.connect(db_path) as conn:
                columns = {row[1] for row in conn.execute("PRAGMA table_info(items)")}
            self.assertIn("custom_fields_json", columns)

    def test_custom_fields_are_searchable_and_part_of_semantic_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "tapl.db"
            conn = tapl_db.connect(db_path)
            tapl_db.upsert_plan(
                conn,
                plan_id="PLAN-001",
                title="Searchable custom fields",
                status="Draft",
                custom_fields={"DecisionMode": "user-selected-merge", "Areas": ["backend", "history"]},
            )

            self.assertEqual(tapl_db.search_word(conn, "backend")[0]["stable_id"], "PLAN-001")
            self.assertEqual(tapl_db.search_bm25(conn, "DecisionMode")[0]["stable_id"], "PLAN-001")
            row = conn.execute(
                "SELECT stable_id, kind, title, body, raw_text, custom_fields_json FROM items WHERE stable_id = ?",
                ("PLAN-001",),
            ).fetchone()
            semantic_text = tapl_embeddings.item_text(row)
            self.assertIn("DecisionMode", semantic_text)
            self.assertIn("user-selected-merge", semantic_text)
            conn.close()

    def test_custom_fields_guidance_lives_in_mcp_instructions_not_cli_help_or_hook(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "tapl.db"
            plan_help = self.run_cli(db_path, "plan", "apply", "--help")
            task_help = self.run_cli(db_path, "task", "create", "--help")
            self.assertEqual(plan_help.returncode, 0, plan_help.stderr)
            self.assertEqual(task_help.returncode, 0, task_help.stderr)
            for output in (plan_help.stdout, task_help.stdout):
                self.assertIn("--custom-fields", output)
                self.assertIn("Manual CLI fallback", output)
                self.assertNotIn("proactively populate `custom_fields`", output)

            context = self.run_cli(db_path, "context", "--event", "UserPromptSubmit", "--json")
            self.assertEqual(context.returncode, 0, context.stderr)
            hook_guidance = "\n".join(json.loads(context.stdout)["workflow_guidance"])
            self.assertIn("MCP server instructions", hook_guidance)
            self.assertNotIn("proactively populate `custom_fields`", hook_guidance)

            server = tapl_mcp.create_server(workspace_root=ROOT)
            guidance = server.instructions
            self.assertIn("proactively populate `custom_fields`", guidance)
            self.assertIn("future search, review, handoff, or decision reconstruction", guidance)
            self.assertIn("even when AGENTS.md and the user do not explicitly request", guidance)
            self.assertIn("metadata shared by the run or multiple tasks", guidance)
            self.assertIn("on the plan instead of copying it to every task", guidance)
            self.assertIn("a task's `custom_fields` only with metadata unique to that task", guidance)
            self.assertIn("owned files or interfaces", guidance)
            self.assertIn("task was actually delegated to a subagent", guidance)
            self.assertIn("model and reasoning effort", guidance)
            self.assertIn("`서브 에이전트 모델`: `gpt-5.6-sol (xhigh)`", guidance)
            self.assertIn("`SubAgent Model`: `gpt-5.6-sol (xhigh)`", guidance)
            self.assertIn("omit this field when no subagent was used", guidance)
            self.assertIn("fact already represented on the source plan", guidance)
            self.assertIn("same key and value across sibling tasks", guidance)
            self.assertIn("task-specific values or context", guidance)
            self.assertIn("natural-language labels", guidance)
            self.assertIn("string values in the user's language", guidance)
            self.assertIn("avoid snake_case", guidance)
            self.assertIn("inspect the record's existing `custom_fields`", guidance)
            self.assertIn("synonymous label or duplicate value", guidance)
            self.assertIn("clearest, most specific label as the canonical key", guidance)
            self.assertIn("top-level nulls for the obsolete alias keys", guidance)
            self.assertIn("when the distinction is unclear, preserve them or ask", guidance)

    def test_mcp_server_instructions_are_compact_and_keep_policy_invariants(self) -> None:
        instructions = tapl_prompt.mcp_server_instructions(
            subagents=tapl_config.SubagentsConfig()
        )

        self.assertLess(len(instructions), 10_000)
        required_policy = (
            "Do not modify source, tests, docs, configs, migrations, generated files",
            "before execution approval",
            "TAPL run, plan, task, finding, approval, and archive records may be created or updated before execution approval",
            "Do not commit, push, rebase, reset, discard changes",
            "Never overwrite user changes",
            "current-state snapshots, not logs",
            "agent must select `lightweight` only for a direct, non-durable answer",
            "`tapl_apply_plan` promotes it to planned mode",
            "Planning must happen before implementation",
            "Mark it finalized only after explicit user confirmation",
            "Before finalizing the plan",
            'Fixed plan detail (`plan_detail = "very_detailed"`)',
            'Fixed planning approval (`planning_approval_level = "more"`)',
            'Fixed task granularity (`task_granularity = "very_granular"`)',
            "Execute planned tasks one at a time in task order",
            "exclusive owned_paths",
            "exact manifest execution_id",
            "recover or cancel the batch before retrying",
            "actual runtime model/reasoning effort",
            'Fixed execution approval (`require_execution_approval = true`)',
            "only active work is In Progress",
            "If scope or implementation changes materially",
            "search relevant prior TAPL history",
            "ignore unrelated matches",
            "During execution, search again",
            "decision-relevant findings with source and impact",
            "never store raw dumps, long candidate lists, or stale findings",
            "Archive the active run when no actionable tasks remain",
            "Record the final result with `tapl_finish_run` before archiving",
        )
        for policy in required_policy:
            self.assertIn(policy, instructions)

    def test_task_set_requires_title_and_status_for_new_task(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "tapl.db"
            missing = self.run_cli(
                db_path,
                "task",
                "set",
                "--id",
                "TASK-001",
                "--json",
            )
            self.assertEqual(missing.returncode, 1)
            payload = json.loads(missing.stdout)
            self.assertFalse(payload["ok"])
            self.assertEqual(payload["plan_task_execute"]["errors"][0]["code"], "task_create_missing_fields")
            guidance = payload["plan_task_execute"]["guidance"]
            self.assertIn("field_contract_source", guidance)
            self.assertIn("stable_ids", guidance)
            self.assertIn("task_required_fields", guidance)
            self.assertNotIn("workflow_order", guidance)
            self.assertNotIn("task_format", guidance)
            self.assertNotIn("record_format", guidance)
            self.assertIn("--title", payload["error"])
            self.assertIn("--status", payload["error"])

    def test_plan_and_task_ids_require_numeric_suffixes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "tapl.db"

            bad_plan = self.run_cli(
                db_path,
                "plan",
                "set",
                "--id",
                "SPEC-MEANINGS",
                "--title",
                "Bad plan id",
                "--json",
            )
            self.assertEqual(bad_plan.returncode, 1)
            bad_plan_payload = json.loads(bad_plan.stdout)
            self.assertEqual(bad_plan_payload["plan_task_execute"]["errors"][0]["code"], "invalid_plan_id")

            good_plan = self.run_cli(
                db_path,
                "plan",
                "set",
                "--id",
                "PLAN-001",
                "--title",
                "Good plan id",
                "--summary",
                "REQ-001: Use numeric stable ids. Validation: CLI rejects word suffixes.",
                "--json",
            )
            self.assertEqual(good_plan.returncode, 0, good_plan.stderr)

            bad_task = self.run_cli(
                db_path,
                "task",
                "set",
                "--id",
                "TASK-MEANINGS",
                "--title",
                "Bad task id",
                "--status",
                "Pending",
                "--spec-id",
                "PLAN-001",
                "--json",
            )
            self.assertEqual(bad_task.returncode, 1)
            bad_task_payload = json.loads(bad_task.stdout)
            self.assertEqual(bad_task_payload["plan_task_execute"]["errors"][0]["code"], "invalid_task_id")

            bad_spec = self.run_cli(
                db_path,
                "task",
                "set",
                "--id",
                "TASK-001",
                "--title",
                "Bad spec id",
                "--status",
                "Pending",
                "--spec-id",
                "SPEC-MEANINGS",
                "--json",
            )
            self.assertEqual(bad_spec.returncode, 1)
            bad_spec_payload = json.loads(bad_spec.stdout)
            self.assertEqual(bad_spec_payload["plan_task_execute"]["errors"][0]["code"], "invalid_task_spec_id")

    def test_load_model_suppresses_loading_weights_progress(self) -> None:
        from taplctl import embeddings

        class FakeSentenceTransformer:
            def __init__(self, model_name: str, **kwargs: object) -> None:
                self.model_name = model_name
                self.kwargs = kwargs
                sys.stderr.write("\rLoading weights: 100%|fake|\n")
                sys.stderr.write("model loaded\n")

        fake_module = types.ModuleType("sentence_transformers")
        fake_module.SentenceTransformer = FakeSentenceTransformer
        original_module = sys.modules.get("sentence_transformers")
        sys.modules["sentence_transformers"] = fake_module
        stderr = io.StringIO()
        try:
            with contextlib.redirect_stderr(stderr):
                model = embeddings.load_model(prefer_local=True)
        finally:
            if original_module is None:
                sys.modules.pop("sentence_transformers", None)
            else:
                sys.modules["sentence_transformers"] = original_module

        self.assertIsInstance(model, FakeSentenceTransformer)
        self.assertEqual(model.kwargs["local_files_only"], True)
        self.assertNotIn("Loading weights", stderr.getvalue())
        self.assertIn("model loaded", stderr.getvalue())

        fd_progress = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "import os\n"
                    "from taplctl.embeddings import suppress_model_load_progress\n"
                    "with suppress_model_load_progress():\n"
                    "    os.write(2, b'\\rLoading weights: 100%|fake|\\n')\n"
                    "print('done')\n"
                ),
            ],
            text=True,
            capture_output=True,
            check=False,
            env=self.tapl_env(),
        )
        self.assertEqual(fd_progress.returncode, 0, fd_progress.stderr)
        self.assertNotIn("Loading weights", fd_progress.stderr)
        self.assertEqual(fd_progress.stdout.strip(), "done")

    def test_config_defaults_when_file_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cfg = tapl_config.load(Path(tmp) / "missing.toml")
            self.assertFalse(cfg.exists)
            self.assertEqual(cfg.search.mode, "hybrid")
            self.assertEqual(cfg.search.max_results, 12)
            self.assertEqual(cfg.search.hybrid_semantic_ratio, 0.65)
            self.assertEqual(cfg.search.hybrid_bm25_ratio, 0.35)
            self.assertEqual(cfg.search.semantic_provider, "auto")
            self.assertEqual(cfg.search.searchd_model_idle_timeout_seconds, 1800)
            self.assertTrue(cfg.subagents.enabled)
            self.assertEqual(
                cfg.subagents.as_dict()["models"],
                {
                    "gpt-5.6-sol": ["xhigh", "max"],
                    "gpt-5.6-terra": ["high", "xhigh", "max"],
                    "gpt-5.6-luna": ["high", "xhigh"],
                },
            )
            self.assertEqual(cfg.as_dict()["subagents"], cfg.subagents.as_dict())
            self.assertNotIn("plan_task_execute", cfg.as_dict())
            self.assertFalse(hasattr(cfg, "plan_task_execute"))

    def test_config_loads_custom_and_disabled_subagent_settings_without_runtime_validation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "tapl.toml"
            config_path.write_text(
                """
[subagents]
enabled = true

[subagents.models]
"gpt-5.6-luna" = ["high", "xhigh"]
" future-runtime-model " = [" custom-effort "]
""".lstrip(),
                encoding="utf-8",
            )

            cfg = tapl_config.load(config_path)

            self.assertTrue(cfg.subagents.enabled)
            self.assertEqual(
                cfg.subagents.as_dict(),
                {
                    "enabled": True,
                    "models": {
                        "gpt-5.6-luna": ["high", "xhigh"],
                        "future-runtime-model": ["custom-effort"],
                    },
                },
            )

            config_path.write_text(
                """
[subagents]
enabled = false

[subagents.models]
""".lstrip(),
                encoding="utf-8",
            )

            disabled = tapl_config.load(config_path)

            self.assertFalse(disabled.subagents.enabled)
            self.assertEqual(disabled.subagents.models, ())
            self.assertEqual(disabled.as_dict()["subagents"], {"enabled": False, "models": {}})

            config_path.write_text(
                "[subagents]\nenabled = false\n",
                encoding="utf-8",
            )

            disabled_with_defaults = tapl_config.load(config_path)

            self.assertFalse(disabled_with_defaults.subagents.enabled)
            self.assertEqual(
                disabled_with_defaults.subagents.as_dict()["models"],
                {
                    "gpt-5.6-sol": ["xhigh", "max"],
                    "gpt-5.6-terra": ["high", "xhigh", "max"],
                    "gpt-5.6-luna": ["high", "xhigh"],
                },
            )

    def test_config_strictly_rejects_invalid_subagent_settings(self) -> None:
        cases = (
            (
                "subagents = true\n",
                "subagents must be a TOML table",
            ),
            (
                '[subagents]\nenabled = "true"\n',
                "subagents.enabled must be a boolean",
            ),
            (
                '[subagents]\nmodels = ["gpt-5.6-sol"]\n',
                "subagents.models must be a TOML table",
            ),
            (
                "[subagents]\nenabled = true\n[subagents.models]\n",
                "subagents.models must define at least one model when subagents.enabled is true",
            ),
            (
                '[subagents.models]\n"" = ["xhigh"]\n',
                "subagents.models model names must be non-empty strings",
            ),
            (
                '[subagents.models]\nfoo = ["high"]\n" foo" = ["xhigh"]\n',
                "subagents.models contains duplicate model name: foo",
            ),
            (
                '[subagents.models]\n"gpt-5.6-sol" = "xhigh"\n',
                "subagents.models.gpt-5.6-sol must be an array of reasoning effort strings",
            ),
            (
                '[subagents.models]\n"gpt-5.6-sol" = []\n',
                "subagents.models.gpt-5.6-sol must contain at least one reasoning effort",
            ),
            (
                '[subagents.models]\n"gpt-5.6-sol" = ["xhigh", "xhigh"]\n',
                "subagents.models.gpt-5.6-sol contains duplicate reasoning effort: xhigh",
            ),
            (
                '[subagents.models]\n"gpt-5.6-sol" = ["xhigh", 3]\n',
                "subagents.models.gpt-5.6-sol[1] must be a non-empty string",
            ),
            (
                '[subagents.models]\nfoo = [" "]\n',
                "subagents.models.foo[0] must be a non-empty string",
            ),
        )
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "tapl.toml"
            for content, expected_error in cases:
                with self.subTest(expected_error=expected_error):
                    config_path.write_text(content, encoding="utf-8")
                    with self.assertRaises(ValueError) as raised:
                        tapl_config.load(config_path)
                    self.assertEqual(str(raised.exception), expected_error)

            config_path.write_text(
                '[subagents]\nenabled = "true"\n',
                encoding="utf-8",
            )
            surfaced = self.run_cli(
                Path(tmp) / "tapl.db",
                "--config",
                str(config_path),
                "context",
                "--event",
                "UserPromptSubmit",
                "--json",
            )
            self.assertEqual(surfaced.returncode, 1, surfaced.stderr)
            self.assertEqual(
                json.loads(surfaced.stdout),
                {"ok": False, "error": "subagents.enabled must be a boolean"},
            )

    def test_approval_cli_records_status_and_list(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "tapl.db"
            self.run_cli(
                db_path,
                "hook-event",
                "--event",
                "UserPromptSubmit",
                "--mode",
                "observe",
                "--json",
                input_text='{"prompt": "Approve execution"}',
            )

            missing = self.run_cli(db_path, "approval", "status", "--json")
            self.assertEqual(missing.returncode, 0, missing.stderr)
            missing_payload = json.loads(missing.stdout)
            self.assertEqual(missing_payload["approval"]["state"], "missing")
            self.assertFalse(missing_payload["approval"]["approved"])

            recorded = self.run_cli(
                db_path,
                "approval",
                "set",
                "--decision",
                "approved",
                "--prompt",
                "Execute prepared TASK-001",
                "--json",
            )
            self.assertEqual(recorded.returncode, 0, recorded.stderr)
            recorded_payload = json.loads(recorded.stdout)
            self.assertEqual(recorded_payload["approval"]["decision"], "approved")
            self.assertEqual(recorded_payload["approval"]["source"], "explicit_user")

            prompted = self.run_cli(
                db_path,
                "approval",
                "set",
                "--decision",
                "approved",
                "--prompt",
                "Continue after plan confirmation",
                "--source",
                "request_user_input",
                "--json",
            )
            self.assertEqual(prompted.returncode, 0, prompted.stderr)
            prompted_payload = json.loads(prompted.stdout)
            self.assertEqual(prompted_payload["approval"]["source"], "request_user_input")

            status = self.run_cli(db_path, "approval", "status", "--json")
            status_payload = json.loads(status.stdout)
            self.assertEqual(status_payload["approval"]["state"], "approved")
            self.assertTrue(status_payload["approval"]["approved"])
            self.assertEqual(status_payload["approval"]["source"], "request_user_input")

            workflow_status = self.run_cli(db_path, "status", "--json")
            workflow_payload = json.loads(workflow_status.stdout)
            self.assertEqual(workflow_payload["approvals"]["execution"]["state"], "approved")
            self.assertEqual(workflow_payload["approvals"]["execution"]["source"], "request_user_input")

            listed = self.run_cli(db_path, "approval", "list", "--json")
            listed_payload = json.loads(listed.stdout)
            self.assertEqual(len(listed_payload["approvals"]), 2)
            self.assertEqual(listed_payload["approvals"][0]["prompt"], "Continue after plan confirmation")
            self.assertEqual(listed_payload["approvals"][0]["source"], "request_user_input")
            self.assertEqual(listed_payload["approvals"][1]["prompt"], "Execute prepared TASK-001")
            self.assertEqual(listed_payload["approvals"][1]["source"], "explicit_user")

    def test_config_loads_user_global_and_ignores_legacy_workflow_policy_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            repo = base / "repo"
            home = base / "home"
            repo.mkdir()
            user_config = home / ".tapl" / "config.toml"
            user_config.parent.mkdir(parents=True)
            user_config.write_text(
                """
[search]
mode = "bm25"

[plan-task-execute]
plan-detail = "minimal"
planning-approval-level = "more"
""",
                encoding="utf-8",
            )

            cfg = tapl_config.load(start=repo, home=home)
            self.assertTrue(cfg.exists)
            self.assertEqual(cfg.path, str(user_config))
            self.assertEqual(cfg.search.mode, "bm25")
            self.assertNotIn("plan_task_execute", cfg.as_dict())

    def test_config_prefers_repo_config_over_user_global(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            repo = base / "repo"
            home = base / "home"
            repo_config = repo / ".tapl" / "config.toml"
            user_config = home / ".tapl" / "config.toml"
            repo_config.parent.mkdir(parents=True)
            user_config.parent.mkdir(parents=True)
            repo_config.write_text('[search]\nmode = "word"\n', encoding="utf-8")
            user_config.write_text('[search]\nmode = "bm25"\n', encoding="utf-8")

            cfg = tapl_config.load(start=repo, home=home)
            self.assertTrue(cfg.exists)
            self.assertEqual(cfg.path, str(repo_config.resolve()))
            self.assertEqual(cfg.search.mode, "word")

    def test_config_search_mode_is_applied(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "tapl.db"
            config_path = Path(tmp) / "tapl.toml"
            config_path.write_text(
                """
[search]
mode = "word"
max_results = 2
hybrid_semantic_ratio = 0.25
semantic-provider = "daemon"
idle-timeout-seconds = 0

""",
                encoding="utf-8",
            )

            self.run_cli(db_path, "init", "--json")
            self.run_cli(
                db_path,
                "task",
                "set",
                "--id",
                "TASK-001",
                "--title",
                "Word mode search",
                "--status",
                "Completed",
                "--goal",
                "Use substring lookup",
            )

            status = self.run_cli(db_path, "--config", str(config_path), "status", "--json")
            status_payload = json.loads(status.stdout)
            self.assertEqual(status_payload["config"]["search"]["mode"], "word")
            self.assertEqual(status_payload["config"]["search"]["semantic_provider"], "daemon")
            self.assertEqual(status_payload["config"]["search"]["searchd_model_idle_timeout_seconds"], 0)
            self.assertNotIn("plan_task_execute", status_payload["config"])

            search = self.run_cli(db_path, "--config", str(config_path), "search", "substring", "--json")
            search_payload = json.loads(search.stdout)
            self.assertEqual(search_payload["mode"], "word")
            self.assertEqual(search_payload["search_config"]["max_results"], 2)
            self.assertEqual(search_payload["results"][0]["search_source"], "word")

    def test_search_limit_uses_default_config_and_cli_override(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            db_path = base / "tapl.db"
            config_path = base / "tapl.toml"
            config_path.write_text(
                """
[search]
mode = "word"
max_results = 3
""",
                encoding="utf-8",
            )

            self.run_cli(db_path, "init", "--json")
            for index in range(9):
                created = self.run_cli(
                    db_path,
                    "task",
                    "set",
                    "--id",
                    f"TASK-{index + 1:03d}",
                    "--title",
                    f"Needle task {index}",
                    "--status",
                    "Completed",
                    "--goal",
                    "shared needle search target",
                    "--json",
                )
                self.assertEqual(created.returncode, 0, created.stderr)

            default_config = self.run_cli(
                db_path,
                "--config",
                str(base / "missing.toml"),
                "search",
                "needle",
                "--json",
            )
            default_payload = json.loads(default_config.stdout)
            self.assertEqual(default_payload["limit"], 12)
            self.assertEqual(len(default_payload["results"]), 9)

            configured = self.run_cli(db_path, "--config", str(config_path), "search", "needle", "--json")
            configured_payload = json.loads(configured.stdout)
            self.assertEqual(configured_payload["limit"], 3)
            self.assertEqual(len(configured_payload["results"]), 3)

            overridden = self.run_cli(
                db_path,
                "--config",
                str(config_path),
                "search",
                "needle",
                "--limit",
                "5",
                "--json",
            )
            overridden_payload = json.loads(overridden.stdout)
            self.assertEqual(overridden_payload["limit"], 5)
            self.assertEqual(len(overridden_payload["results"]), 5)

    def test_config_rejects_non_positive_search_max_results(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "tapl.toml"
            config_path.write_text("[search]\nmax_results = 0\n", encoding="utf-8")

            with self.assertRaises(ValueError):
                tapl_config.load(config_path)

    def test_config_ignores_legacy_workflow_policy_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "tapl.toml"
            config_path.write_text(
                "[plan-task-execute]\nplanning_approval_level = \"always\"\n",
                encoding="utf-8",
            )

            cfg = tapl_config.load(config_path)
            self.assertNotIn("plan_task_execute", cfg.as_dict())

    def test_execution_approval_is_required_without_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "tapl.db"
            self.run_cli(
                db_path,
                "plan",
                "set",
                "--id",
                "SPEC-001",
                "--title",
                "Needs execution approval",
                "--summary",
                "REQ-001: Validate execution approval before durable edits. Validation: taplctl validate.",
            )
            self.run_cli(
                db_path,
                "task",
                "set",
                "--id",
                "TASK-001",
                "--title",
                "Executable task",
                "--status",
                "In Progress",
                "--spec-id",
                "SPEC-001",
                "--goal",
                "Execute approved work",
                "--action",
                "Edit files after approval",
                "--verification",
                "taplctl validate",
            )
            self.run_cli(
                db_path,
                "task",
                "set",
                "--id",
                "TASK-002",
                "--title",
                "Independent verification",
                "--status",
                "Completed",
                "--spec-id",
                "SPEC-001",
                "--verification",
                "Check execution approval validation",
                "--result",
                "Companion task completed",
            )

            missing = self.run_cli(db_path, "validate", "--json")
            self.assertEqual(missing.returncode, 1)
            missing_payload = json.loads(missing.stdout)
            missing_codes = {
                issue["code"] for issue in missing_payload["plan_task_execute"]["errors"]
            }
            self.assertIn("execution_approval_missing", missing_codes)

            approved = self.run_cli(
                db_path,
                "approval",
                "set",
                "--decision",
                "approved",
                "--prompt",
                "Execute TASK-001",
                "--json",
            )
            self.assertEqual(approved.returncode, 0, approved.stderr)

            validated = self.run_cli(db_path, "validate", "--json")
            self.assertEqual(validated.returncode, 0, validated.stdout)

    def test_config_rejects_unknown_search_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "tapl.toml"
            config_path.write_text('[search]\nmode = "unknown"\n', encoding="utf-8")
            with self.assertRaises(ValueError):
                tapl_config.load(config_path)

    def test_config_rejects_unknown_searchd_settings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "tapl.toml"
            config_path.write_text('[search]\nsemantic_provider = "remote"\n', encoding="utf-8")
            with self.assertRaises(ValueError):
                tapl_config.load(config_path)

            config_path.write_text("[search]\nsearchd_model_idle_timeout_seconds = -1\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                tapl_config.load(config_path)

    def test_config_ignores_removed_searchd_settings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "tapl.toml"
            config_path.write_text(
                """
[search]
searchd_missing = "explode"
searchd_socket_path = "~/ignored.sock"
searchd_connect_timeout_ms = 1
searchd_start_timeout_ms = 1
""",
                encoding="utf-8",
            )

            cfg = tapl_config.load(config_path)
            self.assertEqual(cfg.search.semantic_provider, "auto")
            self.assertFalse(hasattr(cfg.search, "searchd_missing"))
            self.assertFalse(hasattr(cfg.search, "searchd_socket_path"))
            self.assertFalse(hasattr(cfg.search, "searchd_connect_timeout_ms"))
            self.assertFalse(hasattr(cfg.search, "searchd_start_timeout_ms"))

    def test_query_embedding_blob_provider_fallback(self) -> None:
        from taplctl import embeddings

        original_embed = embeddings.searchd.embed_query
        original_local = embeddings.local_query_embedding_blob
        try:
            def fake_embed(query: str, settings: tapl_config.SearchConfig) -> bytes:
                raise embeddings.searchd.SearchdUnavailable("down")

            embeddings.searchd.embed_query = fake_embed
            embeddings.local_query_embedding_blob = lambda query: b"local"

            auto = tapl_config.SearchConfig(semantic_provider="auto")
            self.assertEqual(embeddings.query_embedding_blob("query", auto), b"local")

            daemon = tapl_config.SearchConfig(semantic_provider="daemon")
            self.assertEqual(embeddings.query_embedding_blob("query", daemon), b"local")

            def fake_error(query: str, settings: tapl_config.SearchConfig) -> bytes:
                raise embeddings.searchd.SearchdError("bad response")

            embeddings.searchd.embed_query = fake_error
            self.assertEqual(embeddings.query_embedding_blob("query", auto), b"local")
            self.assertIsNone(embeddings.query_embedding_blob("query", daemon))
        finally:
            embeddings.searchd.embed_query = original_embed
            embeddings.local_query_embedding_blob = original_local

    def test_searchd_handle_request_embed_and_ping(self) -> None:
        from taplctl import searchd

        class FakeModelState:
            model_loaded = False
            model_idle_timeout_seconds = 30

            def unload_if_idle(self) -> bool:
                return False

            def status_payload(self, *, started_at: float) -> dict[str, object]:
                return {
                    "ok": True,
                    "pid": 1,
                    "model": "fake",
                    "dimension": 384,
                    "uptime_seconds": 0.0,
                    "model_loaded": self.model_loaded,
                    "model_idle_timeout_seconds": self.model_idle_timeout_seconds,
                }

            def embed(self, text: str) -> dict[str, object]:
                self.text = text
                self.model_loaded = True
                return {"dimension": 3, "embedding_b64": "YWJj"}

        model_state = FakeModelState()

        ping, stop = searchd.handle_request(
            {"op": "ping"},
            model_state=model_state,
            started_at=0.0,
        )
        self.assertTrue(ping["ok"])
        self.assertFalse(stop)
        self.assertFalse(ping["model_loaded"])
        self.assertEqual(ping["model_idle_timeout_seconds"], 30)

        embed, stop = searchd.handle_request(
            {"op": "embed", "text": "hello"},
            model_state=model_state,
            started_at=0.0,
        )
        self.assertTrue(embed["ok"])
        self.assertFalse(stop)
        self.assertEqual(embed["dimension"], 3)
        self.assertEqual(embed["embedding_b64"], "YWJj")
        self.assertTrue(embed["model_loaded"])

    def test_searchd_embed_query_uses_embed_timeout(self) -> None:
        from taplctl import searchd

        captured: dict[str, object] = {}
        original_request = searchd.request
        try:
            def fake_request(
                socket_path: Path,
                payload: dict[str, object],
                *,
                timeout_ms: int,
            ) -> dict[str, object]:
                captured["payload"] = payload
                captured["timeout_ms"] = timeout_ms
                return {"ok": True, "dimension": 384, "embedding_b64": "YWJj"}

            searchd.request = fake_request

            embedded = searchd.embed_query("hello", tapl_config.SearchConfig())

            self.assertEqual(embedded, b"abc")
            self.assertEqual(captured["payload"]["op"], "embed")
            self.assertEqual(captured["timeout_ms"], searchd.DEFAULT_EMBED_TIMEOUT_MS)
        finally:
            searchd.request = original_request

    def test_searchd_send_response_ignores_disconnected_clients(self) -> None:
        from taplctl import searchd

        class RecordingConn:
            sent = b""

            def sendall(self, data: bytes) -> None:
                self.sent = data

        class ClosedConn:
            def sendall(self, data: bytes) -> None:
                raise BrokenPipeError("closed")

        conn = RecordingConn()

        self.assertTrue(searchd.send_response(conn, {"ok": True}))
        self.assertIn(b'"ok":true', conn.sent)
        self.assertFalse(searchd.send_response(ClosedConn(), {"ok": True}))

    def test_searchd_model_state_lazy_loads_and_unloads_model(self) -> None:
        from taplctl import searchd

        current_time = 0.0
        loaded = 0

        class FakeArray:
            shape = (3,)

            def tobytes(self) -> bytes:
                return b"abc"

        class FakeNumpy:
            float32 = object()

            def asarray(self, vector: object, dtype: object) -> FakeArray:
                return FakeArray()

        class FakeModel:
            def get_sentence_embedding_dimension(self) -> int:
                return 3

            def encode(self, texts: list[str], *, normalize_embeddings: bool) -> list[list[float]]:
                self.texts = texts
                self.normalize_embeddings = normalize_embeddings
                return [[1.0, 2.0, 3.0]]

        def now() -> float:
            return current_time

        def load_model() -> FakeModel:
            nonlocal loaded
            loaded += 1
            return FakeModel()

        state = searchd.ModelState(
            model_idle_timeout_seconds=10,
            now=now,
            model_loader=load_model,
            numpy_loader=FakeNumpy,
        )

        self.assertFalse(state.status_payload(started_at=0.0)["model_loaded"])
        self.assertEqual(loaded, 0)

        first = state.embed("hello")
        self.assertEqual(first["dimension"], 3)
        self.assertEqual(loaded, 1)
        self.assertTrue(state.model_loaded)

        current_time = 9.0
        self.assertFalse(state.unload_if_idle())
        self.assertTrue(state.model_loaded)

        current_time = 10.0
        self.assertTrue(state.unload_if_idle())
        self.assertFalse(state.model_loaded)

    def test_searchd_status_reports_missing_daemon(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "tapl.db"
            status = self.run_cli(
                db_path,
                "searchd",
                "status",
                "--socket",
                str(Path(tmp) / "missing.sock"),
                "--json",
            )
            self.assertEqual(status.returncode, 0, status.stderr)
            payload = json.loads(status.stdout)
            self.assertFalse(payload["ok"])
            self.assertFalse(payload["running"])
            self.assertIn("missing.sock", payload["socket_path"])

    def test_removed_subagent_task_option_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "tapl.db"
            result = self.run_cli(
                db_path,
                "task",
                "set",
                "--id",
                "TASK-001",
                "--required-subagent",
                "@senior-worker",
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("unrecognized arguments: --required-subagent", result.stderr)

    def test_legacy_workflow_policy_config_keys_are_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "tapl.db"
            config_path = Path(tmp) / "tapl.toml"
            config_path.write_text(
                "[plan-task-execute]\nuse_level_subagent = true\nlevel_subagent_aggressiveness = \"force\"\nplan_detail = \"minimal\"\nplanning_approval_level = \"less\"\ntask_granularity = \"minimal\"\nrequire_execution_approval = false\n",
                encoding="utf-8",
            )
            task = self.run_cli(
                db_path,
                "--config",
                str(config_path),
                "task",
                "set",
                "--id",
                "TASK-001",
                "--title",
                "Direct task",
                "--status",
                "In Progress",
                "--json",
            )
            self.assertEqual(task.returncode, 0, task.stderr)
            payload = json.loads(task.stdout)
            issue_codes = {issue["code"] for issue in payload["plan_task_execute"]["issues"]}
            self.assertNotIn("missing_required_subagent", issue_codes)

    def test_validate_warns_for_sparse_plan_and_task_content(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "tapl.db"
            self.run_cli(
                db_path,
                "plan",
                "set",
                "--id",
                "SPEC-001",
                "--title",
                "Sparse plan",
                "--summary",
                "Implement the requested behavior by updating the relevant files and checking the result carefully.",
            )
            self.run_cli(
                db_path,
                "task",
                "set",
                "--id",
                "TASK-001",
                "--title",
                "Sparse task",
                "--status",
                "In Progress",
            )
            self.run_cli(
                db_path,
                "task",
                "set",
                "--id",
                "TASK-002",
                "--title",
                "Sparse verification companion",
                "--status",
                "Completed",
                "--spec-id",
                "SPEC-001",
                "--verification",
                "Companion task satisfies strict granularity.",
                "--result",
                "Verification recorded.",
            )
            self.run_cli(
                db_path,
                "approval",
                "set",
                "--decision",
                "approved",
                "--prompt",
                "Execute sparse task validation test",
            )

            validated = self.run_cli(db_path, "validate", "--json")
            self.assertEqual(validated.returncode, 0, validated.stderr)
            payload = json.loads(validated.stdout)
            codes = {item["code"] for item in payload["plan_task_execute"]["warnings"]}
            self.assertIn("plan_content_missing_guidance", codes)
            self.assertIn("task_content_missing_fields", codes)
            self.assertNotIn("guidance", payload["plan_task_execute"])

            context = self.run_cli(db_path, "context", "--event", "UserPromptSubmit", "--json")
            self.assertEqual(context.returncode, 0, context.stderr)
            context_payload = json.loads(context.stdout)
            validation_text = "\n".join(context_payload["validation_issues"])
            next_action_text = "\n".join(context_payload["next_actions"])
            self.assertIn("Plan content is missing", validation_text)
            self.assertIn("TASK-001 is missing task field", validation_text)
            self.assertNotIn("Plan content is missing", next_action_text)
            self.assertNotIn("TASK-001 is missing task field", next_action_text)

    def test_validate_warns_for_non_sequential_task_execution(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "tapl.db"
            self.run_cli(
                db_path,
                "plan",
                "set",
                "--id",
                "SPEC-001",
                "--title",
                "Sequential execution plan",
                "--summary",
                "REQ-001: execute tasks one at a time in order; Validation: validate task sequence warnings.",
            )
            for task_id in ("TASK-001", "TASK-002"):
                self.run_cli(
                    db_path,
                    "task",
                    "set",
                    "--id",
                    task_id,
                    "--title",
                    f"{task_id} implementation",
                    "--status",
                    "In Progress",
                    "--spec-id",
                    "SPEC-001",
                    "--goal",
                    f"Complete {task_id}",
                    "--action",
                    f"Run {task_id}",
                    "--verification",
                    f"Check {task_id}",
                )
            self.run_cli(
                db_path,
                "approval",
                "set",
                "--decision",
                "approved",
                "--prompt",
                "Execute sequential task warning test",
            )

            multiple = self.run_cli(db_path, "validate", "--json")
            self.assertEqual(multiple.returncode, 0, multiple.stderr)
            multiple_payload = json.loads(multiple.stdout)
            multiple_codes = {item["code"] for item in multiple_payload["plan_task_execute"]["warnings"]}
            self.assertIn("multiple_tasks_in_progress", multiple_codes)

            self.run_cli(
                db_path,
                "task",
                "set",
                "--id",
                "TASK-001",
                "--title",
                "TASK-001 implementation",
                "--status",
                "Pending",
                "--spec-id",
                "SPEC-001",
                "--goal",
                "Complete TASK-001",
                "--action",
                "Run TASK-001",
                "--verification",
                "Check TASK-001",
            )

            out_of_order = self.run_cli(db_path, "validate", "--json")
            self.assertEqual(out_of_order.returncode, 0, out_of_order.stderr)
            out_of_order_payload = json.loads(out_of_order.stdout)
            warnings = out_of_order_payload["plan_task_execute"]["warnings"]
            out_of_order_codes = {item["code"] for item in warnings}
            self.assertIn("task_started_out_of_order", out_of_order_codes)
            self.assertIn(
                "TASK-002 is In Progress while earlier task(s) remain incomplete: TASK-001.",
                "\n".join(item["message"] for item in warnings),
            )

    def test_context_command_reports_lifecycle_packet(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "tapl.db"
            self.run_cli(db_path, "init", "--json")

            context = self.run_cli(db_path, "context", "--event", "SessionStart", "--json")
            self.assertEqual(context.returncode, 0, context.stderr)
            payload = json.loads(context.stdout)
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["event"], "SessionStart")
            self.assertEqual(payload["instructions"], [])
            self.assertEqual(payload["validation_issues"], [])
            session_guidance = "\n".join(payload["workflow_guidance"])
            self.assertIn("# TAPL MCP", session_guidance)
            self.assertIn("installed `tapl_*` MCP tools", session_guidance)
            self.assertIn("SessionStart is bootstrap only", session_guidance)
            self.assertNotIn("taplctl --help", session_guidance)
            self.assertEqual(payload["next_actions"], [])

            status = self.run_cli(db_path, "status", "--json")
            self.assertEqual(status.returncode, 0, status.stderr)
            status_payload = json.loads(status.stdout)
            self.assertNotIn("guidance", status_payload["plan_task_execute"])

            manual_context = self.run_cli(db_path, "context", "--json")
            self.assertEqual(manual_context.returncode, 0, manual_context.stderr)
            manual_payload = json.loads(manual_context.stdout)
            self.assertEqual(manual_payload["event"], "Manual")
            self.assertEqual(
                manual_payload["workflow_guidance"],
                [tapl_prompt.user_prompt_submit_guidance()],
            )
            manual_guidance = "\n".join(manual_payload["workflow_guidance"])
            self.assertIn("# TAPL MCP", manual_guidance)
            self.assertIn("Call `tapl_get_next`", manual_guidance)
            self.assertIn("Do not run `taplctl --help`", manual_guidance)
            self.assertNotIn("## Role Boundaries", manual_guidance)

            prompt_context = self.run_cli(db_path, "context", "--event", "UserPromptSubmit", "--json")
            prompt_payload = json.loads(prompt_context.stdout)
            prompt_instructions = "\n".join(prompt_payload["instructions"])
            self.assertEqual(prompt_payload["instructions"], [])
            self.assertEqual(prompt_payload["validation_issues"], [])
            self.assertEqual(
                prompt_payload["workflow_guidance"],
                [tapl_prompt.user_prompt_submit_guidance()],
            )
            prompt_guidance = "\n".join(prompt_payload["workflow_guidance"])
            self.assertIn("MCP server instructions", prompt_guidance)
            self.assertIn("Call `tapl_get_next`", prompt_guidance)
            self.assertIn("Do not run `taplctl --help`", prompt_guidance)
            self.assertNotIn("Planning must happen before implementation", prompt_guidance)
            server_guidance = tapl_mcp.create_server(workspace_root=ROOT).instructions
            self.assertIn("Planning must happen before implementation", server_guidance)
            self.assertIn("## Role Boundaries", server_guidance)
            self.assertIn("## Planning", server_guidance)
            self.assertIn("## Tasks And Execution", server_guidance)
            self.assertIn("## Records And History", server_guidance)
            self.assertIn("## Completion Report", server_guidance)
            self.assertIn("Before finalizing the plan", server_guidance)
            self.assertIn('Fixed plan detail (`plan_detail = "very_detailed"`)', server_guidance)
            self.assertIn('Fixed planning approval (`planning_approval_level = "more"`)', server_guidance)
            self.assertIn('Fixed task granularity (`task_granularity = "very_granular"`)', server_guidance)
            self.assertIn("Fixed execution approval (`require_execution_approval = true`)", server_guidance)
            self.assertIn("`tapl_search_history`", server_guidance)
            self.assertIn("`tapl_get_item`", server_guidance)
            self.assertIn("ignore unrelated matches", server_guidance)
            self.assertIn("During execution, search again", server_guidance)
            self.assertIn("Execute planned tasks one at a time in task order", server_guidance)
            self.assertIn("request_user_input", server_guidance)
            self.assertIn("only active work is In Progress", server_guidance)
            self.assertNotIn("quote every argument", prompt_instructions)
            self.assertIn("Create an active workflow run", "\n".join(prompt_payload["next_actions"]))

            def next_actions_after_plan(request_summary: str) -> str:
                stage_db_path = Path(tmp) / f"{abs(hash(request_summary))}.db"
                prompt_payload_text = json.dumps({"prompt": request_summary}, ensure_ascii=False)
                self.run_cli(
                    stage_db_path,
                    "hook-event",
                    "--event",
                    "UserPromptSubmit",
                    "--mode",
                    "observe",
                    "--json",
                    input_text=prompt_payload_text,
                )
                self.run_cli(stage_db_path, "run", "set", "--summary", request_summary, "--json")
                plan = self.run_cli(
                    stage_db_path,
                    "plan",
                    "set",
                    "--id",
                    "PLAN-001",
                    "--title",
                    "Stage policy plan",
                    "--status",
                    "Finalized",
                    "--summary",
                    "REQ-001: stage policy.",
                    "--objective",
                    "Record stage policy.",
                    "--requirements-trace",
                    "REQ-001: stage policy.",
                    "--selected-approach",
                    "Use context next_actions.",
                    "--affected-files",
                    "context.py",
                    "--execution-order",
                    "Plan then choose next stage.",
                    "--risks",
                    "Prompt intent is heuristic.",
                    "--validation",
                    "Inspect next_actions.",
                    "--json",
                )
                self.assertEqual(plan.returncode, 0, plan.stderr)
                context = self.run_cli(stage_db_path, "context", "--event", "UserPromptSubmit", "--json")
                self.assertEqual(context.returncode, 0, context.stderr)
                return "\n".join(json.loads(context.stdout)["next_actions"])

            plan_only_actions = next_actions_after_plan("계획만 진행해줘")
            plan_then_ask_actions = next_actions_after_plan("계획해줘")
            explicit_execute_actions = next_actions_after_plan("계획하고 구현까지 해줘")
            self.assertEqual(plan_only_actions, plan_then_ask_actions)
            self.assertEqual(plan_then_ask_actions, explicit_execute_actions)
            self.assertIn("agent must judge the user's requested scope directly", plan_only_actions)
            self.assertIn("If the user limited work to planning/reporting", plan_only_actions)
            self.assertIn("If planning was requested without execution", plan_only_actions)
            self.assertIn("If execution, edits, testing, or verification were explicitly requested", plan_only_actions)
            self.assertIn("source `explicit_user`", plan_only_actions)
            self.assertNotIn("Plan-only request detected", plan_only_actions)

            legacy_planning_config = Path(tmp) / "legacy-planning.toml"
            legacy_planning_config.write_text(
                "[plan-task-execute]\nplanning-approval-level = \"less\"\n",
                encoding="utf-8",
            )
            legacy_planning_context = self.run_cli(
                db_path,
                "--config",
                str(legacy_planning_config),
                "context",
                "--event",
                "UserPromptSubmit",
                "--json",
            )
            legacy_planning_payload = json.loads(legacy_planning_context.stdout)
            legacy_planning_guidance = "\n".join(legacy_planning_payload["workflow_guidance"])
            self.assertEqual(legacy_planning_guidance, prompt_guidance)
            self.assertNotIn("only for blocking or high-risk", legacy_planning_guidance)

            self.run_cli(
                db_path,
                "task",
                "set",
                "--id",
                "TASK-001",
                "--title",
                "Context task",
                "--status",
                "In Progress",
            )
            active_context = self.run_cli(db_path, "context", "--event", "SessionStart", "--json")
            active_payload = json.loads(active_context.stdout)
            self.assertEqual(len(active_payload["next_actions"]), 1)
            self.assertIn("resume or update the incomplete task state", active_payload["next_actions"][0])

            active_prompt_context = self.run_cli(db_path, "context", "--event", "UserPromptSubmit", "--json")
            active_prompt_payload = json.loads(active_prompt_context.stdout)
            active_actions = active_prompt_payload["next_actions"]
            self.assertIn("Create or update plan state", "\n".join(active_prompt_payload["next_actions"]))
            self.assertIn("before task design", "\n".join(active_prompt_payload["next_actions"]))
            self.assertIn("get user approval", "\n".join(active_prompt_payload["next_actions"]))
            self.assertIn("finish existing work first", "\n".join(active_prompt_payload["next_actions"]))
            self.assertIn("defer the existing run", "\n".join(active_prompt_payload["next_actions"]))
            self.assertIn("merge the work into one plan", "\n".join(active_prompt_payload["next_actions"]))
            self.assertIn("Continue only TASK-001", "\n".join(active_prompt_payload["next_actions"]))
            approval_index = next(index for index, action in enumerate(active_actions) if "tapl_approve_execution" in action)
            continue_index = next(index for index, action in enumerate(active_actions) if "Continue only TASK-001" in action)
            self.assertLess(approval_index, continue_index)

            text = self.run_cli(db_path, "context", "--event", "SessionStart")
            self.assertEqual(text.returncode, 0, text.stderr)
            self.assertIn("tapl context:", text.stdout)
            self.assertIn("# TAPL MCP", text.stdout)
            self.assertIn("installed `tapl_*` MCP tools", text.stdout)
            self.assertIn("SessionStart is bootstrap only", text.stdout)
            self.assertNotIn("taplctl --help", text.stdout)

            stop_context = self.run_cli(db_path, "context", "--event", "Stop", "--json")
            stop_payload = json.loads(stop_context.stdout)
            stop_instructions = "\n".join(stop_payload["instructions"])
            self.assertEqual(stop_payload["instructions"], [])
            self.assertIn("record the result with `tapl_finish_run`", "\n".join(stop_payload["workflow_guidance"]))
            self.assertIn("`tapl_finish_archive`", "\n".join(stop_payload["workflow_guidance"]))
            self.assertNotIn("At the start of every non-trivial user request", "\n".join(stop_payload["workflow_guidance"]))
            self.assertNotIn("Completion reports should", stop_instructions)
            self.assertNotIn("Archive summaries should", stop_instructions)

            prompt_text = self.run_cli(db_path, "context", "--event", "UserPromptSubmit")
            self.assertEqual(prompt_text.returncode, 0, prompt_text.stderr)
            self.assertIn("tapl context:", prompt_text.stdout)
            self.assertIn("# TAPL MCP", prompt_text.stdout)
            self.assertIn("MCP server instructions", prompt_text.stdout)
            self.assertIn("Call `tapl_get_next`", prompt_text.stdout)
            self.assertIn("Do not run `taplctl --help`", prompt_text.stdout)
            self.assertNotIn("Planning must happen before implementation", prompt_text.stdout)

    def test_command_help_exposes_field_guidance(self) -> None:
        self.assertEqual(tapl_prompt.command_help_epilog(), tapl_prompt.render(tapl_prompt.ROOT_HELP_TEMPLATE))
        self.assertEqual(tapl_prompt.search_epilog(), tapl_prompt.render(tapl_prompt.SEARCH_HELP_TEMPLATE))
        self.assertEqual(tapl_prompt.plan_set_epilog(), tapl_prompt.render(tapl_prompt.PLAN_SET_HELP_TEMPLATE))
        self.assertEqual(tapl_prompt.finding_add_epilog(), tapl_prompt.render(tapl_prompt.FINDING_ADD_HELP_TEMPLATE))
        self.assertEqual(tapl_prompt.approval_set_epilog(), tapl_prompt.render(tapl_prompt.APPROVAL_SET_HELP_TEMPLATE))
        self.assertEqual(
            tapl_prompt.task_set_epilog(),
            tapl_prompt.render(tapl_prompt.TASK_SET_HELP_TEMPLATE),
        )
        self.assertNotIn("usage:", tapl_prompt.ROOT_HELP_TEMPLATE)
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "tapl.db"

            root_help = self.run_cli(db_path, "--help")
            self.assertEqual(root_help.returncode, 0, root_help.stderr)
            self.assertIn("Manual CLI fallback", root_help.stdout)
            self.assertIn("`tapl-mcp` server", root_help.stdout)
            self.assertIn("human operation, diagnostics, or repair", root_help.stdout)
            self.assertNotIn("Lifecycle order", root_help.stdout)
            self.assertNotIn("taplctl <command> <subcommand> --help", root_help.stdout)

            search_help = self.run_cli(db_path, "search", "--help")
            self.assertEqual(search_help.returncode, 0, search_help.stderr)
            self.assertIn("Manual CLI fallback", search_help.stdout)
            self.assertIn("`tapl_search_history`", search_help.stdout)
            self.assertIn("`tapl_get_item`", search_help.stdout)
            self.assertNotIn("History search rules", search_help.stdout)

            run_help = self.run_cli(db_path, "run", "set", "--help")
            self.assertEqual(run_help.returncode, 0, run_help.stderr)
            self.assertIn("Set active run fields", run_help.stdout)
            self.assertIn("--summary", run_help.stdout)
            self.assertIn("--result", run_help.stdout)
            self.assertIn("--agent", run_help.stdout)

            plan_help = self.run_cli(db_path, "plan", "set", "--help")
            self.assertEqual(plan_help.returncode, 0, plan_help.stderr)
            self.assertIn("Manual CLI fallback", plan_help.stdout)
            self.assertIn("`tapl_apply_plan`", plan_help.stdout)
            self.assertNotIn("Plan writing rules", plan_help.stdout)
            self.assertIn("PLAN-001", plan_help.stdout)
            self.assertIn("--objective", plan_help.stdout)
            self.assertIn("--requirements-trace", plan_help.stdout)
            self.assertIn("--selected-approach", plan_help.stdout)
            self.assertIn("--notes", plan_help.stdout)
            self.assertIn("--agent", plan_help.stdout)
            self.assertNotIn("Field contract", plan_help.stdout)
            self.assertNotIn("--body", plan_help.stdout)

            task_help = self.run_cli(db_path, "task", "set", "--help")
            self.assertEqual(task_help.returncode, 0, task_help.stderr)
            self.assertIn("--agent", task_help.stdout)
            self.assertIn("Manual CLI fallback", task_help.stdout)
            self.assertIn("typed TAPL task MCP tools", task_help.stdout)
            self.assertNotIn("Task writing rules", task_help.stdout)
            self.assertIn("--status", task_help.stdout)
            self.assertIn("--spec-id", task_help.stdout)
            self.assertIn("--blocker", task_help.stdout)
            self.assertIn("--next-action", task_help.stdout)

            approval_help = self.run_cli(db_path, "approval", "set", "--help")
            self.assertEqual(approval_help.returncode, 0, approval_help.stderr)
            self.assertIn("Manual CLI fallback", approval_help.stdout)
            self.assertIn("`tapl_approve_execution`", approval_help.stdout)
            self.assertNotIn("Approval writing rules", approval_help.stdout)
            self.assertIn("--decision", approval_help.stdout)
            self.assertIn("--prompt", approval_help.stdout)
            self.assertIn("--source", approval_help.stdout)
            self.assertIn("explicit_user", approval_help.stdout)
            self.assertIn("request_user_input", approval_help.stdout)

            finding_help = self.run_cli(db_path, "finding", "add", "--help")
            self.assertEqual(finding_help.returncode, 0, finding_help.stderr)
            self.assertIn("Add a finding", finding_help.stdout)
            self.assertIn("Why the finding matters", finding_help.stdout)
            self.assertIn("Manual CLI fallback", finding_help.stdout)
            self.assertIn("`tapl_add_finding`", finding_help.stdout)
            self.assertNotIn("Finding writing rules", finding_help.stdout)
            self.assertIn("--title", finding_help.stdout)

            for args in (
                ("init", "--help"),
                ("doctor", "--help"),
                ("reindex", "--help"),
                ("import-md", "--help"),
                ("hook-event", "--help"),
                ("install", "user", "--help"),
                ("install", "repo", "--help"),
                ("searchd", "start", "--help"),
                ("searchd", "run", "--help"),
            ):
                help_result = self.run_cli(db_path, *args)
                self.assertEqual(help_result.returncode, 0, help_result.stderr)
                self.assertIn("--agent", help_result.stdout)
            self.assertNotIn("Markdown form", finding_help.stdout)

            hook_help = self.run_cli(db_path, "hook-event", "--help")
            self.assertEqual(hook_help.returncode, 0, hook_help.stderr)
            self.assertIn("Hook handling mode", hook_help.stdout)
            self.assertIn("Print JSON output", hook_help.stdout)

    def test_high_level_lifecycle_commands_json_next_recipe_and_error_suggestion(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "tapl.db"
            self.run_cli(db_path, "init", "--json")

            summary = self.run_cli(
                db_path,
                "run",
                "summarize",
                "--summary",
                "High level lifecycle",
                "--agent",
            )
            self.assertEqual(summary.returncode, 0, summary.stderr)
            self.assertIn("<operation>run_summarize</operation>", summary.stdout)

            initial_next = self.run_cli(db_path, "next", "--agent")
            self.assertEqual(initial_next.returncode, 0, initial_next.stderr)
            self.assertIn("<name>apply-plan</name>", initial_next.stdout)
            self.assertIn("taplctl plan apply --stdin-json --agent", initial_next.stdout)

            plan_payload = {
                "id": "PLAN-001",
                "title": "Lifecycle plan",
                "summary": "REQ-001: high-level lifecycle commands",
                "objective": "Verify high-level lifecycle commands",
                "requirements_trace": "REQ-001: JSON stdin plan apply",
                "selected_approach": "Use high-level commands",
                "affected_files": "tapl/taplctl/cli.py",
                "execution_order": "Plan, create task, approve, start, complete",
                "risks": "Low-level set remains for repair only",
                "validation": "Focused lifecycle test",
            }
            plan = self.run_cli(
                db_path,
                "plan",
                "apply",
                "--stdin-json",
                "--agent",
                input_text=json.dumps(plan_payload),
            )
            self.assertEqual(plan.returncode, 0, plan.stderr)
            self.assertIn("<operation>plan_apply</operation>", plan.stdout)
            self.assertIn("<stable_id>PLAN-001</stable_id>", plan.stdout)

            after_plan_next = self.run_cli(db_path, "next", "--agent")
            self.assertEqual(after_plan_next.returncode, 0, after_plan_next.stderr)
            self.assertIn("<name>create-task</name>", after_plan_next.stdout)

            task_payload = {
                "id": "TASK-001",
                "title": "Lifecycle task",
                "spec_id": "PLAN-001",
                "goal": "Verify task lifecycle",
                "action": "Run high-level task commands",
                "verification": "Focused lifecycle test",
            }
            task = self.run_cli(
                db_path,
                "task",
                "create",
                "--stdin-json",
                "--agent",
                input_text=json.dumps(task_payload),
            )
            self.assertEqual(task.returncode, 0, task.stderr)
            self.assertIn("<operation>task_create</operation>", task.stdout)
            self.assertIn("<status>Pending</status>", task.stdout)

            approval_next = self.run_cli(db_path, "next", "--agent")
            self.assertEqual(approval_next.returncode, 0, approval_next.stderr)
            self.assertIn("<name>approve-execution</name>", approval_next.stdout)
            self.assertIn("taplctl approval approve", approval_next.stdout)

            approved = self.run_cli(
                db_path,
                "approval",
                "approve",
                "--stdin-json",
                "--agent",
                input_text=json.dumps(
                    {
                        "prompt": "Execute TASK-001 from PLAN-001",
                        "source": "explicit_user",
                    }
                ),
            )
            self.assertEqual(approved.returncode, 0, approved.stderr)
            self.assertIn("<operation>approval_approve</operation>", approved.stdout)

            started = self.run_cli(db_path, "task", "start", "TASK-001", "--agent")
            self.assertEqual(started.returncode, 0, started.stderr)
            self.assertIn("<operation>task_start</operation>", started.stdout)
            self.assertIn("<status>In Progress</status>", started.stdout)

            completed = self.run_cli(
                db_path,
                "task",
                "complete",
                "TASK-001",
                "--verification",
                "Focused lifecycle test passed",
                "--result",
                "Lifecycle commands work",
                "--agent",
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertIn("<operation>task_complete</operation>", completed.stdout)
            self.assertIn("<status>Completed</status>", completed.stdout)

            final_next = self.run_cli(db_path, "next", "--agent")
            self.assertEqual(final_next.returncode, 0, final_next.stderr)
            self.assertIn("<name>finish-run</name>", final_next.stdout)
            self.assertIn("taplctl archive finish", final_next.stdout)

            recipe = self.run_cli(db_path, "recipe", "task-complete", "--agent")
            self.assertEqual(recipe.returncode, 0, recipe.stderr)
            self.assertIn("<name>task-complete</name>", recipe.stdout)
            self.assertIn("taplctl task complete TASK-001", recipe.stdout)

            bad_status = self.run_cli(db_path, "task", "set", "--id", "TASK-001", "--status", "In", "Progress")
            self.assertEqual(bad_status.returncode, 2)
            self.assertIn("Did you mean", bad_status.stderr)
            self.assertIn("taplctl task start TASK-001 --agent", bad_status.stderr)

    def test_task_help_uses_fixed_required_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "tapl.db"
            task_help = self.run_cli(db_path, "task", "set", "--help")
            self.assertEqual(task_help.returncode, 0, task_help.stderr)
            self.assertIn("--spec-id", task_help.stdout)
            self.assertIn("--verification", task_help.stdout)
            self.assertNotIn("executable task:", task_help.stdout)
            self.assertIn("typed TAPL task MCP tools", task_help.stdout)

    def test_prompt_field_contract_helpers_use_invariant_rules(self) -> None:
        self.assertEqual(
            tapl_prompt.markdown_body_fields("plan")[:3],
            (
                ("Summary", "summary"),
                ("Objective", "objective"),
                ("Requirements trace", "requirements_trace"),
            ),
        )
        self.assertEqual(
            tapl_prompt.agent_item_fields("task"),
            (
                "spec_id",
                "goal",
                "action",
                "verification",
                "result",
                "blocker",
                "next_action",
                "custom_fields",
            ),
        )
        self.assertIn("--verification", tapl_prompt.task_required_field_summary())
        self.assertEqual(
            tapl_prompt.task_granularity_remediation(),
            "Split every independent edit, migration, and verification step.",
        )

    def test_parser_actions_have_help_text(self) -> None:
        parser = tapl_cli.build_parser()
        missing: list[str] = []

        def visit(current: argparse.ArgumentParser) -> None:
            for action in current._actions:
                if isinstance(action, (argparse._HelpAction, argparse._VersionAction)):
                    continue
                if isinstance(action, argparse._SubParsersAction):
                    for choice_action in action._choices_actions:
                        if not choice_action.help:
                            missing.append(f"{current.prog} {choice_action.dest}")
                    for subparser in action.choices.values():
                        visit(subparser)
                    continue
                if not action.help:
                    name = ", ".join(action.option_strings) or action.dest
                    missing.append(f"{current.prog}: {name}")

        visit(parser)
        self.assertEqual(missing, [])

    def test_install_user_writes_taplctl_hooks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            codex_home = base / "home" / ".codex"
            db_path = base / "tapl.db"

            installed = self.run_cli(
                db_path,
                "install",
                "user",
                "--codex-home",
                str(codex_home),
                "--taplctl-command",
                "taplctl",
                "--json",
            )
            self.assertEqual(installed.returncode, 0, installed.stderr)
            payload = json.loads(installed.stdout)
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["install"], "user")

            hooks = json.loads((codex_home / "hooks.json").read_text(encoding="utf-8"))
            prompt_hook = hooks["hooks"]["UserPromptSubmit"][0]["hooks"][0]["command"]
            self.assertEqual(prompt_hook, "taplctl hook-event --event UserPromptSubmit --mode observe")
            self.assertNotIn("SessionStart", hooks["hooks"])
            self.assertNotIn("tapl_hook.py", json.dumps(hooks))
            self.assertTrue((codex_home / "config.toml").exists())
            codex_config = tomllib.loads((codex_home / "config.toml").read_text(encoding="utf-8"))
            self.assertEqual(
                codex_config["mcp_servers"]["tapl"],
                {
                    "command": "taplctl",
                    "args": ["mcp"],
                    "enabled": True,
                    "required": False,
                    "default_tools_approval_mode": "auto",
                },
            )
            self.assertEqual(payload["tapl_config"], str(base / "home" / ".tapl" / "config.toml"))
            tapl_config_data = tomllib.loads(
                (base / "home" / ".tapl" / "config.toml").read_text(encoding="utf-8")
            )
            self.assertEqual(
                tapl_config_data["subagents"],
                {
                    "enabled": True,
                    "models": {
                        "gpt-5.6-sol": ["xhigh", "max"],
                        "gpt-5.6-terra": ["high", "xhigh", "max"],
                        "gpt-5.6-luna": ["high", "xhigh"],
                    },
                },
            )
            self.assertNotIn("plan-task-execute", tapl_config_data)
            self.assertNotIn("plan_task_execute", tapl_config_data)
            self.assertEqual(
                (base / "home" / ".tapl" / "version").read_text(encoding="utf-8").strip(),
                __version__,
            )
            self.assertFalse((codex_home / "agents").exists())

    def test_install_user_merges_existing_codex_config_without_overwriting_user_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            codex_home = base / "home" / ".codex"
            codex_home.mkdir(parents=True)
            (codex_home / "config.toml").write_text(
                """
# user codex preferences
model = "gpt-5"
approval_policy = "on-request"

[features]
multi_agent = false

[mcp_servers.existing]
command = "existing-mcp"
""".lstrip(),
                encoding="utf-8",
            )
            agents_dir = codex_home / "agents"
            agents_dir.mkdir()
            (agents_dir / "senior-worker.toml").write_text("name = \"senior-worker\"\n", encoding="utf-8")
            db_path = base / "tapl.db"

            installed = self.run_cli(
                db_path,
                "install",
                "user",
                "--codex-home",
                str(codex_home),
                "--taplctl-command",
                "taplctl",
                "--json",
            )
            self.assertEqual(installed.returncode, 0, installed.stderr)
            payload = json.loads(installed.stdout)
            config_result = next(file for file in payload["files"] if file["path"].endswith("config.toml"))
            self.assertEqual(config_result["action"], "merged")

            config_text = (codex_home / "config.toml").read_text(encoding="utf-8")
            self.assertIn("# user codex preferences", config_text)
            parsed = tomllib.loads(config_text)
            self.assertEqual(parsed["model"], "gpt-5")
            self.assertEqual(parsed["approval_policy"], "on-request")
            self.assertEqual(parsed["model_reasoning_effort"], "xhigh")
            self.assertEqual(parsed["personality"], "pragmatic")
            self.assertNotIn("multi_agent", parsed["features"])
            self.assertTrue(parsed["features"]["default_mode_request_user_input"])
            self.assertEqual(parsed["mcp_servers"]["existing"]["command"], "existing-mcp")
            self.assertEqual(parsed["mcp_servers"]["tapl"]["command"], "taplctl")
            self.assertEqual(parsed["mcp_servers"]["tapl"]["args"], ["mcp"])
            self.assertEqual(parsed["mcp_servers"]["tapl"]["default_tools_approval_mode"], "auto")
            self.assertFalse((agents_dir / "senior-worker.toml").exists())

    def test_install_user_force_applies_managed_codex_config_values_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            codex_home = base / "home" / ".codex"
            codex_home.mkdir(parents=True)
            (codex_home / "config.toml").write_text(
                """
model = "gpt-5"
approval_policy = "on-request"

[features]
multi_agent = false
experimental = true
""".lstrip(),
                encoding="utf-8",
            )
            db_path = base / "tapl.db"

            installed = self.run_cli(
                db_path,
                "install",
                "user",
                "--codex-home",
                str(codex_home),
                "--taplctl-command",
                "taplctl",
                "--force",
                "--json",
            )
            self.assertEqual(installed.returncode, 0, installed.stderr)
            payload = json.loads(installed.stdout)
            config_result = next(file for file in payload["files"] if file["path"].endswith("config.toml"))
            self.assertEqual(config_result["action"], "updated")

            parsed = tomllib.loads((codex_home / "config.toml").read_text(encoding="utf-8"))
            self.assertEqual(parsed["model"], "gpt-5.5")
            self.assertEqual(parsed["approval_policy"], "on-request")
            self.assertEqual(parsed["model_reasoning_effort"], "xhigh")
            self.assertEqual(parsed["personality"], "pragmatic")
            self.assertNotIn("multi_agent", parsed["features"])
            self.assertTrue(parsed["features"]["experimental"])
            self.assertTrue(parsed["features"]["default_mode_request_user_input"])
            self.assertEqual(parsed["mcp_servers"]["tapl"]["command"], "taplctl")
            self.assertEqual(parsed["mcp_servers"]["tapl"]["args"], ["mcp"])

    def test_install_repo_writes_hooks_config_and_db(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            repo = base / "repo"
            repo.mkdir()
            (repo / "README.md").write_text("# repo\n", encoding="utf-8")
            (repo / ".codex").mkdir()
            (repo / ".codex" / "hooks.json").write_text(
                json.dumps(
                    {
                        "hooks": {
                            "SessionStart": [
                                {
                                    "matcher": "startup|resume|clear|compact",
                                    "hooks": [
                                        {
                                            "type": "command",
                                            "command": "echo keep session",
                                        },
                                        {
                                            "type": "command",
                                            "command": "taplctl hook-event --event SessionStart --mode observe",
                                        },
                                    ],
                                }
                            ],
                            "PreToolUse": [
                                {
                                    "hooks": [
                                        {
                                            "type": "command",
                                            "command": "echo keep",
                                        }
                                    ]
                                }
                            ]
                        }
                    }
                ),
                encoding="utf-8",
            )
            db_path = base / "tapl.db"

            installed = self.run_cli(
                db_path,
                "install",
                "repo",
                "--repo",
                str(repo),
                "--taplctl-command",
                "/opt/tapl/bin/taplctl",
                "--json",
            )
            self.assertEqual(installed.returncode, 0, installed.stderr)
            payload = json.loads(installed.stdout)
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["install"], "repo")

            hooks = json.loads((repo / ".codex" / "hooks.json").read_text(encoding="utf-8"))
            session_commands = [
                hook["command"]
                for entry in hooks["hooks"]["SessionStart"]
                for hook in entry["hooks"]
            ]
            self.assertEqual(session_commands, ["echo keep session"])
            pre_tool_commands = [hook["command"] for entry in hooks["hooks"]["PreToolUse"] for hook in entry["hooks"]]
            self.assertIn("echo keep", pre_tool_commands)
            self.assertIn(
                "/opt/tapl/bin/taplctl hook-event --event PreToolUse --mode observe",
                pre_tool_commands,
            )
            self.assertTrue((repo / ".codex" / "config.toml").exists())
            codex_config = tomllib.loads((repo / ".codex" / "config.toml").read_text(encoding="utf-8"))
            self.assertEqual(codex_config["mcp_servers"]["tapl"]["command"], "/opt/tapl/bin/taplctl")
            self.assertEqual(codex_config["mcp_servers"]["tapl"]["args"], ["mcp"])
            self.assertFalse(codex_config["mcp_servers"]["tapl"]["required"])
            self.assertFalse((repo / ".codex" / "agents").exists())
            tapl_config_data = tomllib.loads((repo / ".tapl" / "config.toml").read_text())
            self.assertNotIn("plan-task-execute", tapl_config_data)
            self.assertNotIn("plan_task_execute", tapl_config_data)
            self.assertEqual(
                (repo / ".tapl" / "version").read_text(encoding="utf-8").strip(),
                __version__,
            )
            self.assertFalse((repo / ".tapl" / "workspace.toml").exists())
            self.assertFalse((repo / ".codex" / "tapl" / "tapl.toml").exists())
            self.assertTrue((repo / ".tapl" / "tapl.db").exists())

    def test_install_repo_version_upgrade_prompt_can_overwrite_tapl_config(self) -> None:
        class TtyInput(io.StringIO):
            def isatty(self) -> bool:
                return True

        class TtyOutput(io.StringIO):
            def isatty(self) -> bool:
                return True

        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            repo = base / "repo"
            repo.mkdir()
            tapl_dir = repo / ".tapl"
            tapl_dir.mkdir()
            config_path = tapl_dir / "config.toml"
            config_path.write_text(
                """
[search]
max_results = 3

[plan-task-execute]
use_level_subagent = true
level_subagent_aggressiveness = "force"
plan_detail = "minimal"
planning_approval_level = "less"
task_granularity = "minimal"
require_execution_approval = false

[subagents]
enabled = false

[subagents.models]
"user-runtime-model" = ["custom-effort"]

[user]
keep = true
""".lstrip(),
                encoding="utf-8",
            )
            (tapl_dir / "version").write_text("0.0.0\n", encoding="utf-8")

            original_stdin = sys.stdin
            original_stderr = sys.stderr
            prompt_output = TtyOutput()
            try:
                sys.stdin = TtyInput("o\n")
                sys.stderr = prompt_output
                payload = tapl_install.install_repo(
                    repo=repo,
                    taplctl_command="taplctl",
                )
            finally:
                sys.stdin = original_stdin
                sys.stderr = original_stderr

            config_result = next(
                file for file in payload["files"] if file["path"] == str(config_path.resolve())
            )
            self.assertEqual(config_result["action"], "updated")
            self.assertEqual(config_result["policy"], "overwrite")
            self.assertIn("overwrite with updated defaults", prompt_output.getvalue())

            parsed = tomllib.loads(config_path.read_text(encoding="utf-8"))
            self.assertEqual(parsed["search"]["max_results"], tapl_config.DEFAULT_SEARCH_MAX_RESULTS)
            self.assertTrue(parsed["subagents"]["enabled"])
            self.assertEqual(
                parsed["subagents"]["models"],
                {
                    "gpt-5.6-sol": ["xhigh", "max"],
                    "gpt-5.6-terra": ["high", "xhigh", "max"],
                    "gpt-5.6-luna": ["high", "xhigh"],
                },
            )
            self.assertNotIn("user", parsed)
            self.assertEqual((tapl_dir / "version").read_text(encoding="utf-8").strip(), __version__)

    def test_install_repo_version_upgrade_can_merge_tapl_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            repo = base / "repo"
            repo.mkdir()
            tapl_dir = repo / ".tapl"
            tapl_dir.mkdir()
            config_path = tapl_dir / "config.toml"
            config_path.write_text(
                """
[search]
max_results = 3

[plan-task-execute]
use_level_subagent = true
level_subagent_aggressiveness = "force"
plan_detail = "minimal"
planning_approval_level = "less"
task_granularity = "minimal"
require_execution_approval = false

[subagents]
enabled = false

[subagents.models]
"user-runtime-model" = ["custom-effort"]

[user]
keep = true
""".lstrip(),
                encoding="utf-8",
            )
            (tapl_dir / "version").write_text("0.0.0\n", encoding="utf-8")
            db_path = base / "tapl.db"

            installed = self.run_cli(
                db_path,
                "install",
                "repo",
                "--repo",
                str(repo),
                "--taplctl-command",
                "taplctl",
                "--tapl-config-policy",
                "merge",
                "--json",
            )
            self.assertEqual(installed.returncode, 0, installed.stderr)
            payload = json.loads(installed.stdout)
            config_result = next(
                file for file in payload["files"] if file["path"] == str(config_path.resolve())
            )
            self.assertEqual(config_result["action"], "merged")
            self.assertEqual(config_result["policy"], "merge")

            parsed = tomllib.loads(config_path.read_text(encoding="utf-8"))
            self.assertEqual(parsed["search"]["max_results"], 3)
            self.assertEqual(parsed["user"]["keep"], True)
            self.assertEqual(parsed["search"]["mode"], tapl_config.DEFAULT_SEARCH_MODE)
            self.assertFalse(parsed["subagents"]["enabled"])
            self.assertEqual(
                parsed["subagents"]["models"]["user-runtime-model"],
                ["custom-effort"],
            )
            self.assertEqual(
                parsed["subagents"]["models"]["gpt-5.6-luna"],
                ["high", "xhigh"],
            )
            config_text = config_path.read_text(encoding="utf-8")
            for key in (
                "use_level_subagent",
                "level_subagent_aggressiveness",
                "plan_detail",
                "planning_approval_level",
                "task_granularity",
                "require_execution_approval",
            ):
                self.assertNotIn(key, config_text)
            self.assertEqual((tapl_dir / "version").read_text(encoding="utf-8").strip(), __version__)

    def test_install_repo_version_upgrade_merge_skips_invalid_tapl_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            repo = base / "repo"
            repo.mkdir()
            tapl_dir = repo / ".tapl"
            tapl_dir.mkdir()
            config_path = tapl_dir / "config.toml"
            config_path.write_text("[search\n", encoding="utf-8")
            (tapl_dir / "version").write_text("0.0.0\n", encoding="utf-8")

            payload = tapl_install.install_repo(
                repo=repo,
                taplctl_command="taplctl",
                tapl_config_policy="merge",
            )

            config_result = next(
                file for file in payload["files"] if file["path"] == str(config_path.resolve())
            )
            self.assertEqual(config_result["action"], "skipped")
            self.assertEqual(config_result["policy"], "merge")
            self.assertEqual(config_result["reason"], "invalid_toml")
            self.assertEqual(config_path.read_text(encoding="utf-8"), "[search\n")
            self.assertEqual((tapl_dir / "version").read_text(encoding="utf-8").strip(), __version__)

    def test_auto_install_refreshes_stale_user_and_repo_scopes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            home = base / "home"
            repo = base / "repo"
            repo.mkdir()
            (home / ".tapl").mkdir(parents=True)
            (repo / ".tapl").mkdir(parents=True)
            (home / ".tapl" / "config.toml").write_text("[search]\nmax_results = 4\n", encoding="utf-8")
            (repo / ".tapl" / "config.toml").write_text("[search]\nmax_results = 5\n", encoding="utf-8")
            (home / ".tapl" / "version").write_text("0.0.0\n", encoding="utf-8")
            (repo / ".tapl" / "version").write_text("0.0.0\n", encoding="utf-8")

            original_stdin = sys.stdin
            try:
                sys.stdin = io.StringIO("")
                results = tapl_install.auto_install_if_needed(
                    start=repo,
                    home=home,
                    taplctl_command="taplctl",
                )
            finally:
                sys.stdin = original_stdin

            self.assertEqual([result["install"] for result in results], ["user", "repo"])
            self.assertEqual(
                (home / ".tapl" / "version").read_text(encoding="utf-8").strip(),
                __version__,
            )
            self.assertEqual(
                (repo / ".tapl" / "version").read_text(encoding="utf-8").strip(),
                __version__,
            )
            self.assertTrue((home / ".codex" / "hooks.json").exists())
            self.assertTrue((repo / ".codex" / "hooks.json").exists())
            user_config = tomllib.loads((home / ".tapl" / "config.toml").read_text(encoding="utf-8"))
            repo_config = tomllib.loads((repo / ".tapl" / "config.toml").read_text(encoding="utf-8"))
            self.assertEqual(user_config["search"]["max_results"], 4)
            self.assertEqual(repo_config["search"]["max_results"], 5)
            self.assertNotIn("plan-task-execute", user_config)
            self.assertNotIn("plan_task_execute", user_config)
            self.assertNotIn("plan-task-execute", repo_config)
            self.assertNotIn("plan_task_execute", repo_config)

    def test_auto_install_does_not_treat_repo_db_as_install_marker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            home = base / "home"
            repo = base / "repo"
            repo.mkdir()
            (repo / ".tapl").mkdir()
            (repo / ".tapl" / "tapl.db").write_bytes(b"not a marker")

            results = tapl_install.auto_install_if_needed(start=repo, home=home)

            self.assertEqual(results, [])
            self.assertFalse((repo / ".codex").exists())
            self.assertFalse((repo / ".tapl" / "version").exists())

    def test_hook_enforce_blocks_without_tasks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "tapl.db"
            self.run_cli(db_path, "init", "--json")
            blocked = self.run_cli(
                db_path,
                "hook-event",
                "--event",
                "PreToolUse",
                "--mode",
                "enforce",
                "--tool",
                "apply_patch",
                input_text="{}",
            )
            self.assertEqual(blocked.returncode, 2)
            self.assertIn("durable edit requires", blocked.stderr)
            self.assertIn("Workflow state lives in the repo-local TAPL database", blocked.stderr)
            self.assertIn("installed `tapl_*` MCP tools", blocked.stderr)
            self.assertIn("manual fallback only", blocked.stderr)

            self.run_cli(
                db_path,
                "plan",
                "set",
                "--id",
                "SPEC-001",
                "--title",
                "Approved edit plan",
                "--summary",
                "REQ-001: approved edit hook validation.",
                "--objective",
                "Allow durable edits only after valid plan, task, and approval state.",
                "--requirements-trace",
                "REQ-001: PreToolUse enforce blocks until approval exists.",
                "--selected-approach",
                "Create valid executable and companion verification tasks.",
                "--affected-files",
                "tapl/taplctl/hooks.py",
                "--execution-order",
                "Create plan, create tasks, record approval, then allow hook.",
                "--risks",
                "Strict validation should not obscure the approval check.",
                "--validation",
                "PreToolUse enforce returns 0 after approval.",
            )
            self.run_cli(
                db_path,
                "task",
                "set",
                "--id",
                "TASK-001",
                "--title",
                "Approved edit",
                "--status",
                "In Progress",
                "--spec-id",
                "SPEC-001",
                "--goal",
                "Execute approved edit",
                "--action",
                "Run durable edit after approval",
                "--verification",
                "PreToolUse enforce allows approved edit",
            )
            self.run_cli(
                db_path,
                "task",
                "set",
                "--id",
                "TASK-002",
                "--title",
                "Approved edit verification",
                "--status",
                "Completed",
                "--spec-id",
                "SPEC-001",
                "--verification",
                "Companion verification task satisfies strict granularity.",
                "--result",
                "Verification recorded.",
            )
            approval_blocked = self.run_cli(
                db_path,
                "hook-event",
                "--event",
                "PreToolUse",
                "--mode",
                "enforce",
                "--tool",
                "apply_patch",
                input_text="{}",
            )
            self.assertEqual(approval_blocked.returncode, 2)
            self.assertIn("execution_approval_missing", approval_blocked.stderr)

            approved = self.run_cli(
                db_path,
                "approval",
                "set",
                "--decision",
                "approved",
                "--prompt",
                "Execute approved edit",
                "--json",
            )
            self.assertEqual(approved.returncode, 0, approved.stderr)

            allowed = self.run_cli(
                db_path,
                "hook-event",
                "--event",
                "PreToolUse",
                "--mode",
                "enforce",
                "--tool",
                "apply_patch",
                input_text="{}",
            )
            self.assertEqual(allowed.returncode, 0, allowed.stderr)

    def test_hook_enforce_blocks_config_validation_errors(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "tapl.db"
            self.run_cli(
                db_path,
                "task",
                "set",
                "--id",
                "TASK-001",
                "--title",
                "Existing unrouted task",
                "--status",
                "In Progress",
            )

            blocked = self.run_cli(
                db_path,
                "hook-event",
                "--event",
                "PreToolUse",
                "--mode",
                "enforce",
                "--tool",
                "apply_patch",
                input_text="{}",
            )
            self.assertEqual(blocked.returncode, 2)
            self.assertIn("missing_plan", blocked.stderr)
            self.assertIn("tapl_apply_plan", blocked.stderr)

    def test_hook_observe_warns_for_fixed_very_granular_single_task(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "tapl.db"
            self.run_cli(
                db_path,
                "plan",
                "set",
                "--id",
                "SPEC-001",
                "--title",
                "Config validation",
                "--summary",
                "Add validation, connect CLI and hook, update tests and docs.",
            )
            self.run_cli(
                db_path,
                "task",
                "set",
                "--id",
                "TASK-001",
                "--title",
                "All work in one task",
                "--status",
                "In Progress",
            )

            warned = self.run_cli(
                db_path,
                "hook-event",
                "--event",
                "PreToolUse",
                "--mode",
                "observe",
                "--tool",
                "apply_patch",
                input_text="{}",
            )
            self.assertEqual(warned.returncode, 0, warned.stderr)
            self.assertIn("task_granularity_too_coarse", warned.stdout)
            self.assertIn("Split", warned.stdout)

    def test_hook_user_prompt_outputs_lifecycle_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "tapl.db"
            event = self.run_cli(
                db_path,
                "hook-event",
                "--event",
                "UserPromptSubmit",
                "--mode",
                "observe",
                input_text='{"prompt": "Implement lifecycle context"}',
            )
            self.assertEqual(event.returncode, 0, event.stderr)
            self.assertIn("tapl context:", event.stdout)
            self.assertIn("# TAPL MCP", event.stdout)
            self.assertIn("MCP server instructions", event.stdout)
            self.assertIn("Call `tapl_get_next`", event.stdout)
            self.assertIn("Do not run `taplctl --help`", event.stdout)
            self.assertNotIn("Planning must happen before implementation", event.stdout)
            self.assertIn("## Next Actions", event.stdout)
            self.assertIn("Create or update plan state", event.stdout)
            self.assertIn("`tapl_apply_plan`", event.stdout)
            self.assertNotIn("### SubAgent Delegation", event.stdout)

            server_guidance = tapl_mcp.create_server(workspace_root=ROOT).instructions
            self.assertIn("Planning must happen before implementation", server_guidance)
            self.assertIn("### SubAgent Delegation", server_guidance)
            self.assertIn("`gpt-5.6-sol`: `xhigh`, `max`", server_guidance)
            self.assertIn("`gpt-5.6-luna`: `high`, `xhigh`", server_guidance)

            event_json = self.run_cli(
                db_path,
                "hook-event",
                "--event",
                "UserPromptSubmit",
                "--mode",
                "observe",
                "--json",
                input_text='{"prompt": "Implement lifecycle context"}',
            )
            self.assertEqual(event_json.returncode, 0, event_json.stderr)
            payload = json.loads(event_json.stdout)
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["context"]["prompt_summary"], "Implement lifecycle context")
            self.assertIn("workflow_guidance", payload["context"])

    def test_context_and_user_prompt_hook_apply_enabled_and_disabled_subagent_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            db_path = base / "tapl.db"
            enabled_config = base / "enabled.toml"
            disabled_config = base / "disabled.toml"
            enabled_config.write_text(
                """
[subagents]
enabled = true

[subagents.models]
"gpt-5.6-luna" = ["xhigh"]
"future-runtime-model" = ["custom-effort"]
""".lstrip(),
                encoding="utf-8",
            )
            disabled_config.write_text(
                """
[subagents]
enabled = false
""".lstrip(),
                encoding="utf-8",
            )

            context = self.run_cli(
                db_path,
                "--config",
                str(enabled_config),
                "context",
                "--event",
                "UserPromptSubmit",
                "--json",
            )
            self.assertEqual(context.returncode, 0, context.stderr)
            context_payload = json.loads(context.stdout)
            self.assertEqual(
                context_payload["config"]["subagents"],
                {
                    "enabled": True,
                    "models": {
                        "gpt-5.6-luna": ["xhigh"],
                        "future-runtime-model": ["custom-effort"],
                    },
                },
            )
            guidance = "\n".join(context_payload["workflow_guidance"])
            self.assertIn("MCP server instructions", guidance)
            self.assertNotIn("### SubAgent Delegation", guidance)
            self.assertIn("explicitly requests SubAgent delegation", guidance)
            self.assertIn("without asking the user again", guidance)
            self.assertIn("does not override higher-priority instructions", guidance)
            self.assertEqual(guidance.count("explicitly requests SubAgent delegation"), 1)

            enabled_instructions = tapl_prompt.mcp_server_instructions(
                subagents=tapl_config.load(enabled_config).subagents,
            )
            self.assertIn("### SubAgent Delegation", enabled_instructions)
            self.assertIn("`gpt-5.6-luna`: `xhigh`", enabled_instructions)
            self.assertIn("`future-runtime-model`: `custom-effort`", enabled_instructions)
            self.assertIn("actually supported by the current SubAgent runtime", enabled_instructions)
            self.assertLess(
                enabled_instructions.index("## Tasks And Execution"),
                enabled_instructions.index("### SubAgent Delegation"),
            )
            self.assertLess(
                enabled_instructions.index("### SubAgent Delegation"),
                enabled_instructions.index("Fixed execution approval (`require_execution_approval = true`)"),
            )

            status = self.run_cli(
                db_path,
                "--config",
                str(enabled_config),
                "status",
                "--json",
            )
            self.assertEqual(status.returncode, 0, status.stderr)
            self.assertEqual(
                json.loads(status.stdout)["config"]["subagents"],
                context_payload["config"]["subagents"],
            )

            hook = self.run_cli(
                db_path,
                "--config",
                str(enabled_config),
                "hook-event",
                "--event",
                "UserPromptSubmit",
                "--mode",
                "observe",
                "--json",
                input_text='{"prompt": "Delegate configured work"}',
            )
            self.assertEqual(hook.returncode, 0, hook.stderr)
            hook_payload = json.loads(hook.stdout)
            self.assertEqual(
                hook_payload["context"]["config"]["subagents"],
                context_payload["config"]["subagents"],
            )
            self.assertIn("MCP server instructions", hook_payload["message"])
            self.assertNotIn("### SubAgent Delegation", hook_payload["message"])
            self.assertIn("explicitly requests SubAgent delegation", hook_payload["message"])
            self.assertEqual(
                hook_payload["message"].count("explicitly requests SubAgent delegation"),
                1,
            )

            disabled_context = self.run_cli(
                db_path,
                "--config",
                str(disabled_config),
                "context",
                "--event",
                "UserPromptSubmit",
                "--json",
            )
            self.assertEqual(disabled_context.returncode, 0, disabled_context.stderr)
            disabled_payload = json.loads(disabled_context.stdout)
            self.assertEqual(
                disabled_payload["config"]["subagents"],
                {
                    "enabled": False,
                    "models": {
                        "gpt-5.6-sol": ["xhigh", "max"],
                        "gpt-5.6-terra": ["high", "xhigh", "max"],
                        "gpt-5.6-luna": ["high", "xhigh"],
                    },
                },
            )
            self.assertNotIn(
                "### SubAgent Delegation",
                "\n".join(disabled_payload["workflow_guidance"]),
            )
            self.assertNotIn(
                "explicitly requests SubAgent delegation",
                "\n".join(disabled_payload["workflow_guidance"]),
            )
            disabled_instructions = tapl_prompt.mcp_server_instructions(
                subagents=tapl_config.load(disabled_config).subagents,
            )
            self.assertNotIn("### SubAgent Delegation", disabled_instructions)

            disabled_hook = self.run_cli(
                db_path,
                "--config",
                str(disabled_config),
                "hook-event",
                "--event",
                "UserPromptSubmit",
                "--mode",
                "observe",
                "--json",
                input_text='{"prompt": "Run without delegation"}',
            )
            self.assertEqual(disabled_hook.returncode, 0, disabled_hook.stderr)
            disabled_hook_payload = json.loads(disabled_hook.stdout)
            self.assertNotIn("### SubAgent Delegation", disabled_hook_payload["message"])
            self.assertNotIn(
                "explicitly requests SubAgent delegation",
                disabled_hook_payload["message"],
            )

            session = self.run_cli(
                db_path,
                "--config",
                str(enabled_config),
                "context",
                "--event",
                "SessionStart",
                "--json",
            )
            self.assertEqual(session.returncode, 0, session.stderr)
            self.assertNotIn(
                "### SubAgent Delegation",
                "\n".join(json.loads(session.stdout)["workflow_guidance"]),
            )

    def test_isolated_hook_config_can_use_repo_taplctl_workflow_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            workspace = base / "workspace"
            codex_home = base / "home" / ".codex"
            workspace.mkdir()
            codex_home.mkdir(parents=True)
            repo_taplctl = f"{shlex.quote(sys.executable)} -m taplctl"
            prompt_command = f"{repo_taplctl} hook-event --event UserPromptSubmit --mode observe --json"
            pre_tool_command = f"{repo_taplctl} hook-event --event PreToolUse --mode enforce --json"
            hooks = {
                "hooks": {
                    "UserPromptSubmit": [
                        {
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": prompt_command,
                                }
                            ]
                        }
                    ],
                    "PreToolUse": [
                        {
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": pre_tool_command,
                                }
                            ]
                        }
                    ]
                }
            }
            hooks_path = codex_home / "hooks.json"
            hooks_path.write_text(json.dumps(hooks, indent=2), encoding="utf-8")
            hook_data = json.loads(hooks_path.read_text(encoding="utf-8"))
            hook_command = hook_data["hooks"]["UserPromptSubmit"][0]["hooks"][0]["command"]
            pre_tool_hook_command = hook_data["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
            self.assertIn("-m taplctl", hook_command)
            self.assertIn("-m taplctl", pre_tool_hook_command)
            self.assertNotIn("/opt/homebrew/bin/taplctl", hook_command)
            self.assertNotIn("/opt/homebrew/bin/taplctl", pre_tool_hook_command)

            env = self.tapl_env()
            env["HOME"] = str(base / "home")

            def run_repo_taplctl(*args: str, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
                return subprocess.run(
                    [sys.executable, "-m", "taplctl", *args],
                    input=input_text,
                    text=True,
                    capture_output=True,
                    check=False,
                    cwd=str(workspace),
                    env=env,
                )

            event = subprocess.run(
                hook_command,
                shell=True,
                input=json.dumps({"cwd": str(workspace), "prompt": "Implement isolated workflow"}),
                text=True,
                capture_output=True,
                check=False,
                cwd=str(workspace),
                env=env,
            )
            self.assertEqual(event.returncode, 0, event.stderr)
            payload = json.loads(event.stdout)
            guidance = "\n".join(payload["context"]["workflow_guidance"])
            next_actions = "\n".join(payload["context"]["next_actions"])
            self.assertEqual(payload["context"]["prompt_summary"], "Implement isolated workflow")
            self.assertIn("# TAPL MCP", guidance)
            self.assertIn("MCP server instructions", guidance)
            self.assertIn("Do not run `taplctl --help`", guidance)
            self.assertNotIn("## Role Boundaries", guidance)
            self.assertIn("tapl_summarize_run", next_actions)
            self.assertIn("Create or update plan state", next_actions)
            self.assertIn("tapl_apply_plan", next_actions)
            self.assertEqual(payload["context"]["validation_issues"], [])
            self.assertTrue((workspace / ".tapl" / "tapl.db").exists())

            run = run_repo_taplctl("run", "set", "--summary", "Implement isolated workflow", "--agent")
            self.assertEqual(run.returncode, 0, run.stderr)
            plan = run_repo_taplctl(
                "plan",
                "set",
                "--id",
                "PLAN-001",
                "--title",
                "Isolated workflow plan",
                "--summary",
                "REQ-001: isolated repo taplctl workflow.",
                "--objective",
                "Verify the isolated hook prompt can be followed with the repo-local taplctl.",
                "--requirements-trace",
                "REQ-001: use repo taplctl from isolated hook config.",
                "--selected-approach",
                "Run hook prompt, record plan and tasks, approve execution, then allow durable hook.",
                "--affected-files",
                "isolated workspace",
                "--execution-order",
                "Prompt, summarize run, write plan, write tasks, approve, then run PreToolUse.",
                "--risks",
                "Hook config could accidentally call a globally installed taplctl.",
                "--validation",
                "PreToolUse enforce returns 0 after records and approval.",
                "--agent",
            )
            self.assertEqual(plan.returncode, 0, plan.stderr)
            task = run_repo_taplctl(
                "task",
                "set",
                "--id",
                "TASK-001",
                "--title",
                "Isolated implementation",
                "--status",
                "In Progress",
                "--spec-id",
                "PLAN-001",
                "--goal",
                "Execute the isolated workflow.",
                "--action",
                "Use repo-local taplctl commands from the isolated workspace.",
                "--verification",
                "PreToolUse enforce allows durable work after approval.",
                "--agent",
            )
            self.assertEqual(task.returncode, 0, task.stderr)
            companion = run_repo_taplctl(
                "task",
                "set",
                "--id",
                "TASK-002",
                "--title",
                "Isolated verification",
                "--status",
                "Completed",
                "--spec-id",
                "PLAN-001",
                "--verification",
                "Companion task satisfies strict granularity.",
                "--result",
                "Verification recorded.",
                "--agent",
            )
            self.assertEqual(companion.returncode, 0, companion.stderr)
            approval = run_repo_taplctl(
                "approval",
                "set",
                "--decision",
                "approved",
                "--prompt",
                "Execute isolated workflow task.",
                "--source",
                "explicit_user",
                "--agent",
            )
            self.assertEqual(approval.returncode, 0, approval.stderr)
            allowed = subprocess.run(
                pre_tool_hook_command,
                shell=True,
                input=json.dumps({"cwd": str(workspace), "tool_name": "apply_patch"}),
                text=True,
                capture_output=True,
                check=False,
                cwd=str(workspace),
                env=env,
            )
            self.assertEqual(allowed.returncode, 0, allowed.stderr)
            allowed_payload = json.loads(allowed.stdout)
            self.assertFalse(allowed_payload["block"])

    def test_post_tool_use_external_search_outputs_finding_guidance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "tapl.db"
            event = self.run_cli(
                db_path,
                "hook-event",
                "--event",
                "PostToolUse",
                "--mode",
                "observe",
                "--tool",
                "web.run",
                input_text='{"search_query": [{"q": "tapl workflow"}]}',
            )
            self.assertEqual(event.returncode, 0, event.stderr)
            self.assertIn("tapl_add_finding", event.stdout)
            self.assertIn("decision-relevant", event.stdout)
            self.assertIn("Do not store raw search dumps", event.stdout)

    def test_session_start_hook_does_not_create_active_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "tapl.db"
            session = self.run_cli(
                db_path,
                "hook-event",
                "--event",
                "SessionStart",
                "--mode",
                "observe",
                "--json",
                input_text="{}",
            )
            self.assertEqual(session.returncode, 0, session.stderr)
            session_payload = json.loads(session.stdout)
            self.assertTrue(session_payload["ok"])
            self.assertFalse(session_payload["context"]["active_run"]["present"])

            status = self.run_cli(db_path, "status", "--json")
            self.assertEqual(status.returncode, 0, status.stderr)
            status_payload = json.loads(status.stdout)
            self.assertIsNone(status_payload["active_run"])

            prompt = self.run_cli(
                db_path,
                "hook-event",
                "--event",
                "UserPromptSubmit",
                "--mode",
                "observe",
                "--json",
                input_text='{"prompt": "Start real work"}',
            )
            self.assertEqual(prompt.returncode, 0, prompt.stderr)
            prompt_payload = json.loads(prompt.stdout)
            self.assertTrue(prompt_payload["context"]["active_run"]["present"])
            self.assertEqual(
                prompt_payload["context"]["active_run"]["request_summary"],
                "New request",
            )
            self.assertIn(
                "tapl_summarize_run",
                "\n".join(prompt_payload["context"]["next_actions"]),
            )

            summary = self.run_cli(
                db_path,
                "run",
                "set",
                "--summary",
                "Start real work",
                "--json",
            )
            self.assertEqual(summary.returncode, 0, summary.stderr)
            summary_payload = json.loads(summary.stdout)
            self.assertEqual(
                summary_payload["active_run"]["request_summary"],
                "Start real work",
            )

    def test_stop_hook_observe_is_silent_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "tapl.db"
            prompt = self.run_cli(
                db_path,
                "hook-event",
                "--event",
                "UserPromptSubmit",
                "--mode",
                "observe",
                input_text='{"prompt": "Create a run without plans"}',
            )
            self.assertEqual(prompt.returncode, 0, prompt.stderr)

            stopped = self.run_cli(
                db_path,
                "hook-event",
                "--event",
                "Stop",
                "--mode",
                "observe",
                input_text="{}",
            )
            self.assertEqual(stopped.returncode, 0, stopped.stderr)
            self.assertEqual(stopped.stdout, "")
            self.assertEqual(stopped.stderr, "")

            stopped_json = self.run_cli(
                db_path,
                "hook-event",
                "--event",
                "Stop",
                "--mode",
                "observe",
                "--json",
                input_text="{}",
            )
            self.assertEqual(stopped_json.returncode, 0, stopped_json.stderr)
            payload = json.loads(stopped_json.stdout)
            self.assertTrue(payload["ok"])
            self.assertIn("missing_plan", payload["message"])

    def test_stop_hook_auto_archives_completed_plan_task_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "tapl.db"
            prompt = self.run_cli(
                db_path,
                "hook-event",
                "--event",
                "UserPromptSubmit",
                "--mode",
                "observe",
                "--json",
                input_text='{"prompt": "Ship auto archive"}',
            )
            self.assertEqual(prompt.returncode, 0, prompt.stderr)

            summary = self.run_cli(
                db_path,
                "run",
                "set",
                "--summary",
                "Ship auto archive",
                "--json",
            )
            self.assertEqual(summary.returncode, 0, summary.stderr)

            plan = self.run_cli(
                db_path,
                "plan",
                "set",
                "--id",
                "SPEC-001",
                "--title",
                "Auto archive completed run",
                "--summary",
                "Plan a completed request from planning to task execution and archive it automatically.",
                "--requirements-trace",
                "REQ-001: completed run has enough plan detail for Stop hook archive.",
                "--execution-order",
                "Plan, execute task, then archive on Stop.",
                "--risks",
                "Sparse plans should not pass detailed validation.",
                "--validation",
                "Stop hook archives the run.",
                "--json",
            )
            self.assertEqual(plan.returncode, 0, plan.stderr)

            task = self.run_cli(
                db_path,
                "task",
                "set",
                "--id",
                "TASK-001",
                "--title",
                "Complete implementation",
                "--status",
                "Completed",
                "--spec-id",
                "SPEC-001",
                "--goal",
                "Finish the requested implementation.",
                "--verification",
                "Stop hook archives the run.",
                "--result",
                "Implementation and verification are complete.",
                "--json",
            )
            self.assertEqual(task.returncode, 0, task.stderr)

            verification_task = self.run_cli(
                db_path,
                "task",
                "set",
                "--id",
                "TASK-002",
                "--title",
                "Verify implementation",
                "--status",
                "Completed",
                "--spec-id",
                "SPEC-001",
                "--goal",
                "Verify the requested implementation.",
                "--verification",
                "Stop hook archives the run.",
                "--result",
                "Verification is complete.",
                "--json",
            )
            self.assertEqual(verification_task.returncode, 0, verification_task.stderr)

            stopped = self.run_cli(
                db_path,
                "hook-event",
                "--event",
                "Stop",
                "--mode",
                "observe",
                "--json",
                input_text="{}",
            )
            self.assertEqual(stopped.returncode, 0, stopped.stderr)
            payload = json.loads(stopped.stdout)
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["archive"]["slug"], "ship-auto-archive")
            self.assertIn("archived completed run", payload["message"])

            status = self.run_cli(db_path, "status", "--json")
            self.assertEqual(status.returncode, 0, status.stderr)
            status_payload = json.loads(status.stdout)
            self.assertIsNone(status_payload["active_run"])
            self.assertEqual(status_payload["counts"]["archives"], 1)
            self.assertNotIn("archives", status_payload)

            archives = self.run_cli(db_path, "archive", "list", "--json")
            self.assertEqual(archives.returncode, 0, archives.stderr)
            archives_payload = json.loads(archives.stdout)
            self.assertEqual(len(archives_payload["archives"]), 1)
            self.assertEqual(archives_payload["archives"][0]["slug"], "ship-auto-archive")
            self.assertIn("Original request: Ship auto archive", archives_payload["archives"][0]["summary"])
            self.assertIn("Selected plan: SPEC-001 Auto archive completed run", archives_payload["archives"][0]["summary"])
            self.assertIn("Completed tasks: TASK-001 Complete implementation", archives_payload["archives"][0]["summary"])
            self.assertIn("Verification: Stop hook archives the run.", archives_payload["archives"][0]["summary"])
            self.assertIn("Remaining work: None", archives_payload["archives"][0]["summary"])

            detail = self.run_cli(db_path, "archive", "show", "--id", "ship-auto-archive", "--json")
            self.assertEqual(detail.returncode, 0, detail.stderr)
            detail_payload = json.loads(detail.stdout)
            self.assertEqual(detail_payload["archive"]["request_summary"], "Ship auto archive")
            self.assertEqual(
                [(item["kind"], item["stable_id"], item["archived"]) for item in detail_payload["items"]],
                [("plan", "SPEC-001", 1), ("task", "TASK-001", 1), ("task", "TASK-002", 1)],
            )
            self.assertEqual(detail_payload["events"][-1]["event_type"], "Stop")

    def test_stop_hook_keeps_plan_only_run_active(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "tapl.db"
            prompt = self.run_cli(
                db_path,
                "hook-event",
                "--event",
                "UserPromptSubmit",
                "--mode",
                "observe",
                "--json",
                input_text='{"prompt": "Plan only work"}',
            )
            self.assertEqual(prompt.returncode, 0, prompt.stderr)

            summary = self.run_cli(
                db_path,
                "run",
                "set",
                "--summary",
                "Plan only work",
                "--result",
                "Plan was prepared; execution has not started.",
                "--json",
            )
            self.assertEqual(summary.returncode, 0, summary.stderr)

            plan = self.run_cli(
                db_path,
                "plan",
                "set",
                "--id",
                "SPEC-001",
                "--title",
                "Plan only run",
                "--summary",
                "Prepare a plan without executing implementation tasks.",
                "--requirements-trace",
                "REQ-001 documents that only planning happened.",
                "--execution-order",
                "Create plan and wait for explicit user approval before work.",
                "--risks",
                "Archiving now would hide work that still needs execution.",
                "--validation",
                "Stop hook leaves the run active because no task completed.",
                "--json",
            )
            self.assertEqual(plan.returncode, 0, plan.stderr)

            stopped = self.run_cli(
                db_path,
                "hook-event",
                "--event",
                "Stop",
                "--mode",
                "observe",
                "--json",
                input_text="{}",
            )
            self.assertEqual(stopped.returncode, 0, stopped.stderr)
            payload = json.loads(stopped.stdout)
            self.assertTrue(payload["ok"])
            self.assertNotIn("archive", payload)

            status = self.run_cli(db_path, "status", "--json")
            self.assertEqual(status.returncode, 0, status.stderr)
            status_payload = json.loads(status.stdout)
            self.assertIsNotNone(status_payload["active_run"])
            self.assertEqual(status_payload["active_run"]["request_summary"], "Plan only work")
            self.assertEqual(status_payload["counts"]["tasks"], 0)
            self.assertEqual(status_payload["counts"]["archives"], 0)

            next_prompt = self.run_cli(
                db_path,
                "hook-event",
                "--event",
                "UserPromptSubmit",
                "--mode",
                "observe",
                "--json",
                input_text='{"prompt": "Implement a different feature"}',
            )
            self.assertEqual(next_prompt.returncode, 0, next_prompt.stderr)
            next_payload = json.loads(next_prompt.stdout)
            next_actions = "\n".join(next_payload["context"]["next_actions"])
            self.assertIn("get user approval", next_actions)
            self.assertIn("finish existing work first", next_actions)
            self.assertIn("defer the existing run", next_actions)
            self.assertIn("merge the work into one plan", next_actions)

    def test_user_prompt_context_asks_direction_for_stopped_in_progress_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "tapl.db"
            prompt = self.run_cli(
                db_path,
                "hook-event",
                "--event",
                "UserPromptSubmit",
                "--mode",
                "observe",
                "--json",
                input_text='{"prompt": "Original implementation"}',
            )
            self.assertEqual(prompt.returncode, 0, prompt.stderr)

            summary = self.run_cli(db_path, "run", "set", "--summary", "Original implementation", "--json")
            self.assertEqual(summary.returncode, 0, summary.stderr)

            plan = self.run_cli(
                db_path,
                "plan",
                "set",
                "--id",
                "SPEC-001",
                "--title",
                "Original plan",
                "--summary",
                "REQ-001: original implementation plan.",
                "--objective",
                "Finish the original implementation.",
                "--requirements-trace",
                "REQ-001: user asked for the original implementation.",
                "--selected-approach",
                "Execute one implementation task.",
                "--affected-files",
                "tapl/taplctl/context.py",
                "--execution-order",
                "Start and finish TASK-001.",
                "--risks",
                "A later prompt may be unrelated to the active run.",
                "--validation",
                "Context asks for direction.",
                "--json",
            )
            self.assertEqual(plan.returncode, 0, plan.stderr)

            task = self.run_cli(
                db_path,
                "task",
                "set",
                "--id",
                "TASK-001",
                "--title",
                "Implement original task",
                "--status",
                "In Progress",
                "--spec-id",
                "SPEC-001",
                "--goal",
                "Finish the original implementation task.",
                "--action",
                "Continue implementation from the active task.",
                "--verification",
                "Context asks for direction before new durable edits.",
                "--json",
            )
            self.assertEqual(task.returncode, 0, task.stderr)

            next_prompt = self.run_cli(
                db_path,
                "hook-event",
                "--event",
                "UserPromptSubmit",
                "--mode",
                "observe",
                "--json",
                input_text='{"prompt": "Implement a different feature"}',
            )
            self.assertEqual(next_prompt.returncode, 0, next_prompt.stderr)
            next_payload = json.loads(next_prompt.stdout)
            next_actions = "\n".join(next_payload["context"]["next_actions"])
            self.assertIn("Run stopped during task execution", next_actions)
            self.assertIn("continue execution from TASK-001", next_actions)
            self.assertIn("defer the existing run and archive it", next_actions)
            self.assertIn("merge the work into one plan", next_actions)
            self.assertIn("get user approval", next_actions)

    def test_stop_hook_auto_archives_simple_result_run_without_items(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "tapl.db"
            prompt = self.run_cli(
                db_path,
                "hook-event",
                "--event",
                "UserPromptSubmit",
                "--mode",
                "observe",
                "--json",
                input_text='{"prompt": "Answer a simple question"}',
            )
            self.assertEqual(prompt.returncode, 0, prompt.stderr)

            summary = self.run_cli(
                db_path,
                "run",
                "set",
                "--summary",
                "Answer a simple question",
                "--json",
            )
            self.assertEqual(summary.returncode, 0, summary.stderr)

            result = self.run_cli(
                db_path,
                "run",
                "set",
                "--result",
                "Answered directly without creating plan or task records.",
                "--json",
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            result_payload = json.loads(result.stdout)
            self.assertEqual(
                result_payload["active_run"]["result_summary"],
                "Answered directly without creating plan or task records.",
            )

            stopped = self.run_cli(
                db_path,
                "hook-event",
                "--event",
                "Stop",
                "--mode",
                "observe",
                "--json",
                input_text="{}",
            )
            self.assertEqual(stopped.returncode, 0, stopped.stderr)
            payload = json.loads(stopped.stdout)
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["archive"]["slug"], "answer-a-simple-question")
            self.assertIn("archived completed run", payload["message"])

            archives = self.run_cli(db_path, "archive", "list", "--json")
            self.assertEqual(archives.returncode, 0, archives.stderr)
            archives_payload = json.loads(archives.stdout)
            self.assertEqual(len(archives_payload["archives"]), 1)
            self.assertIn("Original request: Answer a simple question", archives_payload["archives"][0]["summary"])
            self.assertIn(
                "Result: Answered directly without creating plan or task records.",
                archives_payload["archives"][0]["summary"],
            )
            self.assertIn("Selected plan: None", archives_payload["archives"][0]["summary"])
            self.assertIn("Completed tasks: None", archives_payload["archives"][0]["summary"])

            detail = self.run_cli(db_path, "archive", "show", "--id", "answer-a-simple-question", "--json")
            self.assertEqual(detail.returncode, 0, detail.stderr)
            detail_payload = json.loads(detail.stdout)
            self.assertEqual(detail_payload["items"], [])
            self.assertEqual(detail_payload["archive"]["request_summary"], "Answer a simple question")
            self.assertEqual(
                detail_payload["archive"]["result_summary"],
                "Answered directly without creating plan or task records.",
            )

    def test_hook_event_uses_payload_cwd_for_repo_db(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            workspace = base / "workspace"
            outside = base / "outside"
            home = base / "home"
            workspace.mkdir()
            outside.mkdir()
            home.mkdir()
            (workspace / ".tapl").mkdir()
            (workspace / ".tapl" / "version").write_text("0.0.0\n", encoding="utf-8")

            event = self.run_taplctl(
                "hook-event",
                "--event",
                "UserPromptSubmit",
                "--mode",
                "observe",
                "--json",
                input_text=json.dumps({"cwd": str(workspace), "prompt": "Global install workspace"}),
                cwd=outside,
                env_overrides={"HOME": str(home)},
            )
            self.assertEqual(event.returncode, 0, event.stderr)
            payload = json.loads(event.stdout)
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["context"]["prompt_summary"], "Global install workspace")
            self.assertEqual(
                payload["context"]["active_run"]["request_summary"],
                "New request",
            )
            self.assertEqual(payload["workspace"]["workspace_root"], str(workspace.resolve()))
            self.assertTrue((workspace / ".tapl" / "tapl.db").exists())
            self.assertNotIn("workspace_marker", payload["workspace"])
            self.assertNotIn("workspace_marker_action", payload["workspace"])
            self.assertEqual(
                (workspace / ".tapl" / "version").read_text(encoding="utf-8").strip(),
                __version__,
            )
            self.assertTrue((workspace / ".codex" / "hooks.json").exists())
            self.assertFalse((outside / ".tapl").exists())
            self.assertFalse((outside / ".codex").exists())

    def test_hook_workspace_bootstrap_keeps_nested_git_on_one_db(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            workspace = base / "workspace"
            child_repo = workspace / "services" / "child"
            outside = base / "outside"
            home = base / "home"
            (workspace / ".git").mkdir(parents=True)
            (child_repo / ".git").mkdir(parents=True)
            outside.mkdir()
            home.mkdir()
            env = {"HOME": str(home)}

            initialized = self.run_taplctl(
                "hook-event",
                "--event",
                "UserPromptSubmit",
                "--mode",
                "observe",
                "--json",
                input_text=json.dumps({"cwd": str(workspace), "prompt": "Initialize workspace"}),
                cwd=outside,
                env_overrides=env,
            )
            self.assertEqual(initialized.returncode, 0, initialized.stderr)
            initialized_payload = json.loads(initialized.stdout)
            self.assertEqual(initialized_payload["workspace"]["db_action"], "created")

            nested_event = self.run_taplctl(
                "hook-event",
                "--event",
                "UserPromptSubmit",
                "--mode",
                "observe",
                "--json",
                input_text=json.dumps({"cwd": str(child_repo), "prompt": "Continue nested work"}),
                cwd=outside,
                env_overrides=env,
            )
            self.assertEqual(nested_event.returncode, 0, nested_event.stderr)
            nested_payload = json.loads(nested_event.stdout)
            self.assertEqual(nested_payload["workspace"]["workspace_root"], str(workspace.resolve()))
            self.assertEqual(nested_payload["workspace"]["db_action"], "unchanged")
            self.assertFalse((child_repo / ".tapl").exists())

            nested_init = self.run_taplctl("init", "--json", cwd=child_repo, env_overrides=env)
            self.assertEqual(nested_init.returncode, 0, nested_init.stderr)
            self.assertEqual(
                json.loads(nested_init.stdout)["db"],
                str(workspace.resolve() / tapl_db.DEFAULT_DB_RELATIVE),
            )

    def test_hook_explicit_db_bypasses_workspace_bootstrap(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            workspace = base / "workspace"
            explicit_db = base / "explicit.db"
            workspace.mkdir()

            event = self.run_cli(
                explicit_db,
                "hook-event",
                "--event",
                "UserPromptSubmit",
                "--mode",
                "observe",
                "--json",
                input_text=json.dumps({"cwd": str(workspace), "prompt": "Use explicit database"}),
            )
            self.assertEqual(event.returncode, 0, event.stderr)
            self.assertTrue(explicit_db.exists())
            self.assertFalse((workspace / ".tapl").exists())
            self.assertNotIn("workspace", json.loads(event.stdout))

    def test_archive_show_includes_items_and_events(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "tapl.db"
            self.run_cli(db_path, "init", "--json")

            plan = self.run_cli(
                db_path,
                "plan",
                "set",
                "--id",
                "SPEC-001",
                "--title",
                "Archive detail",
                "--summary",
                "Show archived workflow records",
                "--json",
            )
            self.assertEqual(plan.returncode, 0, plan.stderr)

            task = self.run_cli(
                db_path,
                "task",
                "set",
                "--id",
                "TASK-001",
                "--title",
                "Render archive detail",
                "--status",
                "Completed",
                "--goal",
                "Show plan and task history",
                "--json",
            )
            self.assertEqual(task.returncode, 0, task.stderr)

            finding = self.run_cli(
                db_path,
                "finding",
                "add",
                "--title",
                "Archive source",
                "--finding",
                "Archived items remain tied to their workflow run.",
                "--json",
            )
            self.assertEqual(finding.returncode, 0, finding.stderr)

            event = self.run_cli(
                db_path,
                "hook-event",
                "--event",
                "PreToolUse",
                "--mode",
                "observe",
                "--tool",
                "Bash",
                input_text='{"tool_name": "Bash"}',
            )
            self.assertEqual(event.returncode, 0, event.stderr)

            archive = self.run_cli(
                db_path,
                "archive",
                "create",
                "--slug",
                "archive-detail",
                "--summary",
                "Archived detail test",
                "--json",
            )
            self.assertEqual(archive.returncode, 0, archive.stderr)
            archive_id = json.loads(archive.stdout)["archive"]["id"]

            detail = self.run_cli(db_path, "archive", "show", "--id", archive_id, "--json")
            self.assertEqual(detail.returncode, 0, detail.stderr)
            payload = json.loads(detail.stdout)
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["archive"]["slug"], "archive-detail")
            self.assertEqual(
                [(item["kind"], item["stable_id"]) for item in payload["items"]],
                [("plan", "SPEC-001"), ("task", "TASK-001"), ("finding", "FINDING-001")],
            )
            self.assertEqual(payload["events"][0]["event_type"], "PreToolUse")
            self.assertNotIn("payload_json", payload["events"][0])

    def test_import_md_restructures_legacy_archive_as_tapl_records(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "tapl.db"
            workflow = Path(tmp) / ".agent-workflow"
            archive = workflow / "archive" / "20260605-144508-vscode-workflow-viewer"
            archive.mkdir(parents=True)
            (archive / "summary.md").write_text(
                """# Archive Summary

## Original Request
VSCode workflow viewer를 만든다.

## Selected Plan
VSCode 확장을 추가하고 markdown preview를 연결한다.
""",
                encoding="utf-8",
            )
            (archive / "plan.md").write_text(
                """# Plan

## Specs
- SPEC-001: VSCode extension scaffold를 추가한다. (REQ-001)
  - Goal: 확장 기본 구조를 만든다.
  - Validation: `npm run compile`
""",
                encoding="utf-8",
            )
            (archive / "task.md").write_text(
                """# Tasks

## Phase 1: Extension scaffold

- TASK-001 [Completed]: VSCode extension 기본 구조 추가 (SPEC-001)
  - Action: TypeScript extension scaffold를 추가한다.
  - Required Subagent: [@senior-worker](subagent://senior-worker)
  - Verification: `npm run compile`
  - Result: 확장 기본 구조를 추가했다.

## Phase 2: Verification

- TASK-002 [Completed]: Compile 확인 (SPEC-001)
  - Action: compile command를 실행한다.
  - Verification: `npm run compile`
  - Result: 컴파일이 성공했다.
""",
                encoding="utf-8",
            )
            (archive / "finding.md").write_text(
                """# Findings

- FINDING-001: VSCode compile 확인 (REQ-001, SPEC-001)
  - Source: npm
  - Finding: compile command가 성공한다.
  - Impact: import 후 검증 근거로 남긴다.
""",
                encoding="utf-8",
            )

            imported = self.run_cli(db_path, "import-md", "--path", str(workflow), "--json")
            self.assertEqual(imported.returncode, 0, imported.stderr)
            imported_payload = json.loads(imported.stdout)
            self.assertEqual(imported_payload["filesystem_created_archives"], 1)
            self.assertEqual(imported_payload["filesystem_created_plan_items"], 1)
            self.assertEqual(imported_payload["filesystem_created_task_items"], 2)
            self.assertEqual(imported_payload["filesystem_created_finding_items"], 1)

            detail = self.run_cli(
                db_path,
                "archive",
                "show",
                "--id",
                "2026-06-05T144508Z-vscode-workflow-viewer",
                "--json",
            )
            self.assertEqual(detail.returncode, 0, detail.stderr)
            payload = json.loads(detail.stdout)
            self.assertEqual(payload["archive"]["request_summary"], "VSCode workflow viewer를 만든다.")
            self.assertEqual(
                [(item["kind"], item["stable_id"]) for item in payload["items"]],
                [("plan", "SPEC-001"), ("task", "TASK-001"), ("task", "TASK-002"), ("finding", "FINDING-001")],
            )
            plan = next(item for item in payload["items"] if item["stable_id"] == "SPEC-001")
            self.assertEqual(plan["requirements_trace"], "REQ-001")
            self.assertEqual(plan["objective"], "확장 기본 구조를 만든다.")
            self.assertEqual(plan["validation"], "`npm run compile`")
            self.assertIn("### Objective\n확장 기본 구조를 만든다.", plan["body"])
            task = next(item for item in payload["items"] if item["stable_id"] == "TASK-001")
            self.assertEqual(task["status"], "Completed")
            self.assertEqual(task["spec_id"], "SPEC-001")
            self.assertNotIn("required_subagent", task)
            self.assertIn("### Action\nTypeScript extension scaffold를 추가한다.", task["body"])
            self.assertNotIn("Phase 2", task["result"])

    def test_import_md_migrates_existing_raw_legacy_imports(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "tapl.db"
            init = self.run_cli(db_path, "init", "--json")
            self.assertEqual(init.returncode, 0, init.stderr)

            conn = sqlite3.connect(db_path)
            now = "2026-06-15T07:41:03+00:00"
            run_id = "legacy-run"
            conn.execute(
                """
                INSERT INTO workflow_runs(id, slug, status, request_summary, created_at, updated_at, archived_at)
                VALUES(?, 'legacy-markdown-import', 'archived', '', ?, ?, ?)
                """,
                (run_id, now, now, now),
            )
            conn.execute(
                "INSERT INTO archives(id, run_id, slug, summary, created_at) VALUES(?, ?, ?, ?, ?)",
                (
                    "2026-06-15T074103Z-legacy-markdown-import",
                    run_id,
                    "legacy-markdown-import",
                    "old raw import",
                    now,
                ),
            )
            legacy_files = {
                "archive/20260605-144508-vscode-workflow-viewer/summary.md": """# Archive Summary

## Original Request
Legacy archive를 tapl 구조로 옮긴다.

## Selected Plan
계획과 작업을 tapl item으로 재구성한다.
""",
                "archive/20260605-144508-vscode-workflow-viewer/plan.md": """# Plan

## Specs
- SPEC-001: Legacy plan 변환 (REQ-001)
  - Goal: plan file을 SPEC item으로 만든다.
""",
                "archive/20260605-144508-vscode-workflow-viewer/task.md": """# Tasks

- TASK-001 [Completed]: Legacy task 변환 (SPEC-001)
  - Goal: task row를 만든다.
  - Action: task.md 항목을 파싱한다.
  - Verification: archive show
  - Result: 완료
""",
            }
            for index, (source, text) in enumerate(legacy_files.items(), start=1):
                conn.execute(
                    """
                    INSERT INTO items(
                      run_id, stable_id, kind, title, body, raw_text, status, source, archived, created_at, updated_at
                    )
                    VALUES(?, ?, ?, ?, ?, ?, NULL, ?, 1, ?, ?)
                    """,
                    (
                        run_id,
                        f"MD-{index:012d}",
                        Path(source).stem,
                        Path(source).name,
                        text,
                        text,
                        source,
                        now,
                        now,
                    ),
                )
            conn.commit()
            conn.close()

            migrated = self.run_cli(
                db_path,
                "import-md",
                "--path",
                str(Path(tmp) / "missing-agent-workflow"),
                "--migrate-existing",
                "--json",
            )
            self.assertEqual(migrated.returncode, 0, migrated.stderr)
            migrated_payload = json.loads(migrated.stdout)
            self.assertEqual(migrated_payload["existing_legacy_runs"], 1)
            self.assertEqual(migrated_payload["existing_removed_legacy_runs"], 1)
            self.assertEqual(migrated_payload["existing_created_archives"], 1)
            self.assertEqual(migrated_payload["existing_created_task_items"], 1)

            detail = self.run_cli(
                db_path,
                "archive",
                "show",
                "--id",
                "2026-06-05T144508Z-vscode-workflow-viewer",
                "--json",
            )
            self.assertEqual(detail.returncode, 0, detail.stderr)
            payload = json.loads(detail.stdout)
            self.assertEqual(
                [(item["kind"], item["stable_id"]) for item in payload["items"]],
                [("plan", "SPEC-001"), ("task", "TASK-001")],
            )

            conn = sqlite3.connect(db_path)
            md_items = conn.execute("SELECT COUNT(*) FROM items WHERE stable_id LIKE 'MD-%'").fetchone()[0]
            old_runs = conn.execute(
                "SELECT COUNT(*) FROM workflow_runs WHERE slug = 'legacy-markdown-import'"
            ).fetchone()[0]
            conn.close()
            self.assertEqual(md_items, 0)
            self.assertEqual(old_runs, 0)

    def test_schema_v8_migrates_parallel_and_workflow_mode_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "tapl.db"
            initialized = self.run_cli(db_path, "init", "--json")
            self.assertEqual(initialized.returncode, 0, initialized.stderr)
            with sqlite3.connect(db_path) as conn:
                conn.execute("UPDATE meta SET value = '6' WHERE key = 'schema_version'")
                conn.commit()

            self.create_parallel_fixture(db_path, task_ids=("TASK-001", "TASK-002"), owned_paths=("src/a.py", "src/b.py"))
            with sqlite3.connect(db_path) as conn:
                version = conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()[0]
                tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
                task_columns = {row[1] for row in conn.execute("PRAGMA table_info(tasks)")}
                conn.commit()
            self.assertEqual(version, str(tapl_db.SCHEMA_VERSION))
            self.assertTrue({"task_dependencies", "execution_batches", "task_executions"} <= tables)
            self.assertTrue({"execution_mode", "executor_kind", "parallel_group", "owned_paths_json"} <= task_columns)
            payload = self.status_json(db_path)
            self.assertEqual(payload["active_run"]["workflow_mode"], "planned")  # type: ignore[index]
            tasks = {task["stable_id"]: task for task in payload["tasks"]}  # type: ignore[index]
            self.assertEqual(tasks["TASK-001"]["execution_mode"], "parallel")
            self.assertEqual(tasks["TASK-001"]["owned_paths"], ["src/a.py"])
            with sqlite3.connect(db_path) as conn:
                workflow_columns = {
                    row[1] for row in conn.execute("PRAGMA table_info(workflow_runs)")
                }
                conn.execute(
                    "UPDATE meta SET value = ? WHERE key = 'schema_version'",
                    (str(tapl_db.SCHEMA_VERSION + 1),),
                )
                conn.commit()
            self.assertIn("workflow_mode", workflow_columns)
            with self.assertRaisesRegex(RuntimeError, "newer than supported"):
                tapl_db.connect(db_path)

    def test_parallel_dispatch_manifest_is_idempotent_and_settlement_requires_exact_execution(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "tapl.db"
            task_ids = ("TASK-001", "TASK-002", "TASK-003")
            self.create_parallel_fixture(db_path)
            metadata = {
                "TASK-001": {"executor_ref": "agent-a", "model": "gpt-5.6-terra", "reasoning_effort": "high"},
                "TASK-002": {"executor_ref": "agent-b"},
            }
            dispatched = self.run_cli(
                db_path, "task", "dispatch", *task_ids, "--batch-id", "BATCH-001",
                "--execution-metadata", json.dumps(metadata), "--json",
            )
            self.assertEqual(dispatched.returncode, 0, dispatched.stderr)
            manifest = json.loads(dispatched.stdout)
            self.assertEqual(manifest["batch"]["batch_id"], "BATCH-001")
            executions = {row["task_id"]: row for row in manifest["executions"]}
            self.assertEqual(set(executions), set(task_ids))
            self.assertEqual(executions["TASK-001"]["model"], "gpt-5.6-terra")

            repeated = self.run_cli(db_path, "task", "dispatch", *task_ids, "--batch-id", "BATCH-001", "--json")
            self.assertEqual(repeated.returncode, 0, repeated.stderr)
            repeated_ids = {row["task_id"]: row["execution_id"] for row in json.loads(repeated.stdout)["executions"]}
            self.assertEqual(repeated_ids, {task_id: row["execution_id"] for task_id, row in executions.items()})

            validation = self.run_cli(db_path, "validate", "--json")
            self.assertEqual(validation.returncode, 0, validation.stdout)
            validation_payload = json.loads(validation.stdout)
            validation_codes = {
                issue["code"] for issue in validation_payload["plan_task_execute"]["warnings"]
            }
            self.assertNotIn("multiple_tasks_in_progress", validation_codes)
            self.assertNotIn("mixed_in_progress_execution_state", validation_codes)
            context = self.run_cli(db_path, "context", "--json")
            self.assertEqual(context.returncode, 0, context.stderr)
            context_payload = json.loads(context.stdout)
            self.assertEqual(len(context_payload["active_executions"]), 3)
            self.assertIn("BATCH-001", "\n".join(context_payload["next_actions"]))
            agent_status = self.run_cli(db_path, "status", "--agent")
            self.assertEqual(agent_status.returncode, 0, agent_status.stderr)
            self.assertIn("<active_batches>", agent_status.stdout)
            self.assertIn("<active_executions>", agent_status.stdout)

            missing = self.run_cli(db_path, "task", "complete", "TASK-001", "--result", "done", "--json")
            self.assertNotEqual(missing.returncode, 0)
            mismatched = self.run_cli(
                db_path, "task", "complete", "TASK-001", "--execution-id", executions["TASK-002"]["execution_id"],
                "--result", "done", "--json",
            )
            self.assertNotEqual(mismatched.returncode, 0)

            completed = self.run_cli(
                db_path, "task", "complete", "TASK-001", "--execution-id", executions["TASK-001"]["execution_id"],
                "--verification", "Focused checks passed", "--result", "done",
                "--custom-fields", json.dumps({"SubAgent Model": "gpt-5.6-terra (high)"}), "--json",
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            blocked = self.run_cli(
                db_path, "task", "block", "TASK-002", "--execution-id", executions["TASK-002"]["execution_id"],
                "--blocker", "dependency failed", "--next-action", "retry", "--json",
            )
            self.assertEqual(blocked.returncode, 0, blocked.stderr)
            skipped = self.run_cli(
                db_path, "task", "skip", "TASK-003", "--execution-id", executions["TASK-003"]["execution_id"],
                "--result", "not needed", "--json",
            )
            self.assertEqual(skipped.returncode, 0, skipped.stderr)
            stale = self.run_cli(
                db_path, "task", "complete", "TASK-001", "--execution-id", executions["TASK-001"]["execution_id"],
                "--result", "again", "--json",
            )
            self.assertNotEqual(stale.returncode, 0)
            payload = self.status_json(db_path)
            tasks = {task["stable_id"]: task for task in payload["tasks"]}  # type: ignore[index]
            self.assertEqual(tasks["TASK-001"]["status"], "Completed")
            self.assertEqual(tasks["TASK-001"]["verification"], "Focused checks passed")
            self.assertEqual(tasks["TASK-001"]["custom_fields"]["SubAgent Model"], "gpt-5.6-terra (high)")
            self.assertEqual(tasks["TASK-002"]["status"], "Blocked")
            self.assertEqual(tasks["TASK-003"]["status"], "Skipped")
            self.assertEqual(payload["active_batches"], [])

    def test_parallel_dispatch_validation_is_atomic_for_dependencies_contracts_and_paths(self) -> None:
        cases = (
            ("dependency", {"TASK-001": ["TASK-003"]}, ("src/a.py", "src/b.py", "src/c.py"), {}),
            ("contract", {}, ("src/a.py", "src/b.py", "src/c.py"), {"TASK-002": "main"}),
            ("paths", {}, ("src/shared", "src/shared/file.py", "src/c.py"), {}),
        )
        with tempfile.TemporaryDirectory() as tmp:
            for name, dependencies, paths, executors in cases:
                db_path = Path(tmp) / f"{name}.db"
                self.create_parallel_fixture(
                    db_path, dependencies=dependencies, owned_paths=paths, executor_kinds=executors
                )
                invalid = self.run_cli(
                    db_path, "task", "dispatch", "TASK-001", "TASK-002", "--batch-id", f"BATCH-{name}", "--json"
                )
                self.assertNotEqual(invalid.returncode, 0, invalid.stdout)
                state = self.status_json(db_path)
                self.assertEqual(state["active_batches"], [])
                self.assertEqual(state["active_executions"], [])
                self.assertEqual({task["status"] for task in state["tasks"]}, {"Pending"})  # type: ignore[index]

    def test_parallel_dispatch_claim_cancel_and_active_run_guards(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "tapl.db"
            task_ids = ("TASK-001", "TASK-002")
            self.create_parallel_fixture(db_path, task_ids=task_ids, owned_paths=("src/a.py", "src/b.py"))

            def claim(batch_id: str) -> str:
                conn = tapl_db.connect(db_path)
                try:
                    tapl_db.dispatch_tasks(conn, task_ids, batch_id=batch_id)
                    return "success"
                except ValueError:
                    return "rejected"
                finally:
                    conn.close()

            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
                outcomes = list(executor.map(claim, ("BATCH-A", "BATCH-B")))
            self.assertEqual(outcomes.count("success"), 1)
            self.assertEqual(outcomes.count("rejected"), 1)
            state = self.status_json(db_path)
            batch_id = state["active_batches"][0]["batch"]["batch_id"]  # type: ignore[index]
            self.assertEqual(len(state["active_executions"]), 2)

            finish = self.run_cli(db_path, "run", "finish", "--result", "premature", "--json")
            archive = self.run_cli(db_path, "archive", "finish", "--slug", "premature", "--json")
            stop = self.run_cli(
                db_path, "hook-event", "--event", "Stop", "--mode", "enforce", "--json", input_text="{}"
            )
            self.assertNotEqual(finish.returncode, 0)
            self.assertNotEqual(archive.returncode, 0)
            self.assertNotEqual(stop.returncode, 0)

            recovered = self.run_cli(db_path, "batch", "recover", batch_id, "--reason", "interrupted", "--json")
            self.assertEqual(recovered.returncode, 0, recovered.stderr)
            state = self.status_json(db_path)
            recovered_tasks = {
                task["stable_id"]: task for task in state["tasks"]  # type: ignore[index]
            }
            self.assertEqual({task["status"] for task in recovered_tasks.values()}, {"Pending"})
            self.assertTrue(
                all(task["blocker"] == "" for task in recovered_tasks.values())
            )
            self.assertTrue(
                all(task["next_action"] == "" for task in recovered_tasks.values())
            )

            preserved_next_action = "Re-check the existing task-specific recovery steps."
            updated = self.run_cli(
                db_path,
                "task",
                "set",
                "--id",
                "TASK-001",
                "--next-action",
                preserved_next_action,
                "--json",
            )
            self.assertEqual(updated.returncode, 0, updated.stderr)
            dispatched = self.run_cli(db_path, "task", "dispatch", *task_ids, "--batch-id", "BATCH-C", "--json")
            self.assertEqual(dispatched.returncode, 0, dispatched.stderr)
            cancelled = self.run_cli(db_path, "batch", "cancel", "BATCH-C", "--block", "--reason", "halt", "--json")
            self.assertEqual(cancelled.returncode, 0, cancelled.stderr)
            state = self.status_json(db_path)
            blocked_tasks = {
                task["stable_id"]: task for task in state["tasks"]  # type: ignore[index]
            }
            self.assertEqual({task["status"] for task in blocked_tasks.values()}, {"Blocked"})
            self.assertTrue(
                all(task["blocker"] for task in blocked_tasks.values())
            )
            self.assertTrue(
                all(task["next_action"] for task in blocked_tasks.values())
            )
            self.assertEqual(
                blocked_tasks["TASK-001"]["next_action"],
                preserved_next_action,
            )
            for task in blocked_tasks.values():
                self.assertIn("### Blocker\n", task["body"])
                self.assertIn("### Next action\n", task["body"])

            validated = self.run_cli(db_path, "validate", "--json")
            self.assertEqual(validated.returncode, 0, validated.stdout)
            warnings = json.loads(validated.stdout)["plan_task_execute"]["warnings"]
            missing_content = [
                warning
                for warning in warnings
                if warning["code"] == "task_content_missing_fields"
                and warning.get("stable_id") in task_ids
            ]
            self.assertEqual(missing_content, [])


class TaplUpdaterTests(unittest.TestCase):
    """Self-update contracts for managed Linux ``curl | sh`` installations."""

    manifest_url = "https://updates.example.test/taplctl-install-manifest.json"
    wheel_url = "https://updates.example.test/taplctl-1.1.0-py3-none-any.whl"

    def create_curl_sh_fixture(self, base: Path, *, version: str = "1.0.0") -> dict[str, Path | str]:
        install_root = base / "tapl"
        versions_dir = install_root / "versions"
        venv = versions_dir / f"taplctl-{version}"
        bin_dir = base / "bin"
        command = venv / "bin" / "taplctl"
        python = venv / "bin" / "python"
        executable = bin_dir / "taplctl"
        metadata_path = install_root / "install.json"
        command.parent.mkdir(parents=True)
        bin_dir.mkdir(parents=True)
        command.write_text("#!/bin/sh\n", encoding="utf-8")
        command.chmod(0o755)
        python.write_text("#!/bin/sh\n", encoding="utf-8")
        python.chmod(0o755)
        executable.symlink_to(command)
        metadata = {
            "schema_version": 1,
            "method": "curl-sh",
            "manifest_url": self.manifest_url,
            "version": version,
            "wheel_url": self.wheel_url,
            "wheel_sha256": "0" * 64,
            "install_root": str(install_root),
            "bin_dir": str(bin_dir),
            "venv": str(venv),
            "executable": str(executable),
            "installed_at": "2026-08-03T00:00:00Z",
        }
        metadata_path.write_text(json.dumps(metadata) + "\n", encoding="utf-8")
        return {
            "install_root": install_root,
            "versions_dir": versions_dir,
            "venv": venv,
            "bin_dir": bin_dir,
            "command": command,
            "python": python,
            "executable": executable,
            "metadata_path": metadata_path,
        }

    def updater_kwargs(self, fixture: dict[str, Path | str], *, opener: object) -> dict[str, object]:
        return {
            "metadata_path": fixture["metadata_path"],
            "current_prefix": fixture["venv"],
            "current_python": fixture["python"],
            "opener": opener,
        }

    def manifest(self, version: str, wheel: bytes, *, wheel_url: str | None = None) -> bytes:
        return json.dumps(
            {
                "schema_version": 1,
                "version": version,
                "wheel": {
                    "url": wheel_url or self.wheel_url,
                    "sha256": hashlib.sha256(wheel).hexdigest(),
                },
            }
        ).encode("utf-8")

    @staticmethod
    def set_fixture_urls(
        fixture: dict[str, Path | str],
        *,
        manifest_url: str,
        wheel_url: str,
    ) -> None:
        metadata_path = fixture["metadata_path"]
        assert isinstance(metadata_path, Path)
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        metadata["manifest_url"] = manifest_url
        metadata["wheel_url"] = wheel_url
        metadata_path.write_text(json.dumps(metadata) + "\n", encoding="utf-8")

    @staticmethod
    def opener(responses: dict[str, bytes]) -> object:
        def open_url(url: str) -> io.BytesIO:
            return io.BytesIO(responses[url])

        return open_url

    @staticmethod
    def resolved_target(path: Path) -> Path:
        return Path(os.path.realpath(path))

    def candidate_runner(self, *, version: str, fail_at: str | None = None) -> object:
        def run(args: list[str], **_: object) -> types.SimpleNamespace:
            if args[1:3] == ["-m", "venv"]:
                candidate = Path(args[-1])
                if fail_at == "venv":
                    return types.SimpleNamespace(returncode=1, stdout="", stderr="venv failed")
                candidate_bin = candidate / "bin"
                candidate_bin.mkdir(parents=True, exist_ok=True)
                for name in ("python", "taplctl"):
                    command = candidate_bin / name
                    command.write_text("#!/bin/sh\n", encoding="utf-8")
                    command.chmod(0o755)
                return types.SimpleNamespace(returncode=0, stdout="", stderr="")
            if args[1:3] == ["-m", "pip"]:
                return types.SimpleNamespace(
                    returncode=1 if fail_at == "pip" else 0,
                    stdout="",
                    stderr="pip failed" if fail_at == "pip" else "",
                )
            if args[-1] == "--version":
                return types.SimpleNamespace(returncode=0, stdout=f"taplctl {version}\n", stderr="")
            self.fail(f"unexpected candidate command: {args}")

        return run

    def test_check_for_update_reports_available_current_and_newer_versions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = self.create_curl_sh_fixture(Path(tmp))
            for latest, expected_status, expected_available in (
                ("1.1.0", "update-available", True),
                ("1.0.0", "up-to-date", False),
                ("0.9.0", "current-newer", False),
            ):
                with self.subTest(latest=latest):
                    wheel = b"release wheel"
                    payload = tapl_updater.check_for_update(
                        **self.updater_kwargs(
                            fixture,
                            opener=self.opener(
                                {self.manifest_url: self.manifest(latest, wheel)}
                            ),
                        )
                    )
                    self.assertTrue(payload["ok"])
                    self.assertEqual(payload["action"], "check")
                    self.assertEqual(payload["status"], expected_status)
                    self.assertEqual(payload["current_version"], "1.0.0")
                    self.assertEqual(payload["latest_version"], latest)
                    self.assertEqual(payload["update_available"], expected_available)

    def test_check_for_update_redacts_tokenized_urls_without_changing_metadata(self) -> None:
        manifest_url = (
            "https://alice:p4ssword@updates.example.test/releases/manifest.json"
            "?access_token=qsecret#fragsecret"
        )
        wheel_url = (
            "https://bob:wpass@cdn.example.test:8443/artifacts/taplctl-1.1.0.whl"
            "?access_token=wsecret#wfrag"
        )
        with tempfile.TemporaryDirectory() as tmp:
            fixture = self.create_curl_sh_fixture(Path(tmp))
            self.set_fixture_urls(
                fixture,
                manifest_url=manifest_url,
                wheel_url=wheel_url,
            )
            metadata_path = fixture["metadata_path"]
            self.assertIsInstance(metadata_path, Path)
            original_metadata = metadata_path.read_bytes()
            wheel = b"release wheel"
            payload = tapl_updater.check_for_update(
                **self.updater_kwargs(
                    fixture,
                    opener=self.opener(
                        {
                            manifest_url: self.manifest(
                                "1.1.0",
                                wheel,
                                wheel_url=wheel_url,
                            )
                        }
                    ),
                )
            )

            self.assertEqual(
                payload["manifest_url"],
                "https://updates.example.test/releases/manifest.json",
            )
            self.assertEqual(
                payload["wheel_url"],
                "https://cdn.example.test:8443/artifacts/taplctl-1.1.0.whl",
            )
            self.assertEqual(metadata_path.read_bytes(), original_metadata)
            rendered = json.dumps(payload, sort_keys=True)
            for secret in (
                "alice",
                "p4ssword",
                "access_token",
                "qsecret",
                "fragsecret",
                "bob",
                "wpass",
                "wsecret",
                "wfrag",
            ):
                self.assertNotIn(secret, rendered)

    def test_tokenized_manifest_and_download_errors_expose_only_safe_urls(self) -> None:
        manifest_url = (
            "https://alice:p4ssword@updates.example.test/releases/manifest.json"
            "?access_token=qsecret#fragsecret"
        )
        wheel_url = (
            "https://bob:wpass@cdn.example.test/artifacts/taplctl-1.1.0.whl"
            "?access_token=wsecret#wfrag"
        )
        secrets = (
            "alice",
            "p4ssword",
            "access_token",
            "qsecret",
            "fragsecret",
            "bob",
            "wpass",
            "wsecret",
            "wfrag",
        )
        with tempfile.TemporaryDirectory() as tmp:
            fixture = self.create_curl_sh_fixture(Path(tmp))
            self.set_fixture_urls(
                fixture,
                manifest_url=manifest_url,
                wheel_url=wheel_url,
            )

            with self.assertRaises(tapl_updater.UpdateError) as invalid_manifest:
                tapl_updater.check_for_update(
                    **self.updater_kwargs(
                        fixture,
                        opener=self.opener({manifest_url: b'{"schema_version": 1}'}),
                    )
                )
            invalid_payload = invalid_manifest.exception.as_dict()
            self.assertEqual(invalid_manifest.exception.code, "invalid_manifest")
            self.assertEqual(
                invalid_payload["error"]["details"]["manifest_url"],
                "https://updates.example.test/releases/manifest.json",
            )

            malformed_url = "not a valid URL?access_token=malformed-secret#bad-fragment"
            malformed_fixture = self.create_curl_sh_fixture(Path(tmp) / "malformed-url")
            self.set_fixture_urls(
                malformed_fixture,
                manifest_url=malformed_url,
                wheel_url=wheel_url,
            )

            def malformed_opener(url: str) -> io.BytesIO:
                raise OSError(f"network failure while requesting {url}")

            with self.assertRaises(tapl_updater.UpdateError) as malformed_download:
                tapl_updater.check_for_update(
                    **self.updater_kwargs(malformed_fixture, opener=malformed_opener)
                )
            malformed_payload = malformed_download.exception.as_dict()
            self.assertEqual(
                malformed_payload["error"]["details"]["url"],
                "<invalid-url>",
            )
            self.assertNotIn("malformed-secret", json.dumps(malformed_payload))
            self.assertNotIn("bad-fragment", str(malformed_download.exception))

            wheel = b"release wheel"

            def failing_opener(url: str) -> io.BytesIO:
                if url == manifest_url:
                    return io.BytesIO(
                        self.manifest("1.1.0", wheel, wheel_url=wheel_url)
                    )
                raise OSError(f"network failure while requesting {url}")

            with self.assertRaises(tapl_updater.UpdateError) as download_error:
                tapl_updater.update_installation(
                    **self.updater_kwargs(fixture, opener=failing_opener),
                    runner=self.candidate_runner(version="1.1.0"),
                )
            download_payload = download_error.exception.as_dict()
            self.assertEqual(download_error.exception.code, "download_failed")
            self.assertEqual(
                download_payload["error"]["details"]["url"],
                "https://cdn.example.test/artifacts/taplctl-1.1.0.whl",
            )

            rendered = json.dumps(
                [invalid_payload, download_payload],
                sort_keys=True,
            ) + str(invalid_manifest.exception) + str(download_error.exception)
            for secret in secrets:
                self.assertNotIn(secret, rendered)

    def test_check_for_update_rejects_malformed_manifest_and_unowned_installation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            malformed = self.create_curl_sh_fixture(base / "malformed")
            with self.assertRaises(tapl_updater.UpdateError) as malformed_error:
                tapl_updater.check_for_update(
                    **self.updater_kwargs(
                        malformed,
                        opener=self.opener({self.manifest_url: b'{"schema_version": 1}'}),
                    )
                )
            self.assertEqual(malformed_error.exception.code, "invalid_manifest")

            cases: list[tuple[str, dict[str, object]]] = []
            non_curl = self.create_curl_sh_fixture(base / "non-curl")
            non_curl_metadata_path = non_curl["metadata_path"]
            self.assertIsInstance(non_curl_metadata_path, Path)
            metadata = json.loads(non_curl_metadata_path.read_text(encoding="utf-8"))
            metadata["method"] = "pip"
            non_curl_metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
            cases.append(("non-curl metadata", non_curl))

            wrong_link = self.create_curl_sh_fixture(base / "wrong-link")
            wrong_link_executable = wrong_link["executable"]
            self.assertIsInstance(wrong_link_executable, Path)
            wrong_link_executable.unlink()
            other_command = base / "other" / "taplctl"
            other_command.parent.mkdir(parents=True)
            other_command.write_text("#!/bin/sh\n", encoding="utf-8")
            wrong_link_executable.symlink_to(other_command)
            cases.append(("unowned command symlink", wrong_link))

            wrong_prefix = self.create_curl_sh_fixture(base / "wrong-prefix")
            wrong_prefix["current_prefix"] = base / "unowned-venv"
            wrong_prefix["current_python"] = base / "unowned-venv" / "bin" / "python"
            cases.append(("unowned active prefix", wrong_prefix))

            valid_manifest = self.manifest("1.1.0", b"wheel")
            for name, fixture in cases:
                with self.subTest(case=name):
                    kwargs = self.updater_kwargs(
                        fixture,
                        opener=self.opener({self.manifest_url: valid_manifest}),
                    )
                    kwargs["current_prefix"] = fixture.get("current_prefix", fixture["venv"])
                    kwargs["current_python"] = fixture.get("current_python", fixture["python"])
                    with self.assertRaises(tapl_updater.UpdateError) as unsupported_error:
                        tapl_updater.check_for_update(**kwargs)
                    self.assertEqual(unsupported_error.exception.code, "unsupported_installation")

    def test_update_rejects_bad_wheel_checksum_without_changing_installation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = self.create_curl_sh_fixture(Path(tmp))
            metadata_path = fixture["metadata_path"]
            executable = fixture["executable"]
            versions_dir = fixture["versions_dir"]
            self.assertIsInstance(metadata_path, Path)
            self.assertIsInstance(executable, Path)
            self.assertIsInstance(versions_dir, Path)
            original_metadata = metadata_path.read_bytes()
            original_target = self.resolved_target(executable)
            expected_wheel = b"expected release wheel"
            with self.assertRaises(tapl_updater.UpdateError) as checksum_error:
                tapl_updater.update_installation(
                    **self.updater_kwargs(
                        fixture,
                        opener=self.opener(
                            {
                                self.manifest_url: self.manifest("1.1.0", expected_wheel),
                                self.wheel_url: b"tampered release wheel",
                            }
                        ),
                    ),
                    runner=self.candidate_runner(version="1.1.0"),
                )
            self.assertEqual(checksum_error.exception.code, "checksum_mismatch")
            self.assertEqual(metadata_path.read_bytes(), original_metadata)
            self.assertEqual(self.resolved_target(executable), original_target)
            self.assertEqual(list(versions_dir.iterdir()), [fixture["venv"]])

    def test_update_installs_verified_candidate_and_activates_metadata(self) -> None:
        manifest_url = (
            "https://alice:p4ssword@updates.example.test/releases/manifest.json"
            "?access_token=qsecret#fragsecret"
        )
        wheel_url = (
            "https://bob:wpass@cdn.example.test/artifacts/taplctl-1.1.0.whl"
            "?access_token=wsecret#wfrag"
        )
        with tempfile.TemporaryDirectory() as tmp:
            fixture = self.create_curl_sh_fixture(Path(tmp))
            self.set_fixture_urls(
                fixture,
                manifest_url=manifest_url,
                wheel_url=wheel_url,
            )
            wheel = b"verified release wheel"
            payload = tapl_updater.update_installation(
                **self.updater_kwargs(
                    fixture,
                    opener=self.opener(
                        {
                            manifest_url: self.manifest(
                                "1.1.0",
                                wheel,
                                wheel_url=wheel_url,
                            ),
                            wheel_url: wheel,
                        }
                    ),
                ),
                runner=self.candidate_runner(version="1.1.0"),
            )
            metadata_path = fixture["metadata_path"]
            executable = fixture["executable"]
            self.assertIsInstance(metadata_path, Path)
            self.assertIsInstance(executable, Path)
            activated_metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            candidate = Path(payload["venv"])
            self.assertTrue(payload["updated"])
            self.assertEqual(payload["status"], "updated")
            self.assertEqual(payload["previous_version"], "1.0.0")
            self.assertEqual(activated_metadata["version"], "1.1.0")
            self.assertEqual(activated_metadata["manifest_url"], manifest_url)
            self.assertEqual(activated_metadata["wheel_url"], wheel_url)
            self.assertEqual(
                payload["manifest_url"],
                "https://updates.example.test/releases/manifest.json",
            )
            self.assertEqual(
                payload["wheel_url"],
                "https://cdn.example.test/artifacts/taplctl-1.1.0.whl",
            )
            self.assertEqual(Path(activated_metadata["venv"]), candidate)
            self.assertTrue((candidate / "bin" / "taplctl").is_file())
            self.assertEqual(
                self.resolved_target(executable),
                self.resolved_target(candidate / "bin" / "taplctl"),
            )

    def test_update_candidate_creation_or_pip_failure_preserves_active_installation(self) -> None:
        for failure, code in (("venv", "venv_creation_failed"), ("pip", "wheel_install_failed")):
            with self.subTest(failure=failure):
                with tempfile.TemporaryDirectory() as tmp:
                    fixture = self.create_curl_sh_fixture(Path(tmp))
                    metadata_path = fixture["metadata_path"]
                    executable = fixture["executable"]
                    versions_dir = fixture["versions_dir"]
                    self.assertIsInstance(metadata_path, Path)
                    self.assertIsInstance(executable, Path)
                    self.assertIsInstance(versions_dir, Path)
                    original_metadata = metadata_path.read_bytes()
                    original_target = self.resolved_target(executable)
                    wheel = b"verified release wheel"
                    with self.assertRaises(tapl_updater.UpdateError) as failed_update:
                        tapl_updater.update_installation(
                            **self.updater_kwargs(
                                fixture,
                                opener=self.opener(
                                    {
                                        self.manifest_url: self.manifest("1.1.0", wheel),
                                        self.wheel_url: wheel,
                                    }
                                ),
                            ),
                            runner=self.candidate_runner(version="1.1.0", fail_at=failure),
                        )
                    self.assertEqual(failed_update.exception.code, code)
                    self.assertEqual(metadata_path.read_bytes(), original_metadata)
                    self.assertEqual(self.resolved_target(executable), original_target)
                    self.assertEqual(list(versions_dir.iterdir()), [fixture["venv"]])

    def test_metadata_activation_failure_restores_the_previous_command_link(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = self.create_curl_sh_fixture(Path(tmp))
            metadata_path = fixture["metadata_path"]
            executable = fixture["executable"]
            versions_dir = fixture["versions_dir"]
            self.assertIsInstance(metadata_path, Path)
            self.assertIsInstance(executable, Path)
            self.assertIsInstance(versions_dir, Path)
            original_metadata = metadata_path.read_bytes()
            original_target = self.resolved_target(executable)
            wheel = b"verified release wheel"
            real_replace = os.replace

            def fail_metadata_replace(source: object, destination: object) -> None:
                if Path(destination) == metadata_path:
                    raise OSError("metadata storage is read-only")
                real_replace(source, destination)

            with mock.patch.object(tapl_updater.os, "replace", side_effect=fail_metadata_replace):
                with self.assertRaises(tapl_updater.UpdateError) as activation_error:
                    tapl_updater.update_installation(
                        **self.updater_kwargs(
                            fixture,
                            opener=self.opener(
                                {
                                    self.manifest_url: self.manifest("1.1.0", wheel),
                                    self.wheel_url: wheel,
                                }
                            ),
                        ),
                        runner=self.candidate_runner(version="1.1.0"),
                    )
            self.assertEqual(activation_error.exception.code, "metadata_activation_failed")
            self.assertEqual(metadata_path.read_bytes(), original_metadata)
            self.assertEqual(self.resolved_target(executable), original_target)
            self.assertEqual(list(versions_dir.iterdir()), [fixture["venv"]])

    def test_update_cli_renders_check_and_update_payloads_without_auto_install(self) -> None:
        check_payload = {
            "ok": True,
            "action": "check",
            "status": "update-available",
            "update_available": True,
            "current_version": "1.0.0",
            "latest_version": "1.1.0",
        }
        update_payload = {
            "ok": True,
            "action": "update",
            "status": "updated",
            "updated": True,
            "previous_version": "1.0.0",
            "current_version": "1.1.0",
            "latest_version": "1.1.0",
        }
        cases = (
            ("check human", ["update", "--check"], check_payload, "check"),
            ("check json", ["update", "--check", "--json"], check_payload, "check"),
            ("check agent", ["update", "--check", "--agent"], check_payload, "check"),
            ("update human", ["update"], update_payload, "update"),
            ("update json", ["update", "--json"], update_payload, "update"),
            ("update agent", ["update", "--agent"], update_payload, "update"),
        )
        for name, argv, payload, handler in cases:
            with self.subTest(output=name):
                stdout = io.StringIO()
                stderr = io.StringIO()
                with (
                    mock.patch.object(tapl_cli.updater, "check_for_update", return_value=check_payload) as check,
                    mock.patch.object(tapl_cli.updater, "update_installation", return_value=update_payload) as update,
                    mock.patch.object(tapl_cli.tapl_install, "auto_install_if_needed") as auto_install,
                    contextlib.redirect_stdout(stdout),
                    contextlib.redirect_stderr(stderr),
                    warnings.catch_warnings(),
                ):
                    warnings.simplefilter("ignore", ResourceWarning)
                    exit_code = tapl_cli.main(argv)
                self.assertEqual(exit_code, 0)
                self.assertEqual(stderr.getvalue(), "")
                auto_install.assert_not_called()
                if handler == "check":
                    check.assert_called_once_with()
                    update.assert_not_called()
                else:
                    update.assert_called_once_with()
                    check.assert_not_called()
                rendered = stdout.getvalue()
                if "--json" in argv:
                    self.assertEqual(json.loads(rendered), payload)
                elif "--agent" in argv:
                    self.assertIn("<tapl_output>", rendered)
                    self.assertIn(f"<action>{payload['action']}</action>", rendered)
                    self.assertIn(f"<status>{payload['status']}</status>", rendered)
                elif handler == "check":
                    self.assertIn("Update available: taplctl 1.0.0 → 1.1.0", rendered)
                else:
                    self.assertEqual(rendered, "Updated taplctl: 1.0.0 → 1.1.0.\n")

    def test_update_cli_renders_structured_unsupported_installation_errors(self) -> None:
        error = tapl_updater.UpdateError(
            "taplctl is not running from a valid curl-sh installation",
            code="unsupported_installation",
        )
        cases = (
            ("human", ["update", "--check"]),
            ("json", ["update", "--check", "--json"]),
            ("agent", ["update", "--check", "--agent"]),
        )
        for output, argv in cases:
            with self.subTest(output=output):
                stdout = io.StringIO()
                stderr = io.StringIO()
                with (
                    mock.patch.object(tapl_cli.updater, "check_for_update", side_effect=error) as check,
                    mock.patch.object(tapl_cli.updater, "update_installation") as update,
                    mock.patch.object(tapl_cli.tapl_install, "auto_install_if_needed") as auto_install,
                    contextlib.redirect_stdout(stdout),
                    contextlib.redirect_stderr(stderr),
                    warnings.catch_warnings(),
                ):
                    warnings.simplefilter("ignore", ResourceWarning)
                    exit_code = tapl_cli.main(argv)
                self.assertEqual(exit_code, 1)
                check.assert_called_once_with()
                update.assert_not_called()
                auto_install.assert_not_called()
                if output == "json":
                    self.assertEqual(
                        json.loads(stdout.getvalue()),
                        {
                            "ok": False,
                            "error": {
                                "code": "unsupported_installation",
                                "message": "taplctl is not running from a valid curl-sh installation",
                            },
                        },
                    )
                    self.assertEqual(stderr.getvalue(), "")
                elif output == "agent":
                    self.assertIn("<tapl_output>", stdout.getvalue())
                    self.assertIn("<error>", stdout.getvalue())
                    self.assertIn("<code>unsupported_installation</code>", stdout.getvalue())
                    self.assertIn(
                        "<message>taplctl is not running from a valid curl-sh installation</message>",
                        stdout.getvalue(),
                    )
                    self.assertEqual(stderr.getvalue(), "")
                else:
                    self.assertEqual(stdout.getvalue(), "")
                    self.assertIn("brew upgrade taplctl", stderr.getvalue())
                    self.assertIn("brew upgrade taplctl-semantic", stderr.getvalue())

    def test_update_cli_json_and_agent_outputs_keep_tokenized_urls_redacted(self) -> None:
        payload = {
            "ok": True,
            "action": "check",
            "status": "update-available",
            "update_available": True,
            "current_version": "1.0.0",
            "latest_version": "1.1.0",
            "manifest_url": "https://updates.example.test/releases/manifest.json",
            "wheel_url": "https://cdn.example.test/artifacts/taplctl-1.1.0.whl",
        }
        error = tapl_updater.UpdateError(
            "could not download update data",
            code="download_failed",
            details={"url": "https://cdn.example.test/artifacts/taplctl-1.1.0.whl"},
        )
        secrets = (
            "alice",
            "p4ssword",
            "access_token",
            "qsecret",
            "fragsecret",
            "bob",
            "wpass",
            "wsecret",
            "wfrag",
        )
        for mode in ("--json", "--agent"):
            with self.subTest(mode=mode):
                rendered_parts: list[str] = []
                for result in (payload, error):
                    stdout = io.StringIO()
                    stderr = io.StringIO()
                    patch_kwargs = (
                        {"return_value": result}
                        if isinstance(result, dict)
                        else {"side_effect": result}
                    )
                    with (
                        mock.patch.object(
                            tapl_cli.updater,
                            "check_for_update",
                            **patch_kwargs,
                        ),
                        mock.patch.object(tapl_cli.tapl_install, "auto_install_if_needed"),
                        contextlib.redirect_stdout(stdout),
                        contextlib.redirect_stderr(stderr),
                    ):
                        exit_code = tapl_cli.main(["update", "--check", mode])
                    self.assertEqual(exit_code, 0 if isinstance(result, dict) else 1)
                    rendered_parts.extend((stdout.getvalue(), stderr.getvalue()))

                combined = "".join(rendered_parts)
                self.assertIn(
                    "https://updates.example.test/releases/manifest.json",
                    combined,
                )
                self.assertIn(
                    "https://cdn.example.test/artifacts/taplctl-1.1.0.whl",
                    combined,
                )
                self.assertIn("download_failed", combined)
                for secret in secrets:
                    self.assertNotIn(secret, combined)


if __name__ == "__main__":
    unittest.main()
