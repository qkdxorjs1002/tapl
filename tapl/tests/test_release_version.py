from __future__ import annotations

import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
HELPER = REPOSITORY_ROOT / ".github" / "scripts" / "release_version.py"
WORKFLOW = REPOSITORY_ROOT / ".github" / "workflows" / "release.yml"

_SPEC = importlib.util.spec_from_file_location("release_version", HELPER)
assert _SPEC is not None and _SPEC.loader is not None
release_version = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = release_version
_SPEC.loader.exec_module(release_version)


class ReleaseVersionTests(unittest.TestCase):
    def test_stable_version_is_unchanged(self) -> None:
        parsed = release_version.parse_release_tag("2.0.0")

        self.assertEqual(parsed.version, "2.0.0")
        self.assertEqual(parsed.python_version, "2.0.0")
        self.assertFalse(parsed.prerelease)
        self.assertEqual(
            parsed.github_outputs(),
            {
                "version": "2.0.0",
                "python_version": "2.0.0",
                "prerelease": "false",
            },
        )

    def test_prereleases_map_from_semver_to_pep440(self) -> None:
        cases = {
            "2.0.0-alpha1": "2.0.0a1",
            "2.0.0-beta1": "2.0.0b1",
            "2.0.0-beta0": "2.0.0b0",
            "2.0.0-beta12": "2.0.0b12",
            "2.0.0-rc3": "2.0.0rc3",
        }

        for tag, python_version in cases.items():
            with self.subTest(tag=tag):
                parsed = release_version.parse_release_tag(tag)
                self.assertEqual(parsed.version, tag)
                self.assertEqual(parsed.python_version, python_version)
                self.assertTrue(parsed.prerelease)
                self.assertEqual(parsed.github_outputs()["prerelease"], "true")

    def test_noncanonical_tags_are_rejected(self) -> None:
        invalid = (
            "v2.0.0",
            "2.0.0-beta",
            "2.0.0-alpha",
            "2.0.0-rc",
            "2.0.0-preview1",
            "2.0.0-beta01",
            "02.0.0",
            "2.0",
            "2.0.0+build.1",
            "2.0.0-beta1+build.1",
        )

        for tag in invalid:
            with self.subTest(tag=tag), self.assertRaises(ValueError):
                release_version.parse_release_tag(tag)

    def test_cli_writes_github_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            output = Path(temporary_directory) / "github-output"
            result = subprocess.run(
                [
                    sys.executable,
                    str(HELPER),
                    "2.0.0-beta1",
                    "--github-output",
                    str(output),
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, "")
            self.assertEqual(
                output.read_text(encoding="utf-8"),
                "version=2.0.0-beta1\n"
                "python_version=2.0.0b1\n"
                "prerelease=true\n",
            )

    def test_cli_rejects_leading_v(self) -> None:
        result = subprocess.run(
            [sys.executable, str(HELPER), "v2.0.0"],
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("release tag must be x.y.z", result.stderr)


class ReleaseWorkflowPrereleaseContractTests(unittest.TestCase):
    def test_workflow_uses_split_versions_and_rolling_pre_channel(self) -> None:
        workflow = WORKFLOW.read_text(encoding="utf-8")

        self.assertIn("python .github/scripts/release_version.py", workflow)
        self.assertIn("steps.version.outputs.python_version", workflow)
        self.assertIn("taplctl-${PYTHON_VERSION}-py3-none-any.whl", workflow)
        self.assertIn("tapl-workflow-viewer-${TAG_VERSION}.vsix", workflow)
        self.assertIn("taplctl-mcp-runtime-${TAG_VERSION}-${target}.tar.gz", workflow)
        self.assertIn('"prerelease": "true" if self.prerelease else "false"', HELPER.read_text())
        self.assertIn("Upload stable VSIX for Marketplace publication", workflow)
        self.assertIn("- name: Require Homebrew tap token\n        env:", workflow)
        self.assertIn("- name: Checkout Homebrew tap\n        uses:", workflow)
        self.assertIn("- name: Update taplctl Homebrew package\n        env:", workflow)
        self.assertIn("--pre-formula homebrew-tap/Formula/taplctl-pre.rb", workflow)
        self.assertIn("--pre-alias homebrew-tap/Aliases/taplctl@pre", workflow)

        stable_branch = '''if [[ "${RELEASE_PRERELEASE}" == "false" ]]; then'''
        branch_start = workflow.index(stable_branch)
        branch_end = workflow.index("\n\n          ruby -c", branch_start)
        stable_body = workflow[branch_start:branch_end]
        self.assertIn('stable_brew_files+=("${PRE_FORMULA_TEMPLATE}")', stable_body)
        self.assertIn('stable_brew_files+=("homebrew-tap/Formula/taplctl-semantic.rb")', stable_body)
        self.assertNotIn('stable_brew_files+=("${PRE_FORMULA_TEMPLATE}")', workflow[branch_end:])
        self.assertNotIn(
            'stable_brew_files+=("homebrew-tap/Formula/taplctl-semantic.rb")',
            workflow[branch_end:],
        )
        self.assertIn("create_args+=(--prerelease)", workflow)
        self.assertIn("edit_args+=(--prerelease=false)", workflow)
        self.assertIn("expected 24 TAPL MCP tools", workflow)

    def test_marketplace_job_publishes_only_stable_tags_with_entra_id(self) -> None:
        workflow = WORKFLOW.read_text(encoding="utf-8")

        self.assertIn("prerelease: ${{ steps.version.outputs.prerelease }}", workflow)
        self.assertIn("version: ${{ steps.version.outputs.version }}", workflow)
        self.assertIn("if: steps.version.outputs.prerelease == 'false'", workflow)
        self.assertIn("if: needs.release.outputs.prerelease == 'false'", workflow)
        self.assertIn("environment: vscode-marketplace", workflow)
        self.assertIn("id-token: write", workflow)
        self.assertIn("uses: azure/login@v3", workflow)
        self.assertIn("${{ secrets.AZURE_CLIENT_ID }}", workflow)
        self.assertIn("${{ secrets.AZURE_TENANT_ID }}", workflow)
        self.assertIn("${{ secrets.AZURE_SUBSCRIPTION_ID }}", workflow)
        self.assertIn("--azure-credential", workflow)
        self.assertIn("--skip-duplicate", workflow)
        self.assertIn("--packagePath", workflow)
        self.assertNotIn("VSCE_PAT", workflow)

        try:
            import yaml
        except ImportError:
            self.skipTest("PyYAML is not installed")

        parsed = yaml.safe_load(workflow)
        release_job = parsed["jobs"]["release"]
        marketplace_job = parsed["jobs"]["marketplace"]
        self.assertNotIn("if", release_job)
        self.assertEqual(marketplace_job["needs"], "release")
        self.assertEqual(marketplace_job["environment"], "vscode-marketplace")
        self.assertEqual(marketplace_job["permissions"]["contents"], "read")
        self.assertEqual(marketplace_job["permissions"]["id-token"], "write")

    def test_workflow_is_valid_yaml_when_pyyaml_is_available(self) -> None:
        try:
            import yaml
        except ImportError:
            self.skipTest("PyYAML is not installed")

        parsed = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
        self.assertIn("release", parsed["jobs"])


if __name__ == "__main__":
    unittest.main()
