"""Distribution channels and optional dependency selection use local fixtures only."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest import mock

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))
from taplctl import updater


class InstallerChannelTests(unittest.TestCase):
    manifest_url = "https://fixtures.invalid/own/taplctl-install-manifest.json"
    wheel_url = "https://fixtures.invalid/taplctl-1.1.0-py3-none-any.whl"

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.venv = self.base / "install" / "versions" / "1.0.0"
        scripts = self.venv / "Scripts"
        scripts.mkdir(parents=True)
        self.python = scripts / "python.exe"
        self.python.write_bytes(b"python")
        command = scripts / "taplctl.exe"
        command.write_bytes(b"command")
        self.executable = self.base / "bin" / "taplctl.cmd"
        self.executable.parent.mkdir()
        self.executable.write_bytes(updater._windows_launcher_bytes(command))
        self.metadata_path = self.base / "install" / "install.json"
        self.metadata = dict(
            schema_version=1, method="powershell", manifest_url=self.manifest_url,
            version="1.0.0", wheel_url=self.wheel_url, wheel_sha256="0" * 64,
            install_root=str(self.base / "install"), bin_dir=str(self.base / "bin"),
            venv=str(self.venv), executable=str(self.executable),
        )
        self.write_metadata()
        self.requests: list[str] = []
        self.wheel = b"release wheel"
        self.responses = {self.manifest_url: self.manifest(), self.wheel_url: self.wheel}
        self.kwargs = dict(metadata_path=self.metadata_path, current_prefix=self.venv,
                           current_python=self.python, opener=self.opener)
        self.env_patch = mock.patch.dict(os.environ)
        self.env_patch.start()
        self.addCleanup(self.env_patch.stop)
        os.environ.pop("TAPL_INSTALL_MANIFEST_URL", None)

    def manifest(self, version: str = "1.1.0") -> bytes:
        return json.dumps(dict(schema_version=1, version=version,
                               wheel=dict(url=self.wheel_url, sha256=hashlib.sha256(self.wheel).hexdigest()))).encode()

    def write_metadata(self) -> None:
        self.metadata_path.write_text(json.dumps(self.metadata), encoding="utf-8")

    def opener(self, url: str) -> bytes:
        self.requests.append(url)
        return self.responses[url]

    @staticmethod
    def release(tag: str, published: str = "2026-01-01T00:00:00Z", *, draft: bool = False) -> dict:
        return dict(tag_name=tag, published_at=published, draft=draft, prerelease="-" in tag,
                    html_url="https://attacker.invalid/", assets=[dict(browser_download_url="https://attacker.invalid/")])

    @staticmethod
    def api(page: int = 1) -> str:
        return f"https://api.github.com/repos/qkdxorjs1002/tapl/releases?per_page=100&page={page}"

    @staticmethod
    def fixed(tag: str) -> str:
        return f"https://github.com/qkdxorjs1002/tapl/releases/download/{tag}/taplctl-install-manifest.json"

    def test_legacy_and_pinned_keep_their_manifest(self) -> None:
        for channel in (None, "pinned"):
            with self.subTest(channel=channel):
                if channel is not None:
                    self.metadata["channel"] = channel
                self.write_metadata()
                result = updater.check_for_update(**self.kwargs)
                self.assertEqual(result["manifest_url"], self.manifest_url)
        self.assertEqual(self.requests, [self.manifest_url, self.manifest_url])

    def test_stable_uses_latest_stable_manifest(self) -> None:
        self.metadata["channel"] = "stable"
        self.write_metadata()
        latest = "https://github.com/qkdxorjs1002/tapl/releases/latest/download/taplctl-install-manifest.json"
        self.responses[latest] = self.manifest()
        updater.check_for_update(**self.kwargs)
        self.assertEqual(self.requests, [latest])

    def test_explicit_and_environment_manifest_override_channel(self) -> None:
        self.metadata["channel"] = "pre"
        self.write_metadata()
        os.environ["TAPL_INSTALL_MANIFEST_URL"] = self.manifest_url
        updater.check_for_update(**self.kwargs)
        os.environ["TAPL_INSTALL_MANIFEST_URL"] = "https://must-not-fetch.invalid/"
        updater.check_for_update(**self.kwargs, manifest_url=self.manifest_url)
        self.assertEqual(self.requests, [self.manifest_url] * 2)

    def test_pre_uses_publication_time_across_pages_and_includes_stable(self) -> None:
        self.metadata["channel"] = "pre"
        self.write_metadata()
        first = [self.release("9.0.0-beta1")] * 99 + [self.release("10.0.0", "2027-01-01T00:00:00Z", draft=True)]
        # A recently published stable release wins over the higher beta version.
        second = [self.release("1.1.0", "2026-03-01T00:00:00Z"),
                  self.release("8.0.0-rc1", "2026-02-01T00:00:00Z"),
                  self.release("../../bad", "2029-01-01T00:00:00Z")]
        self.responses.update({self.api(): json.dumps(first).encode(), self.api(2): json.dumps(second).encode(),
                               self.fixed("1.1.0"): self.manifest()})
        result = updater.check_for_update(**self.kwargs)
        self.assertEqual(result["manifest_url"], self.fixed("1.1.0"))
        self.assertEqual(self.requests, [self.api(), self.api(2), self.fixed("1.1.0")])

    def test_pre_selects_prerelease_and_does_not_depend_on_response_order(self) -> None:
        for reverse in (False, True):
            releases = [self.release("1.1.0", "2026-01-01T00:00:00Z"),
                        self.release("1.2.0-beta1", "2026-02-01T00:00:00Z")]
            if reverse:
                releases.reverse()
            self.responses[self.api()] = json.dumps(releases).encode()
            selected = updater._newest_published_manifest_url(opener=self.opener, timeout=1)
            self.assertEqual(selected, self.fixed("1.2.0-beta1"))

    def test_pre_fails_closed_on_malformed_empty_or_unavailable_release_lists(self) -> None:
        malformed = [b"{}", b"not json", b"[]",
                     json.dumps([self.release("1.0.0", "not-a-time")]).encode(),
                     json.dumps([dict(tag_name="1.0.0", draft=0, prerelease=False)]).encode(),
                     json.dumps([dict(tag_name="1.0.0", draft=False, prerelease="false")]).encode()]
        for body in malformed:
            with self.subTest(body=body[:80]):
                self.responses[self.api()] = body
                with self.assertRaises(updater.UpdateError):
                    updater._newest_published_manifest_url(opener=self.opener, timeout=1)
        self.responses.clear()
        with self.assertRaises(updater.UpdateError) as caught:
            updater._newest_published_manifest_url(opener=self.opener, timeout=1)
        self.assertEqual(caught.exception.code, "download_failed")

    def test_pre_accepts_large_release_bodies_but_enforces_its_own_size_limit(self) -> None:
        latest = self.release("1.2.0-beta1", "2026-02-01T00:00:00Z")
        latest["body"] = "release notes " * 100_000
        latest["assets"] = [{"browser_download_url": "https://attacker.invalid/", "label": "x" * 10_000}]
        payload = json.dumps([self.release("1.1.0"), latest]).encode()
        self.assertGreater(len(payload), updater._MAX_MANIFEST_BYTES)
        self.assertLess(len(payload), updater._MAX_RELEASE_LIST_BYTES)
        self.responses[self.api()] = payload
        self.assertEqual(updater._newest_published_manifest_url(opener=self.opener, timeout=1),
                         self.fixed("1.2.0-beta1"))
        self.responses[self.api()] = b"x" * (updater._MAX_RELEASE_LIST_BYTES + 1)
        with self.assertRaises(updater.UpdateError) as caught:
            updater._newest_published_manifest_url(opener=self.opener, timeout=1)
        self.assertEqual(caught.exception.code, "invalid_release_list")

    def test_install_manifest_retains_the_smaller_size_limit(self) -> None:
        self.responses[self.manifest_url] = self.manifest() + b" " * updater._MAX_MANIFEST_BYTES
        with self.assertRaises(updater.UpdateError) as caught:
            updater.check_for_update(**self.kwargs)
        self.assertEqual(caught.exception.code, "invalid_manifest")

    def test_pre_pagination_overflow_or_later_page_error_never_uses_partial_selection(self) -> None:
        self.responses[self.api()] = json.dumps([self.release("1.1.0")] * 100).encode()
        with self.assertRaises(updater.UpdateError):
            updater._newest_published_manifest_url(opener=self.opener, timeout=1)
        with mock.patch.object(updater, "_MAX_RELEASE_PAGES", 1):
            with self.assertRaises(updater.UpdateError) as caught:
                updater._newest_published_manifest_url(opener=self.opener, timeout=1)
        self.assertEqual(caught.exception.code, "invalid_release_list")

    def test_invalid_new_metadata_is_rejected_before_download_or_write(self) -> None:
        original_launcher = self.executable.read_bytes()
        for field, bad in (("semantic", "true"), ("semantic", 1), ("semantic", None),
                           ("channel", "PRE"), ("channel", None), ("channel", [])):
            with self.subTest(field=field, value=bad):
                self.metadata.pop("channel", None)
                self.metadata.pop("semantic", None)
                self.metadata[field] = bad
                self.write_metadata()
                before = self.metadata_path.read_bytes()
                with self.assertRaises(updater.UpdateError) as caught:
                    updater.update_installation(**self.kwargs)
                self.assertEqual(caught.exception.code, "unsupported_installation")
                self.assertEqual(self.metadata_path.read_bytes(), before)
                self.assertEqual(self.executable.read_bytes(), original_launcher)
                self.assertEqual(self.requests, [])

    def test_update_preserves_extra_channel_and_legacy_missing_fields(self) -> None:
        for semantic, channel in ((True, "pre"), (False, "stable"), (None, None)):
            with self.subTest(semantic=semantic, channel=channel):
                # Restore original activation between independent update scenarios.
                self.executable.write_bytes(updater._windows_launcher_bytes(self.venv / "Scripts" / "taplctl.exe"))
                self.metadata.pop("semantic", None)
                self.metadata.pop("channel", None)
                if semantic is not None:
                    self.metadata.update(semantic=semantic, channel=channel)
                self.write_metadata()
                pip_args: list[list[str]] = []

                def runner(args: list[str], **_: object) -> types.SimpleNamespace:
                    if args[1:3] == ["-m", "venv"]:
                        scripts = Path(args[-1]) / "Scripts"
                        scripts.mkdir()
                        (scripts / "python.exe").write_bytes(b"python")
                        (scripts / "taplctl.exe").write_bytes(b"command")
                    elif args[1:3] == ["-m", "pip"]:
                        pip_args.append(args)
                    return types.SimpleNamespace(returncode=0, stdout="taplctl 1.1.0\n", stderr="")

                result = updater.update_installation(**self.kwargs, runner=runner, manifest_url=self.manifest_url)
                self.assertTrue(result["updated"])
                recorded = json.loads(self.metadata_path.read_text())
                if semantic is None:
                    self.assertNotIn("semantic", recorded)
                    self.assertNotIn("channel", recorded)
                else:
                    self.assertIs(recorded["semantic"], semantic)
                    self.assertEqual(recorded["channel"], channel)
                self.assertEqual(pip_args[0][-1].endswith("[semantic]"), semantic is True)
                self.assertTrue(self.venv.exists())

    def test_semantic_channel_survive_failed_activation_with_original_launcher(self) -> None:
        self.metadata.update(semantic=True, channel="pre")
        self.write_metadata()
        before_metadata = self.metadata_path.read_bytes()
        before_launcher = self.executable.read_bytes()
        before_versions = set(self.venv.parent.iterdir())
        real_replace = os.replace

        def runner(args: list[str], **_: object) -> types.SimpleNamespace:
            if args[1:3] == ["-m", "venv"]:
                scripts = Path(args[-1]) / "Scripts"
                scripts.mkdir()
                (scripts / "python.exe").write_bytes(b"python")
                (scripts / "taplctl.exe").write_bytes(b"command")
            return types.SimpleNamespace(returncode=0, stdout="taplctl 1.1.0\n", stderr="")

        def replace(source: object, destination: object) -> None:
            if Path(destination) == self.metadata_path:
                raise OSError("simulated metadata failure")
            real_replace(source, destination)

        with mock.patch.object(updater.os, "replace", side_effect=replace):
            with self.assertRaises(updater.UpdateError) as caught:
                updater.update_installation(**self.kwargs, runner=runner, manifest_url=self.manifest_url)
        self.assertEqual(caught.exception.code, "metadata_activation_failed")
        self.assertEqual(self.metadata_path.read_bytes(), before_metadata)
        self.assertEqual(self.executable.read_bytes(), before_launcher)
        self.assertEqual(set(self.venv.parent.iterdir()), before_versions)
