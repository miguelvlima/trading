from __future__ import annotations

from typing import Any


def _round1(value: float) -> float:
    return round(value, 1)


def _as_float(value: object | None) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _as_int(value: object | None) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return None


def compute_suggested_values(
    param_hint: str | None,
    config: dict[str, object],
    strategy_names: list[str],
) -> dict[str, Any] | None:
    if not param_hint:
        return None

    normalized = param_hint.lower()
    suggested: dict[str, Any] = {}

    if "stop_loss_pct" in normalized:
        current = _as_float(config.get("stop_loss_pct"))
        if current is not None:
            suggested["stop_loss_pct"] = _round1(min(15.0, current + 0.5))

    if "take_profit_pct" in normalized:
        current = _as_float(config.get("take_profit_pct"))
        stop_loss = _as_float(config.get("stop_loss_pct"))
        if current is not None:
            suggested["take_profit_pct"] = _round1(min(30.0, current + 1.0))
        elif stop_loss is not None:
            suggested["take_profit_pct"] = _round1(min(30.0, max(stop_loss * 2.0, stop_loss + 1.0)))

    if "min_consensus_strength" in normalized:
        current = _as_float(config.get("min_consensus_strength"))
        if current is not None and len(strategy_names) > 1:
            next_pct = min(100, int(round(current * 100)) + 10)
            suggested["min_consensus_strength_pct"] = next_pct

    if "min_signal_strength" in normalized:
        raw = config.get("strategy_min_strengths")
        per_strategy: dict[str, int] = {}
        if isinstance(raw, dict):
            for strategy in strategy_names:
                current = _as_float(raw.get(strategy))
                if current is None:
                    current = _as_float(config.get("min_consensus_strength")) or 0.1
                per_strategy[strategy] = min(100, int(round(current * 100)) + 10)
        else:
            fallback = _as_float(config.get("min_consensus_strength")) or 0.1
            for strategy in strategy_names:
                per_strategy[strategy] = min(100, int(round(fallback * 100)) + 10)
        if per_strategy:
            suggested["strategy_min_strength_pct"] = per_strategy

    if "entry_confirmation_bars" in normalized:
        current = _as_int(config.get("entry_confirmation_bars")) or 1
        suggested["entry_confirmation_bars"] = min(5, current + 1)

    return suggested or None


def enrich_recommendation(
    recommendation: dict[str, Any],
    config: dict[str, object],
    strategy_names: list[str],
) -> dict[str, Any]:
    param_hint = recommendation.get("param_hint")
    hint_text = str(param_hint) if param_hint is not None else None
    suggested = compute_suggested_values(hint_text, config, strategy_names)
    if suggested is None:
        return recommendation
    enriched = dict(recommendation)
    enriched["suggested_values"] = suggested
    return enriched
