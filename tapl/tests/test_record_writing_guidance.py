"""Agent-facing writing guidance without runtime text enforcement."""
from __future__ import annotations

import asyncio

from mcp import Client
import pytest

from taplctl import db, mcp_server, prompt


def _workspace(tmp_path):
    (tmp_path / ".git").mkdir()
    db.initialize_workspace(tmp_path)
    (tmp_path / ".tapl/config.toml").write_text(
        "[recall]\nenabled=false\n[subagents]\nenabled=false\nsetup_complete=true\n",
        encoding="utf-8",
    )
    return tmp_path


def test_actual_mcp_policy_and_tool_schemas_include_readable_record_guidance(tmp_path):
    async def exercise():
        async with Client(mcp_server.create_server(workspace_root=_workspace(tmp_path))) as client:
            entry = (await client.call_tool("tapl_get_next", {})).structured_content
            policy = entry["workflow_policy"]
            assert "including tool arguments and custom-field descriptions" in policy
            assert "preserve Korean word spacing" in policy
            assert "never by joining words or minifying prose" in policy
            assert "instead of copying compressed wording" in policy
            assert "direct quotations verbatim" in policy
            assert "개발 앱 설정을 준비한 뒤 Task 1개를 실행하고 결과를 확인한다." in policy
            assert "APP_CONFIG_YML 경로를 확인하고 검증 결과를 기록한다." in policy
            # These providers must reach the actual model-facing policy.
            for guidance in (
                prompt.structured_record_guidance(),
                prompt.markdown_record_guidance(),
                prompt.plan_format_guidance(),
            ):
                assert guidance in policy
            assert "${record_writing_guidance}" not in policy

            listed = await client.list_tools()
            tools = {tool.name: tool for tool in listed.tools}
            prose = {
                "tapl_apply_plan": (
                    "title", "summary", "objective", "requirements_trace", "selected_approach",
                    "affected_files", "execution_order", "risks", "validation", "approval_needs", "notes",
                ),
                "tapl_create_task": ("title", "goal", "action", "verification"),
                "tapl_complete_task": ("result", "verification"),
                "tapl_block_task": ("blocker", "next_action", "verification"),
                "tapl_skip_task": ("result",),
                "tapl_add_finding": ("title", "finding", "source", "impact"),
                "tapl_summarize_run": ("summary",),
                "tapl_finish_run": ("result",),
            }
            for tool_name, fields in prose.items():
                schema = tools[tool_name].input_schema["properties"]
                for field in fields:
                    description = schema[field]["description"]
                    assert "Human-readable text" in description, (tool_name, field)
                    assert "natural word spacing and literal identifiers" in description
            for tool_name, fields in {
                "tapl_apply_plan": ("plan_id", "status", "custom_fields", "session_id"),
                "tapl_create_task": ("task_id", "spec_id", "execution_mode", "executor_kind", "owned_paths"),
                "tapl_summarize_run": ("work_type", "workflow_mode"),
            }.items():
                for field in fields:
                    description = tools[tool_name].input_schema["properties"][field].get("description", "")
                    assert "Human-readable text" not in description

    asyncio.run(exercise())


def test_field_contracts_share_the_natural_language_help_without_changing_technical_help():
    for record, field in (
        ("plan", "objective"), ("task", "action"), ("finding", "finding"), ("approval", "prompt"),
    ):
        help_text = prompt.field_help(record, field)
        assert "Human-readable text" in help_text
        assert help_text in prompt.field_contract_section(record)
    for record, field in (
        ("plan", "id"), ("plan", "status"), ("task", "spec_id"), ("task", "custom_fields"),
        ("finding", "related_ids"), ("approval", "source"),
    ):
        assert prompt.field_help(record, field) == prompt.field_spec(record, field).help


@pytest.mark.parametrize("text", [
    "개발앱설정준비후배포결과를검증한다.",
    "개발 앱 설정을 준비한 뒤 APP_CONFIG_YML 및 /service/dev/app/config 경로를 확인한다.",
    '인용 원문: "개발앱설정준비후검증한다."\n  APP_CONFIG_YML=/service/dev/app/config',
])
def test_writing_guidance_accepts_and_preserves_existing_text_verbatim(tmp_path, text):
    async def exercise():
        async with Client(mcp_server.create_server(workspace_root=_workspace(tmp_path))) as client:
            async def call(name, **arguments):
                result = await client.call_tool(name, arguments)
                assert not result.is_error
                assert result.structured_content["ok"]
                return result.structured_content

            await call("tapl_get_next")
            plan = await call("tapl_apply_plan", plan_id="PLAN-001", title="기존 입력 보존", objective=text)
            task = await call(
                "tapl_create_task", task_id="TASK-001", title="입력 원문 확인", spec_id="PLAN-001",
                goal=text, action=text, verification="입력 원문과 비교한다.",
            )
            for written, fields in ((plan, ("objective",)), (task, ("goal", "action"))):
                detail = await call("tapl_get_item", item_id=written["item"]["id"])
                for field in fields:
                    assert detail["item"][field] == text
                assert text in detail["item"]["body"]

    asyncio.run(exercise())
