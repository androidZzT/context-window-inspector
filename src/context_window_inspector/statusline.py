from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .models import ExactUsage, SessionReport, estimated_bucket_dicts, window_usage_tokens


BUCKET_LABELS = {
    "assistant_messages": "asst",
    "tool_results": "tool",
    "tool_calls": "call",
    "summaries": "sum",
    "system_or_base_instructions": "sys",
    "developer_or_mode_instructions": "dev",
    "skills": "skill",
    "mcp_or_dynamic_tools": "mcp",
    "user_messages": "user",
    "hooks": "hook",
    "unknown": "unk",
}

PALETTE = {
    "reset": "\033[0m",
    "dim": "\033[2m",
    "bold": "\033[1m",
    "cyan": "\033[38;2;86;182;194m",
    "green": "\033[38;2;70;190;120m",
    "yellow": "\033[38;2;230;200;0m",
    "orange": "\033[38;2;255;176;85m",
    "red": "\033[38;2;255;85;85m",
    "blue": "\033[38;2;0;153;255m",
    "magenta": "\033[38;2;180;140;255m",
    "white": "\033[38;2;225;225;225m",
    "fg_dark": "\033[38;2;24;28;36m",
    "bg_blue": "\033[48;2;0;153;255m",
    "bg_orange": "\033[48;2;255;176;85m",
    "bg_magenta": "\033[48;2;180;140;255m",
    "bg_cyan": "\033[48;2;86;182;194m",
    "bg_green": "\033[48;2;70;190;120m",
    "bg_yellow": "\033[48;2;230;200;0m",
    "bg_white": "\033[48;2;225;225;225m",
}

BUCKET_COLORS = ["blue", "orange", "magenta", "cyan", "green", "yellow", "white"]
BUCKET_COLOR_BY_NAME = {
    "assistant_messages": "magenta",
    "tool_results": "orange",
    "tool_calls": "cyan",
    "summaries": "green",
    "system_or_base_instructions": "yellow",
    "developer_or_mode_instructions": "blue",
    "skills": "green",
    "mcp_or_dynamic_tools": "cyan",
    "user_messages": "white",
    "hooks": "blue",
    "unknown": "white",
}


def read_status_input(text: str) -> dict[str, Any]:
    text = text.strip()
    if not text:
        return {}
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def session_selector_from_status_input(data: dict[str, Any]) -> str | None:
    transcript = data.get("transcript_path")
    if isinstance(transcript, str) and transcript:
        return transcript
    session_id = data.get("session_id") or data.get("sessionId")
    if isinstance(session_id, str) and session_id:
        return session_id
    session = data.get("session")
    if isinstance(session, dict):
        nested_id = session.get("id") or session.get("session_id")
        if isinstance(nested_id, str) and nested_id:
            return nested_id
    return None


def apply_status_input(report: SessionReport, data: dict[str, Any]) -> None:
    context_window = data.get("context_window")
    if isinstance(context_window, dict):
        size = _to_int(context_window.get("context_window_size") or context_window.get("size"))
        if size:
            report.context_window = size
        current_usage = context_window.get("current_usage")
        if isinstance(current_usage, dict):
            cache_creation = current_usage.get("cache_creation")
            input_details = current_usage.get("input_tokens_details")
            output_details = current_usage.get("output_tokens_details")
            usage = ExactUsage(
                input_tokens=_to_int(current_usage.get("input_tokens")),
                cached_input_tokens=_to_int(current_usage.get("cached_input_tokens"))
                or _nested_int(input_details, "cached_tokens"),
                cache_creation_input_tokens=_to_int(current_usage.get("cache_creation_input_tokens")),
                cache_creation_5m_input_tokens=_nested_int(cache_creation, "ephemeral_5m_input_tokens"),
                cache_creation_1h_input_tokens=_nested_int(cache_creation, "ephemeral_1h_input_tokens"),
                cache_read_input_tokens=_to_int(current_usage.get("cache_read_input_tokens")),
                output_tokens=_to_int(current_usage.get("output_tokens")),
                reasoning_output_tokens=_to_int(current_usage.get("reasoning_output_tokens"))
                or _nested_int(output_details, "reasoning_tokens"),
                total_tokens=_to_int(current_usage.get("total_tokens")),
            )
            if not usage.cache_creation_input_tokens:
                usage.cache_creation_input_tokens = (
                    usage.cache_creation_5m_input_tokens + usage.cache_creation_1h_input_tokens
                )
            usage.ensure_total()
            if usage.total_tokens:
                report.latest_usage = usage
    model = data.get("model")
    if isinstance(model, dict):
        model_name = model.get("display_name") or model.get("id")
        if isinstance(model_name, str) and model_name:
            report.model = model_name
    cwd = data.get("cwd")
    workspace = data.get("workspace")
    if isinstance(workspace, dict):
        cwd = workspace.get("current_dir") or cwd
    if isinstance(cwd, str) and cwd:
        report.project_path = cwd


