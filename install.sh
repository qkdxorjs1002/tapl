#!/bin/sh

set -eu

DEFAULT_MANIFEST_URL="https://github.com/qkdxorjs1002/tapl/releases/latest/download/taplctl-install-manifest.json"

work_dir=
candidate_venv=
candidate_incomplete=0
link_tmp=
install_json_tmp=
link_activated=0
had_existing_link=0
previous_link_target=

die() {
    printf 'taplctl installer: %s\n' "$*" >&2
    exit 1
}

note() {
    printf 'taplctl installer: %s\n' "$*"
}

link_points_to() {
    "$python_bin" - "$1" "$2" <<'PY'
import os
import sys

link_path = sys.argv[1]
expected = os.path.abspath(sys.argv[2])
if not os.path.islink(link_path):
    raise SystemExit(1)
target = os.readlink(link_path)
if not os.path.isabs(target):
    target = os.path.join(os.path.dirname(link_path), target)
raise SystemExit(0 if os.path.abspath(target) == expected else 1)
PY
}

rollback_active_link() {
    [ "$link_activated" -eq 1 ] || return 0

    if [ "$had_existing_link" -eq 1 ]; then
        link_tmp=$bin_dir/.taplctl.rollback.$$
        if [ -e "$link_tmp" ] || [ -L "$link_tmp" ]; then
            return 1
        fi
        if ! ln -s "$previous_link_target" "$link_tmp"; then
            link_tmp=
            return 1
        fi
        if ! mv -f "$link_tmp" "$link_path"; then
            rm -f "$link_tmp"
            link_tmp=
            return 1
        fi
        link_tmp=
    else
        if ! link_points_to "$link_path" "$current_venv/bin/taplctl"; then
            return 1
        fi
        if ! rm -f "$link_path"; then
            return 1
        fi
    fi

    link_activated=0
    return 0
}

cleanup() {
    if [ "$link_activated" -eq 1 ]; then
        if ! rollback_active_link; then
            printf 'taplctl installer: warning: could not restore the previous taplctl command link.\n' >&2
        fi
    fi
    if [ -n "$link_tmp" ]; then
        rm -f "$link_tmp"
    fi
    if [ -n "$install_json_tmp" ]; then
        rm -f "$install_json_tmp"
    fi
    if [ "$candidate_incomplete" -eq 1 ] && [ -n "$candidate_venv" ]; then
        rm -rf "$candidate_venv"
    fi
    if [ -n "$work_dir" ]; then
        rm -rf "$work_dir"
    fi
}

trap cleanup 0
trap 'exit 1' 1 2 15

[ "$(uname -s 2>/dev/null || true)" = "Linux" ] || die "this installer supports Linux only."
command -v curl >/dev/null 2>&1 || die "curl is required."

find_python() {
    for candidate in python3 python; do
        if command -v "$candidate" >/dev/null 2>&1 &&
            "$candidate" -c 'import sys, venv; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' >/dev/null 2>&1
        then
            command -v "$candidate"
            return 0
        fi
    done
    return 1
}

if python_bin=$(find_python); then
    :
else
    die "Python 3.11 or newer with the venv module is required."
fi

if [ -n "${TAPL_INSTALL_ROOT:-}" ]; then
    install_root=$TAPL_INSTALL_ROOT
elif [ -n "${XDG_DATA_HOME:-}" ]; then
    install_root=$XDG_DATA_HOME/tapl
elif [ -n "${HOME:-}" ]; then
    install_root=$HOME/.local/share/tapl
else
    die "HOME, XDG_DATA_HOME, or TAPL_INSTALL_ROOT must be set."
fi

if [ -n "${TAPL_BIN_DIR:-}" ]; then
    bin_dir=$TAPL_BIN_DIR
elif [ -n "${XDG_BIN_HOME:-}" ]; then
    bin_dir=$XDG_BIN_HOME
elif [ -n "${HOME:-}" ]; then
    bin_dir=$HOME/.local/bin
else
    die "HOME, XDG_BIN_HOME, or TAPL_BIN_DIR must be set."
fi

manifest_url=${TAPL_INSTALL_MANIFEST_URL:-$DEFAULT_MANIFEST_URL}

normalize_path() {
    "$python_bin" - "$1" <<'PY'
import os
import sys

print(os.path.abspath(os.path.expanduser(sys.argv[1])))
PY
}

install_root=$(normalize_path "$install_root")
bin_dir=$(normalize_path "$bin_dir")
versions_dir=$install_root/versions
install_json=$install_root/install.json
link_path=$bin_dir/taplctl

mkdir -p "$install_root" "$versions_dir" "$bin_dir" || die "could not create installation directories."

