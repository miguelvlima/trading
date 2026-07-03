from __future__ import annotations

from typing import Any

from app.services.backtest_concrete_pivots import (
    build_spiral_pivot_recommendations,
    strip_vague_recommendations,
)
from app.services.backtest_recommendation_policy import is_protected_winning_run
from app.services.backtest_insight_types import PriorRunSnapshot


def is_worsening_negative_streak(pnl_values: list[float], *, min_length: int = 3) -> bool:
    """True when each run is negative and PnL does not improve (newest first)."""
    if len(pnl_values) < min_length:
        return False
    streak = pnl_values[:min_length]
    if not all(value < 0 for value in streak):
        return False
    return all(streak[index] <= streak[index + 1] for index in range(len(streak) - 1))


def detect_parameter_tuning_spiral(
    prior_runs: list[PriorRunSnapshot],
    current_pnl_pct: float,
    *,
    min_streak: int = 3,
) -> bool:
    pnl_values = [current_pnl_pct, *[item.net_pnl_pct for item in prior_runs]]
    return is_worsening_negative_streak(pnl_values, min_length=min_streak)


def _has_monotonic_stop_loss_increase(
    config: dict[str, object],
    prior_runs: list[PriorRunSnapshot],
    *,
    min_steps: int = 2,
) -> bool:
    current_sl = config.get("stop_loss_pct")
    if not isinstance(current_sl, (int, float)):
        return False
    values = [float(current_sl)]
    for item in prior_runs:
        if isinstance(item.stop_loss_pct, (int, float)):
            values.append(float(item.stop_loss_pct))
    if len(values) < min_steps + 1:
        return False
    recent = values[: min_steps + 1]
    return all(recent[index] > recent[index + 1] for index in range(len(recent) - 1))


def apply_recommendation_guards(
    recommendations: list[dict[str, Any]],
    *,
    prior_runs: list[PriorRunSnapshot],
    current_pnl_pct: float,
    config: dict[str, object],
    strategy_names: list[str],
    timeframe: str,
    bar_counts: dict[str, int] | None = None,
    trades_count: int | None = None,
    bars: list | None = None,
    symbol: str | None = None,
    profit_factor: float | None = None,
) -> list[dict[str, Any]]:
    if trades_count == 0:
        return recommendations
    if is_protected_winning_run(
        trades_count=trades_count,
        net_pnl_pct=current_pnl_pct,
        profit_factor=profit_factor,
    ):
        return recommendations

    spiral = detect_parameter_tuning_spiral(prior_runs, current_pnl_pct)
    sl_creep = _has_monotonic_stop_loss_increase(config, prior_runs)

    if not spiral and not sl_creep:
        return recommendations

    actionable = [item for item in recommendations if item.get("param_hint")]
    if not actionable and not spiral:
        return recommendations

    non_incremental = [item for item in recommendations if not item.get("param_hint")]
    non_incremental = strip_vague_recommendations(non_incremental)
    pivots = build_spiral_pivot_recommendations(
        config=config,
        strategy_names=strategy_names,
        timeframe=timeframe,
        bar_counts=bar_counts,
        trades_count=trades_count,
        prior_runs=prior_runs,
        bars=bars,
        symbol=symbol,
    )
    return pivots + non_incremental


def filter_recommendations_for_symbol_streak(
    recommendations: list[dict[str, Any]],
    recent_pnls_newest_first: list[float],
) -> list[dict[str, Any]]:
    """Read-time guard: drop incremental param hints when recent runs worsened."""
    if not is_worsening_negative_streak(recent_pnls_newest_first, min_length=3):
        return recommendations
    if not any(item.get("param_hint") for item in recommendations):
        return recommendations
    return [item for item in recommendations if not item.get("param_hint")]
