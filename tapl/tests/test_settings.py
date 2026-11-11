from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import threading
import tomllib
import urllib.error
import urllib.request
from unittest import mock

import pytest
from mcp import Client

from taplctl import cli, clients, config, db, mcp_server, settings, viewer


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setenv("TAPL_CLIENT", "codex")
    root = tmp_path / "workspace"
    (root / ".tapl").mkdir(parents=True)
    return root


def write_config(workspace: Path, text: str) -> Path:
    path = workspace / ".tapl/config.toml"
    path.write_text(text)
    return path


def profile(model: str, effort: str = "high") -> list[dict]:
    return [{"name": "routine", "characteristics": "Focused local work", "delegation_bias": "prefer",
             "candidates": [{"model": model, "reasoning_effort": effort}]}]


def test_registry_defaults_and_read_never_create_files(workspace: Path) -> None:
    service = settings.SettingsService(workspace)
    document = service.get()
    expected = set()
    for spec in config.EDITABLE_CONFIG_KEYS:
        key = spec.dynamic_prefix.rstrip(".") if spec.dynamic_prefix else spec.key
        expected.add(key)
        if key.startswith("subagents."):
            expected.add("clients.claude-code." + key)
    assert set(document["values"]) == expected == {field["key"] for field in document["fields"]}
    assert document["values"] == document["defaults"]
    assert len(document["fields"]) == 23
    assert {key: document["values"]["viewer." + key] for key in ("language", "layout", "mcp_path")} == {
        "language": "auto", "layout": "auto", "mcp_path": "",
    }
    assert document["values"]["subagents.setup_complete"] is False
    assert document["overrides"] == []
    assert document["exists"] is False
    assert not Path(document["path"]).exists()
    result = service.save(document["values"], document["revision"])
    assert result["changed"] is False
    assert not Path(document["path"]).exists()


def test_cli_precedence_and_workspace_revision_scope(workspace: Path, tmp_path: Path) -> None:
    home_path = Path.home() / ".tapl/config.toml"
    home_path.parent.mkdir()
    home_path.write_text("[search]\nmax_results = 31\n")
    service = settings.SettingsService(workspace)
    document = service.get()
    assert document["path"] == str(home_path)
    assert document["values"]["search.max_results"] == 31
    other = tmp_path / "other"
    other.mkdir()
    with pytest.raises(settings.SettingsConflict):
        settings.SettingsService(other).save({"search.max_results": 20}, document["revision"])
    local = write_config(workspace, "[search]\nmax_results = 19\n")
    with pytest.raises(settings.SettingsConflict):
        service.save({"search.max_results": 20}, document["revision"])
    assert service.get()["path"] == str(local)
    pinned = settings.SettingsService(workspace, config_path=home_path)
    assert pinned.get()["path"] == str(home_path)


def test_atomic_model_profile_change_and_independent_client_scopes(workspace: Path) -> None:
    service = settings.SettingsService(workspace)
    first = service.save({"subagents.models": {"old.model": ["high"]}, "subagents.profiles": profile("old.model")}, service.get()["revision"])
    with clients.client_scope("claude-code"):
        changed = service.save({
            "subagents.models": {"new.model with spaces": ["high"]},
            "subagents.profiles": profile("new.model with spaces"),
            "clients.claude-code.subagents.models": {"inherit": [], "sonnet.4": []},
            "clients.claude-code.subagents.profiles": [],
        }, first["settings"]["revision"])
    data = tomllib.loads(Path(changed["settings"]["path"]).read_text())
    assert data["subagents"]["models"] == {"new.model with spaces": ["high"]}
    assert data["clients"]["claude-code"]["subagents"]["models"] == {"inherit": [], "sonnet.4": []}
    assert changed["settings"]["values"]["clients.claude-code.subagents.profiles"] == []
    before = Path(changed["settings"]["path"]).read_bytes()
    with pytest.raises(ValueError):
        service.save({"subagents.models": {"broken-reference": ["high"]}}, changed["settings"]["revision"])
    assert Path(changed["settings"]["path"]).read_bytes() == before


