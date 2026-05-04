from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


BUCKETS = (
    "system_or_base_instructions",
    "developer_or_mode_instructions",
    "user_messages",
    "assistant_messages",
    "tool_calls",
    "tool_results",
    "skills",
    "mcp_or_dynamic_tools",
    "hooks",
    "summaries",
    "unknown",
)


@dataclass
class ExactUsage:
    input_tokens: int = 0
    cached_input_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_creation_5m_input_tokens: int = 0
    cache_creation_1h_input_tokens: int = 0
    cache_read_input_tokens: int = 0
    output_tokens: int = 0
    reasoning_output_tokens: int = 0
    total_tokens: int = 0

    def add(self, other: "ExactUsage") -> None:
        self.input_tokens += other.input_tokens
        self.cached_input_tokens += other.cached_input_tokens
        self.cache_creation_input_tokens += other.cache_creation_input_tokens
        self.cache_creation_5m_input_tokens += other.cache_creation_5m_input_tokens
        self.cache_creation_1h_input_tokens += other.cache_creation_1h_input_tokens
        self.cache_read_input_tokens += other.cache_read_input_tokens
        self.output_tokens += other.output_tokens
        self.reasoning_output_tokens += other.reasoning_output_tokens
        self.total_tokens += other.total_tokens

    def ensure_total(self) -> "ExactUsage":
        if not self.total_tokens:
            # cached_input_tokens and reasoning_output_tokens are detail fields, not
            # extra buckets. They are already included in input/output totals.
            self.total_tokens = (
                self.input_tokens
                + self.cache_creation_input_tokens
                + self.cache_read_input_tokens
                + self.output_tokens
            )
        return self

    def to_dict(self) -> dict[str, int]:
        return {
            "input_tokens": self.input_tokens,
            "cached_input_tokens": self.cached_input_tokens,
            "cache_creation_input_tokens": self.cache_creation_input_tokens,
            "cache_creation_5m_input_tokens": self.cache_creation_5m_input_tokens,
            "cache_creation_1h_input_tokens": self.cache_creation_1h_input_tokens,
            "cache_read_input_tokens": self.cache_read_input_tokens,
            "output_tokens": self.output_tokens,
            "reasoning_output_tokens": self.reasoning_output_tokens,
            "total_tokens": self.total_tokens,
        }


@dataclass
class UsageEvent:
    timestamp: str
    usage: ExactUsage
    source: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "source": self.source,
            "usage": self.usage.to_dict(),
        }


@dataclass
class BucketStats:
    name: str
    record_count: int = 0
    char_count: int = 0
    byte_count: int = 0
    examples: list[str] = field(default_factory=list)

    def add(self, text: str, label: str = "") -> None:
        if not text:
            return
        self.record_count += 1
        self.char_count += len(text)
        self.byte_count += len(text.encode("utf-8"))
        if label and len(self.examples) < 5:
            self.examples.append(label[:120])

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "record_count": self.record_count,
            "char_count": self.char_count,
            "byte_count": self.byte_count,
            "examples": self.examples,
        }


@dataclass
class SessionReport:
    provider: str
    session_id: str
    file_path: Path
    project_path: str = ""
    model: str = ""
    context_window: int | None = None
    latest_usage: ExactUsage | None = None
    total_usage: ExactUsage | None = None
    usage_events: list[UsageEvent] = field(default_factory=list)
    buckets: dict[str, BucketStats] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        for name in BUCKETS:
            self.buckets.setdefault(name, BucketStats(name))

    def add_bucket(self, name: str, text: str, label: str = "") -> None:
        if name not in self.buckets:
            name = "unknown"
        self.buckets[name].add(text, label)

    def to_dict(self, include_events: bool = False) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "provider": self.provider,
            "session_id": self.session_id,
            "file_path": str(self.file_path),
            "project_path": self.project_path,
            "model": self.model,
            "context_window": self.context_window,
            "exact_usage": {
                "latest": self.latest_usage.to_dict() if self.latest_usage else None,
                "total": self.total_usage.to_dict() if self.total_usage else None,
            },
            "observable_buckets": [],
            "warnings": self.warnings,
        }
        payload["observable_buckets"] = estimated_bucket_dicts(self)
        from .pricing import estimate_report_costs

        payload["estimated_cost"] = estimate_report_costs(self)
        if include_events:
            payload["usage_events"] = [event.to_dict() for event in self.usage_events]
        return payload


def window_usage_tokens(report: SessionReport) -> int:
    if not report.latest_usage:
        return 0
    return window_usage_tokens_for_usage(report.provider, report.latest_usage)


def window_usage_tokens_for_usage(provider: str, usage: ExactUsage) -> int:
    if provider == "claude":
        value = usage.input_tokens + usage.cache_creation_input_tokens + usage.cache_read_input_tokens
        return value or usage.total_tokens
    return usage.total_tokens


def estimated_bucket_dicts(report: SessionReport) -> list[dict[str, Any]]:
    visible_buckets = [bucket for bucket in report.buckets.values() if bucket.record_count]
    total_bucket_bytes = sum(bucket.byte_count for bucket in visible_buckets)
    window_tokens = window_usage_tokens(report)
    items: list[dict[str, Any]] = []
    for bucket in visible_buckets:
        item = bucket.to_dict()
        if total_bucket_bytes and window_tokens and report.context_window:
            estimated_tokens = round(window_tokens * bucket.byte_count / total_bucket_bytes)
            item["estimated_tokens"] = estimated_tokens
            item["estimated_window_percent"] = estimated_tokens / report.context_window * 100
        items.append(item)
    return items
