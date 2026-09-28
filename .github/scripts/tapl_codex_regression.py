"""One real Codex condition per disposable morae-mcp Linux Box.

The caller supplies an installed checkout, normal CLI authentication, and a fresh
Box for EVERY invocation. Never run this on the host. Evidence excludes auth.
"""
from __future__ import annotations

import argparse
import ast
from datetime import datetime
import json
import os
import re
import shlex
from pathlib import Path
import shutil
import signal
import sqlite3
import subprocess
import sys
import threading
import time

from taplctl import install
from taplctl.application import WorkflowApplication


PROMPTS = {
    "scout": "저장소의 주 문서에 철자 오류가 있는지 조사해주세요. 읽기 전용 SubAgent 한 명에게 탐색을 맡기고, 근거와 확인한 범위를 받아 결과만 보고해주세요. 파일 수정이나 테스트 실행은 승인하지 않습니다. 확인 후 완료 처리해주세요.",
    "inspection": "README.md에 철자 오류가 있는지만 확인하고 발견한 내용만 알려주세요. 파일 수정이나 구현 계획은 필요 없습니다. 읽기 전용 확인을 마치고 완료 처리해주세요.",
    "edit": "README.md의 transactoin 오타를 transaction으로 고쳐주세요. 다른 변경은 필요 없습니다. 수정하고 결과를 검증한 뒤 작업을 완료 처리해주세요.",
    "recall": "README.md의 transactoin 오타를 transaction으로 고쳐주세요. 다른 변경은 필요 없습니다. 수정하고 결과를 검증한 뒤 작업을 완료 처리해주세요.",
    "planning": "README.md 소개 문구를 개선하는 계획만 세워주세요. 파일 수정과 실행은 아직 승인하지 않습니다. 계획을 보고하고 다음 지시를 기다려주세요.",
    "resume": "이전 TAPL 작업을 이어서 완료해주세요. 저장된 계획과 작업 내용을 확인해서 승인된 수정과 검증을 진행해주세요.",
    "delegation": "alpha.txt의 alhpa를 alpha로, beta.txt의 btea를 beta로 각각 수정해주세요. 두 수정은 서로 독립적입니다. 필요한 수정과 검증, SubAgent 병렬 실행을 승인합니다. 각 결과를 확인하고 전체 작업을 완료 처리해주세요.",
    "topics": "서로 다른 두 주제를 처리해주세요. 첫째 README.md의 transactoin 오타를 transaction으로 수정합니다. 둘째 .editorconfig의 indent_size를 4에서 2로 변경합니다. 두 주제는 별도 계획으로 관리해주세요. 필요한 수정과 검증을 승인하며, 검증 후 전체 작업을 완료 처리해주세요.",
    "memory_reuse": "README.md의 transactoin 오타를 transaction으로 고쳐주세요. 기존 README 검증 기억이 있으면 원문을 확인하고 적용해 검증해주세요. 필요한 수정과 검증을 승인합니다. 실제 사용한 기억을 기록하고 작업을 완료 처리해주세요.",
    "batch_recovery": "alpha.txt의 alhpa→alpha, beta.txt의 btea→beta 병렬 작업이 dispatch 후 실제 SubAgent 생성 전에 중단되었습니다. 저장된 batch와 실행 ID를 확인하고 recover_batch로 복구한 뒤 같은 작업들을 Root 순차 실행으로 전환해 수정·검증해주세요. 이 복구와 순차 전환, 실행을 승인합니다. 새 SubAgent는 필요하지 않습니다. 전체 작업을 완료 처리해주세요.",
    "context_loss": "이전 세션에서 저장한 README.md 오타 수정 계획을 이어서 실행해주세요. 이 세션에는 이전 대화가 없습니다. 저장된 계획과 작업을 확인한 다음 transactoin을 transaction으로 수정하고 검증하는 실행을 승인합니다. 작업을 완료 처리해주세요.",
}

CONTEXT_SETUP_PROMPT = (
    "README.md의 transactoin을 transaction으로 수정할 계획과 작업을 TAPL에 저장해주세요. "
    "계획은 확정하되 실제 수정과 실행은 아직 승인하지 않습니다. 저장한 뒤 다음 지시를 기다려주세요."
)


def read_events(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.startswith("{")]


def completed_calls(events):
    return [e["item"] for e in events if e.get("type") == "item.completed"
            and e.get("item", {}).get("type") == "mcp_tool_call"]


def structured_result(call):
    result = call.get("result") or {}
    value = result.get("structured_content") or result.get("structuredContent")
    if isinstance(value, dict):
        return value
    for block in result.get("content", []):
        try:
            value = json.loads(block.get("text", ""))
        except (ValueError, TypeError):
            continue
        if isinstance(value, dict):
            return value
    return {}


def successful_call(call):
    result = call.get("result") or {}
    return (call.get("status") == "completed" and not result.get("isError")
            and not result.get("is_error") and structured_result(call).get("ok") is True)


def original_source_delivered(call, seed):
    from taplctl import db
    value = structured_result(call)
    records = [value.get("item", {})] if call["tool"] == "tapl_get_item" else value.get("items", [])
    for item in records:
        if item.get("id") != seed.get("source_item_id") or item.get("run_id") != seed.get("source_run_id"):
            continue
        body = item.get("body")
        if body is None and item.get("kind") == "task":
            fields = {key: item.get(key) for _, key in db.markdown_body_fields("task")}
            if all(isinstance(v, str) for v in fields.values()):
                body = db.render_task_body(**fields)
        if body == seed.get("source_body") and isinstance(body, str) and body:
            return True
    return False


