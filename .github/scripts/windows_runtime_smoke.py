"""Exercise an installed wheel, isolated from the real home and repository.

Run with the installed virtual environment's Python. No source-tree imports or
Codex credentials are used. Works on Windows and POSIX for release validation.
"""
from __future__ import annotations

import importlib.metadata
import importlib.util
import json
import os
from pathlib import Path
import queue
import shutil
import sqlite3
import subprocess
import sys
import sysconfig
import tempfile
import threading
import tomllib


def run(args, *, cwd, env, input=None, expected=0):
    result = subprocess.run(args, cwd=cwd, env=env, input=input, text=True,
                            encoding="utf-8", capture_output=True, timeout=60)
    assert result.returncode == expected, (args, result.returncode, result.stdout, result.stderr)
    return result.stdout


def shell_commands(command, env):
    if os.name == "nt":
        # Match Codex's raw cmd /C outer quoting, without list2cmdline rewriting
        # embedded shell quotes. Also exercise the user's PowerShell shell.
        yield f'"{env.get("COMSPEC", "cmd.exe")}" /d /s /c "{command}"'
        for name in ("powershell.exe", "pwsh.exe"):
            if executable := shutil.which(name, path=env["PATH"]):
                yield [executable, "-NoProfile", "-NonInteractive", "-Command", command]
    else:
        yield ["/bin/sh", "-c", command]


def rpc_smoke(command, repo, env):
    process = subprocess.Popen([command], cwd=repo, env=env, stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    lines = queue.Queue()
    errors = []

    def read_stdout():
        for line in process.stdout:
            lines.put(line)
        lines.put(None)

    def read_stderr():
        errors.extend(process.stderr)

    readers = [threading.Thread(target=read_stdout, daemon=True),
               threading.Thread(target=read_stderr, daemon=True)]
    for reader in readers:
        reader.start()

    def send(payload):
        process.stdin.write(json.dumps(payload, ensure_ascii=False).encode("utf-8") + b"\n")
        process.stdin.flush()

    def request(identifier, method, params):
        send({"jsonrpc": "2.0", "id": identifier, "method": method, "params": params})
        while True:
            line = lines.get(timeout=45)
            assert line is not None, b"".join(errors).decode("utf-8", "replace")
            payload = json.loads(line)
            if payload.get("id") == identifier:
                assert "error" not in payload, payload
                return payload["result"]

    try:
        initialized = request(1, "initialize", {"protocolVersion": "2025-11-25", "capabilities": {},
                              "clientInfo": {"name": "tapl-wheel-smoke", "version": "1"}})
        assert initialized["serverInfo"]["version"] == importlib.metadata.version("taplctl")
        send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        tools = request(2, "tools/list", {})["tools"]
        assert "tapl_get_status" in {tool["name"] for tool in tools}
        result = request(3, "tools/call", {"name": "tapl_get_status", "arguments": {}})
        assert not result.get("isError"), result
        assert result.get("structuredContent"), result
    finally:
        process.stdin.close()
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)
        for reader in readers:
            reader.join(timeout=5)
        process.stdout.close()
        process.stderr.close()
    assert process.returncode == 0, b"".join(errors).decode("utf-8", "replace")


