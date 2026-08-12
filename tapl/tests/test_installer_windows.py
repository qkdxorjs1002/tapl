from __future__ import annotations

import hashlib
import http.server
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import types
import unittest
import zipfile
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = REPOSITORY_ROOT / "tapl"
INSTALLER = REPOSITORY_ROOT / "install.ps1"
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

from taplctl import updater as tapl_updater


class PowerShellInstallerStaticTests(unittest.TestCase):
    def test_prerelease_validation_and_ordering_are_powershell_51_compatible(self) -> None:
        source = INSTALLER.read_text(encoding="utf-8")

        version_pattern = (
            "^[0-9]+\\.[0-9]+\\.[0-9]+(?:(?:a|b|rc)[0-9]+)?$"
        )
        self.assertGreaterEqual(source.count(version_pattern), 2)
        self.assertIn("function Compare-SemVer {", source)
        self.assertIn("$stageRanks = @{ a = 0; b = 1; rc = 2; stable = 3 }", source)
        self.assertNotIn("[System.Management.Automation.SemanticVersion]", source)


class _FixtureHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args: object, directory: str, requests: list[str], **kwargs: object) -> None:
        self._requests = requests
        super().__init__(*args, directory=directory, **kwargs)

    def do_GET(self) -> None:  # noqa: N802 - inherited HTTP method name
        self._requests.append(self.path)
        super().do_GET()

    def log_message(self, _format: str, *args: object) -> None:
        return


