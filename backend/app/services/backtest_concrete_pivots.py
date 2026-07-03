from __future__ import annotations

from typing import Any

from app.services.backtest_insight_types import PriorRunSnapshot
from app.services.backtest_recommendation_policy import (
    is_protected_winning_run,
    suppress_recommendations_for_winning_run,
)
from app.services.market_bar_availability import BACKTEST_MIN_BARS, is_timeframe_viable
from app.services.strategy_engine import BarInput, get_available_strategies
STRATEGY_LABELS: dict[str, str] = {
    "bollinger_breakout": "Bollinger Breakout",
    "macd_crossover": "MACD Crossover",
    "rsi_mean_reversion": "RSI Mean Reversion",
    "sma_ema_crossover": "SMA/EMA Crossover",
}

DEFAULT_RISK = {"stop_loss_pct": 2.0, "take_profit_pct": 4.0}
VAGUE_AREAS = frozenset(
    {
        "tuning_spiral_guard",
        "strategy_selection",
        "regime_change",
    }
)


def _strategy_label(name: str) -> str:
    return STRATEGY_LABELS.get(name, name)


def suggest_alternative_strategy(strategy_names: list[str]) -> str:
    available = get_available_strategies()
    current = set(strategy_names)
    for name in available:
        if name not in current:
            return name
    for name in available:
        if name != strategy_names[0]:
            return name
    return available[0] if available else "macd_crossover"


def suggest_alternative_timeframe(timeframe: str) -> str:
    if timeframe == "1d":
        return "1w"
    if timeframe == "1w":
        return "1d"
    return "1d"


def _as_float(value: object | None) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    return None


def build_strategy_pivot_recommendation(
    strategy_names: list[str],
    *,
    bars: list[BarInput] | None = None,
    symbol: str | None = None,
    config: dict[str, object] | None = None,
) -> dict[str, Any]:
    alternative: str | None = None
    if bars and symbol and config is not None:
        from app.services.backtest_recommendation_probe import pick_strategy_with_most_trades

        picked = pick_strategy_with_most_trades(
            bars,
            symbol=symbol,
            config=config,
            exclude=set(strategy_names),
        )
        if picked is not None:
            alternative = picked[0]

    if alternative is None:
        alternative = suggest_alternative_strategy(strategy_names)

    current_label = ", ".join(_strategy_label(name) for name in strategy_names)
    return {
        "area": "strategy_pivot",
        "suggestion": f"Trocar estratégia para {_strategy_label(alternative)} (actual: {current_label}).",
        "rationale": (
            "A combinação actual falhou repetidamente neste símbolo — testar um motor de sinais diferente."
        ),
        "param_hint": "strategies",
        "suggested_values": {"strategies": [alternative]},
    }

def build_timeframe_pivot_recommendation(
    timeframe: str,
    *,
    bar_counts: dict[str, int] | None = None,
    min_bars: int = BACKTEST_MIN_BARS,
) -> dict[str, Any] | None:
    alternative = suggest_alternative_timeframe(timeframe)
    if bar_counts is not None and not is_timeframe_viable(bar_counts, alternative, min_bars=min_bars):
        return None
    available = bar_counts.get(alternative, 0) if bar_counts is not None else None
    availability_note = (
        f" ({available} velas disponíveis)"
        if available is not None and bar_counts is not None
        else ""
    )
    return {
        "area": "timeframe_pivot",
        "suggestion": f"Passar de {timeframe} para {alternative}{availability_note}.",
        "rationale": (
            "Mudar a escala temporal altera ruído e frequência de trades sem repetir o mesmo afinamento de SL/TP."
        ),
        "param_hint": "timeframe",
        "suggested_values": {"timeframe": alternative},
    }


