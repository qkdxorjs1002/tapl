#!/usr/bin/env python3
"""Render and verify Windows installer assets bound to one release."""

from __future__ import annotations

import argparse
from pathlib import Path
import re
from typing import Sequence

from release_version import parse_release_tag


def render_installers(tag: str, python_version: str, source_dir: Path) -> dict[str, bytes]:
    release = parse_release_tag(tag)
    if python_version != release.python_version:
        raise ValueError(f"Python version must be {release.python_version!r} for tag {tag!r}")

    script = (source_dir / "install-windows.ps1").read_bytes().decode("utf-8")
    replacements = {
        "__TAPL_RELEASE_TAG__": release.version,
        "__TAPL_RELEASE_PYTHON_VERSION__": release.python_version,
    }
    for token, value in replacements.items():
        if script.count(token) != 1:
            raise ValueError(f"installer template must contain {token} exactly once")
        script = script.replace(token, value)
    assets = {
        "install.ps1": script.encode("utf-8"),
        "install.cmd": (source_dir / "install-windows.cmd").read_bytes(),
    }
    for name, content in assets.items():
        if re.search(rb"__TAPL_[A-Z0-9_]+__", content):
            raise ValueError(f"{name} contains an unresolved template token")
    return assets


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--python-version", required=True)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--source-dir", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--check", action="store_true", help="verify existing assets without writing")
    args = parser.parse_args(argv)
    try:
        assets = render_installers(args.tag, args.python_version, args.source_dir)
        if args.check:
            for name, content in assets.items():
                if (args.output_dir / name).read_bytes() != content:
                    raise ValueError(f"{name} does not match the rendered release installer")
        else:
            args.output_dir.mkdir(parents=True, exist_ok=True)
            for name, content in assets.items():
                (args.output_dir / name).write_bytes(content)
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
