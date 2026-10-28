from __future__ import annotations

import http.server
import json
import os
import shutil
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BOOTSTRAP = ROOT / "install.ps1"
WRAPPER = ROOT / "install.cmd"
RELEASE_BASE = "https://github.com/qkdxorjs1002/tapl/releases"
RELEASES_API = "https://api.github.com/repos/qkdxorjs1002/tapl/releases"
MAIN_SCRIPT = "https://raw.githubusercontent.com/qkdxorjs1002/tapl/main/install.ps1"
MARKER = "# TAPL_RELEASE_BOOTSTRAP_V1"
POWERSHELL = shutil.which("pwsh") or shutil.which("pwsh.exe") or shutil.which("powershell.exe")


class InstallerBootstrapStaticTests(unittest.TestCase):
    def test_release_source_is_fixed_and_separate_from_manifest_configuration(self) -> None:
        source = BOOTSTRAP.read_text(encoding="utf-8")
        self.assertIn(f'$ReleaseBaseUrl = "{RELEASE_BASE}"', source)
        self.assertIn(f'$ReleasesApiUrl = "{RELEASES_API}"', source)
        self.assertIn('$scriptUrl = "$ReleaseBaseUrl/latest/download/install.ps1"', source)
        self.assertIn('$scriptUrl = "$ReleaseBaseUrl/download/$Version/install.ps1"', source)
        self.assertNotIn("TAPL_INSTALL_MANIFEST_URL", source)
        self.assertNotIn("Invoke-Expression", source)
        self.assertIn("$downloadedSource.Contains($BootstrapMarker)", source)
        self.assertIn(MARKER, source)
        self.assertNotIn(MARKER, (ROOT / ".github/scripts/install-windows.ps1").read_text(encoding="utf-8"))

    def test_typed_arguments_validation_cleanup_and_exit_status(self) -> None:
        source = BOOTSTRAP.read_text(encoding="utf-8")
        for parameter in ("[string]$Version", "[switch]$Pre", "[switch]$Semantic", "[switch]$Reinstall", "[switch]$Uninstall"):
            self.assertIn(parameter, source)
        router = source[source.index("\ntry {\n"):]
        self.assertLess(router.index("$Version -cnotmatch"), router.index("$Version = Get-LatestPublishedReleaseTag"))
        self.assertLess(router.index("$Uninstall -and"), router.index("$Version = Get-LatestPublishedReleaseTag"))
        self.assertLess(router.index("$Pre -and $hasVersion"), router.index("$Version = Get-LatestPublishedReleaseTag"))
        self.assertIn('"-File", $scriptPath', source)
        self.assertIn("& $hostExecutable @childArguments", source)
        self.assertIn("$exitCode = $LASTEXITCODE", source)
        self.assertIn("finally {", source)
        self.assertIn("Remove-Item -LiteralPath $WorkDirectory", source)
        self.assertIn("exit $exitCode", source)
        self.assertNotIn('"-Command"', source)
        self.assertIn("SetAccessRuleProtection($true, $false)", source)
        self.assertIn("& /bin/chmod 700 $WorkDirectory", source)
        self.assertIn("[System.Management.Automation.Language.Parser]::ParseFile", source)
        self.assertIn("$installerAst.ParamBlock.Parameters", source)
        self.assertIn("$declaredParameters -notcontains $parameter", source)

    def test_standalone_cmd_has_fixed_download_and_environment_paths(self) -> None:
        source = WRAPPER.read_text(encoding="utf-8")
        self.assertIn("setlocal DisableDelayedExpansion", source)
        self.assertIn(MAIN_SCRIPT, source)
        self.assertNotIn("%~dp0install.ps1", source)
        self.assertNotIn("for /f", source.lower())
        self.assertIn('mkdir "%TAPL_BOOTSTRAP_WORK%"', source)
        self.assertIn("if errorlevel 1 exit /b 1", source)
        self.assertIn("Set-Acl -LiteralPath $env:TAPL_BOOTSTRAP_WORK", source)
        self.assertIn("Join-Path $env:TAPL_BOOTSTRAP_WORK 'install.ps1'", source)
        self.assertIn('-File "%TAPL_BOOTSTRAP_WORK%\\install.ps1" %*', source)
        self.assertIn('set "TAPL_BOOTSTRAP_EXIT=%errorlevel%"', source)
        self.assertIn('rmdir /s /q "%TAPL_BOOTSTRAP_WORK%"', source)
        self.assertIn("exit /b %TAPL_BOOTSTRAP_EXIT%", source)
        for line in source.splitlines():
            if " -Command " in line:
                code = line.split(" -Command ", 1)[1]
                self.assertNotIn("%TEMP%", code)
                self.assertNotIn("%TAPL_BOOTSTRAP_WORK%", code)
                self.assertNotIn("%*", code)


