from __future__ import annotations

import asyncio
import copy
from pathlib import Path
from unittest import mock

import pytest
from mcp import Client

from taplctl import db, mcp_server
from taplctl.application import WorkflowApplicationError


def _payload(kind: str, *, empty: bool = False) -> dict:
    fields = {
        name: "" if empty else f"  {name}: retained 내용\nsecond line  "
        for _, name in db.markdown_body_fields(kind)
    }
    renderer = db.render_plan_body if kind == "plan" else db.render_task_body
    return {
        "ok": True,
        "extra": {"preserved": True},
        "item": {
            "id": 1,
            "stable_id": "PLAN-001" if kind == "plan" else "TASK-001",
            "kind": kind,
            "title": "Full item contract",
            "status": "Blocked",
            "raw_text": "Original imported text with extra details",
            "custom_fields": {"extension": [None, {"value": "custom data"}]},
            "future_field": {"untouched": True},
            **fields,
            "body": renderer(**fields),
        },
    }


@pytest.mark.parametrize("kind", ["plan", "task"])
@pytest.mark.parametrize("empty", [False, True])
def test_compact_removes_only_exact_generated_body_without_mutating_payload(kind: str, empty: bool) -> None:
    payload = _payload(kind, empty=empty)
    original = copy.deepcopy(payload)

    compact = mcp_server.compact_item_payload(payload)

    expected = copy.deepcopy(original)
    del expected["item"]["body"]
    assert compact == expected
    assert payload == original
    assert compact is not payload
    assert compact["item"] is not payload["item"]
    renderer = db.render_plan_body if kind == "plan" else db.render_task_body
    assert renderer(**{
        name: compact["item"][name] for _, name in db.markdown_body_fields(kind)
    }) == original["item"]["body"]


@pytest.mark.parametrize("kind", ["plan", "task"])
@pytest.mark.parametrize("body_change", ["custom", "suffix", "whitespace", "stale", "absent", "null", "object"])
def test_compact_preserves_custom_stale_and_malformed_bodies(kind: str, body_change: str) -> None:
    payload = _payload(kind)
    item = payload["item"]
    if body_change == "custom":
        item["body"] = "User-authored text without generated sections"
    elif body_change == "suffix":
        item["body"] += "\n\n### Custom section\nUnique information"
    elif body_change == "whitespace":
        item["body"] += "\n"
    elif body_change == "stale":
        item[db.markdown_body_fields(kind)[0][1]] = "Updated canonical value"
    elif body_change == "absent":
        del item["body"]
    elif body_change == "null":
        item["body"] = None
    else:
        item["body"] = {"malformed": "retain me"}
    original = copy.deepcopy(payload)

    assert mcp_server.compact_item_payload(payload) == original
    assert payload == original


@pytest.mark.parametrize("kind", ["plan", "task"])
@pytest.mark.parametrize("invalid", [None, 0, False, [], {}])
def test_compact_requires_every_canonical_field_to_be_present_and_string(kind: str, invalid: object) -> None:
    for _, name in db.markdown_body_fields(kind):
        payload = _payload(kind, empty=True)
        payload["item"][name] = invalid
        original = copy.deepcopy(payload)
        assert mcp_server.compact_item_payload(payload) == original
        assert payload == original
        del payload["item"][name]
        missing = copy.deepcopy(payload)
        assert mcp_server.compact_item_payload(payload) == missing
        assert payload == missing


@pytest.mark.parametrize("kind", ["finding", "unknown", "spec", None, ["task"]])
def test_compact_retains_finding_and_unknown_kind_content(kind: object) -> None:
    payload = _payload("task")
    payload["item"]["kind"] = kind
    payload["item"]["impact"] = "Finding-specific impact"
    original = copy.deepcopy(payload)
    assert mcp_server.compact_item_payload(payload) == original
    assert payload == original


@pytest.mark.parametrize("payload", [
    {}, {"ok": False}, {"ok": True}, {"ok": True, "item": None},
    {"ok": True, "item": []}, {"ok": True, "item": "raw response"},
    {"ok": False, "item": _payload("task")["item"], "error": "failure"},
])
def test_compact_preserves_error_and_malformed_envelopes(payload: dict) -> None:
    original = copy.deepcopy(payload)
    assert mcp_server.compact_item_payload(payload) == original
    assert payload == original


