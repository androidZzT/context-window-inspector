from __future__ import annotations

import json
from pathlib import Path

from context_window_inspector.claude import parse_claude_session, resolve_claude_session
from context_window_inspector.reporting import render_json


def write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records),
        encoding="utf-8",
    )


def claude_records() -> list[dict]:
    return [
        {"type": "permission-mode", "permissionMode": "default", "sessionId": "claude-session-1"},
        {
            "type": "attachment",
            "sessionId": "claude-session-1",
            "cwd": "/work/demo",
            "timestamp": "2026-04-30T00:00:00Z",
            "attachment": {
                "type": "skill_listing",
                "content": "- context-budget: inspect context",
                "skillCount": 1,
            },
        },
        {
            "type": "user",
            "sessionId": "claude-session-1",
            "cwd": "/work/demo",
            "timestamp": "2026-04-30T00:00:01Z",
            "message": {"role": "user", "content": "hello"},
        },
        {
            "type": "assistant",
            "sessionId": "claude-session-1",
            "cwd": "/work/demo",
            "timestamp": "2026-04-30T00:00:02Z",
            "message": {
                "id": "msg-1",
                "model": "claude-opus-4-7",
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "tool-1",
                        "name": "Bash",
                        "input": {"command": "pwd"},
                    }
                ],
                "usage": {
                    "input_tokens": 10,
                    "cache_creation_input_tokens": 50,
                    "cache_creation": {
                        "ephemeral_5m_input_tokens": 20,
                        "ephemeral_1h_input_tokens": 30,
                    },
                    "cache_read_input_tokens": 100,
                    "output_tokens": 5,
                },
            },
        },
        {
            "type": "assistant",
            "sessionId": "claude-session-1",
            "cwd": "/work/demo",
            "timestamp": "2026-04-30T00:00:03Z",
            "message": {
                "id": "msg-1",
                "model": "claude-opus-4-7",
                "role": "assistant",
                "content": "duplicate stream record",
                "usage": {
                    "input_tokens": 10,
                    "cache_creation_input_tokens": 50,
                    "cache_creation": {
                        "ephemeral_5m_input_tokens": 20,
                        "ephemeral_1h_input_tokens": 30,
                    },
                    "cache_read_input_tokens": 100,
                    "output_tokens": 5,
                },
            },
        },
        {
            "type": "user",
            "sessionId": "claude-session-1",
            "cwd": "/work/demo",
            "timestamp": "2026-04-30T00:00:04Z",
            "message": {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "tool-1",
                        "content": "ok",
                    }
                ],
            },
        },
        {
            "type": "attachment",
            "sessionId": "claude-session-1",
            "cwd": "/work/demo",
            "timestamp": "2026-04-30T00:00:05Z",
            "attachment": {
                "type": "hook_success",
                "hookEvent": "UserPromptSubmit",
                "hookName": "PreToolUse:Bash",
                "stdout": "hook payload",
            },
        },
        {
            "type": "attachment",
            "sessionId": "claude-session-1",
            "cwd": "/work/demo",
            "timestamp": "2026-04-30T00:00:06Z",
            "attachment": {
                "type": "async_hook_response",
                "hookName": "PostToolUse:Write",
                "response": {"systemMessage": "async context"},
            },
        },
        {
            "type": "attachment",
            "sessionId": "claude-session-1",
            "cwd": "/work/demo",
            "timestamp": "2026-04-30T00:00:07Z",
            "attachment": {
                "type": "hook_success",
                "hookEvent": "PostToolUse",
                "hookName": "PostToolUse:Write",
                "stdout": "{\"tool_input\":{\"content\":\"large echoed write content\"}}",
            },
        },
    ]


def test_parse_claude_usage_dedup_and_buckets(tmp_path: Path) -> None:
    path = tmp_path / ".claude/projects/-work-demo/claude-session-1.jsonl"
    write_jsonl(path, claude_records())

    report = parse_claude_session(path)

    assert report.provider == "claude"
    assert report.session_id == "claude-session-1"
    assert report.project_path == "/work/demo"
    assert report.model == "claude-opus-4-7"
    assert report.latest_usage
    assert report.latest_usage.total_tokens == 165
    assert report.latest_usage.cache_creation_5m_input_tokens == 20
    assert report.latest_usage.cache_creation_1h_input_tokens == 30
    assert report.total_usage
    assert report.total_usage.total_tokens == 165
    assert len(report.usage_events) == 1
    assert report.buckets["skills"].record_count == 1
    assert report.buckets["tool_calls"].record_count == 1
    assert report.buckets["tool_results"].record_count == 1
    assert report.buckets["hooks"].record_count == 2
    assert report.buckets["unknown"].record_count == 0


def test_resolve_claude_session_by_prefix(tmp_path: Path) -> None:
    path = tmp_path / ".claude/projects/-work-demo/claude-session-1.jsonl"
    write_jsonl(path, claude_records())

    resolved = resolve_claude_session("claude-session", latest=False, home=tmp_path)

    assert resolved == path


def test_claude_json_output(tmp_path: Path) -> None:
    path = tmp_path / "claude-session-1.jsonl"
    write_jsonl(path, claude_records())

    data = json.loads(render_json(parse_claude_session(path), include_events=True))

    assert data["exact_usage"]["latest"]["cache_read_input_tokens"] == 100
    assert data["exact_usage"]["latest"]["cache_creation_5m_input_tokens"] == 20
    assert data["estimated_cost"]["latest"]["available"] is True
    assert data["observable_buckets"][0]["record_count"] >= 1
