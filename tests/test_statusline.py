from __future__ import annotations

import json
from pathlib import Path

from context_window_inspector.install import install_claude_statusline, install_codex_statusline
from context_window_inspector.models import ExactUsage, SessionReport
from context_window_inspector.statusline import apply_status_input, render_statusline


def make_report(tmp_path: Path) -> SessionReport:
    report = SessionReport(
        provider="codex",
        session_id="session-1",
        file_path=tmp_path / "rollout.jsonl",
        model="gpt-5.5",
        context_window=100,
        latest_usage=ExactUsage(input_tokens=80, output_tokens=20, total_tokens=100),
    )
    report.add_bucket("assistant_messages", "a" * 500, "assistant")
    report.add_bucket("tool_results", "t" * 300, "tool")
    report.add_bucket("system_or_base_instructions", "s" * 200, "system")
    return report


def test_statusline_orders_estimated_bucket_split(tmp_path: Path) -> None:
    line = render_statusline(make_report(tmp_path), color=False, ascii_only=True, width=200)

    assert "ctx 100.0%" in line
    assert line.index("asst 50.0") < line.index("tool 30.0")
    assert line.index("tool 30.0") < line.index("sys 20.0")


def test_apply_status_input_overrides_claude_usage(tmp_path: Path) -> None:
    report = make_report(tmp_path)
    report.provider = "claude"
    data = {
        "model": {"display_name": "Opus"},
        "workspace": {"current_dir": "/work/demo"},
        "context_window": {
            "context_window_size": 2000,
            "current_usage": {
                "input_tokens": 10,
                "cache_creation_input_tokens": 20,
                "cache_read_input_tokens": 30,
                "output_tokens": 5,
            },
        },
    }

    apply_status_input(report, data)

    assert report.model == "Opus"
    assert report.project_path == "/work/demo"
    assert report.context_window == 2000
    assert report.latest_usage
    assert report.latest_usage.total_tokens == 65

    line = render_statusline(report, color=False, ascii_only=True, width=160)
    assert "ctx 3.0%" in line
    assert "60/2K" in line


def test_install_statusline_helpers(tmp_path: Path) -> None:
    messages = install_claude_statusline(tmp_path)
    messages.extend(install_codex_statusline(tmp_path))

    settings = json.loads((tmp_path / ".claude/settings.json").read_text(encoding="utf-8"))
    config = (tmp_path / ".codex/config.toml").read_text(encoding="utf-8")

    assert settings["statusLine"]["command"] == 'bash "$HOME/.claude/statusline-cwi.sh"'
    assert "context-used" in config
    assert "used-tokens" in config
    assert any("Codex CLI currently accepts built-in" in message for message in messages)
    assert any("Restart Codex" in message for message in messages)
