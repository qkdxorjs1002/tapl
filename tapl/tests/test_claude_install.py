"""Claude installation preserves unrelated data and never opts in Codex."""
from __future__ import annotations

import json
from pathlib import Path
import shlex
import subprocess
import tarfile
import tomllib
from unittest import mock
import zipfile

import pytest

from taplctl import claude_install, cli, db, install, uninstall


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def snapshot(root: Path) -> dict[str, bytes]:
    return {str(path.relative_to(root)): path.read_bytes() for path in root.rglob("*") if path.is_file()}


@pytest.mark.parametrize("scope", ["user", "repo"])
def test_install_merges_only_managed_hooks_and_server(tmp_path: Path, scope: str) -> None:
    root = tmp_path.resolve()
    target = root / ".claude"
    other = {"type": "command", "command": 'echo "tapl-hook"'}
    settings = {
        "model": "chosen-model", "permissions": {"deny": ["Bash(rm *)"]},
        "hooks": {"Stop": [{"hooks": [other, {"type": "command", "command": "tapl-hook --client claude-code --event Stop --mode observe"}]}]},
    }
    write_json(target / "settings.json", settings)
    mcp_path = root / (".claude.json" if scope == "user" else ".mcp.json")
    write_json(mcp_path, {
        "projects": {"/other": {"mcpServers": {"private": {"command": "private"}}}},
        "mcpServers": {"other": {"command": "other"}, "tapl": {"command": "old", "args": ["mcp"], "env": {"KEEP": "yes"}}},
    })
    options = {"claude_home": target} if scope == "user" else {"repo": root}
    result = getattr(install, f"install_{scope}")(
        **options, client="claude-code", taplctl_command="/some path/taplctl", mode="enforce", force=True,
    )
    assert result["ok"]
    assert not (root / ".codex").exists()
    assert not (root / install.VERSION_RELATIVE).exists()
    assert (root / claude_install.VERSION_RELATIVE).is_file()
    merged = json.loads((target / "settings.json").read_text())
    assert merged["model"] == "chosen-model"
    assert merged["permissions"] == settings["permissions"]
    assert merged["hooks"]["Stop"][0]["hooks"] == [other]
    assert set(merged["hooks"]) == {"SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse", "Stop"}
    for entries in merged["hooks"].values():
        for entry in entries:
            for hook in entry["hooks"]:
                if claude_install._owned_hook(hook):
                    args = shlex.split(hook["command"])
                    assert args == ["/some path/tapl-hook", "--client", "claude-code", "--event", next(event for event, values in merged["hooks"].items() if entry in values), "--mode", "enforce"]
    server = json.loads(mcp_path.read_text())
    assert server["mcpServers"]["other"] == {"command": "other"}
    assert server["projects"]["/other"]["mcpServers"]["private"] == {"command": "private"}
    assert server["mcpServers"]["tapl"] == {"type": "stdio", "command": "/some path/tapl-mcp", "env": {"KEEP": "yes", "TAPL_CLIENT": "claude-code"}}


@pytest.mark.parametrize("scope", ["user", "repo"])
def test_dry_run_and_uninstall_preserve_other_client(tmp_path: Path, scope: str) -> None:
    root = tmp_path.resolve()
    codex_options = {"codex_home": root / ".codex"} if scope == "user" else {"repo": root}
    claude_options = {"claude_home": root / ".claude"} if scope == "user" else {"repo": root}
    getattr(install, f"install_{scope}")(**codex_options, taplctl_command="taplctl")
    before = snapshot(root)
    getattr(install, f"install_{scope}")(**claude_options, client="claude-code", dry_run=True)
    assert snapshot(root) == before
    getattr(install, f"install_{scope}")(**claude_options, client="claude-code", taplctl_command="taplctl")
    after_install = snapshot(root)
    remove = getattr(uninstall, f"uninstall_{scope}")
    remove(**claude_options, client="claude-code", purge_db=True, purge_config=True, dry_run=True)
    assert snapshot(root) == after_install
    result = remove(**claude_options, client="claude-code", purge_db=True, purge_config=True)
    assert any(item["action"] == "preserved_shared" for item in result["files"])
    assert (root / ".tapl/config.toml").is_file()
    for relative, content in before.items():
        if relative.startswith(".codex/") or relative == str(install.VERSION_RELATIVE):
            assert (root / relative).read_bytes() == content
    assert not (root / claude_install.VERSION_RELATIVE).exists()
    assert install.auto_install_if_needed(start=root, home=tmp_path / "unused", client="claude-code") == []


def test_codex_uninstall_protects_claude_shared_data(tmp_path: Path) -> None:
    root = tmp_path.resolve()
    install.install_repo(repo=root, taplctl_command="taplctl")
    install.install_repo(repo=root, client="claude-code", taplctl_command="taplctl")
    database = db.local_db_path(root)
    assert database is not None
    result = uninstall.uninstall_repo(repo=root, purge_config=True, purge_db=True)
    assert (root / claude_install.VERSION_RELATIVE).is_file()
    assert (root / ".tapl/config.toml").is_file()
    assert database.is_file()
    assert any(item["action"] == "preserved_shared" for item in result["files"])


