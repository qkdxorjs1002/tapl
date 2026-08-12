from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import textwrap
import tomllib
import unittest
from pathlib import Path

import yaml


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
TAPL_ROOT = REPOSITORY_ROOT / "tapl"
PYPROJECT = TAPL_ROOT / "pyproject.toml"
RELEASE_WORKFLOW = REPOSITORY_ROOT / ".github" / "workflows" / "release.yml"
FORMULA_UPDATER = REPOSITORY_ROOT / ".github" / "scripts" / "update_homebrew_formula.rb"
VSCODE_PACKAGE = REPOSITORY_ROOT / "vscode-extension" / "package.json"
VSCODE_IGNORE = REPOSITORY_ROOT / "vscode-extension" / ".vscodeignore"
VSCODE_BUNDLE_SCRIPT = REPOSITORY_ROOT / "vscode-extension" / "scripts" / "bundle-extension.mjs"


class PythonPackagingContractTests(unittest.TestCase):
    def test_mcp_is_pinned_core_dependency_and_semantic_stack_is_optional(self) -> None:
        with PYPROJECT.open("rb") as pyproject_file:
            project = tomllib.load(pyproject_file)["project"]

        self.assertEqual(project["dependencies"], ["mcp==2.0.0"])
        self.assertEqual(
            project["optional-dependencies"]["semantic"],
            ["numpy>=1.26", "sentence-transformers>=5.0.0", "sqlite-vec>=0.1.6"],
        )

    def test_base_cli_import_does_not_require_mcp(self) -> None:
        result = self._run_with_mcp_import_blocked(
            "import taplctl.cli as cli; cli.main(['--version'])",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertRegex(
            result.stdout.strip(),
            r"^taplctl \d+\.\d+\.\d+(?:(?:a|b|rc)\d+)?$",
        )

    def test_retired_mcp_cli_command_points_to_dedicated_entrypoint(self) -> None:
        result = self._run_with_mcp_import_blocked(
            "import taplctl.cli as cli; raise SystemExit(cli.main(['mcp']))",
        )

        self.assertEqual(result.returncode, 2)
        self.assertIn("`taplctl mcp` is no longer a public command", result.stderr)
        self.assertIn("`tapl-mcp`", result.stderr)
        self.assertNotIn("MCP runtime dependency", result.stderr)

    def test_vscode_package_bundles_the_mcp_client_runtime(self) -> None:
        package = json.loads(VSCODE_PACKAGE.read_text(encoding="utf-8"))
        self.assertEqual(package["dependencies"]["@modelcontextprotocol/sdk"], "1.30.0")
        self.assertEqual(package["dependencies"]["zod"], "4.4.3")
        compile_script = package["scripts"]["compile:extension"]
        self.assertIn("node scripts/bundle-extension.mjs", compile_script)
        self.assertIn("--no-dependencies", package["scripts"]["package"])
        bundle_script = VSCODE_BUNDLE_SCRIPT.read_text(encoding="utf-8")
        self.assertIn("external: ['vscode']", bundle_script)
        self.assertIn("node_modules/ajv/dist/runtime/uri.js", bundle_script)
        self.assertIn("node_modules/ajv-formats/dist/formats.js", bundle_script)

        ignored_paths = {
            line.strip()
            for line in VSCODE_IGNORE.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        }
        self.assertIn("node_modules/**", ignored_paths)

    def _run_with_mcp_import_blocked(self, statement: str) -> subprocess.CompletedProcess[str]:
        script = textwrap.dedent(
            f"""
            import importlib.abc
            import sys

            class BlockMcp(importlib.abc.MetaPathFinder):
                def find_spec(self, fullname, path=None, target=None):
                    if fullname == "mcp" or fullname.startswith("mcp."):
                        raise ModuleNotFoundError(
                            f"No module named {{fullname!r}}",
                            name="mcp",
                        )
                    return None

            sys.meta_path.insert(0, BlockMcp())
            {statement}
            """
        )
        env = os.environ.copy()
        env.pop("TAPL_ENABLE_LEGACY_WORKFLOW_CLI", None)
        env["PYTHONPATH"] = str(TAPL_ROOT)
        return subprocess.run(
            [sys.executable, "-c", script],
            cwd=TAPL_ROOT,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )


class HomebrewFormulaUpdaterTests(unittest.TestCase):
    BASE_FORMULA = textwrap.dedent(
        """\
        class Taplctl < Formula
          include Language::Python::Virtualenv

          desc "Fixture"
          homepage "https://example.invalid"
          url "https://example.invalid/taplctl-1.5.0.whl"
          version "1.5.0"
          sha256 "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"

          depends_on "python@3.12"

          def install
            venv = virtualenv_create(libexec, "python3.12", system_site_packages: false)
            venv.pip_install_and_link buildpath
          end

          service do
            run [opt_bin/"taplctl", "searchd", "run"]
            keep_alive true
          end

          test do
            assert_match(/taplctl/, shell_output("#{bin}/taplctl --version"))
          end
        end
        """
    )

    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary_directory.name)
        self.base_formula = self.base / "taplctl.rb"
        self.semantic_formula = self.base / "taplctl-semantic.rb"
        self.base_formula.write_text(self.BASE_FORMULA, encoding="utf-8")
        self.semantic_formula.write_text(
            self.BASE_FORMULA.replace("class Taplctl <", "class TaplctlSemantic <").replace(
                "  def install\n",
                "  resource \"numpy\" do\n"
                "    url \"https://example.invalid/numpy.whl\"\n"
                "    sha256 \"ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff\"\n"
                "  end\n\n"
                "  def install\n",
            ),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_updater_adds_runtime_offline_install_and_smoke_test_idempotently(self) -> None:
        first = self._run_updater()
        self.assertEqual(first.returncode, 0, first.stderr)
        base_after_first = self.base_formula.read_text(encoding="utf-8")
        semantic_after_first = self.semantic_formula.read_text(encoding="utf-8")

        second = self._run_updater()
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(self.base_formula.read_text(encoding="utf-8"), base_after_first)
        self.assertEqual(self.semantic_formula.read_text(encoding="utf-8"), semantic_after_first)

        for formula in (base_after_first, semantic_after_first):
            self.assertIn('version "1.5.1"', formula)
            self.assertEqual(formula.count('resource "mcp-runtime" do'), 4)
            self.assertEqual(formula.count("# taplctl-mcp-runtime-begin"), 1)
            self.assertIn('resource("mcp-runtime").stage', formula)
            self.assertIn('"--no-index", "--no-deps", "--no-compile"', formula)
            self.assertIn('bin.install_symlink libexec/"bin/tapl-mcp"', formula)
            self.assertIn('from taplctl.mcp_server import create_server', formula)
            self.assertIn('run [opt_bin/"taplctl", "viewer"]', formula)

        self.assertEqual(
            self._conflict_lines(base_after_first),
            [
                'conflicts_with "taplctl-semantic", because: "both install the taplctl executable"',
                'conflicts_with "taplctl-pre", because: "both install the taplctl executable"',
            ],
        )
        self.assertEqual(
            self._conflict_lines(semantic_after_first),
            [
                'conflicts_with "taplctl", because: "both install the taplctl executable"',
                'conflicts_with "taplctl-pre", because: "both install the taplctl executable"',
            ],
        )
        self.assertIn('resource "numpy" do', semantic_after_first)
        for path in (self.base_formula, self.semantic_formula):
            syntax = subprocess.run(
                ["ruby", "-c", str(path)],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(syntax.returncode, 0, syntax.stderr)

    @staticmethod
    def _conflict_lines(formula: str) -> list[str]:
        return [line.strip() for line in formula.splitlines() if line.lstrip().startswith("conflicts_with ")]

    def _run_updater(self) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env.update(
            {
                "RELEASE_VERSION": "1.5.1",
                "WHEEL_URL": "https://example.invalid/taplctl-1.5.1.whl",
                "WHEEL_SHA256": "1" * 64,
                "MCP_RUNTIME_MACOS_ARM64_URL": "https://example.invalid/macos-arm64.tar.gz",
                "MCP_RUNTIME_MACOS_ARM64_SHA256": "2" * 64,
                "MCP_RUNTIME_MACOS_X86_64_URL": "https://example.invalid/macos-x86_64.tar.gz",
                "MCP_RUNTIME_MACOS_X86_64_SHA256": "3" * 64,
                "MCP_RUNTIME_LINUX_ARM64_URL": "https://example.invalid/linux-arm64.tar.gz",
                "MCP_RUNTIME_LINUX_ARM64_SHA256": "4" * 64,
                "MCP_RUNTIME_LINUX_X86_64_URL": "https://example.invalid/linux-x86_64.tar.gz",
                "MCP_RUNTIME_LINUX_X86_64_SHA256": "5" * 64,
            }
        )
        return subprocess.run(
            ["ruby", str(FORMULA_UPDATER), str(self.base_formula), str(self.semantic_formula)],
            cwd=REPOSITORY_ROOT,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )


class ReleaseWorkflowContractTests(unittest.TestCase):
    def test_release_builds_validates_and_installs_all_runtime_archives(self) -> None:
        workflow_text = RELEASE_WORKFLOW.read_text(encoding="utf-8")
        workflow = yaml.safe_load(workflow_text)
        steps = workflow["jobs"]["release"]["steps"]
        named_steps = {step.get("name"): step for step in steps if step.get("name")}

        runtime_step = named_steps["Build MCP runtime wheelhouses"]["run"]
        for target in ("macos-arm64", "macos-x86_64", "linux-arm64", "linux-x86_64"):
            self.assertIn(target, runtime_step)
        self.assertIn("--only-binary=:all:", runtime_step)
        self.assertIn("mcp==", runtime_step)
        self.assertIn("--sort=name", runtime_step)

        validation_step = named_steps["Validate release assets"]
        for env_name in (
            "MCP_RUNTIME_MACOS_ARM64_URL",
            "MCP_RUNTIME_MACOS_X86_64_URL",
            "MCP_RUNTIME_LINUX_ARM64_URL",
            "MCP_RUNTIME_LINUX_X86_64_URL",
        ):
            self.assertIn(env_name, validation_step["env"])
        self.assertIn("required_runtime_distributions", validation_step["run"])

        smoke_step = named_steps["Smoke-test isolated MCP runtime"]["run"]
        self.assertIn("--no-index --no-deps --no-compile", smoke_step)
        self.assertIn("Client(server)", smoke_step)
        self.assertIn('call_tool("tapl_get_status"', smoke_step)

        update_step = named_steps["Update taplctl Homebrew package"]
        self.assertIn("update_homebrew_formula.rb", update_step["run"])
        self.assertIn("MCP_RUNTIME_MACOS_ARM64_SHA256", update_step["env"])
        self.assertLess(
            [step.get("name") for step in steps].index("Publish GitHub Release"),
            [step.get("name") for step in steps].index("Update taplctl Homebrew package"),
        )


if __name__ == "__main__":
    unittest.main()