def exact_byte_verification(command):
    """Recognize this fixture's executed top-level Python equality assertion.

    Not a general shell/program verifier. Unfamiliar equivalent code needs trace
    review; quoted output, substring checks and dead function bodies do not pass.
    """
    try:
        words = shlex.split(command)
        if len(words) == 3 and Path(words[0]).name in {"sh", "bash", "zsh", "dash", "ksh"} and words[1] in {"-c", "-lc"}:
            command = words[2]
            words = shlex.split(command)
    except ValueError:
        return False
    scripts = []
    for match in re.finditer(r"(?:^|\n|&&\s*)(?:[\w/.-]*/)?python[\d.]*\s+-\s*<<\s*['\"]?(\w+)['\"]?\s*\n(.*?)\n\1(?:\n|$)", command, re.S):
        scripts.append(match.group(2))
    for i, word in enumerate(words[:-2]):
        if ((i == 0 or words[i - 1] in {";", "&&"})
                and re.fullmatch(r"(?:[\w/.-]*/)?python[\d.]*", word) and words[i + 1] == "-c"):
            scripts.append(words[i + 2])
    if command.lstrip().startswith(("assert ", "from pathlib ")):
        scripts.append(command)  # Unwrapped Python in synthetic evaluator fixtures.
    actual = object()
    expected = b"# Example\n\nAn atomic transaction.\n"
    for script in scripts:
        try:
            tree = ast.parse(script)
        except SyntaxError:
            continue
        values = {}
        def value(node):
            if isinstance(node, ast.Constant):
                return node.value
            if isinstance(node, ast.Name):
                return values.get(node.id)
            if isinstance(node, ast.Call) and not node.keywords and isinstance(node.func, ast.Attribute):
                owner = node.func.value
                if (node.func.attr == "read_bytes" and not node.args and isinstance(owner, ast.Call)
                        and len(owner.args) == 1 and isinstance(owner.args[0], ast.Constant)
                        and owner.args[0].value in {"README.md", "/case/README.md"}):
                    return actual
                if node.func.attr == "encode" and not node.args and isinstance(value(owner), str):
                    return value(owner).encode()
            return None
        for statement in tree.body:
            if isinstance(statement, ast.Assign):
                for target in statement.targets:
                    if isinstance(target, ast.Name):
                        values[target.id] = value(statement.value)
            if isinstance(statement, ast.Assert) and isinstance(statement.test, ast.Compare):
                test = statement.test
                if len(test.ops) == 1 and isinstance(test.ops[0], ast.Eq):
                    left, right = value(test.left), value(test.comparators[0])
                    if (left is actual and right == expected) or (right is actual and left == expected):
                        return True
    return False


def project_edits(events):
    """Fixture-scoped modifying receipts with actual start/completion indices."""
    starts = {e.get("item", {}).get("id"): i for i, e in enumerate(events) if e.get("type") == "item.started"}
    edits = []
    for end, event in enumerate(events):
        item = event.get("item", {})
        if event.get("type") != "item.completed":
            continue
        paths = []
        if item.get("type") == "file_change":
            paths = [change.get("path", "") for change in item.get("changes", [])]
        elif item.get("type") == "command_execution":
            command = item.get("command", "")
            if re.search(r"write_(?:text|bytes)|apply_patch|\btee\b|\bsed\b[^\n]*\s-i|\bperl\b[^\n]*-[^\s]*i|(?<!>)>(?!>)|>>", command):
                paths = [name for name in ("README.md", "alpha.txt", "beta.txt") if name in command]
        if paths:
            edits.append({"start": starts.get(item.get("id"), end), "end": end, "paths": paths,
                          "verified_start": item.get("id") is not None and item.get("id") in starts})
    return edits


def entry_errors(events):
    """Every genuinely fresh session must fetch the full policy before work."""
    calls = completed_calls(events)
    errors = []
    if not calls or calls[0]["tool"] != "tapl_get_next":
        errors.append("Fresh session did not enter through tapl_get_next")
        return errors
    if any(key in calls[0].get("arguments", {}) for key in
           ("known_policy_revision", "available_models", "catalog_complete")):
        errors.append("Fresh session reused retained policy or catalog arguments")
    entry = structured_result(calls[0])
    if (not successful_call(calls[0]) or not isinstance(entry.get("config"), dict)
            or not all(isinstance(entry.get(k), str) and entry[k].strip()
                       for k in ("workflow_policy", "subagent_guidance", "policy_revision"))
            or entry.get("policy_unchanged") is not False):
        errors.append("Fresh session did not successfully receive the complete policy bundle")
    policy_end = next(i for i, e in enumerate(events) if e.get("type") == "item.completed"
                      and e.get("item", {}).get("tool") == "tapl_get_next")
    if any(not instruction_discovery(e["item"]) for e in events[:policy_end]
           if e.get("type") == "item.started" and e.get("item", {}).get("type") in
           {"command_execution", "file_change", "collab_agent_tool_call"}):
        errors.append("Fresh session performed project work before full policy entry")
    return errors


def rollout_metrics(directory):
    """Usage-only projection; never retain or report account rate-limit fields.

    token_count can be repeated without another model request. Count distinct
    cumulative usage tuples within each root session and measure last-token
    input separately. Missing cached-token accounting remains null, not zero.
    """
    summaries = []
    for path in sorted(directory.glob("*.jsonl")):
        rows = read_events(path)
        meta = next((r.get("payload", {}) for r in rows if r.get("type") == "session_meta"), {})
        if meta.get("parent_thread_id"):
            continue
        seen, inputs, outputs, cached, input_sizes = set(), 0, 0, None, []
        calls, discovery_ids = [], set()
        for row in rows:
            payload = row.get("payload", {})
            if payload.get("type") == "token_count":
                info = payload.get("info") or {}
                total, last = info.get("total_token_usage") or {}, info.get("last_token_usage") or {}
                # Cached/reasoning metadata can be enriched for the same request.
                # Exclude zero initialization and count substantive usage updates.
                signature = (total.get("input_tokens", 0), total.get("output_tokens", 0))
                if any(isinstance(value, int) and value > 0 for value in signature):
                    seen.add(signature)
                    inputs = max(inputs, total.get("input_tokens", 0))
                    outputs = max(outputs, total.get("output_tokens", 0))
                    cached = total.get("cached_input_tokens") if isinstance(total.get("cached_input_tokens"), int) else None
                if isinstance(last.get("input_tokens"), int):
                    input_sizes.append(last["input_tokens"])
            if row.get("type") == "response_item" and payload.get("type") in {"function_call", "custom_tool_call"}:
                calls.append(payload)
                body = payload.get("input", payload.get("arguments", ""))
                if "tool_search" in payload.get("name", "") or "ALL_TOOLS" in body:
                    discovery_ids.add(payload.get("call_id"))
        discovery_bytes = sum(len((p.get("output") if isinstance(p.get("output"), str)
                                   else json.dumps(p.get("output"), ensure_ascii=False)).encode("utf-8"))
                              for row in rows for p in [row.get("payload", {})]
                              if p.get("type") in {"function_call_output", "custom_tool_call_output"}
                              and p.get("call_id") in discovery_ids)
        summaries.append({"session_id": meta.get("id"), "model_requests": len(seen),
                          "input_tokens": inputs, "cached_input_tokens": cached, "output_tokens": outputs,
                          "max_single_input_tokens": max(input_sizes, default=None),
                          "exec_calls": sum(p.get("name", "").split(".")[-1] in {"exec", "exec_command"} for p in calls),
                          "tool_discovery_calls": len(discovery_ids), "tool_discovery_output_bytes": discovery_bytes})
    return {"method": "nonzero distinct cumulative input/output usage updates per root session; model_requests is an estimate; excludes child sessions",
            "sessions": summaries,
            **{key: sum(s[key] for s in summaries) for key in
               ("model_requests", "input_tokens", "output_tokens", "exec_calls", "tool_discovery_calls", "tool_discovery_output_bytes")},
            "cached_input_tokens": sum(s["cached_input_tokens"] for s in summaries)
            if summaries and all(s["cached_input_tokens"] is not None for s in summaries) else None,
            "max_single_input_tokens": max((s["max_single_input_tokens"] for s in summaries
                                            if s["max_single_input_tokens"] is not None), default=None)}


