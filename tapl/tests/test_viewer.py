from __future__ import annotations

import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

from taplctl import config as tapl_config
from taplctl import db as tapl_db
from taplctl import cli as tapl_cli
from taplctl import viewer


class ViewerTests(unittest.TestCase):
    def initialized_workspace(self, root: Path) -> Path:
        workspace = root / "workspace"
        tapl_db.initialize_workspace(workspace)
        return workspace

    def fake_runner(self, _db_path: Path, args: list[str]) -> dict[str, object]:
        if args[:3] == ["status", "--json", "--full"]:
            return {
                "active_run": None,
                "task_counts": {"Pending": 0},
                "incomplete_tasks": 0,
                "plans": [],
                "tasks": [],
                "findings": [],
            }
        if args[:3] == ["status", "--json", "--include-events"]:
            return {"recent_events": [{"event_type": "test", "mode": "observe", "created_at": "now"}]}
        if args[:3] == ["archive", "list", "--json"]:
            return {"ok": True, "archives": []}
        if args[:3] == ["archive", "show", "--id"]:
            archive = {"id": args[3], "slug": "saved", "summary": "", "created_at": "now"}
            return {"ok": True, "archive": archive, "items": [], "events": []}
        if args[0] == "search":
            return {"mode": "fts", "query": args[1], "results": []}
        if args[:3] == ["item", "show", "--id"]:
            return {
                "ok": True,
                "item": {
                    "id": int(args[3]),
                    "stable_id": "PLAN-001",
                    "kind": "plan",
                    "title": "Plan",
                },
            }
        raise AssertionError(f"unexpected args: {args}")

    def test_port_validation(self) -> None:
        self.assertEqual(viewer.parse_port("8000"), 8000)
        for value in ("0", "65536", "abc"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                viewer.parse_port(value)

    def test_allowed_origin_validation(self) -> None:
        self.assertEqual(
            viewer.parse_allowed_origin("HTTPS://Example.COM:443/"),
            "https://example.com",
        )
        self.assertEqual(
            viewer.parse_allowed_origin("http://[::1]:9000"),
            "http://[::1]:9000",
        )
        for value in (
            "example.com",
            "ftp://example.com",
            "https://example.com/path",
            "https://example.com?query=1",
            "https://user@example.com",
            "https://example.com:invalid",
        ):
            with self.subTest(value=value), self.assertRaises(ValueError):
                viewer.parse_allowed_origin(value)

        args = tapl_cli.build_parser().parse_args(
            ["viewer", "--allowed-origin", "HTTPS://Example.COM:443/"]
        )
        self.assertEqual(args.allowed_origins, ["https://example.com"])

    def test_config_loads_and_validates_viewer_allowed_origins(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.toml"
            config_path.write_text(
                """
[viewer]
allowed_origins = [
  "HTTPS://Example.COM:443/",
  "http://viewer.example.com:9000",
]
""".lstrip(),
                encoding="utf-8",
            )

            settings = tapl_config.load(config_path)

            self.assertEqual(
                settings.viewer.allowed_origins,
                ("https://example.com", "http://viewer.example.com:9000"),
            )
            self.assertEqual(
                settings.as_dict()["viewer"],
                {
                    "allowed_origins": [
                        "https://example.com",
                        "http://viewer.example.com:9000",
                    ]
                },
            )

            invalid_cases = (
                ('allowed_origins = "https://example.com"', "must be an array"),
                ("allowed_origins = [3]", r"viewer\.allowed_origins\[0\]"),
                ('allowed_origins = ["https://example.com/path"]', "without a path"),
                (
                    'allowed_origins = ["https://example.com", "https://example.com:443"]',
                    "contains duplicate origin",
                ),
            )
            for setting, expected_error in invalid_cases:
                with self.subTest(setting=setting):
                    config_path.write_text(
                        f"[viewer]\n{setting}\n",
                        encoding="utf-8",
                    )
                    with self.assertRaisesRegex(ValueError, expected_error):
                        tapl_config.load(config_path)

    def test_packaged_viewer_assets_are_present(self) -> None:
        self.assertTrue((viewer.ASSET_ROOT / viewer.INDEX_PATH).is_file())
        self.assertTrue((viewer.ASSET_ROOT / "assets" / "index.js").is_file())
        self.assertTrue((viewer.ASSET_ROOT / "assets" / "index.css").is_file())

    def test_release_build_syncs_assets_before_wheel_and_writes_viewer_service(self) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        workflow = (repo_root / ".github" / "workflows" / "release.yml").read_text(
            encoding="utf-8"
        )
        formula_updater = (repo_root / ".github" / "scripts" / "update_homebrew_formula.rb").read_text(
            encoding="utf-8"
        )
        self.assertLess(workflow.index("- name: Build shared viewer assets"), workflow.index("- name: Build Python wheel"))
        self.assertIn(".github/scripts/update_homebrew_formula.rb", workflow)
        self.assertIn('run [opt_bin/\\"taplctl\\", \\"viewer\\"]', formula_updater)
        self.assertNotIn('run [opt_bin/\\"taplctl\\", \\"searchd\\", \\"run\\"]', formula_updater)
        self.assertIn('restart_delay 5', formula_updater)
        self.assertIn('log_path var/\\"log/taplctl-viewer.log\\"', formula_updater)

    def test_workspace_selection_requires_existing_database(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            app = viewer.ViewerApplication(json_runner=self.fake_runner)

            missing = app.handle_message({"command": "ready", "locale": "ko"})
            self.assertEqual(missing["type"], "hydrate")
            self.assertEqual(missing["view"]["type"], "workspace")
            self.assertEqual(missing["locale"], "ko")

            empty = root / "empty"
            empty.mkdir()
            invalid = app.handle_message({"command": "selectWorkspace", "workspace": str(empty)})
            self.assertEqual(invalid["view"]["type"], "workspace")
            self.assertIn("No tapl database", invalid["view"]["message"])

            workspace = self.initialized_workspace(root)
            selected = app.handle_message({"command": "selectWorkspace", "workspace": str(workspace)})
            self.assertEqual(selected["view"]["type"], "overview")
            self.assertEqual(selected["workspace"], str(workspace.resolve()))

    def test_database_revision_tracks_database_and_sqlite_sidecars(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "tapl.db"
            sidecars = (
                db_path,
                db_path.with_name("tapl.db-wal"),
                db_path.with_name("tapl.db-shm"),
            )

            revision = viewer.database_revision(db_path)
            self.assertEqual(revision, viewer.database_revision(db_path))

            for path in sidecars:
                with self.subTest(path=path.name):
                    path.write_bytes(b"state")
                    created = viewer.database_revision(db_path)
                    self.assertNotEqual(revision, created)
                    self.assertEqual(created, viewer.database_revision(db_path))

                    path.write_bytes(b"state with a different size")
                    contents_changed = viewer.database_revision(db_path)
                    self.assertNotEqual(created, contents_changed)

                    stat = path.stat()
                    os.utime(
                        path,
                        ns=(stat.st_atime_ns, stat.st_mtime_ns + 2_000_000_000),
                    )
                    metadata_changed = viewer.database_revision(db_path)
                    self.assertNotEqual(contents_changed, metadata_changed)

                    path.unlink()
                    revision = viewer.database_revision(db_path)
                    self.assertNotEqual(metadata_changed, revision)

    def test_revision_message_skips_view_build_and_handles_workspace_selection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runner = mock.Mock(side_effect=AssertionError("revision must not query viewer data"))
            unconfigured = viewer.ViewerApplication(json_runner=runner)

            missing = unconfigured.handle_message({"command": "revision", "locale": "ko"})
            self.assertEqual(
                missing,
                {
                    "type": "revision",
                    "revision": "",
                    "workspace": "",
                    "workspaceValid": False,
                    "message": "Choose a workspace that contains .tapl/tapl.db.",
                },
            )

            workspace = self.initialized_workspace(root)
            response = unconfigured.handle_message(
                {"command": "revision", "workspace": str(workspace), "layout": "large"}
            )
            self.assertEqual(
                set(response),
                {"type", "revision", "workspace", "workspaceValid", "message"},
            )
            self.assertEqual(response["type"], "revision")
            self.assertEqual(len(response["revision"]), 64)
            self.assertEqual(response["workspace"], str(workspace.resolve()))
            self.assertTrue(response["workspaceValid"])
            self.assertEqual(response["message"], "")

            db_path = workspace / tapl_db.DEFAULT_DB_RELATIVE
            resolved_db_path = workspace.resolve() / tapl_db.DEFAULT_DB_RELATIVE
            db_path.unlink()
            invalid = unconfigured.handle_message(
                {"command": "revision", "workspace": str(workspace)}
            )
            self.assertEqual(
                invalid,
                {
                    "type": "revision",
                    "revision": "",
                    "workspace": str(workspace),
                    "workspaceValid": False,
                    "message": (
                        f"No tapl database found at {resolved_db_path}. "
                        f"Run `taplctl init --workspace-root {workspace.resolve()}` first."
                    ),
                },
            )
            runner.assert_not_called()

    def test_explicit_database_does_not_claim_the_current_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "custom.db"
            config_path = root / "config.toml"
            tapl_db.connect(db_path).close()
            config_path.write_text(
                '[viewer]\nallowed_origins = ["https://config.example.com"]\n',
                encoding="utf-8",
            )
            args = type(
                "Args",
                (),
                {
                    "db": db_path,
                    "config": config_path,
                    "port": 9123,
                    "allowed_origins": (
                        "https://config.example.com",
                        "https://tapl.example.com",
                    ),
                },
            )()
            with mock.patch.object(tapl_cli.viewer, "existing_workspace") as existing:
                with mock.patch.object(tapl_cli.viewer, "serve") as serve:
                    self.assertEqual(tapl_cli.cmd_viewer(args), 0)
            existing.assert_not_called()
            serve.assert_called_once_with(
                port=9123,
                allowed_origins=(
                    "https://config.example.com",
                    "https://tapl.example.com",
                ),
                default_db=db_path.resolve(),
                default_workspace=None,
            )

    def test_view_messages_use_read_only_cli_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = self.initialized_workspace(Path(tmp))
            app = viewer.ViewerApplication(default_workspace=workspace, json_runner=self.fake_runner)

            overview = app.handle_message({"command": "ready"})
            self.assertEqual(overview["view"]["type"], "overview")
            self.assertEqual(overview["view"]["status"]["recent_events"], [])

            debug = app.handle_message({"command": "debug"})
            self.assertEqual(debug["view"]["type"], "debug")
            self.assertEqual(len(debug["view"]["status"]["recent_events"]), 1)

            archive = app.handle_message({"command": "openArchive", "archiveId": "archive-1"})
            self.assertEqual(archive["view"]["archive"]["id"], "archive-1")

            search = app.handle_message({"command": "search", "query": "viewer"})
            self.assertEqual(search["view"]["search"]["query"], "viewer")

            item = app.handle_message({"command": "openSearchResult", "itemId": 7})
            self.assertEqual(item["view"]["detail"]["id"], 7)

    def test_http_server_serves_assets_and_rejects_cross_origin_api(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = self.initialized_workspace(root)
            assets = root / "assets"
            index = assets / viewer.INDEX_PATH
            script = assets / "assets" / "index.js"
            index.parent.mkdir(parents=True)
            script.parent.mkdir(parents=True)
            index.write_text("<!doctype html><script src='/assets/index.js'></script>", encoding="utf-8")
            script.write_text("console.log('viewer')", encoding="utf-8")

            app = viewer.ViewerApplication(
                default_workspace=workspace,
                asset_root=assets,
                json_runner=self.fake_runner,
            )
            try:
                server = viewer.create_server(
                    app,
                    port=0,
                    allowed_origins=("https://tapl.example.com",),
                )
            except viewer.ViewerError as exc:
                if "Operation not permitted" in str(exc):
                    self.skipTest("sandbox does not permit loopback sockets")
                raise
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            origin = server.browser_origin
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            try:
                with opener.open(f"{origin}/", timeout=5) as response:
                    self.assertEqual(response.status, 200)
                    self.assertIn("default-src 'self'", response.headers["Content-Security-Policy"])
                    self.assertIn(b"doctype html", response.read())

                payload = json.dumps({"command": "ready"}).encode("utf-8")
                request = urllib.request.Request(
                    f"{origin}/api/message",
                    data=payload,
                    headers={"Content-Type": "application/json", "Origin": origin},
                    method="POST",
                )
                with opener.open(request, timeout=5) as response:
                    body = json.loads(response.read())
                    self.assertEqual(body["view"]["type"], "overview")

                public_request = urllib.request.Request(
                    f"{origin}/api/message",
                    data=payload,
                    headers={
                        "Content-Type": "application/json",
                        "Origin": "https://tapl.example.com",
                    },
                    method="POST",
                )
                with opener.open(public_request, timeout=5) as response:
                    body = json.loads(response.read())
                    self.assertEqual(body["view"]["type"], "overview")

                revision_request = urllib.request.Request(
                    f"{origin}/api/message",
                    data=json.dumps({"command": "revision"}).encode("utf-8"),
                    headers={"Content-Type": "application/json", "Origin": origin},
                    method="POST",
                )
                with opener.open(revision_request, timeout=5) as response:
                    body = json.loads(response.read())
                    self.assertEqual(
                        set(body),
                        {"type", "revision", "workspace", "workspaceValid", "message"},
                    )
                    self.assertEqual(body["type"], "revision")
                    self.assertEqual(len(body["revision"]), 64)
                    self.assertEqual(body["workspace"], str(workspace.resolve()))
                    self.assertTrue(body["workspaceValid"])
                    self.assertEqual(body["message"], "")

                forbidden = urllib.request.Request(
                    f"{origin}/api/message",
                    data=payload,
                    headers={"Content-Type": "application/json", "Origin": "https://example.com"},
                    method="POST",
                )
                with self.assertRaises(urllib.error.HTTPError) as caught:
                    opener.open(forbidden, timeout=5)
                self.assertEqual(caught.exception.code, 403)
                caught.exception.close()

                with self.assertRaises(urllib.error.HTTPError) as caught:
                    opener.open(f"{origin}/api/message", timeout=5)
                self.assertEqual(caught.exception.code, 405)
                caught.exception.close()
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

    def test_port_conflict_has_actionable_error(self) -> None:
        app = viewer.ViewerApplication(json_runner=self.fake_runner)
        with mock.patch.object(
            viewer,
            "ViewerHTTPServer",
            side_effect=OSError(48, "Address already in use"),
        ):
            with self.assertRaisesRegex(viewer.ViewerError, "--port"):
                viewer.create_server(app, port=8000)


if __name__ == "__main__":
    unittest.main()
