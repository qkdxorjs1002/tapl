from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from taplctl import __version__, config as tapl_config


class TaplCliTests(unittest.TestCase):
    def tapl_env(self) -> dict[str, str]:
        env = os.environ.copy()
        env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
        return env

    def run_cli(self, db_path: Path, *args: str, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "taplctl", "--db", str(db_path), *args],
            input=input_text,
            text=True,
            capture_output=True,
            check=False,
            env=self.tapl_env(),
        )

    def run_taplctl(
        self,
        *args: str,
        input_text: str | None = None,
        cwd: Path | None = None,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "taplctl", *args],
            input=input_text,
            text=True,
            capture_output=True,
            check=False,
            env=self.tapl_env(),
            cwd=str(cwd) if cwd else None,
        )

    def test_version_comes_from_pyproject(self) -> None:
        with (ROOT / "pyproject.toml").open("rb") as pyproject_file:
            pyproject = tomllib.load(pyproject_file)
        expected_version = pyproject["project"]["version"]

        self.assertEqual(__version__, expected_version)

        version = self.run_taplctl("--version")
        self.assertEqual(version.returncode, 0, version.stderr)
        self.assertEqual(version.stdout.strip(), f"taplctl {expected_version}")

    def test_init_task_status_and_search(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "tapl.db"
            init = self.run_cli(db_path, "init", "--json")
            self.assertEqual(init.returncode, 0, init.stderr)
            self.assertTrue(json.loads(init.stdout)["ok"])

            task = self.run_cli(
                db_path,
                "task",
                "upsert",
                "--id",
                "TASK-001",
                "--title",
                "Build tapl harness",
                "--status",
                "In Progress",
                "--goal",
                "Create DB-backed workflow state",
                "--json",
            )
            self.assertEqual(task.returncode, 0, task.stderr)

            status = self.run_cli(db_path, "status", "--json")
            payload = json.loads(status.stdout)
            self.assertEqual(payload["task_counts"]["In Progress"], 1)
            self.assertEqual(payload["counts"]["tasks"], 1)
            self.assertEqual(payload["counts"]["archives"], 0)
            self.assertNotIn("recent_events", payload)
            self.assertNotIn("archives", payload)
            self.assertNotIn("body", payload["tasks"][0])
            self.assertNotIn("goal", payload["tasks"][0])

            full_status = self.run_cli(db_path, "status", "--json", "--full")
            self.assertEqual(full_status.returncode, 0, full_status.stderr)
            full_payload = json.loads(full_status.stdout)
            self.assertNotIn("recent_events", full_payload)
            self.assertNotIn("archives", full_payload)
            self.assertIn("body", full_payload["tasks"][0])
            self.assertEqual(full_payload["tasks"][0]["goal"], "Create DB-backed workflow state")

            event = self.run_cli(
                db_path,
                "hook-event",
                "--event",
                "PreToolUse",
                "--mode",
                "observe",
                "--tool",
                "Bash",
                "--json",
                input_text='{"tool_input": {"command": "taplctl status --json"}}',
            )
            self.assertEqual(event.returncode, 0, event.stderr)
            event_status = self.run_cli(db_path, "status", "--json", "--include-events")
            self.assertEqual(event_status.returncode, 0, event_status.stderr)
            event_payload = json.loads(event_status.stdout)
            self.assertEqual(event_payload["recent_events"][0]["event_type"], "PreToolUse")
            self.assertNotIn("archives", event_payload)
            self.assertNotIn("payload_json", event_payload["recent_events"][0])

            status_text = self.run_cli(db_path, "status")
            self.assertEqual(status_text.returncode, 0, status_text.stderr)
            self.assertIn("active run:", status_text.stdout)
            self.assertIn("incomplete tasks: 1", status_text.stdout)
            self.assertNotEqual(status_text.stdout.strip(), "no archives")

            search = self.run_cli(db_path, "search", "workflow", "--json")
            results = json.loads(search.stdout)["results"]
            self.assertEqual(results[0]["stable_id"], "TASK-001")

            detail = self.run_cli(db_path, "item", "show", "--id", str(results[0]["id"]), "--json")
            self.assertEqual(detail.returncode, 0, detail.stderr)
            item = json.loads(detail.stdout)["item"]
            self.assertEqual(item["stable_id"], "TASK-001")
            self.assertEqual(item["goal"], "Create DB-backed workflow state")

    def test_config_defaults_when_file_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cfg = tapl_config.load(Path(tmp) / "missing.toml")
            self.assertFalse(cfg.exists)
            self.assertEqual(cfg.search.mode, "hybrid")
            self.assertEqual(cfg.search.hybrid_semantic_ratio, 0.65)
            self.assertEqual(cfg.search.hybrid_bm25_ratio, 0.35)
            self.assertTrue(cfg.plan_task_execute.use_level_subagent)
            self.assertEqual(cfg.plan_task_execute.level_subagent_aggressiveness, "auto")
            self.assertEqual(cfg.plan_task_execute.plan_detail, "detailed")
            self.assertEqual(cfg.plan_task_execute.task_granularity, "granular")

    def test_config_search_mode_is_applied(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "tapl.db"
            config_path = Path(tmp) / "tapl.toml"
            config_path.write_text(
                """
[search]
mode = "word"
hybrid_semantic_ratio = 0.25

[plan-task-execute]
use-level-subagent = false
level-subagent-aggressiveness = "minimal"
plan-detail = "less-detailed"
task-granularity = "less-granular"
""",
                encoding="utf-8",
            )

            self.run_cli(db_path, "init", "--json")
            self.run_cli(
                db_path,
                "task",
                "upsert",
                "--id",
                "TASK-001",
                "--title",
                "Word mode search",
                "--status",
                "Completed",
                "--goal",
                "Use substring lookup",
            )

            status = self.run_cli(db_path, "--config", str(config_path), "status", "--json")
            status_payload = json.loads(status.stdout)
            self.assertEqual(status_payload["config"]["search"]["mode"], "word")
            self.assertFalse(status_payload["config"]["plan_task_execute"]["use_level_subagent"])

            search = self.run_cli(db_path, "--config", str(config_path), "search", "substring", "--json")
            search_payload = json.loads(search.stdout)
            self.assertEqual(search_payload["mode"], "word")
            self.assertEqual(search_payload["results"][0]["search_source"], "word")

    def test_config_rejects_unknown_search_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "tapl.toml"
            config_path.write_text('[search]\nmode = "unknown"\n', encoding="utf-8")
            with self.assertRaises(ValueError):
                tapl_config.load(config_path)

    def test_task_upsert_enforces_forced_level_subagent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "tapl.db"
            config_path = Path(tmp) / "tapl.toml"
            config_path.write_text(
                """
[plan-task-execute]
use_level_subagent = true
level_subagent_aggressiveness = "force"
""",
                encoding="utf-8",
            )

            missing = self.run_cli(
                db_path,
                "--config",
                str(config_path),
                "task",
                "upsert",
                "--id",
                "TASK-001",
                "--title",
                "Needs routing",
                "--status",
                "In Progress",
                "--json",
            )
            self.assertEqual(missing.returncode, 1)
            missing_payload = json.loads(missing.stdout)
            self.assertEqual(
                missing_payload["plan_task_execute"]["errors"][0]["code"],
                "missing_required_subagent",
            )

            invalid = self.run_cli(
                db_path,
                "--config",
                str(config_path),
                "task",
                "upsert",
                "--id",
                "TASK-001",
                "--title",
                "Bad routing",
                "--status",
                "In Progress",
                "--required-subagent",
                "@unknown-worker",
                "--json",
            )
            self.assertEqual(invalid.returncode, 1)
            invalid_payload = json.loads(invalid.stdout)
            self.assertEqual(
                invalid_payload["plan_task_execute"]["errors"][0]["code"],
                "invalid_required_subagent",
            )

    def test_validate_reports_plan_task_execute_issues(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "tapl.db"
            config_path = Path(tmp) / "tapl.toml"
            config_path.write_text(
                """
[plan-task-execute]
use_level_subagent = true
level_subagent_aggressiveness = "force"
""",
                encoding="utf-8",
            )
            self.run_cli(
                db_path,
                "task",
                "upsert",
                "--id",
                "TASK-001",
                "--title",
                "Existing unrouted task",
                "--status",
                "In Progress",
            )

            validated = self.run_cli(db_path, "--config", str(config_path), "validate", "--json")
            self.assertEqual(validated.returncode, 1)
            payload = json.loads(validated.stdout)
            self.assertFalse(payload["ok"])
            self.assertEqual(payload["plan_task_execute"]["errors"][0]["code"], "missing_required_subagent")
            self.assertIn("@senior-worker", payload["plan_task_execute"]["guidance"]["allowed_level_subagents"])

    def test_context_command_reports_lifecycle_packet(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "tapl.db"
            self.run_cli(db_path, "init", "--json")

            context = self.run_cli(db_path, "context", "--event", "SessionStart", "--json")
            self.assertEqual(context.returncode, 0, context.stderr)
            payload = json.loads(context.stdout)
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["event"], "SessionStart")
            self.assertIn("SessionStart is bootstrap context", "\n".join(payload["instructions"]))
            self.assertIn("Assume `taplctl` is installed as a user-global command", "\n".join(payload["instructions"]))
            self.assertIn("never `$taplctl`", "\n".join(payload["instructions"]))
            self.assertIn("configure hooks with `taplctl install user`", "\n".join(payload["instructions"]))
            self.assertIn("keep workflow DB/config in the current repo workspace", "\n".join(payload["instructions"]))
            self.assertIn("taplctl status --json", "\n".join(payload["instructions"]))
            self.assertIn("taplctl search '<query>' --json", "\n".join(payload["instructions"]))
            self.assertIn("@senior-worker", "\n".join(payload["instructions"]))
            self.assertEqual(payload["next_actions"], [])

            prompt_context = self.run_cli(db_path, "context", "--event", "UserPromptSubmit", "--json")
            prompt_payload = json.loads(prompt_context.stdout)
            self.assertIn("quote every argument", "\n".join(prompt_payload["instructions"]))
            self.assertIn("never `--status In Progress`", "\n".join(prompt_payload["instructions"]))
            self.assertIn("Do not use level names such as `level2`", "\n".join(prompt_payload["instructions"]))
            self.assertIn("Create an active workflow run", "\n".join(prompt_payload["next_actions"]))

            self.run_cli(
                db_path,
                "task",
                "upsert",
                "--id",
                "TASK-001",
                "--title",
                "Context task",
                "--status",
                "In Progress",
                "--required-subagent",
                "@senior-worker",
            )
            active_context = self.run_cli(db_path, "context", "--event", "SessionStart", "--json")
            active_payload = json.loads(active_context.stdout)
            self.assertEqual(len(active_payload["next_actions"]), 1)
            self.assertIn("resume or update the incomplete task state", active_payload["next_actions"][0])

            active_prompt_context = self.run_cli(db_path, "context", "--event", "UserPromptSubmit", "--json")
            active_prompt_payload = json.loads(active_prompt_context.stdout)
            self.assertIn("Create or update plan state", "\n".join(active_prompt_payload["next_actions"]))

            text = self.run_cli(db_path, "context", "--event", "SessionStart")
            self.assertEqual(text.returncode, 0, text.stderr)
            self.assertIn("tapl context:", text.stdout)
            self.assertIn("SessionStart is bootstrap context", text.stdout)
            self.assertIn("Assume `taplctl` is installed as a user-global command", text.stdout)
            self.assertIn("never `$taplctl`", text.stdout)
            self.assertIn("configure hooks with `taplctl install user`", text.stdout)
            self.assertIn("keep workflow DB/config in the current repo workspace", text.stdout)

            prompt_text = self.run_cli(db_path, "context", "--event", "UserPromptSubmit")
            self.assertEqual(prompt_text.returncode, 0, prompt_text.stderr)
            self.assertIn("tapl context:", prompt_text.stdout)
            self.assertIn("quote every argument", prompt_text.stdout)
            self.assertIn("never `--status In Progress`", prompt_text.stdout)

    def test_install_user_writes_taplctl_hooks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            codex_home = base / "home" / ".codex"
            db_path = base / "tapl.db"

            installed = self.run_cli(
                db_path,
                "install",
                "user",
                "--codex-home",
                str(codex_home),
                "--taplctl-command",
                "taplctl",
                "--json",
            )
            self.assertEqual(installed.returncode, 0, installed.stderr)
            payload = json.loads(installed.stdout)
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["install"], "user")

            hooks = json.loads((codex_home / "hooks.json").read_text(encoding="utf-8"))
            prompt_hook = hooks["hooks"]["UserPromptSubmit"][0]["hooks"][0]["command"]
            self.assertEqual(prompt_hook, "taplctl hook-event --event UserPromptSubmit --mode observe")
            self.assertNotIn("tapl_hook.py", json.dumps(hooks))
            self.assertTrue((codex_home / "config.toml").exists())
            self.assertTrue((codex_home / "agents" / "senior-worker.toml").exists())

    def test_install_user_merges_existing_codex_config_without_overwriting_user_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            codex_home = base / "home" / ".codex"
            codex_home.mkdir(parents=True)
            (codex_home / "config.toml").write_text(
                """
# user codex preferences
model = "gpt-5"
approval_policy = "on-request"

[features]
multi_agent = false
""".lstrip(),
                encoding="utf-8",
            )
            db_path = base / "tapl.db"

            installed = self.run_cli(
                db_path,
                "install",
                "user",
                "--codex-home",
                str(codex_home),
                "--taplctl-command",
                "taplctl",
                "--json",
            )
            self.assertEqual(installed.returncode, 0, installed.stderr)
            payload = json.loads(installed.stdout)
            config_result = next(file for file in payload["files"] if file["path"].endswith("config.toml"))
            self.assertEqual(config_result["action"], "merged")

            config_text = (codex_home / "config.toml").read_text(encoding="utf-8")
            self.assertIn("# user codex preferences", config_text)
            parsed = tomllib.loads(config_text)
            self.assertEqual(parsed["model"], "gpt-5")
            self.assertEqual(parsed["approval_policy"], "on-request")
            self.assertEqual(parsed["model_reasoning_effort"], "xhigh")
            self.assertEqual(parsed["personality"], "pragmatic")
            self.assertFalse(parsed["features"]["multi_agent"])
            self.assertTrue(parsed["features"]["default_mode_request_user_input"])

    def test_install_user_force_applies_managed_codex_config_values_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            codex_home = base / "home" / ".codex"
            codex_home.mkdir(parents=True)
            (codex_home / "config.toml").write_text(
                """
model = "gpt-5"
approval_policy = "on-request"

[features]
multi_agent = false
experimental = true
""".lstrip(),
                encoding="utf-8",
            )
            db_path = base / "tapl.db"

            installed = self.run_cli(
                db_path,
                "install",
                "user",
                "--codex-home",
                str(codex_home),
                "--taplctl-command",
                "taplctl",
                "--force",
                "--json",
            )
            self.assertEqual(installed.returncode, 0, installed.stderr)
            payload = json.loads(installed.stdout)
            config_result = next(file for file in payload["files"] if file["path"].endswith("config.toml"))
            self.assertEqual(config_result["action"], "updated")

            parsed = tomllib.loads((codex_home / "config.toml").read_text(encoding="utf-8"))
            self.assertEqual(parsed["model"], "gpt-5.5")
            self.assertEqual(parsed["approval_policy"], "on-request")
            self.assertEqual(parsed["model_reasoning_effort"], "xhigh")
            self.assertEqual(parsed["personality"], "pragmatic")
            self.assertTrue(parsed["features"]["multi_agent"])
            self.assertTrue(parsed["features"]["experimental"])
            self.assertTrue(parsed["features"]["default_mode_request_user_input"])

    def test_install_repo_writes_hooks_config_and_db(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            repo = base / "repo"
            repo.mkdir()
            (repo / "README.md").write_text("# repo\n", encoding="utf-8")
            (repo / ".codex").mkdir()
            (repo / ".codex" / "hooks.json").write_text(
                json.dumps(
                    {
                        "hooks": {
                            "PreToolUse": [
                                {
                                    "hooks": [
                                        {
                                            "type": "command",
                                            "command": "echo keep",
                                        }
                                    ]
                                }
                            ]
                        }
                    }
                ),
                encoding="utf-8",
            )
            db_path = base / "tapl.db"

            installed = self.run_cli(
                db_path,
                "install",
                "repo",
                "--repo",
                str(repo),
                "--taplctl-command",
                "/opt/tapl/bin/taplctl",
                "--json",
            )
            self.assertEqual(installed.returncode, 0, installed.stderr)
            payload = json.loads(installed.stdout)
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["install"], "repo")

            hooks = json.loads((repo / ".codex" / "hooks.json").read_text(encoding="utf-8"))
            pre_tool_commands = [hook["command"] for entry in hooks["hooks"]["PreToolUse"] for hook in entry["hooks"]]
            self.assertIn("echo keep", pre_tool_commands)
            self.assertIn(
                "/opt/tapl/bin/taplctl hook-event --event PreToolUse --mode observe",
                pre_tool_commands,
            )
            self.assertTrue((repo / ".codex" / "config.toml").exists())
            self.assertTrue((repo / ".codex" / "agents" / "senior-worker.toml").exists())
            self.assertIn("task_granularity", (repo / ".tapl" / "config.toml").read_text())
            self.assertFalse((repo / ".codex" / "tapl" / "tapl.toml").exists())
            self.assertTrue((repo / ".tapl" / "tapl.db").exists())

    def test_hook_enforce_blocks_without_tasks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "tapl.db"
            self.run_cli(db_path, "init", "--json")
            blocked = self.run_cli(
                db_path,
                "hook-event",
                "--event",
                "PreToolUse",
                "--mode",
                "enforce",
                "--tool",
                "apply_patch",
                input_text="{}",
            )
            self.assertEqual(blocked.returncode, 2)
            self.assertIn("durable edit requires", blocked.stderr)
            self.assertIn("Assume `taplctl` is installed as a user-global command", blocked.stderr)
            self.assertIn("keep workflow DB/config in the current repo workspace", blocked.stderr)

            self.run_cli(
                db_path,
                "task",
                "upsert",
                "--id",
                "TASK-001",
                "--title",
                "Approved edit",
                "--status",
                "In Progress",
            )
            allowed = self.run_cli(
                db_path,
                "hook-event",
                "--event",
                "PreToolUse",
                "--mode",
                "enforce",
                "--tool",
                "apply_patch",
                input_text="{}",
            )
            self.assertEqual(allowed.returncode, 0, allowed.stderr)

    def test_hook_enforce_blocks_config_validation_errors(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "tapl.db"
            config_path = Path(tmp) / "tapl.toml"
            config_path.write_text(
                """
[plan-task-execute]
use_level_subagent = true
level_subagent_aggressiveness = "force"
""",
                encoding="utf-8",
            )
            self.run_cli(
                db_path,
                "task",
                "upsert",
                "--id",
                "TASK-001",
                "--title",
                "Existing unrouted task",
                "--status",
                "In Progress",
            )

            blocked = self.run_cli(
                db_path,
                "--config",
                str(config_path),
                "hook-event",
                "--event",
                "PreToolUse",
                "--mode",
                "enforce",
                "--tool",
                "apply_patch",
                input_text="{}",
            )
            self.assertEqual(blocked.returncode, 2)
            self.assertIn("missing_required_subagent", blocked.stderr)
            self.assertIn("Set --required-subagent", blocked.stderr)

    def test_hook_observe_warns_for_very_granular_single_task(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "tapl.db"
            config_path = Path(tmp) / "tapl.toml"
            config_path.write_text(
                """
[plan-task-execute]
task_granularity = "very_granular"
""",
                encoding="utf-8",
            )
            self.run_cli(
                db_path,
                "plan",
                "upsert",
                "--id",
                "SPEC-001",
                "--title",
                "Config validation",
                "--summary",
                "Add validation, connect CLI and hook, update tests and docs.",
            )
            self.run_cli(
                db_path,
                "task",
                "upsert",
                "--id",
                "TASK-001",
                "--title",
                "All work in one task",
                "--status",
                "In Progress",
                "--required-subagent",
                "@senior-worker",
            )

            warned = self.run_cli(
                db_path,
                "--config",
                str(config_path),
                "hook-event",
                "--event",
                "PreToolUse",
                "--mode",
                "observe",
                "--tool",
                "apply_patch",
                input_text="{}",
            )
            self.assertEqual(warned.returncode, 0, warned.stderr)
            self.assertIn("task_granularity_too_coarse", warned.stdout)
            self.assertIn("Split", warned.stdout)

    def test_hook_user_prompt_outputs_lifecycle_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "tapl.db"
            event = self.run_cli(
                db_path,
                "hook-event",
                "--event",
                "UserPromptSubmit",
                "--mode",
                "observe",
                input_text='{"prompt": "Implement lifecycle context"}',
            )
            self.assertEqual(event.returncode, 0, event.stderr)
            self.assertIn("tapl context:", event.stdout)
            self.assertIn("taplctl status --json", event.stdout)
            self.assertIn("taplctl search '<query>' --json", event.stdout)
            self.assertIn("Do not use level names such as `level2`", event.stdout)
            self.assertIn("Create or update plan state", event.stdout)

            event_json = self.run_cli(
                db_path,
                "hook-event",
                "--event",
                "UserPromptSubmit",
                "--mode",
                "observe",
                "--json",
                input_text='{"prompt": "Implement lifecycle context"}',
            )
            self.assertEqual(event_json.returncode, 0, event_json.stderr)
            payload = json.loads(event_json.stdout)
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["context"]["prompt_summary"], "Implement lifecycle context")

    def test_stop_hook_observe_is_silent_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "tapl.db"
            prompt = self.run_cli(
                db_path,
                "hook-event",
                "--event",
                "UserPromptSubmit",
                "--mode",
                "observe",
                input_text='{"prompt": "Create a run without plans"}',
            )
            self.assertEqual(prompt.returncode, 0, prompt.stderr)

            stopped = self.run_cli(
                db_path,
                "hook-event",
                "--event",
                "Stop",
                "--mode",
                "observe",
                input_text="{}",
            )
            self.assertEqual(stopped.returncode, 0, stopped.stderr)
            self.assertEqual(stopped.stdout, "")
            self.assertEqual(stopped.stderr, "")

            stopped_json = self.run_cli(
                db_path,
                "hook-event",
                "--event",
                "Stop",
                "--mode",
                "observe",
                "--json",
                input_text="{}",
            )
            self.assertEqual(stopped_json.returncode, 0, stopped_json.stderr)
            payload = json.loads(stopped_json.stdout)
            self.assertTrue(payload["ok"])
            self.assertIn("missing_plan", payload["message"])

    def test_stop_hook_auto_archives_completed_plan_task_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "tapl.db"
            prompt = self.run_cli(
                db_path,
                "hook-event",
                "--event",
                "UserPromptSubmit",
                "--mode",
                "observe",
                "--json",
                input_text='{"prompt": "Ship auto archive"}',
            )
            self.assertEqual(prompt.returncode, 0, prompt.stderr)

            plan = self.run_cli(
                db_path,
                "plan",
                "upsert",
                "--id",
                "SPEC-001",
                "--title",
                "Auto archive completed run",
                "--summary",
                "Plan a completed request from planning to task execution and archive it automatically.",
                "--body",
                "Requirements trace, execution order, risks, and validation are documented so the completed run is eligible for Stop hook archive.",
                "--json",
            )
            self.assertEqual(plan.returncode, 0, plan.stderr)

            task = self.run_cli(
                db_path,
                "task",
                "upsert",
                "--id",
                "TASK-001",
                "--title",
                "Complete implementation",
                "--status",
                "Completed",
                "--spec-id",
                "SPEC-001",
                "--goal",
                "Finish the requested implementation.",
                "--verification",
                "Stop hook archives the run.",
                "--result",
                "Implementation and verification are complete.",
                "--json",
            )
            self.assertEqual(task.returncode, 0, task.stderr)

            stopped = self.run_cli(
                db_path,
                "hook-event",
                "--event",
                "Stop",
                "--mode",
                "observe",
                "--json",
                input_text="{}",
            )
            self.assertEqual(stopped.returncode, 0, stopped.stderr)
            payload = json.loads(stopped.stdout)
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["archive"]["slug"], "ship-auto-archive")
            self.assertIn("archived completed run", payload["message"])

            status = self.run_cli(db_path, "status", "--json")
            self.assertEqual(status.returncode, 0, status.stderr)
            status_payload = json.loads(status.stdout)
            self.assertIsNone(status_payload["active_run"])
            self.assertEqual(status_payload["counts"]["archives"], 1)
            self.assertNotIn("archives", status_payload)

            archives = self.run_cli(db_path, "archive", "list", "--json")
            self.assertEqual(archives.returncode, 0, archives.stderr)
            archives_payload = json.loads(archives.stdout)
            self.assertEqual(len(archives_payload["archives"]), 1)
            self.assertEqual(archives_payload["archives"][0]["slug"], "ship-auto-archive")

            detail = self.run_cli(db_path, "archive", "show", "--id", "ship-auto-archive", "--json")
            self.assertEqual(detail.returncode, 0, detail.stderr)
            detail_payload = json.loads(detail.stdout)
            self.assertEqual(detail_payload["archive"]["request_summary"], "Ship auto archive")
            self.assertEqual(
                [(item["kind"], item["stable_id"], item["archived"]) for item in detail_payload["items"]],
                [("plan", "SPEC-001", 1), ("task", "TASK-001", 1)],
            )
            self.assertEqual(detail_payload["events"][-1]["event_type"], "Stop")

    def test_hook_event_uses_payload_cwd_for_repo_db(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            workspace = base / "workspace"
            outside = base / "outside"
            workspace.mkdir()
            outside.mkdir()

            event = self.run_taplctl(
                "hook-event",
                "--event",
                "UserPromptSubmit",
                "--mode",
                "observe",
                "--json",
                input_text=json.dumps({"cwd": str(workspace), "prompt": "Global install workspace"}),
                cwd=outside,
            )
            self.assertEqual(event.returncode, 0, event.stderr)
            payload = json.loads(event.stdout)
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["context"]["prompt_summary"], "Global install workspace")
            self.assertEqual(
                payload["context"]["active_run"]["request_summary"],
                "Global install workspace",
            )
            self.assertTrue((workspace / ".tapl" / "tapl.db").exists())
            self.assertFalse((outside / ".tapl").exists())

    def test_archive_show_includes_items_and_events(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "tapl.db"
            self.run_cli(db_path, "init", "--json")

            plan = self.run_cli(
                db_path,
                "plan",
                "upsert",
                "--id",
                "SPEC-001",
                "--title",
                "Archive detail",
                "--summary",
                "Show archived workflow records",
                "--json",
            )
            self.assertEqual(plan.returncode, 0, plan.stderr)

            task = self.run_cli(
                db_path,
                "task",
                "upsert",
                "--id",
                "TASK-001",
                "--title",
                "Render archive detail",
                "--status",
                "Completed",
                "--goal",
                "Show plan and task history",
                "--json",
            )
            self.assertEqual(task.returncode, 0, task.stderr)

            finding = self.run_cli(
                db_path,
                "finding",
                "add",
                "--title",
                "Archive source",
                "--finding",
                "Archived items remain tied to their workflow run.",
                "--json",
            )
            self.assertEqual(finding.returncode, 0, finding.stderr)

            event = self.run_cli(
                db_path,
                "hook-event",
                "--event",
                "PreToolUse",
                "--mode",
                "observe",
                "--tool",
                "Bash",
                input_text='{"tool_name": "Bash"}',
            )
            self.assertEqual(event.returncode, 0, event.stderr)

            archive = self.run_cli(
                db_path,
                "archive",
                "create",
                "--slug",
                "archive-detail",
                "--summary",
                "Archived detail test",
                "--json",
            )
            self.assertEqual(archive.returncode, 0, archive.stderr)
            archive_id = json.loads(archive.stdout)["archive"]["id"]

            detail = self.run_cli(db_path, "archive", "show", "--id", archive_id, "--json")
            self.assertEqual(detail.returncode, 0, detail.stderr)
            payload = json.loads(detail.stdout)
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["archive"]["slug"], "archive-detail")
            self.assertEqual(
                [(item["kind"], item["stable_id"]) for item in payload["items"]],
                [("plan", "SPEC-001"), ("task", "TASK-001"), ("finding", "FINDING-001")],
            )
            self.assertEqual(payload["events"][0]["event_type"], "PreToolUse")

    def test_import_md_restructures_legacy_archive_as_tapl_records(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "tapl.db"
            workflow = Path(tmp) / ".agent-workflow"
            archive = workflow / "archive" / "20260605-144508-vscode-workflow-viewer"
            archive.mkdir(parents=True)
            (archive / "summary.md").write_text(
                """# Archive Summary

## Original Request
VSCode workflow viewer를 만든다.

## Selected Plan
VSCode 확장을 추가하고 markdown preview를 연결한다.
""",
                encoding="utf-8",
            )
            (archive / "plan.md").write_text(
                """# Plan

## Specs
- SPEC-001: VSCode extension scaffold를 추가한다. (REQ-001)
  - Goal: 확장 기본 구조를 만든다.
  - Validation: `npm run compile`
""",
                encoding="utf-8",
            )
            (archive / "task.md").write_text(
                """# Tasks

## Phase 1: Extension scaffold

- TASK-001 [Completed]: VSCode extension 기본 구조 추가 (SPEC-001)
  - Action: TypeScript extension scaffold를 추가한다.
  - Required Subagent: [@senior-worker](subagent://senior-worker)
  - Verification: `npm run compile`
  - Result: 확장 기본 구조를 추가했다.

## Phase 2: Verification

- TASK-002 [Completed]: Compile 확인 (SPEC-001)
  - Action: compile command를 실행한다.
  - Verification: `npm run compile`
  - Result: 컴파일이 성공했다.
""",
                encoding="utf-8",
            )
            (archive / "finding.md").write_text(
                """# Findings

- FINDING-001: VSCode compile 확인 (REQ-001, SPEC-001)
  - Source: npm
  - Finding: compile command가 성공한다.
  - Impact: import 후 검증 근거로 남긴다.
""",
                encoding="utf-8",
            )

            imported = self.run_cli(db_path, "import-md", "--path", str(workflow), "--json")
            self.assertEqual(imported.returncode, 0, imported.stderr)
            imported_payload = json.loads(imported.stdout)
            self.assertEqual(imported_payload["filesystem_created_archives"], 1)
            self.assertEqual(imported_payload["filesystem_created_plan_items"], 1)
            self.assertEqual(imported_payload["filesystem_created_task_items"], 2)
            self.assertEqual(imported_payload["filesystem_created_finding_items"], 1)

            detail = self.run_cli(
                db_path,
                "archive",
                "show",
                "--id",
                "2026-06-05T144508Z-vscode-workflow-viewer",
                "--json",
            )
            self.assertEqual(detail.returncode, 0, detail.stderr)
            payload = json.loads(detail.stdout)
            self.assertEqual(payload["archive"]["request_summary"], "VSCode workflow viewer를 만든다.")
            self.assertEqual(
                [(item["kind"], item["stable_id"]) for item in payload["items"]],
                [("plan", "SPEC-001"), ("task", "TASK-001"), ("task", "TASK-002"), ("finding", "FINDING-001")],
            )
            task = next(item for item in payload["items"] if item["stable_id"] == "TASK-001")
            self.assertEqual(task["status"], "Completed")
            self.assertEqual(task["spec_id"], "SPEC-001")
            self.assertEqual(task["required_subagent"], "@senior-worker")
            self.assertNotIn("Phase 2", task["result"])

    def test_import_md_migrates_existing_raw_legacy_imports(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "tapl.db"
            init = self.run_cli(db_path, "init", "--json")
            self.assertEqual(init.returncode, 0, init.stderr)

            conn = sqlite3.connect(db_path)
            now = "2026-06-15T07:41:03+00:00"
            run_id = "legacy-run"
            conn.execute(
                """
                INSERT INTO workflow_runs(id, slug, status, request_summary, created_at, updated_at, archived_at)
                VALUES(?, 'legacy-markdown-import', 'archived', '', ?, ?, ?)
                """,
                (run_id, now, now, now),
            )
            conn.execute(
                "INSERT INTO archives(id, run_id, slug, summary, created_at) VALUES(?, ?, ?, ?, ?)",
                (
                    "2026-06-15T074103Z-legacy-markdown-import",
                    run_id,
                    "legacy-markdown-import",
                    "old raw import",
                    now,
                ),
            )
            legacy_files = {
                "archive/20260605-144508-vscode-workflow-viewer/summary.md": """# Archive Summary

## Original Request
Legacy archive를 tapl 구조로 옮긴다.

## Selected Plan
계획과 작업을 tapl item으로 재구성한다.
""",
                "archive/20260605-144508-vscode-workflow-viewer/plan.md": """# Plan

## Specs
- SPEC-001: Legacy plan 변환 (REQ-001)
  - Goal: plan file을 SPEC item으로 만든다.
""",
                "archive/20260605-144508-vscode-workflow-viewer/task.md": """# Tasks

- TASK-001 [Completed]: Legacy task 변환 (SPEC-001)
  - Goal: task row를 만든다.
  - Action: task.md 항목을 파싱한다.
  - Verification: archive show
  - Result: 완료
""",
            }
            for index, (source, text) in enumerate(legacy_files.items(), start=1):
                conn.execute(
                    """
                    INSERT INTO items(
                      run_id, stable_id, kind, title, body, raw_text, status, source, archived, created_at, updated_at
                    )
                    VALUES(?, ?, ?, ?, ?, ?, NULL, ?, 1, ?, ?)
                    """,
                    (
                        run_id,
                        f"MD-{index:012d}",
                        Path(source).stem,
                        Path(source).name,
                        text,
                        text,
                        source,
                        now,
                        now,
                    ),
                )
            conn.commit()
            conn.close()

            migrated = self.run_cli(
                db_path,
                "import-md",
                "--path",
                str(Path(tmp) / "missing-agent-workflow"),
                "--migrate-existing",
                "--json",
            )
            self.assertEqual(migrated.returncode, 0, migrated.stderr)
            migrated_payload = json.loads(migrated.stdout)
            self.assertEqual(migrated_payload["existing_legacy_runs"], 1)
            self.assertEqual(migrated_payload["existing_removed_legacy_runs"], 1)
            self.assertEqual(migrated_payload["existing_created_archives"], 1)
            self.assertEqual(migrated_payload["existing_created_task_items"], 1)

            detail = self.run_cli(
                db_path,
                "archive",
                "show",
                "--id",
                "2026-06-05T144508Z-vscode-workflow-viewer",
                "--json",
            )
            self.assertEqual(detail.returncode, 0, detail.stderr)
            payload = json.loads(detail.stdout)
            self.assertEqual(
                [(item["kind"], item["stable_id"]) for item in payload["items"]],
                [("plan", "SPEC-001"), ("task", "TASK-001")],
            )

            conn = sqlite3.connect(db_path)
            md_items = conn.execute("SELECT COUNT(*) FROM items WHERE stable_id LIKE 'MD-%'").fetchone()[0]
            old_runs = conn.execute(
                "SELECT COUNT(*) FROM workflow_runs WHERE slug = 'legacy-markdown-import'"
            ).fetchone()[0]
            conn.close()
            self.assertEqual(md_items, 0)
            self.assertEqual(old_runs, 0)


if __name__ == "__main__":
    unittest.main()
