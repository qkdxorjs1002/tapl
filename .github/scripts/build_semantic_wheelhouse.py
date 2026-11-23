"""Download the locked semantic wheels that supplement a release MCP wheelhouse."""

import argparse
import hashlib
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import tomllib


def build(target: str, mcp: Path, destination: Path) -> None:
    project = tomllib.loads(Path("tapl/pyproject.toml").read_text())["project"]
    packages = tomllib.loads(Path("tapl/uv.lock").read_text())["package"]
    # Keep versions selected for the older MCP platform when dependencies overlap.
    base = {w.name.split("-")[0].replace("_", "-"): w.name.split("-")[1] for w in mcp.glob("*.whl")}
    if "mcp" not in base:
        raise ValueError(f"No MCP wheel in {mcp}")

    constraints = [f"{name}=={version}" for name, version in base.items()]
    hashes = {}
    for package in packages:
        name = package["name"]
        if name in base or "registry" not in package["source"]:
            continue
        requirement = f"{name}=={package['version']}"
        markers = package.get("resolution-markers", [])
        if markers:
            requirement += "; " + " or ".join(f"({marker})" for marker in markers)
        constraints.append(requirement)
        for wheel in package.get("wheels", []):
            hashes[wheel["url"].rsplit("/", 1)[1]] = wheel["hash"]

    if target == "macos-arm64":
        platforms = ["macosx_14_0_arm64"]
    else:
        arch = {"linux-arm64": "aarch64", "linux-x86_64": "x86_64"}[target]
        platforms = [f"manylinux_2_{minor}_{arch}" for minor in range(28, 16, -1)]
        platforms.append(f"manylinux2014_{arch}")

    destination.mkdir(parents=True, exist_ok=True)
    if any(destination.iterdir()):
        raise ValueError(f"Expected an empty wheelhouse: {destination}")
    with tempfile.TemporaryDirectory() as temporary:
        work = Path(temporary)
        constraints_path = work / "constraints.txt"
        constraints_path.write_text("\n".join(constraints) + "\n")
        subprocess.run([
            sys.executable, "-m", "pip", "download", "--only-binary=:all:", "--disable-pip-version-check",
            "--dest", str(work), "--constraint", str(constraints_path), "--find-links", str(mcp),
            *(arg for platform in platforms for arg in ("--platform", platform)),
            *project["optional-dependencies"]["semantic"],
        ], check=True)
        for wheel in work.glob("*.whl"):
            if wheel.name.split("-")[0].replace("_", "-") in base:
                continue
            digest = "sha256:" + hashlib.sha256(wheel.read_bytes()).hexdigest()
            if hashes.get(wheel.name) != digest:
                raise ValueError(f"Semantic wheel does not match tapl/uv.lock: {wheel.name}")
            shutil.move(wheel, destination / wheel.name)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", choices=("macos-arm64", "linux-x86_64", "linux-arm64"))
    parser.add_argument("mcp_wheelhouse", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    build(args.target, args.mcp_wheelhouse, args.destination)