class _Fixture(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.base = Path(self.directory.name)
        self.temp = self.base / "private temp & spaces !"
        self.temp.mkdir()
        self.capture = self.base / "capture.json"
        self.requests: list[str] = []
        self.assets: dict[str, tuple[int, str]] = {}
        fixture = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                fixture.requests.append(self.path)
                status, body = fixture.assets.get(self.path, (404, "missing fixture"))
                data = body.encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, _format: str, *args: object) -> None:
                pass

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=lambda: self.server.serve_forever(poll_interval=0.05), daemon=True)
        self.thread.start()
        self.addCleanup(self._stop_server)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.source = BOOTSTRAP.read_text(encoding="utf-8")
        # Only disposable test copies may use HTTP; production has no source override.
        self.assertEqual(self.source.count(RELEASE_BASE), 1)
        self.assertEqual(self.source.count(RELEASES_API), 1)
        self.source = self.source.replace(RELEASE_BASE, self.url + "/releases")
        self.source = self.source.replace(RELEASES_API, self.url + "/api/releases")
        self.script = self.base / "bootstrap script.ps1"
        self.script.write_text(self.source, encoding="utf-8")
        self.payload = '''[CmdletBinding()]
param([string]$Version, [switch]$Reinstall, [switch]$Uninstall, [switch]$Semantic, [ValidateSet('stable','pre','pinned')][string]$Channel='pinned')
$data = @{version=$Version; reinstall=[bool]$Reinstall; uninstall=[bool]$Uninstall; semantic=[bool]$Semantic; channel=$Channel; directory=$PSScriptRoot}
[IO.File]::WriteAllText($env:TAPL_TEST_CAPTURE, ($data | ConvertTo-Json -Compress))
exit ([int]$env:TAPL_TEST_EXIT)
'''
        self.assets["/releases/latest/download/install.ps1"] = (200, self.payload)
        self.environment = dict(os.environ, TMPDIR=str(self.temp), TEMP=str(self.temp), TMP=str(self.temp),
                                TAPL_TEST_CAPTURE=str(self.capture), TAPL_TEST_EXIT="0",
                                TAPL_INSTALL_MANIFEST_URL=self.url + "/untrusted-manifest")

    def _stop_server(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def assert_clean(self) -> None:
        # Unix pwsh may retain its own pwsh-* engine cache in TMPDIR. The
        # bootstrap owns only tapl-bootstrap-* and tapl-cmd-* directories.
        leftovers = [path for path in self.temp.iterdir()
                     if path.name.startswith(("tapl-bootstrap-", "tapl-cmd-"))]
        self.assertEqual(leftovers, [])

    def captured(self) -> dict[str, object]:
        return json.loads(self.capture.read_text(encoding="utf-8-sig"))

    @staticmethod
    def release(tag: str, published: str = "2026-01-01T00:00:00Z", **extra: object) -> dict[str, object]:
        return {"tag_name": tag, "published_at": published, "draft": False, **extra}

    def api_page(self, entries: list[object], page: int = 1) -> None:
        self.assets[f"/api/releases?per_page=100&page={page}"] = (200, json.dumps(entries))


@unittest.skipUnless(POWERSHELL, "PowerShell 5.1 or pwsh is unavailable")
class PowerShellBootstrapTests(_Fixture):
    def run_script(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run([str(POWERSHELL), "-NoLogo", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                               "-File", str(self.script), *arguments], env=self.environment,
                              capture_output=True, text=True, check=False, timeout=45)

    def test_default_fetches_latest_release_and_cleans_private_directory(self) -> None:
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.requests, ["/releases/latest/download/install.ps1"])
        capture = self.captured()
        self.assertEqual(capture["version"], "")
        self.assertFalse(capture["reinstall"])
        self.assertFalse(capture["uninstall"])
        self.assertFalse(capture["semantic"])
        self.assertEqual(capture["channel"], "stable")
        self.assertTrue(Path(str(capture["directory"])).name.startswith("tapl-bootstrap-"))
        self.assert_clean()

    def test_pinned_tags_and_reinstall_are_forwarded_unchanged(self) -> None:
        for tag in ("2.14.0", "2.14.0-alpha1", "2.14.0-beta12", "2.14.0-rc0"):
            with self.subTest(tag=tag):
                path = f"/releases/download/{tag}/install.ps1"
                self.assets[path] = (200, self.payload)
                result = self.run_script("-Version", tag, "-Reinstall")
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(self.requests[-1], path)
                self.assertEqual(self.captured()["version"], tag)
                self.assertTrue(self.captured()["reinstall"])
                self.assertEqual(self.captured()["channel"], "pinned")
                self.assert_clean()

    def test_uninstall_and_reinstall_without_version_are_forwarded(self) -> None:
        for flag, key in (("-Uninstall", "uninstall"), ("-Reinstall", "reinstall")):
            with self.subTest(flag=flag):
                result = self.run_script(flag)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertTrue(self.captured()[key])
                self.assert_clean()

    def test_invalid_tags_and_conflicts_fail_before_network(self) -> None:
        cases = [("-Version", tag) for tag in ("../bad", "v1.0.0", "1.0.0b1", "1.0.0-beta01", "01.0.0", "1.0.0;exit 0", "")]
        cases += [("-Uninstall", "-Reinstall"), ("-Pre", "-Version", "1.0.0")]
        for arguments in cases:
            with self.subTest(arguments=arguments):
                result = self.run_script(*arguments)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(self.requests, [])
                self.assertFalse(self.capture.exists())
                self.assert_clean()

    def test_child_nonzero_exit_is_preserved_exactly(self) -> None:
        self.environment["TAPL_TEST_EXIT"] = "23"
        result = self.run_script()
        self.assertEqual(result.returncode, 23, result.stderr)
        self.assertTrue(self.capture.exists())
        self.assert_clean()

    def test_http_failures_do_not_execute_response_and_cleanup(self) -> None:
        for status in (404, 500):
            with self.subTest(status=status):
                self.assets["/releases/latest/download/install.ps1"] = (status, self.payload)
                result = self.run_script()
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(self.capture.exists())
                self.assert_clean()

    def test_bootstrap_asset_is_refused_without_recursion(self) -> None:
        self.assets["/releases/latest/download/install.ps1"] = (200, self.source)
        result = self.run_script()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("refusing recursive execution", result.stderr)
        self.assertEqual(len(self.requests), 1)
        self.assertFalse(self.capture.exists())
        self.assert_clean()

    def test_empty_release_asset_fails_closed(self) -> None:
        self.assets["/releases/latest/download/install.ps1"] = (200, " \r\n")
        result = self.run_script()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("asset is empty", result.stderr)
        self.assertFalse(self.capture.exists())
        self.assert_clean()

    def test_separate_runs_receive_distinct_temporary_directories(self) -> None:
        first = self.run_script()
        self.assertEqual(first.returncode, 0, first.stderr)
        directory = self.captured()["directory"]
        second = self.run_script()
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertNotEqual(directory, self.captured()["directory"])
        self.assert_clean()

    def test_legacy_no_parameter_payload_allows_default_install(self) -> None:
        self.assets["/releases/latest/download/install.ps1"] = (
            200, '[IO.File]::WriteAllText($env:TAPL_TEST_CAPTURE, \'{"legacy":true}\')\nexit 0\n',
        )
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(self.captured()["legacy"])
        self.assert_clean()

    def test_requested_options_require_top_level_parameter_declarations(self) -> None:
        side_effect = '[IO.File]::WriteAllText($env:TAPL_TEST_CAPTURE, \'{"ran":true}\')\nexit 0\n'
        fake_blocks = (
            "",
            "# param([string]$Version, [switch]$Reinstall, [switch]$Uninstall, [switch]$Semantic)\n",
            "function Invoke-Legacy { param([string]$Version, [switch]$Reinstall, [switch]$Uninstall, [switch]$Semantic) }\n",
        )
        for fake in fake_blocks:
            for arguments in (("-Version", "2.13.2"), ("-Reinstall",), ("-Uninstall",), ("-Semantic",)):
                with self.subTest(fake=fake, arguments=arguments):
                    self.assets["/releases/latest/download/install.ps1"] = (200, fake + side_effect)
                    self.assets["/releases/download/2.13.2/install.ps1"] = (200, fake + side_effect)
                    result = self.run_script(*arguments)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("does not support the requested " + arguments[0] + " option", result.stderr)
                    self.assertFalse(self.capture.exists())
                    self.assert_clean()

    def test_parameter_declarations_are_case_insensitive(self) -> None:
        payload = self.payload.replace("[string]$Version", "[string]$version").replace("[switch]$Reinstall", "[switch]$reINSTALL")
        self.assets["/releases/download/2.13.2/install.ps1"] = (200, payload)
        result = self.run_script("-Version", "2.13.2", "-Reinstall")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.captured()["version"], "2.13.2")
        self.assertTrue(self.captured()["reinstall"])
        self.assert_clean()

    def test_syntax_invalid_payload_is_rejected_before_any_execution(self) -> None:
        self.assets["/releases/latest/download/install.ps1"] = (
            200, '[IO.File]::WriteAllText($env:TAPL_TEST_CAPTURE, "ran")\nif (\n',
        )
        result = self.run_script()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("contains PowerShell syntax errors", result.stderr)
        self.assertFalse(self.capture.exists())
        self.assert_clean()

    def test_channel_and_semantic_option_matrix(self) -> None:
        tag = "3.0.0-beta1"
        self.api_page([self.release(tag)])
        self.assets[f"/releases/download/{tag}/install.ps1"] = (200, self.payload)
        for arguments, channel, version in (((), "stable", ""), (("-Pre",), "pre", tag), (("-Version", tag), "pinned", tag)):
            for semantic in (False, True):
                with self.subTest(channel=channel, semantic=semantic):
                    self.requests.clear()
                    flags = (*arguments, "-Semantic") if semantic else arguments
                    result = self.run_script(*flags)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    capture = self.captured()
                    self.assertEqual(capture["channel"], channel)
                    self.assertEqual(capture["version"], version)
                    self.assertEqual(capture["semantic"], semantic)
                    expected = ["/releases/latest/download/install.ps1"] if channel == "stable" else [f"/releases/download/{tag}/install.ps1"]
                    if channel == "pre":
                        expected.insert(0, "/api/releases?per_page=100&page=1")
                    self.assertEqual(self.requests, expected)
                    self.assert_clean()

    def test_pre_selects_publication_timestamp_and_ignores_untrusted_asset_urls(self) -> None:
        self.api_page([
            self.release("9.0.0-beta9", "2026-01-01T00:00:00Z", prerelease=True),
            self.release("3.0.0", "2026-02-01T00:00:00Z", assets=[{"browser_download_url": self.url + "/untrusted.ps1"}]),
            self.release("4.0.0", "2026-03-01T00:00:00Z", draft=True),
            self.release("../bad", "2026-04-01T00:00:00Z"),
            self.release("5.0.0", "not-a-timestamp"),
            {"tag_name": "6.0.0", "draft": False},
        ])
        self.assets["/releases/download/3.0.0/install.ps1"] = (200, self.payload)
        result = self.run_script("-Pre")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.captured()["version"], "3.0.0")
        self.assertEqual(self.captured()["channel"], "pre")
        self.assertEqual(self.requests, ["/api/releases?per_page=100&page=1", "/releases/download/3.0.0/install.ps1"])
        self.assert_clean()

    def test_pre_normalizes_non_enumerated_json_arrays(self) -> None:
        conversion = '$parsedReleases = $json | ConvertFrom-Json @jsonParameters'
        self.assertEqual(self.source.count(conversion), 1)
        self.script.write_text(self.source.replace(
            conversion, '$parsedReleases = Write-Output -NoEnumerate ($json | ConvertFrom-Json @jsonParameters)',
        ), encoding="utf-8")
        tag = "3.0.0-beta1"
        self.assets[f"/releases/download/{tag}/install.ps1"] = (200, self.payload)
        for releases in ([self.release(tag)], [self.release("2.0.0"), self.release(tag, "2026-05-01T00:00:00Z")]):
            with self.subTest(count=len(releases)):
                self.api_page(releases)
                result = self.run_script("-Pre")
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(self.captured()["version"], tag)
                self.assert_clean()

    def test_pre_paginates_full_pages_and_selects_from_later_page(self) -> None:
        self.api_page([self.release(f"1.0.{index}") for index in range(100)])
        self.api_page([self.release("2.0.0-rc1", "2026-05-01T00:00:00Z")], page=2)
        self.assets["/releases/download/2.0.0-rc1/install.ps1"] = (200, self.payload)
        result = self.run_script("-Pre", "-Semantic")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.captured()["version"], "2.0.0-rc1")
        self.assertEqual(self.requests, ["/api/releases?per_page=100&page=1", "/api/releases?per_page=100&page=2", "/releases/download/2.0.0-rc1/install.ps1"])
        self.assert_clean()

    def test_pre_compares_offset_timestamps_as_instants_on_both_json_paths(self) -> None:
        self.api_page([
            self.release("1.0.0", "2026-05-01T01:00:00+09:00"),
            self.release("1.1.0", "2026-04-30T17:30:00Z"),
            self.release("1.2.0-beta1", "2026-04-30T13:00:00-05:00"),
            self.release("9.0.0", "2026-99-99T00:00:00Z"),
            self.release("8.0.0", "2026-05-30T00:00:00"),
        ])
        self.assets["/releases/download/1.2.0-beta1/install.ps1"] = (200, self.payload)
        detection = 'if ((Get-Command ConvertFrom-Json).Parameters.ContainsKey("DateKind"))'
        self.assertEqual(self.source.count(detection), 1)
        for legacy_json in (False, True):
            with self.subTest(legacy_json=legacy_json):
                source = self.source.replace(detection, "if ($false)") if legacy_json else self.source
                self.script.write_text(source, encoding="utf-8")
                result = self.run_script("-Pre")
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(self.captured()["version"], "1.2.0-beta1")
                self.assert_clean()

    def test_pre_refuses_incomplete_selection_on_pagination_overflow(self) -> None:
        for page in range(1, 11):
            self.api_page([self.release("1.0.0") for _ in range(100)], page=page)
        result = self.run_script("-Pre")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("pagination limit", result.stderr)
        self.assertEqual(len(self.requests), 10)
        self.assertTrue(all(path.startswith("/api/releases?") for path in self.requests))
        self.assertFalse(self.capture.exists())
        self.assert_clean()

    def test_pre_api_errors_and_no_valid_release_fail_before_payload_download(self) -> None:
        cases = (
            (200, "[]"),
            (200, json.dumps([self.release("1.0.0", draft=True), self.release("bad"), self.release("2.0.0", "2026-99-99T00:00:00Z") ])),
            (200, "{\"message\":\"not an array\"}"),
            (200, "[malformed]"),
            (403, "rate limited"),
            (500, "server error"),
        )
        for status, body in cases:
            with self.subTest(status=status, body=body):
                self.requests.clear()
                self.assets["/api/releases?per_page=100&page=1"] = (status, body)
                result = self.run_script("-Pre")
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(self.requests, ["/api/releases?per_page=100&page=1"])
                self.assertFalse(self.capture.exists())
                self.assert_clean()

    def test_pre_install_requires_channel_support_but_legacy_default_and_pin_remain_compatible(self) -> None:
        legacy = '''param([string]$Version, [switch]$Uninstall)
[IO.File]::WriteAllText($env:TAPL_TEST_CAPTURE, ('{"version":"' + $Version + '","uninstall":' + ([bool]$Uninstall).ToString().ToLowerInvariant() + '}'))
'''
        self.api_page([self.release("2.13.2")])
        self.assets["/releases/latest/download/install.ps1"] = (200, legacy)
        self.assets["/releases/download/2.13.2/install.ps1"] = (200, legacy)
        result = self.run_script("-Pre")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("requested -Channel option", result.stderr)
        self.assertFalse(self.capture.exists())
        for arguments in ((), ("-Version", "2.13.2")):
            with self.subTest(arguments=arguments):
                result = self.run_script(*arguments)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(self.captured()["version"], "2.13.2" if arguments else "")
                self.assert_clean()

    def test_uninstall_selectors_do_not_forward_version_and_can_use_legacy_channel(self) -> None:
        legacy = '''param([switch]$Uninstall)
[IO.File]::WriteAllText($env:TAPL_TEST_CAPTURE, ('{"uninstall":' + ([bool]$Uninstall).ToString().ToLowerInvariant() + '}'))
'''
        self.api_page([self.release("2.13.2")])
        self.assets["/releases/download/2.13.2/install.ps1"] = (200, legacy)
        for selector in (("-Version", "2.13.2"), ("-Pre",)):
            with self.subTest(selector=selector):
                self.requests.clear()
                result = self.run_script(*selector, "-Uninstall")
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertTrue(self.captured()["uninstall"])
                self.assertEqual(self.requests[-1], "/releases/download/2.13.2/install.ps1")
                self.assert_clean()
        self.assets["/releases/download/2.13.2/install.ps1"] = (200, self.payload)
        for selector, channel in ((("-Version", "2.13.2"), "pinned"), (("-Pre",), "pre")):
            with self.subTest(selector=selector, channel=channel):
                result = self.run_script(*selector, "-Uninstall", "-Semantic")
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(self.captured()["version"], "")
                self.assertEqual(self.captured()["channel"], channel)
                self.assertTrue(self.captured()["uninstall"])
                self.assertTrue(self.captured()["semantic"])
                self.assert_clean()


