#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PLUGIN_ROOT.parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from context_window_inspector.codex import parse_codex_session, resolve_codex_session
from context_window_inspector.models import estimated_bucket_dicts
from context_window_inspector.pricing import estimate_report_costs
from context_window_inspector.statusline import render_statusline


SERVER_NAME = "context-window-inspector"
SERVER_VERSION = "0.1.0"


def main() -> int:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
            response = handle_request(request)
        except Exception as exc:  # MCP servers should fail per-request, not crash.
            response = _error_response(None, -32603, str(exc))
        if response is not None:
            print(json.dumps(response, ensure_ascii=False), flush=True)
    return 0


def handle_request(request: dict[str, Any]) -> dict[str, Any] | None:
    method = request.get("method")
    request_id = request.get("id")
    if method == "initialize":
        return _result_response(
            request_id,
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            },
        )
    if method == "notifications/initialized":
        return None
    if method == "tools/list":
        return _result_response(request_id, {"tools": [_tool_schema()]})
    if method == "tools/call":
        params = request.get("params")
        if not isinstance(params, dict):
            return _error_response(request_id, -32602, "Missing params.")
        name = params.get("name")
        arguments = params.get("arguments") or {}
        if name != "get_codex_context_window":
            return _error_response(request_id, -32601, f"Unknown tool: {name}")
        if not isinstance(arguments, dict):
            return _error_response(request_id, -32602, "Tool arguments must be an object.")
        try:
            text = get_codex_context_window(arguments)
        except Exception as exc:
            return _error_response(request_id, -32000, str(exc))
        return _result_response(request_id, {"content": [{"type": "text", "text": text}]})
    return _error_response(request_id, -32601, f"Unknown method: {method}")


def get_codex_context_window(arguments: dict[str, Any]) -> str:
    selector = arguments.get("session")
    if selector is not None and not isinstance(selector, str):
        raise ValueError("session must be a string when provided.")
    report = parse_codex_session(resolve_codex_session(selector, latest=not selector))
    output_format = str(arguments.get("format") or "summary")
    top = _bounded_int(arguments.get("top"), default=8, minimum=1, maximum=20)
    width = _bounded_int(arguments.get("width"), default=160, minimum=80, maximum=240)

    if output_format == "json":
        return json.dumps(report.to_dict(include_events=False), ensure_ascii=False, indent=2)
    if output_format == "statusline":
        return render_statusline(
            report,
            color=False,
            ascii_only=True,
            top=top,
            width=width,
            include_model=True,
        )
    if output_format != "summary":
        raise ValueError("format must be one of: summary, statusline, json.")
    return _summary(report, top=top, width=width)


def _summary(report: Any, *, top: int, width: int) -> str:
    usage = report.latest_usage
    line = render_statusline(
        report,
        color=False,
        ascii_only=True,
        top=min(top, 6),
        width=width,
        include_model=True,
    )
    lines = [line, ""]
    lines.append(f"Provider: {report.provider}")
    lines.append(f"Session: {report.session_id}")
    if report.model:
        lines.append(f"Model: {report.model}")
    if report.context_window:
        lines.append(f"Context window: {_fmt(report.context_window)} tokens")
    if usage:
        percent = usage.total_tokens / report.context_window * 100 if report.context_window else 0
        lines.append(
            "Latest usage: "
            f"{_fmt(usage.total_tokens)} total "
            f"({_fmt(usage.input_tokens)} input, "
            f"{_fmt(usage.cached_input_tokens)} cached input, "
            f"{_fmt(usage.output_tokens)} output, "
            f"{_fmt(usage.reasoning_output_tokens)} reasoning)"
        )
        if report.context_window:
            lines.append(f"Window used: {percent:.1f}%")

    costs = estimate_report_costs(report)
    latest_cost = costs.get("latest")
    if isinstance(latest_cost, dict) and latest_cost.get("available"):
        lines.append(f"Estimated API-equivalent latest cost: ${latest_cost['total']:.6f}")

    items = [
        item
        for item in estimated_bucket_dicts(report)
        if item.get("estimated_window_percent") is not None
    ]
    items.sort(key=lambda item: float(item["estimated_window_percent"]), reverse=True)
    if items:
        lines.extend(["", "Estimated context buckets:"])
        for item in items[:top]:
            lines.append(
                f"- {item['name']}: "
                f"{float(item['estimated_window_percent']):.1f}% "
                f"({_fmt(int(item['estimated_tokens']))} tokens, "
                f"{_fmt(int(item['byte_count']))} bytes, "
                f"{item['record_count']} records)"
            )
    if report.warnings:
        lines.extend(["", "Warnings:"])
        lines.extend(f"- {warning}" for warning in report.warnings)
    return "\n".join(lines)


def _tool_schema() -> dict[str, Any]:
    return {
        "name": "get_codex_context_window",
        "description": (
            "Inspect the latest Codex session context-window usage from local JSONL logs. "
            "Returns exact token usage plus estimated bucket attribution."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "session": {
                    "type": "string",
                    "description": "Optional Codex session id prefix or rollout JSONL path. Defaults to latest session.",
                },
                "format": {
                    "type": "string",
                    "enum": ["summary", "statusline", "json"],
                    "description": "Output shape. summary is human-readable; statusline is compact; json is machine-readable.",
                    "default": "summary",
                },
                "top": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 20,
                    "description": "Maximum number of estimated context buckets to include.",
                    "default": 8,
                },
                "width": {
                    "type": "integer",
                    "minimum": 80,
                    "maximum": 240,
                    "description": "Maximum width for statusline rendering.",
                    "default": 160,
                },
            },
            "additionalProperties": False,
        },
    }


def _result_response(request_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _error_response(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def _bounded_int(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, parsed))


def _fmt(value: int) -> str:
    return f"{value:,}"


if __name__ == "__main__":
    raise SystemExit(main())
