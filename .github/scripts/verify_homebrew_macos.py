#!/usr/bin/env python3
"""Verify that a real Homebrew install preserves signed runtime wheel bytes."""

from __future__ import annotations

import argparse
from email.parser import BytesParser
import hashlib
import io
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import tarfile
import zipfile

from sign_macos_wheels import MACHO_MAGICS, verify_signature


TAP = "tapl-ci/signature-check"
FORMULA = f"{TAP}/tapl-signature-check"


def native_hashes(archive: Path) -> dict[str, str]:
    expected: dict[str, str] = {}
    with tarfile.open(archive, "r:gz") as runtime:
        for member in runtime:
            if not member.isfile() or not member.name.endswith(".whl"):
                continue
            stream = runtime.extractfile(member)
            assert stream is not None
            with zipfile.ZipFile(io.BytesIO(stream.read())) as wheel:
                for entry in wheel.infolist():
                    if entry.is_dir():
                        continue
                    payload = wheel.read(entry)
                    if payload[:4] not in MACHO_MAGICS:
                        continue
                    path = PurePosixPath(entry.filename)
                    if path.is_absolute() or ".." in path.parts or "\\" in entry.filename:
                        raise ValueError(f"Unsafe native wheel path: {entry.filename}")
                    if any(part.endswith(".data") for part in path.parts):
                        raise ValueError(f"Unsupported native wheel install layout: {entry.filename}")
                    if entry.filename in expected:
                        raise ValueError(f"Duplicate native runtime path: {entry.filename}")
                    expected[entry.filename] = hashlib.sha256(payload).hexdigest()
    if not expected:
        raise ValueError("No Mach-O files found in the signed runtime archive")
    return expected


def verify_installed(site_packages: Path, expected: dict[str, str], team_id: str) -> int:
    if re.fullmatch(r"[A-Z0-9]{10}", team_id) is None:
        raise ValueError("A valid Apple Team ID is required")
    if not expected:
        raise ValueError("No expected native files")
    root = site_packages.resolve()
    for relative, digest in expected.items():
        installed = (root / relative).resolve()
        if not installed.is_relative_to(root) or not installed.is_file():
            raise ValueError(f"Missing or unsafe installed native file: {relative}")
        if hashlib.sha256(installed.read_bytes()).hexdigest() != digest:
            raise ValueError(f"Homebrew changed signed runtime bytes: {relative}")
        # codesign --verify alone also accepts ad-hoc signatures. Require the
        # Developer ID authority, intended team, timestamp and runtime flag.
        verify_signature(installed, team_id)
    print(f"Verified {len(expected)} installed Mach-O files: unchanged bytes and Developer ID signatures.", flush=True)
    return len(expected)


def verify_prefix(prefix: Path, expected: dict[str, str], team_id: str) -> None:
    python = prefix / "libexec/bin/python"
    site = subprocess.check_output(
        [str(python), "-c", "import sysconfig; print(sysconfig.get_path('platlib'))"], text=True,
    ).strip()
    verify_installed(Path(site), expected, team_id)
    subprocess.run([str(prefix / "bin/taplctl"), "--version"], check=True)
    subprocess.run([str(python), "-c", (
        "import _cffi_backend, cryptography.hazmat.bindings._rust, pydantic_core, rpds; "
        "from taplctl.mcp_server import create_server; assert create_server(); "
        "print('Installed native imports and MCP server smoke passed.')"
    )], check=True)


def wheel_version(wheel: Path) -> str:
    with zipfile.ZipFile(wheel) as package:
        metadata = [name for name in package.namelist() if name.endswith(".dist-info/METADATA")]
        if len(metadata) != 1:
            raise ValueError("Expected one TAPL wheel metadata file")
        parsed = BytesParser().parsebytes(package.read(metadata[0]))
    if parsed["Name"] != "taplctl" or not re.fullmatch(r"\d+\.\d+\.\d+(?:(?:a|b|rc)\d+)?", parsed["Version"] or ""):
        raise ValueError("Expected a versioned taplctl wheel")
    return parsed["Version"]


