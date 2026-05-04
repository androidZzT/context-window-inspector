from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .models import ExactUsage, SessionReport


MILLION = 1_000_000
OPENAI_PRICING_SOURCE = "https://developers.openai.com/api/docs/pricing"
OPENAI_USAGE_SOURCE = (
    "https://developers.openai.com/api/reference/resources/responses/methods/create"
)
CLAUDE_PROMPT_CACHING_SOURCE = "https://platform.claude.com/docs/en/build-with-claude/prompt-caching"
CLAUDE_OPUS_47_SOURCE = "https://www.anthropic.com/claude/opus"
CLAUDE_CODE_COSTS_SOURCE = "https://code.claude.com/docs/en/costs"


@dataclass(frozen=True)
class PriceRate:
    provider: str
    priced_as: str
    input_per_million: float
    output_per_million: float
    cached_input_per_million: float | None = None
    cache_creation_5m_per_million: float | None = None
    cache_creation_1h_per_million: float | None = None
    cache_read_per_million: float | None = None
    long_context_threshold: int | None = None
    long_input_per_million: float | None = None
    long_cached_input_per_million: float | None = None
    long_output_per_million: float | None = None
    source_urls: tuple[str, ...] = ()


def estimate_report_costs(report: "SessionReport") -> dict[str, Any]:
    return {
        "currency": "USD",
        "latest": estimate_usage_cost(
            report.provider,
            report.model,
            report.latest_usage,
            context_window=report.context_window,
        ),
        "session_total": estimate_usage_cost(
            report.provider,
            report.model,
            report.total_usage,
            context_window=report.context_window,
        ),
    }


def estimate_usage_cost(
    provider: str,
    model: str,
    usage: "ExactUsage | None",
    *,
    context_window: int | None = None,
) -> dict[str, Any] | None:
    if not usage:
        return None
    rate = find_price_rate(provider, model)
    if not rate:
        return {
            "available": False,
            "provider": provider,
            "model": model,
            "warnings": [
                "No public API price is configured for this provider/model; cost was not estimated."
            ],
        }
    if provider == "claude":
        return _estimate_claude_cost(rate, model, usage)
    return _estimate_openai_cost(rate, model, usage, context_window=context_window)


def find_price_rate(provider: str, model: str) -> PriceRate | None:
    table = _ANTHROPIC_RATES if provider == "claude" else _OPENAI_RATES
    normalized = _normalize_model(model)
    variants = {normalized, normalized.replace(".", "-")}
    for key in sorted(table, key=len, reverse=True):
        for variant in variants:
            if variant == key or variant.startswith(f"{key}-"):
                return table[key]
    return None


def _estimate_openai_cost(
    rate: PriceRate,
    model: str,
    usage: "ExactUsage",
    *,
    context_window: int | None,
) -> dict[str, Any]:
    input_rate = rate.input_per_million
    cached_rate = rate.cached_input_per_million
    output_rate = rate.output_per_million
    if (
        rate.long_context_threshold
        and context_window
        and context_window > rate.long_context_threshold
    ):
        input_rate = rate.long_input_per_million or input_rate
        cached_rate = (
            rate.long_cached_input_per_million
            if rate.long_cached_input_per_million is not None
            else cached_rate
        )
        output_rate = rate.long_output_per_million or output_rate

    warnings = [
        "Cost is an API-equivalent estimate from recorded token counts, not a Codex subscription bill."
    ]
    input_tokens = max(0, usage.input_tokens)
    cached_tokens = max(0, usage.cached_input_tokens)
    if cached_tokens > input_tokens:
        warnings.append("cached_input_tokens exceeded input_tokens and was capped for pricing.")
        cached_tokens = input_tokens
    uncached_tokens = input_tokens - cached_tokens
    if cached_tokens and cached_rate is None:
        warnings.append(
            "Cached input price is unavailable for this model; cached tokens were priced as uncached input."
        )
        cached_rate = input_rate
    cached_rate = cached_rate if cached_rate is not None else input_rate

    input_cost = uncached_tokens * input_rate / MILLION
    cached_input_cost = cached_tokens * cached_rate / MILLION
    output_cost = usage.output_tokens * output_rate / MILLION
    return _cost_payload(
        provider="codex",
        model=model,
        priced_as=rate.priced_as,
        source_urls=(*rate.source_urls, OPENAI_USAGE_SOURCE),
        rates={
            "input_per_million": input_rate,
            "cached_input_per_million": cached_rate,
            "output_per_million": output_rate,
        },
        tokens={
            "input_tokens": uncached_tokens,
            "cached_input_tokens": cached_tokens,
            "output_tokens": usage.output_tokens,
            "reasoning_output_tokens": usage.reasoning_output_tokens,
        },
        costs={
            "input": input_cost,
            "cached_input": cached_input_cost,
            "output": output_cost,
        },
        warnings=warnings,
    )


