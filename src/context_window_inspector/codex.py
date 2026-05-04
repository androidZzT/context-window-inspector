from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Any

from .models import ExactUsage, SessionReport, UsageEvent
from .util import label_from_text, newest, read_jsonl, stable_text


_TAG_BUCKETS = {
    "skills_instructions": "skills",
    "plugins_instructions": "mcp_or_dynamic_tools",
    "apps_instructions": "mcp_or_dynamic_tools",
    "permissions instructions": "developer_or_mode_instructions",
    "collaboration_mode": "developer_or_mode_instructions",
}


def discover_codex_sessions(home: Path | None = None) -> list[Path]:
    root = (home or Path.home()) / ".codex" / "sessions"
    if not root.exists():
        return []
    return sorted(root.glob("**/rollout-*.jsonl"))


def resolve_codex_session(selector: str | None, latest: bool, home: Path | None = None) -> Path:
    if selector:
        candidate = Path(selector).expanduser()
        if candidate.exists():
            return candidate
    sessions = discover_codex_sessions(home)
    if selector:
        matches: list[Path] = []
        for path in sessions:
            if selector in path.stem or selector in _read_codex_session_id(path):
                matches.append(path)
        if len(matches) == 1:
            return matches[0]
        if matches:
            return newest(matches) or matches[0]
        raise FileNotFoundError(f"No Codex session matched {selector!r}")
    if latest:
        path = newest(sessions)
        if path:
            return path
    raise FileNotFoundError("No Codex session found")


def parse_codex_session(path: Path, home: Path | None = None) -> SessionReport:
    records = list(read_jsonl(path))
    session_id = _read_codex_session_id_from_records(records) or path.stem
    report = SessionReport(provider="codex", session_id=session_id, file_path=path)
    total_usage = ExactUsage()
    session_meta: dict[str, Any] | None = None
    latest_turn_context: dict[str, Any] | None = None
    active_start = _last_record_index(records, "compacted")

    for obj in records:
        timestamp = str(obj.get("timestamp", ""))
        record_type = obj.get("type")
        payload = obj.get("payload", {})
        if record_type == "session_meta" and isinstance(payload, dict):
            session_meta = payload
            report.project_path = payload.get("cwd", report.project_path) or report.project_path
            continue

        if record_type == "turn_context" and isinstance(payload, dict):
            latest_turn_context = payload
            report.project_path = payload.get("cwd", report.project_path) or report.project_path
            report.model = payload.get("model", report.model) or report.model
            continue

        if record_type == "event_msg" and isinstance(payload, dict):
            _parse_codex_event(
                report,
                payload,
                timestamp,
                total_usage,
                collect_buckets=False,
            )

    _add_active_codex_buckets(report, records, session_meta, latest_turn_context, active_start)

    if report.usage_events:
        report.latest_usage = report.usage_events[-1].usage
    report.total_usage = total_usage if total_usage.total_tokens else report.latest_usage
    _add_dynamic_tools(report, home)
    if not report.latest_usage:
        report.warnings.append("No exact token usage found in Codex token_count events.")
    return report


def _read_codex_session_id(path: Path) -> str:
    return _read_codex_session_id_from_records(read_jsonl(path))


def _read_codex_session_id_from_records(records: Any) -> str:
    for obj in records:
        if obj.get("type") == "session_meta":
            payload = obj.get("payload", {})
            if isinstance(payload, dict):
                value = payload.get("id")
                if value:
                    return str(value)
    return ""


def _last_record_index(records: list[dict[str, Any]], record_type: str) -> int:
    result = -1
    for index, obj in enumerate(records):
        if obj.get("type") == record_type:
            result = index
    return result


