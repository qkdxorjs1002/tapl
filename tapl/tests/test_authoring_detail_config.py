from __future__ import annotations

import contextlib
from dataclasses import FrozenInstanceError
import io
import json
from pathlib import Path
import tempfile
import tomllib
import unittest
from unittest import mock
import xml.etree.ElementTree as ET

from taplctl import cli, config, config_editor


class AuthoringDetailConfigTests(unittest.TestCase):
    def run_cli(self, arguments: list[str]) -> tuple[int, str, str]:
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = cli.main(arguments)
        return code, stdout.getvalue(), stderr.getvalue()

    def test_default_is_auto_for_direct_and_loaded_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "missing.toml"
            for settings in (
                config.TaplConfig(path=str(path), exists=False),
                config.load(path),
                config.from_mapping({"workflow": {}}, path=path),
            ):
                with self.subTest(settings=settings):
                    self.assertEqual(settings.workflow.authoring_detail, "auto")
                    self.assertEqual(
                        settings.as_dict()["workflow"],
                        {"authoring_detail": "auto"},
                    )
            self.assertFalse(path.exists())
            with self.assertRaises(FrozenInstanceError):
                config.WorkflowConfig().authoring_detail = "minimal"

    def test_runtime_values_are_validated_and_normalized(self) -> None:
        for value in config.AUTHORING_DETAILS:
            with self.subTest(value=value):
                loaded = config.from_mapping(
                    {"workflow": {"authoring_detail": f" {value.upper()} "}},
                    path="config.toml",
                )
                self.assertEqual(loaded.workflow.authoring_detail, value)
        for value in (None, True, 1, 1.0, [], {}):
            with self.subTest(value=value), self.assertRaisesRegex(
                ValueError, r"workflow.authoring_detail must be a string"
            ):
                config.from_mapping(
                    {"workflow": {"authoring_detail": value}}, path="config.toml"
                )
        for value in ("", "brief", "verbose"):
            with self.subTest(value=value), self.assertRaisesRegex(
                ValueError, "must be one of: auto, precise, normal, minimal"
            ):
                config.from_mapping(
                    {"workflow": {"authoring_detail": value}}, path="config.toml"
                )
        for value in (None, False, [], "minimal"):
            with self.subTest(table=value), self.assertRaisesRegex(
                ValueError, "workflow must be a TOML table"
            ):
                config.from_mapping({"workflow": value}, path="config.toml")

    def test_editor_roundtrip_preserves_other_settings_and_unset_restores_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.toml"
            original = '# keep this comment\n[search]\nmode = "word" # keep search\n'
            path.write_text(original)
            for value in config.AUTHORING_DETAILS:
                with self.subTest(value=value):
                    result = config_editor.set_value(path, "workflow.authoring_detail", value)
                    self.assertEqual(result.value, value)
                    self.assertIn(original, path.read_text())
                    self.assertEqual(
                        tomllib.loads(path.read_text())["workflow"]["authoring_detail"],
                        value,
                    )
                    self.assertEqual(config.load(path).workflow.authoring_detail, value)
                    self.assertFalse(
                        config_editor.set_value(path, "workflow.authoring_detail", value).changed
                    )
            self.assertTrue(config_editor.unset_value(path, "workflow.authoring_detail").changed)
            self.assertEqual(config.load(path).workflow.authoring_detail, "auto")
            self.assertEqual(config.load(path).search.mode, "word")
            self.assertFalse(config_editor.unset_value(path, "workflow.authoring_detail").changed)

    def test_invalid_edits_do_not_write_or_create_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.toml"
            path.write_text('[workflow]\nauthoring_detail = "normal"\n')
            original = path.read_bytes()
            for raw_value in ('"brief"', "true", "1", "[]", '""'):
                with self.subTest(raw_value=raw_value), self.assertRaises(ValueError):
                    config_editor.set_value(path, "workflow.authoring_detail", raw_value)
                self.assertEqual(path.read_bytes(), original)
            absent = Path(tmp) / "missing" / "config.toml"
            with self.assertRaises(ValueError):
                config_editor.set_value(absent, "workflow.authoring_detail", '"brief"')
            self.assertFalse(absent.parent.exists())

    def test_cli_get_set_unset_and_agent_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.toml"
            prefix = ["--config", str(path), "config"]
            code, output, error = self.run_cli(
                [*prefix, "get", "workflow.authoring_detail"]
            )
            self.assertEqual((code, output, error), (0, "auto\n", ""))
            self.assertFalse(path.exists())
            code, output, error = self.run_cli(
                [*prefix, "set", "workflow.authoring_detail", '"MINIMAL"', "--json"]
            )
            self.assertEqual((code, error), (0, ""))
            self.assertEqual(json.loads(output)["value"], "minimal")
            code, output, error = self.run_cli([*prefix, "get", "workflow", "--json"])
            self.assertEqual((code, error), (0, ""))
            self.assertEqual(json.loads(output)["value"], {"authoring_detail": "minimal"})
            code, output, error = self.run_cli(
                [*prefix, "get", "workflow.authoring_detail", "--agent"]
            )
            self.assertEqual((code, error), (0, ""))
            self.assertEqual(json.loads(ET.fromstring(output).findtext("value")), "minimal")
            code, output, error = self.run_cli(
                [*prefix, "unset", "workflow.authoring_detail", "--json"]
            )
            self.assertEqual((code, error), (0, ""))
            self.assertTrue(json.loads(output)["changed"])
            self.assertEqual(
                self.run_cli([*prefix, "get", "workflow.authoring_detail"]),
                (0, "auto\n", ""),
            )

    def test_path_precedence_keeps_single_file_selection_without_merging(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            repo, home = root / "repo", root / "home"
            repo.mkdir()
            (repo / ".git").mkdir()
            repo_config = repo / ".tapl/config.toml"
            user_config = home / ".tapl/config.toml"
            user_config.parent.mkdir(parents=True)
            user_config.write_text('[workflow]\nauthoring_detail = "minimal"\n')
            explicit = root / "explicit.toml"
            explicit.write_text('[workflow]\nauthoring_detail = "normal"\n')
            with mock.patch.object(Path, "cwd", return_value=repo), mock.patch.object(
                Path, "home", return_value=home
            ):
                def get(selected: Path | None = None) -> dict:
                    prefix = ["--config", str(selected)] if selected else []
                    code, output, error = self.run_cli(
                        [*prefix, "config", "get", "workflow.authoring_detail", "--json"]
                    )
                    self.assertEqual((code, error), (0, ""))
                    return json.loads(output)

                self.assertEqual(get()["path"], str(user_config))
                self.assertEqual(get()["value"], "minimal")
                repo_config.parent.mkdir()
                repo_config.write_text('[search]\nmode = "word"\n')
                self.assertEqual(get()["path"], str(repo_config))
                self.assertEqual(get()["value"], "auto")
                self.assertEqual(get(explicit)["value"], "normal")
                self.assertEqual(get(root / "absent.toml")["value"], "auto")
                code, output, error = self.run_cli(
                    ["config", "set", "workflow.authoring_detail", "normal", "--json"]
                )
                self.assertEqual((code, error), (0, ""))
                self.assertEqual(json.loads(output)["path"], str(repo_config))
                self.assertEqual(config.load(repo_config).workflow.authoring_detail, "normal")
                self.assertEqual(config.load(user_config).workflow.authoring_detail, "minimal")
                self.assertEqual(config.load(explicit).workflow.authoring_detail, "normal")


if __name__ == "__main__":
    unittest.main()
