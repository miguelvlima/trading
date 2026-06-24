from datetime import UTC, datetime, timedelta

from app.services.backtest_engine import (
    AggregatedSignal,
    BacktestConfig,
    _compute_position_quantity,
    _dynamic_slippage_bps,
    aggregate_signals,
    run_backtest,
)
from app.services.strategy_engine import BarInput


def _bar(
    day: int,
    *,
    open_: float,
    high: float,
    low: float,
    close: float,
    volume: float = 1000.0,
) -> BarInput:
    return BarInput(
        timestamp=datetime(2024, 1, day, tzinfo=UTC),
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=volume,
    )


def _risk_config(**overrides: object) -> BacktestConfig:
    base = {
        "initial_capital": 10_000.0,
        "fee_bps": 0.0,
        "slippage_bps": 0.0,
        "slippage_model": "fixed",
        "position_size_pct": 100.0,
        "position_sizing_model": "fixed_pct",
        "risk_per_trade_pct": 1.0,
        "entry_confirmation_bars": 1,
        "execution_timing": "signal_close",
        "exit_mode": "tp_sl_only",
        "stop_loss_pct": 2.0,
        "take_profit_pct": 4.0,
        "max_bars_in_trade": None,
        "benchmark_enabled": False,
    }
    base.update(overrides)
    return BacktestConfig(**base)  # type: ignore[arg-type]


def test_aggregate_signals_uses_per_strategy_thresholds() -> None:
    ts = datetime(2024, 1, 1, tzinfo=UTC)
    per_strategy = {
        "rsi_mean_reversion": [(ts, "BUY", 0.25)],
        "macd_crossover": [(ts, "BUY", 0.15)],
    }

    aggregated = aggregate_signals(
        per_strategy=per_strategy,
        min_signal_strength=0.1,
        strategy_min_strengths={"rsi_mean_reversion": 0.3, "macd_crossover": 0.2},
        min_consensus_strength=0.1,
    )

    assert aggregated == {}


def test_aggregate_signals_applies_consensus_threshold() -> None:
    ts = datetime(2024, 1, 1, tzinfo=UTC)
    per_strategy = {
        "rsi_mean_reversion": [(ts, "BUY", 0.6)],
        "macd_crossover": [(ts, "SELL", 0.55)],
    }

    aggregated = aggregate_signals(
        per_strategy=per_strategy,
        min_signal_strength=0.1,
        strategy_min_strengths={},
        min_consensus_strength=0.8,
    )

    assert aggregated == {}


def test_long_stop_triggers_on_intrabar_low_not_close() -> None:
    entry_ts = datetime(2024, 1, 1, tzinfo=UTC)
    bars = [
        _bar(1, open_=100, high=101, low=99, close=100),
        _bar(2, open_=100, high=101, low=97, close=99.5),
    ]
    signals = {
        entry_ts: AggregatedSignal(direction="BUY", confidence=1.0, rationale="enter"),
    }

    result = run_backtest(bars, signals, _risk_config())

    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade.exit_reason == "Stop-loss triggered."
    assert trade.exit_price == 98.0


def test_long_stop_triggers_on_gap_at_open() -> None:
    entry_ts = datetime(2024, 1, 1, tzinfo=UTC)
    bars = [
        _bar(1, open_=100, high=101, low=99, close=100),
        _bar(2, open_=97, high=98, low=96, close=97.5),
    ]
    signals = {entry_ts: AggregatedSignal(direction="BUY", confidence=1.0, rationale="enter")}

    result = run_backtest(bars, signals, _risk_config())

    assert len(result.trades) == 1
    assert result.trades[0].exit_reason == "Stop-loss triggered (gap at open)."
    assert result.trades[0].exit_price == 97.0


def test_pessimistic_stop_when_both_sl_and_tp_touched_intrabar() -> None:
    entry_ts = datetime(2024, 1, 1, tzinfo=UTC)
    bars = [
        _bar(1, open_=100, high=101, low=99, close=100),
        _bar(2, open_=100, high=105, low=97, close=102),
    ]
    signals = {entry_ts: AggregatedSignal(direction="BUY", confidence=1.0, rationale="enter")}

    result = run_backtest(bars, signals, _risk_config())

    assert len(result.trades) == 1
    assert result.trades[0].exit_reason == "Stop-loss triggered (intrabar)."
    assert result.trades[0].exit_price == 98.0


def test_no_sl_on_signal_close_entry_bar_even_if_range_would_hit() -> None:
    entry_ts = datetime(2024, 1, 1, tzinfo=UTC)
    bars = [
        _bar(1, open_=100, high=101, low=97, close=100),
    ]
    signals = {entry_ts: AggregatedSignal(direction="BUY", confidence=1.0, rationale="enter")}

    result = run_backtest(bars, signals, _risk_config(execution_timing="signal_close"))

    assert len(result.trades) == 1
    assert result.trades[0].exit_reason == "End of backtest window."


