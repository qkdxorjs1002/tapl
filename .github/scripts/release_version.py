#!/usr/bin/env python3
"""Validate a release tag and expose its packaging-safe versions.

Git tags and VS Code assets use SemVer (for example ``2.0.0-beta1``),
while Python package metadata uses the equivalent PEP 440 version
(``2.0.0b1``).
"""

from __future__ import annotations

import argparse
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence


_TAG_PATTERN = re.compile(
    r"(?P<base>(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*))"
    r"(?:-(?P<kind>alpha|beta|rc)(?P<serial>0|[1-9][0-9]*))?"
)
_PEP440_MARKERS = {"alpha": "a", "beta": "b", "rc": "rc"}


@dataclass(frozen=True)
class ReleaseVersion:
    version: str
    python_version: str
    prerelease: bool

    def github_outputs(self) -> Mapping[str, str]:
        return {
            "version": self.version,
            "python_version": self.python_version,
            "prerelease": "true" if self.prerelease else "false",
        }


def parse_release_tag(tag: str) -> ReleaseVersion:
    """Parse the repository's canonical stable or prerelease tag format."""

    match = _TAG_PATTERN.fullmatch(tag)
    if match is None:
        raise ValueError(
            "release tag must be x.y.z or "
            "x.y.z-(alpha|beta|rc)N (for example 2.0.0-beta1); "
            f"got {tag!r}"
        )

    kind = match.group("kind")
    serial = match.group("serial")
    python_version = match.group("base")
    if kind is not None:
        python_version += f"{_PEP440_MARKERS[kind]}{serial}"

    return ReleaseVersion(
        version=tag,
        python_version=python_version,
        prerelease=kind is not None,
    )


def write_github_outputs(release: ReleaseVersion, destination: Path) -> None:
    """Append validated values to a GitHub Actions output file."""

    with destination.open("a", encoding="utf-8") as output_file:
        for name, value in release.github_outputs().items():
            output_file.write(f"{name}={value}\n")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tag", help="Git tag without a leading v")
    parser.add_argument(
        "--github-output",
        type=Path,
        help="output file to append to (defaults to $GITHUB_OUTPUT when set)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        release = parse_release_tag(args.tag)
    except ValueError as exc:
        _parser().error(str(exc))

    destination = args.github_output
    if destination is None and os.environ.get("GITHUB_OUTPUT"):
        destination = Path(os.environ["GITHUB_OUTPUT"])

    if destination is not None:
        write_github_outputs(release, destination)
    else:
        for name, value in release.github_outputs().items():
            print(f"{name}={value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