def run(*args, cwd=None):
    subprocess.run(args, cwd=cwd, check=True, stdout=subprocess.DEVNULL)


def instruction_discovery(item):
    """Permit only harmless metadata lookups needed to locate fixture AGENTS.md.

    This exception cannot read source contents, launch helpers, or write files.
    All accepted commands are retained in result.json for manual trace review.
    """
    if item.get("type") != "command_execution":
        return False
    parts = shlex.split(item.get("command", ""))
    body = parts[-1] if len(parts) == 3 and parts[1] in {"-c", "-lc"} else item.get("command", "")
    body = body.replace("2>/dev/null", "")
    if any(token in body for token in ("\n", "`", "$", ">", "<", "|")):
        return False
    for segment in re.split(r"&&|;", body):
        words = shlex.split(segment)
        if words == ["pwd"]:
            continue
        if words and words[0] == "rg" and "--files" in words and any("AGENTS.md" in word for word in words):
            continue
        if words and words[0] == "ls" and any("AGENTS.md" in word for word in words) and all(
            word in {"-l", "-a", "-la", "-al"} or Path(word).name in {"AGENTS.md", "README.md"} for word in words[1:]
        ):
            continue
        return False
    return True


def delegation_evidence(directory):
    """Codex 0.153 emits collaboration in rollouts, not exec's JSON item stream.

    Link a successful spawn receipt to its actual child session and completion.
    Retain synthetic commands for human ownership/verification review; do not
    inspect encrypted handoffs or copy full session metadata into the summary.
    """
    sessions = []
    for path in directory.glob("*.jsonl"):
        rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
        meta = next((row["payload"] for row in rows if row["type"] == "session_meta"), {})
        sessions.append((meta, rows))
    evidence = []
    for parent, rows in sessions:
        if parent.get("parent_thread_id"):
            continue
        outputs = {row["payload"].get("call_id"): row["payload"].get("output", "") for row in rows
                   if row["type"] == "response_item" and row["payload"].get("type") == "function_call_output"}
        for row in rows:
            payload = row.get("payload", {})
            if payload.get("type") != "function_call" or payload.get("name") != "spawn_agent":
                continue
            arguments = json.loads(payload["arguments"])
            try:
                receipt = json.loads(outputs.get(payload["call_id"], "{}"))
            except ValueError:
                continue
            path = receipt.get("task_name")
            if not path:
                continue
            for child, child_rows in sessions:
                if child.get("parent_thread_id") != parent.get("id") or child.get("agent_path") != path:
                    continue
                completed = [r["payload"] for r in child_rows if r.get("payload", {}).get("type") == "task_complete"]
                outputs_by_id = {r["payload"].get("call_id"): r["payload"].get("output") for r in child_rows
                                 if r.get("payload", {}).get("type") in {"function_call_output", "custom_tool_call_output"}}
                child_calls = [{"call_id": r["payload"].get("call_id"),
                                "command": " ".join((r["payload"].get("namespace", ""), r["payload"].get("name", ""),
                                                     r["payload"].get("input", r["payload"].get("arguments", "")))),
                                "output": outputs_by_id.get(r["payload"].get("call_id"))} for r in child_rows
                               if r["type"] == "response_item" and r["payload"].get("type") in {"function_call", "custom_tool_call"}]
                evidence.append({"agent_path": path, "child_id": child["id"], "parent_id": parent["id"],
                                 "model": arguments.get("model"), "effort": arguments.get("reasoning_effort"),
                                 "fork_turns": arguments.get("fork_turns"), "completed": bool(completed),
                                 "commands": [c["command"] for c in child_calls], "calls": child_calls,
                                 "spawn_at": payload.get("internal_chat_message_metadata_passthrough", {}).get("create_time"),
                                 "started_at": completed[-1].get("started_at") if completed else None,
                                 "completed_at": completed[-1].get("completed_at") if completed else None,
                                 "result": completed[-1].get("last_agent_message") if completed else None})
    return evidence


def command_exit_codes(output):
    """Parse tool result records; never search text printed by a command for exit codes."""
    if isinstance(output, str):
        try:
            return command_exit_codes(json.loads(output))
        except ValueError:
            return []
    if isinstance(output, list):
        return [code for block in output if isinstance(block, dict)
                for code in command_exit_codes(block.get("text"))]
    if isinstance(output, dict) and isinstance(output.get("exit_code"), int):
        return [output["exit_code"]]
    # functions.exec may expose Promise.allSettled results. Traverse only
    # these orchestration wrappers, never a shell command's output string.
    if isinstance(output, dict):
        settled = output.get("result", output)
        if isinstance(settled, dict) and settled.get("status") == "rejected":
            return [-1]
        if isinstance(settled, dict) and settled.get("status") == "fulfilled":
            value = settled.get("value")
            if isinstance(value, dict) and isinstance(value.get("exit_code"), int):
                return [value["exit_code"]]
            return [-1]  # A fulfilled tool call without an exit receipt is unverified.
    return []


