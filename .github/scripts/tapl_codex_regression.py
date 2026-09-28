"""One real Codex condition per disposable morae-mcp Linux Box.

The caller supplies an installed checkout, normal CLI authentication, and a fresh
Box for EVERY invocation. Never run this on the host. Evidence excludes auth.
"""
from __future__ import annotations

import argparse
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
}


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


def audit_records(directory, condition):
    """Recheck retained evidence, including after an evaluator-only correction.

    This is fixture-specific trace evidence, not a general shell effect analyzer.
    An unfamiliar editing method is flagged for review rather than assumed safe.
    """
    errors, links = [], []
    with sqlite3.connect(f"file:{directory / 'tapl.db'}?mode=ro", uri=True) as conn:
        conn.row_factory = sqlite3.Row
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
    enabled = args.condition in {"delegation", "scout"}
    recall = args.condition == "recall"
    (root / ".tapl/config.toml").write_text(
        '[search]\nmode="bm25"\n[recall]\nenabled=' + str(recall).lower() + '\n'
        '[subagents]\nsetup_complete=true\nenabled=' + str(enabled).lower() + '\n'
        'strategy="aggressive"\npreference="독립 작업은 병렬 실행"\n'
        + ('[subagents.models]\n"' + args.model + '"=["high"]\n' if enabled else '')
    )
    seed_run_id = None
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
    timed_out = threading.Event()
    with (output / "events.jsonl").open("w") as stdout, (output / "stderr.log").open("w") as stderr:
        try:
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
            for line in process.stdout:
                stdout.write(line)
                stdout.flush()
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                item = event.get("item", {})
                if event.get("type") in {"turn.failed", "error", "turn.completed"}:
                    print(json.dumps({"event": event.get("type"), "usage": event.get("usage")}), flush=True)
                elif event.get("type") == "item.completed" and item.get("type") == "mcp_tool_call":
                    print(json.dumps({"tool": item.get("tool"), "status": item.get("status")}), flush=True)
            process.wait(timeout=30)
        finally:
            if 'timer' in locals():
                timer.cancel()
            if 'process' in locals() and process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
            Path("/root/.codex/auth.json").unlink(missing_ok=True)
    events = [json.loads(line) for line in (output / "events.jsonl").read_text().splitlines() if line.startswith("{")]
    rollouts = output / "rollouts"
    rollouts.mkdir()
    for path in set(sessions.rglob("*.jsonl")) - existing_rollouts:
        shutil.copy2(path, rollouts / path.name)
    calls = [event["item"] for event in events if event.get("type") == "item.completed"
             and event.get("item", {}).get("type") == "mcp_tool_call"]
    names = [call["tool"] for call in calls]
    errors = []
    def check(condition, message):
        if not condition:
            errors.append(message)
    check(process.returncode == 0, f"Codex exit {process.returncode}")
    check(not timed_out.is_set(), "Codex deadline exceeded")
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
        check(archives == 1, "Expected exactly one archive")
        check(bool(tasks) and all(task["status"] == "Completed" for task in tasks), "Tasks were not completed")
        check("tapl_finish_run" in names and "tapl_finish_archive" in names, "Missing completion lifecycle")
        if args.condition == "delegation":
            check((root / "alpha.txt").read_text() == "alpha\n" and (root / "beta.txt").read_text() == "beta\n", "Independent edits incomplete")
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
        else:
            check((root / "README.md").read_text() == "# Example\n\nAn atomic transaction.\n", "Requested edit differs")
        if args.condition == "resume":
            check(any(c["tool"] == "tapl_get_status" and c.get("arguments", {}).get("full") is True for c in calls), "Resume did not read missing task/plan bodies")
            check(archived_ids == [seed_run_id] and {t["stable_id"] for t in tasks} == {"TASK-001", "TASK-002"}, "Resume replaced the seeded work")
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
    result = {"condition": args.condition, "model": args.model, "codex_exit_code": process.returncode,
              "elapsed_seconds": round(time.monotonic()-start, 3),
              "tools": names, "archives": archives, "plans": plans, "tasks": tasks, "executions": executions, "errors": errors,
              "instruction_discovery": [item.get("command") for item in preceding],
              "usage": [e.get("usage") for e in events if e.get("type") == "turn.completed"],
              "record_audit": audit, "passed": not errors}
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