@unittest.skipUnless(os.name == "nt", "PowerShell installer tests require Windows")
class PowerShellInstallerTests(unittest.TestCase):
    """Run the PowerShell installer against only local, disposable fixtures.

    The checked-in installer intentionally updates the real per-user PATH.  A
    test copy replaces only that write with a process-local equivalent and a
    log file.  The copy also contains narrow failure hooks used to exercise
    rollback branches that cannot otherwise be triggered reliably on Windows.
    """

    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary_directory.name)
        self.install_root = self.base / "install"
        self.bin_dir = self.base / "bin"
        self.home = self.base / "home"
        self.temp_dir = self.base / "tmp"
        self.fixture_dir = self.base / "fixtures"
        self.path_log = self.base / "path.log"
        for directory in (self.home, self.temp_dir, self.fixture_dir):
            directory.mkdir(parents=True)

        self.requests: list[str] = []
        handler = lambda *args, **kwargs: _FixtureHandler(  # noqa: E731
            *args,
            directory=str(self.fixture_dir),
            requests=self.requests,
            **kwargs,
        )
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.server_thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.server_thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.manifest_url = f"{self.base_url}/taplctl-install-manifest.json"

        self.powershell = shutil.which("powershell.exe") or shutil.which("pwsh.exe")
        if self.powershell is None:
            self.skipTest("PowerShell 5.1 or newer is unavailable")
        self.installer = self._write_safe_test_installer()

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.server_thread.join(timeout=5)
        self.temporary_directory.cleanup()

    def _write_safe_test_installer(self) -> Path:
        source = INSTALLER.read_text(encoding="utf-8")

        path_start = source.index("function Add-ToUserPath {")
        path_end = source.index("\n}\n\ntry {", path_start) + 2
        safe_path_function = r'''function Add-ToUserPath {
    param([Parameter(Mandatory = $true)][string]$Directory)
    if (-not (Test-PathListContains $env:Path $Directory)) {
        $env:Path = $env:Path.TrimEnd(';') + ';' + $Directory
    }
    [System.IO.File]::WriteAllText($env:TAPL_TEST_PATH_LOG, $env:Path, $Utf8NoBom)
}'''
        source = source[:path_start] + safe_path_function + source[path_end:]

        move_marker = "    if ([System.IO.File]::Exists($Destination)) {"
        move_hook = r'''    if (
        $env:TAPL_TEST_FAIL_MOVE -eq "launcher" -and
        [System.IO.Path]::GetFileName($Destination) -eq "taplctl.cmd"
    ) {
        throw "simulated launcher activation failure"
    }
    if (
        $env:TAPL_TEST_FAIL_MOVE -eq "metadata" -and
        [System.IO.Path]::GetFileName($Destination) -eq "install.json"
    ) {
        throw "simulated metadata activation failure"
    }
'''
        self.assertEqual(source.count(move_marker), 1)
        source = source.replace(move_marker, move_hook + move_marker, 1)

        python_marker = "    & $executable @allArguments | Out-Host\n"
        python_hook = r'''    if (
        $env:TAPL_TEST_FAIL_CANDIDATE -eq "venv" -and
        $Arguments.Length -ge 2 -and
        $Arguments[0] -eq "-m" -and
        $Arguments[1] -eq "venv"
    ) {
        return 91
    }
'''
        self.assertEqual(source.count(python_marker), 1)
        source = source.replace(python_marker, python_hook + python_marker, 1)

        pip_original = '''        & $candidatePython -m pip install --disable-pip-version-check --upgrade $wheelPath
        if ($LASTEXITCODE -ne 0) {
            Stop-Installer "pip could not install taplctl; the previous installation was left unchanged."
        }
'''
        pip_hook = r'''        if ($env:TAPL_TEST_FAIL_CANDIDATE -eq "pip") {
            $pipExit = 92
        }
        else {
            & $candidatePython -m pip install --disable-pip-version-check --upgrade $wheelPath
            $pipExit = $LASTEXITCODE
        }
        if ($pipExit -ne 0) {
            Stop-Installer "pip could not install taplctl; the previous installation was left unchanged."
        }
'''
        self.assertEqual(source.count(pip_original), 1)
        source = source.replace(pip_original, pip_hook, 1)

        destination = self.base / "install.test.ps1"
        destination.write_text(source, encoding="utf-8")
        return destination

    def build_wheel(self, version: str, *, reported_version: str | None = None) -> tuple[Path, str]:
        reported_version = reported_version or version
        filename = f"taplctl-{version}-py3-none-any.whl"
        wheel_path = self.fixture_dir / filename
        dist_info = f"taplctl-{version}.dist-info"
        files = {
            "taplctl/__init__.py": f'__version__ = "{version}"\n',
            "taplctl/cli.py": (
                "import sys\n\n"
                "def main():\n"
                "    if '--version' in sys.argv:\n"
                f"        print('taplctl {reported_version}')\n"
                "    return 0\n"
            ),
            f"{dist_info}/METADATA": (
                "Metadata-Version: 2.1\n"
                "Name: taplctl\n"
                f"Version: {version}\n"
            ),
            f"{dist_info}/WHEEL": (
                "Wheel-Version: 1.0\n"
                "Generator: windows-installer-test\n"
                "Root-Is-Purelib: true\n"
                "Tag: py3-none-any\n"
            ),
            f"{dist_info}/entry_points.txt": "[console_scripts]\ntaplctl = taplctl.cli:main\n",
        }
        files[f"{dist_info}/RECORD"] = "".join(f"{name},,\n" for name in files)
        with zipfile.ZipFile(wheel_path, "w", compression=zipfile.ZIP_DEFLATED) as wheel:
            for name, contents in files.items():
                wheel.writestr(name, contents)
        return wheel_path, hashlib.sha256(wheel_path.read_bytes()).hexdigest()

    def write_manifest(
        self,
        version: str,
        wheel: Path,
        sha256: str,
        *,
        payload: object | None = None,
    ) -> None:
        manifest = payload
        if manifest is None:
            manifest = {
                "schema_version": 1,
                "version": version,
                "wheel": {
                    "url": f"{self.base_url}/{wheel.name}",
                    "sha256": sha256,
                },
            }
        (self.fixture_dir / "taplctl-install-manifest.json").write_text(
            json.dumps(manifest), encoding="utf-8"
        )

    def installer_environment(self, **overrides: str) -> dict[str, str]:
        environment = os.environ.copy()
        environment.update(
            {
                "HOME": str(self.home),
                "USERPROFILE": str(self.home),
                "LOCALAPPDATA": str(self.home / "AppData" / "Local"),
                "TEMP": str(self.temp_dir),
                "TMP": str(self.temp_dir),
                "TAPL_INSTALL_ROOT": str(self.install_root),
                "TAPL_BIN_DIR": str(self.bin_dir),
                "TAPL_INSTALL_MANIFEST_URL": self.manifest_url,
                "TAPL_TEST_PATH_LOG": str(self.path_log),
                "TAPL_TEST_FAIL_MOVE": "",
                "TAPL_TEST_FAIL_CANDIDATE": "",
            }
        )
        environment.update(overrides)
        return environment

    def run_installer(self, **environment_overrides: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                self.powershell,
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(self.installer),
            ],
            text=True,
            capture_output=True,
            check=False,
            env=self.installer_environment(**environment_overrides),
            timeout=120,
        )

    def install_release(
        self,
        version: str,
        *,
        reported_version: str | None = None,
        **environment_overrides: str,
    ) -> subprocess.CompletedProcess[str]:
        wheel, sha256 = self.build_wheel(version, reported_version=reported_version)
        self.write_manifest(version, wheel, sha256)
        return self.run_installer(**environment_overrides)

    @property
    def metadata_path(self) -> Path:
        return self.install_root / "install.json"

    @property
    def launcher_path(self) -> Path:
        return self.bin_dir / "taplctl.cmd"

    def installed_metadata(self) -> dict[str, object]:
        return json.loads(self.metadata_path.read_text(encoding="utf-8"))

    def assert_active_release(self, version: str) -> dict[str, object]:
        metadata = self.installed_metadata()
        venv = Path(str(metadata["venv"]))
        command = venv / "Scripts" / "taplctl.exe"
        self.assertEqual(metadata["schema_version"], 1)
        self.assertEqual(metadata["method"], "powershell")
        self.assertEqual(metadata["version"], version)
        self.assertEqual(metadata["install_root"], str(self.install_root.resolve()))
        self.assertEqual(metadata["bin_dir"], str(self.bin_dir.resolve()))
        self.assertEqual(metadata["executable"], str(self.launcher_path.resolve()))
        self.assertTrue(command.is_file())
        expected_launcher = tapl_updater._windows_launcher_bytes(command)
        self.assertEqual(self.launcher_path.read_bytes(), expected_launcher)
        version_result = subprocess.run(
            [str(command), "--version"], text=True, capture_output=True, check=False
        )
        self.assertEqual(version_result.returncode, 0, version_result.stderr)
        self.assertEqual(version_result.stdout.strip(), f"taplctl {version}")
        path_entries = self.path_log.read_text(encoding="utf-8").split(os.pathsep)
        matching_path_entry = False
        for raw_entry in path_entries:
            entry = raw_entry.strip().strip('"')
            if not entry:
                continue
            try:
                if os.path.samefile(entry, self.bin_dir):
                    matching_path_entry = True
                    break
            except OSError:
                continue
        self.assertTrue(
            matching_path_entry,
            f"{self.bin_dir} was not found in PATH entries: {path_entries!r}",
        )
        return metadata

    def install_initial_release(self, version: str = "1.0.0") -> dict[str, object]:
        result = self.install_release(version)
        self.assertEqual(result.returncode, 0, result.stderr)
        return self.assert_active_release(version)

    def preserved_state(self) -> tuple[bytes, bytes, tuple[str, ...]]:
        return (
            self.metadata_path.read_bytes(),
            self.launcher_path.read_bytes(),
            tuple(sorted(path.name for path in (self.install_root / "versions").iterdir())),
        )

    def assert_preserved(self, state: tuple[bytes, bytes, tuple[str, ...]]) -> None:
        self.assertEqual(self.metadata_path.read_bytes(), state[0])
        self.assertEqual(self.launcher_path.read_bytes(), state[1])
        self.assertEqual(
            tuple(sorted(path.name for path in (self.install_root / "versions").iterdir())),
            state[2],
        )

    def test_first_install_creates_canonical_launcher_metadata_and_process_path(self) -> None:
        result = self.install_release("1.0.0")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("taplctl 1.0.0 is installed", result.stdout)
        self.assertIn("Workflow hooks were not installed automatically", result.stdout)
        metadata = self.assert_active_release("1.0.0")
        self.assertEqual(metadata["manifest_url"], self.manifest_url)
        self.assertEqual(self.requests, ["/taplctl-install-manifest.json", "/taplctl-1.0.0-py3-none-any.whl"])

    def test_repeated_same_version_reuses_the_existing_environment(self) -> None:
        original = self.install_initial_release()
        state = self.preserved_state()
        self.requests.clear()

        repeated = self.run_installer()

        self.assertEqual(repeated.returncode, 0, repeated.stderr)
        self.assertIn("version 1.0.0 is already installed", repeated.stdout)
        self.assertEqual(self.requests, ["/taplctl-install-manifest.json"])
        self.assertEqual(self.installed_metadata()["venv"], original["venv"])
        self.assertEqual(self.preserved_state()[1:], state[1:])
        self.assert_active_release("1.0.0")

    def test_newer_release_upgrades_and_older_release_is_a_noop(self) -> None:
        old = self.install_initial_release("1.0.0")

        upgraded = self.install_release("1.1.0")
        self.assertEqual(upgraded.returncode, 0, upgraded.stderr)
        new = self.assert_active_release("1.1.0")
        self.assertNotEqual(new["venv"], old["venv"])
        self.assertTrue(Path(str(old["venv"])).is_dir())

        state = self.preserved_state()
        self.requests.clear()
        wheel, sha256 = self.build_wheel("1.0.0")
        self.write_manifest("1.0.0", wheel, sha256)
        downgrade = self.run_installer()

        self.assertEqual(downgrade.returncode, 0, downgrade.stderr)
        self.assertIn("is newer than published release 1.0.0", downgrade.stdout)
        self.assertEqual(self.requests, ["/taplctl-install-manifest.json"])
        self.assert_preserved(state)

    def test_prerelease_versions_upgrade_in_python_order_without_downgrade(self) -> None:
        self.install_initial_release("1.9.9")

        for version in ("2.0.0b1", "2.0.0b2", "2.0.0rc1", "2.0.0"):
            with self.subTest(version=version):
                updated = self.install_release(version)
                self.assertEqual(updated.returncode, 0, updated.stderr)
                self.assert_active_release(version)

        state = self.preserved_state()
        self.requests.clear()
        wheel, sha256 = self.build_wheel("2.0.0rc2")
        self.write_manifest("2.0.0rc2", wheel, sha256)
        downgrade = self.run_installer()

        self.assertEqual(downgrade.returncode, 0, downgrade.stderr)
        self.assertIn("is newer than published release 2.0.0rc2", downgrade.stdout)
        self.assertEqual(self.requests, ["/taplctl-install-manifest.json"])
        self.assert_preserved(state)

    def test_manifest_rejects_noncanonical_prerelease_versions(self) -> None:
        self.install_initial_release()
        state = self.preserved_state()
        wheel, sha256 = self.build_wheel("2.0.0b1")
        for version in (
            "2.0.0-beta1",
            "2.0.0beta1",
            "2.0.0b",
            "2.0.0rc",
            "2.0.0RC1",
            "v2.0.0b1",
            "2.0.0.post1",
        ):
            with self.subTest(version=version):
                self.write_manifest(version, wheel, sha256)
                failed = self.run_installer()
                self.assertNotEqual(failed.returncode, 0)
                self.assertIn("release manifest validation failed", failed.stderr)
                self.assert_preserved(state)

    def test_invalid_manifest_and_checksum_preserve_an_existing_installation(self) -> None:
        self.install_initial_release()
        state = self.preserved_state()

        wheel, _sha256 = self.build_wheel("1.1.0")
        cases = (
            ("manifest", {"schema_version": 2}, "release manifest validation failed"),
            (
                "checksum",
                {
                    "schema_version": 1,
                    "version": "1.1.0",
                    "wheel": {"url": f"{self.base_url}/{wheel.name}", "sha256": "0" * 64},
                },
                "wheel SHA-256 mismatch",
            ),
        )
        for name, payload, message in cases:
            with self.subTest(case=name):
                self.write_manifest("1.1.0", wheel, "0" * 64, payload=payload)
                failed = self.run_installer()
                self.assertNotEqual(failed.returncode, 0)
                self.assertIn(message, failed.stderr)
                self.assert_preserved(state)

    def test_unmanaged_launcher_is_rejected_before_any_download(self) -> None:
        self.bin_dir.mkdir(parents=True)
        self.launcher_path.write_text("@echo unmanaged\r\n", encoding="utf-8")

        failed = self.run_installer()

        self.assertNotEqual(failed.returncode, 0)
        self.assertIn("already exists and is not managed", failed.stderr)
        self.assertEqual(self.requests, [])

    def test_invalid_metadata_is_rejected_before_any_download(self) -> None:
        self.install_root.mkdir(parents=True)
        self.metadata_path.write_text('{"schema_version": 9}\n', encoding="utf-8")

        failed = self.run_installer()

        self.assertNotEqual(failed.returncode, 0)
        self.assertIn("refusing to overwrite it", failed.stderr)
        self.assertEqual(self.requests, [])

    def test_managed_command_version_mismatch_is_rejected_before_download(self) -> None:
        self.install_initial_release()
        metadata = self.installed_metadata()
        metadata["version"] = "9.9.9"
        self.metadata_path.write_text(json.dumps(metadata) + "\n", encoding="utf-8")
        state = self.preserved_state()
        self.requests.clear()

        failed = self.run_installer()

        self.assertNotEqual(failed.returncode, 0)
        self.assertIn("command version does not match install.json", failed.stderr)
        self.assertEqual(self.requests, [])
        self.assert_preserved(state)

    def test_candidate_venv_pip_and_validation_failures_preserve_the_active_release(self) -> None:
        self.install_initial_release()
        state = self.preserved_state()
        cases = (
            ("venv", None, "could not create a virtual environment"),
            ("pip", None, "pip could not install taplctl"),
            ("", "9.9.9", "executable failed validation"),
        )
        for failure, reported_version, message in cases:
            with self.subTest(failure=failure or "validation"):
                wheel, sha256 = self.build_wheel("1.1.0", reported_version=reported_version)
                self.write_manifest("1.1.0", wheel, sha256)
                failed = self.run_installer(TAPL_TEST_FAIL_CANDIDATE=failure)
                self.assertNotEqual(failed.returncode, 0)
                self.assertIn(message, failed.stderr)
                self.assert_preserved(state)

    def test_launcher_and_metadata_activation_failures_preserve_the_active_release(self) -> None:
        self.install_initial_release()
        state = self.preserved_state()
        cases = (
            ("launcher", "could not activate the taplctl command launcher"),
            ("metadata", "previous command launcher was restored"),
        )
        for failure, message in cases:
            with self.subTest(failure=failure):
                wheel, sha256 = self.build_wheel("1.1.0")
                self.write_manifest("1.1.0", wheel, sha256)
                failed = self.run_installer(TAPL_TEST_FAIL_MOVE=failure)
                self.assertNotEqual(failed.returncode, 0)
                self.assertIn(message, failed.stderr)
                self.assert_preserved(state)