managed_install=0
managed_venv=
install_json_exists=0
if [ -e "$install_json" ] || [ -L "$install_json" ]; then
    install_json_exists=1
fi
if [ -f "$install_json" ]; then
    if managed_venv=$("$python_bin" - "$install_json" "$install_root" "$bin_dir" "$versions_dir" "$link_path" <<'PY'
import json
import os
import re
import sys
from pathlib import Path

try:
    metadata = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    install_root = os.path.abspath(sys.argv[2])
    bin_dir = os.path.abspath(sys.argv[3])
    versions_dir = os.path.abspath(sys.argv[4])
    link_path = os.path.abspath(sys.argv[5])

    if (
        not isinstance(metadata, dict)
        or metadata.get("schema_version") != 1
        or isinstance(metadata.get("schema_version"), bool)
    ):
        raise ValueError
    if metadata.get("method") != "curl-sh":
        raise ValueError
    if metadata.get("install_root") != install_root:
        raise ValueError
    if metadata.get("bin_dir") != bin_dir:
        raise ValueError
    if metadata.get("executable") != link_path:
        raise ValueError
    if not isinstance(metadata.get("manifest_url"), str) or not metadata["manifest_url"]:
        raise ValueError
    if not isinstance(metadata.get("wheel_url"), str) or not metadata["wheel_url"]:
        raise ValueError
    if not isinstance(metadata.get("version"), str) or re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+(?:(?:a|b|rc)[0-9]+)?", metadata["version"]) is None:
        raise ValueError
    if not isinstance(metadata.get("wheel_sha256"), str) or re.fullmatch(r"[0-9a-fA-F]{64}", metadata["wheel_sha256"]) is None:
        raise ValueError

    venv = metadata["venv"]
    if not isinstance(venv, str):
        raise ValueError
    venv = os.path.abspath(venv)
    if os.path.commonpath((venv, versions_dir)) != versions_dir or venv == versions_dir:
        raise ValueError
except (KeyError, OSError, UnicodeError, ValueError, json.JSONDecodeError):
    raise SystemExit(1)

print(venv)
PY
    ); then
        managed_install=1
    else
        managed_venv=
    fi
fi

if [ "$install_json_exists" -eq 1 ] && [ "$managed_install" -ne 1 ]; then
    die "$install_json exists but is not valid schema 1 curl-sh install metadata; refusing to overwrite it."
fi

if [ -e "$link_path" ] || [ -L "$link_path" ]; then
    if [ "$managed_install" -ne 1 ]; then
        die "$link_path already exists and is not managed by a valid curl-sh install.json; move it or choose TAPL_BIN_DIR."
    fi
    if previous_link_target=$("$python_bin" - "$link_path" "$managed_venv/bin/taplctl" <<'PY'
import os
import sys

link_path = sys.argv[1]
expected = os.path.abspath(sys.argv[2])
if not os.path.islink(link_path):
    raise SystemExit(1)
target = os.readlink(link_path)
if not os.path.isabs(target):
    resolved_target = os.path.abspath(os.path.join(os.path.dirname(link_path), target))
else:
    resolved_target = os.path.abspath(target)
if resolved_target != expected:
    raise SystemExit(1)
print(target)
PY
    ); then
        had_existing_link=1
    else
        die "$link_path does not point to the executable recorded by the managed curl-sh installation; refusing to overwrite it."
    fi
fi

work_dir=$(mktemp -d "${TMPDIR:-/tmp}/tapl-install.XXXXXX") || die "could not create a temporary directory."
manifest_file=$work_dir/taplctl-install-manifest.json

note "fetching the latest release manifest"
manifest_curl_error=$work_dir/manifest-curl-error
if ! curl --fail --location --silent --show-error --retry 3 --output "$manifest_file" "$manifest_url" 2>"$manifest_curl_error"; then
    die "could not download the release manifest."
fi

if ! "$python_bin" - "$manifest_file" "$work_dir" <<'PY'
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

manifest_path = Path(sys.argv[1])
output_dir = Path(sys.argv[2])

try:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
except (OSError, UnicodeError, json.JSONDecodeError) as exc:
    raise SystemExit(f"invalid release manifest: {exc}")

if not isinstance(manifest, dict):
    raise SystemExit("invalid release manifest: root must be an object")
if manifest.get("schema_version") != 1 or isinstance(manifest.get("schema_version"), bool):
    raise SystemExit("unsupported release manifest schema_version")

version = manifest.get("version")
if not isinstance(version, str) or re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+(?:(?:a|b|rc)[0-9]+)?", version) is None:
    raise SystemExit("invalid release manifest version")

