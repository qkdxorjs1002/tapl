from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import tomllib
import unittest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from taplctl import config, config_editor


class SubagentSetupTests(unittest.TestCase):
    def test_ordinary_noop_does_not_migrate_a_legacy_config(self) -> None:
        original = '[search]\nmode = "word"\n[subagents.models]\nchosen = ["high"]\n'
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.toml"
            path.write_text(original, encoding="utf-8")
            result = config_editor.set_value(path, "search.mode", "word")
            self.assertFalse(result.changed)
            self.assertEqual(path.read_text(encoding="utf-8"), original)

    def test_missing_config_is_pending_with_generic_profiles(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            loaded = config.load(Path(tmp) / "missing.toml")

        self.assertFalse(loaded.subagents.setup_complete)
        self.assertEqual(loaded.subagents.preference, "")
        self.assertEqual(loaded.subagents.models, ())
        self.assertTrue(loaded.subagents.profiles)
        self.assertTrue(
            all(not profile.candidates for profile in loaded.subagents.profiles)
        )

    def test_legacy_explicit_model_settings_remain_complete(self) -> None:
        content = """[subagents]
enabled = true

[subagents.models]
custom-runtime = ["careful"]

[[subagents.profiles]]
name = "routine"
candidates = [{ model = "custom-runtime", reasoning_effort = "careful" }]
"""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.toml"
            path.write_text(content, encoding="utf-8")
            loaded = config.load(path)

        self.assertTrue(loaded.subagents.setup_complete)
        self.assertEqual(
            loaded.subagents.as_dict()["models"],
            {"custom-runtime": ["careful"]},
        )
        self.assertEqual(
            loaded.subagents.profiles[0].candidates[0].as_dict(),
            {"model": "custom-runtime", "reasoning_effort": "careful"},
        )

    def test_completed_enabled_setup_requires_models_even_when_table_is_absent(self) -> None:
        for content in (
            "[subagents]\nsetup_complete = true\n",
            "[subagents]\nsetup_complete = true\n[subagents.models]\n",
        ):
            with self.subTest(content=content):
                with self.assertRaisesRegex(
                    ValueError,
                    "must define at least one model",
                ):
                    config.from_mapping(
                        tomllib.loads(content),
                        path="config.toml",
                    )

    def test_invalid_completed_setup_leaves_file_unchanged(self) -> None:
        original = """[subagents]
custom_setting = "retain"

[subagents.models]
old-runtime = ["high"]
"""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.toml"
            path.write_text(original, encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "must define at least one model"):
                config_editor.configure_subagents(
                    path,
                    enabled=True,
                    strategy="balanced",
                    models={},
                )

            self.assertEqual(path.read_text(encoding="utf-8"), original)

    def test_configure_subagents_replaces_standard_settings_atomically(self) -> None:
        original = """# Retain this project setting.
[search]
mode = "bm25"

[subagents]
custom_setting = "retain"
enabled = false
preference = "old preference"

[subagents.models]
old-runtime = ["low"]

[[subagents.profiles]]
name = "obsolete"
candidates = [{ model = "old-runtime", reasoning_effort = "low" }]

[viewer]
# Retain this unrelated table comment.
allowed_origins = ["https://example.test"]
"""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.toml"
            path.write_text(original, encoding="utf-8")

            result = config_editor.configure_subagents(
                path,
                enabled=True,
                strategy="balanced",
                models={"chosen-runtime": ["careful", "thorough"]},
                profiles=[
                    {
                        "name": "focused",
                        "delegation_bias": "prefer",
                        "candidates": [
                            {
                                "model": "chosen-runtime",
                                "reasoning_effort": "thorough",
                            }
                        ],
                    }
                ],
                preference="Favor careful work",
            )
            saved = path.read_text(encoding="utf-8")

        self.assertTrue(result.changed)
        self.assertTrue(result.config.setup_complete)
        self.assertEqual(result.config.preference, "Favor careful work")
        self.assertEqual(
            result.config.as_dict()["models"],
            {"chosen-runtime": ["careful", "thorough"]},
        )
        self.assertEqual([profile.name for profile in result.config.profiles], ["focused"])
        self.assertNotIn("old-runtime", saved)
        self.assertNotIn("obsolete", saved)
        self.assertIn('custom_setting = "retain"', saved)
        self.assertIn('mode = "bm25"', saved)
        self.assertIn("# Retain this unrelated table comment.", saved)

    def test_configure_subagents_replaces_dotted_and_inline_standard_forms(self) -> None:
        original = """subagents.custom_setting = "retain"
subagents.models.old-runtime = ["low"]

[[subagents.profiles]]
name = "obsolete"

[[subagents.profiles.candidates]]
model = "old-runtime"
reasoning_effort = "low"
"""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.toml"
            path.write_text(original, encoding="utf-8")

            result = config_editor.configure_subagents(
                path,
                enabled=False,
                strategy="conservative",
                models={},
                profiles=[],
            )
            saved = path.read_text(encoding="utf-8")

        self.assertEqual(result.config.models, ())
        self.assertEqual(result.config.profiles, ())
        self.assertIn('custom_setting = "retain"', saved)
        self.assertNotIn("old-runtime", saved)
        self.assertNotIn("obsolete", saved)

    def test_configure_subagents_preserves_custom_inline_subagent_settings(self) -> None:
        original = """subagents = { custom_setting = "retain", enabled = false, models = { old-runtime = ["low"] }, profiles = [] }
"""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.toml"
            path.write_text(original, encoding="utf-8")

            config_editor.configure_subagents(
                path,
                enabled=False,
                strategy="conservative",
                models={},
                profiles=[],
            )
            saved = path.read_text(encoding="utf-8")

        self.assertIn('custom_setting = "retain"', saved)
        self.assertNotIn("old-runtime", saved)

    def test_catalog_updates_preserve_dotted_settings(self) -> None:
        original = 'subagents.custom_setting = "retain"\nsubagents.models.chosen = ["high"]\n'
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.toml"
            path.write_text(original, encoding="utf-8")
            for catalog in ({"chosen": ["high"]}, {"chosen": ["high"], "new": ["low"]}):
                saved = config_editor.configure_subagents(
                    path, enabled=True, strategy="balanced", models={"chosen": ["high"]},
                    available_models=catalog,
                )
                self.assertEqual(saved.config.as_dict()["available_models"], catalog)
                self.assertEqual(tomllib.loads(path.read_text())["subagents"]["custom_setting"], "retain")


if __name__ == "__main__":
    unittest.main()