class WindowsSelfUpdateContractTests(unittest.TestCase):
    """Exercise the PowerShell metadata/launcher branch on every platform."""

    manifest_url = "https://fixtures.invalid/taplctl-install-manifest.json"
    wheel_url = "https://fixtures.invalid/taplctl-1.1.0-py3-none-any.whl"

    def create_fixture(self, base: Path) -> dict[str, Path]:
        install_root = base / "install"
        versions_dir = install_root / "versions"
        venv = versions_dir / "1.0.0-fixture"
        scripts = venv / "Scripts"
        bin_dir = base / "bin"
        scripts.mkdir(parents=True)
        bin_dir.mkdir()
        python = scripts / "python.exe"
        command = scripts / "taplctl.exe"
        python.write_bytes(b"fixture python")
        command.write_bytes(b"fixture command")
        executable = bin_dir / "taplctl.cmd"
        executable.write_bytes(tapl_updater._windows_launcher_bytes(command))
        metadata_path = install_root / "install.json"
        metadata = {
            "schema_version": 1,
            "method": "powershell",
            "manifest_url": self.manifest_url,
            "version": "1.0.0",
            "wheel_url": "https://fixtures.invalid/taplctl-1.0.0-py3-none-any.whl",
            "wheel_sha256": "1" * 64,
            "install_root": str(install_root),
            "bin_dir": str(bin_dir),
            "venv": str(venv),
            "executable": str(executable),
            "installed_at": "2026-01-01T00:00:00Z",
        }
        metadata_path.write_text(json.dumps(metadata) + "\n", encoding="utf-8")
        return {
            "install_root": install_root,
            "versions_dir": versions_dir,
            "venv": venv,
            "python": python,
            "command": command,
            "executable": executable,
            "metadata_path": metadata_path,
        }

    def manifest(self, wheel: bytes) -> bytes:
        return json.dumps(
            {
                "schema_version": 1,
                "version": "1.1.0",
                "wheel": {
                    "url": self.wheel_url,
                    "sha256": hashlib.sha256(wheel).hexdigest(),
                },
            }
        ).encode()

    def opener(self, responses: dict[str, bytes]):
        def open_fixture(url: str) -> bytes:
            return responses[url]

        return open_fixture

    def test_check_and_update_honor_the_powershell_installation_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = self.create_fixture(Path(tmp))
            wheel = b"fixture release wheel"
            responses = {self.manifest_url: self.manifest(wheel), self.wheel_url: wheel}
            kwargs = {
                "metadata_path": fixture["metadata_path"],
                "current_prefix": fixture["venv"],
                "current_python": fixture["python"],
                "opener": self.opener(responses),
            }

            checked = tapl_updater.check_for_update(**kwargs)

            self.assertEqual(checked["status"], "update-available")
            self.assertTrue(checked["update_available"])
            self.assertEqual(checked["executable"], str(fixture["executable"]))

            def runner(args: list[str], **_kwargs: object) -> types.SimpleNamespace:
                if args[1:3] == ["-m", "venv"]:
                    candidate = Path(args[3])
                    scripts = candidate / "Scripts"
                    scripts.mkdir(parents=True, exist_ok=True)
                    (scripts / "python.exe").write_bytes(b"candidate python")
                    (scripts / "taplctl.exe").write_bytes(b"candidate command")
                    return types.SimpleNamespace(returncode=0, stdout="", stderr="")
                if args[1:3] == ["-m", "pip"]:
                    return types.SimpleNamespace(returncode=0, stdout="", stderr="")
                return types.SimpleNamespace(returncode=0, stdout="taplctl 1.1.0\n", stderr="")

            updated = tapl_updater.update_installation(**kwargs, runner=runner)

            self.assertEqual(updated["status"], "updated")
            self.assertEqual(updated["previous_version"], "1.0.0")
            self.assertEqual(updated["current_version"], "1.1.0")
            metadata = json.loads(fixture["metadata_path"].read_text(encoding="utf-8"))
            candidate = Path(metadata["venv"])
            self.assertEqual(metadata["method"], "powershell")
            self.assertEqual(metadata["version"], "1.1.0")
            self.assertEqual(
                fixture["executable"].read_bytes(),
                tapl_updater._windows_launcher_bytes(candidate / "Scripts" / "taplctl.exe"),
            )
            self.assertTrue(fixture["venv"].is_dir(), "the previous environment must be retained")

    def test_check_rejects_noncanonical_windows_launcher_bytes_before_download(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = self.create_fixture(Path(tmp))
            canonical = fixture["executable"].read_bytes()
            invalid_launchers = {
                "lf-only": canonical.replace(b"\r\n", b"\n"),
                "utf8-bom": b"\xef\xbb\xbf" + canonical,
            }

            for name, launcher in invalid_launchers.items():
                with self.subTest(case=name):
                    fixture["executable"].write_bytes(launcher)

                    def fail_if_opened(_url: str) -> bytes:
                        self.fail("invalid launcher ownership must be rejected before download")

                    with self.assertRaises(tapl_updater.UpdateError) as rejected:
                        tapl_updater.check_for_update(
                            metadata_path=fixture["metadata_path"],
                            current_prefix=fixture["venv"],
                            current_python=fixture["python"],
                            opener=fail_if_opened,
                        )

                    self.assertEqual(rejected.exception.code, "unsupported_installation")
                    fixture["executable"].write_bytes(canonical)


if __name__ == "__main__":
    unittest.main()