def scenario_audit(directory, condition, conn):
    """Fail closed on missing recovery/source receipts for the added scenarios."""
    if condition not in {"memory_reuse", "batch_recovery", "context_loss"}:
        return []
    errors = []
    seed_path, events_path = directory / "scenario.json", directory / "events.jsonl"
    if not seed_path.exists() or not events_path.exists():
        return ["Missing scenario seed or live-session evidence"]
    seed, events = json.loads(seed_path.read_text()), read_events(events_path)
    calls = completed_calls(events)
    errors.extend(entry_errors(events))
    successful = [c for c in calls if successful_call(c)]
    if condition == "memory_reuse":
        source_calls = [c for c in successful if
                        ((c["tool"] == "tapl_get_archive" and c.get("arguments", {}).get("archive_id") == seed["source_archive_id"])
                        or (c["tool"] == "tapl_get_item" and seed.get("source_item_id") is not None
                            and c.get("arguments", {}).get("item_id") == seed["source_item_id"]))
                        and original_source_delivered(c, seed)]
        if not source_calls:
            errors.append("Memory reuse lacks an original get_item/get_archive source lookup")
        recalls = [structured_result(c).get("recall", structured_result(c)) for c in successful
                   if c["tool"] in {"tapl_summarize_run", "tapl_recall"}]
        if not any(any(m.get("id") == seed["memory_id"] for m in r.get("memories", [])) for r in recalls):
            errors.append("Seeded memory was not recalled")
        uses = [use for c in successful if c["tool"] == "tapl_finish_run"
                for use in c.get("arguments", {}).get("memory_uses", [])
                if use.get("memory_id") == seed["memory_id"] and use.get("source_checked") is True
                and use.get("revision") == seed["memory_revision"] and use.get("usage", "").strip()]
        if not uses:
            errors.append("Missing exact source-checked memory reuse receipt")
        # This scenario's source contract requires byte-for-byte validation.
        # A claimed memory use alone cannot substitute for successful execution.
        source_index = next((i for i, e in enumerate(events) if e.get("type") == "item.completed"
                             and e.get("item") in source_calls), len(events))
        finish_index = next((i for i, e in enumerate(events) if e.get("type") == "item.completed"
                             and e.get("item", {}).get("tool") == "tapl_finish_run"), len(events))
        starts = {e.get("item", {}).get("id"): i for i, e in enumerate(events) if e.get("type") == "item.started"}
        commands = [e["item"].get("command", "") for e in events[source_index + 1:finish_index]
                    if e.get("type") == "item.completed" and e.get("item", {}).get("type") == "command_execution"
                    and e["item"].get("exit_code") == 0
                    and source_index < starts.get(e["item"].get("id"), -1) < finish_index]
        if not any(exact_byte_verification(command) for command in commands):
            errors.append("No successful source-derived byte verification before memory reuse")
        row = conn.execute("SELECT source_run_id FROM memories WHERE memory_id=?", (seed["memory_id"],)).fetchone()
        if row is None or row["source_run_id"] != seed["source_run_id"]:
            errors.append("Seeded memory source was replaced")
    elif condition == "batch_recovery":
        recovery = next((c for c in successful if c["tool"] == "tapl_recover_batch"
                         and c.get("arguments", {}).get("batch_id") == seed["batch_id"]), None)
        if recovery is None:
            errors.append("Interrupted batch did not recover its exact persisted batch ID")
        elif any(c["tool"] in {"tapl_start_task", "tapl_complete_task", "tapl_dispatch_tasks"}
                 for c in calls[:calls.index(recovery)]):
            errors.append("Recovery task work preceded cancellation of the interrupted batch")
        if recovery is not None:
            recovery_end = next(i for i, e in enumerate(events) if e.get("type") == "item.completed" and e.get("item") == recovery)
            edits = project_edits(events)
            if any(not edit["verified_start"] or edit["start"] <= recovery_end for edit in edits):
                errors.append("Project edit preceded successful batch recovery or lacks a start receipt")
            recovered_state = "\n".join(json.dumps(structured_result(c)) for c in successful
                                        if calls.index(c) < calls.index(recovery)
                                        and c["tool"] in {"tapl_get_next", "tapl_get_status"})
            if not all(e["execution_id"] in recovered_state for e in seed["executions"]):
                errors.append("Recovery did not read the original exact execution IDs")
            previous_end = recovery_end
            for task_id, filename in (("TASK-001", "alpha.txt"), ("TASK-002", "beta.txt")):
                boundaries = {tool: next((i for i, e in enumerate(events)
                                         if e.get("type") == "item.completed" and e.get("item", {}).get("tool") == tool
                                         and e["item"].get("arguments", {}).get("task_id") == task_id
                                         and successful_call(e["item"])), None)
                              for tool in ("tapl_start_task", "tapl_complete_task")}
                begin, end = boundaries["tapl_start_task"], boundaries["tapl_complete_task"]
                owned = [edit for edit in edits if any(Path(path).name == filename for path in edit["paths"])]
                if (begin is None or end is None or not previous_end < begin < end or not owned
                        or any(not begin < edit["start"] <= edit["end"] < end for edit in owned)):
                    errors.append(f"Recovery edit escaped sequential task lifecycle: {task_id}")
                if end is not None:
                    previous_end = end
        executions = list(conn.execute("SELECT te.id,te.state,i.stable_id FROM task_executions te "
                                       "JOIN items i ON i.id=te.task_item_id"))
        actual = {e["id"]: (e["stable_id"], e["state"]) for e in executions}
        if actual != {e["execution_id"]: (e["task_id"], "cancelled") for e in seed["executions"]}:
            errors.append("Original execution IDs were replaced, left active, or falsely completed")
        for task_id in ("TASK-001", "TASK-002"):
            task = conn.execute("SELECT i.status,t.execution_mode,t.executor_kind FROM items i "
                                "JOIN tasks t ON t.item_id=i.id WHERE i.stable_id=?", (task_id,)).fetchone()
            if task is None or tuple(task) != ("Completed", "sequential", "main"):
                errors.append(f"Recovery did not complete the authorized sequential transition: {task_id}")
        if delegation_evidence(directory / "rollouts"):
            errors.append("Recovery unexpectedly spawned a helper")
    else:
        setup_path = directory / "setup-events.jsonl"
        if not setup_path.exists():
            return errors + ["Context loss lacks the real first-session transcript"]
        setup = read_events(setup_path)
        errors.extend(entry_errors(setup))
        first_ids = {e.get("thread_id") for e in setup if e.get("type") == "thread.started"}
        second_ids = {e.get("thread_id") for e in events if e.get("type") == "thread.started"}
        if not first_ids or not second_ids or None in first_ids | second_ids or first_ids & second_ids:
            errors.append("Context-loss recovery did not use two distinct real sessions")
        if not any(e.get("type") == "turn.completed" for e in setup):
            errors.append("Context-loss setup session did not finish")
        setup_names = {c["tool"] for c in completed_calls(setup)}
        if not {"tapl_apply_plan", "tapl_create_task"} <= setup_names:
            errors.append("First session did not actually persist its plan and tasks")
        persisted = seed.get("setup_items", [])
        if not persisted or {item.get("kind") for item in persisted} != {"plan", "task"}:
            errors.append("Missing persisted setup plan/task identities")
        saved_ids = {structured_result(c).get("item", {}).get("id") for c in completed_calls(setup)
                     if successful_call(c) and c["tool"] in {"tapl_apply_plan", "tapl_create_task"}}
        for item in persisted:
            row = conn.execute("SELECT id,stable_id,kind,run_id FROM items WHERE id=?", (item["id"],)).fetchone()
            if (item["id"] not in saved_ids or row is None or row["run_id"] != seed.get("run_id")
                    or row["stable_id"] != item["stable_id"] or row["kind"] != item["kind"]):
                errors.append("Fresh session did not preserve a first-session record identity")
        if {"tapl_approve_execution", "tapl_start_task", "tapl_dispatch_tasks", "tapl_finish_run"} & setup_names:
            errors.append("Context-loss setup entered an unapproved execution lifecycle")
        if not seed.get("setup_unchanged") or seed.get("setup_archives") != 0:
            errors.append("Unapproved context-loss setup changed or finished the fixture")
        archived = [r[0] for r in conn.execute("SELECT run_id FROM archives")]
        if archived != [seed.get("run_id")]:
            errors.append("Fresh session replaced the persisted run")
        execution_index = next((i for i, e in enumerate(events) if e.get("type") == "item.started"
                                and (e.get("item", {}).get("tool") in {"tapl_start_task", "tapl_dispatch_tasks"}
                                     or e.get("item", {}).get("type") == "file_change")), len(events))
        execution_index = min([execution_index] + [edit["start"] for edit in project_edits(events)])
        restored_ids = set()
        for call in completed_calls(events[:execution_index]):
            if not successful_call(call):
                continue
            value = structured_result(call)
            records = []
            if call["tool"] == "tapl_get_status" and call.get("arguments", {}).get("full") is True:
                records = value.get("plans", []) + value.get("tasks", [])
            elif call["tool"] == "tapl_get_item":
                records = [value.get("item", {})]
            for item in persisted:
                if any(record.get("id") == item["id"] and (
                    record.get("body") == item["body"] or all(record.get(k) == v for k, v in item["fields"].items())
                ) for record in records):
                    restored_ids.add(item["id"])
        if not persisted or restored_ids != {item["id"] for item in persisted}:
            errors.append("Fresh session did not reload persisted work bodies")
    return errors


