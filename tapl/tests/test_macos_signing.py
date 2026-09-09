from __future__ import annotations

import base64
import csv
import hashlib
import importlib.util
import io
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock
import zipfile

from wheel.wheelfile import WheelFile


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / ".github/scripts/sign_macos_wheels.py"
WRAPPER = ROOT / ".github/scripts/sign_macos_runtime.sh"
spec = importlib.util.spec_from_file_location("sign_macos_wheels", SCRIPT)
signing = importlib.util.module_from_spec(spec)
spec.loader.exec_module(signing)
TEAM = "ABCDE12345"
IDENTITY = "A" * 40
NATIVE = bytes.fromhex("cffaedfe") + b"native fixture"
SIGNATURE = b"Developer ID fixture signature"
DETAILS = f"Authority=Developer ID Application: Fixture ({TEAM})\nTeamIdentifier={TEAM}\nTimestamp=fixture\nflags=0x10000(runtime)\n"


class MacosWheelSigningTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.wheelhouse = Path(self.temporary.name)
        self.real_run = subprocess.run
        self.signed_paths = []
        self.fail_signing = False
        self.details = DETAILS

    def make_wheel(self, name="native", payload=None, signatures=False):
        native = payload is not None
        tag = "cp312-cp312-macosx_11_0_arm64" if native else "py3-none-any"
        wheel = self.wheelhouse / f"{name}-1.0-{tag}.whl"
        info = f"{name}-1.0.dist-info"
        with WheelFile(wheel, "w") as archive:
            archive.writestr(f"{name}/__init__.py", b"# fixture\n")
            if native:
                archive.writestr(f"{name}/extension.so", payload)
                archive.writestr(f"{name}/helper", bytes.fromhex("cafebabe") + b"universal fixture")
                archive.writestr(f"{name}/text.so", b"not native code")
            archive.writestr(f"{info}/METADATA", f"Metadata-Version: 2.1\nName: {name}\nVersion: 1.0\n")
            archive.writestr(f"{info}/WHEEL", f"Wheel-Version: 1.0\nRoot-Is-Purelib: {str(not native).lower()}\nTag: {tag}\n")
            if signatures:
                archive.writestr(f"{info}/RECORD.jws", b"old jws")
                archive.writestr(f"{info}/RECORD.p7s", b"old p7s")
        return wheel

    def run_command(self, command, **kwargs):
        if command[0] == "security":
            return subprocess.CompletedProcess(command, 0, f'  1) {IDENTITY} "Developer ID Application: Fixture ({TEAM})"\n', "")
        if command[0] != "codesign":
            return self.real_run(command, **kwargs)
        path = Path(command[-1])
        if "--sign" in command:
            if self.fail_signing:
                raise subprocess.CalledProcessError(1, command)
            self.assertIn("--timestamp", command)
            self.assertIn("runtime", command)
            self.assertIn(IDENTITY, command)
            path.write_bytes(path.read_bytes() + SIGNATURE)
            self.signed_paths.append(path.name)
        elif "--verify" in command:
            self.assertIn("--strict", command)
            self.assertIn("--all-architectures", command)
            self.assertTrue(path.read_bytes().endswith(SIGNATURE))
        else:
            return subprocess.CompletedProcess(command, 0, "", self.details)
        return subprocess.CompletedProcess(command, 0, "", "")

    def sign(self):
        with mock.patch.object(signing.subprocess, "run", side_effect=self.run_command):
            return signing.sign_wheelhouse(self.wheelhouse, "temporary.keychain-db", TEAM)

    def test_native_signatures_survive_repacking_and_record_matches_final_bytes(self):
        native = self.make_wheel(payload=NATIVE, signatures=True)
        pure = self.make_wheel("pure")
        pure_before = pure.read_bytes()
        self.assertEqual(self.sign(), 2)
        self.assertEqual(self.signed_paths, ["extension.so", "helper"])
        self.assertEqual(pure.read_bytes(), pure_before)
        with WheelFile(native) as archive:
            for name in archive.namelist():
                archive.read(name)  # WheelFile verifies each RECORD hash.
            self.assertNotIn("native-1.0.dist-info/RECORD.jws", archive.namelist())
            self.assertNotIn("native-1.0.dist-info/RECORD.p7s", archive.namelist())
            data = archive.read("native/extension.so")
            rows = list(csv.reader(io.StringIO(archive.read("native-1.0.dist-info/RECORD").decode())))
        digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()
        self.assertIn(["native/extension.so", f"sha256={digest}", str(len(data))], rows)
        self.assertTrue(data.endswith(SIGNATURE))

    def test_signing_failure_preserves_original_wheel(self):
        wheel = self.make_wheel(payload=NATIVE)
        before = wheel.read_bytes()
        self.fail_signing = True
        with self.assertRaises(subprocess.CalledProcessError):
            self.sign()
        self.assertEqual(wheel.read_bytes(), before)

    def test_bad_later_wheel_does_not_replace_already_signed_wheel(self):
        first = self.make_wheel("aaa", NATIVE)
        later = self.make_wheel("zzz", NATIVE)
        before = first.read_bytes()
        with zipfile.ZipFile(later) as archive:
            files = {name: archive.read(name) for name in archive.namelist()}
        files["zzz/extension.so"] = b"tampered content"
        with zipfile.ZipFile(later, "w") as archive:
            for name, content in files.items():
                archive.writestr(name, content)
        with self.assertRaises(subprocess.CalledProcessError):
            self.sign()
        self.assertEqual(first.read_bytes(), before)

    def test_missing_identity_wrong_team_and_ambiguous_identities_fail(self):
        lines = [
            "0 valid identities found",
            f'1) {IDENTITY} "Apple Development: Fixture ({TEAM})"',
            f'1) {IDENTITY} "Developer ID Application: Fixture (OTHER12345)"',
            f'1) {IDENTITY} "Developer ID Application: One ({TEAM})"\n2) {IDENTITY} "Developer ID Application: Two ({TEAM})"',
        ]
        for identities in lines:
            with self.subTest(identities=identities), mock.patch.object(
                signing.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, identities, ""),
            ), self.assertRaises(ValueError):
                signing.signing_identity("fixture", TEAM)

    def test_invalid_signature_metadata_fails_without_replacing_wheel(self):
        wheel = self.make_wheel(payload=NATIVE)
        before = wheel.read_bytes()
        for removed in [f"TeamIdentifier={TEAM}", "Authority=Developer ID Application:", "Timestamp=", "(runtime)"]:
            with self.subTest(removed=removed):
                self.details = DETAILS.replace(removed, "invalid")
                with self.assertRaises(ValueError):
                    self.sign()
                self.assertEqual(wheel.read_bytes(), before)

    def test_empty_and_pure_only_wheelhouses_fail(self):
        with self.assertRaisesRegex(ValueError, "empty"):
            self.sign()
        self.make_wheel("pure")
        with self.assertRaisesRegex(ValueError, "No Mach-O"):
            self.sign()