def main():
    origin = Path(importlib.util.find_spec("taplctl").origin).resolve()
    assert origin.is_relative_to(Path(sys.prefix).resolve()), f"Expected installed wheel, got {origin}"
    scripts = Path(sysconfig.get_path("scripts"))
    executable = scripts / ("taplctl.exe" if os.name == "nt" else "taplctl")
    assert executable.is_file(), executable
    with tempfile.TemporaryDirectory(prefix="tapl runtime smoke ") as temporary:
        base = Path(temporary).resolve()
        home = base / "isolated user 한글 & O'Neil"
        repo = base / "repo with spaces 한글"
        home.mkdir()
        repo.mkdir()
        env = {key: value for key, value in os.environ.items()
               if not key.startswith(("TAPL_", "CODEX_", "PYTHON"))}
        env.update(HOME=str(home), USERPROFILE=str(home), CODEX_HOME=str(home / ".codex"),
                   APPDATA=str(home / "AppData" / "Roaming"),
                   LOCALAPPDATA=str(home / "AppData" / "Local"),
                   TAPL_INSTALL_METADATA=str(base / "no-installer-metadata.json"),
                   PATH=str(scripts) + os.pathsep + env.get("PATH", ""))
        version = run([str(executable), "--version"], cwd=repo, env=env).strip()
        assert version == "taplctl " + importlib.metadata.version("taplctl"), version
        sentinel_hook = {"type": "command", "command": "echo unrelated-user-hook"}
        for root in (home, repo):
            (root / ".codex").mkdir()
            (root / ".tapl").mkdir()
            (root / ".codex/config.toml").write_text(
                'model = "user-selected-model"\n[mcp_servers.other]\ncommand = "other-server"\n', encoding="utf-8")
            (root / ".codex/hooks.json").write_text(json.dumps({"hooks": {
                "Stop": [{"hooks": [sentinel_hook]}]}}), encoding="utf-8")
            (root / ".tapl/config.toml").write_text(
                '[search]\nmax_results = 7\n[subagents]\nenabled = false\n', encoding="utf-8")
        for scope in ("user", "repo"):
            result = json.loads(run([str(executable), "install", scope, "--mode", "enforce", "--json"], cwd=repo, env=env))
            assert result["ok"], result
        # Force a same-version refresh and verify both preference preservation
        # and the install-state fingerprint's write-free steady state.
        for root in (home, repo):
            (root / ".tapl/install-state.json").unlink()
        assert json.loads(run([str(executable), "doctor", "--json"], cwd=repo, env=env))["ok"]
        marker_bytes = {}
        for root in (home, repo):
            state = root / ".tapl/install-state.json"
            assert len(json.loads(state.read_text(encoding="utf-8"))["fingerprint"]) == 64
            marker_bytes[state] = (state.read_bytes(), state.stat().st_mtime_ns)
            settings = tomllib.loads((root / ".tapl/config.toml").read_text(encoding="utf-8"))
            assert settings["search"]["max_results"] == 7
            assert settings["subagents"]["enabled"] is False
        run([str(executable), "doctor", "--json"], cwd=repo, env=env)
        assert all((path.read_bytes(), path.stat().st_mtime_ns) == value for path, value in marker_bytes.items())
        parsed = tomllib.loads((repo / ".codex/config.toml").read_text(encoding="utf-8"))
        mcp = parsed["mcp_servers"]["tapl"]
        assert Path(mcp["command"]).is_file(), mcp
        rpc_smoke(mcp["command"], repo, env)
        hooks = json.loads((repo / ".codex/hooks.json").read_text(encoding="utf-8"))["hooks"]
        for event, expected in (("UserPromptSubmit", 0), ("PreToolUse", 2)):
            command = hooks[event][-1]["hooks"][0]["command"]
            payload = json.dumps({"cwd": str(repo), "session_id": "native-smoke-한글", "prompt": "유니코드 입력",
                                  "tool_name": "Write", "tool_input": {"file_path": str(repo / "new.txt")}}, ensure_ascii=False)
            for shell in shell_commands(command, env):
                output = run(shell, cwd=repo, env=env, input=payload,
                             expected=0 if os.name == "nt" else expected)
                if event == "PreToolUse" and os.name == "nt":
                    decision = json.loads(output)
                    assert decision["decision"] == "block" and decision["reason"], decision
        # Inspect only the disposable DB, after all processes have released it.
        connection = sqlite3.connect(repo / ".tapl/tapl.db")
        try:
            rows = connection.execute("SELECT payload_json FROM events WHERE event_type = 'UserPromptSubmit'").fetchall()
            assert rows and all(json.loads(row[0])["prompt"] == "유니코드 입력" for row in rows)
        finally:
            connection.close()
        for scope, root in (("repo", repo), ("user", home)):
            assert json.loads(run([str(executable), "uninstall", scope, "--json"], cwd=repo, env=env))["ok"]
            parsed = tomllib.loads((root / ".codex/config.toml").read_text(encoding="utf-8"))
            assert parsed["model"] == "user-selected-model"
            assert parsed["mcp_servers"] == {"other": {"command": "other-server"}}
            remaining = json.loads((root / ".codex/hooks.json").read_text(encoding="utf-8"))["hooks"]
            assert remaining == {"Stop": [{"hooks": [sentinel_hook]}]}, remaining
            assert not (root / ".tapl/version").exists()
            assert not (root / ".tapl/install-state.json").exists()
            assert (root / ".tapl/config.toml").is_file()
        assert (repo / ".tapl/tapl.db").is_file()
        run([str(executable), "doctor", "--json"], cwd=repo, env=env)
        assert not any((root / ".tapl/version").exists() for root in (home, repo))
    print("Installed-wheel runtime smoke passed: CLI, refresh, MCP stdio, hooks, uninstall")


if __name__ == "__main__":
    main()