def audit_records(directory, condition):
    """Recheck retained evidence, including after an evaluator-only correction.

    This is fixture-specific trace evidence, not a general shell effect analyzer.
    An unfamiliar editing method is flagged for review rather than assumed safe.
    """
    errors, links = [], []
    with sqlite3.connect(f"file:{directory / 'tapl.db'}?mode=ro", uri=True) as conn:
        conn.row_factory = sqlite3.Row
        errors.extend(scenario_audit(directory, condition, conn))
        if condition == "topics":
            plans = list(conn.execute("SELECT * FROM plans"))
            tasks = list(conn.execute("SELECT * FROM tasks"))
            linked = []
            # Typed task actions may identify the concrete replacement instead
            # of repeating the plan's filename. Both identify this fixture's topic.
            for filename, markers in (("README.md", ("README.md", "transactoin", "transaction")),
                                      (".editorconfig", (".editorconfig", "indent_size"))):
                matches = [p for p in plans if filename in p["affected_files"]]
                if len(matches) != 1:
                    errors.append(f"Missing unique plan for {filename}")
                    continue
                plan = matches[0]
                if not any(t["spec_id"] == plan["plan_id"] and any(marker in t["goal"] + t["action"] for marker in markers)
                           for t in tasks):
                    errors.append(f"Missing topic-specific task linked to {plan['plan_id']}")
                linked.append(plan["plan_id"])
            if len(set(linked)) != 2:
                errors.append("Independent topics share a plan")
        if condition == "scout":
            children = delegation_evidence(directory / "rollouts")
            if len(children) != 1 or not children[0]["completed"]:
                errors.append("Missing one completed observation helper")
            for child in children:
                text = "\n".join(child["commands"])
                calls = re.findall(r"\btapl_([a-z_]+)\b", text.replace("mcp__tapl__", ""))
                readonly = {"get_next", "get_status", "validate_state", "get_context", "search_history",
                            "recall", "get_memory", "get_item", "list_archives", "get_archive"}
                if any(name not in readonly for name in calls):
                    errors.append("Observation helper wrote TAPL state")
                if re.search(r"\b(spawn_agent|apply_patch|write_text|write_bytes|pytest|unittest|touch|mkdir|rm)\b"
                             r"|\bsed\b[^\n]*\s-i\b|\b(?:npm|pnpm|yarn|bun)\s+(?:run\s+)?test\b", text):
                    errors.append("Observation helper attempted delegation, mutation or tests")
                if not any("README.md" in c["command"] and command_exit_codes(c["output"])
                           and all(code == 0 for code in command_exit_codes(c["output"])) for c in child["calls"]):
                    errors.append("Missing successful helper document lookup")
        if condition == "delegation":
            children = delegation_evidence(directory / "rollouts")
            executions = list(conn.execute("SELECT te.*, t.task_id, t.owned_paths_json FROM task_executions te "
                                           "JOIN tasks t ON t.item_id=te.task_item_id"))
            readonly = {"get_next", "get_status", "validate_state", "get_context", "search_history",
                        "recall", "get_memory", "get_item", "list_archives", "get_archive"}
            for child in children:
                text = "\n".join(child["commands"])
                calls = re.findall(r"\btapl_([a-z_]+)\b", text.replace("mcp__tapl__", ""))
                if any(name not in readonly for name in calls):
                    errors.append(f"Child wrote TAPL state: {child['agent_path']}")
                files = {name for name in ("alpha.txt", "beta.txt") if name in text}
                matches = [e for e in executions if {Path(p).name for p in json.loads(e["owned_paths_json"])} == files]
                if len(files) != 1 or len(matches) != 1:
                    errors.append(f"Child lacks unique manifest ownership: {child['agent_path']}")
                    continue
                execution = matches[0]
                successful = "\n".join(c["command"] for c in child["calls"]
                                       if command_exit_codes(c["output"]) and all(code == 0 for code in command_exit_codes(c["output"])))
                if not (re.search(r"write_(?:bytes|text)|sed[^\n]*-i", successful)
                        and re.search(r"assert|\bcmp\b|\bdiff\b", successful)):
                    errors.append(f"Review actual child edit/verification evidence: {child['agent_path']}")
                settled = datetime.fromisoformat(execution["finished_at"]).timestamp() if execution["finished_at"] else 0
                if not child["completed_at"] or settled < child["completed_at"]:
                    errors.append(f"Settlement preceded child completion: {child['agent_path']}")
                links.append({"agent_path": child["agent_path"], "task_id": execution["task_id"],
                              "execution_id": execution["id"], "owned_files": sorted(files)})
            if len({link["execution_id"] for link in links}) != 2:
                errors.append("Missing two distinct child-to-execution links")
            if len(children) == 2:
                if (not all(c["started_at"] and c["completed_at"] for c in children)
                        or max(c["started_at"] for c in children) >= min(c["completed_at"] for c in children)):
                    errors.append("Actual child execution intervals did not overlap")
            settlement_times = [datetime.fromisoformat(e["finished_at"]).timestamp() for e in executions if e["finished_at"]]
            if len(settlement_times) != len(executions):
                errors.append("Unsettled execution remains")
            if children and settlement_times:
                first_settlement = min(settlement_times)
                if any(not c["spawn_at"] or c["spawn_at"] >= first_settlement for c in children):
                    errors.append("Children were not both launched before settlement")
    return {"errors": errors, "links": links, "passed": not errors}


