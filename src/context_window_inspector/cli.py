from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .claude import parse_claude_session, resolve_claude_session
from .codex import parse_codex_session, resolve_codex_session
from .install import install_claude_statusline, install_codex_statusline
from .reporting import render_json, render_markdown
from .statusline import (
    apply_status_input,
    read_status_input,
    render_statusline,
    session_selector_from_status_input,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cw-inspect",
        description="Inspect Claude Code and Codex context window usage from local session logs.",
    )
    subparsers = parser.add_subparsers(dest="provider", required=True)
    for provider in ("codex", "claude"):
        sub = subparsers.add_parser(provider, help=f"Inspect {provider} sessions")
        sub.add_argument("--latest", action="store_true", help="Inspect the newest local session")
        sub.add_argument("--session", help="Session id prefix or JSONL path")
        sub.add_argument("--json", action="store_true", help="Print machine-readable JSON")
        sub.add_argument("--all-turns", action="store_true", help="Include every exact usage event")
        sub.add_argument("--home", type=Path, help=argparse.SUPPRESS)
    status = subparsers.add_parser("statusline", help="Render a one-line context split for status bars")
    status.add_argument("source", choices=("codex", "claude"), help="Session provider")
    status.add_argument("--latest", action="store_true", help="Inspect the newest local session")
    status.add_argument("--session", help="Session id prefix or JSONL path")
    status.add_argument("--stdin", action="store_true", help="Read Claude Code statusLine JSON from stdin")
    status.add_argument("--no-color", action="store_true", help="Disable ANSI color")
    status.add_argument("--ascii", action="store_true", help="Use ASCII-only bar characters")
    status.add_argument("--top", type=int, default=5, help="Number of bucket segments to show")
    status.add_argument("--width", type=int, default=120, help="Maximum output width")
    status.add_argument("--no-model", action="store_true", help="Hide model name in statusline output")
    status.add_argument("--home", type=Path, help=argparse.SUPPRESS)
    install = subparsers.add_parser("install-statusline", help="Install statusline integration helpers")
    install.add_argument("source", choices=("codex", "claude", "all"), help="Integration target")
    install.add_argument("--home", type=Path, help=argparse.SUPPRESS)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.provider == "install-statusline":
        return _install_statusline(args)
    if args.provider == "statusline":
        return _render_statusline(args)

    latest = args.latest or not args.session
    home = args.home.expanduser() if args.home else None

    try:
        if args.provider == "codex":
            path = resolve_codex_session(args.session, latest=latest, home=home)
            report = parse_codex_session(path, home=home)
        else:
            path = resolve_claude_session(args.session, latest=latest, home=home)
            report = parse_claude_session(path)
    except FileNotFoundError as exc:
        print(f"cw-inspect: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(render_json(report, include_events=args.all_turns))
    else:
        print(render_markdown(report, include_events=args.all_turns))
    return 0


def _render_statusline(args: argparse.Namespace) -> int:
    home = args.home.expanduser() if args.home else None
    status_input = read_status_input(sys.stdin.read()) if args.stdin or not sys.stdin.isatty() else {}
    selector = args.session or session_selector_from_status_input(status_input)
    latest = args.latest or not selector
    try:
        if args.source == "codex":
            path = resolve_codex_session(selector, latest=latest, home=home)
            report = parse_codex_session(path, home=home)
        else:
            path = resolve_claude_session(selector, latest=latest, home=home)
            report = parse_claude_session(path)
        apply_status_input(report, status_input)
        print(
            render_statusline(
                report,
                color=not args.no_color,
                ascii_only=args.ascii,
                top=args.top,
                width=args.width,
                include_model=not args.no_model,
            )
        )
    except FileNotFoundError:
        print("ctx n/a")
    return 0


def _install_statusline(args: argparse.Namespace) -> int:
    home = args.home.expanduser() if args.home else None
    messages: list[str] = []
    if args.source in {"claude", "all"}:
        messages.extend(install_claude_statusline(home))
    if args.source in {"codex", "all"}:
        messages.extend(install_codex_statusline(home))
    for message in messages:
        print(message)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
