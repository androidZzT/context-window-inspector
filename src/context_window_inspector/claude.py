from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .models import ExactUsage, SessionReport, UsageEvent
from .util import label_from_text, newest, read_jsonl, stable_text


STDOUT_CONTEXT_EVENTS = {"SessionStart", "UserPromptSubmit", "UserPromptExpansion"}


def discover_claude_sessions(home: Path | None = None) -> list[Path]:
    root = (home or Path.home()) / ".claude" / "projects"
    if not root.exists():
        return []
    results: list[Path] = []
    for project in sorted(root.iterdir()):
        if not project.is_dir():
            continue
        for path in sorted(project.glob("*.jsonl")):
            if path.name.startswith("agent-") or "subagents" in path.parts:
                continue
            results.append(path)
    return results


def resolve_claude_session(selector: str | None, latest: bool, home: Path | None = None) -> Path:
    if selector:
        candidate = Path(selector).expanduser()
        if candidate.exists():
            return candidate
    sessions = discover_claude_sessions(home)
    if selector:
        matches = [path for path in sessions if selector in path.stem]
        if len(matches) == 1:
            return matches[0]
        if matches:
            return newest(matches) or matches[0]
        raise FileNotFoundError(f"No Claude Code session matched {selector!r}")
    if latest:
        path = newest(sessions)
        if path:
            return path
    raise FileNotFoundError("No Claude Code session found")


def parse_claude_session(path: Path) -> SessionReport:
    records = list(read_jsonl(path))
    session_id = path.stem
    report = SessionReport(provider="claude", session_id=session_id, file_path=path)

    usage_by_message: dict[str, UsageEvent] = {}
    usage_without_id: list[UsageEvent] = []
    for obj in records:
        session_id = obj.get("sessionId")
        if session_id and report.session_id == path.stem:
            report.session_id = str(session_id)
        cwd = obj.get("cwd")
        if cwd and not report.project_path:
            report.project_path = str(cwd)

        timestamp = str(obj.get("timestamp", ""))
        attachment = obj.get("attachment")
        if isinstance(attachment, dict):
            _parse_claude_attachment(report, attachment)
            continue

        record_type = obj.get("type")
        if record_type == "system":
            report.add_bucket("system_or_base_instructions", stable_text(obj), "system")
            continue
        if record_type in {"permission-mode", "last-prompt", "file-history-snapshot"}:
            report.add_bucket("developer_or_mode_instructions", stable_text(obj), str(record_type))
            continue
        if record_type not in {"user", "assistant"}:
            continue

        message = obj.get("message", {})
        if not isinstance(message, dict):
            continue
        content = message.get("content", "")
        if record_type == "user":
            if _contains_tool_result(content):
                report.add_bucket("tool_results", stable_text(content), "user.tool_result")
            else:
                text = stable_text(content)
                report.add_bucket("user_messages", text, label_from_text("user", text))
            continue

        model = message.get("model")
        if model:
            report.model = str(model)
        text = stable_text(content)
        report.add_bucket("assistant_messages", text, label_from_text("assistant", text))
        for tool_name, tool_input in _iter_tool_uses(content):
            report.add_bucket("tool_calls", stable_text(tool_input), f"tool_call.{tool_name}")

        usage = message.get("usage")
        if isinstance(usage, dict):
            event = UsageEvent(timestamp, _usage_from_anthropic(usage), "claude.message.usage")
            message_id = str(message.get("id", ""))
            if message_id:
                existing = usage_by_message.get(message_id)
                if not existing or event.usage.output_tokens >= existing.usage.output_tokens:
                    usage_by_message[message_id] = event
            else:
                usage_without_id.append(event)

    usage_events = sorted(
        [*usage_by_message.values(), *usage_without_id],
        key=lambda event: event.timestamp,
    )
    report.usage_events = usage_events
    total = ExactUsage()
    for event in usage_events:
        total.add(event.usage)
    if usage_events:
        report.latest_usage = usage_events[-1].usage
        report.total_usage = total.ensure_total()
    else:
        report.warnings.append("No exact token usage found in Claude assistant message usage fields.")
    return report


def _usage_from_anthropic(payload: dict[str, Any]) -> ExactUsage:
    cache_creation = payload.get("cache_creation")
    cache_5m = _nested_int(cache_creation, "ephemeral_5m_input_tokens")
    cache_1h = _nested_int(cache_creation, "ephemeral_1h_input_tokens")
    cache_creation_total = _to_int(payload.get("cache_creation_input_tokens")) or cache_5m + cache_1h
    usage = ExactUsage(
        input_tokens=_to_int(payload.get("input_tokens")),
        cache_creation_input_tokens=cache_creation_total,
        cache_creation_5m_input_tokens=cache_5m,
        cache_creation_1h_input_tokens=cache_1h,
        cache_read_input_tokens=_to_int(payload.get("cache_read_input_tokens")),
        output_tokens=_to_int(payload.get("output_tokens")),
    )
    return usage.ensure_total()