wheel = manifest.get("wheel")
if not isinstance(wheel, dict):
    raise SystemExit("invalid release manifest wheel")

wheel_url = wheel.get("url")
if not isinstance(wheel_url, str) or not wheel_url or any(char in wheel_url for char in "\r\n\t"):
    raise SystemExit("invalid release manifest wheel URL")

wheel_sha256 = wheel.get("sha256")
if not isinstance(wheel_sha256, str) or re.fullmatch(r"[0-9a-fA-F]{64}", wheel_sha256) is None:
    raise SystemExit("invalid release manifest wheel SHA-256")
wheel_sha256 = wheel_sha256.lower()

wheel_name = os.path.basename(urlsplit(wheel_url).path)
if not wheel_name.endswith(".whl") or re.fullmatch(r"[A-Za-z0-9_.+-]+", wheel_name) is None:
    raise SystemExit("invalid release manifest wheel filename")

fields = {
    "version": version,
    "wheel-url": wheel_url,
    "wheel-sha256": wheel_sha256,
    "wheel-name": wheel_name,
}
for name, value in fields.items():
    (output_dir / name).write_text(value, encoding="utf-8")
PY
then
    die "release manifest validation failed."
fi

manifest_version=$(cat "$work_dir/version")
wheel_url=$(cat "$work_dir/wheel-url")
wheel_sha256=$(cat "$work_dir/wheel-sha256")
wheel_name=$(cat "$work_dir/wheel-name")

if [ "$managed_install" -eq 1 ]; then
    managed_version=$("$python_bin" - "$install_json" <<'PY'
import json
import sys
from pathlib import Path

metadata = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
print(metadata["version"])
PY
    ) || die "could not read the managed taplctl version from install.json."

    version_order=$("$python_bin" - "$managed_version" "$manifest_version" <<'PY'
import sys
import re

version_re = re.compile(
    r"(?P<major>[0-9]+)\.(?P<minor>[0-9]+)\.(?P<patch>[0-9]+)"
    r"(?:(?P<stage>a|b|rc)(?P<serial>[0-9]+))?"
)
stage_rank = {"a": 0, "b": 1, "rc": 2, None: 3}

def version_key(value):
    match = version_re.fullmatch(value)
    if match is None:
        raise ValueError("invalid version")
    stage = match.group("stage")
    return (
        int(match.group("major")),
        int(match.group("minor")),
        int(match.group("patch")),
        stage_rank[stage],
        int(match.group("serial")) if stage is not None else 0,
    )

installed = version_key(sys.argv[1])
published = version_key(sys.argv[2])
if installed > published:
    print("newer")
elif installed < published:
    print("older")
else:
    print("same")
PY
    ) || die "could not compare installed and published taplctl versions."

    if [ "$version_order" = "newer" ]; then
        if [ "$had_existing_link" -ne 1 ]; then
            die "installed taplctl $managed_version is newer than published release $manifest_version, but its managed command link is missing."
        fi
        expected_managed_version_output="taplctl $managed_version"
        if managed_version_output=$("$managed_venv/bin/taplctl" --version 2>/dev/null) &&
            [ "$managed_version_output" = "$expected_managed_version_output" ]
        then
            note "installed taplctl $managed_version is newer than published release $manifest_version; leaving it unchanged"
            exit 0
        fi
        die "managed taplctl command version does not match install.json (expected $expected_managed_version_output)."
    fi
fi

current_venv=
if [ "$managed_install" -eq 1 ]; then
    if current_venv=$("$python_bin" - "$install_json" "$manifest_version" "$wheel_sha256" "$versions_dir" <<'PY'
import json
import os
import sys
from pathlib import Path

try:
    metadata = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    expected_version = sys.argv[2]
    expected_sha256 = sys.argv[3]
    versions_dir = os.path.abspath(sys.argv[4])
    venv = metadata["venv"]
    if not isinstance(venv, str):
        raise ValueError
    venv = os.path.abspath(venv)
    if os.path.commonpath((venv, versions_dir)) != versions_dir:
        raise ValueError
    if metadata.get("method") != "curl-sh":
        raise ValueError
    if metadata.get("version") != expected_version:
        raise ValueError
    if metadata.get("wheel_sha256") != expected_sha256:
        raise ValueError
except (KeyError, OSError, UnicodeError, ValueError, json.JSONDecodeError):
    raise SystemExit(1)

print(venv)
PY
    ); then
        :
    else
        current_venv=
    fi
fi

expected_version_output="taplctl $manifest_version"
if [ -n "$current_venv" ] && [ -x "$current_venv/bin/taplctl" ]; then
    if installed_version_output=$("$current_venv/bin/taplctl" --version 2>/dev/null) &&
        [ "$installed_version_output" = "$expected_version_output" ]
    then
        note "version $manifest_version is already installed"
    else
        current_venv=
    fi
