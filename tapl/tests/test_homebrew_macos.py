from __future__ import annotations

import hashlib
import importlib.util
import io
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest import mock
import zipfile


SCRIPTS = Path(__file__).resolve().parents[2] / ".github/scripts"
spec = importlib.util.spec_from_file_location("verify_homebrew_macos", SCRIPTS / "verify_homebrew_macos.py")
verification = importlib.util.module_from_spec(spec)
with mock.patch.object(sys, "path", [str(SCRIPTS), *sys.path]):
    spec.loader.exec_module(verification)

NATIVE = bytes.fromhex("cffaedfe") + b"signed native payload"
TEAM = "ABCDE12345"


class HomebrewMacosVerificationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.addCleanup(self.temporary.cleanup)

    def archive(self, *wheels):
        path = self.root / "runtime.tar.gz"
        with tarfile.open(path, "w:gz") as runtime:
            for index, entries in enumerate(wheels):
                buffer = io.BytesIO()
                with zipfile.ZipFile(buffer, "w") as wheel:
                    for name, data in entries.items():
                        wheel.writestr(name, data)
                payload = buffer.getvalue()
                entry = tarfile.TarInfo(f"./package{index}-1-py3-none-any.whl")
                entry.size = len(payload)
                runtime.addfile(entry, io.BytesIO(payload))
        return path

    def test_only_native_payloads_are_compared_with_installed_bytes(self):
        archive = self.archive({"package/native.so": NATIVE, "package/source.py": b"pass\n"})
        expected = verification.native_hashes(archive)
        self.assertEqual(expected, {"package/native.so": hashlib.sha256(NATIVE).hexdigest()})
        site = self.root / "site"
        (site / "package").mkdir(parents=True)
        (site / "package/native.so").write_bytes(NATIVE)
        with mock.patch.object(verification, "verify_signature") as verify:
            self.assertEqual(verification.verify_installed(site, expected, TEAM), 1)
        verify.assert_called_once_with(site / "package/native.so", TEAM)

    def test_relocated_bytes_fail_even_if_a_new_signature_would_verify(self):
        archive = self.archive({"native.so": NATIVE})
        (self.root / "native.so").write_bytes(NATIVE + b"Homebrew relocation")
        with mock.patch.object(verification, "verify_signature") as verify:
            with self.assertRaisesRegex(ValueError, "changed signed runtime bytes"):
                verification.verify_installed(self.root, verification.native_hashes(archive), TEAM)
        verify.assert_not_called()

    def test_ad_hoc_signature_does_not_pass_codesign_success_alone(self):
        archive = self.archive({"native.so": NATIVE})
        (self.root / "native.so").write_bytes(NATIVE)
        results = [
            subprocess.CompletedProcess([], 0, "", ""),
            subprocess.CompletedProcess([], 0, "", "Signature=adhoc\nTeamIdentifier=not set\nflags=0x10002(adhoc,runtime)\n"),
        ]
        with mock.patch.object(verification.subprocess, "run", side_effect=results):
            with self.assertRaisesRegex(ValueError, "Missing Developer ID"):
                verification.verify_installed(self.root, verification.native_hashes(archive), TEAM)

    def test_rejects_missing_duplicate_and_unsafe_native_payloads(self):
        with self.assertRaisesRegex(ValueError, "No Mach-O"):
            verification.native_hashes(self.archive({"source.py": b"pass"}))
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            verification.native_hashes(self.archive({"native.so": NATIVE}, {"native.so": NATIVE}))
        for name in ("../native.so", "/native.so", "package\\native.so", "pkg.data/platlib/native.so"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                verification.native_hashes(self.archive({name: NATIVE}))
        with self.assertRaisesRegex(ValueError, "Missing or unsafe"):
            verification.verify_installed(self.root, {"missing.so": "0" * 64}, TEAM)

    def test_rejects_installed_symlink_outside_site_packages(self):
        site = self.root / "site"
        site.mkdir()
        (self.root / "outside.so").write_bytes(NATIVE)
        (site / "native.so").symlink_to(self.root / "outside.so")
        with self.assertRaisesRegex(ValueError, "Missing or unsafe"):
            verification.verify_installed(site, {"native.so": hashlib.sha256(NATIVE).hexdigest()}, TEAM)

    def test_installation_mode_requires_disposable_ci(self):
        with mock.patch.dict(verification.os.environ, {"GITHUB_ACTIONS": "false"}):
            with mock.patch.object(verification.subprocess, "run") as run:
                with self.assertRaisesRegex(ValueError, "GitHub Actions"):
                    verification.install_and_verify(self.root, self.root, {}, TEAM)
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