def _to_int(value: Any) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return 0


def _nested_int(payload: Any, key: str) -> int:
    if isinstance(payload, dict):
        return _to_int(payload.get(key))
    return 0


def _parse_claude_attachment(report: SessionReport, attachment: dict[str, Any]) -> None:
    attachment_type = attachment.get("type")
    text = stable_text(attachment)
    if attachment_type == "skill_listing":
        report.add_bucket("skills", stable_text(attachment.get("content", "")), "attachment.skill_listing")
        return
    if attachment_type == "deferred_tools_delta":
        report.add_bucket("mcp_or_dynamic_tools", text, "attachment.deferred_tools_delta")
        return
    if attachment_type == "hook_additional_context":
        report.add_bucket("hooks", stable_text(attachment.get("content", "")), "attachment.hook_additional_context")
        return
    if attachment_type in {"hook_success", "async_hook_response"}:
        context_text = _extract_hook_context(attachment)
        report.add_bucket("hooks", context_text, f"attachment.{attachment_type}")
        return
    if attachment_type == "hook_blocking_error":
        report.add_bucket("hooks", _extract_hook_blocking_error(attachment), "attachment.hook_blocking_error")
        return
    if attachment_type == "task_reminder":
        report.add_bucket("summaries", stable_text(attachment.get("content", "")), "attachment.task_reminder")
        return
    if attachment_type == "edited_text_file":
        report.add_bucket("tool_results", text, "attachment.edited_text_file")
        return
    if attachment_type in {"plan_mode", "plan_mode_exit", "plan_mode_reentry"}:
        report.add_bucket("developer_or_mode_instructions", text, f"attachment.{attachment_type}")
        return
    if attachment_type == "date_change":
        report.add_bucket("system_or_base_instructions", text, "attachment.date_change")
        return
    if isinstance(attachment_type, str) and attachment_type.startswith("hook_"):
        context_text = _extract_hook_context(attachment) or _extract_hook_blocking_error(attachment)
        report.add_bucket("hooks", context_text, f"attachment.{attachment_type}")
        return
    report.add_bucket("unknown", text, f"attachment.{attachment_type}")


def _extract_hook_context(attachment: dict[str, Any]) -> str:
    event = str(attachment.get("hookEvent", ""))
    parts: list[str] = []

    response = attachment.get("response")
    if isinstance(response, dict):
        parts.extend(_context_fields_from_hook_json(response))

    for key in ("stdout", "content"):
        value = attachment.get(key)
        if not isinstance(value, str) or not value:
            continue
        parsed = _parse_json_object(value)
        if parsed:
            parts.extend(_context_fields_from_hook_json(parsed))
        elif event in STDOUT_CONTEXT_EVENTS:
            parts.append(value)

    return "\n".join(part for part in parts if part)


def _context_fields_from_hook_json(payload: dict[str, Any]) -> list[str]:
    parts: list[str] = []
    for key in ("additionalContext", "systemMessage"):
        value = payload.get(key)
        if value:
            parts.append(stable_text(value))
    hook_specific = payload.get("hookSpecificOutput")
    if isinstance(hook_specific, dict):
        for key in ("additionalContext", "systemMessage"):
            value = hook_specific.get(key)
            if value:
                parts.append(stable_text(value))
    return parts


def _extract_hook_blocking_error(attachment: dict[str, Any]) -> str:
    blocking = attachment.get("blockingError")
    if isinstance(blocking, dict):
        return stable_text(blocking.get("blockingError") or blocking.get("message") or blocking)
    if blocking:
        return stable_text(blocking)
    stderr = attachment.get("stderr")
    if stderr:
        return stable_text(stderr)
    return ""


def _parse_json_object(value: str) -> dict[str, Any] | None:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _contains_tool_result(content: Any) -> bool:
    if not isinstance(content, list):
        return False
    return any(isinstance(block, dict) and block.get("type") == "tool_result" for block in content)


def _iter_tool_uses(content: Any) -> list[tuple[str, Any]]:
    if not isinstance(content, list):
        return []
    results: list[tuple[str, Any]] = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "tool_use":
            results.append((str(block.get("name", "")), block.get("input", {})))
    return results