def execute_session(command, output, prefix=""):
    """Run one real session. A second invocation has no prior transcript input."""
    timed_out = threading.Event()
    with (output / f"{prefix}events.jsonl").open("w") as stdout, (output / f"{prefix}stderr.log").open("w") as stderr:
        process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                   stderr=stderr, text=True, start_new_session=True)
        def expire():
            timed_out.set()
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        timer = threading.Timer(840, expire)
        timer.start()
        try:
            for line in process.stdout:
                stdout.write(line)
                stdout.flush()
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                item = event.get("item", {})
                if event.get("type") in {"turn.failed", "error", "turn.completed"}:
                    print(json.dumps({"phase": prefix or "main", "event": event.get("type"), "usage": event.get("usage")}), flush=True)
                elif event.get("type") == "item.completed" and item.get("type") == "mcp_tool_call":
                    print(json.dumps({"phase": prefix or "main", "tool": item.get("tool"), "status": item.get("status")}), flush=True)
            process.wait(timeout=30)
        finally:
            timer.cancel()
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
    return process.returncode, timed_out.is_set()


def seed_memory(root):
    app = WorkflowApplication(root)
    source = app.summarize_run("README transaction byte verification", work_type="implementation", workflow_mode="standard")["active_run"]["id"]
    contract = ("README 검증 계약: Python pathlib.Path('README.md').read_bytes()를 사용하여 "
                "b'# Example\\n\\nAn atomic transaction.\\n'와 정확히 일치하는지 assert한다. 마지막 개행과 다른 바이트도 보존한다.")
    app.apply_plan("PLAN-901", title="Synthetic verification contract", objective="Preserve every unrelated byte", status="Finalized")
    source_item = app.create_task("TASK-901", "README byte verification contract", "PLAN-901",
                                  "Record the synthetic verification contract", contract, contract)["item"]["id"]
    app.record_approval(decision="approved", prompt="Synthetic fixture setup", source="explicit_user")
    app.start_task("TASK-901")
    app.settle_task("TASK-901", status="Completed", verification=contract, result="Synthetic known fixture contract recorded")
    result = app.finish_run(
        contract,
        expected_run_id=source, memory_candidates=[{
            "slot": 1, "cue": ["README", "transaction", "transactoin", "검증"],
            "note": "README 오타 수정 검증은 원본 기록의 정확한 bytes 계약을 확인하고 적용한다.",
            "source_run_id": source, "source_item_id": source_item}])
    memory_id = result["memory"]["captures"][0]["memory_id"]
    app.finish_archive("README byte verification source")
    memory = app.get_memory(memory_id)["memory"]
    return {"memory_id": memory_id, "memory_revision": memory["revision"], "source_run_id": source,
            "source_archive_id": memory["source"]["archive_id"], "source_item_id": source_item,
            "source_body": app.get_item(source_item)["item"]["body"]}


def seed_interrupted_batch(root, model):
    app = WorkflowApplication(root)
    run_id = app.summarize_run("alpha beta 독립 오타 수정", work_type="implementation", workflow_mode="standard")["active_run"]["id"]
    app.apply_plan("PLAN-001", title="독립 오타 수정", status="Finalized", objective="alpha beta 오타 수정",
                   selected_approach="독립 파일별 병렬 수정", validation="각 파일의 정확한 내용 검증",
                   execution_order="dispatch, 수정, 검증, 정산", affected_files="alpha.txt, beta.txt")
    for task_id, filename, before, after in (("TASK-001", "alpha.txt", "alhpa", "alpha"), ("TASK-002", "beta.txt", "btea", "beta")):
        app.create_task(task_id, filename + " 수정", "PLAN-001", filename + " 오타 수정",
                        f"{filename}의 {before}를 {after}로 수정", f"정확히 {after}와 개행만 있는지 검증",
                        execution_mode="parallel", executor_kind="subagent", parallel_group="typos", owned_paths=[filename])
    app.record_approval(decision="approved", prompt="두 수정과 검증 승인", source="explicit_user")
    app.configure_subagents(user_confirmed=True, enabled=True, strategy="aggressive",
                            models={model: ["high"]}, available_models={model: ["high"]})
    manifest = app.dispatch_tasks(["TASK-001", "TASK-002"], batch_id="BATCH-INTERRUPTED",
                                  execution_metadata={task: {"model": model, "reasoning_effort": "high"}
                                                      for task in ("TASK-001", "TASK-002")})
    return {"kind": "seeded interruption after dispatch, before any actual child spawn", "run_id": run_id,
            "batch_id": "BATCH-INTERRUPTED", "executions": [
                {"execution_id": e["execution_id"], "task_id": e["task_id"]} for e in manifest["executions"]]}


