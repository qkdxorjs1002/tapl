from __future__ import annotations

import argparse
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest import mock

from taplctl import cli, hook_cli, install


MANAGEMENT_COMMANDS = {
    "config",
    "init",
    "doctor",
    "update",
    "install",
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
        self.assertTrue({"status", "mcp", "hook-event"}.isdisjoint(commands))

    def test_config_command_is_management_only_and_skips_auto_install(self) -> None:
        args = cli.build_parser().parse_args(
            ["config", "set", "search.mode", "hybrid"]
        )

        self.assertEqual(args.command, "config")
        self.assertTrue(cli.should_skip_auto_install(args))

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
            "true, false",
            "subagents.models.<model-id> TOML_ARRAY",
        ):
            self.assertIn(expected, config_help)
            self.assertIn(expected, set_help)
            self.assertIn(expected, unset_help)
        self.assertIn("taplctl config set search.mode hybrid", set_help)
        self.assertIn("taplctl config unset search.mode", unset_help)


class HookEntrypointTests(unittest.TestCase):
    def test_hook_cli_handles_event_without_management_cli_bridge(self) -> None:
        connection = mock.Mock()
        outcome = {"event": "PreToolUse", "block": True, "message": "blocked"}
        with (
            mock.patch.object(hook_cli, "_read_stdin_payload", return_value={"cwd": "/workspace"}),
            mock.patch.object(hook_cli.tapl_config, "load", return_value=mock.sentinel.settings),
            mock.patch.object(hook_cli.db, "connect", return_value=connection),
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
                    "/tmp/tapl.db",
                    "--json",
                ]
            )

        self.assertEqual(result, 2)
        self.assertEqual(handler.call_args.kwargs["event"], "PreToolUse")
        self.assertEqual(handler.call_args.kwargs["mode"], "enforce")
        self.assertEqual(handler.call_args.kwargs["tool"], "Bash")
        self.assertEqual(handler.call_args.kwargs["payload"], {"cwd": "/workspace"})
        self.assertIs(handler.call_args.kwargs["tapl_settings"], mock.sentinel.settings)
        connection.close.assert_called_once_with()


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
enabled = true
""".lstrip()

        rendered = install.retarget_codex_mcp_config(
            template,
            taplctl_command="/opt/tapl/bin/taplctl",
        )
        tapl = tomllib.loads(rendered)["mcp_servers"]["tapl"]

        self.assertEqual(tapl["command"], "/opt/tapl/bin/tapl-mcp")
        self.assertNotIn("args", tapl)

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
enabled = true
user_setting = "keep"
""".lstrip()

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.toml"
            path.write_text(existing, encoding="utf-8")
            install.merge_codex_config(path, template, force=False, dry_run=False)
            tapl = tomllib.loads(path.read_text(encoding="utf-8"))["mcp_servers"]["tapl"]

        self.assertEqual(tapl["command"], "/opt/tapl/bin/tapl-mcp")
        self.assertNotIn("args", tapl)
        self.assertEqual(tapl["user_setting"], "keep")

    def test_pyproject_registers_dedicated_hook_script(self) -> None:
        pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
        scripts = tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]["scripts"]
        self.assertEqual(scripts["tapl-hook"], "taplctl.hook_cli:main")
        self.assertEqual(scripts["tapl-mcp"], "taplctl.mcp_server:main")


if __name__ == "__main__":
    unittest.main()