@pytest.mark.parametrize("kind", ["plan", "task", "finding"])
def test_get_item_mcp_default_and_false_are_exact_full_responses(tmp_path: Path, kind: str) -> None:
    payload = _payload("task" if kind == "finding" else kind)
    payload["item"]["kind"] = kind
    original = copy.deepcopy(payload)
    (tmp_path / ".git").mkdir()
    with mock.patch.object(mcp_server, "WorkflowApplication") as application_factory:
        application = application_factory.return_value
        application.get_item.return_value = payload
        server = mcp_server.create_server(workspace_root=tmp_path)

        async def exercise() -> None:
            tools = await server.list_tools()
            assert len(tools) == 29
            tool = next(tool for tool in tools if tool.name == "tapl_get_item")
            assert tool.annotations.read_only_hint
            assert tool.input_schema["required"] == ["item_id"]
            assert tool.input_schema["properties"]["compact"]["default"] is False
            assert tool.input_schema["properties"]["compact"]["type"] == "boolean"
            async with Client(server) as client:
                for arguments in ({"item_id": 1}, {"item_id": 1, "compact": False}):
                    result = await client.call_tool("tapl_get_item", arguments)
                    assert not result.is_error
                    assert result.structured_content == original
                compact = await client.call_tool("tapl_get_item", {"item_id": 1, "compact": True})
                assert not compact.is_error
                expected = copy.deepcopy(original)
                if kind != "finding":
                    del expected["item"]["body"]
                assert compact.structured_content == expected
                # A compact read cannot change a subsequent full read.
                full = await client.call_tool("tapl_get_item", {"item_id": 1})
                assert full.structured_content == original

        asyncio.run(exercise())
        assert application.get_item.call_args_list == [mock.call(1)] * 4
    assert payload == original


def test_get_item_mcp_compact_preserves_application_errors(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    with mock.patch.object(mcp_server, "WorkflowApplication") as application_factory:
        application_factory.return_value.get_item.side_effect = WorkflowApplicationError("item not found: 999")
        server = mcp_server.create_server(workspace_root=tmp_path)

        async def exercise() -> None:
            async with Client(server) as client:
                results = [
                    await client.call_tool("tapl_get_item", arguments)
                    for arguments in (
                        {"item_id": 999},
                        {"item_id": 999, "compact": False},
                        {"item_id": 999, "compact": True},
                    )
                ]
                assert all(result.is_error for result in results)
                assert results[0].content == results[1].content == results[2].content
                assert "item not found: 999" in results[0].content[0].text

        asyncio.run(exercise())


@pytest.mark.parametrize("archived", [False, True])
def test_compact_reads_real_stored_records_without_losing_content(tmp_path: Path, archived: bool) -> None:
    from taplctl.application import WorkflowApplication

    (tmp_path / ".git").mkdir()
    db.initialize_workspace(tmp_path)
    (tmp_path / ".tapl/config.toml").write_text('[recall]\nenabled=false\n')
    app = WorkflowApplication(tmp_path)
    app.summarize_run("Synthetic compact contract", work_type="implementation", workflow_mode="standard")
    plan = app.apply_plan("PLAN-001", title="Preserve content", status="Finalized", objective="Keep all bytes")
    task = app.create_task("TASK-001", "Read contract", "PLAN-001", "Read only", "Inspect fixture", "Compare exact bytes")
    finding = app.add_finding("Original finding", finding="Unique primary body", source="fixture", impact="Preserve")
    app.record_approval(decision="approved", prompt="Synthetic fixture", source="explicit_user")
    app.start_task("TASK-001")
    app.settle_task("TASK-001", status="Completed", verification="Compared fixture", result="Preserved")
    if archived:
        app.finish_run("Synthetic fixture complete")
        app.finish_archive("compact-source")
    ids = [r["item"]["id"] for r in (plan, task, finding)]
    originals = [app.get_item(item_id) for item_id in ids]

    async def exercise():
        async with Client(mcp_server.create_server(workspace_root=tmp_path)) as client:
            for item_id, original in zip(ids, originals):
                full = (await client.call_tool("tapl_get_item", {"item_id": item_id})).structured_content
                compact = (await client.call_tool("tapl_get_item", {"item_id": item_id, "compact": True})).structured_content
                again = (await client.call_tool("tapl_get_item", {"item_id": item_id, "compact": False})).structured_content
                assert full == original == again
                expected = copy.deepcopy(original)
                if original["item"]["kind"] in {"plan", "task"}:
                    del expected["item"]["body"]
                assert compact == expected
            with db.connect(tmp_path / ".tapl/tapl.db") as conn:
                conn.execute("UPDATE items SET body=? WHERE id=?", ("User-authored extra content", ids[1]))
            custom = (await client.call_tool("tapl_get_item", {"item_id": ids[1], "compact": True})).structured_content
            assert custom == app.get_item(ids[1])
            assert custom["item"]["body"] == "User-authored extra content"

    asyncio.run(exercise())


@pytest.mark.parametrize("error_count", [1, 4])
def test_compact_validation_never_hides_errors_behind_warnings(error_count: int) -> None:
    warnings = [{"severity": "warning", "code": f"warning-{i}", "message": "Pending dependency"} for i in range(4)]
    errors = [{"severity": "error", "code": f"blocker-{i}", "message": "Cannot execute", "remediation": "Recover first"}
              for i in range(error_count)]
    payload = {"ok": False, "issues": warnings + errors}
    original = copy.deepcopy(payload)
    compact = mcp_server.compact_validation_receipt(payload)
    assert compact["ok"] is False
    assert [i for i in compact["issues"] if i["severity"] == "error"] == errors
    assert compact["issues"][:error_count] == errors
    assert compact["issue_count"] == 4 + error_count
    assert compact["omitted_issue_count"] == len(payload["issues"]) - len(compact["issues"])
    assert payload == original
