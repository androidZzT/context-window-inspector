from __future__ import annotations

import json

from .models import (
    ExactUsage,
    SessionReport,
    estimated_bucket_dicts,
    window_usage_tokens_for_usage,
)
from .pricing import estimate_report_costs


def render_json(report: SessionReport, include_events: bool = False) -> str:
    return json.dumps(report.to_dict(include_events=include_events), ensure_ascii=False, indent=2)


def render_markdown(report: SessionReport, include_events: bool = False) -> str:
    lines: list[str] = []
    lines.append("# Context Window Inspector")
    lines.append("")
    lines.append(f"- Provider: `{report.provider}`")
    lines.append(f"- Session: `{report.session_id}`")
    if report.model:
        lines.append(f"- Model: `{report.model}`")
    if report.project_path:
        lines.append(f"- Project: `{report.project_path}`")
    lines.append(f"- File: `{report.file_path}`")
    if report.context_window:
        lines.append(f"- Context window: `{_fmt(report.context_window)}` tokens")
    lines.append("")
    lines.append("## Exact Token Usage")
    lines.append("")
    lines.append(
        "| Scope | Input | Cached input | Cache create | 5m write | 1h write | "
        "Cache read | Output | Reasoning | Total | Window |"
    )
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    lines.append(_usage_row("Latest request", report.provider, report.latest_usage, report.context_window))
    lines.append(_usage_row("Session total", report.provider, report.total_usage, None))
    lines.append("")
    lines.append(
        "Exact token values come from recorded usage fields. Window percentage uses the provider-specific context formula."
    )
    lines.append("")
    lines.append("## Estimated API Cost")
    lines.append("")
    lines.append("Cost is estimated from public API prices and local token counts; subscription billing can differ.")
    lines.append("")
    lines.append("| Scope | Estimated cost | Priced as | Notes |")
    lines.append("|---|---:|---|---|")
    costs = estimate_report_costs(report)
    lines.append(_cost_row("Latest request", costs.get("latest")))
    lines.append(_cost_row("Session total", costs.get("session_total")))
    lines.append("")
    lines.append("## Estimated Window Split")
    lines.append("")
    lines.append(
        "This split allocates the latest exact token usage across observable buckets by byte weight, "
        "so the percentages are approximate."
    )
    lines.append("")
    lines.append("| Bucket | Estimated window | Estimated tokens |")
    lines.append("|---|---:|---:|")
    split_rows = _estimated_split_rows(report)
    if not split_rows:
        lines.append("| none | n/a | n/a |")
    for name, percent, tokens in split_rows:
        lines.append(f"| `{name}` | {percent:.1f}% | {_fmt(tokens)} |")
    lines.append("")
    lines.append("## Observable Payload Buckets")
    lines.append("")
    lines.append("| Bucket | Records | Chars | Bytes | Examples |")
    lines.append("|---|---:|---:|---:|---|")
    buckets = sorted(
        [bucket for bucket in report.buckets.values() if bucket.record_count],
        key=lambda bucket: bucket.byte_count,
        reverse=True,
    )
    if not buckets:
        lines.append("| none | 0 | 0 | 0 |  |")
    for bucket in buckets:
        examples = "<br>".join(_escape(example) for example in bucket.examples)
        lines.append(
            f"| `{bucket.name}` | {bucket.record_count} | {_fmt(bucket.char_count)} | "
            f"{_fmt(bucket.byte_count)} | {examples} |"
        )
    if include_events and report.usage_events:
        lines.append("")
        lines.append("## Usage Events")
        lines.append("")
        lines.append("| Timestamp | Source | Input | Cache create | Cache read | Output | Total |")
        lines.append("|---|---|---:|---:|---:|---:|---:|")
        for event in report.usage_events:
            usage = event.usage
            lines.append(
                f"| `{event.timestamp}` | `{event.source}` | {_fmt(usage.input_tokens)} | "
                f"{_fmt(usage.cache_creation_input_tokens)} | {_fmt(usage.cache_read_input_tokens)} | "
                f"{_fmt(usage.output_tokens)} | {_fmt(usage.total_tokens)} |"
            )
    if report.warnings:
        lines.append("")
        lines.append("## Warnings")
        lines.append("")
        for warning in report.warnings:
            lines.append(f"- {warning}")
    lines.append("")
    return "\n".join(lines)


def _estimated_split_rows(report: SessionReport) -> list[tuple[str, float, int]]:
    rows: list[tuple[str, float, int]] = []
    for item in estimated_bucket_dicts(report):
        percent = item.get("estimated_window_percent")
        tokens = item.get("estimated_tokens")
        if percent is None or tokens is None:
            continue
        rows.append((str(item["name"]), float(percent), int(tokens)))
    return sorted(rows, key=lambda row: row[1], reverse=True)


def _usage_row(
    label: str,
    provider: str,
    usage: ExactUsage | None,
    context_window: int | None,
) -> str:
    if not usage:
        return f"| {label} | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a |"
    window = "n/a"
    if context_window:
        pct = window_usage_tokens_for_usage(provider, usage) / context_window * 100
        window = f"{pct:.1f}%"
    return (
        f"| {label} | {_fmt(usage.input_tokens)} | {_fmt(usage.cached_input_tokens)} | "
        f"{_fmt(usage.cache_creation_input_tokens)} | {_fmt(usage.cache_creation_5m_input_tokens)} | "
        f"{_fmt(usage.cache_creation_1h_input_tokens)} | {_fmt(usage.cache_read_input_tokens)} | "
        f"{_fmt(usage.output_tokens)} | {_fmt(usage.reasoning_output_tokens)} | "
        f"{_fmt(usage.total_tokens)} | {window} |"
    )


def _cost_row(label: str, cost: dict | None) -> str:
    if not cost:
        return f"| {label} | n/a | n/a | n/a |"
    if not cost.get("available"):
        notes = "<br>".join(_escape(warning) for warning in cost.get("warnings", []))
        return f"| {label} | n/a | n/a | {notes} |"
    notes = "<br>".join(_escape(warning) for warning in cost.get("warnings", []))
    return (
        f"| {label} | {_fmt_cost(float(cost['total']))} | "
        f"`{_escape(str(cost['priced_as']))}` | {notes} |"
    )


def _fmt_cost(value: float) -> str:
    if value < 0.01:
        return f"${value:.6f}"
    return f"${value:.2f}"


def _fmt(value: int) -> str:
    return f"{value:,}"


def _escape(value: str) -> str:
    return value.replace("|", "\\|")