def _usage_from_openai(payload: dict[str, Any]) -> ExactUsage:
    input_details = payload.get("input_tokens_details")
    output_details = payload.get("output_tokens_details")
    usage = ExactUsage(
        input_tokens=_to_int(payload.get("input_tokens")),
        cached_input_tokens=_to_int(payload.get("cached_input_tokens"))
        or _nested_int(input_details, "cached_tokens"),
        output_tokens=_to_int(payload.get("output_tokens")),
        reasoning_output_tokens=_to_int(payload.get("reasoning_output_tokens"))
        or _nested_int(output_details, "reasoning_tokens"),
        total_tokens=_to_int(payload.get("total_tokens")),
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


def _add_codex_instruction_text(
    report: SessionReport,
    text: str,
    default_bucket: str,
    default_label: str,
) -> None:
    if not text:
        return
    remaining = text
    for tag, bucket in _TAG_BUCKETS.items():
        pattern = re.compile(rf"<{re.escape(tag)}>(.*?)</{re.escape(tag)}>", re.DOTALL)
        for match in pattern.finditer(text):
            block = match.group(0)
            report.add_bucket(bucket, block, f"base_instructions.{tag}")
        remaining = pattern.sub("", remaining)
    report.add_bucket(default_bucket, remaining.strip(), default_label)


def _parse_codex_event(
    report: SessionReport,
    payload: dict[str, Any],
    timestamp: str,
    total_usage: ExactUsage,
    collect_buckets: bool = True,
    collect_usage: bool = True,
) -> None:
    event_type = payload.get("type")
    if event_type == "user_message":
        if collect_buckets:
            report.add_bucket("user_messages", stable_text(payload.get("message", "")), "event_msg.user_message")
        return
    if event_type == "agent_message":
        if collect_buckets:
            report.add_bucket("assistant_messages", stable_text(payload.get("message", "")), "event_msg.agent_message")
        return
    if event_type != "token_count" or not collect_usage:
        return

    info = payload.get("info")
    if not isinstance(info, dict):
        return
    latest = info.get("last_token_usage")
    total = info.get("total_token_usage")
    if isinstance(latest, dict):
        report.usage_events.append(UsageEvent(timestamp, _usage_from_openai(latest), "codex.last_token_usage"))
    if isinstance(total, dict):
        usage = _usage_from_openai(total)
        total_usage.input_tokens = usage.input_tokens
        total_usage.cached_input_tokens = usage.cached_input_tokens
        total_usage.cache_creation_input_tokens = usage.cache_creation_input_tokens
        total_usage.cache_creation_5m_input_tokens = usage.cache_creation_5m_input_tokens
        total_usage.cache_creation_1h_input_tokens = usage.cache_creation_1h_input_tokens
        total_usage.cache_read_input_tokens = usage.cache_read_input_tokens
        total_usage.output_tokens = usage.output_tokens
        total_usage.reasoning_output_tokens = usage.reasoning_output_tokens
        total_usage.total_tokens = usage.total_tokens
    context_window = _to_int(info.get("model_context_window"))
    if context_window:
        report.context_window = context_window


def _add_active_codex_buckets(
    report: SessionReport,
    records: list[dict[str, Any]],
    session_meta: dict[str, Any] | None,
    latest_turn_context: dict[str, Any] | None,
    active_start: int,
) -> None:
    if session_meta:
        base = session_meta.get("base_instructions", {})
        if isinstance(base, dict):
            _add_codex_instruction_text(
                report,
                stable_text(base.get("text", "")),
                "system_or_base_instructions",
                "session_meta.base_instructions",
            )

    if latest_turn_context:
        summary = stable_text(latest_turn_context.get("summary", ""))
        if summary and summary != "none":
            report.add_bucket("summaries", summary, "latest_turn_context.summary")
        user_instructions = stable_text(latest_turn_context.get("user_instructions", ""))
        report.add_bucket(
            "system_or_base_instructions",
            user_instructions,
            "latest_turn_context.user_instructions",
        )
        mode = latest_turn_context.get("collaboration_mode")
        report.add_bucket(
            "developer_or_mode_instructions",
            stable_text(mode),
            "latest_turn_context.collaboration_mode",
        )

    if active_start >= 0:
        compacted = records[active_start]
        report.add_bucket(
            "summaries",
            stable_text(compacted.get("payload", {})),
            f"compacted.line_{active_start + 1}",
        )

    response_roles = _active_response_message_roles(records, active_start)
    for index, obj in enumerate(records):
        if index <= active_start:
            continue
        payload = obj.get("payload", {})
        if not isinstance(payload, dict):
            continue
        record_type = obj.get("type")
        if record_type == "response_item":
            _parse_codex_response_item(report, payload)
            continue
        if record_type != "event_msg":
            continue
        event_type = payload.get("type")
        if event_type == "user_message" and "user" in response_roles:
            continue
        if event_type == "agent_message" and "assistant" in response_roles:
            continue
        _parse_codex_event(
            report,
            payload,
            str(obj.get("timestamp", "")),
            ExactUsage(),
            collect_usage=False,
        )


def _active_response_message_roles(records: list[dict[str, Any]], active_start: int) -> set[str]:
    roles: set[str] = set()
    for index, obj in enumerate(records):
        if index <= active_start:
            continue
        payload = obj.get("payload", {})
        if not isinstance(payload, dict):
            continue
        if obj.get("type") == "response_item" and payload.get("type") == "message":
            role = payload.get("role")
            if role in {"user", "assistant"}:
                roles.add(str(role))
    return roles


def _parse_codex_response_item(report: SessionReport, payload: dict[str, Any]) -> None:
    item_type = payload.get("type")
    if item_type in {"function_call", "custom_tool_call"}:
        text = stable_text({
            "name": payload.get("name"),
            "arguments": payload.get("arguments") or payload.get("input"),
        })
        report.add_bucket("tool_calls", text, f"tool_call.{payload.get('name', '')}")
        return
    if item_type in {"function_call_output", "custom_tool_call_output"}:
        report.add_bucket("tool_results", stable_text(payload), f"tool_result.{payload.get('call_id', '')}")
        return
    if item_type == "message":
        role = payload.get("role")
        content = stable_text(payload.get("content", ""))
        if role == "user":
            report.add_bucket("user_messages", content, label_from_text("message.user", content))
        elif role == "developer":
            _add_codex_instruction_text(
                report,
                content,
                "developer_or_mode_instructions",
                "message.developer",
            )
        elif role == "system":
            _add_codex_instruction_text(
                report,
                content,
                "system_or_base_instructions",
                "message.system",
            )
        else:
            report.add_bucket("assistant_messages", content, label_from_text(f"message.{role}", content))
        return
    if item_type == "reasoning":
        report.add_bucket("assistant_messages", stable_text(payload), "response_item.reasoning")


def _add_dynamic_tools(report: SessionReport, home: Path | None) -> None:
    root = (home or Path.home()) / ".codex"
    dbs = sorted(root.glob("state_*.sqlite"), key=lambda path: path.stat().st_mtime, reverse=True)
    if not dbs:
        return
    try:
        with sqlite3.connect(f"file:{dbs[0]}?mode=ro", uri=True) as conn:
            rows = conn.execute(
                "select name, description, input_schema, namespace "
                "from thread_dynamic_tools where thread_id=? order by position",
                (report.session_id,),
            ).fetchall()
    except sqlite3.Error:
        return
    for name, description, input_schema, namespace in rows:
        text = stable_text({
            "name": name,
            "namespace": namespace,
            "description": description,
            "input_schema": input_schema,
        })
        report.add_bucket("mcp_or_dynamic_tools", text, f"dynamic_tool.{name}")