@unittest.skipUnless(os.name == "nt", "Standalone CMD tests require Windows")
class CommandBootstrapTests(_Fixture):
    def setUp(self) -> None:
        super().setUp()
        # The wrapper is deliberately downloaded alone, with no adjacent .ps1.
        wrapper = WRAPPER.read_text(encoding="utf-8")
        self.assertEqual(wrapper.count(MAIN_SCRIPT), 1)
        self.wrapper = self.base / "standalone installer.cmd"
        self.wrapper.write_text(wrapper.replace(MAIN_SCRIPT, self.url + "/main/install.ps1"), encoding="utf-8")
        self.assets["/main/install.ps1"] = (200, self.source)
        self.assertFalse(self.wrapper.with_suffix(".ps1").exists())

    def run_cmd(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(f'cmd.exe /d /s /c ""{self.wrapper}" {subprocess.list2cmdline(arguments)}"',
                              env=self.environment, capture_output=True, text=True, check=False, timeout=60)

    def test_downloaded_alone_forwards_version_flags_and_exit_code(self) -> None:
        self.assets["/releases/download/2.14.0-beta1/install.ps1"] = (200, self.payload)
        self.environment["TAPL_TEST_EXIT"] = "23"
        result = self.run_cmd("-Version", "2.14.0-beta1", "-Reinstall")
        self.assertEqual(result.returncode, 23, result.stderr)
        self.assertEqual(self.captured()["version"], "2.14.0-beta1")
        self.assertTrue(self.captured()["reinstall"])
        self.assertEqual(self.requests, ["/main/install.ps1", "/releases/download/2.14.0-beta1/install.ps1"])
        self.assert_clean()

    def test_downloaded_alone_forwards_uninstall(self) -> None:
        result = self.run_cmd("-Uninstall")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(self.captured()["uninstall"])
        self.assert_clean()

    def test_downloaded_alone_forwards_pre_and_semantic(self) -> None:
        self.api_page([self.release("3.0.0-beta1")])
        self.assets["/releases/download/3.0.0-beta1/install.ps1"] = (200, self.payload)
        result = self.run_cmd("-Pre", "-Semantic")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.captured()["version"], "3.0.0-beta1")
        self.assertEqual(self.captured()["channel"], "pre")
        self.assertTrue(self.captured()["semantic"])
        self.assertEqual(self.requests, ["/main/install.ps1", "/api/releases?per_page=100&page=1", "/releases/download/3.0.0-beta1/install.ps1"])
        self.assert_clean()

    def test_windows_powershell_uses_current_host_modules(self) -> None:
        legacy_host = Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
        # Reproduce a Python intermediary inheriting pwsh's module path. The
        # 5.1 entry script must still resolve its own Security/Utility modules.
        self.environment["PSModulePath"] = str(Path(str(POWERSHELL)).parent / "Modules")
        self.api_page([self.release("3.0.0-beta1")])
        self.assets["/releases/download/3.0.0-beta1/install.ps1"] = (200, self.payload)
        for flags, channel, semantic in (((), "stable", False), (("-Pre", "-Semantic"), "pre", True)):
            with self.subTest(flags=flags):
                result = subprocess.run(
                    [str(legacy_host), "-NoLogo", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                     "-File", str(self.script), *flags], env=self.environment,
                    capture_output=True, text=True, check=False, timeout=60,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(self.captured()["channel"], channel)
                self.assertEqual(self.captured()["semantic"], semantic)
                self.assert_clean()

    def test_failed_bootstrap_download_fails_closed_and_cleans(self) -> None:
        self.assets["/main/install.ps1"] = (500, self.source)
        result = self.run_cmd()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.requests, ["/main/install.ps1"])
        self.assertFalse(self.capture.exists())
        self.assert_clean()

    def test_invalid_options_fail_before_release_download(self) -> None:
        for arguments in (("-Version", "../bad"), ("-Uninstall", "-Reinstall"), ("-Pre", "-Version", "1.0.0")):
            with self.subTest(arguments=arguments):
                self.requests.clear()
                result = self.run_cmd(*arguments)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(self.requests, ["/main/install.ps1"])
                self.assertFalse(self.capture.exists())
                self.assert_clean()


if __name__ == "__main__":
    unittest.main()
