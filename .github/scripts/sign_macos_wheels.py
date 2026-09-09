#!/usr/bin/env python3
"""Sign native code in a macOS wheelhouse, preserving valid wheel RECORDs."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile


MACHO_MAGICS = {
    bytes.fromhex(magic)
    for magic in (
        "feedface", "cefaedfe", "feedfacf", "cffaedfe",
        "cafebabe", "bebafeca", "cafebabf", "bfbafeca",
    )
}


def is_macho(path: Path) -> bool:
    with path.open("rb") as stream:
        return stream.read(4) in MACHO_MAGICS


def signing_identity(keychain: str, team_id: str) -> str:
    result = subprocess.run(
        ["security", "find-identity", "-v", "-p", "codesigning", keychain],
        check=True, capture_output=True, text=True,
    )
    identities = re.findall(
        r'\b([0-9A-Fa-f]{40}) "Developer ID Application: [^"\n]+ '
        + re.escape(f"({team_id})") + r'"',
        result.stdout,
    )
    if len(identities) != 1:
        raise ValueError(
            "The temporary keychain must contain exactly one valid Developer ID "
            "Application identity for APPLE_TEAM_ID (including its private key)."
        )
    return identities[0]


def verify_signature(path: Path, team_id: str) -> None:
    subprocess.run(
        ["codesign", "--verify", "--strict", "--all-architectures", str(path)],
        check=True,
    )
    details = subprocess.run(
        ["codesign", "--display", "--verbose=4", str(path)],
        check=True, capture_output=True, text=True,
    )
    signature = details.stdout + details.stderr
    if (
        f"TeamIdentifier={team_id}" not in signature.splitlines()
        or "Authority=Developer ID Application:" not in signature
        or "Timestamp=" not in signature
        or "(runtime)" not in signature
    ):
        raise ValueError(f"Missing Developer ID, team, timestamp, or hardened runtime: {path.name}")


def sign_wheelhouse(wheelhouse: Path, keychain: str, team_id: str) -> int:
    if re.fullmatch(r"[A-Z0-9]{10}", team_id) is None:
        raise ValueError("APPLE_TEAM_ID must be the 10-character Apple developer Team ID.")
    wheels = sorted(wheelhouse.glob("*.whl"))
    if not wheels:
        raise ValueError("The runtime wheelhouse is empty.")
    identity = signing_identity(keychain, team_id)
    signed_count = 0
    # Stage every replacement before changing the input wheelhouse. A failed
    # signature or invalid wheel must never become a published runtime archive.
    with tempfile.TemporaryDirectory(prefix="tapl-signed-wheels-") as temporary:
        staging = Path(temporary)
        replacements: list[tuple[Path, Path]] = []
        for index, wheel in enumerate(wheels):
            unpacked = staging / str(index) / "unpacked"
            packed = staging / str(index) / "packed"
            subprocess.run(
                [sys.executable, "-m", "wheel", "unpack", str(wheel), "--dest", str(unpacked)],
                check=True,
            )
            roots = list(unpacked.iterdir())
            if len(roots) != 1 or not roots[0].is_dir():
                raise ValueError(f"Unexpected wheel layout: {wheel.name}")
            root = roots[0]
            binaries = [path for path in sorted(root.rglob("*")) if path.is_file() and is_macho(path)]
            if not binaries:
                continue
            for binary in binaries:
                subprocess.run(
                    ["codesign", "--force", "--sign", identity, "--keychain", keychain,
                     "--timestamp", "--options", "runtime", str(binary)],
                    check=True,
                )
                verify_signature(binary, team_id)
            # RECORD signatures describe the upstream wheel, not our re-signed
            # payload. wheel pack regenerates RECORD hashes for all new bytes.
            for signature in root.glob("*.dist-info/RECORD.*"):
                if signature.name in {"RECORD.jws", "RECORD.p7s"}:
                    signature.unlink()
            packed.mkdir()
            subprocess.run(
                [sys.executable, "-m", "wheel", "pack", str(root), "--dest-dir", str(packed)],
                check=True,
            )
            replacement = packed / wheel.name
            if not replacement.is_file() or len(list(packed.iterdir())) != 1:
                raise ValueError(f"Repacking changed the wheel filename: {wheel.name}")
            # Unpack the final wheel again: wheel checks RECORD hashes, then
            # codesign verifies the exact bytes that installers will receive.
            verified = staging / str(index) / "verified"
            subprocess.run(
                [sys.executable, "-m", "wheel", "unpack", str(replacement), "--dest", str(verified)],
                check=True,
            )
            for binary in binaries:
                verify_signature(verified / root.name / binary.relative_to(root), team_id)
            signed_count += len(binaries)
            replacements.append((wheel, replacement))
        if signed_count == 0:
            raise ValueError("No Mach-O binaries found in the macOS runtime wheelhouse.")
        for original, replacement in replacements:
            shutil.copyfile(replacement, original)
    return signed_count


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wheelhouse", type=Path)
    parser.add_argument("--keychain", required=True)
    args = parser.parse_args()
    if sys.platform != "darwin":
        parser.error("Developer ID signing requires macOS.")
    count = sign_wheelhouse(args.wheelhouse, args.keychain, os.environ.get("APPLE_TEAM_ID", ""))
    print(f"Verified Developer ID signatures on {count} Mach-O files.")


if __name__ == "__main__":
    main()