@pytest.mark.parametrize("values", [
    {"path": "/tmp/not-allowed"}, {"subagents.available_models": {}},
    {"search.max_results": True}, {"search.max_results": 0}, {"recall.enabled": "false"},
    {"search.hybrid_semantic_ratio": float("nan")}, {"search.hybrid_semantic_ratio": 1.1},
    {"viewer.allowed_origins": ["https://example.com/path"]},
    {"viewer.language": "ja"}, {"viewer.language": True},
    {"viewer.layout": "wide"}, {"viewer.layout": 1},
    {"viewer.mcp_path": ["tapl-mcp"]}, {"viewer.mcp_path": "tapl-mcp\n--flag"},
    {"subagents.models": {"codex.model": []}}, {"subagents.models": {" padded ": ["high"]}},
    {"clients.claude-code.subagents.models": {"inherit": ["high"]}},
])
def test_rejects_invalid_values_without_writing(workspace: Path, values: dict) -> None:
    path = write_config(workspace, "# retain\n[search]\nmax_results = 22\n")
    original = path.read_bytes()
    service = settings.SettingsService(workspace)
    with pytest.raises((ValueError, TypeError)):
        service.save(values, service.get()["revision"])
    assert path.read_bytes() == original


def test_stale_revision_rejects_external_edit(workspace: Path) -> None:
    path = write_config(workspace, "# one\n")
    service = settings.SettingsService(workspace)
    revision = service.get()["revision"]
    path.write_text("# two\n")
    with pytest.raises(settings.SettingsConflict):
        service.save({"search.max_results": 40}, revision)
    assert path.read_text() == "# two\n"


def test_concurrent_saves_cannot_overwrite_same_revision(workspace: Path) -> None:
    service = settings.SettingsService(workspace)
    revision = service.get()["revision"]

    def save(value: int) -> str:
        try:
            service.save({"search.max_results": value}, revision)
            return "saved"
        except settings.SettingsConflict:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(save, (20, 21))) == ["conflict", "saved"]


def test_atomic_write_failure_preserves_original(workspace: Path) -> None:
    path = write_config(workspace, "# original\n")
    service = settings.SettingsService(workspace)
    with mock.patch("taplctl.config_editor.os.replace", side_effect=OSError("write failed")):
        with pytest.raises(OSError):
            service.save({"search.max_results": 25}, service.get()["revision"])
    assert path.read_text() == "# original\n"
    assert list(path.parent.iterdir()) == [path]


@pytest.mark.parametrize("text", [
    '# custom\nsearch.max_results = 20 # limit\nsubagents.models."model.a" = ["high"] # model\nsubagents.profiles = []\nsubagents.available_models."catalog.a" = ["high"]\nsubagents.custom = "keep"\n',
    '# custom\nsearch = { limit = 20, custom = "keep" } # search\nsubagents = { models = { "model.a" = ["high"] }, profiles = [], available_models = { "catalog.a" = ["high"] }, custom = "keep" } # subagents\n',
    '# custom\n[search]\nmax_results = 20 # limit\n[subagents]\ncustom = "keep"\n[subagents.models]\n"model.a" = ["high"] # model\n[subagents.available_models]\n"catalog.a" = ["high"]\n[[subagents.profiles]]\nname = "routine" # profile\n[[subagents.profiles.candidates]]\nmodel = "model.a"\nreasoning_effort = "high"\n',
])
def test_reset_removes_overrides_and_inferred_setup_preserves_unknowns_and_comments(workspace: Path, text: str) -> None:
    text += '\n[clients.claude-code.subagents]\nenabled = false # claude\ncustom = "claude keep"\navailable_models = { sonnet = [] }\n'
    path = write_config(workspace, text)
    service = settings.SettingsService(workspace)
    document = service.get()
    assert document["values"]["subagents.setup_complete"] is True
    result = service.save({}, document["revision"], reset_all=True)
    assert result["settings"]["values"] == result["settings"]["defaults"]
    assert result["settings"]["overrides"] == []
    rendered = path.read_text()
    assert "# custom" in rendered and "# claude" in rendered
    for comment in ("# limit", "# model", "# search", "# subagents", "# profile"):
        if comment in text:
            assert comment in rendered
    data = tomllib.loads(rendered)
    assert data["subagents"]["custom"] == "keep"
    assert data["subagents"]["available_models"] == {"catalog.a": ["high"]}
    assert data["clients"]["claude-code"]["subagents"]["available_models"] == {"sonnet": []}


