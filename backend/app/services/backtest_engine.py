from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.services.indicator_engine import atr, relative_volume
from app.services.strategy_engine import BarInput


@dataclass
class AggregatedSignal:
    direction: str
    confidence: float
    rationale: str


@dataclass
class SimulatedTrade:
    direction: str
    entry_timestamp: datetime
    exit_timestamp: datetime
    entry_price: float
    exit_price: float
    quantity: float
    gross_pnl: float
    fee_paid: float
    net_pnl: float
    return_pct: float
    bars_held: int
    entry_reason: str
    exit_reason: str


@dataclass
class BacktestMetrics:
    bars_processed: int
    trades_count: int
    net_pnl: float
    net_pnl_pct: float
    win_rate: float
    profit_factor: float
    max_drawdown_pct: float
    final_capital: float


@dataclass
class BacktestConfig:
    initial_capital: float
    fee_bps: float
    slippage_bps: float
    position_size_pct: float
    position_sizing_model: str  # "fixed_pct" | "atr_risk"
    risk_per_trade_pct: float
    entry_confirmation_bars: int
    execution_timing: str  # "signal_close" | "next_open"
    exit_mode: str
    stop_loss_pct: float | None
    take_profit_pct: float | None
    max_bars_in_trade: int | None
    benchmark_enabled: bool
    slippage_model: str  # "fixed" | "atr_volume"


# Typical daily ATR/close for liquid US equities; used to scale dynamic slippage around 1x.
_DYNAMIC_SLIPPAGE_BASELINE_ATR_PCT = 0.015
_ATR_RISK_STOP_ATR_MULTIPLIER = 2.0


@dataclass
class BacktestOutput:
    metrics: BacktestMetrics
    trades: list[SimulatedTrade]
    summary: dict[str, object]


def aggregate_signals(
    per_strategy: dict[str, list[tuple[datetime, str, float]]],
    min_signal_strength: float,
    strategy_min_strengths: dict[str, float] | None = None,
    min_consensus_strength: float | None = None,
) -> dict[datetime, AggregatedSignal]:
    strategy_thresholds = strategy_min_strengths or {}
    consensus_threshold = (
        min_consensus_strength if min_consensus_strength is not None else min_signal_strength
    )
    by_timestamp: dict[datetime, dict[str, float]] = {}
    for strategy_name, signals in per_strategy.items():
        strategy_threshold = strategy_thresholds.get(strategy_name, min_signal_strength)
        for timestamp, direction, strength in signals:
            if strength < strategy_threshold:
                continue
            bucket = by_timestamp.setdefault(timestamp, {"buy": 0.0, "sell": 0.0})
            if direction == "BUY":
                bucket["buy"] += strength
            elif direction == "SELL":
                bucket["sell"] += strength

    aggregated: dict[datetime, AggregatedSignal] = {}
    for timestamp, scores in by_timestamp.items():
        buy_score = scores["buy"]
        sell_score = scores["sell"]
        total = buy_score + sell_score
        if total <= 0:
            continue
        net = buy_score - sell_score
        confidence = abs(net) / total
        if confidence < consensus_threshold or net == 0:
            continue
        direction = "BUY" if net > 0 else "SELL"
        rationale = (
            f"Consensus {direction} with confidence {confidence:.3f} "
            f"(buy={buy_score:.3f}, sell={sell_score:.3f})."
        )
        aggregated[timestamp] = AggregatedSignal(
            direction=direction,
            confidence=confidence,
            rationale=rationale,
        )
    return aggregated


def run_backtest(
    bars: list[BarInput],
    aggregated_signals: dict[datetime, AggregatedSignal],
    config: BacktestConfig,
) -> BacktestOutput:
    return _simulate_window(bars=bars, aggregated_signals=aggregated_signals, config=config)


def run_backtest_with_walkforward(
    bars: list[BarInput],
    aggregated_signals: dict[datetime, AggregatedSignal],
    config: BacktestConfig,
    split_pct: float,
) -> BacktestOutput:
    if split_pct <= 0 or len(bars) < 10:
        return _simulate_window(bars=bars, aggregated_signals=aggregated_signals, config=config)

    split_index = int(len(bars) * (1.0 - split_pct / 100.0))
    split_index = max(5, min(len(bars) - 5, split_index))
    in_sample = bars[:split_index]
    out_sample = bars[split_index:]
    in_signals = {k: v for k, v in aggregated_signals.items() if k <= in_sample[-1].timestamp}
    out_signals = {k: v for k, v in aggregated_signals.items() if k >= out_sample[0].timestamp}

    in_result = _simulate_window(bars=in_sample, aggregated_signals=in_signals, config=config)
    out_result = _simulate_window(bars=out_sample, aggregated_signals=out_signals, config=config)
    full_result = _simulate_window(bars=bars, aggregated_signals=aggregated_signals, config=config)

    full_result.summary["walkforward"] = {
        "split_pct": split_pct,
        "split_index": split_index,
        "in_sample": _metrics_as_dict(in_result.metrics),
        "out_sample": _metrics_as_dict(out_result.metrics),
    }
    return full_result


