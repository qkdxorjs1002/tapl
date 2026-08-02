from __future__ import annotations

import hashlib
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
INSTALLER = REPOSITORY_ROOT / "install.sh"
MANIFEST_URL = "https://fixtures.invalid/taplctl-install-manifest.json"


class CurlShInstallerTests(unittest.TestCase):
    """End-to-end contracts for the Linux ``curl | sh`` installer.

    The tests run the checked-in shell script with a Linux ``uname`` and a
    fixture-backed ``curl``.  Every install location, download, and command
    shim belongs to the per-test temporary directory, so they do not need
    network access or affect the developer's local installation.
    """

    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary_directory.name)
        self.install_root = self.base / "data" / "tapl"
        self.bin_dir = self.base / "bin"
        self.home = self.base / "home"
        self.fixture_dir = self.base / "fixtures"
        self.stub_dir = self.base / "stubs"
        self.manifest_path = self.fixture_dir / "taplctl-install-manifest.json"
        self.fixture_dir.mkdir()
        self.stub_dir.mkdir()
        self._write_command_stubs()

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def _write_command_stubs(self) -> None:
        real_cp = shlex.quote(shutil.which("cp") or "/bin/cp")
        real_mv = shlex.quote(shutil.which("mv") or "/bin/mv")

        self._write_executable(
            "uname",
            "#!/bin/sh\nprintf '%s\\n' Linux\n",
        )
        self._write_executable(
            "curl",
            f"""#!/bin/sh
output=
url=
while [ "$#" -gt 0 ]; do
    case "$1" in
        --output)
            output=$2
            shift 2
            ;;
        *)
            url=$1
            shift
            ;;
    esac
done

if [ -z "$output" ]; then
    echo 'fixture curl requires --output' >&2
    exit 2
fi
if [ -n "${{TAPL_TEST_CURL_LOG:-}}" ]; then
    printf '%s\n' "$url" >> "$TAPL_TEST_CURL_LOG"
fi
if [ "$url" = "$TAPL_TEST_MANIFEST_URL" ]; then
    exec {real_cp} "$TAPL_TEST_MANIFEST_PATH" "$output"
fi

wheel_name=${{url##*/}}
if [ -f "$TAPL_TEST_WHEEL_DIR/$wheel_name" ]; then
    exec {real_cp} "$TAPL_TEST_WHEEL_DIR/$wheel_name" "$output"
fi
echo "unexpected fixture URL: $url" >&2
exit 22
""",
        )
        self._write_executable(
            "mv",
            f"""#!/bin/sh
destination=
for argument in "$@"; do
    destination=$argument
done
if [ "${{TAPL_TEST_FAIL_METADATA_MV:-0}}" = 1 ] && \
    [ "$destination" = "${{TAPL_TEST_INSTALL_JSON:-}}" ]; then
    echo 'simulated install metadata activation failure' >&2
    exit 41
fi
exec {real_mv} "$@"
""",
        )
        self._write_executable(
            "python3",
            """#!/bin/sh
if [ "${TAPL_TEST_FAIL_VENV:-0}" = 1 ] && [ "${1:-}" = "-m" ] && \
    [ "${2:-}" = "venv" ]; then
    echo 'simulated venv creation failure' >&2
    exit 42
fi

if [ "${1:-}" = "-m" ] && [ "${2:-}" = "venv" ]; then
    "$TAPL_TEST_REAL_PYTHON" "$@"
    status=$?
    if [ "$status" -eq 0 ] && [ "${TAPL_TEST_FAIL_PIP:-0}" = 1 ]; then
        venv_path=
        for argument in "$@"; do
            venv_path=$argument
        done
        mv "$venv_path/bin/python" "$venv_path/bin/.tapl-real-python"
        cat > "$venv_path/bin/python" <<'PYTHON_WRAPPER'
#!/bin/sh
if [ "${1:-}" = "-m" ] && [ "${2:-}" = "pip" ]; then
    echo 'simulated pip installation failure' >&2
    exit 43
fi
exec "$(dirname "$0")/.tapl-real-python" "$@"
PYTHON_WRAPPER
        chmod 755 "$venv_path/bin/python"
    fi
    exit "$status"
fi

exec "$TAPL_TEST_REAL_PYTHON" "$@"
""",
        )

    def _write_executable(self, name: str, contents: str) -> Path:
        path = self.stub_dir / name
        path.write_text(contents, encoding="utf-8")
        path.chmod(0o755)
        return path

    def build_wheel(self, version: str) -> tuple[Path, str]:
        """Build a deliberately tiny valid pure-Python wheel without tooling."""

        filename = f"taplctl-{version}-py3-none-any.whl"
        wheel_path = self.fixture_dir / filename
        dist_info = f"taplctl-{version}.dist-info"
        files = {
            "taplctl/__init__.py": f'__version__ = "{version}"\n',
            "taplctl/cli.py": (
                "import sys\n\n"
                "def main():\n"
                "    if '--version' in sys.argv:\n"
                f"        print('taplctl {version}')\n"
                "        return 0\n"
                "    return 0\n"
            ),
            f"{dist_info}/METADATA": (
                "Metadata-Version: 2.1\n"
                "Name: taplctl\n"
                f"Version: {version}\n"
            ),
            f"{dist_info}/WHEEL": (
                "Wheel-Version: 1.0\n"
                "Generator: installer-test\n"
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

    def write_manifest(self, version: str, wheel: Path, sha256: str) -> None:
        payload = {
            "schema_version": 1,
            "version": version,
            "wheel": {
                "url": f"https://fixtures.invalid/{wheel.name}",
                "sha256": sha256,
            },
        }
        self.manifest_path.write_text(json.dumps(payload), encoding="utf-8")

    def installer_environment(self, **overrides: str) -> dict[str, str]:
        environment = os.environ.copy()
        environment.update(
            {
                "PATH": str(self.stub_dir) + os.pathsep + environment.get("PATH", ""),
                "HOME": str(self.home),
                "TAPL_INSTALL_ROOT": str(self.install_root),
                "TAPL_BIN_DIR": str(self.bin_dir),
                "TAPL_INSTALL_MANIFEST_URL": MANIFEST_URL,
                "TAPL_TEST_MANIFEST_URL": MANIFEST_URL,
                "TAPL_TEST_MANIFEST_PATH": str(self.manifest_path),
                "TAPL_TEST_WHEEL_DIR": str(self.fixture_dir),
                "TAPL_TEST_REAL_PYTHON": sys.executable,
                "TAPL_TEST_INSTALL_JSON": str(self.install_root / "install.json"),
                "TAPL_TEST_CURL_LOG": str(self.base / "curl.log"),
            }
        )
        environment.update(overrides)
        return environment

    def run_installer(self, **environment_overrides: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["sh", str(INSTALLER)],
            text=True,
            capture_output=True,
            check=False,
            env=self.installer_environment(**environment_overrides),
        )

    def install_release(self, version: str, **environment_overrides: str) -> subprocess.CompletedProcess[str]:
        wheel, sha256 = self.build_wheel(version)
        self.write_manifest(version, wheel, sha256)
        return self.run_installer(**environment_overrides)

    def installed_metadata(self) -> dict[str, object]:
        return json.loads((self.install_root / "install.json").read_text(encoding="utf-8"))

    def assert_active_release(self, version: str) -> dict[str, object]:
        metadata = self.installed_metadata()
        link_path = self.bin_dir / "taplctl"
        self.assertTrue(link_path.is_symlink())
        self.assertEqual(
            link_path.resolve(),
            (Path(str(metadata["venv"])) / "bin" / "taplctl").resolve(),
        )
        self.assertEqual(metadata["version"], version)
        executable = subprocess.run(
            [str(link_path), "--version"], text=True, capture_output=True, check=False
        )
        self.assertEqual(executable.returncode, 0, executable.stderr)
        self.assertEqual(executable.stdout.strip(), f"taplctl {version}")
        return metadata

    def install_initial_release(self, version: str = "1.0.0") -> dict[str, object]:
        installed = self.install_release(version)
        self.assertEqual(installed.returncode, 0, installed.stderr)
        return self.assert_active_release(version)

    def assert_existing_installation_is_preserved(
        self, metadata_text: str, link_target: str
    ) -> None:
        self.assertEqual((self.install_root / "install.json").read_text(encoding="utf-8"), metadata_text)
        self.assertEqual(os.readlink(self.bin_dir / "taplctl"), link_target)

    def assert_url_secrets_are_redacted(
        self,
        result: subprocess.CompletedProcess[str],
        sensitive_values: tuple[str, ...],
    ) -> None:
        combined_output = result.stdout + result.stderr
        for sensitive_value in sensitive_values:
            self.assertFalse(
                sensitive_value in combined_output,
                "installer output leaked a sensitive URL component",
            )

    def test_shell_syntax_is_valid(self) -> None:
        result = subprocess.run(
            ["sh", "-n", str(INSTALLER)], text=True, capture_output=True, check=False
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_first_install_and_repeated_manifest_install_are_safe(self) -> None:
        metadata = self.install_initial_release()
        link_path = self.bin_dir / "taplctl"
        original_venv = metadata["venv"]
        original_link = os.readlink(link_path)
        original_versions = sorted(path.name for path in (self.install_root / "versions").iterdir())

        repeated = self.run_installer()

        self.assertEqual(repeated.returncode, 0, repeated.stderr)
        self.assertIn("version 1.0.0 is already installed", repeated.stdout)
        self.assertIn(f'export PATH="{self.bin_dir}:$PATH"', repeated.stdout)
        self.assertIn("Workflow hooks were not installed automatically", repeated.stdout)
        self.assertFalse((self.home / ".codex").exists())
        repeated_metadata = self.assert_active_release("1.0.0")
        self.assertEqual(repeated_metadata["venv"], original_venv)
        self.assertEqual(os.readlink(link_path), original_link)
        self.assertEqual(
            sorted(path.name for path in (self.install_root / "versions").iterdir()), original_versions
        )

    def test_new_manifest_version_updates_the_active_release(self) -> None:
        old_metadata = self.install_initial_release("1.0.0")

        updated = self.install_release("1.1.0")

        self.assertEqual(updated.returncode, 0, updated.stderr)
        self.assertIn("taplctl 1.1.0 is installed", updated.stdout)
        new_metadata = self.assert_active_release("1.1.0")
        self.assertNotEqual(new_metadata["venv"], old_metadata["venv"])
        self.assertTrue(Path(str(old_metadata["venv"])).is_dir())

    def test_older_manifest_is_a_noop_when_managed_install_is_newer(self) -> None:
        self.install_initial_release("1.1.0")
        metadata_path = self.install_root / "install.json"
        preserved_metadata = metadata_path.read_text(encoding="utf-8")
        preserved_link = os.readlink(self.bin_dir / "taplctl")
        preserved_versions = sorted(
            path.name for path in (self.install_root / "versions").iterdir()
        )
        old_wheel, old_sha256 = self.build_wheel("1.0.0")
        self.write_manifest("1.0.0", old_wheel, old_sha256)
        curl_log = self.base / "curl.log"
        curl_log.unlink()

        downgrade = self.run_installer()

        self.assertEqual(downgrade.returncode, 0, downgrade.stderr)
        self.assertIn(
            "installed taplctl 1.1.0 is newer than published release 1.0.0",
            downgrade.stdout,
        )
        self.assertEqual(curl_log.read_text(encoding="utf-8").splitlines(), [MANIFEST_URL])
        self.assert_existing_installation_is_preserved(preserved_metadata, preserved_link)
        self.assertEqual(
            sorted(path.name for path in (self.install_root / "versions").iterdir()),
            preserved_versions,
        )
        self.assert_active_release("1.1.0")

    def test_older_manifest_fails_when_managed_command_version_disagrees(self) -> None:
        metadata = self.install_initial_release("1.1.0")
        metadata_path = self.install_root / "install.json"
        preserved_metadata = metadata_path.read_text(encoding="utf-8")
        preserved_link = os.readlink(self.bin_dir / "taplctl")
        managed_command = Path(str(metadata["venv"])) / "bin" / "taplctl"
        managed_command.write_text("#!/bin/sh\nprintf 'taplctl 9.9.9\\n'\n", encoding="utf-8")
        managed_command.chmod(0o755)
        old_wheel, old_sha256 = self.build_wheel("1.0.0")
        self.write_manifest("1.0.0", old_wheel, old_sha256)
        curl_log = self.base / "curl.log"
        curl_log.unlink()

        downgrade = self.run_installer()

        self.assertNotEqual(downgrade.returncode, 0)
        self.assertIn("managed taplctl command version does not match install.json", downgrade.stderr)
        self.assertEqual(curl_log.read_text(encoding="utf-8").splitlines(), [MANIFEST_URL])
        self.assert_existing_installation_is_preserved(preserved_metadata, preserved_link)

    def test_checksum_venv_and_pip_failures_leave_an_existing_release_untouched(self) -> None:
        self.install_initial_release()
        metadata_path = self.install_root / "install.json"
        preserved_metadata = metadata_path.read_text(encoding="utf-8")
        preserved_link = os.readlink(self.bin_dir / "taplctl")

        bad_wheel, _ = self.build_wheel("1.1.0")
        self.write_manifest("1.1.0", bad_wheel, "0" * 64)
        checksum_failure = self.run_installer()
        self.assertNotEqual(checksum_failure.returncode, 0)
        self.assertIn("wheel SHA-256 mismatch", checksum_failure.stderr)
        self.assert_existing_installation_is_preserved(preserved_metadata, preserved_link)

        venv_failure = self.install_release("1.2.0", TAPL_TEST_FAIL_VENV="1")
        self.assertNotEqual(venv_failure.returncode, 0)
        self.assertIn("could not create a virtual environment", venv_failure.stderr)
        self.assert_existing_installation_is_preserved(preserved_metadata, preserved_link)

        pip_failure = self.install_release("1.3.0", TAPL_TEST_FAIL_PIP="1")
        self.assertNotEqual(pip_failure.returncode, 0)
        self.assertIn("pip could not install taplctl", pip_failure.stderr)
        self.assert_existing_installation_is_preserved(preserved_metadata, preserved_link)

    def test_unmanaged_command_collision_is_refused_without_overwrite(self) -> None:
        self.bin_dir.mkdir(parents=True)
        command = self.bin_dir / "taplctl"
        command.write_text("user-managed command\n", encoding="utf-8")
        wheel, sha256 = self.build_wheel("1.0.0")
        self.write_manifest("1.0.0", wheel, sha256)

        result = self.run_installer()

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("already exists and is not managed", result.stderr)
        self.assertEqual(command.read_text(encoding="utf-8"), "user-managed command\n")
        self.assertFalse((self.install_root / "install.json").exists())

    def assert_invalid_install_metadata_is_preserved_without_manifest_fetch(
        self, metadata_text: str
    ) -> None:
        self.install_root.mkdir(parents=True)
        metadata_path = self.install_root / "install.json"
        metadata_path.write_text(metadata_text, encoding="utf-8")

        result = self.run_installer()

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("is not valid schema 1 curl-sh install metadata", result.stderr)
        self.assertEqual(metadata_path.read_text(encoding="utf-8"), metadata_text)
        self.assertFalse((self.bin_dir / "taplctl").exists())
        self.assertFalse(self.manifest_path.exists())
        self.assertFalse((self.base / "curl.log").exists())

    def test_invalid_json_metadata_without_command_is_refused_before_download(self) -> None:
        self.assert_invalid_install_metadata_is_preserved_without_manifest_fetch(
            "{ definitely not valid JSON\n"
        )

    def test_non_curl_metadata_without_command_is_refused_before_download(self) -> None:
        metadata_text = json.dumps(
            {"schema_version": 1, "method": "homebrew", "version": "9.9.9"}
        ) + "\n"
        self.assert_invalid_install_metadata_is_preserved_without_manifest_fetch(metadata_text)

    def test_manifest_download_failure_redacts_url_secrets(self) -> None:
        manifest_url = (
            "https://manifest-user:manifest-password@fixtures.invalid/manifest.json"
            "?access_token=manifest-token#manifest-fragment"
        )

        result = self.run_installer(TAPL_INSTALL_MANIFEST_URL=manifest_url)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("could not download the release manifest", result.stderr)
        self.assertTrue(
            manifest_url in (self.base / "curl.log").read_text(encoding="utf-8"),
            "fixture curl did not receive the sensitive manifest URL",
        )
        self.assert_url_secrets_are_redacted(
            result,
            (
                manifest_url,
                "manifest-user",
                "manifest-password",
                "manifest-token",
                "manifest-fragment",
            ),
        )

    def test_wheel_download_failure_redacts_url_secrets(self) -> None:
        wheel_url = (
            "https://wheel-user:wheel-password@fixtures.invalid/"
            "taplctl-1.0.0-py3-none-any.whl?access_token=wheel-token#wheel-fragment"
        )
        self.manifest_path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "version": "1.0.0",
                    "wheel": {"url": wheel_url, "sha256": "a" * 64},
                }
            ),
            encoding="utf-8",
        )

        result = self.run_installer()

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("could not download the taplctl wheel", result.stderr)
        self.assertTrue(
            wheel_url in (self.base / "curl.log").read_text(encoding="utf-8"),
            "fixture curl did not receive the sensitive wheel URL",
        )
        self.assert_url_secrets_are_redacted(
            result,
            (
                wheel_url,
                "wheel-user",
                "wheel-password",
                "wheel-token",
                "wheel-fragment",
            ),
        )

    def test_metadata_activation_failure_rolls_back_the_command_link(self) -> None:
        self.install_initial_release("1.0.0")
        metadata_path = self.install_root / "install.json"
        preserved_metadata = metadata_path.read_text(encoding="utf-8")
        preserved_link = os.readlink(self.bin_dir / "taplctl")

        failed_update = self.install_release("1.1.0", TAPL_TEST_FAIL_METADATA_MV="1")

        self.assertNotEqual(failed_update.returncode, 0)
        self.assertIn("install metadata could not be activated", failed_update.stderr)
        self.assert_existing_installation_is_preserved(preserved_metadata, preserved_link)
        self.assert_active_release("1.0.0")


if __name__ == "__main__":
    unittest.main()