def build_risk_reset_recommendation(config: dict[str, object]) -> dict[str, Any] | None:
    stop_loss = _as_float(config.get("stop_loss_pct"))
    take_profit = _as_float(config.get("take_profit_pct"))
    target_sl = DEFAULT_RISK["stop_loss_pct"]
    target_tp = DEFAULT_RISK["take_profit_pct"]
    if stop_loss is None and take_profit is None:
        return None
    if (
        stop_loss is not None
        and stop_loss <= target_sl + 0.25
        and take_profit is not None
        and take_profit <= target_tp + 0.5
    ):
        return None
    sl_text = f"{stop_loss:g}%" if stop_loss is not None else "n/d"
    tp_text = f"{take_profit:g}%" if take_profit is not None else "n/d"
    return {
        "area": "risk_reset",
        "suggestion": f"Repor risco base: SL {target_sl:g}% e TP {target_tp:g}% (actual: SL {sl_text}, TP {tp_text}).",
        "rationale": (
            "Vários ajustes incrementais de SL/TP pioraram — voltar a uma base neutra antes de novo teste."
        ),
        "param_hint": "risk_reset",
        "suggested_values": {
            "stop_loss_pct": target_sl,
            "take_profit_pct": target_tp,
        },
    }


def build_entry_confirmation_recommendation(config: dict[str, object]) -> dict[str, Any] | None:
    raw = config.get("entry_confirmation_bars")
    current = int(raw) if isinstance(raw, (int, float)) else 1
    if current >= 2:
        return None
    target = 2
    return {
        "area": "entry_confirmation",
        "suggestion": f"Exigir {target} velas de confirmação na entrada (actual: {current}).",
        "rationale": "Filtrar entradas impulsivas reduz stops prematuros sem mexer outra vez no SL.",
        "param_hint": "entry_confirmation_bars",
        "suggested_values": {"entry_confirmation_bars": target},
    }


def build_consensus_filter_recommendation(
    config: dict[str, object],
    strategy_names: list[str],
) -> dict[str, Any] | None:
    if len(strategy_names) <= 1:
        return None
    current = _as_float(config.get("min_consensus_strength"))
    if current is None:
        current = _as_float(config.get("min_signal_strength"))
    if current is None:
        return None
    current_pct = int(round(current * 100))
    target_pct = max(25, min(50, current_pct + 15))
    if target_pct <= current_pct:
        return None
    return {
        "area": "consensus_filter",
        "suggestion": f"Subir consenso mínimo para {target_pct}% (actual: {current_pct}%).",
        "rationale": "Menos entradas fracas quando várias estratégias estão activas.",
        "param_hint": "min_consensus_strength",
        "suggested_values": {"min_consensus_strength_pct": target_pct},
    }


def build_loosen_entry_confirmation_recommendation(config: dict[str, object]) -> dict[str, Any] | None:
    raw = config.get("entry_confirmation_bars")
    current = int(raw) if isinstance(raw, (int, float)) else 1
    if current <= 1:
        return None
    return {
        "area": "loosen_entry_confirmation",
        "suggestion": f"Voltar confirmação de entrada para 1 vela (actual: {current}).",
        "rationale": "Com 0 trades, a confirmação extra pode estar a bloquear todas as entradas.",
        "param_hint": "entry_confirmation_bars",
        "suggested_values": {"entry_confirmation_bars": 1},
    }


def build_loosen_signal_strength_recommendation(
    config: dict[str, object],
    strategy_names: list[str],
) -> dict[str, Any] | None:
    current = _as_float(config.get("min_consensus_strength"))
    if current is None:
        current = _as_float(config.get("min_signal_strength"))
    if current is None:
        current = 0.1
    current_pct = int(round(current * 100))
    if current_pct <= 5:
        return None
    target_pct = max(5, current_pct - 5)
    suggested: dict[str, Any] = {"min_consensus_strength_pct": target_pct}
    if len(strategy_names) == 1:
        suggested["strategy_min_strength_pct"] = {strategy_names[0]: target_pct}
    return {
        "area": "loosen_signal_strength",
        "suggestion": f"Baixar limiar de força para {target_pct}% (actual: {current_pct}%).",
        "rationale": "Um limiar alto pode impedir qualquer entrada no período testado.",
        "param_hint": "loosen_min_signal_strength",
        "suggested_values": suggested,
    }