def test_save_replaces_nested_model_and_profile_tables_together(workspace: Path) -> None:
    path = write_config(workspace, '''# file header
[subagents.models]
"old.model" = ["high"] # model comment
[[subagents.profiles]]
name = "old" # profile comment
[[subagents.profiles.candidates]]
model = "old.model"
reasoning_effort = "high"
[subagents.available_models]
"old.model" = ["high"]
''')
    service = settings.SettingsService(workspace)
    result = service.save({"subagents.models": {"new.model": ["high"]},
                           "subagents.profiles": profile("new.model")}, service.get()["revision"])
    assert result["settings"]["values"]["subagents.models"] == {"new.model": ["high"]}
    data = tomllib.loads(path.read_text())
    assert data["subagents"]["available_models"] == {"old.model": ["high"]}
    assert "# model comment" in path.read_text() and "# profile comment" in path.read_text()


@pytest.mark.parametrize("source", [
    '[clients.claude-code]\nsubagents.preference = "keep" # existing preference\n',
    '[clients]\nclaude-code.subagents.preference = "keep" # existing preference\n',
    '[clients.claude-code]\nsubagents.preference = "keep" # existing preference\n[clients.claude-code.other]\ncustom = "keep"\n',
])
def test_save_claude_dotted_settings_stays_within_existing_ancestor_table(workspace: Path, source: str) -> None:
    path = write_config(workspace, source)
    service = settings.SettingsService(workspace)
    result = service.save({"clients.claude-code.subagents.strategy": "balanced",
                           "clients.claude-code.subagents.models": {"sonnet.4": []},
                           "clients.claude-code.subagents.profiles": []}, service.get()["revision"])
    assert result["ok"] is True
    claude = tomllib.loads(path.read_text())["clients"]["claude-code"]["subagents"]
    assert claude["preference"] == "keep"
    assert claude["strategy"] == "balanced"
    assert claude["models"] == {"sonnet.4": []}
    assert "# existing preference" in path.read_text()


def test_reset_clears_all_accepted_legacy_aliases(workspace: Path) -> None:
    path = write_config(workspace, '''[search]
limit = 22
semantic-ratio = 0.2
semantic-provider = "local"
idle-timeout-seconds = 3
custom = "untouched"
[viewer]
allowed-origins = ["https://example.com"]
''')
    service = settings.SettingsService(workspace)
    result = service.save({}, service.get()["revision"], reset_all=True)
    assert result["settings"]["values"] == result["settings"]["defaults"]
    assert tomllib.loads(path.read_text())["search"] == {"custom": "untouched"}


def test_viewer_settings_route_requires_scope_and_reset_confirmation(workspace: Path) -> None:
    db.initialize_workspace(workspace)
    path = write_config(workspace, "[search]\nmax_results = 25\n")
    app = viewer.ViewerApplication(default_workspace=workspace)
    read = app.handle_message({"command": "getSettings", "requestId": "read", "runId": "missing"})
    assert read["ok"] is True and read["action"] == "get"
    revision = read["settings"]["revision"]
    for payload in (
        {"command": "saveSettings", "values": {"search.max_results": 40}},
        {"command": "resetSettings", "workspace": str(workspace)},
    ):
        result = app.handle_message({"requestId": "write", "revision": revision, **payload})
        assert result["type"] == "settings:result" and result["ok"] is False
    assert path.read_text() == "[search]\nmax_results = 25\n"
    reset = app.handle_message({"command": "resetSettings", "requestId": "reset", "workspace": str(workspace),
                                "revision": revision, "confirmed": True})
    assert reset["ok"] is True and reset["changed"] is True
    stale = app.handle_message({"command": "saveSettings", "requestId": "stale", "workspace": str(workspace),
                                "revision": revision, "values": {"search.max_results": 40}})
    assert stale["code"] == "settings_conflict"


