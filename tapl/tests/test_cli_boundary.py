from __future__ import annotations

import argparse
import contextlib
import io
import json
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest import mock

from taplctl import cli, config, hook_cli, install


MANAGEMENT_COMMANDS = {
    "config",
    "init",
    "doctor",
    "update",
    "install",
    "uninstall",
    "viewer",
    "reindex",
    "searchd",
}


def root_commands(parser: argparse.ArgumentParser) -> set[str]:
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return set(action.choices)
    raise AssertionError("root subparser action not found")


class PublicCliBoundaryTests(unittest.TestCase):
    def test_public_parser_contains_only_management_commands(self) -> None:
        parser = cli.build_parser()

        self.assertEqual(root_commands(parser), MANAGEMENT_COMMANDS)
        help_text = parser.format_help()
        self.assertIn("Agent workflow operations are available through the dedicated `tapl-mcp`", help_text)
        self.assertNotIn("hook-event", help_text)
        self.assertNotIn("{mcp,", help_text)

    def test_workflow_commands_are_not_registered_by_management_cli(self) -> None:
        commands = root_commands(cli.build_parser())
        self.assertTrue({"status", "mcp", "hook-event", "recall", "update-memory", "delete-memory"}.isdisjoint(commands))

    def test_config_command_is_management_only_and_skips_auto_install(self) -> None:
        args = cli.build_parser().parse_args(
            ["config", "set", "search.mode", "hybrid"]
        )

        self.assertEqual(args.command, "config")
        self.assertTrue(cli.should_skip_auto_install(args))

    def test_uninstall_requires_an_explicit_scope(self) -> None:
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
            cli.build_parser().parse_args(["uninstall"])
        self.assertEqual(raised.exception.code, 2)

    def test_uninstall_cli_preserves_data_then_purges_with_all_output_formats(self) -> None:
        for scope in ("user", "repo"):
            with self.subTest(scope=scope), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp).resolve()
                if scope == "user":
                    install.install_user(codex_home=root / ".codex", taplctl_command="taplctl")
                    target_args = ["--codex-home", str(root / ".codex")]
                else:
                    install.install_repo(repo=root, taplctl_command="taplctl")
                    target_args = ["--repo", str(root)]
                db_path = root / ".tapl" / "tapl.db"
                if not db_path.exists():
                    db_path.write_bytes(b"preserve user database")
                before = {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}
                arguments = ["uninstall", scope, *target_args]
                with mock.patch.object(install, "auto_install_if_needed") as auto_install:
                    output = io.StringIO()
                    with contextlib.redirect_stdout(output):
                        result = cli.main([*arguments, "--purge", "--dry-run", "--json"])
                    self.assertEqual(result, 0)
                    payload = json.loads(output.getvalue())
                    self.assertEqual(payload["uninstall"], scope)
                    self.assertTrue(payload["purge"])
                    self.assertTrue(payload["dry_run"])
                    self.assertIn("would_removed", {item["action"] for item in payload["files"]})
                    self.assertEqual(
                        {path: path.read_bytes() for path in root.rglob("*") if path.is_file()},
                        before,
                    )

                    output = io.StringIO()
                    with contextlib.redirect_stdout(output):
                        result = cli.main([*arguments, "--agent"])
                    self.assertEqual(result, 0)
                    self.assertIn(f"<uninstall>{scope}</uninstall>", output.getvalue())
                    self.assertFalse((root / ".tapl" / "version").exists())
                    self.assertEqual(db_path.read_bytes(), before[db_path])
                    config_path = root / ".tapl" / "config.toml"
                    self.assertEqual(config_path.read_bytes(), before[config_path])

                    output = io.StringIO()
                    with contextlib.redirect_stdout(output):
                        result = cli.main([*arguments, "--purge"])
                    self.assertEqual(result, 0)
                    self.assertIn(f"tapl uninstall {scope}:", output.getvalue())
                    self.assertIn(f"removed: {db_path}", output.getvalue())
                    self.assertFalse(db_path.exists())
                    self.assertFalse(config_path.exists())
                    auto_install.assert_not_called()

    def test_uninstall_cli_reports_invalid_configuration_without_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            codex_home = Path(tmp) / ".codex"
            codex_home.mkdir()
            hooks_path = codex_home / "hooks.json"
            hooks_path.write_text("{invalid", encoding="utf-8")
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                result = cli.main(["uninstall", "user", "--codex-home", str(codex_home), "--json"])
            self.assertEqual(result, 1)
            self.assertFalse(json.loads(output.getvalue())["ok"])
            self.assertEqual(hooks_path.read_text(encoding="utf-8"), "{invalid")

    def test_config_help_lists_keys_value_formats_allowed_values_and_examples(self) -> None:
        parser = cli.build_parser()
        config_action = next(
            action
            for action in parser._actions
            if isinstance(action, argparse._SubParsersAction)
        ).choices["config"]
        config_sub = next(
            action
            for action in config_action._actions
            if isinstance(action, argparse._SubParsersAction)
        )
        set_parser = config_sub.choices["set"]
        unset_parser = config_sub.choices["unset"]

        config_help = config_action.format_help()
        set_help = set_parser.format_help()
        unset_help = unset_parser.format_help()
        for expected in (
            "search.mode MODE",
            "semantic, bm25, word, hybrid",
            "viewer.allowed_origins TOML_ARRAY",
            "subagents.enabled BOOLEAN",
            "recall.enabled BOOLEAN",
            "true, false",
            "subagents.models.<model-id> TOML_ARRAY",
        ):
            self.assertIn(expected, config_help)
            self.assertIn(expected, set_help)
            self.assertIn(expected, unset_help)
        self.assertIn("taplctl config set search.mode hybrid", set_help)
        self.assertIn("taplctl config unset search.mode", unset_help)