def build_zero_trade_recovery_recommendations(
    *,
    config: dict[str, object],
    strategy_names: list[str],
    bars: list[BarInput] | None = None,
    symbol: str | None = None,
) -> list[dict[str, Any]]:
    recs: list[dict[str, Any]] = []
    entry_loosen = build_loosen_entry_confirmation_recommendation(config)
    if entry_loosen is not None:
        recs.append(entry_loosen)
    strength_loosen = build_loosen_signal_strength_recommendation(config, strategy_names)
    if strength_loosen is not None:
        recs.append(strength_loosen)
    recs.append(
        build_strategy_pivot_recommendation(
            strategy_names,
            bars=bars,
            symbol=symbol,
            config=config,
        )
    )
    return recs


def _recent_zero_trade_runs(
    trades_count: int | None,
    prior_runs: list[PriorRunSnapshot] | None,
) -> bool:
    if trades_count == 0:
        return True
    return any(item.trades_count == 0 for item in (prior_runs or [])[:2])


def build_spiral_pivot_recommendations(
    *,
    config: dict[str, object],
    strategy_names: list[str],
    timeframe: str,
    bar_counts: dict[str, int] | None = None,
    min_bars: int = BACKTEST_MIN_BARS,
    trades_count: int | None = None,
    prior_runs: list[PriorRunSnapshot] | None = None,
    bars: list[BarInput] | None = None,
    symbol: str | None = None,
) -> list[dict[str, Any]]:
    if trades_count == 0:
        return build_zero_trade_recovery_recommendations(
            config=config,
            strategy_names=strategy_names,
            bars=bars,
            symbol=symbol,
        )

    pivots: list[dict[str, Any]] = [
        build_strategy_pivot_recommendation(
            strategy_names,
            bars=bars,
            symbol=symbol,
            config=config,
        ),
    ]
    timeframe_pivot = build_timeframe_pivot_recommendation(
        timeframe,
        bar_counts=bar_counts,
        min_bars=min_bars,
    )
    if timeframe_pivot is not None:
        pivots.append(timeframe_pivot)
    risk_reset = build_risk_reset_recommendation(config)
    if risk_reset is not None:
        pivots.append(risk_reset)
    if not _recent_zero_trade_runs(trades_count, prior_runs):
        entry_confirmation = build_entry_confirmation_recommendation(config)
        if entry_confirmation is not None:
            pivots.append(entry_confirmation)
    return pivots

def _is_worsening_negative_streak(pnl_values: list[float], *, min_length: int = 3) -> bool:
    if len(pnl_values) < min_length:
        return False
    streak = pnl_values[:min_length]
    if not all(value < 0 for value in streak):
        return False
    return all(streak[index] <= streak[index + 1] for index in range(len(streak) - 1))