def test_http_settings_origin_required_and_allowlist_remains_frozen(workspace: Path) -> None:
    db.initialize_workspace(workspace)
    path = write_config(workspace, "[search]\nmax_results = 25\n")
    server = viewer.create_server(viewer.ViewerApplication(default_workspace=workspace), port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    def request(payload: dict, origin: str | None) -> tuple[int, dict]:
        headers = {"Content-Type": "application/json"}
        if origin is not None:
            headers["Origin"] = origin
        req = urllib.request.Request(server.browser_origin + "/api/message", data=json.dumps(payload).encode(), headers=headers)
        try:
            with urllib.request.urlopen(req) as response:
                return response.status, json.load(response)
        except urllib.error.HTTPError as exc:
            return exc.code, json.load(exc)

    try:
        get = {"command": "getSettings", "requestId": "get", "workspace": str(workspace)}
        for origin in (None, "null", "https://evil.example", "http://localhost.invalid"):
            assert request(get, origin)[0] == 403
        status, read = request(get, server.browser_origin)
        assert status == 200 and read["ok"] is True
        save = {"command": "saveSettings", "requestId": "save", "workspace": str(workspace),
                "revision": read["settings"]["revision"], "values": {"viewer.allowed_origins": ["https://new.example"]}}
        before = path.read_bytes()
        assert request(save, None)[0] == 403
        assert path.read_bytes() == before
        _, saved = request(save, server.browser_origin)
        assert saved["ok"] is True
        assert "viewer.allowed_origins" in saved["settings"]["restart_required"]
        assert request(get, "https://new.example")[0] == 403
        reset = {"command": "resetSettings", "requestId": "reset", "workspace": str(workspace),
                 "revision": saved["settings"]["revision"]}
        assert request(reset, server.browser_origin)[1]["ok"] is False
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_cli_viewer_pins_explicit_config(workspace: Path, tmp_path: Path) -> None:
    db.initialize_workspace(workspace)
    explicit = tmp_path / "explicit.toml"
    explicit.write_text("[search]\nmax_results = 23\n")
    with mock.patch.object(viewer, "serve") as serve, mock.patch.object(viewer, "existing_workspace", return_value=workspace):
        args = cli.build_parser().parse_args(["--config", str(explicit), "viewer"])
        cli.cmd_viewer(args)
    assert serve.call_args.kwargs["config_path"] == explicit
    app = viewer.ViewerApplication(default_workspace=workspace, config_path=explicit)
    read = app.handle_message({"command": "getSettings", "requestId": "pinned"})
    assert read["settings"]["path"] == str(explicit)


def test_mcp_settings_without_workflow_database_and_no_path_argument(workspace: Path) -> None:
    server = mcp_server.create_server(workspace_root=workspace)

    async def exercise() -> None:
        async with Client(server) as client:
            tools = {tool.name: tool for tool in await server.list_tools()}
            assert "path" not in tools["tapl_save_settings"].input_schema["properties"]
            assert tools["tapl_get_settings"].annotations.read_only_hint is True
            read = (await client.call_tool("tapl_get_settings", {})).structured_content
            assert read["ok"] is True
            saved = (await client.call_tool("tapl_save_settings", {
                "values": {"search.max_results": 37}, "expected_revision": read["settings"]["revision"],
            })).structured_content
            assert saved["ok"] is True and saved["settings"]["values"]["search.max_results"] == 37
            stale = (await client.call_tool("tapl_save_settings", {
                "values": {"search.max_results": 38}, "expected_revision": read["settings"]["revision"],
            })).structured_content
            assert stale["code"] == "settings_conflict"
            reset = (await client.call_tool("tapl_save_settings", {
                "values": {}, "expected_revision": saved["settings"]["revision"], "reset_all": True,
            })).structured_content
            assert reset["ok"] is True and reset["settings"]["overrides"] == []

    asyncio.run(exercise())
    assert not list(workspace.rglob("*.db"))


def test_mcp_settings_validates_host_identity_without_db(workspace: Path) -> None:
    with clients.client_scope("claude-code"):
        server = mcp_server.create_server(workspace_root=workspace)

    async def exercise() -> None:
        async with Client(server) as client:
            for arguments in ({}, {"session_id": "codex-session"}):
                result = (await client.call_tool("tapl_get_settings", arguments)).structured_content
                assert result["ok"] is False
            result = (await client.call_tool("tapl_get_settings", {"session_id": "claude-code:session"})).structured_content
            assert result["ok"] is True

    asyncio.run(exercise())
    assert not list(workspace.rglob("*.db"))
