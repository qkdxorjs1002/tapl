from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest import mock

from taplctl import cli, config


class ConfigGetTests(unittest.TestCase):
    def run_cli(self, arguments: list[str]) -> tuple[int, str, str]:
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = cli.main(arguments)
        return code, stdout.getvalue(), stderr.getvalue()

    def get(self, path: Path, key: str | None = None, output: str = "--json"):
        arguments = ["--config", str(path), "config", "get"]
        if key is not None:
            arguments.append(key)
        if output:
            arguments.append(output)
        return self.run_cli(arguments)

    def test_get_missing_file_returns_defaults_without_writes_or_auto_install(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "missing" / "config.toml"
            with mock.patch.object(cli.tapl_install, "auto_install_if_needed") as install:
                with mock.patch.object(cli, "open_conn") as open_conn:
                    code, output, error = self.get(path)
            self.assertEqual((code, error), (0, ""))
            payload = json.loads(output)
            self.assertEqual(payload["path"], str(path))
            self.assertFalse(payload["exists"])
            self.assertIsNone(payload["key"])
            self.assertEqual(set(payload["value"]), {"search", "viewer", "recall", "subagents"})
            self.assertEqual(payload["value"]["search"]["mode"], config.DEFAULT_SEARCH_MODE)
            self.assertIsNone(payload["value"]["subagents"]["available_models"])
            self.assertEqual(list(root.iterdir()), [])
            install.assert_not_called()
            open_conn.assert_not_called()

    def test_get_uses_explicit_repo_user_precedence_without_merging_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo, home = root / "repo", root / "home"
            repo_config, user_config = repo / ".tapl/config.toml", home / ".tapl/config.toml"
            for path, value in ((repo_config, 3), (user_config, 7)):
                path.parent.mkdir(parents=True)
                path.write_text(f"[search]\nmax_results = {value}\n")
            explicit = root / "explicit.toml"
            explicit.write_text("[search]\nmax_results = 11\n")
            with mock.patch.object(Path, "cwd", return_value=repo), mock.patch.object(Path, "home", return_value=home):
                for selected, expected in ((explicit, 11), (None, 3)):
                    args = (["--config", str(selected)] if selected else [])
                    code, output, error = self.run_cli([*args, "config", "get", "search.max_results"])
                    self.assertEqual((code, output, error), (0, f"{expected}\n", ""))
                repo_config.unlink()
                code, output, _ = self.run_cli(["config", "get", "search.max_results", "--json"])
                self.assertEqual(code, 0)
                self.assertEqual(json.loads(output)["value"], 7)
                self.assertEqual(json.loads(output)["path"], str(user_config))
                code, output, _ = self.get(root / "absent.toml", "search.max_results")
                self.assertEqual(code, 0)
                self.assertEqual(json.loads(output)["value"], config.DEFAULT_SEARCH_MAX_RESULTS)
                user_config.unlink()
                code, output, _ = self.run_cli(["config", "get", "search.max_results"])
                self.assertEqual((code, output), (0, f"{config.DEFAULT_SEARCH_MAX_RESULTS}\n"))
                self.assertFalse(repo_config.exists())
                self.assertFalse(user_config.exists())

    def test_get_returns_normalized_derived_and_inferred_runtime_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.toml"
            original = (
                '[search]\nmode = "WORD"\nmax-results = 4\nhybrid_semantic_ratio = 0.8\n'
                '[subagents]\nstrategy = "balanced"\nprofiles = []\n'
                '[subagents.models]\n"gpt-5.6-sol" = ["high"]\n'
            )
            path.write_text(original)
            expected = {
                "search.mode": "word",
                "search.max_results": 4,
                "subagents.setup_complete": True,
                "subagents.models.gpt-5.6-sol": ["high"],
                "subagents.profiles": [],
                "subagents.available_models": None,
            }
            for key, value in expected.items():
                with self.subTest(key=key):
                    code, output, error = self.get(path, key)
                    self.assertEqual((code, error), (0, ""))
                    self.assertEqual(json.loads(output)["value"], value)
            code, output, _ = self.get(path, "search")
            self.assertEqual(code, 0)
            self.assertAlmostEqual(json.loads(output)["value"]["hybrid_bm25_ratio"], 0.2)
            self.assertEqual(path.read_text(), original)

    def test_get_catalog_model_ids_with_dots(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.toml"
            path.write_text('[subagents.available_models]\n"gpt-5.6-sol" = ["high", "xhigh"]\n')
            code, output, error = self.get(path, "subagents.available_models.gpt-5.6-sol")
            self.assertEqual((code, error), (0, ""))
            self.assertEqual(json.loads(output)["value"], ["high", "xhigh"])

    def test_get_human_output_preserves_false_zero_and_empty_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.toml"
            path.write_text(
                '[recall]\nenabled = false\n[search]\nsearchd_model_idle_timeout_seconds = 0\n'
                '[subagents]\nprofiles = []\npreference = ""\n'
            )
            cases = {
                "recall.enabled": "false\n",
                "search.searchd_model_idle_timeout_seconds": "0\n",
                "subagents.preference": "\n",
                "subagents.profiles": "[]\n",
                "subagents.models": "{}\n",
                "subagents.available_models": "null\n",
                "search.mode": f"{config.DEFAULT_SEARCH_MODE}\n",
            }
            for key, expected in cases.items():
                with self.subTest(key=key):
                    self.assertEqual(self.get(path, key, output=""), (0, expected, ""))
            code, output, _ = self.get(path, output="")
            self.assertEqual(code, 0)
            self.assertFalse(json.loads(output)["recall"]["enabled"])

    def test_agent_get_keeps_empty_values_and_exact_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.toml"
            path.write_text(
                '[recall]\nenabled = false\n[subagents]\nprofiles = []\npreference = "<quality&speed>"\n'
                '[subagents.models]\n"gpt-5.6-sol" = ["high"]\n'
            )
            for key in (None, "subagents", "subagents.profiles", "subagents.available_models", "recall.enabled", "subagents.preference"):
                with self.subTest(key=key):
                    code, output, error = self.get(path, key, output="--agent")
                    self.assertEqual((code, error), (0, ""))
                    element = ET.fromstring(output)
                    self.assertEqual(element.findtext("config_action"), "get")
                    value = element.find("value")
                    self.assertIsNotNone(value)
                    self.assertEqual(value.attrib["format"], "json")
                    _, expected, _ = self.get(path, key)
                    self.assertEqual(json.loads(value.text), json.loads(expected)["value"])

    def test_get_unknown_keys_fail_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.toml"
            path.write_text('[search]\nmode = "word"\n')
            before = path.read_bytes()
            for key in ("", " search.mode", "missing", "search.missing", "search.mode.extra", "search.", "subagents.models.absent", "path", "exists"):
                with self.subTest(key=key):
                    code, output, _ = self.get(path, key)
                    self.assertEqual(code, 1)
                    self.assertFalse(json.loads(output)["ok"])
                    self.assertIn("error", json.loads(output))
            self.assertEqual(path.read_bytes(), before)

    def test_get_invalid_config_fails_instead_of_hiding_errors(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.toml"
            for text in ("[search\n", '[search]\nmode = "unsupported"\n'):
                with self.subTest(text=text):
                    path.write_text(text)
                    code, output, _ = self.get(path, "search.mode")
                    self.assertEqual(code, 1)
                    self.assertFalse(json.loads(output)["ok"])
                    self.assertEqual(path.read_text(), text)


if __name__ == "__main__":
    unittest.main()
