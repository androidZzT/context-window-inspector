from __future__ import annotations

from context_window_inspector.models import ExactUsage
from context_window_inspector.pricing import estimate_usage_cost


def test_openai_cost_prices_cached_input_and_reasoning_as_output_detail() -> None:
    usage = ExactUsage(
        input_tokens=1000,
        cached_input_tokens=400,
        output_tokens=100,
        reasoning_output_tokens=80,
        total_tokens=1100,
    )

    cost = estimate_usage_cost("codex", "gpt-5.5", usage, context_window=258400)

    assert cost
    assert cost["available"] is True
    assert cost["tokens"]["input_tokens"] == 600
    assert cost["tokens"]["cached_input_tokens"] == 400
    assert cost["total"] == 0.0062


def test_claude_cost_uses_cache_duration_split() -> None:
    usage = ExactUsage(
        input_tokens=1000,
        cache_creation_input_tokens=300,
        cache_creation_5m_input_tokens=100,
        cache_creation_1h_input_tokens=200,
        cache_read_input_tokens=500,
        output_tokens=100,
        total_tokens=1900,
    )

    cost = estimate_usage_cost("claude", "claude-opus-4-7", usage)

    assert cost
    assert cost["available"] is True
    assert cost["breakdown"]["cache_creation_5m"] == 0.000625
    assert cost["breakdown"]["cache_creation_1h"] == 0.002
    assert cost["breakdown"]["cache_read"] == 0.00025
    assert cost["total"] == 0.010375


def test_unknown_model_cost_is_unavailable() -> None:
    cost = estimate_usage_cost("codex", "unknown-model", ExactUsage(input_tokens=10, total_tokens=10))

    assert cost
    assert cost["available"] is False