@pytest.mark.parametrize("client,owner", [("codex", "claude-code:old"), ("claude-code", "codex-old"), ("claude-code", "")])
@pytest.mark.parametrize("record", ["run", "event"])
def test_purge_preserves_peer_history_without_marker_or_config(tmp_path: Path, client: str, owner: str, record: str) -> None:
    root = tmp_path.resolve()
    install.install_repo(repo=root, client=client, taplctl_command="taplctl")
    (root / ".tapl/config.toml").unlink()
    database = db.local_db_path(root)
    assert database is not None
    conn = db.connect(database, session_id=owner)
    if record == "run":
        conn.execute("INSERT INTO workflow_runs(id, session_id, slug, status, created_at, updated_at) VALUES('old', ?, 'old', 'completed', 'now', 'now')", (owner,))
    else:
        db.record_event(conn, event_type="old_record")
    conn.commit()
    conn.close()
    before = snapshot(root)
    uninstall.uninstall_repo(repo=root, client=client, purge_db=True, dry_run=True)
    assert snapshot(root) == before
    result = uninstall.uninstall_repo(repo=root, client=client, purge_db=True)
    assert database.is_file()
    assert {item["path"]: item["action"] for item in result["files"]}[str(database)] == "preserved_shared"


@pytest.mark.parametrize("client,config_text", [
    ("codex", '[clients.claude-code.subagents]\npreference = "Claude"\n'),
    ("claude-code", '[subagents]\npreference = "Codex"\n'),
])
def test_purge_preserves_peer_config_without_install_marker(tmp_path: Path, client: str, config_text: str) -> None:
    root = tmp_path.resolve()
    install.install_repo(repo=root, client=client, taplctl_command="taplctl")
    path = root / ".tapl/config.toml"
    path.write_text(config_text)
    result = uninstall.uninstall_repo(repo=root, client=client, purge_config=True, purge_db=True)
    assert path.read_text() == config_text
    assert {item["path"]: item["action"] for item in result["files"]}[str(path)] == "preserved_shared"


@pytest.mark.parametrize("client,owner", [("codex", "codex-only"), ("claude-code", "claude-code:only")])
def test_single_client_explicit_purge_removes_own_history(tmp_path: Path, client: str, owner: str) -> None:
    root = tmp_path.resolve()
    install.install_repo(repo=root, client=client, taplctl_command="taplctl")
    (root / ".tapl/config.toml").unlink()
    database = db.local_db_path(root)
    assert database is not None
    conn = db.connect(database, session_id=owner)
    db.record_event(conn, event_type="only")
    conn.commit()
    conn.close()
    uninstall.uninstall_repo(repo=root, client=client, purge_db=True)
    assert not database.exists()


def test_standalone_claude_explicit_purge_removes_generated_defaults(tmp_path: Path) -> None:
    root = tmp_path.resolve()
    install.install_repo(repo=root, client="claude-code", taplctl_command="taplctl")
    database = db.local_db_path(root)
    assert database is not None
    conn = db.connect(database, session_id="claude-code:only")
    db.record_event(conn, event_type="only")
    conn.commit()
    conn.close()
    uninstall.uninstall_repo(repo=root, client="claude-code", purge_config=True, purge_db=True)
    assert not database.exists()
    assert not (root / ".tapl/config.toml").exists()


def test_uninstall_removes_only_tapl_hooks_and_top_level_user_server(tmp_path: Path) -> None:
    root = tmp_path.resolve()
    install.install_user(claude_home=root / ".claude", client="claude-code", taplctl_command="taplctl")
    settings_path = root / ".claude/settings.json"
    settings = json.loads(settings_path.read_text())
    other = {"type": "command", "command": "echo keep"}
    settings["hooks"]["Stop"][0]["hooks"].append(other)
    settings["permissions"] = {"allow": ["Read"]}
    write_json(settings_path, settings)
    write_json(root / ".claude.json", {"projects": {"/keep": {"mcpServers": {"tapl": {"command": "private"}}}}, "mcpServers": {"tapl": {"command": "tapl-mcp"}, "keep": {"command": "keep"}}})
    uninstall.uninstall_user(claude_home=root / ".claude", client="claude-code")
    settings = json.loads(settings_path.read_text())
    assert settings == {"permissions": {"allow": ["Read"]}, "hooks": {"Stop": [{"hooks": [other]}]}}
    mcp = json.loads((root / ".claude.json").read_text())
    assert mcp["mcpServers"] == {"keep": {"command": "keep"}}
    assert mcp["projects"]["/keep"]["mcpServers"]["tapl"]["command"] == "private"