def render_statusline(
    report: SessionReport,
    *,
    color: bool = True,
    ascii_only: bool = False,
    top: int = 5,
    width: int = 120,
    include_model: bool = True,
) -> str:
    if not report.latest_usage or not report.context_window:
        return _fit(_paint("ctx n/a", "yellow", color), width)

    window_tokens = window_usage_tokens(report)
    total_percent = window_tokens / report.context_window * 100
    used = _format_tokens(window_tokens)
    total = _format_tokens(report.context_window)
    prefix_width = len(report.model) + 3 if include_model and report.model else 0
    bar_width = max(26, min(104, width - prefix_width - 28))
    bar = _segmented_bar(
        report,
        total_percent,
        bar_width,
        window_tokens=window_tokens,
        top=top,
        color=color,
        ascii_only=ascii_only,
    )
    sep = " | " if ascii_only else f" {_paint('│', 'dim', color)} "
    head = f"{_paint('ctx', 'cyan', color)} {_paint(f'{total_percent:.1f}%', _usage_color(total_percent), color)}"
    head += f" {bar} {_paint(f'{used}/{total}', 'dim', color)}"
    if include_model and report.model:
        head = f"{_paint(report.model, 'blue', color)}{sep}{head}"
    return _fit(head, width)


def _bucket_pieces(report: SessionReport, top: int, color: bool) -> list[str]:
    items = [
        item
        for item in estimated_bucket_dicts(report)
        if item.get("estimated_window_percent") is not None
    ]
    items.sort(key=lambda item: float(item["estimated_window_percent"]), reverse=True)
    pieces: list[str] = []
    for index, item in enumerate(items[:top]):
        name = str(item["name"])
        label = BUCKET_LABELS.get(name, name[:5])
        percent = float(item["estimated_window_percent"])
        color_name = BUCKET_COLORS[index % len(BUCKET_COLORS)]
        pieces.append(f"{_paint(label, color_name, color)} {_paint(f'{percent:.1f}%', 'white', color)}")
    return pieces


def _bar(percent: float, width: int, *, color: bool, ascii_only: bool) -> str:
    clamped = max(0, min(100, percent))
    filled = round(clamped * width / 100)
    if 0 < clamped < 100 and filled == 0:
        filled = 1
    empty = width - filled
    if ascii_only:
        raw = "[" + "#" * filled + "-" * empty + "]"
    else:
        raw = "▰" * filled + _paint("▱" * empty, "dim", color)
    return _paint(raw, _usage_color(percent), color)


def _segmented_bar(
    report: SessionReport,
    total_percent: float,
    width: int,
    *,
    window_tokens: int,
    top: int,
    color: bool,
    ascii_only: bool,
) -> str:
    items = _estimated_statusline_bucket_items(report, window_tokens)
    if not items:
        return _bar(total_percent, width, color=color, ascii_only=ascii_only)

    items.sort(key=lambda item: float(item["estimated_window_percent"]), reverse=True)
    total_percent = max(0, min(100, total_percent))
    used_width = round(total_percent * width / 100)
    if 0 < total_percent < 100 and used_width == 0:
        used_width = 1
    used_width = min(width, used_width)

    segments: list[tuple[str, float, str]] = []
    shown = items[:top]
    for index, item in enumerate(shown):
        name = str(item["name"])
        label = BUCKET_LABELS.get(name, name[:5])
        color_name = BUCKET_COLOR_BY_NAME.get(name, BUCKET_COLORS[index % len(BUCKET_COLORS)])
        segments.append((label, float(item["estimated_window_percent"]), color_name))
    other_percent = max(0.0, total_percent - sum(percent for _, percent, _ in segments))
    if other_percent >= 0.1:
        segments.append(("+", other_percent, "white"))

    return _chip_bar(segments, width, color=color, ascii_only=ascii_only)


def _estimated_statusline_bucket_items(report: SessionReport, window_tokens: int) -> list[dict[str, Any]]:
    visible_buckets = [bucket for bucket in report.buckets.values() if bucket.record_count]
    total_bucket_bytes = sum(bucket.byte_count for bucket in visible_buckets)
    if not total_bucket_bytes or not window_tokens or not report.context_window:
        return []
    items: list[dict[str, Any]] = []
    for bucket in visible_buckets:
        estimated_tokens = round(window_tokens * bucket.byte_count / total_bucket_bytes)
        item = bucket.to_dict()
        item["estimated_tokens"] = estimated_tokens
        item["estimated_window_percent"] = estimated_tokens / report.context_window * 100
        items.append(item)
    return items