def _metrics_as_dict(metrics: BacktestMetrics) -> dict[str, float | int]:
    return {
        "bars_processed": metrics.bars_processed,
        "trades_count": metrics.trades_count,
        "net_pnl": metrics.net_pnl,
        "net_pnl_pct": metrics.net_pnl_pct,
        "win_rate": metrics.win_rate,
        "profit_factor": metrics.profit_factor,
        "max_drawdown_pct": metrics.max_drawdown_pct,
        "final_capital": metrics.final_capital,
    }


def _resolve_long_risk_exit(
    bar: BarInput,
    entry_price: float,
    stop_loss_rate: float | None,
    take_profit_rate: float | None,
) -> tuple[str, float] | None:
    """Return (reason, raw_exit_price) when SL/TP is hit within the bar."""
    stop_price = entry_price * (1.0 - stop_loss_rate) if stop_loss_rate is not None else None
    tp_price = entry_price * (1.0 + take_profit_rate) if take_profit_rate is not None else None

    if stop_price is not None and bar.open <= stop_price:
        return "Stop-loss triggered (gap at open).", bar.open
    if tp_price is not None and bar.open >= tp_price:
        return "Take-profit triggered (gap at open).", bar.open

    stop_hit = stop_price is not None and bar.low <= stop_price
    tp_hit = tp_price is not None and bar.high >= tp_price
    if stop_hit and tp_hit:
        return "Stop-loss triggered (intrabar).", stop_price
    if stop_hit:
        return "Stop-loss triggered.", stop_price
    if tp_hit:
        return "Take-profit triggered.", tp_price
    return None


def _resolve_short_risk_exit(
    bar: BarInput,
    entry_price: float,
    stop_loss_rate: float | None,
    take_profit_rate: float | None,
) -> tuple[str, float] | None:
    """Return (reason, raw_exit_price) when SL/TP is hit within the bar."""
    stop_price = entry_price * (1.0 + stop_loss_rate) if stop_loss_rate is not None else None
    tp_price = entry_price * (1.0 - take_profit_rate) if take_profit_rate is not None else None

    if stop_price is not None and bar.open >= stop_price:
        return "Stop-loss triggered (gap at open).", bar.open
    if tp_price is not None and bar.open <= tp_price:
        return "Take-profit triggered (gap at open).", bar.open

    stop_hit = stop_price is not None and bar.high >= stop_price
    tp_hit = tp_price is not None and bar.low <= tp_price
    if stop_hit and tp_hit:
        return "Stop-loss triggered (intrabar).", stop_price
    if stop_hit:
        return "Stop-loss triggered.", stop_price
    if tp_hit:
        return "Take-profit triggered.", tp_price
    return None


def _dynamic_slippage_bps(
    *,
    base_bps: float,
    atr_value: float | None,
    close: float,
    relative_vol: float | None,
) -> float:
    if close <= 0:
        return base_bps
    if atr_value is None:
        return base_bps

    atr_pct = atr_value / close
    atr_mult = max(0.5, min(4.0, atr_pct / _DYNAMIC_SLIPPAGE_BASELINE_ATR_PCT))
    if relative_vol is None or relative_vol <= 0:
        vol_mult = 1.0
    else:
        vol_mult = max(0.75, min(2.5, 1.0 / (relative_vol**0.5)))
    return base_bps * atr_mult * vol_mult


def _compute_position_quantity(
    *,
    capital: float,
    exec_price: float,
    bar_idx: int,
    atr_values: list[float | None],
    config: BacktestConfig,
    stop_loss_rate: float | None,
    position_size_rate: float,
) -> float:
    if exec_price <= 0 or capital <= 0:
        return 0.0

    if config.position_sizing_model == "atr_risk":
        risk_amount = capital * max(0.0, config.risk_per_trade_pct / 100.0)
        if stop_loss_rate:
            stop_distance = exec_price * stop_loss_rate
        else:
            atr_value = atr_values[bar_idx]
            stop_distance = (
                _ATR_RISK_STOP_ATR_MULTIPLIER * atr_value
                if atr_value is not None and atr_value > 0
                else exec_price * 0.02
            )
        qty = risk_amount / stop_distance if stop_distance > 0 else 0.0
        max_notional = capital * position_size_rate
        if exec_price * qty > max_notional:
            qty = max_notional / exec_price
        return qty

    return (capital * position_size_rate) / exec_price


