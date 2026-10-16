"""Automatic migrations use only opted-in, isolated installation scopes."""
from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import tomllib
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from taplctl import install, uninstall


class AutoRefreshTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve()
        self.home = self.base / "home"
        self.repo = self.base / "repo"
        self.repo.mkdir()

    def install_scope(self, scope: str) -> Path:
        if scope == "user":
            install.install_user(codex_home=self.home / ".codex", taplctl_command="taplctl")
            return self.home
        install.install_repo(repo=self.repo, taplctl_command="taplctl")
        return self.repo

    def refresh(self, **kwargs):
        return install.auto_install_if_needed(
            start=self.repo, home=self.home, taplctl_command="taplctl", **kwargs,
        )

    @staticmethod
    def snapshot(root: Path):
        return {str(p.relative_to(root)): (p.read_bytes(), p.stat().st_mtime_ns)
                for p in root.rglob("*") if p.is_file()}

    def test_same_version_template_drift_merges_and_becomes_write_free(self):
        for scope in ("user", "repo"):
            self.install_scope(scope)
        template = install.default_config_text() + '\n[new_defaults]\nadded = "yes"\n'
        with mock.patch.object(install, "default_config_text", return_value=template):
            results = self.refresh()
            self.assertEqual([r["install"] for r in results], ["user", "repo"])
            for root in (self.home, self.repo):
                self.assertEqual(tomllib.loads((root / ".tapl/config.toml").read_text())["new_defaults"]["added"], "yes")
                state = json.loads((root / install.INSTALL_STATE_RELATIVE).read_text())
                self.assertEqual(state, install.managed_install_state())
            before = self.snapshot(self.base)
            self.assertEqual(self.refresh(), [])
            self.assertEqual(self.snapshot(self.base), before)

    def test_legacy_version_only_marker_refreshes_without_prompt_or_overwrite(self):
        root = self.install_scope("user")
        (root / install.INSTALL_STATE_RELATIVE).unlink()
        config = root / ".tapl/config.toml"
        config.write_text('[search]\nmax_results = 3\n[subagents]\nsetup_complete = true\nstrategy = "balanced"\n[subagents.models]\n"custom" = ["high"]\n')
        with mock.patch.object(install, "prompt_tapl_config_policy", side_effect=AssertionError("prompted")):
            self.refresh(tapl_config_policy="overwrite")
        parsed = tomllib.loads(config.read_text())
        self.assertEqual(parsed["search"]["max_results"], 3)
        self.assertEqual(parsed["subagents"]["models"], {"custom": ["high"]})
        self.assertEqual(parsed["subagents"]["strategy"], "balanced")
        self.assertTrue(parsed["recall"]["enabled"])

    def test_customization_alone_does_not_trigger_refresh(self):
        root = self.install_scope("user")
        (root / ".tapl/config.toml").write_text('[search]\nmax_results = 9\n')
        (root / ".codex/config.toml").write_text('model = "custom"\n')
        before = self.snapshot(self.base)
        self.assertEqual(self.refresh(), [])
        self.assertEqual(self.snapshot(self.base), before)

    def test_migration_preserves_model_other_hooks_and_enforce_mode(self):
        root = self.install_scope("user")
        (root / install.INSTALL_STATE_RELATIVE).unlink()
        (root / ".codex/config.toml").write_text('model = "chosen-model"\nmodel_reasoning_effort = "high"\n[features]\nmulti_agent = true\n[mcp_servers.tapl]\ncommand = "taplctl"\nargs = ["mcp"]\ncwd = "/old"\n[mcp_servers.other]\ncommand = "other"\n')
        hooks = install.build_hooks_config(taplctl_command="taplctl", mode="enforce")
        other = {"hooks": [{"type": "command", "command": 'echo "tapl-hook"'}]}
        hooks["hooks"]["Stop"].insert(0, other)
        (root / ".codex/hooks.json").write_text(json.dumps(hooks))
        self.refresh()
        parsed = tomllib.loads((root / ".codex/config.toml").read_text())
        self.assertEqual(parsed["model"], "chosen-model")
        self.assertEqual(parsed["model_reasoning_effort"], "high")
        self.assertNotIn("multi_agent", parsed.get("features", {}))
        self.assertEqual(parsed["mcp_servers"]["tapl"]["command"], "tapl-mcp")
        self.assertNotIn("cwd", parsed["mcp_servers"]["tapl"])
        self.assertNotIn("args", parsed["mcp_servers"]["tapl"])
        self.assertEqual(parsed["mcp_servers"]["other"]["command"], "other")
        refreshed = json.loads((root / ".codex/hooks.json").read_text())
        self.assertIn(other, refreshed["hooks"]["Stop"])
        for entries in refreshed["hooks"].values():
            for entry in entries:
                for hook in entry["hooks"]:
                    if install.is_tapl_hook_command_entry(hook):
                        self.assertIn("--mode enforce", hook["command"])

    def test_invalid_toml_does_not_write_any_scope_files_or_markers(self):
        root = self.install_scope("user")
        for relative in (".tapl/config.toml", ".codex/config.toml"):
            with self.subTest(relative=relative):
                path = root / relative
                original = path.read_text()
                path.write_text("[broken\n")
                (root / ".tapl/version").write_text("old\n")
                before = self.snapshot(root)
                with self.assertRaisesRegex(ValueError, "repair invalid TOML"):
                    self.refresh()
                self.assertEqual(self.snapshot(root), before)
                path.write_text(original)

    def test_partial_write_failure_keeps_completion_markers_stale_for_retry(self):
        root = self.install_scope("user")
        (root / ".tapl/version").write_text("old\n")
        (root / ".tapl/config.toml").write_text("[search]\nmax_results = 4\n")
        before = {p: p.read_bytes() for p in (root / ".tapl/version", root / install.INSTALL_STATE_RELATIVE)}
        original = install.config_editor._atomic_write
        def failing(path, text):
            if path == root / ".tapl/config.toml":
                raise OSError("simulated write failure")
            original(path, text)
        with mock.patch.object(install.config_editor, "_atomic_write", side_effect=failing):
            with self.assertRaisesRegex(OSError, "simulated"):
                self.refresh()
        for path, content in before.items():
            self.assertEqual(path.read_bytes(), content)
        self.assertTrue(install.user_scope_needs_install(root))
        self.assertTrue(self.refresh()[0]["ok"])

    def test_missing_repo_config_inherits_and_repo_requires_db(self):
        self.install_scope("repo")
        (self.repo / ".tapl/config.toml").unlink()
        (self.repo / install.INSTALL_STATE_RELATIVE).unlink()
        self.assertEqual(self.refresh()[0]["install"], "repo")
        self.assertFalse((self.repo / ".tapl/config.toml").exists())
        (self.repo / ".tapl/tapl.db").unlink()
        (self.repo / install.INSTALL_STATE_RELATIVE).unlink()
        before = self.snapshot(self.repo)
        self.assertEqual(self.refresh(), [])
        self.assertEqual(self.snapshot(self.repo), before)

    def test_uninstall_removes_state_and_prevents_reenrollment(self):
        for scope in ("user", "repo"):
            root = self.install_scope(scope)
            if scope == "user":
                uninstall.uninstall_user(codex_home=root / ".codex")
            else:
                uninstall.uninstall_repo(repo=root)
            self.assertFalse((root / install.INSTALL_STATE_RELATIVE).exists())
            self.assertFalse((root / install.VERSION_RELATIVE).exists())
        before = self.snapshot(self.base)
        self.assertEqual(self.refresh(), [])
        self.assertEqual(self.snapshot(self.base), before)

    def test_orphan_state_marker_does_not_opt_in(self):
        for root in (self.home, self.repo):
            (root / ".tapl").mkdir(parents=True)
            (root / install.INSTALL_STATE_RELATIVE).write_text(json.dumps(install.managed_install_state()))
        self.assertEqual(self.refresh(), [])

    def test_revision_and_codex_template_changes_trigger_refresh(self):
        root = self.install_scope("user")
        with mock.patch.object(install, "INSTALL_MIGRATION_REVISION", 100):
            self.assertTrue(install.user_scope_needs_install(root))
        original = install.codex_template_text
        def changed(*parts):
            text = original(*parts)
            return text + "\n# revised default template\n" if parts == ("config.toml",) else text
        with mock.patch.object(install, "codex_template_text", side_effect=changed):
            self.assertTrue(install.user_scope_needs_install(root))
            self.assertTrue(self.refresh()[0]["ok"])
            self.assertEqual(self.refresh(), [])

    def test_invalid_state_recovers_using_existing_version_opt_in(self):
        root = self.install_scope("user")
        (root / install.INSTALL_STATE_RELATIVE).write_text("{broken")
        self.assertTrue(self.refresh()[0]["ok"])
        self.assertEqual(self.refresh(), [])

    def test_inline_and_multiline_deprecated_paths_migrate_safely(self):
        root = self.install_scope("user")
        (root / install.INSTALL_STATE_RELATIVE).unlink()
        (root / ".codex/config.toml").write_text(
            'model = "custom"\nfeatures = { multi_agent = true, keep = true }\n'
            '[mcp_servers.tapl]\ncommand = "taplctl"\nargs = [\n"mcp",\n]\ncwd = "/old"\n'
        )
        (root / ".tapl/config.toml").write_text(
            'search = { max_results = 3 }\n'
            '"plan-task-execute" = { require_execution_approval = false, keep = true }\n'
        )
        self.refresh()
        parsed = tomllib.loads((root / ".codex/config.toml").read_text())
        self.assertTrue(parsed["features"]["keep"])
        self.assertNotIn("multi_agent", parsed["features"])
        self.assertEqual(parsed["model"], "custom")
        self.assertNotIn("args", parsed["mcp_servers"]["tapl"])
        parsed = tomllib.loads((root / ".tapl/config.toml").read_text())
        self.assertEqual(parsed["search"]["max_results"], 3)
        self.assertEqual(parsed["plan-task-execute"], {"keep": True})

    def test_explicit_install_invalid_config_does_not_mark_complete(self):
        root = self.install_scope("user")
        (root / ".tapl/config.toml").write_text("[broken\n")
        (root / install.INSTALL_STATE_RELATIVE).unlink()
        result = install.install_user(codex_home=root / ".codex", taplctl_command="taplctl")
        self.assertFalse(result["ok"])
        self.assertFalse((root / install.INSTALL_STATE_RELATIVE).exists())
        self.assertTrue(any("Repair invalid TOML" in item.get("error", "") for item in result["files"]))

    def test_atomic_write_failure_preserves_previous_config(self):
        path = self.repo / "config.toml"
        path.write_text("old = true\n")
        with mock.patch.object(install.config_editor.os, "replace", side_effect=OSError("replace failed")):
            with self.assertRaises(OSError):
                install.write_text_if_needed(path, "new = true\n", force=True, dry_run=False)
        self.assertEqual(path.read_text(), "old = true\n")
        self.assertEqual(list(self.repo.glob(".*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
