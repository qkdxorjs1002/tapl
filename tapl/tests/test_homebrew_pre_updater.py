from __future__ import annotations

import os
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
FORMULA_UPDATER = REPOSITORY_ROOT / ".github" / "scripts" / "update_homebrew_formula.rb"


class HomebrewPrereleaseFormulaUpdaterTests(unittest.TestCase):
    STABLE_FORMULA_TEMPLATE = textwrap.dedent(
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

          test do
            assert_match(/taplctl \\d+\\.\\d+\\.\\d+\\z/, shell_output("#{bin}/taplctl --version"))
          end
        end
        """
    )

    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary_directory.name)
        self.formula_directory = self.base / "Formula"
        self.alias_directory = self.base / "Aliases"
        self.template = self.formula_directory / "taplctl.rb"
        self.pre_formula = self.formula_directory / "taplctl-pre.rb"
        self.pre_alias = self.alias_directory / "taplctl@pre"
        self.formula_directory.mkdir()
        self.template.write_text(self.STABLE_FORMULA_TEMPLATE, encoding="utf-8")

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_creates_and_updates_rolling_prerelease_formula_idempotently(self) -> None:
        first = self._run_updater("2.0.0b1")
        self.assertEqual(first.returncode, 0, first.stderr)

        formula_after_first = self.pre_formula.read_text(encoding="utf-8")
        self.assertIn("class TaplctlPre < Formula", formula_after_first)
        self.assertIn('version "2.0.0b1"', formula_after_first)
        self.assertIn('url "https://example.invalid/taplctl-2.0.0b1.whl"', formula_after_first)
        self.assertIn(
            'conflicts_with "taplctl", because: "both install the taplctl executable"',
            formula_after_first,
        )
        self.assertIn(
            'conflicts_with "taplctl-semantic", because: "both install the taplctl executable"',
            formula_after_first,
        )
        self.assertIn(
            r"assert_match(/taplctl \d+\.\d+\.\d+(?:(?:a|b|rc)\d+)?\z/",
            formula_after_first,
        )
        self.assertTrue(self.pre_alias.is_symlink())
        self.assertEqual(self.pre_alias.readlink(), Path("../Formula/taplctl-pre.rb"))

        second = self._run_updater("2.0.0b1")
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(self.pre_formula.read_text(encoding="utf-8"), formula_after_first)
        self.assertTrue(self.pre_alias.is_symlink())
        self.assertEqual(self.pre_alias.readlink(), Path("../Formula/taplctl-pre.rb"))

    def test_older_release_does_not_replace_prerelease_formula_metadata(self) -> None:
        created = self._run_updater("2.0.0b1")
        self.assertEqual(created.returncode, 0, created.stderr)
        metadata_at_prerelease = self.pre_formula.read_text(encoding="utf-8")

        older = self._run_updater("1.9.0")
        self.assertEqual(older.returncode, 0, older.stderr)
        self.assertIn("Skipping", older.stderr)
        self.assertEqual(self.pre_formula.read_text(encoding="utf-8"), metadata_at_prerelease)

    def test_refuses_to_replace_a_non_symlink_prerelease_alias(self) -> None:
        self.alias_directory.mkdir()
        self.pre_alias.write_text("not a symlink", encoding="utf-8")

        result = self._run_updater("2.0.0b1")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Refusing to replace non-symlink prerelease alias", result.stderr)
        self.assertEqual(self.pre_alias.read_text(encoding="utf-8"), "not a symlink")

    def _run_updater(self, version: str) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env.update(
            {
                "PRE_FORMULA_TEMPLATE": str(self.template),
                "RELEASE_VERSION": version,
                "WHEEL_URL": f"https://example.invalid/taplctl-{version}.whl",
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
            [
                "ruby",
                str(FORMULA_UPDATER),
                "--pre-formula",
                str(self.pre_formula),
                "--pre-alias",
                str(self.pre_alias),
            ],
            cwd=REPOSITORY_ROOT,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )


if __name__ == "__main__":
    unittest.main()
