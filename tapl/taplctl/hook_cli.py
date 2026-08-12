"""Dedicated command-line entry point for TAPL Codex hook events."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import cli


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tapl-hook",
        description="Handle one Codex hook event through TAPL.",
    )
    parser.add_argument("--event", required=True, help="Codex hook event name.")
    parser.add_argument(
        "--mode",
        choices=("observe", "enforce"),
        default="observe",
        help="Hook handling mode.",
    )
    parser.add_argument("--tool", default=None, help="Tool name for tool hook events.")
    parser.add_argument("--db", type=Path, default=None, help="Path to tapl SQLite DB.")
    parser.add_argument("--config", type=Path, default=None, help="Path to tapl TOML config.")
    output = parser.add_mutually_exclusive_group()
    output.add_argument("--json", action="store_true", help=cli.JSON_HELP)
    output.add_argument("--agent", action="store_true", help=cli.AGENT_HELP)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(sys.argv[1:] if argv is None else argv)
    try:
        return int(cli.cmd_hook_event(args) or 0)
    except Exception as exc:
        if args.json:
            cli.print_json({"ok": False, "error": str(exc)})
        elif args.agent:
            print(cli.agent_error(str(exc)))
        else:
            print(f"tapl-hook: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
