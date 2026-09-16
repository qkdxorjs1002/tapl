"""Opt-in real Codex memory exercise. Run inside a disposable Linux VM.

Install this checkout and Codex first, authenticate through the normal CLI login,
then run setup, capture, reuse, and skip with the same --root and --output.
The engineering prompts do not ask Codex to save or reinforce a memory.
Logs contain synthetic project data; this script never reads credentials.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys


MIGRATION = '''import sqlite3

def migrate(connection, fail=False):
    """Apply the Orion snapshot schema and schema-version update atomically."""
    connection.execute("BEGIN")
    try:
        connection.executescript("CREATE TABLE orion_snapshot (id INTEGER PRIMARY KEY, value TEXT);")
        if fail:
            raise RuntimeError("injected version-write failure")
        connection.execute("UPDATE schema_version SET version=2")
        connection.commit()
    except Exception:
        connection.rollback()
        raise
'''

TEST = '''import sqlite3
import unittest
from migration import migrate

class MigrationTests(unittest.TestCase):
    def connection(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE schema_version (version INTEGER)")
        conn.execute("INSERT INTO schema_version VALUES (1)")
        conn.commit()
        self.addCleanup(conn.close)
        return conn

    def test_failure_rolls_back_schema_and_version(self):
        conn = self.connection()
        with self.assertRaisesRegex(RuntimeError, "injected"):
            migrate(conn, fail=True)
        self.assertEqual(conn.execute("SELECT version FROM schema_version").fetchone()[0], 1)
        self.assertIsNone(conn.execute("SELECT name FROM sqlite_master WHERE name='orion_snapshot'").fetchone())

    def test_success_commits_schema_and_version(self):
        conn = self.connection()
        migrate(conn)
        self.assertEqual(conn.execute("SELECT version FROM schema_version").fetchone()[0], 2)
        conn.execute("INSERT INTO orion_snapshot VALUES (1, 'example')")

if __name__ == "__main__":
    unittest.main()
'''

PROMPTS = {
    "capture": "Orion SQLite snapshot migration의 실패 복구 테스트가 깨집니다. migration.py와 test_migration.py를 확인하고 원인을 고친 뒤 python -m unittest -v로 검증해주세요. 실패하면 스키마와 버전이 모두 이전 상태여야 합니다. 필요한 수정과 테스트 실행은 승인합니다. 작업을 완료 처리해주세요.",
    "reuse": "Orion SQLite snapshot migration을 다시 검토해주세요. 다음 마이그레이션에도 schema_version과 스키마 변경이 함께 롤백되어야 합니다. 이전 수정에서 확인한 함정과 근거를 찾아 현재 구현이 같은 문제를 피하는지 확인하고, 앞으로의 구현에서 적용할 구체적인 원칙을 설명해주세요. 새 기능 구현은 필요 없습니다. 검토를 완료 처리해주세요.",
    "skip": "README.md의 오타 transactoin을 transaction으로 고쳐주세요. 다른 내용 변경이나 추가 조사는 필요 없습니다. 작업을 완료 처리해주세요.",
}


def run(*args: str, cwd: Path | None = None) -> None:
    subprocess.run(args, cwd=cwd, check=True, stdout=subprocess.DEVNULL)


def setup(root: Path, output: Path) -> None:
    root.mkdir(parents=True, exist_ok=False)
    output.mkdir(parents=True, exist_ok=True)
    run("git", "init", "-q", str(root))
    run("git", "config", "user.name", "Memory smoke test", cwd=root)
    run("git", "config", "user.email", "memory-smoke@example.invalid", cwd=root)
    (root / "migration.py").write_text(MIGRATION)
    (root / "test_migration.py").write_text(TEST)
    (root / "README.md").write_text("# Orion snapshot\n\nAn atomic SQLite transactoin example.\n")
    run("git", "add", "migration.py", "test_migration.py", "README.md", cwd=root)
    run("git", "commit", "-qm", "Add synthetic Orion migration fixture", cwd=root)
    taplctl = shutil.which("taplctl")
    if not taplctl:
        raise SystemExit("Install the checkout into this VM before setup.")
    run(taplctl, "install", "repo", "--repo", str(root), "--taplctl-command", taplctl)
    (root / ".tapl/config.toml").write_text('[search]\nmode="bm25"\n[recall]\nenabled=true\n[subagents]\nenabled=false\nsetup_complete=true\n')
    # Only the test server injects this fault; shipping modules are unchanged.
    wrapper = output / "fault_server.py"
    wrapper.write_text(
        "from pathlib import Path\nfrom taplctl import recall, mcp_server\n"
        f"marker=Path({str(output / 'fault-consumed')!r})\n"
        "original=recall._capture\n"
        "def capture(*args, **kwargs):\n"
        "    if not marker.exists():\n"
        "        marker.write_text('one synthetic transient failure')\n"
        "        raise recall.MemoryError('Synthetic transient storage failure; retry this same slot once.', 'memory_unavailable')\n"
        "    return original(*args, **kwargs)\n"
        "recall._capture=capture\nmcp_server.main()\n"
    )
    print(json.dumps({"phase": "setup", "fixture": str(root), "fault": "one transient capture failure"}), flush=True)


def objects(value):
    if isinstance(value, dict):
        yield value
        for v in value.values():
            yield from objects(v)
    elif isinstance(value, list):
        for v in value:
            yield from objects(v)
    elif isinstance(value, str) and value.startswith(("{", "[")):
        try:
            yield from objects(json.loads(value))
        except (ValueError, RecursionError):
            pass


def exercise(args) -> None:
    root, output = args.root.resolve(), args.output.resolve()
    if args.phase == "setup":
        setup(root, output)
        return
    db_path = root / ".tapl/tapl.db"
    if not db_path.is_file():
        raise SystemExit("Run setup first.")
    with sqlite3.connect(db_path) as conn:
        before_memories = dict(conn.execute("SELECT memory_id,half_life_days FROM memories WHERE state='active'"))
        before_archives = conn.execute("SELECT count(*) FROM archives").fetchone()[0]
    # Make the 24-hour reinforcement interval explicit fixture data, not a wait.
    if args.phase == "reuse":
        with sqlite3.connect(db_path) as conn:
            aged = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
            conn.execute("UPDATE memories SET content_updated_at=? WHERE state='active'", (aged,))
        print(json.dumps({"fixture_adjustment": "memory content age = 25 hours for cooldown boundary"}), flush=True)
    command = [
        args.codex, "exec", "--json", "--ignore-rules",
        "--dangerously-bypass-approvals-and-sandbox", "--dangerously-bypass-hook-trust",
        "-C", str(root), "-m", args.model, "-c", 'model_reasoning_effort="high"',
        "-c", 'cli_auth_credentials_store="file"',
        "-c", f'projects.{json.dumps(str(root))}.trust_level="trusted"',
        "-c", f'mcp_servers.tapl.command={json.dumps(sys.executable)}',
        "-c", f'mcp_servers.tapl.args={json.dumps([str(output / "fault_server.py")])}',
        "-c", f'mcp_servers.tapl.cwd={json.dumps(str(root))}',
        "-c", 'mcp_servers.tapl.required=true',
        "-c", 'mcp_servers.tapl.enabled=true',
        "-c", 'mcp_servers.tapl.default_tools_approval_mode="auto"',
        "-o", str(output / f"{args.phase}-answer.txt"), PROMPTS[args.phase],
    ]
    events = []
    with (output / f"{args.phase}.jsonl").open("w") as log, (output / f"{args.phase}.stderr").open("w") as err:
        process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=err, text=True)
        try:
            for line in process.stdout:
                log.write(line)
                log.flush()
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                events.append(event)
                if event.get("type") in {"thread.started", "turn.started", "turn.completed", "turn.failed", "error"}:
                    print(json.dumps({"phase": args.phase, "event": event.get("type")}), flush=True)
                item = event.get("item", {})
                if item.get("type") == "mcp_tool_call" and event.get("type") == "item.completed":
                    print(json.dumps({"phase": args.phase, "tool": item.get("tool"), "status": item.get("status")}), flush=True)
            code = process.wait(timeout=30)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
    if code:
        raise SystemExit(f"Codex exit {code}; inspect {args.phase}.stderr")
    data = list(objects(events))
    calls = [o for o in data if o.get("type") == "mcp_tool_call" and o.get("status") == "completed"]
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        memories = [dict(r) for r in conn.execute("SELECT memory_id,note,revision,half_life_days,last_reinforced_run_id FROM memories WHERE state='active'")]
        archives = conn.execute("SELECT count(*) FROM archives").fetchone()[0]
        errors = conn.execute("SELECT count(*) FROM events WHERE event_type='memory_finish_error'").fetchone()[0]
        reviews = [json.loads(r[0]) for r in conn.execute("SELECT payload_json FROM events WHERE event_type='memory_review' ORDER BY id")]
    summary = {"phase": args.phase, "memory_count": len(memories), "archives": archives, "capture_errors": errors,
               "tools": [c.get("tool") for c in calls], "last_review": reviews[-1] if reviews else None}
    assert archives == before_archives + 1, "This conversation did not archive exactly one run"
    assert reviews and reviews[-1]["status"] == "ok" and not reviews[-1]["pending_errors"], "Memory review remains unresolved"
    if args.phase == "capture":
        assert len(memories) >= 1, "No useful memory captured by the ordinary engineering task"
        assert errors >= 1 and (output / "fault-consumed").exists(), "Fault injection was not exercised"
        assert reviews[-1]["status"] == "ok" and not reviews[-1]["pending_errors"], "Capture failure was not resolved"
        run(sys.executable, "-m", "unittest", "-v", cwd=root)
        assert archives >= 1, "Capture run was not archived"
    elif args.phase == "reuse":
        source_tools = {"tapl_get_archive", "tapl_get_item"}
        assert any(c.get("tool") in source_tools for c in calls), "No original-source tool lookup"
        assert any(m["memory_id"] in before_memories and m["half_life_days"] > before_memories[m["memory_id"]] for m in memories), "No existing memory reinforced after aged fixture"
        assert any(o.get("source_checked") is True and o.get("usage") for o in data), "No actual memory-use report"
        assert any(o.get("status") == "recalled" and o.get("memories") for o in data), "No recalled memory observed"
        assert archives >= 2, "Reuse run was not archived"
    else:
        assert reviews[-1].get("decision") == "skip" and reviews[-1].get("reason"), "Trivial edit did not record a reasoned skip"
        assert {m["memory_id"] for m in memories} == set(before_memories), "Trivial edit changed the memory inventory"
        assert "transactoin" not in (root / "README.md").read_text(), "Requested typo remains"
        assert archives >= 3, "Skip run was not archived"
    (output / f"{args.phase}-result.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    print(json.dumps(summary, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--phase", choices=["setup", *PROMPTS], required=True)
    parser.add_argument("--codex", default="codex")
    parser.add_argument("--model", required=True)
    parser.add_argument("--isolated", action="store_true", help="Confirm this is a disposable Linux VM")
    arguments = parser.parse_args()
    if not arguments.isolated or sys.platform != "linux":
        parser.error("Run only inside a disposable Linux VM with --isolated")
    exercise(arguments)
