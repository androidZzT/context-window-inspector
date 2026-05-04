from __future__ import annotations

import json
from pathlib import Path

from context_window_inspector.codex import _usage_from_openai, parse_codex_session, resolve_codex_session
from context_window_inspector.reporting import render_json, render_markdown


def write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records),
        encoding="utf-8",
    )


def codex_records() -> list[dict]:
    return [
        {
            "timestamp": "2026-04-30T00:00:00Z",
            "type": "session_meta",
            "payload": {
                "id": "codex-session-1",
                "cwd": "/work/demo",
                "base_instructions": {
                    "text": "base rules <skills_instructions>skill list</skills_instructions>",
                },
            },
        },
        {
            "timestamp": "2026-04-30T00:00:01Z",
            "type": "turn_context",
            "payload": {
                "turn_id": "turn-1",
                "cwd": "/work/demo",
                "model": "gpt-5.5",
                "summary": "none",
                "user_instructions": "AGENTS.md content",
            },
        },
        {
            "timestamp": "2026-04-30T00:00:02Z",
            "type": "event_msg",
            "payload": {"type": "user_message", "message": "hello"},
        },
        {
            "timestamp": "2026-04-30T00:00:03Z",
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "developer",
                "content": [
                    {
                        "type": "input_text",
                        "text": "<plugins_instructions>plugin metadata</plugins_instructions>developer rules",
                    }
                ],
            },
        },
        {
            "timestamp": "2026-04-30T00:00:04Z",
            "type": "response_item",
            "payload": {
                "type": "function_call",
                "name": "exec_command",
                "arguments": "{\"cmd\":\"pwd\"}",
                "call_id": "call-1",
            },
        },
        {
            "timestamp": "2026-04-30T00:00:05Z",
            "type": "event_msg",
            "payload": {
                "type": "token_count",
                "info": {
                    "last_token_usage": {
                        "input_tokens": 100,
                        "cached_input_tokens": 40,
                        "output_tokens": 10,
                        "reasoning_output_tokens": 2,
                        "total_tokens": 112,
                    },
                    "total_token_usage": {
                        "input_tokens": 200,
                        "cached_input_tokens": 80,
                        "output_tokens": 30,
                        "reasoning_output_tokens": 5,
                        "total_tokens": 235,
                    },
                    "model_context_window": 1000,
                },
            },
        },
        {
            "timestamp": "2026-04-30T00:00:06Z",
            "type": "event_msg",
            "payload": {"type": "agent_message", "message": "done"},
        },
    ]


def test_parse_codex_exact_usage_and_buckets(tmp_path: Path) -> None:
    path = tmp_path / ".codex/sessions/2026/04/30/rollout-test.jsonl"
    write_jsonl(path, codex_records())

    report = parse_codex_session(path, home=tmp_path)

    assert report.provider == "codex"
    assert report.session_id == "codex-session-1"
    assert report.project_path == "/work/demo"
    assert report.model == "gpt-5.5"
    assert report.context_window == 1000
    assert report.latest_usage
    assert report.latest_usage.total_tokens == 112
    assert report.total_usage
    assert report.total_usage.total_tokens == 235
    assert report.buckets["skills"].record_count == 1
    assert report.buckets["mcp_or_dynamic_tools"].record_count == 1
    assert report.buckets["developer_or_mode_instructions"].record_count >= 1
    assert report.buckets["tool_calls"].record_count == 1
    assert report.buckets["user_messages"].record_count == 1


def test_resolve_codex_session_by_prefix(tmp_path: Path) -> None:
    path = tmp_path / ".codex/sessions/2026/04/30/rollout-test.jsonl"
    write_jsonl(path, codex_records())

    resolved = resolve_codex_session("codex-session", latest=False, home=tmp_path)

    assert resolved == path


def test_codex_report_outputs(tmp_path: Path) -> None:
    path = tmp_path / "rollout-test.jsonl"
    write_jsonl(path, codex_records())
    report = parse_codex_session(path, home=tmp_path)

    markdown = render_markdown(report, include_events=True)
    data = json.loads(render_json(report, include_events=True))

    assert "Exact Token Usage" in markdown
    assert "Estimated Window Split" in markdown
    assert data["exact_usage"]["latest"]["total_tokens"] == 112
    assert data["usage_events"][0]["usage"]["input_tokens"] == 100
    assert data["observable_buckets"][0]["estimated_window_percent"] > 0


def test_codex_buckets_use_active_context_after_compaction(tmp_path: Path) -> None:
    records = [
        {
            "type": "session_meta",
            "payload": {
                "id": "codex-session-compact",
                "base_instructions": {"text": "base"},
            },
        },
        {
            "type": "response_item",
            "payload": {
                "type": "function_call_output",
                "call_id": "old",
                "output": "old output should not be active",
            },
        },
        {
            "type": "compacted",
            "payload": {"replacement_history": [{"content": "summary of old output"}]},
        },
        {
            "type": "turn_context",
            "payload": {
                "model": "gpt-5.5",
                "summary": "none",
                "user_instructions": "project instructions",
            },
        },
        {
            "type": "response_item",
            "payload": {
                "type": "function_call_output",
                "call_id": "new",
                "output": "new active output",
            },
        },
        {
            "timestamp": "2026-04-30T00:00:05Z",
            "type": "event_msg",
            "payload": {
                "type": "token_count",
                "info": {
                    "last_token_usage": {"input_tokens": 50, "output_tokens": 10, "total_tokens": 60},
                    "model_context_window": 100,
                },
            },
        },
    ]
    path = tmp_path / "rollout-compact.jsonl"
    write_jsonl(path, records)

    report = parse_codex_session(path, home=tmp_path)

    assert report.buckets["tool_results"].record_count == 1
    assert report.buckets["tool_results"].examples == ["tool_result.new"]
    assert report.buckets["summaries"].record_count == 1


def test_openai_usage_nested_details_are_not_double_counted() -> None:
    usage = _usage_from_openai(
        {
            "input_tokens": 100,
            "input_tokens_details": {"cached_tokens": 40},
            "output_tokens": 10,
            "output_tokens_details": {"reasoning_tokens": 2},
        }
    )

    assert usage.cached_input_tokens == 40
    assert usage.reasoning_output_tokens == 2
    assert usage.total_tokens == 110