def install_and_verify(runtime: Path, wheel: Path, expected: dict[str, str], team_id: str) -> None:
    # This mode intentionally creates/removes a Homebrew formula. Limit it to
    # disposable CI runners; --verify-prefix is a read-only local check.
    if os.environ.get("GITHUB_ACTIONS") != "true":
        raise ValueError("Homebrew installation checks must run in GitHub Actions")
    env = dict(os.environ, HOMEBREW_NO_AUTO_UPDATE="1", HOMEBREW_NO_INSTALL_CLEANUP="1",
               HOMEBREW_NO_ENV_HINTS="1")
    # Intel runner images also contain python.org framework symlinks under
    # /usr/local/bin. Provision Homebrew's interpreter without link conflicts,
    # then use its links for the formula's Python dependency.
    subprocess.run(["brew", "install", "--skip-link", "python@3.12"], check=True, env=env)
    subprocess.run(["brew", "link", "--overwrite", "python@3.12"], check=True, env=env)
    subprocess.run(["brew", "tap-new", "--no-git", TAP], check=True, env=env)
    try:
        tap_path = Path(subprocess.check_output(["brew", "--repository", TAP], text=True, env=env).strip())
        formula = tap_path / "Formula/tapl-signature-check.rb"
        formula.write_text('''class TaplSignatureCheck < Formula
  include Language::Python::Virtualenv
  desc "TAPL signed runtime installation check"
  homepage "https://github.com/qkdxorjs1002/tapl"
  url "https://example.invalid/taplctl-0.0.0.whl"
  version "0.0.0"
  sha256 "0000000000000000000000000000000000000000000000000000000000000000"
  license "MIT"
  depends_on "python@3.12"
  def install
  end
  test do
    assert_match(/taplctl/, shell_output("#{bin}/taplctl --version"))
  end
end
''')
        env.update(RELEASE_VERSION=wheel_version(wheel), WHEEL_URL=wheel.as_uri(),
                   WHEEL_SHA256=hashlib.sha256(wheel.read_bytes()).hexdigest())
        for target in ("MACOS_ARM64", "MACOS_X86_64", "LINUX_ARM64", "LINUX_X86_64"):
            env[f"MCP_RUNTIME_{target}_URL"] = runtime.as_uri()
            env[f"MCP_RUNTIME_{target}_SHA256"] = hashlib.sha256(runtime.read_bytes()).hexdigest()
        updater = Path(__file__).with_name("update_homebrew_formula.rb")
        subprocess.run(["ruby", str(updater), str(formula)], check=True, env=env)
        for command in ("install", "reinstall"):
            args = ["brew", command, "--formula", FORMULA]
            if command == "install":
                args.insert(2, "--skip-link")
            subprocess.run(args, check=True, env=env)
            prefix = Path(subprocess.check_output(["brew", "--prefix", FORMULA], text=True, env=env).strip())
            print(f"Checking completed brew {command}", flush=True)
            verify_prefix(prefix, expected, team_id)
    finally:
        subprocess.run(["brew", "uninstall", "--force", FORMULA], env=env, check=False)
        subprocess.run(["brew", "untap", TAP], env=env, check=False)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--wheel", type=Path)
    parser.add_argument("--team-id", required=True)
    parser.add_argument("--verify-prefix", type=Path)
    args = parser.parse_args()
    if sys.platform != "darwin":
        parser.error("Actual Homebrew signature verification requires macOS")
    expected = native_hashes(args.runtime)
    if args.verify_prefix:
        verify_prefix(args.verify_prefix, expected, args.team_id)
    elif args.wheel:
        install_and_verify(args.runtime.resolve(), args.wheel.resolve(), expected, args.team_id)
    else:
        parser.error("Provide --wheel for CI installation or --verify-prefix for an existing installation")


if __name__ == "__main__":
    main()
