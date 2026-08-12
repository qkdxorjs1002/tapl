from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest import mock

from taplctl import cli, hook_cli, install


MANAGEMENT_COMMANDS = {
    "init",
    "doctor",
    "update",
    "install",
    "viewer",
    "reindex",
    "searchd",
    "import-md",
}


def root_commands(parser: argparse.ArgumentParser) -> set[str]:
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return set(action.choices)
    raise AssertionError("root subparser action not found")


class PublicCliBoundaryTests(unittest.TestCase):
    def test_public_parser_contains_only_management_commands(self) -> None:
        with mock.patch.dict(os.environ, {cli.LEGACY_WORKFLOW_CLI_ENV: ""}):
            parser = cli.build_parser()

        self.assertEqual(root_commands(parser), MANAGEMENT_COMMANDS)
        help_text = parser.format_help()
        self.assertIn("Agent workflow operations are MCP-only", help_text)
        self.assertNotIn("hook-event", help_text)
        self.assertNotIn("{mcp,", help_text)

    def test_removed_workflow_command_has_actionable_mcp_error(self) -> None:
        with mock.patch.dict(os.environ, {cli.LEGACY_WORKFLOW_CLI_ENV: ""}):
            parser = cli.build_parser()
        stderr = io.StringIO()

        with contextlib.redirect_stderr(stderr), self.assertRaises(SystemExit) as raised:
            parser.parse_args(["status"])

        self.assertEqual(raised.exception.code, 2)
        self.assertIn("Agent workflows are MCP-only", stderr.getvalue())
        self.assertIn("tapl-mcp", stderr.getvalue())

    def test_mcp_and_hook_event_point_to_dedicated_executables(self) -> None:
        cases = {
            "mcp": "tapl-mcp",
            "hook-event": "tapl-hook",
        }
        for command, executable in cases.items():
            with self.subTest(command=command):
                with mock.patch.dict(os.environ, {cli.LEGACY_WORKFLOW_CLI_ENV: ""}):
                    parser = cli.build_parser()
                stderr = io.StringIO()
                with contextlib.redirect_stderr(stderr), self.assertRaises(SystemExit):
                    parser.parse_args([command])
                self.assertIn(executable, stderr.getvalue())


class HookEntrypointTests(unittest.TestCase):
    def test_hook_cli_delegates_parsed_event_to_existing_handler(self) -> None:
        with mock.patch.object(cli, "cmd_hook_event", return_value=2) as handler:
            result = hook_cli.main(
                ["--event", "PreToolUse", "--mode", "enforce", "--tool", "Bash", "--json"]
            )

        self.assertEqual(result, 2)
        args = handler.call_args.args[0]
        self.assertEqual(args.event, "PreToolUse")
        self.assertEqual(args.mode, "enforce")
        self.assertEqual(args.tool, "Bash")
        self.assertTrue(args.json)


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