class MacosKeychainCleanupTests(unittest.TestCase):
    def test_missing_secrets_fail_without_echoing_values(self):
        env = {key: value for key, value in os.environ.items() if key not in {
            "MACOS_CERTIFICATE_P12_BASE64", "MACOS_CERTIFICATE_PASSWORD", "APPLE_TEAM_ID",
        }}
        result = subprocess.run(["bash", str(WRAPPER), "unused"], env=env, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Set MACOS_CERTIFICATE_P12_BASE64", result.stderr)

    def test_import_and_later_signing_failures_cleanup_keychain_and_certificate(self):
        for fail_import in [True, False]:
            with self.subTest(fail_import=fail_import), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                binaries = root / "bin"
                binaries.mkdir()
                (root / "runtime").mkdir()
                signing_root = root / "signing"
                signing_root.mkdir()
                uname = binaries / "uname"
                uname.write_text("#!/bin/sh\necho Darwin\n")
                uname.chmod(0o755)
                security = binaries / "security"
                security.write_text(
                    "#!/bin/bash\n"
                    'echo "$1" >> "$TEST_SECURITY_LOG"\n'
                    'if [[ "$1" == create-keychain ]]; then touch "${@: -1}"; fi\n'
                    'if [[ "$1" == import && "$TEST_FAIL_IMPORT" == 1 ]]; then exit 1; fi\n'
                )
                security.chmod(0o755)
                env = dict(os.environ, PATH=f"{binaries}:{os.environ['PATH']}", RUNNER_TEMP=str(signing_root),
                           MACOS_CERTIFICATE_P12_BASE64=base64.b64encode(b"fixture certificate").decode(),
                           MACOS_CERTIFICATE_PASSWORD="fixture-password-DO-NOT-LOG", APPLE_TEAM_ID=TEAM,
                           TEST_SECURITY_LOG=str(root / "security.log"), TEST_FAIL_IMPORT=str(int(fail_import)))
                result = subprocess.run(["bash", str(WRAPPER), str(root / "runtime")], env=env, capture_output=True, text=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(list(signing_root.iterdir()), [])
                self.assertIn("delete-keychain", (root / "security.log").read_text())
                self.assertNotIn(env["MACOS_CERTIFICATE_PASSWORD"], result.stdout + result.stderr)
                self.assertNotIn(env["MACOS_CERTIFICATE_P12_BASE64"], result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
