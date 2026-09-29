from __future__ import annotations

import json
import os
import tempfile
import tomllib
import unittest
from pathlib import Path

from taplctl import install, uninstall


def write(path: Path, content: str | bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content, encoding="utf-8")


def file_state(root: Path) -> dict[str, bytes | str]:
    state: dict[str, bytes | str] = {}
    if not root.exists() and not root.is_symlink():
        return state
    for path in sorted(root.rglob("*")):
        relative = str(path.relative_to(root))
        if path.is_symlink():
            state[relative] = f"symlink:{os.readlink(path)}"
        elif path.is_file():
            state[relative] = path.read_bytes()
    return state


def managed_hooks() -> dict[str, object]:
    return {
        "schema": 1,
        "hooks": {
            "UserPromptSubmit": [
                {
                    "matcher": "prompt",
                    "hooks": [
                        {
                            "type": "command",
                            "command": "tapl-hook --event UserPromptSubmit --mode observe",
                        },
                        {"type": "command", "command": "echo keep user hook"},
                    ],
                }
            ],
            "PermissionRequest": [
                {
                    "matcher": "Bash|Edit",
                    "hooks": [
                        {
                            "type": "command",
                            "command": (
                                "taplctl hook-event --event PermissionRequest --mode observe"
                            ),
                        },
                        {"type": "command", "command": "echo keep permission hook"},
                    ],
                }
            ],
            "UnrelatedEvent": [
                {"hooks": [{"type": "command", "command": "echo keep unrelated"}]}
            ],
        },
    }


def install_fixture(scope: Path) -> tuple[Path, Path]:
    codex_home = scope / ".codex"
    tapl_home = scope / ".tapl"
    write(codex_home / "hooks.json", json.dumps(managed_hooks(), indent=2) + "\n")
    write(
        codex_home / "config.toml",
        """
# keep this user comment
model = "user-model"

[features]
keep_feature = true

[mcp_servers.tapl]
command = "tapl-mcp"
enabled = true

[mcp_servers.keep]
command = "keep-mcp"
""".lstrip(),
    )
    write(tapl_home / "version", "0.0.0\n")
    write(tapl_home / "config.toml", "[search]\nmax_results = 7\n")
    write(tapl_home / "tapl.db", b"database")
    return codex_home, tapl_home


def file_result(payload: dict[str, object], path: Path) -> dict[str, str]:
    resolved = path.resolve(strict=False)
    return next(
        item
        for item in payload["files"]  # type: ignore[index]
        if Path(item["path"]).resolve(strict=False) == resolved
    )