def _estimate_claude_cost(rate: PriceRate, model: str, usage: "ExactUsage") -> dict[str, Any]:
    warnings = [
        "Cost is a local API-equivalent estimate and may differ from authoritative Claude billing."
    ]
    cache_5m = max(0, usage.cache_creation_5m_input_tokens)
    cache_1h = max(0, usage.cache_creation_1h_input_tokens)
    known_cache_creation = cache_5m + cache_1h
    aggregate_cache_creation = max(0, usage.cache_creation_input_tokens)
    generic_cache_creation = max(0, aggregate_cache_creation - known_cache_creation)
    if generic_cache_creation:
        warnings.append(
            "Cache creation duration split was unavailable; remaining cache writes were priced at the 5-minute rate."
        )

    cache_5m_rate = rate.cache_creation_5m_per_million or rate.input_per_million
    cache_1h_rate = rate.cache_creation_1h_per_million or cache_5m_rate
    cache_read_rate = rate.cache_read_per_million or rate.input_per_million
    input_cost = usage.input_tokens * rate.input_per_million / MILLION
    cache_5m_cost = cache_5m * cache_5m_rate / MILLION
    cache_1h_cost = cache_1h * cache_1h_rate / MILLION
    cache_creation_cost = generic_cache_creation * cache_5m_rate / MILLION
    cache_read_cost = usage.cache_read_input_tokens * cache_read_rate / MILLION
    output_cost = usage.output_tokens * rate.output_per_million / MILLION
    return _cost_payload(
        provider="claude",
        model=model,
        priced_as=rate.priced_as,
        source_urls=(*rate.source_urls, CLAUDE_CODE_COSTS_SOURCE),
        rates={
            "input_per_million": rate.input_per_million,
            "cache_creation_5m_per_million": cache_5m_rate,
            "cache_creation_1h_per_million": cache_1h_rate,
            "cache_read_per_million": cache_read_rate,
            "output_per_million": rate.output_per_million,
        },
        tokens={
            "input_tokens": usage.input_tokens,
            "cache_creation_5m_input_tokens": cache_5m,
            "cache_creation_1h_input_tokens": cache_1h,
            "cache_creation_input_tokens": generic_cache_creation,
            "cache_read_input_tokens": usage.cache_read_input_tokens,
            "output_tokens": usage.output_tokens,
        },
        costs={
            "input": input_cost,
            "cache_creation_5m": cache_5m_cost,
            "cache_creation_1h": cache_1h_cost,
            "cache_creation": cache_creation_cost,
            "cache_read": cache_read_cost,
            "output": output_cost,
        },
        warnings=warnings,
    )


def _cost_payload(
    *,
    provider: str,
    model: str,
    priced_as: str,
    source_urls: tuple[str, ...],
    rates: dict[str, float],
    tokens: dict[str, int],
    costs: dict[str, float],
    warnings: list[str],
) -> dict[str, Any]:
    total = sum(costs.values())
    return {
        "available": True,
        "provider": provider,
        "model": model,
        "priced_as": priced_as,
        "currency": "USD",
        "total": _round_cost(total),
        "breakdown": {key: _round_cost(value) for key, value in costs.items()},
        "tokens": tokens,
        "rates_per_million": rates,
        "source_urls": list(dict.fromkeys(source_urls)),
        "warnings": warnings,
    }


def _round_cost(value: float) -> float:
    return round(value, 8)


def _normalize_model(model: str) -> str:
    return "-".join(model.strip().lower().replace("_", "-").split())


def _rate(
    provider: str,
    priced_as: str,
    input_rate: float,
    output_rate: float,
    *,
    cached_input: float | None = None,
    cache_5m: float | None = None,
    cache_1h: float | None = None,
    cache_read: float | None = None,
    long_threshold: int | None = None,
    long_input: float | None = None,
    long_cached_input: float | None = None,
    long_output: float | None = None,
    sources: tuple[str, ...] = (),
) -> PriceRate:
    return PriceRate(
        provider=provider,
        priced_as=priced_as,
        input_per_million=input_rate,
        output_per_million=output_rate,
        cached_input_per_million=cached_input,
        cache_creation_5m_per_million=cache_5m,
        cache_creation_1h_per_million=cache_1h,
        cache_read_per_million=cache_read,
        long_context_threshold=long_threshold,
        long_input_per_million=long_input,
        long_cached_input_per_million=long_cached_input,
        long_output_per_million=long_output,
        source_urls=sources,
    )