def strip_vague_recommendations(recommendations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [item for item in recommendations if item.get("area") not in VAGUE_AREAS]


def materialize_recommendations(
    recommendations: list[dict[str, Any]],
    *,
    config: dict[str, object],
    strategy_names: list[str],
    timeframe: str,
    recent_pnls_newest_first: list[float] | None = None,
    prior_runs: list[PriorRunSnapshot] | None = None,
    current_pnl_pct: float | None = None,
    bar_counts: dict[str, int] | None = None,
    min_bars: int = BACKTEST_MIN_BARS,
    bars: list[BarInput] | None = None,
    symbol: str | None = None,
    trades_count: int | None = None,
    profit_factor: float | None = None,
) -> list[dict[str, Any]]:
    """Turn vague guidance into concrete, applicable pivot suggestions."""
    if is_protected_winning_run(
        trades_count=trades_count,
        net_pnl_pct=current_pnl_pct,
        profit_factor=profit_factor,
    ):
        return []

    if trades_count == 0:
        result = build_zero_trade_recovery_recommendations(
            config=config,
            strategy_names=strategy_names,
            bars=bars,
            symbol=symbol,
        )
        return _filter_probe_or_keep(result, bars=bars, symbol=symbol, strategy_names=strategy_names, config=config)

    spiral = False
    if is_protected_winning_run(
        trades_count=trades_count,
        net_pnl_pct=current_pnl_pct,
        profit_factor=profit_factor,
    ):
        spiral = False
    elif prior_runs is not None and current_pnl_pct is not None:
        from app.services.backtest_insight_guards import detect_parameter_tuning_spiral

        spiral = detect_parameter_tuning_spiral(prior_runs, current_pnl_pct)
    elif recent_pnls_newest_first:
        spiral = _is_worsening_negative_streak(recent_pnls_newest_first, min_length=3)

    has_vague = any(item.get("area") in VAGUE_AREAS for item in recommendations)
    has_incremental = any(
        item.get("param_hint")
        and item.get("area") not in {"strategy_pivot", "timeframe_pivot", "risk_reset", "entry_confirmation", "consensus_filter"}
        for item in recommendations
    )

    cleaned = strip_vague_recommendations(recommendations)
    if not spiral and not has_vague:
        result = _replace_inline_vague(cleaned, config, strategy_names, timeframe, bar_counts, min_bars, bars, symbol)
        return _filter_probe_or_keep(result, bars=bars, symbol=symbol, strategy_names=strategy_names, config=config)

    if spiral or has_vague or (not has_incremental and has_vague):
        pivots = build_spiral_pivot_recommendations(
            config=config,
            strategy_names=strategy_names,
            timeframe=timeframe,
            bar_counts=bar_counts,
            min_bars=min_bars,
            trades_count=trades_count,
            prior_runs=prior_runs,
            bars=bars,
            symbol=symbol,
        )
        non_param = [item for item in cleaned if not item.get("param_hint")]
        result = pivots + non_param
        return _filter_probe_or_keep(result, bars=bars, symbol=symbol, strategy_names=strategy_names, config=config)

    result = _replace_inline_vague(cleaned, config, strategy_names, timeframe, bar_counts, min_bars, bars, symbol)
    return suppress_recommendations_for_winning_run(
        _filter_probe_or_keep(result, bars=bars, symbol=symbol, strategy_names=strategy_names, config=config),
        trades_count=trades_count,
        net_pnl_pct=current_pnl_pct,
        profit_factor=profit_factor,
    )


def _filter_probe_or_keep(
    recommendations: list[dict[str, Any]],
    *,
    bars: list[BarInput] | None,
    symbol: str | None,
    strategy_names: list[str],
    config: dict[str, object],
) -> list[dict[str, Any]]:
    if not bars or not symbol:
        return recommendations
    from app.services.backtest_recommendation_probe import filter_viable_recommendations

    viable = filter_viable_recommendations(
        recommendations,
        bars=bars,
        symbol=symbol,
        strategy_names=strategy_names,
        base_config=config,
    )
    if viable:
        return viable
    recovery = build_zero_trade_recovery_recommendations(
        config=config,
        strategy_names=strategy_names,
        bars=bars,
        symbol=symbol,
    )
    return recovery or recommendations

def _replace_inline_vague(
    recommendations: list[dict[str, Any]],
    config: dict[str, object],
    strategy_names: list[str],
    timeframe: str,
    bar_counts: dict[str, int] | None = None,
    min_bars: int = BACKTEST_MIN_BARS,
    bars: list[BarInput] | None = None,
    symbol: str | None = None,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    replaced_strategy = False
    replaced_timeframe = False

    for item in recommendations:
        area = item.get("area")
        if area == "strategy_selection" and not replaced_strategy:
            result.append(
                build_strategy_pivot_recommendation(
                    strategy_names,
                    bars=bars,
                    symbol=symbol,
                    config=config,
                )
            )
            replaced_strategy = True
            continue
        if area == "regime_change" and not replaced_timeframe:
            timeframe_pivot = build_timeframe_pivot_recommendation(
                timeframe,
                bar_counts=bar_counts,
                min_bars=min_bars,
            )
            if timeframe_pivot is not None:
                result.append(timeframe_pivot)
            replaced_timeframe = True
            continue
        if area in VAGUE_AREAS:
            continue
        result.append(item)

    return result
