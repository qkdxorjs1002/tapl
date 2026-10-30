from __future__ import annotations

import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import textwrap
import tomllib
import unittest
import zipfile
from pathlib import Path
from unittest import mock

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

    def test_management_cli_entrypoint_reports_its_version(self) -> None:
        result = self._run_python(
            "import taplctl.cli as cli; raise SystemExit(cli.main(['--version']))",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertRegex(
            result.stdout.strip(),
            r"^taplctl \d+\.\d+\.\d+(?:(?:a|b|rc)\d+)?$",
        )

    def test_dedicated_mcp_entrypoint_creates_a_server(self) -> None:
        result = self._run_python(
            "from taplctl.mcp_server import create_server; assert create_server() is not None",
        )

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_built_wheel_excludes_retired_importer_and_registers_dedicated_entrypoints(self) -> None:
        uv = shutil.which("uv")
        if uv is None:
            self.skipTest("uv is required to build the release wheel")

        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "wheel"
            environment = os.environ.copy()
            environment.setdefault("UV_CACHE_DIR", str(Path(tmp) / "uv-cache"))
            build = subprocess.run(
                [uv, "build", "--wheel", "--out-dir", str(output), str(TAPL_ROOT)],
                cwd=REPOSITORY_ROOT,
                env=environment,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(build.returncode, 0, build.stderr)
            wheels = list(output.glob("taplctl-*.whl"))
            self.assertEqual(len(wheels), 1)

            with zipfile.ZipFile(wheels[0]) as wheel:
                names = set(wheel.namelist())
                entry_points = next(name for name in names if name.endswith(".dist-info/entry_points.txt"))
                scripts = wheel.read(entry_points).decode("utf-8")

        self.assertNotIn("taplctl/importer.py", names)
        self.assertIn("tapl-mcp = taplctl.mcp_server:main", scripts)
        self.assertIn("tapl-hook = taplctl.hook_cli:main", scripts)

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

    def _run_python(self, statement: str) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env["PYTHONPATH"] = str(TAPL_ROOT)
        return subprocess.run(
            [sys.executable, "-c", statement],
            cwd=TAPL_ROOT,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )


class VsCodeMarketplaceAssetTests(unittest.TestCase):
    def test_manifest_icon_is_a_png_within_marketplace_dimensions(self) -> None:
        package = json.loads(VSCODE_PACKAGE.read_text(encoding="utf-8"))
        icon = VSCODE_PACKAGE.parent / package["icon"]
        with icon.open("rb") as icon_file:
            header = icon_file.read(24)

        self.assertEqual(header[:8], b"\x89PNG\r\n\x1a\n")
        self.assertEqual(header[12:16], b"IHDR")
        self.assertEqual(len(header), 24)
        width, height = struct.unpack(">II", header[16:24])
        for dimension in (width, height):
            self.assertGreater(dimension, 0)
            self.assertLessEqual(
                dimension, 1024, "Marketplace icon dimensions must not exceed 1024 pixels"
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
            self.assertEqual(formula.count("  preserve_rpath\n"), 1)
            self.assertEqual(formula.count('resource "mcp-runtime" do'), 4)
            self.assertEqual(formula.count("# taplctl-mcp-runtime-begin"), 1)
            self.assertIn('resource("mcp-runtime").stage', formula)
            self.assertIn('"--no-index", "--no-deps", "--no-compile"', formula)
            self.assertIn('bin.install_symlink libexec/"bin/tapl-mcp"', formula)
            self.assertIn('bin.install_symlink libexec/"bin/tapl-hook"', formula)
            self.assertIn('assert_path_exists bin/"tapl-hook"', formula)
            self.assertIn('from taplctl.mcp_server import create_server', formula)
            self.assertIn('run [opt_bin/"taplctl", "viewer"]', formula)
            self._assert_running_service_restart_contract(formula)

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

    def _assert_running_service_restart_contract(self, formula: str) -> None:
        self.assertEqual(formula.count("# taplctl-service-restart-begin"), 1)
        self.assertEqual(formula.count("# taplctl-service-restart-end"), 1)
        self.assertEqual(formula.count("def post_install"), 1)
        self.assertIn(
            'quiet_system "/bin/launchctl", "kill", "SIGTERM", "gui/#{Process.uid}/#{plist_name}"',
            formula,
        )
        self.assertIn('quiet_system systemctl, "--user", "daemon-reload"', formula)
        self.assertIn(
            'quiet_system systemctl, "--user", "try-restart", service_name',
            formula,
        )

    def test_updater_rejects_incomplete_service_restart_marker(self) -> None:
        self.base_formula.write_text(
            self.BASE_FORMULA.replace(
                "  def install\n",
                "  # taplctl-service-restart-begin\n\n  def install\n",
                1,
            ),
            encoding="utf-8",
        )

        result = self._run_updater()

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Incomplete marked block # taplctl-service-restart-begin", result.stderr)

    def test_updater_rejects_unmanaged_post_install(self) -> None:
        self.base_formula.write_text(
            self.BASE_FORMULA.replace(
                "  service do\n",
                "  def post_install\n  end\n\n  service do\n",
                1,
            ),
            encoding="utf-8",
        )

        result = self._run_updater()

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Refusing to overwrite unmanaged post_install block", result.stderr)

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


class WindowsInstallerAssetTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.workspace = Path(self.temporary.name)
        self.source = self.workspace / 'scripts'
        self.source.mkdir()
        self.output = self.workspace / 'release-dist'
        for extension in ('ps1', 'cmd'):
            shutil.copyfile(
                REPOSITORY_ROOT / f'.github/scripts/install-windows.{extension}',
                self.source / f'install-windows.{extension}',
            )

    def _prepare(self, tag: str = '3.2.1', python_version: str = '3.2.1',
                 *, check: bool = False) -> subprocess.CompletedProcess[str]:
        command = [sys.executable, str(REPOSITORY_ROOT / '.github/scripts/prepare_windows_installers.py'),
                   '--tag', tag, '--python-version', python_version,
                   '--source-dir', str(self.source), '--output-dir', str(self.output)]
        if check:
            command.append('--check')
        return subprocess.run(command, text=True, capture_output=True, check=False)

    def test_stable_and_prerelease_assets_are_bound_to_their_own_version(self) -> None:
        template = (self.source / 'install-windows.ps1').read_bytes()
        for tag, version in (('3.2.1', '3.2.1'), ('3.2.1-alpha2', '3.2.1a2'),
                             ('3.2.1-beta3', '3.2.1b3'), ('3.2.1-rc4', '3.2.1rc4')):
            with self.subTest(tag=tag):
                result = self._prepare(tag, version)
                self.assertEqual(result.returncode, 0, result.stderr)
                published = (self.output / 'install.ps1').read_bytes()
                expected = template.replace(b'__TAPL_RELEASE_TAG__', tag.encode()).replace(
                    b'__TAPL_RELEASE_PYTHON_VERSION__', version.encode())
                self.assertEqual(published, expected)
                self.assertNotRegex(published, rb'__TAPL_[A-Z0-9_]+__')
                self.assertIn(f'$ReleaseTag = "{tag}"'.encode(), published)
                self.assertIn(f'$ReleasePythonVersion = "{version}"'.encode(), published)
                for extension in ('ps1', 'cmd'):
                    self.assertNotEqual((self.output / f'install.{extension}').read_bytes(),
                                        (REPOSITORY_ROOT / f'install.{extension}').read_bytes())
                self.assertEqual((self.output / 'install.cmd').read_bytes(),
                                 (self.source / 'install-windows.cmd').read_bytes())
                validation = self._prepare(tag, version, check=True)
                self.assertEqual(validation.returncode, 0, validation.stderr)
        self.assertEqual((self.source / 'install-windows.ps1').read_bytes(), template)

    def test_rejects_malformed_and_mismatched_tag_versions_without_writing_assets(self) -> None:
        for tag, version in (('v3.2.1', '3.2.1'), ('3.2.1-beta', '3.2.1b1'),
                             ('03.2.1', '3.2.1'), ('3.2.1', '3.2.2'),
                             ('3.2.1-beta1', '3.2.1'), ('3.2.1-rc1', '3.2.1b1'),
                             ('3.2.1', '3.2.1;exit 0')):
            with self.subTest(tag=tag, version=version):
                result = self._prepare(tag, version)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(self.output.exists())

    def test_rejects_missing_duplicate_and_unresolved_template_tokens(self) -> None:
        template_path = self.source / 'install-windows.ps1'
        template = template_path.read_bytes()
        for token in (b'__TAPL_RELEASE_TAG__', b'__TAPL_RELEASE_PYTHON_VERSION__'):
            for invalid in (template.replace(token, b''), template + b'\n# ' + token):
                with self.subTest(token=token, duplicate=invalid.endswith(token)):
                    template_path.write_bytes(invalid)
                    result = self._prepare()
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn('exactly once', result.stderr)
                    self.assertFalse(self.output.exists())
        template_path.write_bytes(template + b'\n# __TAPL_UNKNOWN_TOKEN__')
        result = self._prepare()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('unresolved template token', result.stderr)
        self.assertFalse(self.output.exists())

    def test_check_rejects_tampered_or_missing_assets_without_rewriting(self) -> None:
        result = self._prepare()
        self.assertEqual(result.returncode, 0, result.stderr)
        for extension in ('ps1', 'cmd'):
            asset = self.output / f'install.{extension}'
            original = asset.read_bytes()
            asset.write_bytes(original + b'\nREM changed')
            validation = self._prepare(check=True)
            self.assertNotEqual(validation.returncode, 0)
            self.assertIn('does not match', validation.stderr)
            self.assertEqual(asset.read_bytes(), original + b'\nREM changed')
            asset.write_bytes(original)
        (self.output / 'install.cmd').unlink()
        self.assertNotEqual(self._prepare(check=True).returncode, 0)
        self.assertFalse((self.output / 'install.cmd').exists())


class ReleaseWorkflowContractTests(unittest.TestCase):
    def test_windows_matrix_and_release_preflight_use_actual_wheel_lifecycle(self) -> None:
        windows = yaml.safe_load(
            (REPOSITORY_ROOT / '.github/workflows/windows.yml').read_text(encoding='utf-8')
        )
        release = yaml.safe_load(RELEASE_WORKFLOW.read_text(encoding='utf-8'))
        ci_job = windows['jobs']['windows-installer-tests']
        preflight = release['jobs']['windows-installer-preflight']
        self.assertEqual(ci_job['steps'], preflight['steps'])
        for job in (ci_job, preflight):
            self.assertEqual(job['runs-on'], 'windows-latest')
            self.assertEqual(job['strategy']['matrix']['python-version'], ['3.11', '3.12'])
            steps = {step['name']: step for step in job['steps']}
            parser = steps['Parse installer and lifecycle smoke with Windows PowerShell 5.1']
            self.assertEqual(parser['shell'], 'powershell')
            self.assertIn('Language.Parser]::ParseFile', parser['run'])
            for script in ('install.ps1', '.github/scripts/install-windows.ps1',
                           '.github/scripts/windows_install_smoke.ps1'):
                self.assertIn(f"'{script}'", parser['run'])
            installer_tests = steps['Run Windows installer tests (stdlib-only fixtures)']['run'].split()
            self.assertEqual(installer_tests[:4], ['python', '-m', 'unittest', '-v'])
            self.assertIn('tapl.tests.test_installer_windows', installer_tests)
            bootstrap = steps['Test standalone Windows bootstrap']
            self.assertIn('python -m unittest -v tapl.tests.test_installer_bootstrap', bootstrap['run'])
            names = [step['name'] for step in job['steps']]
            self.assertLess(names.index(bootstrap['name']), names.index('Test Windows runtime regressions'))
            self.assertIn('tapl.tests.test_release_packaging.WindowsInstallerAssetTests',
                          steps['Test version-bound Windows release assets']['run'])
            self.assertIn('pip wheel --no-deps', steps['Build actual TAPL wheel']['run'])
            smoke = steps['Test actual wheel install, update, reinstall, uninstall and CLI/MCP runtime']
            self.assertEqual(smoke['shell'], 'powershell')
            self.assertIn('windows_install_smoke.ps1 -Wheel $wheel -Python', smoke['run'])
        self.assertIn('windows-installer-preflight', release['jobs']['release']['needs'])
        release_steps = {step['name']: step for step in release['jobs']['release']['steps']}
        preparation = release_steps['Prepare release assets']['run']
        validation = release_steps['Validate release assets']['run']
        helper = 'python .github/scripts/prepare_windows_installers.py'
        for command in (preparation, validation):
            self.assertIn(helper, command)
            self.assertIn('--tag "${TAG_VERSION}" --python-version "${PYTHON_VERSION}"', command)
            self.assertIn('--output-dir release-dist', command)
        self.assertNotIn('--check', preparation)
        self.assertIn('--check', validation)
        self.assertNotIn('cp install.ps1', preparation)
        self.assertNotIn('cp install.cmd', preparation)
        self.assertIn('release-dist/*', release_steps['Publish GitHub Release']['run'])

    def test_windows_wheel_smoke_stages_release_wrapper_with_adjacent_payload(self) -> None:
        smoke = (REPOSITORY_ROOT / '.github/scripts/windows_install_smoke.ps1').read_text(encoding='utf-8')
        for extension in ('ps1', 'cmd'):
            self.assertIn(
                f"Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'install-windows.{extension}') "
                f"-Destination (Join-Path $installerRoot 'install.{extension}')",
                smoke,
            )
        self.assertIn("& (Join-Path $installerRoot 'install.cmd') @InstallerArguments", smoke)
        self.assertNotIn("& (Join-Path $repoRoot 'install.cmd')", smoke)
        self.assertIn("prepare_windows_installers.py') --tag $pinnedVersion", smoke)
        self.assertIn("Pinned release accepted a different manifest version.", smoke)

    def test_release_builds_validates_and_installs_all_runtime_archives(self) -> None:
        workflow_text = RELEASE_WORKFLOW.read_text(encoding="utf-8")
        workflow = yaml.safe_load(workflow_text)
        steps = workflow["jobs"]["release"]["steps"]
        named_steps = {step.get("name"): step for step in steps if step.get("name")}

        runtime_step = named_steps["Build MCP runtime wheelhouses"]["run"]
        for target in ("linux-arm64", "linux-x86_64"):
            self.assertIn(target, runtime_step)
        self.assertNotIn("macos-", runtime_step)
        self.assertIn("--only-binary=:all:", runtime_step)
        self.assertIn("mcp==", runtime_step)
        self.assertIn("--sort=name", runtime_step)

        macos_job = workflow["jobs"]["macos-runtime"]
        self.assertEqual(macos_job["runs-on"], "${{ matrix.runner }}")
        self.assertEqual(
            {item["target"]: item["runner"] for item in macos_job["strategy"]["matrix"]["include"]},
            {"macos-arm64": "macos-15", "macos-x86_64": "macos-15-intel"},
        )
        self.assertEqual(
            {item["target"] for item in macos_job["strategy"]["matrix"]["include"]},
            {"macos-arm64", "macos-x86_64"},
        )
        self.assertIn("macos-runtime", workflow["jobs"]["release"]["needs"])
        macos_steps = {step["name"]: step for step in macos_job["steps"]}
        signer = macos_steps["Sign and verify macOS runtime wheels"]
        self.assertNotIn("if", signer)
        self.assertNotIn("continue-on-error", signer)
        self.assertIn("sign_macos_runtime.sh", signer["run"])
        self.assertEqual(signer["env"]["APPLE_TEAM_ID"], "${{ vars.APPLE_TEAM_ID }}")
        self.assertEqual(
            signer["env"]["MACOS_CERTIFICATE_P12_BASE64"],
            "${{ secrets.MACOS_CERTIFICATE_P12_BASE64 }}",
        )
        macos_names = list(macos_steps)
        install_check = macos_steps["Verify signatures after Homebrew install and reinstall"]
        self.assertNotIn("if", install_check)
        self.assertNotIn("continue-on-error", install_check)
        self.assertIn("verify_homebrew_macos.py", install_check["run"])
        self.assertEqual(install_check["env"]["APPLE_TEAM_ID"], "${{ vars.APPLE_TEAM_ID }}")
        self.assertLess(
            macos_names.index("Archive signed macOS runtime"),
            macos_names.index("Verify signatures after Homebrew install and reinstall"),
        )
        self.assertLess(
            macos_names.index("Verify signatures after Homebrew install and reinstall"),
            macos_names.index("Upload signed macOS runtime"),
        )
        self.assertLess(
            macos_names.index("Sign and verify macOS runtime wheels"),
            macos_names.index("Archive signed macOS runtime"),
        )
        download = named_steps["Download signed macOS runtimes"]
        self.assertEqual(download["with"]["pattern"], "signed-runtime-macos-*")
        self.assertEqual(download["with"]["path"], "release-dist")
        self.assertIs(download["with"]["merge-multiple"], True)
        names = [step.get("name") for step in steps]
        self.assertLess(names.index("Download signed macOS runtimes"), names.index("Prepare release assets"))

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


class ReleaseMcpSmokeTests(unittest.TestCase):
    def _run_smoke(self) -> None:
        from taplctl import db

        workflow = yaml.safe_load(RELEASE_WORKFLOW.read_text(encoding="utf-8"))
        smoke_step = next(
            step for step in workflow["jobs"]["release"]["steps"]
            if step.get("name") == "Smoke-test isolated MCP runtime"
        )
        source = smoke_step["run"].split("<<'PY'\n", 1)[1].rsplit("\nPY", 1)[0]
        with tempfile.TemporaryDirectory() as temporary_directory:
            workspace = Path(temporary_directory) / "workspace"
            (workspace / ".git").mkdir(parents=True)
            db.initialize_workspace(workspace)
            with mock.patch.object(sys, "argv", ["-", str(workspace)]):
                exec(compile(source, str(RELEASE_WORKFLOW), "exec"), {})

    def test_smoke_accepts_current_mcp_tools(self) -> None:
        self._run_smoke()

    def test_smoke_accepts_new_registered_tools(self) -> None:
        from taplctl.mcp_server import create_server

        def extended_server(**kwargs):
            server = create_server(**kwargs)

            @server.tool(name="tapl_future_tool")
            def future_tool() -> dict[str, bool]:
                return {"ok": True}

            return server

        with mock.patch("taplctl.mcp_server.create_server", side_effect=extended_server):
            self._run_smoke()

    def test_smoke_rejects_missing_tool_even_when_count_matches(self) -> None:
        from mcp import Client

        original_list_tools = Client.list_tools

        async def renamed_tool(client, *args, **kwargs):
            result = await original_list_tools(client, *args, **kwargs)
            for tool in result.tools:
                if tool.name == "tapl_configure_subagents":
                    tool.name = "tapl_unexpected_tool"
                    break
            return result

        with mock.patch.object(Client, "list_tools", renamed_tool):
            with self.assertRaises(BaseExceptionGroup) as raised:
                self._run_smoke()
        self.assertRegex(
            repr(raised.exception.subgroup(SystemExit)),
            "missing=.*tapl_configure_subagents.*unexpected=.*tapl_unexpected_tool",
        )


if __name__ == "__main__":
    unittest.main()
