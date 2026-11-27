#!/usr/bin/env python3
"""Plan a VS Code Viewer release from published GitHub releases and Git tags."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from release_version import ReleaseVersion, parse_release_tag


_PREFIX = "viewer-"
_PACKAGE_JSON = "vscode-extension/package.json"
_VSIX_INPUTS = (
    "vscode-extension",
    ":(exclude)vscode-extension/tests",
    ":(exclude)vscode-extension/out",
    ":(exclude)vscode-extension/webview-dist",
    ":(exclude)vscode-extension/node_modules",
    ":(exclude)vscode-extension/AGENTS.md",
    ":(exclude)vscode-extension/README.ko.md",
    ":(exclude)vscode-extension/resources/marketplace-icon.svg",
    ":(exclude,glob)vscode-extension/**/.DS_Store",
    ":(exclude,glob)vscode-extension/**/*.vsix",
)
_COMMIT_ID = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})")


@dataclass(frozen=True)
class ViewerReleasePlan:
    tag: str
    version: ReleaseVersion
    baseline: str | None
    publish: bool
    existing_asset: bool
    tag_object: str
    commit: str


def parse_viewer_tag(tag: str) -> ReleaseVersion:
    """Require the Viewer namespace and validate the canonical version suffix."""

    if not tag.startswith(_PREFIX):
        raise ValueError(f"Viewer tag must begin with {_PREFIX!r}; got {tag!r}")
    return parse_release_tag(tag.removeprefix(_PREFIX))


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, check=check, input=b""
    )


def _tag_commit(repo: Path, tag: str) -> str:
    return _git(
        repo, "rev-parse", "--verify", "--quiet", f"refs/tags/{tag}^{{commit}}", check=False
    ).stdout.decode("ascii").strip()


def _published_at(release: dict) -> str:
    timestamp = release.get("published_at")
    return timestamp if isinstance(timestamp, str) else ""


def _is_published_vsix(release: dict, version: ReleaseVersion) -> bool:
    if (
        release.get("draft") is not False
        or release.get("prerelease") is not version.prerelease
        or not _published_at(release)
    ):
        return False
    asset_name = f"tapl-workflow-viewer-{version.version}.vsix"
    return any(
        asset.get("name") == asset_name and asset.get("state") == "uploaded"
        for asset in release.get("assets", [])
    )


def _baseline(
    repo: Path, tag: str, version: ReleaseVersion, releases: Sequence[dict]
) -> tuple[str | None, str]:
    legacy = None
    for release in sorted(releases, key=_published_at, reverse=True):
        previous_tag = release.get("tag_name")
        if not isinstance(previous_tag, str) or previous_tag == tag:
            continue
        is_viewer = previous_tag.startswith(_PREFIX)
        try:
            previous = (
                parse_viewer_tag(previous_tag) if is_viewer else parse_release_tag(previous_tag)
            )
        except ValueError:
            continue
        if previous.prerelease != (is_viewer and version.prerelease):
            continue
        if not _is_published_vsix(release, previous):
            continue
        commit = _tag_commit(repo, previous_tag)
        if not commit:
            continue
        if is_viewer:
            return previous_tag, commit
        if legacy is None:
            legacy = previous_tag, commit
    if legacy is not None:
        return legacy
    return None, _git(repo, "hash-object", "-t", "tree", "--stdin").stdout.decode("ascii").strip()


def _package_without_version(repo: Path, revision: str) -> dict | None:
    if not _git(repo, "ls-tree", revision, "--", _PACKAGE_JSON).stdout:
        return None
    package = json.loads(_git(repo, "cat-file", "blob", f"{revision}:{_PACKAGE_JSON}").stdout)
    package.pop("version", None)
    return package


def _has_vsix_changes(repo: Path, baseline: str, commit: str) -> bool:
    changed = _git(
        repo, "diff", "--no-ext-diff", "--no-renames", "--name-only", "-z",
        baseline, commit, "--", *_VSIX_INPUTS
    ).stdout
    if changed == _PACKAGE_JSON.encode() + b"\0":
        # The workflow overwrites the checked-in version before packaging.
        return _package_without_version(repo, baseline) != _package_without_version(repo, commit)
    return bool(changed)


def plan_viewer_release(
    tag: str, releases: Sequence[dict], *, repo: Path = Path(".")
) -> ViewerReleasePlan:
    """Compare current VSIX inputs with the previous published channel release."""

    version = parse_viewer_tag(tag)
    commit = _tag_commit(repo, tag)
    if not commit:
        raise ValueError(f"Viewer tag {tag!r} does not resolve to a local Git commit")
    tag_object = _git(repo, "rev-parse", "--verify", f"refs/tags/{tag}").stdout.decode("ascii").strip()
    existing = next((release for release in releases if release.get("tag_name") == tag), None)
    existing_asset = existing is not None and _is_published_vsix(existing, version)
    baseline, baseline_commit = _baseline(repo, tag, version, releases)
    return ViewerReleasePlan(
        tag=tag,
        version=version,
        baseline=baseline,
        publish=existing_asset or _has_vsix_changes(repo, baseline_commit, commit),
        existing_asset=existing_asset,
        tag_object=tag_object,
        commit=commit,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tag", help="pushed viewer-x.y.z tag")
    parser.add_argument("--releases", type=Path, required=True, help="slurped GitHub REST release pages")
    parser.add_argument("--expected-commit", required=True, help="commit or annotated tag SHA from the push")
    parser.add_argument("--github-output", type=Path, required=True)
    args = parser.parse_args(argv)

    if not _COMMIT_ID.fullmatch(args.expected_commit):
        parser.error("expected commit must be a full Git object ID")
    try:
        pages = json.loads(args.releases.read_text(encoding="utf-8"))
        plan = plan_viewer_release(args.tag, [release for page in pages for release in page])
        expected_commit = _git(
            Path("."), "rev-parse", "--verify", f"{args.expected_commit}^{{commit}}"
        ).stdout.decode("ascii").strip()
        checked_out_commit = _git(Path("."), "rev-parse", "HEAD").stdout.decode("ascii").strip()
    except (ValueError, subprocess.CalledProcessError) as exc:
        parser.error(str(exc))
    if plan.commit != expected_commit or plan.commit != checked_out_commit:
        parser.error("Viewer tag does not match the pushed and checked-out commit")

    outputs = {
        "version": plan.version.version,
        "prerelease": str(plan.version.prerelease).lower(),
        "baseline": plan.baseline or "",
        "publish": str(plan.publish).lower(),
        "existing_asset": str(plan.existing_asset).lower(),
        "tag_object": plan.tag_object,
    }
    with args.github_output.open("a", encoding="utf-8") as output:
        for name, value in outputs.items():
            output.write(f"{name}={value}\n")
    if plan.existing_asset:
        print(f"Retrying published Viewer release {plan.tag}.")
    else:
        changes = "changes" if plan.publish else "no changes"
        print(f"Viewer inputs have {changes} since {plan.baseline or 'the empty tree'}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