_OPENAI_RATES: dict[str, PriceRate] = {}
for _key, _rate_value in {
    "gpt-5.5": _rate(
        "openai",
        "gpt-5.5",
        5.00,
        30.00,
        cached_input=0.50,
        long_threshold=270_000,
        long_input=10.00,
        long_cached_input=1.00,
        long_output=45.00,
        sources=(OPENAI_PRICING_SOURCE,),
    ),
    "gpt-5.5-pro": _rate(
        "openai",
        "gpt-5.5-pro",
        30.00,
        180.00,
        long_threshold=270_000,
        long_input=60.00,
        long_output=270.00,
        sources=(OPENAI_PRICING_SOURCE,),
    ),
    "gpt-5.4": _rate(
        "openai",
        "gpt-5.4",
        2.50,
        15.00,
        cached_input=0.25,
        long_threshold=270_000,
        long_input=5.00,
        long_cached_input=0.50,
        long_output=22.50,
        sources=(OPENAI_PRICING_SOURCE,),
    ),
    "gpt-5.4-mini": _rate(
        "openai",
        "gpt-5.4-mini",
        0.75,
        4.50,
        cached_input=0.075,
        sources=(OPENAI_PRICING_SOURCE,),
    ),
    "gpt-5.4-nano": _rate(
        "openai",
        "gpt-5.4-nano",
        0.20,
        1.25,
        cached_input=0.02,
        sources=(OPENAI_PRICING_SOURCE,),
    ),
    "gpt-5.4-pro": _rate(
        "openai",
        "gpt-5.4-pro",
        30.00,
        180.00,
        long_threshold=270_000,
        long_input=60.00,
        long_output=270.00,
        sources=(OPENAI_PRICING_SOURCE,),
    ),
}.items():
    _OPENAI_RATES[_key] = _rate_value


_ANTHROPIC_RATES: dict[str, PriceRate] = {}


def _add_anthropic_rate(
    keys: tuple[str, ...],
    priced_as: str,
    input_rate: float,
    output_rate: float,
    sources: tuple[str, ...],
) -> None:
    rate = _rate(
        "anthropic",
        priced_as,
        input_rate,
        output_rate,
        cache_5m=input_rate * 1.25,
        cache_1h=input_rate * 2,
        cache_read=input_rate * 0.1,
        sources=sources,
    )
    for key in keys:
        _ANTHROPIC_RATES[key] = rate


_add_anthropic_rate(
    ("claude-opus-4-7", "claude-opus-4.7", "opus-4-7", "opus-4.7"),
    "claude-opus-4-7",
    5.00,
    25.00,
    (CLAUDE_OPUS_47_SOURCE, CLAUDE_PROMPT_CACHING_SOURCE),
)
_add_anthropic_rate(
    ("claude-opus-4-6", "claude-opus-4.6", "claude-opus-4-5", "claude-opus-4.5"),
    "claude-opus-4.5/4.6",
    5.00,
    25.00,
    (CLAUDE_PROMPT_CACHING_SOURCE,),
)
_add_anthropic_rate(
    (
        "claude-sonnet-4-6",
        "claude-sonnet-4.6",
        "claude-sonnet-4-5",
        "claude-sonnet-4.5",
        "claude-sonnet-4",
    ),
    "claude-sonnet-4.5/4.6",
    3.00,
    15.00,
    (CLAUDE_PROMPT_CACHING_SOURCE,),
)
_add_anthropic_rate(
    ("claude-haiku-4-5", "claude-haiku-4.5"),
    "claude-haiku-4.5",
    1.00,
    5.00,
    (CLAUDE_PROMPT_CACHING_SOURCE,),
)
_add_anthropic_rate(
    ("claude-opus-4-1", "claude-opus-4.1", "claude-opus-4"),
    "claude-opus-4/4.1",
    15.00,
    75.00,
    (CLAUDE_PROMPT_CACHING_SOURCE,),
)
_add_anthropic_rate(
    ("claude-sonnet-3-7", "claude-sonnet-3.7", "claude-sonnet-3-5", "claude-sonnet-3.5"),
    "claude-sonnet-3.5/3.7",
    3.00,
    15.00,
    (CLAUDE_PROMPT_CACHING_SOURCE,),
)
_add_anthropic_rate(
    ("claude-haiku-3-5", "claude-haiku-3.5"),
    "claude-haiku-3.5",
    0.80,
    4.00,
    (CLAUDE_PROMPT_CACHING_SOURCE,),
)
_add_anthropic_rate(
    ("claude-haiku-3",),
    "claude-haiku-3",
    0.25,
    1.25,
    (CLAUDE_PROMPT_CACHING_SOURCE,),
)