def main(args):
    root, output = Path("/case"), Path("/evidence")
    root.mkdir(exist_ok=False)
    output.mkdir(exist_ok=False)
    run("git", "init", "-q", str(root))
    run("git", "config", "user.name", "TAPL regression", cwd=root)
    run("git", "config", "user.email", "test@example.invalid", cwd=root)
    (root / "README.md").write_text("# Example\n\nAn atomic transactoin.\n")
    (root / "alpha.txt").write_text("alhpa\n")
    (root / "beta.txt").write_text("btea\n")
    if args.condition == "topics":
        (root / ".editorconfig").write_text("root = true\n\n[*]\nindent_size = 4\n")
    run("git", "add", ".", cwd=root)
    run("git", "commit", "-qm", "Synthetic fixture", cwd=root)
    install.install_repo(repo=root, taplctl_command=shutil.which("taplctl"))
    enabled = args.condition in {"delegation", "scout", "batch_recovery"}
    recall = args.condition in {"recall", "memory_reuse"}
    (root / ".tapl/config.toml").write_text(
        '[search]\nmode="bm25"\n[recall]\nenabled=' + str(recall).lower() + '\n'
        '[subagents]\nsetup_complete=true\nenabled=' + str(enabled).lower() + '\n'
        'strategy="aggressive"\npreference="독립 작업은 병렬 실행"\n'
        + ('[subagents.models]\n"' + args.model + '"=["high"]\n' if enabled else '')
    )
    seed_run_id = None
    scenario = {}
    if args.condition == "memory_reuse":
        scenario = seed_memory(root)
    elif args.condition == "batch_recovery":
        scenario = seed_interrupted_batch(root, args.model)
    if args.condition == "resume":
        app = WorkflowApplication(root)
        seed_run_id = app.summarize_run("README 오타 수정 및 검증", work_type="implementation", workflow_mode="standard")["active_run"]["id"]
        app.apply_plan("PLAN-001", title="오타 수정", status="Finalized",
                       objective="README의 transactoin을 transaction으로 수정",
                       selected_approach="한 단어 수정 후 내용 확인", validation="수정 내용 확인",
                       execution_order="수정 후 검증", affected_files="README.md")
        for task, title in (("TASK-001", "오타 수정"), ("TASK-002", "수정 검증")):
            app.create_task(task, title, "PLAN-001", title,
                            "README.md의 transactoin을 transaction으로 수정" if task == "TASK-001" else "README의 수정 내용 확인",
                            "README에 transactoin이 없고 transaction이 있는지 확인",
                            depends_on=[] if task == "TASK-001" else ["TASK-001"])
        app.record_approval(decision="approved", prompt="수정 및 검증 승인", source="explicit_user")
    # This is a fresh, test-owned Box. Its configuration has no external MCPs.
    codex_config = Path("/root/.codex/config.toml")
    codex_config.parent.mkdir(exist_ok=True)
    codex_config.write_text('cli_auth_credentials_store="file"\n')
    command = ["codex", "exec", "--json", "--ignore-rules",
               "--dangerously-bypass-approvals-and-sandbox", "--dangerously-bypass-hook-trust",
               "-C", str(root), "-m", args.model, "-c", 'model_reasoning_effort="high"',
               "-c", 'features.multi_agent=true',
               "-c", 'projects."/case".trust_level="trusted"',
               "-c", f'mcp_servers.tapl.command={json.dumps(sys.executable)}',
               "-c", 'mcp_servers.tapl.args=["-m","taplctl.mcp_server"]',
               "-c", 'mcp_servers.tapl.cwd="/case"',
               "-c", 'mcp_servers.tapl.required=true',
               "-c", 'mcp_servers.tapl.default_tools_approval_mode="auto"',
               "-o", str(output / "answer.txt"), PROMPTS[args.condition]]
    start = time.monotonic()
    sessions = Path("/root/.codex/sessions")
    existing_rollouts = set(sessions.rglob("*.jsonl")) if sessions.exists() else set()
    setup_errors = []
    try:
        if args.condition == "context_loss":
            setup_command = command[:-3] + ["-o", str(output / "setup-answer.txt"), CONTEXT_SETUP_PROMPT]
            setup_exit, setup_timeout = execute_session(setup_command, output, "setup-")
            app = WorkflowApplication(root)
            status = app.get_status(full=True)
            scenario = {"kind": "fresh-session persisted-run recovery; not actual compaction",
                        "run_id": (status.get("active_run") or {}).get("id"),
                        "setup_unchanged": (root / "README.md").read_text() == "# Example\n\nAn atomic transactoin.\n"}
            from taplctl import db
            scenario["setup_items"] = [{"id": item["id"], "stable_id": item["stable_id"], "kind": item["kind"],
                                         "body": item["body"],
                                         "fields": {field: item[field] for _, field in db.markdown_body_fields(item["kind"])}}
                                        for item in status.get("plans", []) + status.get("tasks", [])]
            with sqlite3.connect(root / ".tapl/tapl.db") as conn:
                scenario["setup_archives"] = conn.execute("SELECT count(*) FROM archives").fetchone()[0]
            if setup_exit != 0 or setup_timeout:
                setup_errors.append("First context-loss session failed or timed out")
        (output / "scenario.json").write_text(json.dumps(scenario, ensure_ascii=False, indent=2))
        exit_code, timed_out = execute_session(command, output)
    finally:
        Path("/root/.codex/auth.json").unlink(missing_ok=True)
    events = read_events(output / "events.jsonl")
    rollouts = output / "rollouts"
    rollouts.mkdir()
    for path in set(sessions.rglob("*.jsonl")) - existing_rollouts:
        # Preserve audit evidence but discard account-level token_count extras.
        rows = read_events(path)
        for row in rows:
            payload = row.get("payload", {})
            if payload.get("type") == "token_count":
                info = payload.get("info") or {}
                row["payload"] = {"type": "token_count", "info": {
                    key: {field: value for field, value in (info.get(key) or {}).items()
                          if field in {"input_tokens", "cached_input_tokens", "output_tokens", "reasoning_output_tokens", "total_tokens"}}
                    for key in ("total_token_usage", "last_token_usage")}}
        (rollouts / path.name).write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows))
    calls = [event["item"] for event in events if event.get("type") == "item.completed"
             and event.get("item", {}).get("type") == "mcp_tool_call"]
    names = [call["tool"] for call in calls]
    errors = list(setup_errors) + entry_errors(events)
    def check(condition, message):
        if not condition:
            errors.append(message)
    check(exit_code == 0, f"Codex exit {exit_code}")
    check(not timed_out, "Codex deadline exceeded")
    check(any(event.get("type") == "turn.completed" for event in events), "No completed turn")
    check(not any(event.get("type") in {"turn.failed", "error"} for event in events), "Terminal Codex error")
    check(bool(names) and names[0] == "tapl_get_next", "First MCP call must load TAPL policy")
    policy_end = next((index for index, event in enumerate(events) if event.get("type") == "item.completed"
                       and event.get("item", {}).get("tool") == "tapl_get_next"), len(events))
    preceding = [event["item"] for event in events[:policy_end] if event.get("type") == "item.started"
                 and event.get("item", {}).get("type") in {"command_execution", "file_change", "collab_agent_tool_call"}]
    check(all(instruction_discovery(item) for item in preceding), "Project work preceded policy loading")
    entry = next((c for c in calls if c["tool"] == "tapl_get_next"), {})
    check(not any(key in entry.get("arguments", {}) for key in ("available_models", "catalog_complete", "known_policy_revision")),
          "Ordinary entry must omit catalog and retained-policy arguments")
    # A repeat is flagged for trace review; the evaluator must check whether a
    # preceding truncation/failure/policy-loss legitimately required it.
    check(names.count("tapl_get_next") == 1, "Review repeated entry for a legitimate policy-loss condition")
    check(all(c.get("status") == "completed" for c in calls), "Failed MCP call")
    for call in calls:
        result = call.get("result") or {}
        structured = result.get("structured_content") or {}
        check(not result.get("isError") and not result.get("is_error") and structured.get("ok") is not False,
              f"MCP error in {call['tool']}")
    with sqlite3.connect(root / ".tapl/tapl.db") as conn:
        conn.row_factory = sqlite3.Row
        archives = conn.execute("SELECT count(*) FROM archives").fetchone()[0]
        plans = conn.execute("SELECT count(*) FROM items WHERE kind='plan'").fetchone()[0]
        tasks = [dict(row) for row in conn.execute("SELECT stable_id,status FROM items WHERE kind='task'")]
        archived_ids = [row[0] for row in conn.execute("SELECT run_id FROM archives")]
        executions = [dict(row) for row in conn.execute(
            "SELECT te.id,i.stable_id AS task_id,te.state FROM task_executions te "
            "JOIN items i ON i.id=te.task_item_id")]
        memory_reviews = [json.loads(row[0]) for row in conn.execute(
            "SELECT payload_json FROM events WHERE event_type='memory_review' ORDER BY id")]
    if args.condition in {"inspection", "scout"}:
        check((root / "README.md").read_text() == "# Example\n\nAn atomic transactoin.\n", "Read-only inspection edited README")
        check((root / "alpha.txt").read_text() == "alhpa\n" and (root / "beta.txt").read_text() == "btea\n", "Inspection changed another artifact")
        check({p.name for p in root.iterdir()} == {"README.md", "alpha.txt", "beta.txt", ".git", ".codex", ".tapl"}, "Inspection created an unrelated artifact")
        check(plans == 0 and not tasks, "Read-only Fast inspection created unnecessary plans/tasks")
        check(not {"tapl_approve_execution", "tapl_start_task", "tapl_dispatch_tasks"}.intersection(names), "Read-only request entered execution")
        check(archives == 1 and "tapl_finish_run" in names and "tapl_finish_archive" in names, "Inspection did not complete lifecycle")
        summaries = [c.get("arguments", {}) for c in calls if c["tool"] == "tapl_summarize_run"]
        if args.condition == "inspection":
            check(bool(summaries) and summaries[-1].get("workflow_mode", "").lower() == "fast", "Known read-only inspection was not Fast")
        check("transactoin" in (output / "answer.txt").read_text(), "Inspection omitted the observed typo")
        if args.condition == "scout":
            children = delegation_evidence(output / "rollouts")
            check(len(children) == 1 and children[0]["completed"], "Expected one completed read-only helper")
            check(all(c["model"] == args.model and c["effort"] == "high" and c["fork_turns"] == "none" for c in children),
                  "Helper did not use allowed model/effort and compact handoff")
            check(not executions, "Read-only helper created an executable task batch")
    elif args.condition == "planning":
        check((root / "README.md").read_text() == "# Example\n\nAn atomic transactoin.\n", "Planning-only request edited the file")
        check("tapl_apply_plan" in names, "Planning-only request did not record a plan")
        check(not {"tapl_approve_execution", "tapl_start_task", "tapl_dispatch_tasks"}.intersection(names), "Unapproved execution")
        check((root / "alpha.txt").read_text() == "alhpa\n" and (root / "beta.txt").read_text() == "btea\n", "Planning changed another artifact")
        check({p.name for p in root.iterdir()} == {"README.md", "alpha.txt", "beta.txt", ".git", ".codex", ".tapl"}, "Planning created an unrelated artifact")
        check(archives == 0 and "tapl_finish_run" not in names, "Planning-only work was finished or archived")
    else:
        check(archives == (2 if args.condition == "memory_reuse" else 1), "Unexpected archive count")
        check(bool(tasks) and all(task["status"] == "Completed" for task in tasks), "Tasks were not completed")
        check("tapl_finish_run" in names and "tapl_finish_archive" in names, "Missing completion lifecycle")
        if args.condition in {"delegation", "batch_recovery"}:
            check((root / "alpha.txt").read_text() == "alpha\n" and (root / "beta.txt").read_text() == "beta\n", "Independent edits incomplete")
        if args.condition == "delegation":
            check("tapl_dispatch_tasks" in names, "Explicit parallel delegation was not dispatched")
            children = delegation_evidence(output / "rollouts")
            check(len(children) == 2 and all(c["completed"] for c in children), "Missing successful child spawn/session/completion evidence")
            check(all(c["model"] == args.model and c["effort"] == "high" and c["fork_turns"] == "none" for c in children),
                  "Delegate did not use the selected model/effort and compact handoff")
            for filename in ("alpha.txt", "beta.txt"):
                check(sum(any(filename in command for command in c["commands"]) for c in children) == 1,
                      f"Missing unique child ownership evidence for {filename}")
            settlements = [c.get("arguments", {}).get("execution_id") for c in calls if c["tool"] == "tapl_complete_task"]
            check(len(executions) == 2 and all(e["id"] in settlements and e["state"] == "completed" for e in executions),
                  "Missing exact completed execution settlement")
        elif args.condition != "batch_recovery":
            check((root / "README.md").read_text() == "# Example\n\nAn atomic transaction.\n", "Requested edit differs")
        if args.condition == "resume":
            check(any(c["tool"] == "tapl_get_status" and c.get("arguments", {}).get("full") is True for c in calls), "Resume did not read missing task/plan bodies")
            check(archived_ids == [seed_run_id] and {t["stable_id"] for t in tasks} == {"TASK-001", "TASK-002"}, "Resume replaced the seeded work")
        elif args.condition == "batch_recovery":
            check(archived_ids == [scenario["run_id"]], "Recovery replaced the seeded run")
        elif args.condition == "topics":
            check(plans == 2, "Independent topics did not retain separate plans")
            check((root / ".editorconfig").read_text() == "root = true\n\n[*]\nindent_size = 2\n", "Second independent topic was not completed")
            check("tapl_approve_execution" in names, "Execution approval was not recorded")
        else:
            check("tapl_approve_execution" in names, "Execution approval was not recorded")
        if args.condition == "recall":
            check(bool(memory_reviews) and memory_reviews[-1].get("decision") == "skip"
                  and bool(memory_reviews[-1].get("reason")), "Trivial edit did not record a reasoned memory skip")
    shutil.copy2(root / ".tapl/tapl.db", output / "tapl.db")
    audit = audit_records(output, args.condition)
    errors.extend(audit["errors"])
    result = {"condition": args.condition, "model": args.model, "codex_exit_code": exit_code,
              "elapsed_seconds": round(time.monotonic()-start, 3),
              "tools": names, "archives": archives, "plans": plans, "tasks": tasks, "executions": executions, "errors": errors,
              "instruction_discovery": [item.get("command") for item in preceding],
              "usage": [e.get("usage") for e in events if e.get("type") == "turn.completed"],
              "record_audit": audit, "rollout_metrics": rollout_metrics(rollouts),
              "scenario": scenario, "passed": not errors}
    if args.condition in {"delegation", "scout"}:
        result["children"] = children
    (output / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps(result, ensure_ascii=False), flush=True)
    return bool(errors)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--condition", choices=PROMPTS, required=True)
    parser.add_argument("--model", help="Required for live tests: a model supported by the authenticated Codex account")
    parser.add_argument("--audit-directory", type=Path, help="Read-only replay of saved DB and rollout evidence; allowed on the host")
    parser.add_argument("--isolated", action="store_true")
    args = parser.parse_args()
    if args.audit_directory:
        audit = audit_records(args.audit_directory, args.condition)
        print(json.dumps(audit, ensure_ascii=False, indent=2))
        sys.exit(not audit["passed"])
    if not args.model:
        parser.error("--model is required for live tests")
    if (not args.isolated or sys.platform != "linux"
            or "KRUN_INIT=/.moraebox-agent" not in Path("/proc/cmdline").read_text()):
        parser.error("A new disposable morae-mcp Linux Box and --isolated are required")
    try:
        sys.exit(main(args))
    finally:
        Path("/root/.codex/auth.json").unlink(missing_ok=True)
