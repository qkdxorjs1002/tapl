from __future__ import annotations

import contextlib
import io
import argparse
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import tomllib
import types
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from taplctl import __version__, cli as tapl_cli, config as tapl_config, install as tapl_install


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
        env_overrides: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        env = self.tapl_env()
        if env_overrides:
            env.update(env_overrides)
        return subprocess.run(
            [sys.executable, "-m", "taplctl", *args],
            input=input_text,
            text=True,
            capture_output=True,
            check=False,
            env=env,
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
                "set",
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

    def test_task_set_allows_partial_update_for_existing_task(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "tapl.db"
            created = self.run_cli(
                db_path,
                "task",
                "set",
                "--id",
                "TASK-001",
                "--title",
                "Implement partial updates",
                "--status",
                "In Progress",
                "--spec-id",
                "SPEC-001",
                "--goal",
                "Preserve unchanged fields",
                "--action",
                "Merge supplied task fields with stored values",
                "--required-subagent",
                "@senior-worker",
                "--verification",
                "Run focused tests",
                "--json",
            )
            self.assertEqual(created.returncode, 0, created.stderr)

            updated = self.run_cli(
                db_path,
                "task",
                "set",
                "--id",
                "TASK-001",
                "--status",
                "Completed",
                "--result",
                "Focused tests passed",
                "--json",
            )
            self.assertEqual(updated.returncode, 0, updated.stderr)

            status = self.run_cli(db_path, "status", "--json", "--full")
            self.assertEqual(status.returncode, 0, status.stderr)
            task = json.loads(status.stdout)["tasks"][0]
            self.assertEqual(task["title"], "Implement partial updates")
            self.assertEqual(task["status"], "Completed")
            self.assertEqual(task["spec_id"], "SPEC-001")
            self.assertEqual(task["goal"], "Preserve unchanged fields")
            self.assertEqual(task["action"], "Merge supplied task fields with stored values")
            self.assertEqual(task["required_subagent"], "@senior-worker")
            self.assertEqual(task["verification"], "Run focused tests")
            self.assertEqual(task["result"], "Focused tests passed")

    def test_task_set_requires_title_and_status_for_new_task(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "tapl.db"
            missing = self.run_cli(
                db_path,
                "task",
                "set",
                "--id",
                "TASK-001",
                "--json",
            )
            self.assertEqual(missing.returncode, 1)
            payload = json.loads(missing.stdout)
            self.assertFalse(payload["ok"])
            self.assertEqual(payload["plan_task_execute"]["errors"][0]["code"], "task_create_missing_fields")
            self.assertIn("--title", payload["error"])
            self.assertIn("--status", payload["error"])

    def test_plan_and_task_ids_require_numeric_suffixes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "tapl.db"

            bad_plan = self.run_cli(
                db_path,
                "plan",
                "set",
                "--id",
                "SPEC-MEANINGS",
                "--title",
                "Bad plan id",
                "--json",
            )
            self.assertEqual(bad_plan.returncode, 1)
            bad_plan_payload = json.loads(bad_plan.stdout)
            self.assertEqual(bad_plan_payload["plan_task_execute"]["errors"][0]["code"], "invalid_plan_id")

            good_plan = self.run_cli(
                db_path,
                "plan",
                "set",
                "--id",
                "PLAN-001",
                "--title",
                "Good plan id",
                "--summary",
                "REQ-001: Use numeric stable ids. Validation: CLI rejects word suffixes.",
                "--json",
            )
            self.assertEqual(good_plan.returncode, 0, good_plan.stderr)

            bad_task = self.run_cli(
                db_path,
                "task",
                "set",
                "--id",
                "TASK-MEANINGS",
                "--title",
                "Bad task id",
                "--status",
                "Pending",
                "--spec-id",
                "PLAN-001",
                "--json",
            )
            self.assertEqual(bad_task.returncode, 1)
            bad_task_payload = json.loads(bad_task.stdout)
            self.assertEqual(bad_task_payload["plan_task_execute"]["errors"][0]["code"], "invalid_task_id")

            bad_spec = self.run_cli(
                db_path,
                "task",
                "set",
                "--id",
                "TASK-001",
                "--title",
                "Bad spec id",
                "--status",
                "Pending",
                "--spec-id",
                "SPEC-MEANINGS",
                "--json",
            )
            self.assertEqual(bad_spec.returncode, 1)
            bad_spec_payload = json.loads(bad_spec.stdout)
            self.assertEqual(bad_spec_payload["plan_task_execute"]["errors"][0]["code"], "invalid_task_spec_id")

    def test_load_model_suppresses_loading_weights_progress(self) -> None:
        from taplctl import embeddings

        class FakeSentenceTransformer:
            def __init__(self, model_name: str, **kwargs: object) -> None:
                self.model_name = model_name
                self.kwargs = kwargs
                sys.stderr.write("\rLoading weights: 100%|fake|\n")
                sys.stderr.write("model loaded\n")

        fake_module = types.ModuleType("sentence_transformers")
        fake_module.SentenceTransformer = FakeSentenceTransformer
        original_module = sys.modules.get("sentence_transformers")
        sys.modules["sentence_transformers"] = fake_module
        stderr = io.StringIO()
        try:
            with contextlib.redirect_stderr(stderr):
                model = embeddings.load_model(prefer_local=True)
        finally:
            if original_module is None:
                sys.modules.pop("sentence_transformers", None)
            else:
                sys.modules["sentence_transformers"] = original_module

        self.assertIsInstance(model, FakeSentenceTransformer)
        self.assertEqual(model.kwargs["local_files_only"], True)
        self.assertNotIn("Loading weights", stderr.getvalue())
        self.assertIn("model loaded", stderr.getvalue())

        fd_progress = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "import os\n"
                    "from taplctl.embeddings import suppress_model_load_progress\n"
                    "with suppress_model_load_progress():\n"
                    "    os.write(2, b'\\rLoading weights: 100%|fake|\\n')\n"
                    "print('done')\n"
                ),
            ],
            text=True,
            capture_output=True,
            check=False,
            env=self.tapl_env(),
        )
        self.assertEqual(fd_progress.returncode, 0, fd_progress.stderr)
        self.assertNotIn("Loading weights", fd_progress.stderr)
        self.assertEqual(fd_progress.stdout.strip(), "done")

    def test_config_defaults_when_file_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cfg = tapl_config.load(Path(tmp) / "missing.toml")
            self.assertFalse(cfg.exists)
            self.assertEqual(cfg.search.mode, "hybrid")
            self.assertEqual(cfg.search.max_results, 7)
            self.assertEqual(cfg.search.hybrid_semantic_ratio, 0.65)
            self.assertEqual(cfg.search.hybrid_bm25_ratio, 0.35)
            self.assertEqual(cfg.search.semantic_provider, "auto")
            self.assertEqual(cfg.search.searchd_model_idle_timeout_seconds, 1800)
            self.assertTrue(cfg.plan_task_execute.use_level_subagent)
            self.assertEqual(cfg.plan_task_execute.level_subagent_aggressiveness, "auto")
            self.assertEqual(cfg.plan_task_execute.plan_detail, "detailed")
            self.assertEqual(cfg.plan_task_execute.planning_approval_level, "auto")
            self.assertEqual(cfg.plan_task_execute.task_granularity, "granular")
            self.assertTrue(cfg.plan_task_execute.require_execution_approval)

    def test_approval_cli_records_status_and_list(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "tapl.db"
            self.run_cli(
                db_path,
                "hook-event",
                "--event",
                "UserPromptSubmit",
                "--mode",
                "observe",
                "--json",
                input_text='{"prompt": "Approve execution"}',
            )

            missing = self.run_cli(db_path, "approval", "status", "--json")
            self.assertEqual(missing.returncode, 0, missing.stderr)
            missing_payload = json.loads(missing.stdout)
            self.assertEqual(missing_payload["approval"]["state"], "missing")
            self.assertFalse(missing_payload["approval"]["approved"])

            recorded = self.run_cli(
                db_path,
                "approval",
                "set",
                "--decision",
                "approved",
                "--prompt",
                "Execute prepared TASK-001",
                "--json",
            )
            self.assertEqual(recorded.returncode, 0, recorded.stderr)
            recorded_payload = json.loads(recorded.stdout)
            self.assertEqual(recorded_payload["approval"]["decision"], "approved")

            status = self.run_cli(db_path, "approval", "status", "--json")
            status_payload = json.loads(status.stdout)
            self.assertEqual(status_payload["approval"]["state"], "approved")
            self.assertTrue(status_payload["approval"]["approved"])

            workflow_status = self.run_cli(db_path, "status", "--json")
            workflow_payload = json.loads(workflow_status.stdout)
            self.assertEqual(workflow_payload["approvals"]["execution"]["state"], "approved")

            listed = self.run_cli(db_path, "approval", "list", "--json")
            listed_payload = json.loads(listed.stdout)
            self.assertEqual(len(listed_payload["approvals"]), 1)
            self.assertEqual(listed_payload["approvals"][0]["prompt"], "Execute prepared TASK-001")

    def test_config_loads_user_global_when_repo_config_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            repo = base / "repo"
            home = base / "home"
            repo.mkdir()
            user_config = home / ".tapl" / "config.toml"
            user_config.parent.mkdir(parents=True)
            user_config.write_text(
                """
[search]
mode = "bm25"

[plan-task-execute]
plan-detail = "minimal"
planning-approval-level = "more"
""",
                encoding="utf-8",
            )

            cfg = tapl_config.load(start=repo, home=home)
            self.assertTrue(cfg.exists)
            self.assertEqual(cfg.path, str(user_config))
            self.assertEqual(cfg.search.mode, "bm25")
            self.assertEqual(cfg.plan_task_execute.plan_detail, "minimal")
            self.assertEqual(cfg.plan_task_execute.planning_approval_level, "more")

    def test_config_prefers_repo_config_over_user_global(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            repo = base / "repo"
            home = base / "home"
            repo_config = repo / ".tapl" / "config.toml"
            user_config = home / ".tapl" / "config.toml"
            repo_config.parent.mkdir(parents=True)
            user_config.parent.mkdir(parents=True)
            repo_config.write_text('[search]\nmode = "word"\n', encoding="utf-8")
            user_config.write_text('[search]\nmode = "bm25"\n', encoding="utf-8")

            cfg = tapl_config.load(start=repo, home=home)
            self.assertTrue(cfg.exists)
            self.assertEqual(cfg.path, str(repo_config.resolve()))
            self.assertEqual(cfg.search.mode, "word")

    def test_config_search_mode_is_applied(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "tapl.db"
            config_path = Path(tmp) / "tapl.toml"
            config_path.write_text(
                """
[search]
mode = "word"
max_results = 2
hybrid_semantic_ratio = 0.25
semantic-provider = "daemon"
idle-timeout-seconds = 0

[plan-task-execute]
use-level-subagent = false
level-subagent-aggressiveness = "minimal"
plan-detail = "less-detailed"
planning-approval-level = "less"
task-granularity = "less-granular"
""",
                encoding="utf-8",
            )

            self.run_cli(db_path, "init", "--json")
            self.run_cli(
                db_path,
                "task",
                "set",
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
            self.assertEqual(status_payload["config"]["search"]["semantic_provider"], "daemon")
            self.assertEqual(status_payload["config"]["search"]["searchd_model_idle_timeout_seconds"], 0)
            self.assertFalse(status_payload["config"]["plan_task_execute"]["use_level_subagent"])
            self.assertEqual(status_payload["config"]["plan_task_execute"]["planning_approval_level"], "less")

            search = self.run_cli(db_path, "--config", str(config_path), "search", "substring", "--json")
            search_payload = json.loads(search.stdout)
            self.assertEqual(search_payload["mode"], "word")
            self.assertEqual(search_payload["search_config"]["max_results"], 2)
            self.assertEqual(search_payload["results"][0]["search_source"], "word")

    def test_search_limit_uses_default_config_and_cli_override(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            db_path = base / "tapl.db"
            config_path = base / "tapl.toml"
            config_path.write_text(
                """
[search]
mode = "word"
max_results = 3
""",
                encoding="utf-8",
            )

            self.run_cli(db_path, "init", "--json")
            for index in range(9):
                created = self.run_cli(
                    db_path,
                    "task",
                    "set",
                    "--id",
                    f"TASK-{index + 1:03d}",
                    "--title",
                    f"Needle task {index}",
                    "--status",
                    "Completed",
                    "--goal",
                    "shared needle search target",
                    "--json",
                )
                self.assertEqual(created.returncode, 0, created.stderr)

            default_config = self.run_cli(
                db_path,
                "--config",
                str(base / "missing.toml"),
                "search",
                "needle",
                "--json",
            )
            default_payload = json.loads(default_config.stdout)
            self.assertEqual(default_payload["limit"], 7)
            self.assertEqual(len(default_payload["results"]), 7)

            configured = self.run_cli(db_path, "--config", str(config_path), "search", "needle", "--json")
            configured_payload = json.loads(configured.stdout)
            self.assertEqual(configured_payload["limit"], 3)
            self.assertEqual(len(configured_payload["results"]), 3)

            overridden = self.run_cli(
                db_path,
                "--config",
                str(config_path),
                "search",
                "needle",
                "--limit",
                "5",
                "--json",
            )
            overridden_payload = json.loads(overridden.stdout)
            self.assertEqual(overridden_payload["limit"], 5)
            self.assertEqual(len(overridden_payload["results"]), 5)

    def test_config_rejects_non_positive_search_max_results(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "tapl.toml"
            config_path.write_text("[search]\nmax_results = 0\n", encoding="utf-8")

            with self.assertRaises(ValueError):
                tapl_config.load(config_path)

    def test_config_rejects_unknown_planning_approval_level(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "tapl.toml"
            config_path.write_text(
                "[plan-task-execute]\nplanning_approval_level = \"always\"\n",
                encoding="utf-8",
            )

            with self.assertRaises(ValueError):
                tapl_config.load(config_path)

    def test_config_can_require_execution_approval(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "tapl.db"
            config_path = Path(tmp) / "tapl.toml"
            config_path.write_text(
                """
[plan-task-execute]
require_execution_approval = true
""",
                encoding="utf-8",
            )
            self.run_cli(
                db_path,
                "plan",
                "set",
                "--id",
                "SPEC-001",
                "--title",
                "Needs execution approval",
                "--summary",
                "REQ-001: Validate execution approval before durable edits. Validation: taplctl validate.",
            )
            self.run_cli(
                db_path,
                "task",
                "set",
                "--id",
                "TASK-001",
                "--title",
                "Executable task",
                "--status",
                "In Progress",
                "--spec-id",
                "SPEC-001",
                "--goal",
                "Execute approved work",
                "--action",
                "Edit files after approval",
                "--required-subagent",
                "@senior-worker",
                "--verification",
                "taplctl validate",
            )

            missing = self.run_cli(db_path, "--config", str(config_path), "validate", "--json")
            self.assertEqual(missing.returncode, 1)
            missing_payload = json.loads(missing.stdout)
            self.assertEqual(
                missing_payload["plan_task_execute"]["errors"][0]["code"],
                "execution_approval_missing",
            )

            approved = self.run_cli(
                db_path,
                "approval",
                "set",
                "--decision",
                "approved",
                "--prompt",
                "Execute TASK-001",
                "--json",
            )
            self.assertEqual(approved.returncode, 0, approved.stderr)

            validated = self.run_cli(db_path, "--config", str(config_path), "validate", "--json")
            self.assertEqual(validated.returncode, 0, validated.stdout)

    def test_config_rejects_unknown_search_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "tapl.toml"
            config_path.write_text('[search]\nmode = "unknown"\n', encoding="utf-8")
            with self.assertRaises(ValueError):
                tapl_config.load(config_path)

    def test_config_rejects_unknown_searchd_settings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "tapl.toml"
            config_path.write_text('[search]\nsemantic_provider = "remote"\n', encoding="utf-8")
            with self.assertRaises(ValueError):
                tapl_config.load(config_path)

            config_path.write_text("[search]\nsearchd_model_idle_timeout_seconds = -1\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                tapl_config.load(config_path)

    def test_config_ignores_removed_searchd_settings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "tapl.toml"
            config_path.write_text(
                """
[search]
searchd_missing = "explode"
searchd_socket_path = "~/ignored.sock"
searchd_connect_timeout_ms = 1
searchd_start_timeout_ms = 1
""",
                encoding="utf-8",
            )

            cfg = tapl_config.load(config_path)
            self.assertEqual(cfg.search.semantic_provider, "auto")
            self.assertFalse(hasattr(cfg.search, "searchd_missing"))
            self.assertFalse(hasattr(cfg.search, "searchd_socket_path"))
            self.assertFalse(hasattr(cfg.search, "searchd_connect_timeout_ms"))
            self.assertFalse(hasattr(cfg.search, "searchd_start_timeout_ms"))

    def test_query_embedding_blob_provider_fallback(self) -> None:
        from taplctl import embeddings

        original_embed = embeddings.searchd.embed_query
        original_local = embeddings.local_query_embedding_blob
        try:
            def fake_embed(query: str, settings: tapl_config.SearchConfig) -> bytes:
                raise embeddings.searchd.SearchdUnavailable("down")

            embeddings.searchd.embed_query = fake_embed
            embeddings.local_query_embedding_blob = lambda query: b"local"

            auto = tapl_config.SearchConfig(semantic_provider="auto")
            self.assertEqual(embeddings.query_embedding_blob("query", auto), b"local")

            daemon = tapl_config.SearchConfig(semantic_provider="daemon")
            self.assertEqual(embeddings.query_embedding_blob("query", daemon), b"local")

            def fake_error(query: str, settings: tapl_config.SearchConfig) -> bytes:
                raise embeddings.searchd.SearchdError("bad response")

            embeddings.searchd.embed_query = fake_error
            self.assertEqual(embeddings.query_embedding_blob("query", auto), b"local")
            self.assertIsNone(embeddings.query_embedding_blob("query", daemon))
        finally:
            embeddings.searchd.embed_query = original_embed
            embeddings.local_query_embedding_blob = original_local

    def test_searchd_handle_request_embed_and_ping(self) -> None:
        from taplctl import searchd

        class FakeModelState:
            model_loaded = False
            model_idle_timeout_seconds = 30

            def unload_if_idle(self) -> bool:
                return False

            def status_payload(self, *, started_at: float) -> dict[str, object]:
                return {
                    "ok": True,
                    "pid": 1,
                    "model": "fake",
                    "dimension": 384,
                    "uptime_seconds": 0.0,
                    "model_loaded": self.model_loaded,
                    "model_idle_timeout_seconds": self.model_idle_timeout_seconds,
                }

            def embed(self, text: str) -> dict[str, object]:
                self.text = text
                self.model_loaded = True
                return {"dimension": 3, "embedding_b64": "YWJj"}

        model_state = FakeModelState()

        ping, stop = searchd.handle_request(
            {"op": "ping"},
            model_state=model_state,
            started_at=0.0,
        )
        self.assertTrue(ping["ok"])
        self.assertFalse(stop)
        self.assertFalse(ping["model_loaded"])
        self.assertEqual(ping["model_idle_timeout_seconds"], 30)

        embed, stop = searchd.handle_request(
            {"op": "embed", "text": "hello"},
            model_state=model_state,
            started_at=0.0,
        )
        self.assertTrue(embed["ok"])
        self.assertFalse(stop)
        self.assertEqual(embed["dimension"], 3)
        self.assertEqual(embed["embedding_b64"], "YWJj")
        self.assertTrue(embed["model_loaded"])

    def test_searchd_model_state_lazy_loads_and_unloads_model(self) -> None:
        from taplctl import searchd

        current_time = 0.0
        loaded = 0

        class FakeArray:
            shape = (3,)

            def tobytes(self) -> bytes:
                return b"abc"

        class FakeNumpy:
            float32 = object()

            def asarray(self, vector: object, dtype: object) -> FakeArray:
                return FakeArray()

        class FakeModel:
            def get_sentence_embedding_dimension(self) -> int:
                return 3

            def encode(self, texts: list[str], *, normalize_embeddings: bool) -> list[list[float]]:
                self.texts = texts
                self.normalize_embeddings = normalize_embeddings
                return [[1.0, 2.0, 3.0]]

        def now() -> float:
            return current_time

        def load_model() -> FakeModel:
            nonlocal loaded
            loaded += 1
            return FakeModel()

        state = searchd.ModelState(
            model_idle_timeout_seconds=10,
            now=now,
            model_loader=load_model,
            numpy_loader=FakeNumpy,
        )

        self.assertFalse(state.status_payload(started_at=0.0)["model_loaded"])
        self.assertEqual(loaded, 0)

        first = state.embed("hello")
        self.assertEqual(first["dimension"], 3)
        self.assertEqual(loaded, 1)
        self.assertTrue(state.model_loaded)

        current_time = 9.0
        self.assertFalse(state.unload_if_idle())
        self.assertTrue(state.model_loaded)

        current_time = 10.0
        self.assertTrue(state.unload_if_idle())
        self.assertFalse(state.model_loaded)

    def test_searchd_status_reports_missing_daemon(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "tapl.db"
            status = self.run_cli(
                db_path,
                "searchd",
                "status",
                "--socket",
                str(Path(tmp) / "missing.sock"),
                "--json",
            )
            self.assertEqual(status.returncode, 0, status.stderr)
            payload = json.loads(status.stdout)
            self.assertFalse(payload["ok"])
            self.assertFalse(payload["running"])
            self.assertIn("missing.sock", payload["socket_path"])

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
                "set",
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
                "set",
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
                "set",
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
            self.assertNotIn("guidance", payload["plan_task_execute"])

    def test_validate_warns_for_sparse_plan_and_task_content(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "tapl.db"
            self.run_cli(
                db_path,
                "plan",
                "set",
                "--id",
                "SPEC-001",
                "--title",
                "Sparse plan",
                "--summary",
                "Implement the requested behavior by updating the relevant files and checking the result carefully.",
            )
            self.run_cli(
                db_path,
                "task",
                "set",
                "--id",
                "TASK-001",
                "--title",
                "Sparse task",
                "--status",
                "In Progress",
            )
            self.run_cli(
                db_path,
                "approval",
                "set",
                "--decision",
                "approved",
                "--prompt",
                "Execute sparse task validation test",
            )

            validated = self.run_cli(db_path, "validate", "--json")
            self.assertEqual(validated.returncode, 0, validated.stderr)
            payload = json.loads(validated.stdout)
            codes = {item["code"] for item in payload["plan_task_execute"]["warnings"]}
            self.assertIn("plan_content_missing_guidance", codes)
            self.assertIn("task_content_missing_fields", codes)
            self.assertNotIn("guidance", payload["plan_task_execute"])

    def test_validate_warns_for_non_sequential_task_execution(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "tapl.db"
            self.run_cli(
                db_path,
                "plan",
                "set",
                "--id",
                "SPEC-001",
                "--title",
                "Sequential execution plan",
                "--summary",
                "REQ-001: execute tasks one at a time in order; Validation: validate task sequence warnings.",
            )
            for task_id in ("TASK-001", "TASK-002"):
                self.run_cli(
                    db_path,
                    "task",
                    "set",
                    "--id",
                    task_id,
                    "--title",
                    f"{task_id} implementation",
                    "--status",
                    "In Progress",
                    "--spec-id",
                    "SPEC-001",
                    "--goal",
                    f"Complete {task_id}",
                    "--action",
                    f"Run {task_id}",
                    "--required-subagent",
                    "@senior-worker",
                    "--verification",
                    f"Check {task_id}",
                )
            self.run_cli(
                db_path,
                "approval",
                "set",
                "--decision",
                "approved",
                "--prompt",
                "Execute sequential task warning test",
            )

            multiple = self.run_cli(db_path, "validate", "--json")
            self.assertEqual(multiple.returncode, 0, multiple.stderr)
            multiple_payload = json.loads(multiple.stdout)
            multiple_codes = {item["code"] for item in multiple_payload["plan_task_execute"]["warnings"]}
            self.assertIn("multiple_tasks_in_progress", multiple_codes)

            self.run_cli(
                db_path,
                "task",
                "set",
                "--id",
                "TASK-001",
                "--title",
                "TASK-001 implementation",
                "--status",
                "Pending",
                "--spec-id",
                "SPEC-001",
                "--goal",
                "Complete TASK-001",
                "--action",
                "Run TASK-001",
                "--required-subagent",
                "@senior-worker",
                "--verification",
                "Check TASK-001",
            )

            out_of_order = self.run_cli(db_path, "validate", "--json")
            self.assertEqual(out_of_order.returncode, 0, out_of_order.stderr)
            out_of_order_payload = json.loads(out_of_order.stdout)
            warnings = out_of_order_payload["plan_task_execute"]["warnings"]
            out_of_order_codes = {item["code"] for item in warnings}
            self.assertIn("task_started_out_of_order", out_of_order_codes)
            self.assertIn(
                "TASK-002 is In Progress while earlier task(s) remain incomplete: TASK-001.",
                "\n".join(item["message"] for item in warnings),
            )

    def test_context_command_reports_lifecycle_packet(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "tapl.db"
            self.run_cli(db_path, "init", "--json")

            context = self.run_cli(db_path, "context", "--event", "SessionStart", "--json")
            self.assertEqual(context.returncode, 0, context.stderr)
            payload = json.loads(context.stdout)
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["event"], "SessionStart")
            self.assertIn("SessionStart is bootstrap only", "\n".join(payload["instructions"]))
            self.assertIn("literal global `taplctl`", "\n".join(payload["instructions"]))
            self.assertIn("workflow DB/config repo-local", "\n".join(payload["instructions"]))
            self.assertIn("taplctl status --json", "\n".join(payload["instructions"]))
            self.assertIn("taplctl search '<query>' --json", "\n".join(payload["instructions"]))
            self.assertIn("search relevant prior work", "\n".join(payload["workflow_guidance"]))
            self.assertEqual(payload["next_actions"], [])

            status = self.run_cli(db_path, "status", "--json")
            self.assertEqual(status.returncode, 0, status.stderr)
            status_payload = json.loads(status.stdout)
            self.assertNotIn("guidance", status_payload["plan_task_execute"])

            prompt_context = self.run_cli(db_path, "context", "--event", "UserPromptSubmit", "--json")
            prompt_payload = json.loads(prompt_context.stdout)
            prompt_instructions = "\n".join(prompt_payload["instructions"])
            self.assertIn("taplctl <command> <subcommand> --help", prompt_instructions)
            prompt_guidance = "\n".join(prompt_payload["workflow_guidance"])
            self.assertIn("plan-based task design", prompt_guidance)
            self.assertIn("Phase order", prompt_guidance)
            self.assertIn("stored plan", prompt_guidance)
            self.assertIn("Execute planned tasks one at a time", prompt_guidance)
            self.assertIn("requirements trace", prompt_guidance)
            self.assertIn("request_user_input", prompt_guidance)
            self.assertIn("1-3 concise options", prompt_guidance)
            self.assertIn("meaningful implementation", prompt_guidance)
            self.assertIn("Agent contract", prompt_guidance)
            self.assertIn("spawn it to execute that task", prompt_guidance)
            self.assertIn("@senior-worker", prompt_guidance)
            self.assertIn("set execution approval", prompt_guidance)
            self.assertIn("taplctl finding add", prompt_guidance)
            self.assertIn("Markdown form", prompt_guidance)
            self.assertNotIn("quote every argument", prompt_instructions)
            self.assertNotIn("Do not use level names such as `level2`", prompt_guidance)
            self.assertIn("Create an active workflow run", "\n".join(prompt_payload["next_actions"]))

            less_planning_config = Path(tmp) / "less-planning.toml"
            less_planning_config.write_text(
                "[plan-task-execute]\nplanning-approval-level = \"less\"\n",
                encoding="utf-8",
            )
            less_planning_context = self.run_cli(
                db_path,
                "--config",
                str(less_planning_config),
                "context",
                "--event",
                "UserPromptSubmit",
                "--json",
            )
            less_planning_payload = json.loads(less_planning_context.stdout)
            self.assertIn(
                "blocking or high-risk planning choices",
                "\n".join(less_planning_payload["workflow_guidance"]),
            )

            more_planning_config = Path(tmp) / "more-planning.toml"
            more_planning_config.write_text(
                "[plan-task-execute]\nplanning-approval-level = \"more\"\n",
                encoding="utf-8",
            )
            more_planning_context = self.run_cli(
                db_path,
                "--config",
                str(more_planning_config),
                "context",
                "--event",
                "UserPromptSubmit",
                "--json",
            )
            more_planning_payload = json.loads(more_planning_context.stdout)
            self.assertIn(
                "use request_user_input Tool early",
                "\n".join(more_planning_payload["workflow_guidance"]),
            )

            no_subagent_config = Path(tmp) / "no-subagent.toml"
            no_subagent_config.write_text(
                "[plan-task-execute]\nuse-level-subagent = false\n",
                encoding="utf-8",
            )
            no_subagent_context = self.run_cli(
                db_path,
                "--config",
                str(no_subagent_config),
                "context",
                "--event",
                "UserPromptSubmit",
                "--json",
            )
            no_subagent_payload = json.loads(no_subagent_context.stdout)
            no_subagent_guidance = "\n".join(no_subagent_payload["workflow_guidance"])
            self.assertNotIn("spawn it to execute that task", no_subagent_guidance)
            self.assertNotIn("required_subagent", no_subagent_guidance)

            self.run_cli(
                db_path,
                "task",
                "set",
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
            active_actions = active_prompt_payload["next_actions"]
            self.assertIn("Create or update plan state", "\n".join(active_prompt_payload["next_actions"]))
            self.assertIn("before task design", "\n".join(active_prompt_payload["next_actions"]))
            self.assertIn("ask whether to finish", "\n".join(active_prompt_payload["next_actions"]))
            self.assertIn("finish, combine, defer/archive, or discard", "\n".join(active_prompt_payload["next_actions"]))
            self.assertIn("Continue only TASK-001", "\n".join(active_prompt_payload["next_actions"]))
            self.assertIn("spawn @senior-worker and assign only this task", "\n".join(active_prompt_payload["next_actions"]))
            approval_index = next(index for index, action in enumerate(active_actions) if "approval set" in action)
            continue_index = next(index for index, action in enumerate(active_actions) if "Continue only TASK-001" in action)
            self.assertLess(approval_index, continue_index)

            active_no_subagent_context = self.run_cli(
                db_path,
                "--config",
                str(no_subagent_config),
                "context",
                "--event",
                "UserPromptSubmit",
                "--json",
            )
            active_no_subagent_payload = json.loads(active_no_subagent_context.stdout)
            self.assertNotIn(
                "spawn @senior-worker",
                "\n".join(active_no_subagent_payload["next_actions"]),
            )

            text = self.run_cli(db_path, "context", "--event", "SessionStart")
            self.assertEqual(text.returncode, 0, text.stderr)
            self.assertIn("tapl context:", text.stdout)
            self.assertIn("SessionStart is bootstrap only", text.stdout)
            self.assertIn("literal global `taplctl`", text.stdout)
            self.assertIn("workflow DB/config repo-local", text.stdout)

            stop_context = self.run_cli(db_path, "context", "--event", "Stop", "--json")
            stop_payload = json.loads(stop_context.stdout)
            stop_instructions = "\n".join(stop_payload["instructions"])
            self.assertIn("taplctl status --json", stop_instructions)
            self.assertIn("set result", "\n".join(stop_payload["workflow_guidance"]))
            self.assertNotIn("Completion reports should", stop_instructions)
            self.assertNotIn("Archive summaries should", stop_instructions)

            prompt_text = self.run_cli(db_path, "context", "--event", "UserPromptSubmit")
            self.assertEqual(prompt_text.returncode, 0, prompt_text.stderr)
            self.assertIn("tapl context:", prompt_text.stdout)
            self.assertIn("Flow: search relevant prior work", prompt_text.stdout)
            self.assertIn("plan-based task design", prompt_text.stdout)
            self.assertIn("Execute planned tasks one at a time", prompt_text.stdout)
            self.assertIn("spawn it to execute that task", prompt_text.stdout)
            self.assertIn("taplctl finding add", prompt_text.stdout)
            self.assertIn("taplctl <command> <subcommand> --help", prompt_text.stdout)
            self.assertIn("Markdown form", prompt_text.stdout)
            self.assertIn("Use numeric stable ids only", prompt_text.stdout)
            self.assertNotIn("quote every argument", prompt_text.stdout)

    def test_command_help_exposes_field_guidance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "tapl.db"

            root_help = self.run_cli(db_path, "--help")
            self.assertEqual(root_help.returncode, 0, root_help.stderr)
            self.assertIn("taplctl <command> <subcommand> --help", root_help.stdout)
            self.assertIn("taplctl validate --json", root_help.stdout)
            self.assertIn("Phase order", root_help.stdout)
            self.assertIn("taplctl plan set", root_help.stdout)
            self.assertIn("Execute planned tasks one at a time", root_help.stdout)
            self.assertIn("Markdown form", root_help.stdout)

            run_help = self.run_cli(db_path, "run", "set", "--help")
            self.assertEqual(run_help.returncode, 0, run_help.stderr)
            self.assertIn("Set active run fields", run_help.stdout)
            self.assertIn("--summary", run_help.stdout)
            self.assertIn("--result", run_help.stdout)

            plan_help = self.run_cli(db_path, "plan", "set", "--help")
            self.assertEqual(plan_help.returncode, 0, plan_help.stderr)
            self.assertIn("Plan writing rules", plan_help.stdout)
            self.assertIn("Plan records should include objective", plan_help.stdout)
            self.assertIn("before task records", plan_help.stdout)
            self.assertIn("Markdown form", plan_help.stdout)
            self.assertIn("Use numeric stable ids only", plan_help.stdout)
            self.assertIn("PLAN-001", plan_help.stdout)
            self.assertIn("--body", plan_help.stdout)

            task_help = self.run_cli(db_path, "task", "set", "--help")
            self.assertEqual(task_help.returncode, 0, task_help.stderr)
            self.assertIn("Task writing rules", task_help.stdout)
            self.assertIn("Use numeric stable ids only", task_help.stdout)
            self.assertIn("Existing task updates are partial", task_help.stdout)
            self.assertIn("New task creation requires --title and --status", task_help.stdout)
            self.assertIn("--status 'In Progress'", task_help.stdout)
            self.assertIn("Execute planned tasks one at a time", task_help.stdout)
            self.assertIn("When level subagent routing is enabled", task_help.stdout)
            self.assertIn("spawn the task's required_subagent", task_help.stdout)
            self.assertIn("@senior-worker", task_help.stdout)
            self.assertIn("source plan/spec exists", task_help.stdout)
            self.assertIn("Markdown form", task_help.stdout)
            self.assertIn("--blocker/--next-action", task_help.stdout)

            approval_help = self.run_cli(db_path, "approval", "set", "--help")
            self.assertEqual(approval_help.returncode, 0, approval_help.stderr)
            self.assertIn("Approval writing rules", approval_help.stdout)
            self.assertIn("before starting or", approval_help.stdout)
            self.assertIn("continuing task execution", approval_help.stdout)
            self.assertIn("--decision", approval_help.stdout)
            self.assertIn("--prompt", approval_help.stdout)

            finding_help = self.run_cli(db_path, "finding", "add", "--help")
            self.assertEqual(finding_help.returncode, 0, finding_help.stderr)
            self.assertIn("Add a finding", finding_help.stdout)
            self.assertIn("Why the finding matters", finding_help.stdout)
            self.assertIn("Finding writing rules", finding_help.stdout)
            self.assertIn("Markdown form", finding_help.stdout)

            hook_help = self.run_cli(db_path, "hook-event", "--help")
            self.assertEqual(hook_help.returncode, 0, hook_help.stderr)
            self.assertIn("Hook handling mode", hook_help.stdout)
            self.assertIn("Print JSON output", hook_help.stdout)

    def test_parser_actions_have_help_text(self) -> None:
        parser = tapl_cli.build_parser()
        missing: list[str] = []

        def visit(current: argparse.ArgumentParser) -> None:
            for action in current._actions:
                if isinstance(action, (argparse._HelpAction, argparse._VersionAction)):
                    continue
                if isinstance(action, argparse._SubParsersAction):
                    for choice_action in action._choices_actions:
                        if not choice_action.help:
                            missing.append(f"{current.prog} {choice_action.dest}")
                    for subparser in action.choices.values():
                        visit(subparser)
                    continue
                if not action.help:
                    name = ", ".join(action.option_strings) or action.dest
                    missing.append(f"{current.prog}: {name}")

        visit(parser)
        self.assertEqual(missing, [])

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
            self.assertNotIn("SessionStart", hooks["hooks"])
            self.assertNotIn("tapl_hook.py", json.dumps(hooks))
            self.assertTrue((codex_home / "config.toml").exists())
            self.assertEqual(payload["tapl_config"], str(base / "home" / ".tapl" / "config.toml"))
            self.assertIn(
                "task_granularity",
                (base / "home" / ".tapl" / "config.toml").read_text(encoding="utf-8"),
            )
            self.assertIn(
                "planning_approval_level",
                (base / "home" / ".tapl" / "config.toml").read_text(encoding="utf-8"),
            )
            self.assertEqual(
                (base / "home" / ".tapl" / "version").read_text(encoding="utf-8").strip(),
                __version__,
            )
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
                            "SessionStart": [
                                {
                                    "matcher": "startup|resume|clear|compact",
                                    "hooks": [
                                        {
                                            "type": "command",
                                            "command": "echo keep session",
                                        },
                                        {
                                            "type": "command",
                                            "command": "taplctl hook-event --event SessionStart --mode observe",
                                        },
                                    ],
                                }
                            ],
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
            session_commands = [
                hook["command"]
                for entry in hooks["hooks"]["SessionStart"]
                for hook in entry["hooks"]
            ]
            self.assertEqual(session_commands, ["echo keep session"])
            pre_tool_commands = [hook["command"] for entry in hooks["hooks"]["PreToolUse"] for hook in entry["hooks"]]
            self.assertIn("echo keep", pre_tool_commands)
            self.assertIn(
                "/opt/tapl/bin/taplctl hook-event --event PreToolUse --mode observe",
                pre_tool_commands,
            )
            self.assertTrue((repo / ".codex" / "config.toml").exists())
            self.assertTrue((repo / ".codex" / "agents" / "senior-worker.toml").exists())
            self.assertIn("task_granularity", (repo / ".tapl" / "config.toml").read_text())
            self.assertIn("planning_approval_level", (repo / ".tapl" / "config.toml").read_text())
            self.assertEqual(
                (repo / ".tapl" / "version").read_text(encoding="utf-8").strip(),
                __version__,
            )
            self.assertFalse((repo / ".codex" / "tapl" / "tapl.toml").exists())
            self.assertTrue((repo / ".tapl" / "tapl.db").exists())

    def test_auto_install_refreshes_stale_user_and_repo_scopes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            home = base / "home"
            repo = base / "repo"
            repo.mkdir()
            (home / ".tapl").mkdir(parents=True)
            (repo / ".tapl").mkdir(parents=True)
            (home / ".tapl" / "version").write_text("0.0.0\n", encoding="utf-8")
            (repo / ".tapl" / "version").write_text("0.0.0\n", encoding="utf-8")

            results = tapl_install.auto_install_if_needed(
                start=repo,
                home=home,
                taplctl_command="taplctl",
            )

            self.assertEqual([result["install"] for result in results], ["user", "repo"])
            self.assertEqual(
                (home / ".tapl" / "version").read_text(encoding="utf-8").strip(),
                __version__,
            )
            self.assertEqual(
                (repo / ".tapl" / "version").read_text(encoding="utf-8").strip(),
                __version__,
            )
            self.assertTrue((home / ".codex" / "hooks.json").exists())
            self.assertTrue((repo / ".codex" / "hooks.json").exists())

    def test_auto_install_does_not_treat_repo_db_as_install_marker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            home = base / "home"
            repo = base / "repo"
            repo.mkdir()
            (repo / ".tapl").mkdir()
            (repo / ".tapl" / "tapl.db").write_bytes(b"not a marker")

            results = tapl_install.auto_install_if_needed(start=repo, home=home)

            self.assertEqual(results, [])
            self.assertFalse((repo / ".codex").exists())
            self.assertFalse((repo / ".tapl" / "version").exists())

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
            self.assertIn("literal global `taplctl`", blocked.stderr)
            self.assertIn("workflow DB/config repo-local", blocked.stderr)

            self.run_cli(
                db_path,
                "task",
                "set",
                "--id",
                "TASK-001",
                "--title",
                "Approved edit",
                "--status",
                "In Progress",
            )
            approval_blocked = self.run_cli(
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
            self.assertEqual(approval_blocked.returncode, 2)
            self.assertIn("execution_approval_missing", approval_blocked.stderr)

            approved = self.run_cli(
                db_path,
                "approval",
                "set",
                "--decision",
                "approved",
                "--prompt",
                "Execute approved edit",
                "--json",
            )
            self.assertEqual(approved.returncode, 0, approved.stderr)

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
                "set",
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
                "set",
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
                "set",
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
            self.assertIn("taplctl <command> <subcommand> --help", event.stdout)
            self.assertNotIn("Do not use level names such as `level2`", event.stdout)
            self.assertIn("Flow: search relevant prior work", event.stdout)
            self.assertIn("plan-based task design", event.stdout)
            self.assertIn("Phase order", event.stdout)
            self.assertIn("Search: before planning non-trivial work", event.stdout)
            self.assertIn("Plan:", event.stdout)
            self.assertIn("taplctl finding add", event.stdout)
            self.assertIn("Markdown form", event.stdout)
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
            self.assertIn("workflow_guidance", payload["context"])

    def test_post_tool_use_external_search_outputs_finding_guidance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "tapl.db"
            event = self.run_cli(
                db_path,
                "hook-event",
                "--event",
                "PostToolUse",
                "--mode",
                "observe",
                "--tool",
                "web.run",
                input_text='{"search_query": [{"q": "tapl workflow"}]}',
            )
            self.assertEqual(event.returncode, 0, event.stderr)
            self.assertIn("taplctl finding add", event.stdout)
            self.assertIn("decision-relevant", event.stdout)
            self.assertIn("Markdown form", event.stdout)

    def test_session_start_hook_does_not_create_active_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "tapl.db"
            session = self.run_cli(
                db_path,
                "hook-event",
                "--event",
                "SessionStart",
                "--mode",
                "observe",
                "--json",
                input_text="{}",
            )
            self.assertEqual(session.returncode, 0, session.stderr)
            session_payload = json.loads(session.stdout)
            self.assertTrue(session_payload["ok"])
            self.assertFalse(session_payload["context"]["active_run"]["present"])

            status = self.run_cli(db_path, "status", "--json")
            self.assertEqual(status.returncode, 0, status.stderr)
            status_payload = json.loads(status.stdout)
            self.assertIsNone(status_payload["active_run"])

            prompt = self.run_cli(
                db_path,
                "hook-event",
                "--event",
                "UserPromptSubmit",
                "--mode",
                "observe",
                "--json",
                input_text='{"prompt": "Start real work"}',
            )
            self.assertEqual(prompt.returncode, 0, prompt.stderr)
            prompt_payload = json.loads(prompt.stdout)
            self.assertTrue(prompt_payload["context"]["active_run"]["present"])
            self.assertEqual(
                prompt_payload["context"]["active_run"]["request_summary"],
                "New request",
            )
            self.assertIn(
                "taplctl run set --summary",
                "\n".join(prompt_payload["context"]["next_actions"]),
            )

            summary = self.run_cli(
                db_path,
                "run",
                "set",
                "--summary",
                "Start real work",
                "--json",
            )
            self.assertEqual(summary.returncode, 0, summary.stderr)
            summary_payload = json.loads(summary.stdout)
            self.assertEqual(
                summary_payload["active_run"]["request_summary"],
                "Start real work",
            )

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

            summary = self.run_cli(
                db_path,
                "run",
                "set",
                "--summary",
                "Ship auto archive",
                "--json",
            )
            self.assertEqual(summary.returncode, 0, summary.stderr)

            plan = self.run_cli(
                db_path,
                "plan",
                "set",
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
                "set",
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
            self.assertIn("Original request: Ship auto archive", archives_payload["archives"][0]["summary"])
            self.assertIn("Selected plan: SPEC-001 Auto archive completed run", archives_payload["archives"][0]["summary"])
            self.assertIn("Completed tasks: TASK-001 Complete implementation", archives_payload["archives"][0]["summary"])
            self.assertIn("Verification: Stop hook archives the run.", archives_payload["archives"][0]["summary"])
            self.assertIn("Remaining work: None", archives_payload["archives"][0]["summary"])

            detail = self.run_cli(db_path, "archive", "show", "--id", "ship-auto-archive", "--json")
            self.assertEqual(detail.returncode, 0, detail.stderr)
            detail_payload = json.loads(detail.stdout)
            self.assertEqual(detail_payload["archive"]["request_summary"], "Ship auto archive")
            self.assertEqual(
                [(item["kind"], item["stable_id"], item["archived"]) for item in detail_payload["items"]],
                [("plan", "SPEC-001", 1), ("task", "TASK-001", 1)],
            )
            self.assertEqual(detail_payload["events"][-1]["event_type"], "Stop")

    def test_stop_hook_auto_archives_simple_result_run_without_items(self) -> None:
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
                input_text='{"prompt": "Answer a simple question"}',
            )
            self.assertEqual(prompt.returncode, 0, prompt.stderr)

            summary = self.run_cli(
                db_path,
                "run",
                "set",
                "--summary",
                "Answer a simple question",
                "--json",
            )
            self.assertEqual(summary.returncode, 0, summary.stderr)

            result = self.run_cli(
                db_path,
                "run",
                "set",
                "--result",
                "Answered directly without creating plan or task records.",
                "--json",
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            result_payload = json.loads(result.stdout)
            self.assertEqual(
                result_payload["active_run"]["result_summary"],
                "Answered directly without creating plan or task records.",
            )

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
            self.assertEqual(payload["archive"]["slug"], "answer-a-simple-question")
            self.assertIn("archived completed run", payload["message"])

            archives = self.run_cli(db_path, "archive", "list", "--json")
            self.assertEqual(archives.returncode, 0, archives.stderr)
            archives_payload = json.loads(archives.stdout)
            self.assertEqual(len(archives_payload["archives"]), 1)
            self.assertIn("Original request: Answer a simple question", archives_payload["archives"][0]["summary"])
            self.assertIn(
                "Result: Answered directly without creating plan or task records.",
                archives_payload["archives"][0]["summary"],
            )
            self.assertIn("Selected plan: None", archives_payload["archives"][0]["summary"])
            self.assertIn("Completed tasks: None", archives_payload["archives"][0]["summary"])

            detail = self.run_cli(db_path, "archive", "show", "--id", "answer-a-simple-question", "--json")
            self.assertEqual(detail.returncode, 0, detail.stderr)
            detail_payload = json.loads(detail.stdout)
            self.assertEqual(detail_payload["items"], [])
            self.assertEqual(detail_payload["archive"]["request_summary"], "Answer a simple question")
            self.assertEqual(
                detail_payload["archive"]["result_summary"],
                "Answered directly without creating plan or task records.",
            )

    def test_hook_event_uses_payload_cwd_for_repo_db(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            workspace = base / "workspace"
            outside = base / "outside"
            home = base / "home"
            workspace.mkdir()
            outside.mkdir()
            home.mkdir()
            (workspace / ".tapl").mkdir()
            (workspace / ".tapl" / "version").write_text("0.0.0\n", encoding="utf-8")

            event = self.run_taplctl(
                "hook-event",
                "--event",
                "UserPromptSubmit",
                "--mode",
                "observe",
                "--json",
                input_text=json.dumps({"cwd": str(workspace), "prompt": "Global install workspace"}),
                cwd=outside,
                env_overrides={"HOME": str(home)},
            )
            self.assertEqual(event.returncode, 0, event.stderr)
            payload = json.loads(event.stdout)
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["context"]["prompt_summary"], "Global install workspace")
            self.assertEqual(
                payload["context"]["active_run"]["request_summary"],
                "New request",
            )
            self.assertTrue((workspace / ".tapl" / "tapl.db").exists())
            self.assertEqual(
                (workspace / ".tapl" / "version").read_text(encoding="utf-8").strip(),
                __version__,
            )
            self.assertTrue((workspace / ".codex" / "hooks.json").exists())
            self.assertFalse((outside / ".tapl").exists())
            self.assertFalse((outside / ".codex").exists())

    def test_archive_show_includes_items_and_events(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "tapl.db"
            self.run_cli(db_path, "init", "--json")

            plan = self.run_cli(
                db_path,
                "plan",
                "set",
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
                "set",
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
