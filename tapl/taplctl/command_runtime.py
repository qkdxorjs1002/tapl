"""Shell-independent Windows hook launchers and their ownership metadata."""

from __future__ import annotations

import base64
import binascii
import re
import sys


_PREFIX = "powershell.exe -NoProfile -NonInteractive -OutputFormat Text -EncodedCommand "
_STDIO = (
    "$OutputEncoding = [Console]::InputEncoding = [Console]::OutputEncoding = "
    "[System.Text.UTF8Encoding]::new($false); [Console]::In.ReadToEnd() | "
)
_LITERAL = r"'((?:[^']|'')*)'"
_SCRIPT = re.compile(
    re.escape(_STDIO) + rf"& {_LITERAL} '--event' {_LITERAL} '--mode' {_LITERAL}; exit \$LASTEXITCODE"
)


def configure_stdio() -> None:
    """Keep redirected Windows CLI and hook JSON in UTF-8, as Codex expects."""
    if sys.platform != "win32":
        return
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8")


def windows_hook_command(executable: str, event: str, mode: str) -> str:
    # The outer Codex shell can be either cmd or PowerShell. An encoded script
    # keeps executable paths (including spaces, apostrophes and shell syntax)
    # literal in both. Blocking uses the hook JSON protocol because an outer
    # PowerShell -Command coerces a native nonzero exit code to 1.
    def literal(value: str) -> str:
        return "'" + value.replace("'", "''") + "'"

    script = (
        _STDIO + f"& {literal(executable)} '--event' {literal(event)} '--mode' {literal(mode)}; "
        "exit $LASTEXITCODE"
    )
    return _PREFIX + base64.b64encode(script.encode("utf-16-le")).decode("ascii")


def windows_hook_tokens(command: str) -> list[str] | None:
    """Decode only our exact launcher shape, never arbitrary PowerShell code."""
    if not command.startswith(_PREFIX):
        return None
    try:
        encoded = command[len(_PREFIX):]
        script = base64.b64decode(encoded, validate=True).decode("utf-16-le")
    except (ValueError, UnicodeError, binascii.Error):
        return None
    match = _SCRIPT.fullmatch(script)
    if match is None:
        return None
    executable, event, mode = (part.replace("''", "'") for part in match.groups())
    # Newlines are valid PowerShell string content, but never an owned path.
    if any(char in executable for char in "\r\n") or mode not in {"observe", "enforce"}:
        return None
    return [executable, "--event", event, "--mode", mode]