else
    current_venv=
fi

if [ -z "$current_venv" ]; then
    wheel_path=$work_dir/$wheel_name
    note "downloading taplctl $manifest_version"
    wheel_curl_error=$work_dir/wheel-curl-error
    if ! curl --fail --location --silent --show-error --retry 3 --output "$wheel_path" "$wheel_url" 2>"$wheel_curl_error"; then
        die "could not download the taplctl wheel."
    fi

    actual_sha256=$("$python_bin" - "$wheel_path" <<'PY'
import hashlib
import sys

digest = hashlib.sha256()
with open(sys.argv[1], "rb") as wheel:
    for chunk in iter(lambda: wheel.read(1024 * 1024), b""):
        digest.update(chunk)
print(digest.hexdigest())
PY
    ) || die "could not calculate the wheel SHA-256."

    if [ "$actual_sha256" != "$wheel_sha256" ]; then
        die "wheel SHA-256 mismatch (expected $wheel_sha256, got $actual_sha256)."
    fi
    note "wheel SHA-256 verified"

    sha_prefix=$(printf '%s' "$wheel_sha256" | cut -c 1-12)
    candidate_venv=$(mktemp -d "$versions_dir/$manifest_version-$sha_prefix.XXXXXX") ||
        die "could not create the taplctl virtual environment."
    candidate_incomplete=1

    note "creating a dedicated virtual environment"
    if ! "$python_bin" -m venv "$candidate_venv"; then
        die "could not create a virtual environment; install your distribution's Python venv package."
    fi

    note "installing taplctl $manifest_version"
    if ! "$candidate_venv/bin/python" -m pip install --disable-pip-version-check --upgrade "$wheel_path"; then
        die "pip could not install taplctl; the previous installation was left unchanged."
    fi

    if installed_version_output=$("$candidate_venv/bin/taplctl" --version 2>/dev/null) &&
        [ "$installed_version_output" = "$expected_version_output" ]
    then
        current_venv=$candidate_venv
    else
        die "the installed taplctl executable failed validation."
    fi
fi

install_json_tmp=$(mktemp "$install_root/.install.json.XXXXXX") || die "could not prepare install metadata."
if ! "$python_bin" - "$install_json_tmp" "$manifest_url" "$manifest_version" "$wheel_url" "$wheel_sha256" "$install_root" "$bin_dir" "$current_venv" "$link_path" <<'PY'
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

metadata = {
    "schema_version": 1,
    "method": "curl-sh",
    "manifest_url": sys.argv[2],
    "version": sys.argv[3],
    "wheel_url": sys.argv[4],
    "wheel_sha256": sys.argv[5],
    "install_root": sys.argv[6],
    "bin_dir": sys.argv[7],
    "venv": sys.argv[8],
    "executable": sys.argv[9],
    "installed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
}
Path(sys.argv[1]).write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY
then
    die "could not write install metadata."
fi

if [ -d "$link_path" ]; then
    die "$link_path is a directory; move it before installing taplctl."
fi
link_tmp=$bin_dir/.taplctl.tmp.$$
if [ -e "$link_tmp" ] || [ -L "$link_tmp" ]; then
    die "temporary link $link_tmp already exists."
fi
ln -s "$current_venv/bin/taplctl" "$link_tmp" || die "could not create the taplctl command link."
if ! mv -f "$link_tmp" "$link_path"; then
    die "could not activate the taplctl command link; the previous installation was left unchanged."
fi
link_tmp=
link_activated=1

trap '' 1 2 15
if ! mv -f "$install_json_tmp" "$install_json"; then
    if rollback_active_link; then
        if [ "$had_existing_link" -eq 1 ]; then
            rollback_message="the previous command link was restored"
        else
            rollback_message="the new command link was removed"
        fi
    else
        rollback_message="the previous command link could not be restored"
    fi
    trap 'exit 1' 1 2 15
    die "install metadata could not be activated; $rollback_message."
fi
install_json_tmp=
link_activated=0
candidate_incomplete=0
trap 'exit 1' 1 2 15

note "taplctl $manifest_version is installed at $link_path"
case ":${PATH:-}:" in
    *":$bin_dir:"*)
        ;;
    *)
        printf '\nAdd taplctl to PATH for future shells:\n'
        printf '  export PATH="%s:$PATH"\n' "$bin_dir"
        ;;
esac

printf '\nWorkflow hooks were not installed automatically. Install them when ready:\n'
printf '  taplctl install user\n'
