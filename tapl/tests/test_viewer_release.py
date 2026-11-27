import json
import subprocess
import sys
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[2] / ".github/scripts/viewer_release.py"


def git(repo: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()


def commit(repo: Path, changes: dict[str, str]) -> str:
    for name, content in changes.items():
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "--no-gpg-sign", "-m", "Update release inputs")
    return git(repo, "rev-parse", "HEAD")


def release(tag: str, date: str, *, has_vsix: bool = True, prerelease: bool = False) -> dict:
    version = tag.removeprefix("viewer-")
    assets = [{"name": f"tapl-workflow-viewer-{version}.vsix", "state": "uploaded"}] if has_vsix else []
    return {"tag_name": tag, "published_at": date, "draft": False, "prerelease": prerelease, "assets": assets}


def plan(repo: Path, scratch: Path, tag: str, releases: list[dict], expected: str) -> dict[str, str]:
    metadata = scratch / "releases.json"
    metadata.write_text(json.dumps([[item] for item in releases]), encoding="utf-8")
    output = scratch / "outputs"
    output.unlink(missing_ok=True)
    subprocess.run(
        [sys.executable, str(SCRIPT), tag, "--releases", str(metadata), "--expected-commit", expected,
         "--github-output", str(output)],
        cwd=repo, check=True,
    )
    return dict(line.split("=", 1) for line in output.read_text(encoding="utf-8").splitlines())


def test_viewer_release_uses_the_last_published_vsix_in_each_channel(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init")
    git(repo, "config", "user.name", "Release Test")
    git(repo, "config", "user.email", "release@example.invalid")
    git(repo, "config", "tag.gpgSign", "false")
    commit(repo, {
        "vscode-extension/src/viewer.ts": "export const title = 'Viewer';\n",
        "vscode-extension/package.json": '{"name": "tapl-workflow-viewer", "version": "2.25.5"}\n',
    })
    git(repo, "tag", "2.25.5")
    releases = [release("2.25.5", "2026-11-23T00:00:00Z")]

    ctl = commit(repo, {"tapl/taplctl/viewer.py": "# Python server edit\n"})
    git(repo, "tag", "2.25.6")
    git(repo, "tag", "viewer-2.25.6")
    releases.append(release("2.25.6", "2026-11-24T00:00:00Z", has_vsix=False))
    unchanged = plan(repo, tmp_path, "viewer-2.25.6", releases, ctl)
    assert unchanged["baseline"] == "2.25.5"
    assert unchanged["publish"] == "false"

    version_only = commit(repo, {
        "vscode-extension/package.json": '{"name": "tapl-workflow-viewer", "version": "2.25.7"}\n',
        "vscode-extension/tests/viewer.cjs": "// Test edit\n",
    })
    git(repo, "tag", "viewer-2.25.7")
    assert plan(repo, tmp_path, "viewer-2.25.7", releases, version_only)["publish"] == "false"

    viewer = commit(repo, {"vscode-extension/src/viewer.ts": "export const title = 'Updated Viewer';\n"})
    git(repo, "tag", "-a", "viewer-2.26.0-beta1", "-m", "Viewer preview")
    git(repo, "tag", "viewer-2.26.0")
    tag_object = git(repo, "rev-parse", "viewer-2.26.0-beta1")
    preview = plan(repo, tmp_path, "viewer-2.26.0-beta1", releases, tag_object)
    assert preview["publish"] == preview["prerelease"] == "true"
    assert preview["tag_object"] == tag_object
    releases.append(release("viewer-2.26.0-beta1", "2026-11-25T00:00:00Z", prerelease=True))

    stable = plan(repo, tmp_path, "viewer-2.26.0", releases, viewer)
    assert stable["publish"] == "true"
    assert stable["prerelease"] == "false"
    assert stable["baseline"] == "2.25.5"
    releases.append(release("viewer-2.26.0", "2026-11-26T00:00:00Z"))
    retry = plan(repo, tmp_path, "viewer-2.26.0", releases, viewer)
    assert retry["publish"] == retry["existing_asset"] == "true"

    ctl = commit(repo, {"tapl/taplctl/viewer.py": "# Another Python server edit\n"})
    git(repo, "tag", "viewer-2.26.1")
    unchanged = plan(repo, tmp_path, "viewer-2.26.1", releases, ctl)
    assert unchanged["baseline"] == "viewer-2.26.0"
    assert unchanged["publish"] == "false"
