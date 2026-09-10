#!/bin/bash
# Sign a downloaded wheelhouse using an ephemeral CI keychain.
set +x
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "Usage: $0 WHEELHOUSE" >&2
  exit 1
fi
for name in MACOS_CERTIFICATE_P12_BASE64 MACOS_CERTIFICATE_PASSWORD APPLE_TEAM_ID; do
  if [[ -z "${!name:-}" ]]; then
    echo "Set ${name} before releasing macOS runtimes; see .github/MACOS_SIGNING.md." >&2
    exit 1
  fi
done
if [[ "$(uname -s)" != Darwin ]]; then
  echo "Developer ID signing requires macOS." >&2
  exit 1
fi

umask 077
signing_dir="$(mktemp -d "${RUNNER_TEMP:-${TMPDIR:-/tmp}}/tapl-signing.XXXXXX")"
keychain_path="${signing_dir}/signing.keychain-db"
certificate_path="${signing_dir}/certificate.p12"
keychain_list_path="${signing_dir}/original-keychains.json"
cleanup() {
  if [[ -f "${keychain_list_path}" ]]; then
    python - "${keychain_list_path}" <<'PY' || true
import json
from pathlib import Path
import subprocess
import sys

previous = json.loads(Path(sys.argv[1]).read_text())
subprocess.run(["security", "list-keychains", "-d", "user", "-s", *previous], check=True)
PY
  fi
  if [[ -f "${keychain_path}" ]]; then
    security delete-keychain "${keychain_path}" >/dev/null 2>&1 || true
  fi
  rm -rf "${signing_dir}"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

python - "${certificate_path}" <<'PY'
import base64
import os
from pathlib import Path
import sys

encoded = "".join(os.environ["MACOS_CERTIFICATE_P12_BASE64"].split())
Path(sys.argv[1]).write_bytes(base64.b64decode(encoded, validate=True))
PY
unset MACOS_CERTIFICATE_P12_BASE64
python - "${keychain_list_path}" <<'PY'
import json
from pathlib import Path
import shlex
import subprocess
import sys

previous = subprocess.check_output(["security", "list-keychains", "-d", "user"], text=True)
Path(sys.argv[1]).write_text(json.dumps(shlex.split(previous)))
PY
keychain_password="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
security create-keychain -p "${keychain_password}" "${keychain_path}"
security set-keychain-settings -lut 3600 "${keychain_path}"
security unlock-keychain -p "${keychain_password}" "${keychain_path}"
security import "${certificate_path}" -P "${MACOS_CERTIFICATE_PASSWORD}" \
  -T /usr/bin/codesign -t cert -f pkcs12 -k "${keychain_path}" >/dev/null
security set-key-partition-list -S apple-tool:,apple:,codesign: \
  -s -k "${keychain_password}" "${keychain_path}" >/dev/null
# codesign also needs the identity's keychain in the user search list, even
# when --keychain is supplied. Preserve the runner's original search order.
python - "${keychain_list_path}" "${keychain_path}" <<'PY'
import json
from pathlib import Path
import subprocess
import sys

previous = json.loads(Path(sys.argv[1]).read_text())
subprocess.run(["security", "list-keychains", "-d", "user", "-s", sys.argv[2], *previous], check=True)
PY
unset MACOS_CERTIFICATE_PASSWORD keychain_password
rm -f "${certificate_path}"

script_dir="$(cd "$(dirname "$0")" && pwd)"
python "${script_dir}/sign_macos_wheels.py" "$1" --keychain "${keychain_path}"