class HookEntrypointTests(unittest.TestCase):
    def test_user_install_hooks_do_not_enroll_workspaces_without_version_marker(self) -> None:
        for evidence in ("empty", "db", "config", "hook", "config_and_hook"):
            with self.subTest(evidence=evidence), tempfile.TemporaryDirectory() as tmp:
                user_root = Path(tmp) / "home" / "paragonnov"
                workspace = user_root / "workspace" / "infra"
                workspace.mkdir(parents=True)
                with mock.patch.object(Path, "home", return_value=user_root):
                    install.install_user(
                        taplctl_command="/home/linuxbrew/.linuxbrew/bin/taplctl"
                    )
                    user_config = user_root / ".tapl" / "config.toml"
                    user_config.write_text("[search]\nmax_results = 7\n", encoding="utf-8")
                    if evidence != "empty":
                        hook_cli.db.initialize_workspace(workspace)
                    repo_config = workspace / ".tapl" / "config.toml"
                    if evidence in ("config", "config_and_hook"):
                        repo_config.write_text("[search]\nmax_results = 3\n", encoding="utf-8")
                    if evidence in ("hook", "config_and_hook"):
                        install.install_hooks(
                            workspace / ".codex" / "hooks.json",
                            taplctl_command="/home/linuxbrew/.linuxbrew/bin/taplctl",
                            mode="observe",
                            dry_run=False,
                        )
                    tracked = [
                        scope / relative
                        for scope in (user_root, workspace)
                        for relative in (
                            ".tapl/config.toml", ".tapl/version",
                            ".codex/config.toml", ".codex/hooks.json",
                        )
                    ]
                    before = {path: path.read_bytes() if path.exists() else None for path in tracked}

                    for event in ("SessionStart", "UserPromptSubmit", "UserPromptSubmit"):
                        payload = json.dumps({"cwd": str(workspace), "prompt": "Inspect the workspace"})
                        with (
                            mock.patch("sys.stdin", io.StringIO(payload)),
                            contextlib.redirect_stdout(io.StringIO()),
                        ):
                            result = hook_cli.main(["--event", event, "--json"])
                        self.assertEqual(result, 0)
                        self.assertEqual(
                            {path: path.read_bytes() if path.exists() else None for path in tracked},
                            before,
                        )

                    self.assertTrue((workspace / hook_cli.db.DEFAULT_DB_RELATIVE).is_file())
                    settings = hook_cli.tapl_config.load(start=workspace)
                    has_config = evidence in ("config", "config_and_hook")
                    self.assertEqual(Path(settings.path).resolve(), (repo_config if has_config else user_config).resolve())
                    self.assertEqual(settings.search.max_results, 3 if has_config else 7)

    def test_hook_cli_handles_event_without_management_cli_bridge(self) -> None:
        connection = mock.Mock()
        outcome = {"event": "PreToolUse", "block": True, "message": "blocked"}
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            workspace.mkdir()
            db_path = workspace / ".tapl" / "tapl.db"
            with (
                mock.patch.object(hook_cli, "_read_stdin_payload", return_value={"cwd": str(workspace)}),
                mock.patch.object(hook_cli.tapl_config, "load", return_value=mock.sentinel.settings),
                mock.patch.object(hook_cli.db, "connect", return_value=connection) as connect,
                mock.patch.object(hook_cli.hooks, "handle_event", return_value=outcome) as handler,
            ):
                result = hook_cli.main(
                    [
                        "--event",
                        "PreToolUse",
                        "--mode",
                        "enforce",
                        "--tool",
                        "Bash",
                        "--db",
                        str(db_path),
                        "--json",
                    ]
                )
            connect.assert_called_once_with(workspace.resolve() / ".tapl" / "tapl.db")

        self.assertEqual(result, 2)
        self.assertEqual(handler.call_args.kwargs["event"], "PreToolUse")
        self.assertEqual(handler.call_args.kwargs["mode"], "enforce")
        self.assertEqual(handler.call_args.kwargs["tool"], "Bash")
        self.assertEqual(handler.call_args.kwargs["payload"], {"cwd": str(workspace)})
        self.assertIs(handler.call_args.kwargs["tapl_settings"], mock.sentinel.settings)
        connection.close.assert_called_once_with()

    def test_hook_rejects_absent_or_invalid_cwd_before_touching_a_database(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            file_path = root / "file.txt"
            file_path.write_text("data", encoding="utf-8")
            cases = ({}, {"cwd": None}, {"cwd": ""}, {"cwd": "relative"},
                     {"cwd": str(root / "missing")}, {"cwd": str(file_path)})
            for payload in cases:
                with self.subTest(payload=payload):
                    with (
                        mock.patch.object(hook_cli, "_read_stdin_payload", return_value=payload),
                        mock.patch.object(hook_cli.db, "connect") as connect,
                        mock.patch.object(hook_cli.db, "initialize_workspace") as initialize,
                        mock.patch.object(install, "auto_install_if_needed") as auto_install,
                        contextlib.redirect_stdout(io.StringIO()) as output,
                    ):
                        result = hook_cli.main(["--event", "UserPromptSubmit", "--json"])
                        self.assertEqual(result, 1)
                        self.assertFalse(json.loads(output.getvalue())["ok"])
                        connect.assert_not_called()
                        initialize.assert_not_called()
                        auto_install.assert_not_called()
            self.assertFalse((root / ".tapl").exists())

    def test_hook_uses_exact_child_cwd_and_rejects_conflicting_db_override(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "parent"
            child = root / "child"
            sibling = root / "sibling"
            child.mkdir(parents=True)
            sibling.mkdir()
            (root / ".git").mkdir()
            (child / ".codex").mkdir()
            (child / "README.md").write_text("not a workspace marker", encoding="utf-8")
            parent_db = Path(hook_cli.db.initialize_workspace(root)["db"])
            sibling_db = Path(hook_cli.db.initialize_workspace(sibling)["db"])
            before = {path: path.read_bytes() for path in (parent_db, sibling_db)}
            payload = {"cwd": str(child), "prompt": "Inspect this folder"}

            with (
                mock.patch.object(hook_cli, "_read_stdin_payload", return_value=payload),
                contextlib.redirect_stdout(io.StringIO()) as output,
            ):
                conflict = hook_cli.main(["--event", "UserPromptSubmit", "--db", str(parent_db), "--json"])
            self.assertEqual(conflict, 1)
            self.assertIn("must match", json.loads(output.getvalue())["error"])
            self.assertFalse((child / ".tapl").exists())

            with (
                mock.patch.object(hook_cli, "_read_stdin_payload", return_value=payload),
                mock.patch.object(install, "auto_install_if_needed"),
                contextlib.redirect_stdout(io.StringIO()) as output,
            ):
                accepted = hook_cli.main(["--event", "UserPromptSubmit", "--json"])
            self.assertEqual(accepted, 0, output.getvalue())
            self.assertEqual(json.loads(output.getvalue())["workspace"]["workspace_root"], str(child.resolve()))
            self.assertTrue((child / ".tapl" / "tapl.db").is_file())
            self.assertEqual({path: path.read_bytes() for path in before}, before)

    def test_default_config_uses_selected_folder_or_user_scope(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            parent = root / "parent"
            child = parent / "child"
            home = root / "home"
            child.mkdir(parents=True)
            (parent / ".tapl").mkdir()
            (home / ".tapl").mkdir(parents=True)
            parent_config = parent / ".tapl" / "config.toml"
            parent_config.write_text("[search]\nmax_results = 3\n", encoding="utf-8")
            user_config = home / ".tapl" / "config.toml"
            user_config.write_text("[search]\nmax_results = 7\n", encoding="utf-8")

            inherited = config.load(start=child, home=home)
            self.assertEqual(Path(inherited.path).resolve(), user_config.resolve())
            self.assertEqual(inherited.search.max_results, 7)
            child_config = child / ".tapl" / "config.toml"
            child_config.parent.mkdir()
            child_config.write_text("[search]\nmax_results = 5\n", encoding="utf-8")
            selected = config.load(start=child, home=home)
            self.assertEqual(Path(selected.path).resolve(), child_config.resolve())
            self.assertEqual(selected.search.max_results, 5)


class InstallerBoundaryTests(unittest.TestCase):
    def test_companion_commands_are_derived_from_taplctl_path(self) -> None:
        self.assertEqual(
            install.sibling_tapl_command("/opt/tapl/bin/taplctl", "tapl-mcp"),
            "/opt/tapl/bin/tapl-mcp",
        )
        self.assertEqual(
            install.sibling_tapl_command("/opt/tapl/bin/taplctl", "tapl-hook"),
            "/opt/tapl/bin/tapl-hook",
        )
        self.assertEqual(install.sibling_tapl_command("taplctl", "tapl-mcp"), "tapl-mcp")

    def test_path_resolution_feeds_sibling_derivation(self) -> None:
        with mock.patch.object(install.shutil, "which", return_value="/usr/local/tapl/bin/taplctl"):
            resolved = install.resolved_taplctl_command(None)

        self.assertEqual(resolved, "/usr/local/tapl/bin/taplctl")
        self.assertEqual(
            install.sibling_tapl_command(resolved, "tapl-mcp"),
            "/usr/local/tapl/bin/tapl-mcp",
        )

    def test_generated_hook_commands_use_tapl_hook(self) -> None:
        generated = install.build_hooks_config(
            taplctl_command="/opt/tapl/bin/taplctl",
            mode="observe",
        )
        commands = [
            hook["command"]
            for entries in generated["hooks"].values()
            for entry in entries
            for hook in entry["hooks"]
        ]

        self.assertTrue(commands)
        self.assertTrue(all(command.startswith("/opt/tapl/bin/tapl-hook ") for command in commands))
        self.assertTrue(all("hook-event" not in command for command in commands))

    def test_generated_mcp_config_uses_tapl_mcp_without_legacy_args(self) -> None:
        template = """
[mcp_servers.tapl]
command = "taplctl"
args = ["mcp"]
cwd = "/stale/workspace"
enabled = true
""".lstrip()

        rendered = install.retarget_codex_mcp_config(
            template,
            taplctl_command="/opt/tapl/bin/taplctl",
        )
        tapl = tomllib.loads(rendered)["mcp_servers"]["tapl"]

        self.assertEqual(tapl["command"], "/opt/tapl/bin/tapl-mcp")
        self.assertNotIn("args", tapl)
        self.assertNotIn("cwd", tapl)

    def test_existing_legacy_mcp_config_is_migrated(self) -> None:
        template = """
[mcp_servers.tapl]
command = "/opt/tapl/bin/tapl-mcp"
enabled = true
""".lstrip()
        existing = """
[mcp_servers.tapl]
command = "/opt/tapl/bin/taplctl"
args = ["mcp"]
cwd = "/stale/workspace"
enabled = true
user_setting = "keep"

[mcp_servers.other]
command = "other-mcp"
cwd = "/other/workspace"
""".lstrip()

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.toml"
            path.write_text(existing, encoding="utf-8")
            install.merge_codex_config(path, template, force=False, dry_run=False)
            servers = tomllib.loads(path.read_text(encoding="utf-8"))["mcp_servers"]
            tapl = servers["tapl"]

        self.assertEqual(tapl["command"], "/opt/tapl/bin/tapl-mcp")
        self.assertNotIn("args", tapl)
        self.assertNotIn("cwd", tapl)
        self.assertEqual(tapl["user_setting"], "keep")
        self.assertEqual(servers["other"]["cwd"], "/other/workspace")

    def test_pyproject_registers_dedicated_hook_script(self) -> None:
        pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
        scripts = tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]["scripts"]
        self.assertEqual(scripts["tapl-hook"], "taplctl.hook_cli:main")
        self.assertEqual(scripts["tapl-mcp"], "taplctl.mcp_server:main")


if __name__ == "__main__":
    unittest.main()