def _simulate_window(
    bars: list[BarInput],
    aggregated_signals: dict[datetime, AggregatedSignal],
    config: BacktestConfig,
) -> BacktestOutput:
    initial_capital = config.initial_capital
    if not bars:
        metrics = BacktestMetrics(
            bars_processed=0,
            trades_count=0,
            net_pnl=0.0,
            net_pnl_pct=0.0,
            win_rate=0.0,
            profit_factor=0.0,
            max_drawdown_pct=0.0,
            final_capital=initial_capital,
        )
        return BacktestOutput(metrics=metrics, trades=[], summary={"note": "No bars available."})

    fee_rate = max(0.0, config.fee_bps / 10000.0)
    base_slippage_bps = max(0.0, config.slippage_bps)
    position_size_rate = max(0.01, min(1.0, config.position_size_pct / 100.0))
    stop_loss_rate = (config.stop_loss_pct / 100.0) if config.stop_loss_pct else None
    take_profit_rate = (config.take_profit_pct / 100.0) if config.take_profit_pct else None
    uses_next_open = config.execution_timing == "next_open"

    highs = [bar.high for bar in bars]
    lows = [bar.low for bar in bars]
    closes = [bar.close for bar in bars]
    volumes = [bar.volume for bar in bars]
    atr_values = atr(highs, lows, closes, 14)
    relative_volume_values = relative_volume(volumes, 20)

    capital = initial_capital
    trades: list[SimulatedTrade] = []
    bar_index: dict[datetime, int] = {bar.timestamp: idx for idx, bar in enumerate(bars)}
    equity_curve: list[dict[str, float | str]] = []

    position_direction: str | None = None
    entry_price = 0.0
    entry_timestamp: datetime | None = None
    quantity = 0.0
    entry_fee = 0.0
    entry_reason = ""
    entry_bar_idx = 0
    pending_entry: AggregatedSignal | None = None
    pending_exit: tuple[str, float | None] | None = None

    peak_equity = capital
    max_drawdown_pct = 0.0
    first_close = bars[0].close

    def slippage_rate_for_bar(bar_idx: int) -> float:
        if config.slippage_model != "atr_volume":
            return base_slippage_bps / 10000.0
        dynamic_bps = _dynamic_slippage_bps(
            base_bps=base_slippage_bps,
            atr_value=atr_values[bar_idx],
            close=bars[bar_idx].close,
            relative_vol=relative_volume_values[bar_idx],
        )
        return dynamic_bps / 10000.0

    def execution_price(raw_price: float, side: str, bar_idx: int) -> float:
        slip = slippage_rate_for_bar(bar_idx)
        if side == "BUY":
            return raw_price * (1.0 + slip)
        return raw_price * (1.0 - slip)

    def close_position(
        current_bar: BarInput,
        reason: str,
        exit_base_price: float | None = None,
    ) -> None:
        nonlocal capital
        nonlocal position_direction
        nonlocal entry_price
        nonlocal entry_timestamp
        nonlocal quantity
        nonlocal entry_fee
        nonlocal entry_reason
        nonlocal entry_bar_idx
        nonlocal pending_exit
        if position_direction is None or entry_timestamp is None:
            return

        exit_side = "SELL" if position_direction == "LONG" else "BUY"
        raw_exit = exit_base_price if exit_base_price is not None else current_bar.close
        exit_idx = bar_index[current_bar.timestamp]
        exit_price = execution_price(raw_exit, exit_side, exit_idx)
        exit_notional = abs(exit_price * quantity)
        exit_fee = exit_notional * fee_rate

        if position_direction == "LONG":
            gross_pnl = (exit_price - entry_price) * quantity
            return_pct = (exit_price / entry_price) - 1.0 if entry_price else 0.0
        else:
            gross_pnl = (entry_price - exit_price) * quantity
            return_pct = (entry_price / exit_price) - 1.0 if exit_price else 0.0

        net_pnl = gross_pnl - entry_fee - exit_fee
        fee_paid = entry_fee + exit_fee
        capital += net_pnl

        trades.append(
            SimulatedTrade(
                direction=position_direction,
                entry_timestamp=entry_timestamp,
                exit_timestamp=current_bar.timestamp,
                entry_price=entry_price,
                exit_price=exit_price,
                quantity=quantity,
                gross_pnl=gross_pnl,
                fee_paid=fee_paid,
                net_pnl=net_pnl,
                return_pct=return_pct,
                bars_held=max(1, bar_index[current_bar.timestamp] - bar_index[entry_timestamp]),
                entry_reason=entry_reason,
                exit_reason=reason,
            )
        )

        position_direction = None
        entry_price = 0.0
        entry_timestamp = None
        quantity = 0.0
        entry_fee = 0.0
        entry_reason = ""
        entry_bar_idx = 0
        pending_exit = None

    def schedule_or_close(reason: str, bar: BarInput, idx: int, raw_price: float | None = None) -> None:
        nonlocal pending_exit
        if position_direction is None:
            return
        if uses_next_open and idx + 1 < len(bars):
            pending_exit = (reason, raw_price)
            return
        close_position(bar, reason=reason, exit_base_price=raw_price)

    def open_position_at_price(
        current_bar: BarInput,
        signal: AggregatedSignal,
        index: int,
        raw_price: float,
    ) -> None:
        nonlocal position_direction
        nonlocal entry_price
        nonlocal entry_timestamp
        nonlocal quantity
        nonlocal entry_fee
        nonlocal entry_reason
        nonlocal entry_bar_idx
        if capital <= 0:
            return

        entry_side = "BUY" if signal.direction == "BUY" else "SELL"
        direction = "LONG" if signal.direction == "BUY" else "SHORT"
        exec_price = execution_price(raw_price, entry_side, index)
        qty = _compute_position_quantity(
            capital=capital,
            exec_price=exec_price,
            bar_idx=index,
            atr_values=atr_values,
            config=config,
            stop_loss_rate=stop_loss_rate,
            position_size_rate=position_size_rate,
        )
        if qty <= 0:
            return

        notional = abs(exec_price * qty)
        fee = notional * fee_rate
        position_direction = direction
        entry_price = exec_price
        entry_timestamp = current_bar.timestamp
        quantity = qty
        entry_fee = fee
        entry_reason = signal.rationale
        entry_bar_idx = index

    def should_exit_by_risk(current_bar: BarInput, index: int) -> tuple[str, float] | None:
        if position_direction is None:
            return None
        if index < entry_bar_idx:
            return None
        if index == entry_bar_idx and not uses_next_open:
            return None
        if position_direction == "LONG":
            return _resolve_long_risk_exit(
                current_bar,
                entry_price,
                stop_loss_rate,
                take_profit_rate,
            )
        return _resolve_short_risk_exit(
            current_bar,
            entry_price,
            stop_loss_rate,
            take_profit_rate,
        )

    def has_confirmed_signal(index: int, direction: str) -> AggregatedSignal | None:
        if index < 0:
            return None
        start_idx = index - config.entry_confirmation_bars + 1
        if start_idx < 0:
            return None
        current_signal = aggregated_signals.get(bars[index].timestamp)
        if current_signal is None or current_signal.direction != direction:
            return None
        for step_idx in range(start_idx, index + 1):
            step_signal = aggregated_signals.get(bars[step_idx].timestamp)
            if step_signal is None or step_signal.direction != direction:
                return None
        return current_signal

    for idx, bar in enumerate(bars):
        if pending_exit is not None and position_direction is not None:
            reason, raw_price = pending_exit
            close_position(bar, reason=reason, exit_base_price=raw_price if raw_price is not None else bar.open)

        if pending_entry is not None and position_direction is None:
            open_position_at_price(bar, pending_entry, idx, bar.open)
            pending_entry = None

        risk_exit = should_exit_by_risk(bar, idx)
        if risk_exit:
            reason, exit_base_price = risk_exit
            close_position(bar, reason=reason, exit_base_price=exit_base_price)

        if (
            config.max_bars_in_trade
            and position_direction is not None
            and pending_exit is None
            and (idx - entry_bar_idx) >= config.max_bars_in_trade
        ):
            schedule_or_close("Max bars in trade reached.", bar, idx, bar.close if not uses_next_open else None)

        signal = aggregated_signals.get(bar.timestamp)
        if signal is not None:
            target_direction = "LONG" if signal.direction == "BUY" else "SHORT"
            allow_opposite_exit = config.exit_mode in {"opposite_signal", "tp_sl_or_opposite"}
            confirmed_signal = has_confirmed_signal(idx, signal.direction)
            if allow_opposite_exit and position_direction and position_direction != target_direction:
                if uses_next_open and idx + 1 < len(bars):
                    pending_exit = ("Opposite consensus signal.", None)
                    if confirmed_signal:
                        pending_entry = confirmed_signal
                else:
                    close_position(bar, reason="Opposite consensus signal.")
                    if confirmed_signal:
                        open_position_at_price(bar, confirmed_signal, idx, bar.close)
            elif position_direction is None and pending_entry is None and confirmed_signal:
                if uses_next_open:
                    if idx + 1 < len(bars):
                        pending_entry = confirmed_signal
                else:
                    open_position_at_price(bar, confirmed_signal, idx, bar.close)

        equity = capital
        equity_worst = capital
        if position_direction == "LONG":
            equity += (bar.close - entry_price) * quantity
            equity_worst += (bar.low - entry_price) * quantity
        elif position_direction == "SHORT":
            equity += (entry_price - bar.close) * quantity
            equity_worst += (entry_price - bar.high) * quantity

        peak_equity = max(peak_equity, equity)
        if peak_equity > 0:
            drawdown_pct = max(0.0, (peak_equity - equity_worst) / peak_equity)
            max_drawdown_pct = max(max_drawdown_pct, drawdown_pct)
        else:
            drawdown_pct = 0.0
        curve_point: dict[str, float | str] = {
            "timestamp": bar.timestamp.isoformat(),
            "equity": equity,
            "drawdown_pct": drawdown_pct,
        }
        if config.benchmark_enabled and first_close > 0:
            curve_point["benchmark_equity"] = initial_capital * (bar.close / first_close)
        equity_curve.append(curve_point)

    if position_direction is not None:
        close_position(bars[-1], reason="End of backtest window.")

    net_pnl = capital - initial_capital
    net_pnl_pct = (net_pnl / initial_capital) if initial_capital > 0 else 0.0
    winning_trades = [trade for trade in trades if trade.net_pnl > 0]
    losing_trades = [trade for trade in trades if trade.net_pnl < 0]
    win_rate = len(winning_trades) / len(trades) if trades else 0.0
    gross_profit = sum(trade.net_pnl for trade in winning_trades)
    gross_loss = abs(sum(trade.net_pnl for trade in losing_trades))
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else float(gross_profit > 0)
    avg_win = (gross_profit / len(winning_trades)) if winning_trades else 0.0
    avg_loss = (gross_loss / len(losing_trades)) if losing_trades else 0.0
    expectancy = (win_rate * avg_win) - ((1 - win_rate) * avg_loss)

    benchmark_return = 0.0
    if config.benchmark_enabled and bars[0].close > 0:
        benchmark_return = (bars[-1].close / bars[0].close) - 1.0

    metrics = BacktestMetrics(
        bars_processed=len(bars),
        trades_count=len(trades),
        net_pnl=net_pnl,
        net_pnl_pct=net_pnl_pct,
        win_rate=win_rate,
        profit_factor=profit_factor,
        max_drawdown_pct=max_drawdown_pct,
        final_capital=capital,
    )
    summary: dict[str, float | int | str | None] = {
        "initial_capital": initial_capital,
        "final_capital": capital,
        "winning_trades": len(winning_trades),
        "losing_trades": len(losing_trades),
        "best_trade_pnl": max((trade.net_pnl for trade in trades), default=0.0),
        "worst_trade_pnl": min((trade.net_pnl for trade in trades), default=0.0),
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "expectancy": expectancy,
        "benchmark_return_pct": benchmark_return,
        "alpha_vs_benchmark_pct": net_pnl_pct - benchmark_return,
        "config": {
            "position_size_pct": config.position_size_pct,
            "position_sizing_model": config.position_sizing_model,
            "risk_per_trade_pct": config.risk_per_trade_pct,
            "entry_confirmation_bars": config.entry_confirmation_bars,
            "execution_timing": config.execution_timing,
            "exit_mode": config.exit_mode,
            "stop_loss_pct": config.stop_loss_pct,
            "take_profit_pct": config.take_profit_pct,
            "max_bars_in_trade": config.max_bars_in_trade,
            "benchmark_enabled": config.benchmark_enabled,
            "slippage_model": config.slippage_model,
            "execution_model": "intrabar_ohlc_pessimistic",
            "signal_decision_point": "bar_close",
        },
        "equity_curve": equity_curve,
    }
    return BacktestOutput(metrics=metrics, trades=trades, summary=summary)