def test_next_open_enters_on_following_bar_open() -> None:
    entry_ts = datetime(2024, 1, 1, tzinfo=UTC)
    next_ts = datetime(2024, 1, 2, tzinfo=UTC)
    bars = [
        _bar(1, open_=100, high=101, low=99, close=100),
        _bar(2, open_=102, high=103, low=101, close=102.5),
        _bar(3, open_=102.5, high=103, low=102, close=102.8),
    ]
    signals = {entry_ts: AggregatedSignal(direction="BUY", confidence=1.0, rationale="enter")}

    result = run_backtest(
        bars,
        signals,
        _risk_config(execution_timing="next_open", stop_loss_pct=None, take_profit_pct=None),
    )

    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade.entry_timestamp == next_ts
    assert trade.entry_price == 102.0


def test_next_open_skips_signal_on_last_bar() -> None:
    entry_ts = datetime(2024, 1, 1, tzinfo=UTC)
    bars = [_bar(1, open_=100, high=101, low=99, close=100)]
    signals = {entry_ts: AggregatedSignal(direction="BUY", confidence=1.0, rationale="enter")}

    result = run_backtest(bars, signals, _risk_config(execution_timing="next_open"))

    assert result.trades == []


def test_opposite_signal_exits_on_next_open() -> None:
    buy_ts = datetime(2024, 1, 1, tzinfo=UTC)
    sell_ts = datetime(2024, 1, 2, tzinfo=UTC)
    exit_ts = datetime(2024, 1, 3, tzinfo=UTC)
    bars = [
        _bar(1, open_=100, high=101, low=99, close=100),
        _bar(2, open_=101, high=102, low=100, close=101),
        _bar(3, open_=99, high=100, low=98, close=99.5),
        _bar(4, open_=99.5, high=100, low=99, close=99.8),
    ]
    signals = {
        buy_ts: AggregatedSignal(direction="BUY", confidence=1.0, rationale="buy"),
        sell_ts: AggregatedSignal(direction="SELL", confidence=1.0, rationale="sell"),
    }

    result = run_backtest(
        bars,
        signals,
        _risk_config(
            execution_timing="next_open",
            exit_mode="opposite_signal",
            stop_loss_pct=None,
            take_profit_pct=None,
        ),
    )

    assert len(result.trades) == 2
    long_trade = result.trades[0]
    assert long_trade.exit_timestamp == exit_ts
    assert long_trade.exit_reason == "Opposite consensus signal."
    assert long_trade.exit_price == 99.0


def test_dynamic_slippage_increases_with_atr_and_thin_volume() -> None:
    low = _dynamic_slippage_bps(base_bps=5.0, atr_value=1.0, close=100.0, relative_vol=1.2)
    high = _dynamic_slippage_bps(base_bps=5.0, atr_value=4.0, close=100.0, relative_vol=0.3)
    assert high > low


def test_dynamic_slippage_raises_entry_price_vs_fixed() -> None:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    bars: list[BarInput] = []
    for offset in range(19):
        ts = start + timedelta(days=offset)
        bars.append(BarInput(ts, 100, 101, 99, 100, 5000))
    entry_ts = start + timedelta(days=19)
    bars.append(BarInput(entry_ts, 100, 108, 98, 100, 400))
    exit_ts = start + timedelta(days=20)
    bars.append(BarInput(exit_ts, 100, 101, 99, 100, 5000))
    signals = {entry_ts: AggregatedSignal(direction="BUY", confidence=1.0, rationale="enter")}

    fixed = run_backtest(
        bars,
        signals,
        _risk_config(
            slippage_bps=10,
            slippage_model="fixed",
            stop_loss_pct=None,
            take_profit_pct=None,
            exit_mode="opposite_signal",
        ),
    )
    dynamic = run_backtest(
        bars,
        signals,
        _risk_config(
            slippage_bps=10,
            slippage_model="atr_volume",
            stop_loss_pct=None,
            take_profit_pct=None,
            exit_mode="opposite_signal",
        ),
    )

    assert dynamic.trades[0].entry_price > fixed.trades[0].entry_price


def test_atr_risk_position_sizing_is_smaller_than_full_capital() -> None:
    config = _risk_config(
        position_sizing_model="atr_risk",
        risk_per_trade_pct=1.0,
        position_size_pct=100.0,
        stop_loss_pct=2.0,
    )
    atr_values = [None] * 14 + [4.0] * 6
    fixed_qty = _compute_position_quantity(
        capital=10_000,
        exec_price=100,
        bar_idx=15,
        atr_values=atr_values,
        config=_risk_config(position_size_pct=100.0),
        stop_loss_rate=0.02,
        position_size_rate=1.0,
    )
    risk_qty = _compute_position_quantity(
        capital=10_000,
        exec_price=100,
        bar_idx=15,
        atr_values=atr_values,
        config=config,
        stop_loss_rate=0.02,
        position_size_rate=1.0,
    )
    assert risk_qty < fixed_qty