def test_auto_refresh_is_independent_opted_in_and_keeps_mode(tmp_path: Path) -> None:
    root, home = tmp_path / "repo", tmp_path / "home"
    root.mkdir()
    assert install.auto_install_if_needed(start=root, home=home, client="claude-code") == []
    install.install_repo(repo=root, client="claude-code", taplctl_command="taplctl", mode="enforce")
    (root / claude_install.INSTALL_STATE_RELATIVE).unlink()
    (root / ".tapl/config.toml").unlink()
    results = install.auto_install_if_needed(start=root, home=home, client="claude-code", taplctl_command="taplctl")
    assert len(results) == 1
    assert results[0]["mode"] == "enforce"
    assert not (root / ".tapl/config.toml").exists()
    assert not (root / install.VERSION_RELATIVE).exists()
    assert install.auto_install_if_needed(start=root, home=home, client="claude-code") == []
    with mock.patch.object(install, "managed_install_state", side_effect=AssertionError("Codex refresh used")):
        assert install.auto_install_if_needed(start=root, home=home, client="codex") == []


@pytest.mark.parametrize("relative", [".claude/settings.json", ".mcp.json"])
def test_invalid_json_prevents_any_install_or_uninstall_writes(tmp_path: Path, relative: str) -> None:
    root = tmp_path.resolve()
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{broken", encoding="utf-8")
    before = snapshot(root)
    for operation in (install.install_repo, uninstall.uninstall_repo):
        with pytest.raises(ValueError):
            operation(repo=root, client="claude-code")
        assert snapshot(root) == before


@pytest.mark.parametrize("policy", ["merge", "overwrite"])
def test_tapl_config_policy_matches_codex(tmp_path: Path, policy: str) -> None:
    path = tmp_path / ".tapl/config.toml"
    path.parent.mkdir()
    path.write_text("[search]\nmax_results = 3\n")
    install.install_repo(repo=tmp_path, client="claude-code", tapl_config_policy=policy)
    parsed = tomllib.loads(path.read_text())
    default = tomllib.loads(install.default_config_text())["search"]["max_results"]
    assert parsed["search"]["max_results"] == (3 if policy == "merge" else default)


def test_cli_explicit_client_and_home(tmp_path: Path, capsys) -> None:
    assert cli.main(["install", "user", "--client", "claude-code", "--claude-home", str(tmp_path / ".claude"), "--dry-run", "--json"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["client"] == "claude-code"
    assert not snapshot(tmp_path)
    assert cli.main(["install", "user", "--claude-home", str(tmp_path / ".claude"), "--json"]) == 1
    assert "requires --client" in json.loads(capsys.readouterr().out)["error"]


@pytest.mark.parametrize("client", ["codex", "claude-code"])
@pytest.mark.parametrize("force", [False, True])
def test_overwrite_preserves_peer_subagents(tmp_path: Path, client: str, force: bool) -> None:
    path = tmp_path / ".tapl/config.toml"
    path.parent.mkdir()
    codex = {"enabled": False, "preference": "codex choice", "models": {"codex-model": ["high"]}}
    claude = {"enabled": False, "preference": "claude choice", "models": {"sonnet": []}}
    path.write_text(install.dump_toml({"search": {"max_results": 3}, "subagents": codex, "clients": {"claude-code": {"subagents": claude}}}))
    install.install_repo(repo=tmp_path, client=client, force=force, tapl_config_policy="overwrite")
    result = tomllib.loads(path.read_text())
    assert result["search"]["max_results"] == tomllib.loads(install.default_config_text())["search"]["max_results"]
    if client == "codex":
        assert result["clients"]["claude-code"]["subagents"] == claude
    else:
        assert result["subagents"] == codex


def test_config_get_explicit_claude_subagents_routes_to_client(tmp_path: Path, capsys) -> None:
    path = tmp_path / "config.toml"
    path.write_text('[subagents]\nenabled = false\npreference = "Codex"\n[clients.claude-code.subagents]\nenabled = false\npreference = "Claude"\n')
    assert cli.main(["--config", str(path), "config", "get", "clients.claude-code.subagents.preference", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["value"] == "Claude"


def test_windows_encoded_claude_hooks_are_idempotent() -> None:
    with mock.patch.object(install, "WINDOWS", True):
        hooks = claude_install.build_hooks_config(taplctl_command=r"C:\Program Files\tapl\taplctl.exe", mode="enforce")
        assert claude_install.merge_hooks(hooks, hooks) == hooks
        command = hooks["hooks"]["SessionStart"][0]["hooks"][0]["command"]
        assert claude_install._windows_codex_command(command) is not None
        assert claude_install._owned_hook({"type": "command", "command": command})


def test_claude_templates_packaged_in_wheel_and_sdist(tmp_path: Path) -> None:
    package_root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        ["uv", "build", "--out-dir", str(tmp_path)],
        cwd=package_root, text=True, capture_output=True,
    )
    assert result.returncode == 0, result.stderr
    with zipfile.ZipFile(next(tmp_path.glob("*.whl"))) as wheel:
        assert {"taplctl/_templates/.claude/settings.json", "taplctl/_templates/.claude/mcp.json"} <= set(wheel.namelist())
    with tarfile.open(next(tmp_path.glob("*.tar.gz"))) as source:
        names = {name.split("/", 1)[1] for name in source.getnames() if "/" in name}
        assert {".claude/settings.json", ".claude/mcp.json"} <= names