class UninstallTests(unittest.TestCase):
    def test_default_user_uninstall_removes_only_integration_and_marker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            codex_home, tapl_home = install_fixture(home)

            payload = uninstall.uninstall_user(codex_home=codex_home)

            self.assertTrue(payload["ok"])
            self.assertEqual(payload["uninstall"], "user")
            self.assertEqual(Path(payload["codex_home"]), codex_home.resolve())
            self.assertFalse(payload["purge_config"])
            self.assertFalse(payload["purge_db"])
            self.assertFalse(payload["dry_run"])
            self.assertEqual(file_result(payload, codex_home / "hooks.json")["action"], "updated")
            self.assertEqual(file_result(payload, codex_home / "config.toml")["action"], "updated")
            self.assertEqual(file_result(payload, tapl_home / "version")["action"], "removed")

            hooks = json.loads((codex_home / "hooks.json").read_text(encoding="utf-8"))
            commands = json.dumps(hooks)
            self.assertNotIn("taplctl hook-event", commands)
            self.assertNotIn('"tapl-hook --event', commands)
            self.assertIn("echo keep user hook", commands)
            self.assertIn("echo keep permission hook", commands)
            self.assertIn("echo keep unrelated", commands)
            config = tomllib.loads((codex_home / "config.toml").read_text(encoding="utf-8"))
            self.assertIn(
                "# keep this user comment",
                (codex_home / "config.toml").read_text(encoding="utf-8"),
            )
            self.assertEqual(config["model"], "user-model")
            self.assertTrue(config["features"]["keep_feature"])
            self.assertNotIn("tapl", config.get("mcp_servers", {}))
            self.assertEqual(config["mcp_servers"]["keep"]["command"], "keep-mcp")
            self.assertFalse((tapl_home / "version").exists())
            self.assertEqual((tapl_home / "config.toml").read_text(), "[search]\nmax_results = 7\n")
            self.assertEqual((tapl_home / "tapl.db").read_bytes(), b"database")

    def test_default_repo_uninstall_preserves_runtime_state_and_unrelated_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            codex_home, tapl_home = install_fixture(repo)
            write(codex_home / "notes.txt", "keep codex\n")
            write(tapl_home / "archive.json", "keep tapl\n")

            payload = uninstall.uninstall_repo(repo=repo)

            self.assertTrue(payload["ok"])
            self.assertEqual(payload["uninstall"], "repo")
            self.assertEqual(Path(payload["repo"]), repo.resolve())
            self.assertFalse((tapl_home / "version").exists())
            self.assertTrue((tapl_home / "config.toml").is_file())
            self.assertTrue((tapl_home / "tapl.db").is_file())
            self.assertEqual((codex_home / "notes.txt").read_text(), "keep codex\n")
            self.assertEqual((tapl_home / "archive.json").read_text(), "keep tapl\n")

    def test_codex_toml_removal_supports_nested_dotted_and_inline_tables(self) -> None:
        variants = {
            "nested": """
[mcp_servers.keep]
command = "keep-mcp"
[mcp_servers.tapl]
command = "tapl-mcp"
[other]
value = 3
""",
            "dotted": """
mcp_servers.keep.command = "keep-mcp"
mcp_servers.tapl.command = "tapl-mcp"
mcp_servers.tapl.enabled = true
other.value = 3
""",
            "inline": """
mcp_servers = { keep = { command = "keep-mcp" }, tapl = { command = "tapl-mcp", enabled = true } }
other = { value = 3 }
""",
        }
        for name, source in variants.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmp:
                home = Path(tmp) / "home"
                codex_home = home / ".codex"
                write(codex_home / "config.toml", source.lstrip())
                write(home / ".tapl" / "version", "0.0.0\n")

                uninstall.uninstall_user(codex_home=codex_home)

                parsed = tomllib.loads((codex_home / "config.toml").read_text(encoding="utf-8"))
                self.assertNotIn("tapl", parsed.get("mcp_servers", {}))
                self.assertEqual(parsed["mcp_servers"]["keep"]["command"], "keep-mcp")
                self.assertEqual(parsed["other"]["value"], 3)

    def test_hook_removal_handles_wrappers_and_rejects_substring_false_positives(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            hooks_path = home / ".codex" / "hooks.json"
            remove = (
                "tapl-hook --event Stop",
                "/opt/tapl/bin/tapl-hook --event Stop",
                "env TAPL_MODE=observe /opt/tapl/bin/tapl-hook --event Stop",
                "exec /opt/tapl/bin/taplctl hook-event --event Stop",
            )
            keep = (
                "echo tapl-hook notes",
                "my-tapl-hook-helper --event Stop",
                "taplctl status",
                "echo taplctl hook-event documentation",
            )
            write(
                hooks_path,
                json.dumps(
                    {
                        "hooks": {
                            "PermissionRequest": [
                                {
                                    "matcher": "Bash",
                                    "hooks": [
                                        *(
                                            {"type": "command", "command": command}
                                            for command in remove
                                        ),
                                        *(
                                            {"type": "command", "command": command}
                                            for command in keep
                                        ),
                                    ],
                                }
                            ]
                        }
                    }
                ),
            )
            write(home / ".tapl" / "version", "0.0.0\n")

            uninstall.uninstall_user(codex_home=home / ".codex")

            rendered = hooks_path.read_text(encoding="utf-8")
            for command in remove:
                self.assertNotIn(command, rendered)
            for command in keep:
                self.assertIn(command, rendered)

    def test_dry_run_reports_changes_without_writing_user_or_repo_scope(self) -> None:
        for scope_name in ("user", "repo"):
            with self.subTest(scope=scope_name), tempfile.TemporaryDirectory() as tmp:
                scope = Path(tmp) / scope_name
                scope.mkdir()
                codex_home, tapl_home = install_fixture(scope)
                before = file_state(scope)

                if scope_name == "user":
                    payload = uninstall.uninstall_user(
                        codex_home=codex_home, purge_config=True, purge_db=True, dry_run=True
                    )
                else:
                    payload = uninstall.uninstall_repo(
                        repo=scope, purge_config=True, purge_db=True, dry_run=True
                    )

                self.assertTrue(payload["purge_config"])
                self.assertTrue(payload["purge_db"])
                self.assertTrue(payload["dry_run"])
                self.assertEqual(file_state(scope), before)
                self.assertEqual(
                    file_result(payload, tapl_home / "version")["action"],
                    "would_removed",
                )
                self.assertEqual(
                    file_result(payload, codex_home / "config.toml")["action"],
                    "would_updated",
                )
                self.assertEqual(
                    file_result(payload, tapl_home / "tapl.db")["action"],
                    "would_removed",
                )

    def test_purge_deletes_only_fixed_state_files_in_selected_scope(self) -> None:
        for scope_name in ("user", "repo"):
            with self.subTest(scope=scope_name), tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                scope = base / scope_name
                scope.mkdir()
                codex_home, tapl_home = install_fixture(scope)
                for suffix in ("-wal", "-shm", "-journal"):
                    write(tapl_home / f"tapl.db{suffix}", suffix.encode())
                preserved = {
                    tapl_home / "config.toml.bak": b"config backup",
                    tapl_home / "tapl.db.backup": b"db backup",
                    tapl_home / "other.db": b"other db",
                    tapl_home / "archive.json": b"archive",
                }
                for path, content in preserved.items():
                    write(path, content)
                other_scope = base / "other"
                _, other_tapl = install_fixture(other_scope)
                other_before = file_state(other_scope)

                if scope_name == "user":
                    payload = uninstall.uninstall_user(codex_home=codex_home, purge_config=True, purge_db=True)
                else:
                    payload = uninstall.uninstall_repo(repo=scope, purge_config=True, purge_db=True)

                self.assertTrue(payload["purge_config"])
                self.assertTrue(payload["purge_db"])
                for name in (
                    "version",
                    "config.toml",
                    "tapl.db",
                    "tapl.db-wal",
                    "tapl.db-shm",
                    "tapl.db-journal",
                ):
                    self.assertFalse((tapl_home / name).exists(), name)
                for path, content in preserved.items():
                    self.assertEqual(path.read_bytes(), content)
                self.assertEqual(file_state(other_scope), other_before)
                self.assertTrue(other_tapl.joinpath("version").exists())

    def test_repeated_uninstall_is_safe_and_reports_missing_targets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            codex_home, tapl_home = install_fixture(home)

            uninstall.uninstall_user(codex_home=codex_home, purge_config=True, purge_db=True)
            after_first = file_state(home)
            second = uninstall.uninstall_user(codex_home=codex_home, purge_config=True, purge_db=True)

            self.assertTrue(second["ok"])
            self.assertEqual(file_state(home), after_first)
            self.assertEqual(file_result(second, tapl_home / "version")["action"], "missing")
            self.assertEqual(file_result(second, tapl_home / "tapl.db")["action"], "missing")

    def test_malformed_json_or_toml_fails_preflight_before_any_write(self) -> None:
        cases = {
            "hooks_json": (Path(".codex/hooks.json"), "{broken"),
            "codex_toml": (Path(".codex/config.toml"), "[broken\n"),
            "tapl_toml": (Path(".tapl/config.toml"), "[broken\n"),
        }
        for name, (relative, malformed) in cases.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmp:
                home = Path(tmp) / "home"
                codex_home, _ = install_fixture(home)
                write(home / relative, malformed)
                before = file_state(home)

                with self.assertRaises((ValueError, json.JSONDecodeError, tomllib.TOMLDecodeError)):
                    uninstall.uninstall_user(codex_home=codex_home)

                self.assertEqual(file_state(home), before)

    def test_symlinked_scope_directories_and_managed_leaves_fail_preflight(self) -> None:
        cases = (
            ".codex",
            ".tapl",
            ".codex/hooks.json",
            ".codex/config.toml",
            ".tapl/version",
            ".tapl/config.toml",
            ".tapl/tapl.db",
            ".tapl/tapl.db-wal",
        )
        for relative in cases:
            with self.subTest(relative=relative), tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                home = base / "home"
                codex_home, _ = install_fixture(home)
                target = home / relative
                if not target.exists():
                    write(target, b"managed sidecar")
                external = base / "external" / relative.replace("/", "_")
                if target.is_dir():
                    external.mkdir(parents=True)
                    for child in target.iterdir():
                        if child.is_file():
                            write(external / child.name, child.read_bytes())
                    for child in list(target.iterdir()):
                        child.unlink()
                    target.rmdir()
                else:
                    write(external, target.read_bytes())
                    target.unlink()
                target.symlink_to(external, target_is_directory=external.is_dir())
                before_home = file_state(home)
                before_external = file_state(base / "external")

                with self.assertRaises(ValueError):
                    uninstall.uninstall_user(codex_home=codex_home)

                self.assertEqual(file_state(home), before_home)
                self.assertEqual(file_state(base / "external"), before_external)

    def test_uninstall_disables_auto_install_until_explicit_install_restores_it(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            repo = Path(tmp) / "repo"
            repo.mkdir()
            codex_home = home / ".codex"
            install.install_user(codex_home=codex_home, taplctl_command="taplctl")
            tapl_config = home / ".tapl" / "config.toml"
            write(tapl_config, "[search]\nmax_results = 9\n")

            uninstall.uninstall_user(codex_home=codex_home)
            after_uninstall = tapl_config.read_bytes()
            results = install.auto_install_if_needed(
                start=repo,
                home=home,
                taplctl_command="taplctl",
            )

            self.assertEqual(results, [])
            self.assertEqual(tapl_config.read_bytes(), after_uninstall)
            self.assertFalse((home / ".tapl" / "version").exists())
            codex = tomllib.loads((codex_home / "config.toml").read_text(encoding="utf-8"))
            self.assertNotIn("tapl", codex.get("mcp_servers", {}))

            install.install_user(codex_home=codex_home, taplctl_command="taplctl")

            self.assertTrue((home / ".tapl" / "version").is_file())
            restored = tomllib.loads((codex_home / "config.toml").read_text(encoding="utf-8"))
            self.assertEqual(restored["mcp_servers"]["tapl"]["command"], "tapl-mcp")
            self.assertIn("tapl-hook", (codex_home / "hooks.json").read_text(encoding="utf-8"))

    def test_symlinked_repo_root_is_rejected_before_purge(self) -> None:
        for dry_run in (False, True):
            with self.subTest(dry_run=dry_run), tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp).resolve()
                external = base / "external"
                install_fixture(external)
                selected = base / "repo-link"
                selected.symlink_to(external, target_is_directory=True)
                before = file_state(base)

                with self.assertRaises(ValueError):
                    uninstall.uninstall_repo(repo=selected, purge_config=True, purge_db=True, dry_run=dry_run)

                self.assertEqual(file_state(base), before)

    def test_user_root_and_payload_paths_resolve_filesystem_aliases(self) -> None:
        with tempfile.TemporaryDirectory(dir="/tmp") as tmp:
            home = Path(tmp) / "home"
            codex_home, tapl_home = install_fixture(home)

            payload = uninstall.uninstall_user(codex_home=codex_home)

            self.assertEqual(Path(payload["codex_home"]), codex_home.resolve())
            self.assertEqual(
                Path(file_result(payload, tapl_home / "version")["path"]),
                (tapl_home / "version").resolve(strict=False),
            )


if __name__ == "__main__":
    unittest.main()
