from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

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
    entry_confirmation_bars: int
    exit_mode: str
    stop_loss_pct: float | None
    take_profit_pct: float | None
    max_bars_in_trade: int | None
    benchmark_enabled: bool


@dataclass
class BacktestOutput:
    metrics: BacktestMetrics
    trades: list[SimulatedTrade]
    summary: dict[str, object]


def aggregate_signals(
    per_strategy: dict[str, list[tuple[datetime, str, float]]],
    min_signal_strength: float,
) -> dict[datetime, AggregatedSignal]:
    by_timestamp: dict[datetime, dict[str, float]] = {}
    for strategy_name, signals in per_strategy.items():
        for timestamp, direction, strength in signals:
            if strength < min_signal_strength:
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
        if confidence < min_signal_strength or net == 0:
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
    slippage_rate = max(0.0, config.slippage_bps / 10000.0)
    position_size_rate = max(0.01, min(1.0, config.position_size_pct / 100.0))
    stop_loss_rate = (config.stop_loss_pct / 100.0) if config.stop_loss_pct else None
    take_profit_rate = (config.take_profit_pct / 100.0) if config.take_profit_pct else None

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

    peak_equity = capital
    max_drawdown_pct = 0.0

    def execution_price(close_price: float, side: str) -> float:
        if side == "BUY":
            return close_price * (1.0 + slippage_rate)
        return close_price * (1.0 - slippage_rate)

    def close_position(current_bar: BarInput, reason: str) -> None:
        nonlocal capital
        nonlocal position_direction
        nonlocal entry_price
        nonlocal entry_timestamp
        nonlocal quantity
        nonlocal entry_fee
        nonlocal entry_reason
        nonlocal entry_bar_idx
        if position_direction is None or entry_timestamp is None:
            return

        exit_side = "SELL" if position_direction == "LONG" else "BUY"
        exit_price = execution_price(current_bar.close, exit_side)
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

    def open_position(current_bar: BarInput, signal: AggregatedSignal, index: int) -> None:
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
        exec_price = execution_price(current_bar.close, entry_side)
        qty = (capital * position_size_rate) / exec_price if exec_price > 0 else 0.0
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

    def should_exit_by_risk(current_bar: BarInput, index: int) -> str | None:
        if position_direction is None:
            return None
        if config.max_bars_in_trade and (index - entry_bar_idx) >= config.max_bars_in_trade:
            return "Max bars in trade reached."
        if stop_loss_rate is not None:
            if position_direction == "LONG" and current_bar.close <= entry_price * (1 - stop_loss_rate):
                return "Stop-loss triggered."
            if position_direction == "SHORT" and current_bar.close >= entry_price * (1 + stop_loss_rate):
                return "Stop-loss triggered."
        if take_profit_rate is not None:
            if position_direction == "LONG" and current_bar.close >= entry_price * (1 + take_profit_rate):
                return "Take-profit triggered."
            if position_direction == "SHORT" and current_bar.close <= entry_price * (1 - take_profit_rate):
                return "Take-profit triggered."
        return None

    def has_confirmed_signal(index: int, direction: str) -> AggregatedSignal | None:
        if index < 0:
            return None
        start_idx = index - config.entry_confirmation_bars + 1
        if start_idx < 0:
            return None
        current_signal = aggregated_signals.get(bars[index].timestamp)
        if current_signal is None or current_signal.direction != direction:
            return None
        for idx in range(start_idx, index + 1):
            step_signal = aggregated_signals.get(bars[idx].timestamp)
            if step_signal is None or step_signal.direction != direction:
                return None
        return current_signal

    for idx, bar in enumerate(bars):
        risk_exit_reason = should_exit_by_risk(bar, idx)
        if risk_exit_reason:
            close_position(bar, reason=risk_exit_reason)

        signal = aggregated_signals.get(bar.timestamp)
        if signal is not None:
            target_direction = "LONG" if signal.direction == "BUY" else "SHORT"
            allow_opposite_exit = config.exit_mode in {"opposite_signal", "tp_sl_or_opposite"}
            if allow_opposite_exit and position_direction and position_direction != target_direction:
                close_position(bar, reason="Opposite consensus signal.")
            if position_direction is None:
                confirmed_signal = has_confirmed_signal(idx, signal.direction)
                if confirmed_signal:
                    open_position(bar, confirmed_signal, idx)

        equity = capital
        if position_direction == "LONG":
            equity += (bar.close - entry_price) * quantity
        elif position_direction == "SHORT":
            equity += (entry_price - bar.close) * quantity

        peak_equity = max(peak_equity, equity)
        if peak_equity > 0:
            drawdown_pct = (peak_equity - equity) / peak_equity
            max_drawdown_pct = max(max_drawdown_pct, drawdown_pct)
        equity_curve.append(
            {"timestamp": bar.timestamp.isoformat(), "equity": equity, "drawdown_pct": drawdown_pct}
        )

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
            "entry_confirmation_bars": config.entry_confirmation_bars,
            "exit_mode": config.exit_mode,
            "stop_loss_pct": config.stop_loss_pct,
            "take_profit_pct": config.take_profit_pct,
            "max_bars_in_trade": config.max_bars_in_trade,
            "benchmark_enabled": config.benchmark_enabled,
        },
        "equity_curve": equity_curve,
    }
    return BacktestOutput(metrics=metrics, trades=trades, summary=summary)
