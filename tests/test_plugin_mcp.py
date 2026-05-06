from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records),
        encoding="utf-8",
    )


def test_context_window_plugin_mcp_statusline(tmp_path: Path) -> None:
    session = tmp_path / "rollout-test.jsonl"
    write_jsonl(
        session,
        [
            {
                "type": "session_meta",
                "payload": {
                    "id": "codex-plugin-test",
                    "cwd": "/work/demo",
                    "base_instructions": {"text": "base"},
                },
            },
            {
                "type": "turn_context",
                "payload": {
                    "model": "gpt-5.5",
                    "user_instructions": "project instructions",
                },
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "function_call_output",
                    "call_id": "call-1",
                    "output": "tool output",
                },
            },
            {
                "timestamp": "2026-05-06T00:00:00Z",
                "type": "event_msg",
                "payload": {
                    "type": "token_count",
                    "info": {
                        "last_token_usage": {
                            "input_tokens": 50,
                            "output_tokens": 10,
                            "total_tokens": 60,
                        },
                        "model_context_window": 100,
                    },
                },
            },
        ],
    )
    script = (
        Path(__file__).resolve().parents[1]
        / "plugins/context-window-inspector/scripts/context_window_mcp.py"
    )
    request_lines = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "0"},
            },
        },
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "get_codex_context_window",
                "arguments": {
                    "session": str(session),
                    "format": "statusline",
                    "width": 120,
                },
            },
        },
    ]

    result = subprocess.run(
        [sys.executable, str(script)],
        cwd=script.parents[1],
        input="\n".join(json.dumps(line) for line in request_lines) + "\n",
        text=True,
        capture_output=True,
        check=True,
    )

    responses = [json.loads(line) for line in result.stdout.splitlines()]
    assert responses[0]["result"]["serverInfo"]["name"] == "context-window-inspector"
    assert responses[1]["result"]["tools"][0]["name"] == "get_codex_context_window"
    text = responses[2]["result"]["content"][0]["text"]
    assert "ctx 60.0%" in text
    assert "60/100" in text
