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
    validation as tapl_validation,
)


class TaplRuntimeTests(unittest.TestCase):
    def tapl_env(self) -> dict[str, str]:
        env = os.environ.copy()
        env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
        return env

    def run_management_cli(
        self, db_path: Path, *args: str, input_text: str | None = None
    ) -> subprocess.CompletedProcess[str]:
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

        self.assertEqual(len(tools), 23)
        self.assertIn("tapl_get_status", by_name)
        self.assertIn("tapl_get_context", by_name)
        self.assertIn("tapl_list_archives", by_name)
        self.assertIn("tapl_get_archive", by_name)
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
            set(summarize_schema["required"]),
            {"summary", "work_type", "workflow_mode"},
        )
        self.assertEqual(
            summarize_schema["properties"]["work_type"]["enum"],
            ["answer", "investigation", "analysis", "planning", "implementation", "mixed"],
        )
        self.assertEqual(
            summarize_schema["properties"]["workflow_mode"]["enum"],
            ["fast", "standard", "strict"],
        )

    def test_every_mcp_write_tool_routes_through_compact_receipt_with_next(self) -> None:
        server = tapl_mcp.create_server(workspace_root=ROOT)
        calls = (
            (
                "tapl_summarize_run",
                {"summary": "Receipt routing", "work_type": "analysis", "workflow_mode": "standard"},
            ),
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
            application: object,
            method: object,
            *args: object,
            operation: str,
            **kwargs: object,
        ) -> dict[str, object]:
            del application, method, args, kwargs
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
            "call_application_write",
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
                "work_type": "implementation",
                "workflow_mode": "strict",
                "record_mode": "planned",
                "request_summary": "Do not echo this body",
            },
        }
        application = mock.Mock()
        application.get_next.side_effect = RuntimeError("next unavailable")
        receipt = asyncio.run(
            tapl_mcp.call_application_write(
                application,
                lambda: raw_write,
                operation="run_summarize",
            )
        )

        self.assertTrue(receipt["ok"])
        self.assertNotIn("request_summary", receipt["active_run"])
        self.assertEqual(receipt["recommendations"][0]["tool"], "tapl_get_status")

    def test_tapl_mcp_stdio_entrypoint_negotiates_and_calls_tools(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            (workspace / ".git").mkdir(parents=True)
            tapl_db.initialize_workspace(workspace)
            params = StdioServerParameters(
                command=sys.executable,
                args=["-m", "taplctl.mcp_server"],
                cwd=workspace,
            )

            async def exercise() -> tuple[object, object]:
                async with Client(stdio_client(params)) as client:
                    tools = await client.list_tools()
                    result = await client.call_tool(
                        "tapl_summarize_run",
                        {
                            "summary": "stdio MCP smoke test",
                            "work_type": "analysis",
                            "workflow_mode": "standard",
                        },
                    )
                    return tools, result

            tools, result = asyncio.run(exercise())
            self.assertEqual(len(tools.tools), 23)
            self.assertFalse(result.is_error)
            receipt = result.structured_content
            self.assertEqual(receipt["operation"], "run_summarize")
            self.assertEqual(receipt["active_run"]["work_type"], "analysis")
            self.assertEqual(receipt["active_run"]["workflow_mode"], "standard")
            self.assertEqual(receipt["active_run"]["record_mode"], "planned")
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
                        await client.call_tool(
                            "tapl_summarize_run",
                            {
                                "summary": "MCP lifecycle",
                                "work_type": "implementation",
                                "workflow_mode": "standard",
                            },
                        ),
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
                        {
                            "summary": "Answer a simple question",
                            "work_type": "answer",
                            "workflow_mode": "fast",
                        },
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
                summarized.structured_content["active_run"]["work_type"],
                "answer",
            )
            self.assertEqual(
                summarized.structured_content["active_run"]["workflow_mode"],
                "fast",
            )
            self.assertEqual(
                summarized.structured_content["active_run"]["record_mode"],
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

    def test_database_migrations_preserve_task_data_and_backfill_plan_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "tapl.db"
            conn = tapl_db.connect(db_path)
            try:
                tapl_db.upsert_task(
                    conn,
                    task_id="TASK-001",
                    title="Preserve task data",
                    status="Completed",
                    spec_id="PLAN-001",
                    verification="Migration smoke",
                    result="Done",
                )
                tapl_db.upsert_item(
                    conn,
                    kind="plan",
                    stable_id="PLAN-001",
                    title="Backfilled plan",
                    body="Existing plan body",
                )
            finally:
                conn.close()

            with sqlite3.connect(db_path) as legacy:
                legacy.execute(
                    "ALTER TABLE tasks ADD COLUMN required_subagent TEXT NOT NULL DEFAULT ''"
                )
                legacy.execute("UPDATE tasks SET required_subagent = '@senior-worker'")
                legacy.execute("UPDATE meta SET value = '4' WHERE key = 'schema_version'")

            migrated = tapl_db.connect(db_path)
            try:
                task = tapl_db.get_active_task(migrated, "TASK-001")
                plan = tapl_db.get_active_plan(migrated, "PLAN-001")
                columns = {row["name"] for row in migrated.execute("PRAGMA table_info(tasks)")}
                self.assertEqual(task["verification"], "Migration smoke")
                self.assertEqual(task["result"], "Done")
                self.assertEqual(plan["plan_id"], "PLAN-001")
                self.assertNotIn("required_subagent", columns)
                self.assertEqual(
                    tapl_db.get_meta(migrated)["schema_version"], str(tapl_db.SCHEMA_VERSION)
                )
            finally:
                migrated.close()

    def test_v8_workflow_modes_migrate_to_explicit_classification_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "tapl.db"
            with sqlite3.connect(db_path) as legacy:
                legacy.executescript(
                    """
                    CREATE TABLE meta (
                      key TEXT PRIMARY KEY,
                      value TEXT NOT NULL
                    );
                    INSERT INTO meta(key, value) VALUES('schema_version', '8');
                    CREATE TABLE workflow_runs (
                      id TEXT PRIMARY KEY,
                      slug TEXT NOT NULL,
                      status TEXT NOT NULL,
                      request_summary TEXT NOT NULL DEFAULT '',
                      result_summary TEXT NOT NULL DEFAULT '',
                      workflow_mode TEXT NOT NULL DEFAULT 'planned'
                        CHECK (workflow_mode IN ('planned', 'lightweight')),
                      created_at TEXT NOT NULL,
                      updated_at TEXT NOT NULL,
                      archived_at TEXT
                    );
                    INSERT INTO workflow_runs(
                      id, slug, status, request_summary, workflow_mode, created_at, updated_at
                    ) VALUES
                      ('legacy-fast', 'legacy-fast', 'archived', 'Small answer', 'lightweight', '2026-01-01', '2026-01-01'),
                      ('legacy-planned', 'active', 'active', 'Durable work', 'planned', '2026-01-02', '2026-01-02');
                    """
                )

            migrated = tapl_db.connect(db_path)
            try:
                columns = {
                    row["name"] for row in migrated.execute("PRAGMA table_info(workflow_runs)")
                }
                rows = {
                    row["id"]: dict(row)
                    for row in migrated.execute(
                        "SELECT id, work_type, workflow_mode, record_mode FROM workflow_runs"
                    )
                }
                self.assertEqual(
                    {"work_type", "workflow_mode", "record_mode"} - columns,
                    set(),
                )
                self.assertEqual(
                    rows["legacy-fast"],
                    {
                        "id": "legacy-fast",
                        "work_type": "answer",
                        "workflow_mode": "fast",
                        "record_mode": "lightweight",
                    },
                )
                self.assertEqual(
                    rows["legacy-planned"],
                    {
                        "id": "legacy-planned",
                        "work_type": "mixed",
                        "workflow_mode": "standard",
                        "record_mode": "planned",
                    },
                )
                self.assertEqual(tapl_db.get_meta(migrated)["schema_version"], "9")
            finally:
                migrated.close()

    def test_mcp_server_instructions_are_compact_and_keep_adaptive_policy(self) -> None:
        instructions = tapl_prompt.mcp_server_instructions(
            subagents=tapl_config.SubagentsConfig()
        )

        self.assertLess(len(instructions), 8_500)
        required_policy = (
            "Do not modify source, tests, docs, configs, migrations, generated files",
            "before execution approval",
            "TAPL run, plan, task, finding, approval, and archive records may be created or updated before execution approval",
            "Do not commit, push, rebase, reset, discard changes",
            "Never overwrite user changes",
            "current-state snapshots, not logs",
            "Classify once from the request and readily available context: Answer, Investigation, Analysis, Planning, Implementation, or Mixed.",
            "First choose Strict",
            "Otherwise choose Fast",
            "All other work is Standard.",
            "Mixed uses its highest child mode.",
            "Pass the selected work_type and workflow_mode explicitly",
            "record_mode=`lightweight` only for Fast non-durable Answer, Investigation, Analysis, or Planning work",
            "`tapl_apply_plan` promotes only record_mode when scope or risk grows.",
            "Planning must happen before implementation",
            "Finalize only after explicit user confirmation.",
            "Before finalizing a plan",
            "Do not search, query history, or create plan/tasks solely to classify",
            "Record at most two short reasons",
            "uncertainty defaults to Standard",
            "Bundle sequential implementation and its targeted verification in one task.",
            "Split only independent",
            "Execute planned tasks one at a time in task order",
            "exclusive owned_paths",
            "exact manifest execution_id",
            "recover or cancel the batch before retrying",
            "actual runtime model/reasoning effort",
            "Delegate only when at least two genuinely independent, non-overlapping parallel tracks",
            "startup and coordination cost.",
            "execution approval",
            "only active work is In Progress",
            "Reclassify upward only when scope, risk, or uncertainty grows",
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
        self.assertNotIn("very_detailed", instructions)
        self.assertNotIn("very_granular", instructions)

    def test_mcp_result_table_guidance_stays_in_server_instructions(self) -> None:
        instructions = tapl_prompt.mcp_server_instructions()
        injected_context = "\n".join(
            (
                tapl_prompt.session_start_guidance(),
                tapl_prompt.user_prompt_submit_guidance(),
                tapl_prompt.stop_guidance(),
            )
        )
        tool_result = json.dumps(
            tapl_mcp.mcp_write_receipt(
                {
                    "ok": True,
                    "item": {
                        "id": 1,
                        "stable_id": "TASK-001",
                        "kind": "task",
                        "status": "Pending",
                    },
                },
                operation="task_create",
            )
        )

        required_result_guidance = (
            "For one or more `tapl_*` write results reported in the same turn, begin exactly with `### TAPL`",
            "Render each record as its own Markdown block",
            "``| **✏️ PLAN-001** | **✅ `확정`** |``",
            "the separator `|---|---|`",
            "one or more summary list items beginning with `- ` immediately below the table",
            "Separate record blocks with a blank line",
            "never combine multiple records into one table",
            "Use ⚙️ for RUN, ✏️ for PLAN, 📋 for TASK, 🔎 for FINDING, and 🗂️ for ARCHIVE",
            "Use ✅ for Completed, finalized, or confirmed",
            "⏩ for Skipped; ⛔️ for Blocked; ♻️ for InProgress; and 📝 for Created",
            "Translate status labels and other codes to the user's language",
            "Use each record's stable ID when available",
            "a concise, unique, human-readable name otherwise, such as an archive slug",
            "never use a UUID or another opaque random identifier",
            "Summarize submitted or changed write fields and relevant",
            "`tapl_search_history`→`tapl_get_item` detail in that record's list",
            "Finish all blocks before the next non-`tapl_*` call or ordinary response",
            "Report errors, blockers, approvals, and user-input calls immediately",
            "Use normal prose for all other reads, reasoning, injected context, ordinary answers, and final reports",
        )
        for guidance in required_result_guidance:
            self.assertIn(guidance, instructions)
            self.assertNotIn(guidance, injected_context)
            self.assertNotIn(guidance, tool_result)
        self.assertNotIn("TAPL-headed", instructions)
        self.assertNotIn("`| TAPL | |`", instructions)
        self.assertNotIn("one Markdown table", instructions)
        self.assertNotIn("three-row block", instructions)
        self.assertNotIn("a `| |` separator", instructions)
        self.assertNotIn("• TAPL", instructions)
        self.assertNotIn("record/status headings", instructions)
        self.assertNotIn("TASK-003·004", instructions)
        self.assertNotIn("Immediately after each `tapl_*` MCP tool call", instructions)

    def test_adaptive_validation_allows_compact_plans_and_coherent_task_bundles(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            (workspace / ".git").mkdir(parents=True)
            tapl_db.initialize_workspace(workspace)
            conn = tapl_db.connect(workspace / tapl_db.DEFAULT_DB_RELATIVE)
            try:
                tapl_db.ensure_active_run(
                    conn,
                    request_summary="Apply one small local fix.",
                    work_type="implementation",
                    workflow_mode="fast",
                )
                missing_plan_issues = tapl_validation.validate_plan_task_execute(conn)["issues"]
                self.assertIn("missing_plan", {issue["code"] for issue in missing_plan_issues})

                tapl_db.upsert_plan(
                    conn,
                    plan_id="PLAN-001",
                    title="Compact local fix",
                    status="Finalized",
                    summary="Fix one local issue.",
                    validation="Run the targeted test.",
                )
                tapl_db.upsert_task(
                    conn,
                    task_id="TASK-001",
                    title="Fix and verify local issue",
                    status="Pending",
                    spec_id="PLAN-001",
                    goal="Fix the local issue.",
                    action="Implement the change and run its targeted test.",
                    verification="The targeted test passes.",
                )
                issues = tapl_validation.validate_plan_task_execute(conn)["issues"]
            finally:
                conn.close()

        codes = {issue["code"] for issue in issues}
        self.assertNotIn("plan_detail_too_sparse", codes)
        self.assertNotIn("task_granularity_too_coarse", codes)

        self.assertEqual(tapl_validation.validate_plan_detail([], required=False), [])

    def test_adaptive_validation_guidance_uses_adaptive_policy_keys(self) -> None:
        payload = tapl_validation.guidance()

        self.assertIn("adaptive_plan_policy", payload)
        self.assertIn("adaptive_task_policy", payload)
        self.assertIn("execution_approval_policy", payload)
        self.assertNotIn("fixed_plan_policy", payload)
        self.assertNotIn("fixed_task_policy", payload)
        self.assertNotIn("fixed_execution_approval_policy", payload)

    def test_subagent_opt_in_is_compact_and_conditional(self) -> None:
        guidance = tapl_prompt.subagent_delegation_request_guidance(
            tapl_config.SubagentsConfig()
        )

        self.assertLess(len(guidance), 350)
        self.assertIn("only for approved tasks meeting the MCP delegation criteria", guidance)
        self.assertIn("without renewed approval", guidance)
        self.assertIn("dispatch, ownership, model-selection, and settlement rules", guidance)
        self.assertIn("scope, safety, permission, and sandbox constraints", guidance)
        self.assertNotIn("For this TAPL run", guidance)

    def test_lightweight_help_covers_all_fast_non_durable_work(self) -> None:
        work_type_help = tapl_prompt.field_help("run", "work_type")
        mode_help = tapl_prompt.field_help("run", "workflow_mode")
        next_action = tapl_prompt.lightweight_run_next_action()

        self.assertIn("answer, investigation, analysis, planning, implementation, or mixed", work_type_help)
        self.assertIn("fast, standard, or strict", mode_help)
        self.assertIn("complete the Fast non-durable work", next_action)
        self.assertIn("record_mode to planned", next_action)
        self.assertNotIn("answer directly", next_action)

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

    def test_config_rejects_non_positive_search_max_results(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "tapl.toml"
            config_path.write_text("[search]\nmax_results = 0\n", encoding="utf-8")

            with self.assertRaises(ValueError):
                tapl_config.load(config_path)

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
            status = self.run_management_cli(
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

    def test_install_user_writes_taplctl_hooks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            codex_home = base / "home" / ".codex"
            db_path = base / "tapl.db"

            installed = self.run_management_cli(
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
            self.assertEqual(prompt_hook, "tapl-hook --event UserPromptSubmit --mode observe")
            self.assertNotIn("SessionStart", hooks["hooks"])
            self.assertNotIn("tapl_hook.py", json.dumps(hooks))
            self.assertTrue((codex_home / "config.toml").exists())
            codex_config = tomllib.loads((codex_home / "config.toml").read_text(encoding="utf-8"))
            self.assertEqual(
                codex_config["mcp_servers"]["tapl"],
                {
                    "command": "tapl-mcp",
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

            installed = self.run_management_cli(
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
            self.assertNotIn("model_reasoning_effort", parsed)
            self.assertNotIn("personality", parsed)
            self.assertNotIn("multi_agent", parsed["features"])
            self.assertTrue(parsed["features"]["default_mode_request_user_input"])
            self.assertEqual(parsed["mcp_servers"]["existing"]["command"], "existing-mcp")
            self.assertEqual(parsed["mcp_servers"]["tapl"]["command"], "tapl-mcp")
            self.assertNotIn("args", parsed["mcp_servers"]["tapl"])
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

            installed = self.run_management_cli(
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
            self.assertEqual(parsed["model"], "gpt-5")
            self.assertEqual(parsed["approval_policy"], "on-request")
            self.assertNotIn("model_reasoning_effort", parsed)
            self.assertNotIn("personality", parsed)
            self.assertNotIn("multi_agent", parsed["features"])
            self.assertTrue(parsed["features"]["experimental"])
            self.assertTrue(parsed["features"]["default_mode_request_user_input"])
            self.assertEqual(parsed["mcp_servers"]["tapl"]["command"], "tapl-mcp")
            self.assertNotIn("args", parsed["mcp_servers"]["tapl"])

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

            installed = self.run_management_cli(
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
                "/opt/tapl/bin/tapl-hook --event PreToolUse --mode observe",
                pre_tool_commands,
            )
            self.assertTrue((repo / ".codex" / "config.toml").exists())
            codex_config = tomllib.loads((repo / ".codex" / "config.toml").read_text(encoding="utf-8"))
            self.assertEqual(codex_config["mcp_servers"]["tapl"]["command"], "/opt/tapl/bin/tapl-mcp")
            self.assertNotIn("args", codex_config["mcp_servers"]["tapl"])
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

            installed = self.run_management_cli(
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
            tapl_db.initialize_workspace(repo)

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

    def test_auto_install_skips_uninitialized_repo_but_refreshes_stale_user(self) -> None:
        def add_install_evidence(scope: Path, evidence: str) -> Path:
            if evidence == "version":
                path = scope / ".tapl" / "version"
                path.parent.mkdir(parents=True)
                path.write_text("0.0.0\n", encoding="utf-8")
                return path
            if evidence == "config":
                path = scope / ".tapl" / "config.toml"
                path.parent.mkdir(parents=True)
                path.write_text("[search]\nmax_results = 4\n", encoding="utf-8")
                return path
            if evidence == "hook":
                path = scope / ".codex" / "hooks.json"
                path.parent.mkdir(parents=True)
                path.write_text(
                    json.dumps(
                        {
                            "hooks": {
                                "UserPromptSubmit": [
                                    {
                                        "hooks": [
                                            {
                                                "type": "command",
                                                "command": "taplctl hook-event --event UserPromptSubmit --mode observe",
                                            }
                                        ]
                                    }
                                ]
                            }
                        }
                    ),
                    encoding="utf-8",
                )
                return path
            self.fail(f"unknown install evidence: {evidence}")

        for evidence in ("version", "config", "hook"):
            with self.subTest(evidence=evidence), tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                home = base / "home"
                repo = base / "repo"
                repo.mkdir()
                user_evidence = add_install_evidence(home, evidence)
                repo_evidence = add_install_evidence(repo, evidence)
                repo_evidence_before = repo_evidence.read_bytes()

                results = tapl_install.auto_install_if_needed(start=repo, home=home)

                self.assertEqual([result["install"] for result in results], ["user"])
                self.assertEqual(
                    (home / ".tapl" / "version").read_text(encoding="utf-8").strip(),
                    __version__,
                )
                self.assertTrue(user_evidence.exists())
                self.assertEqual(repo_evidence.read_bytes(), repo_evidence_before)
                self.assertFalse((repo / tapl_db.DEFAULT_DB_RELATIVE).exists())
                self.assertNotEqual(
                    tapl_install.installed_version(repo / ".tapl" / "version"),
                    __version__,
                )

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

    def test_check_for_update_orders_canonical_python_prereleases(self) -> None:
        cases = (
            ("1.9.9", "2.0.0b1", "update-available", True),
            ("2.0.0a9", "2.0.0b1", "update-available", True),
            ("2.0.0b1", "2.0.0b2", "update-available", True),
            ("2.0.0b2", "2.0.0rc1", "update-available", True),
            ("2.0.0rc1", "2.0.0", "update-available", True),
            ("2.0.0", "2.0.0rc9", "current-newer", False),
            ("2.0.0b10", "2.0.0b2", "current-newer", False),
        )
        with tempfile.TemporaryDirectory() as tmp:
            for index, (current, latest, status, available) in enumerate(cases):
                with self.subTest(current=current, latest=latest):
                    fixture = self.create_curl_sh_fixture(
                        Path(tmp) / str(index), version=current
                    )
                    wheel = b"release wheel"
                    payload = tapl_updater.check_for_update(
                        **self.updater_kwargs(
                            fixture,
                            opener=self.opener(
                                {self.manifest_url: self.manifest(latest, wheel)}
                            ),
                        )
                    )
                    self.assertEqual(payload["status"], status)
                    self.assertEqual(payload["update_available"], available)

    def test_update_versions_reject_noncanonical_prerelease_formats(self) -> None:
        invalid_versions = (
            "2.0.0-beta1",
            "2.0.0beta1",
            "2.0.0b",
            "2.0.0rc",
            "2.0.0RC1",
            "v2.0.0b1",
            "2.0",
            "2.0.0.post1",
            "2.0.0b1 ",
        )
        with tempfile.TemporaryDirectory() as tmp:
            fixture = self.create_curl_sh_fixture(Path(tmp))
            for version in invalid_versions:
                with self.subTest(version=version):
                    with self.assertRaises(tapl_updater.UpdateError) as raised:
                        tapl_updater.check_for_update(
                            **self.updater_kwargs(
                                fixture,
                                opener=self.opener(
                                    {
                                        self.manifest_url: self.manifest(
                                            version, b"release wheel"
                                        )
                                    }
                                ),
                            )
                        )
                    self.assertEqual(raised.exception.code, "invalid_manifest")

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