def _chip_bar(
    segments: list[tuple[str, float, str]],
    width: int,
    *,
    color: bool,
    ascii_only: bool,
) -> str:
    if ascii_only:
        body = "".join(_ascii_chip(label, percent) for label, percent, _ in segments)
        body = body[:width]
        return body + "-" * max(0, width - len(body))

    body = "".join(
        _color_chip(label, percent, color_name, color=color)
        for label, percent, color_name in segments
    )
    if _visible_len(body) > width:
        body = _truncate_ansi(body, width)
    return body + _paint("▱" * max(0, width - _visible_len(body)), "dim", color)


def _ascii_chip(label: str, percent: float) -> str:
    return f"[{label} {percent:.1f}]"


def _color_chip(label: str, percent: float, color_name: str, *, color: bool) -> str:
    text = f" {label} {percent:.1f} "
    if not color:
        return text
    return f"{PALETTE.get('bg_' + color_name, '')}{PALETTE['fg_dark']}{text}{PALETTE['reset']}"


def _allocate_segment_widths(
    percents: list[float],
    used_width: int,
    full_width: int,
    min_widths: list[int],
) -> list[int]:
    if not percents or used_width <= 0:
        return [0 for _ in percents]
    raw = [max(0.0, percent) * full_width / 100 for percent in percents]
    widths = [int(value) for value in raw]
    positive = [index for index, percent in enumerate(percents) if percent > 0]
    for index in positive:
        target = min_widths[index] if index < len(min_widths) else 1
        if widths[index] < target and sum(widths) + target - widths[index] <= used_width:
            widths[index] = target
    while sum(widths) < used_width:
        remainders = [(raw[index] - int(raw[index]), index) for index in range(len(raw))]
        _, index = max(remainders)
        widths[index] += 1
        raw[index] = int(raw[index])
    while sum(widths) > used_width:
        candidates = [
            (widths[index], index)
            for index in range(len(widths))
            if widths[index] > max(0, min_widths[index] if index < len(min_widths) else 0)
        ]
        if not candidates:
            candidates = [(widths[index], index) for index in range(len(widths)) if widths[index] > 0]
        if not candidates:
            break
        _, index = min(candidates)
        widths[index] -= 1
    return widths


def _ascii_segment(label: str, percent: float, width: int) -> str:
    if width <= 0:
        return ""
    if not label:
        return "=" * width
    text = _segment_label(label, percent, width)
    if not text:
        return "=" * width
    return (text + "=" * width)[:width]


def _color_segment(label: str, percent: float, color_name: str, width: int, *, color: bool) -> str:
    if width <= 0:
        return ""
    if not label:
        return _paint("▰" * width, color_name, color)
    text = _segment_label(label, percent, width)
    if not text:
        text = "▰" * width
        return _paint(text, color_name, color)
    text = text.ljust(width)[:width]
    if not color:
        return text
    return f"{PALETTE.get('bg_' + color_name, '')}{PALETTE['fg_dark']}{text}{PALETTE['reset']}"


def _segment_label(label: str, percent: float, width: int) -> str:
    candidates = [
        f" {label} {percent:.1f} ",
        f"{label} {percent:.1f}",
        f" {label} ",
        label,
    ]
    for candidate in candidates:
        if len(candidate) <= width:
            return candidate
    return label[:width]


def _visible_len(text: str) -> int:
    return len(_strip_ansi(text))


def _usage_color(percent: float) -> str:
    if percent >= 90:
        return "red"
    if percent >= 70:
        return "yellow"
    if percent >= 50:
        return "orange"
    return "green"


def _paint(text: str, color_name: str, enabled: bool) -> str:
    if not enabled:
        return text
    return f"{PALETTE.get(color_name, '')}{text}{PALETTE['reset']}"


def _fit(text: str, width: int) -> str:
    if width <= 0:
        return text
    plain = _strip_ansi(text)
    if len(plain) <= width:
        return text
    return _truncate_ansi(text, width - 1) + "…"


def _strip_ansi(text: str) -> str:
    result = []
    in_escape = False
    for char in text:
        if char == "\033":
            in_escape = True
            continue
        if in_escape:
            if char == "m":
                in_escape = False
            continue
        result.append(char)
    return "".join(result)


def _truncate_ansi(text: str, max_plain_chars: int) -> str:
    if max_plain_chars <= 0:
        return ""
    result = []
    plain_count = 0
    index = 0
    while index < len(text) and plain_count < max_plain_chars:
        char = text[index]
        result.append(char)
        if char == "\033":
            index += 1
            while index < len(text):
                result.append(text[index])
                if text[index] == "m":
                    break
                index += 1
        else:
            plain_count += 1
        index += 1
    if "\033[" in "".join(result):
        result.append(PALETTE["reset"])
    return "".join(result)


def _format_tokens(value: int) -> str:
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    if value >= 1_000:
        return f"{value / 1_000:.0f}K"
    return str(value)


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


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def pythonpath_env() -> str:
    src = str(repo_root() / "src")
    existing = os.environ.get("PYTHONPATH")
    return src if not existing else f"{src}{os.pathsep}{existing}"
