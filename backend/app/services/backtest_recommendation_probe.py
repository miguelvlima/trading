from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Instrument, MarketBar
from app.services.backtest_engine import BacktestConfig, aggregate_signals, run_backtest
from app.services.strategy_engine import BarInput, get_available_strategies, run_strategy

MIN_VIABLE_TRADES = 1


def load_symbol_bars(
    db: Session,
    *,
    symbol: str,
    timeframe: str,
    limit: int = 5000,
) -> list[BarInput]:
    instrument = db.execute(
        select(Instrument.id).where(Instrument.symbol == symbol.upper().strip())
    ).scalar_one_or_none()
    if instrument is None:
        return []
    rows = db.execute(
        select(MarketBar)
        .where(
            MarketBar.instrument_id == instrument,
            MarketBar.timeframe == timeframe,
        )
        .order_by(MarketBar.timestamp.asc())
        .limit(limit)
    ).scalars().all()
    return [
        BarInput(
            timestamp=bar.timestamp,
            open=float(bar.open),
            high=float(bar.high),
            low=float(bar.low),
            close=float(bar.close),
            volume=float(bar.volume),
        )
        for bar in rows
    ]


def _as_float(value: object | None, default: float | None = None) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    return default


def _as_int(value: object | None, default: int) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return default


def config_to_backtest_config(config: dict[str, object]) -> BacktestConfig:
    return BacktestConfig(
        initial_capital=_as_float(config.get("initial_capital"), 10_000.0) or 10_000.0,
        fee_bps=_as_float(config.get("fee_bps"), 5.0) or 5.0,
        fee_model=str(config.get("fee_model") or "fixed_bps"),
        slippage_bps=_as_float(config.get("slippage_bps"), 2.0) or 2.0,
        position_size_pct=_as_float(config.get("position_size_pct"), 100.0) or 100.0,
        position_sizing_model=str(config.get("position_sizing_model") or "fixed_pct"),
        risk_per_trade_pct=_as_float(config.get("risk_per_trade_pct"), 1.0) or 1.0,
        entry_confirmation_bars=_as_int(config.get("entry_confirmation_bars"), 1),
        execution_timing=str(config.get("execution_timing") or "next_open"),
        exit_mode=str(config.get("exit_mode") or "tp_sl_or_opposite"),
        stop_loss_pct=_as_float(config.get("stop_loss_pct")),
        take_profit_pct=_as_float(config.get("take_profit_pct")),
        max_bars_in_trade=_as_int(config.get("max_bars_in_trade"), 0) or None
        if isinstance(config.get("max_bars_in_trade"), (int, float))
        else None,
        benchmark_enabled=bool(config.get("benchmark_enabled", True)),
        slippage_model=str(config.get("slippage_model") or "atr_volume"),
    )


def _strategy_names_for_config(config: dict[str, object], fallback: list[str]) -> list[str]:
    raw = config.get("strategies")
    if isinstance(raw, list) and raw:
        return [str(item) for item in raw]
    return list(fallback)


def estimate_trades(
    bars: list[BarInput],
    *,
    symbol: str,
    strategy_names: list[str],
    config: dict[str, object],
) -> int:
    if not bars or not strategy_names:
        return 0

    min_signal = (
        _as_float(config.get("min_consensus_strength"))
        or _as_float(config.get("min_signal_strength"))
        or 0.1
    )
    strategy_mins_raw = config.get("strategy_min_strengths")
    strategy_mins: dict[str, float] = {}
    if isinstance(strategy_mins_raw, dict):
        for key, value in strategy_mins_raw.items():
            parsed = _as_float(value)
            if parsed is not None:
                strategy_mins[str(key)] = parsed

    per_strategy: dict[str, list[tuple[datetime, str, float]]] = {}
    for name in strategy_names:
        signals = run_strategy(name, symbol, bars)
        per_strategy[name] = [(item.timestamp, item.direction, item.strength) for item in signals]

    aggregated = aggregate_signals(
        per_strategy,
        min_signal_strength=min_signal,
        strategy_min_strengths=strategy_mins,
        min_consensus_strength=_as_float(config.get("min_consensus_strength")),
    )
    result = run_backtest(bars, aggregated, config_to_backtest_config(config))
    return int(result.metrics.trades_count)


def pick_strategy_with_most_trades(
    bars: list[BarInput],
    *,
    symbol: str,
    config: dict[str, object],
    exclude: set[str],
) -> tuple[str, int] | None:
    probe_config = deepcopy(config)
    probe_config["entry_confirmation_bars"] = 1
    current_strength = (
        _as_float(probe_config.get("min_consensus_strength"))
        or _as_float(probe_config.get("min_signal_strength"))
        or 0.1
    )
    probe_config["min_consensus_strength"] = min(current_strength, 0.05)
    probe_config["min_signal_strength"] = min(current_strength, 0.05)

    best_name: str | None = None
    best_count = 0
    for name in get_available_strategies():
        if name in exclude:
            continue
        count = estimate_trades(bars, symbol=symbol, strategy_names=[name], config=probe_config)
        if count > best_count:
            best_count = count
            best_name = name
    if best_name is None or best_count < MIN_VIABLE_TRADES:
        return None
    return best_name, best_count


def apply_recommendation_to_config(
    base_config: dict[str, object],
    recommendation: dict[str, Any],
    *,
    strategy_names: list[str],
) -> tuple[dict[str, object], list[str]]:
    config = deepcopy(base_config)
    strategies = list(strategy_names)
    suggested = recommendation.get("suggested_values")
    if not isinstance(suggested, dict):
        return config, strategies

    if isinstance(suggested.get("strategies"), list):
        strategies = [str(item) for item in suggested["strategies"] if str(item).strip()]
        config["strategies"] = strategies

    if isinstance(suggested.get("timeframe"), str):
        config["timeframe"] = suggested["timeframe"]

    if isinstance(suggested.get("stop_loss_pct"), (int, float)):
        config["stop_loss_pct"] = float(suggested["stop_loss_pct"])
    if isinstance(suggested.get("take_profit_pct"), (int, float)):
        config["take_profit_pct"] = float(suggested["take_profit_pct"])
    if isinstance(suggested.get("entry_confirmation_bars"), (int, float)):
        config["entry_confirmation_bars"] = int(suggested["entry_confirmation_bars"])

    if isinstance(suggested.get("min_consensus_strength_pct"), (int, float)):
        pct = float(suggested["min_consensus_strength_pct"]) / 100.0
        config["min_consensus_strength"] = pct
        config["min_signal_strength"] = pct

    per_strategy = suggested.get("strategy_min_strength_pct")
    if isinstance(per_strategy, dict):
        config["strategy_min_strengths"] = {
            str(key): float(value) / 100.0 for key, value in per_strategy.items()
        }

    return config, strategies


def filter_viable_recommendations(
    recommendations: list[dict[str, Any]],
    *,
    bars: list[BarInput],
    symbol: str,
    strategy_names: list[str],
    base_config: dict[str, object],
) -> list[dict[str, Any]]:
    if not bars:
        return recommendations

    viable: list[dict[str, Any]] = []
    for recommendation in recommendations:
        trial_config, trial_strategies = apply_recommendation_to_config(
            base_config,
            recommendation,
            strategy_names=strategy_names,
        )
        if not trial_strategies:
            continue
        trades = estimate_trades(
            bars,
            symbol=symbol,
            strategy_names=trial_strategies,
            config=trial_config,
        )
        if trades >= MIN_VIABLE_TRADES:
            enriched = dict(recommendation)
            enriched["expected_trades"] = trades
            viable.append(enriched)
    return viable
