from __future__ import annotations

import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
RELEASE_WORKFLOW = REPOSITORY_ROOT / ".github" / "workflows" / "release.yml"


class HomebrewPrereleaseWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.workflow = RELEASE_WORKFLOW.read_text(encoding="utf-8")

    @classmethod
    def _step(cls, name: str) -> str:
        marker = f"      - name: {name}\n"
        start = cls.workflow.index(marker)
        next_step = cls.workflow.find("\n      - name:", start + len(marker))
        return cls.workflow[start : None if next_step == -1 else next_step]

    def test_homebrew_credentials_and_checkout_run_for_all_release_channels(self) -> None:
        token_step = self._step("Require Homebrew tap token")
        checkout_step = self._step("Checkout Homebrew tap")

        self.assertNotIn("if: steps.version.outputs.prerelease", token_step)
        self.assertNotIn("if: steps.version.outputs.prerelease", checkout_step)
        self.assertIn("repository: qkdxorjs1002/homebrew-tap", checkout_step)

    def test_pre_formula_update_is_always_configured(self) -> None:
        update_step = self._step("Update taplctl Homebrew package")

        self.assertNotIn("if: steps.version.outputs.prerelease", update_step)
        self.assertIn("RELEASE_PRERELEASE: ${{ steps.version.outputs.prerelease }}", update_step)
        self.assertIn("RELEASE_TAG: ${{ github.ref_name }}", update_step)
        self.assertIn("PRE_FORMULA_TEMPLATE: homebrew-tap/Formula/taplctl.rb", update_step)
        self.assertIn("--pre-formula homebrew-tap/Formula/taplctl-pre.rb", update_step)
        self.assertIn("--pre-alias homebrew-tap/Aliases/taplctl@pre", update_step)

    def test_stable_formulas_are_positional_only_for_stable_releases(self) -> None:
        run = self._step("Update taplctl Homebrew package")
        stable_branch = '''if [[ "${RELEASE_PRERELEASE}" == "false" ]]; then'''
        branch_start = run.index(stable_branch)
        branch_end = run.index("\n\n          ruby -c", branch_start)
        stable_body = run[branch_start:branch_end]

        self.assertIn('stable_brew_files+=("${PRE_FORMULA_TEMPLATE}")', stable_body)
        self.assertIn('stable_brew_files+=("homebrew-tap/Formula/taplctl-semantic.rb")', stable_body)
        self.assertIn('"${stable_brew_files[@]}"', run)
        self.assertNotIn('"${PRE_FORMULA_TEMPLATE}"', run[branch_end:])

    def test_tap_stages_pre_formula_and_alias_and_commit_identifies_channel(self) -> None:
        run = self._step("Update taplctl Homebrew package")

        self.assertIn('"Formula/taplctl-pre.rb"', run)
        self.assertIn('"Aliases/taplctl@pre"', run)
        self.assertIn('git -C homebrew-tap add "${tap_paths[@]}"', run)
        self.assertIn('release_channel="stable"', run)
        self.assertIn('release_channel="prerelease"', run)
        self.assertIn(
            'git -C homebrew-tap commit -m "taplctl ${RELEASE_TAG} (${release_channel})"',
            run,
        )

    def test_github_release_precedes_tap_checkout_and_update(self) -> None:
        publish_index = self.workflow.index("      - name: Publish GitHub Release\n")
        checkout_index = self.workflow.index("      - name: Checkout Homebrew tap\n")
        update_index = self.workflow.index("      - name: Update taplctl Homebrew package\n")

        self.assertLess(publish_index, checkout_index)
        self.assertLess(checkout_index, update_index)


if __name__ == "__main__":
    unittest.main()
