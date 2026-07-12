from datetime import UTC, datetime, timedelta

import pytest

from app.services.indicator_engine import atr
from app.services.strategy_engine import BarInput, get_available_strategies, run_strategy


def _make_bars_from_closes(closes: list[float]) -> list[BarInput]:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    bars: list[BarInput] = []
    for index, close in enumerate(closes):
        bars.append(
            BarInput(
                timestamp=start + timedelta(days=index),
                open=close - 1,
                high=close + 1,
                low=close - 2,
                close=close,
                volume=1000 + index * 10,
            )
        )
    return bars


def test_strategy_registry_exposes_all_reference_strategies() -> None:
    strategies = get_available_strategies()
    assert "rsi_mean_reversion" in strategies
    assert "macd_crossover" in strategies
    assert "sma_ema_crossover" in strategies
    assert "bollinger_breakout" in strategies


def test_rsi_mean_reversion_generates_signal_on_oversold() -> None:
    closes = [100.0] * 20 + [90.0, 89.0, 88.0, 87.0]
    signals = run_strategy("rsi_mean_reversion", "AAPL", _make_bars_from_closes(closes))
    assert any(signal.direction == "BUY" for signal in signals)


def test_rsi_mean_reversion_suggests_atr_based_stop() -> None:
    closes = [100.0] * 20 + [90.0, 89.0, 88.0, 87.0]
    bars = _make_bars_from_closes(closes)
    signals = run_strategy("rsi_mean_reversion", "AAPL", bars)
    buys = [signal for signal in signals if signal.direction == "BUY"]
    assert buys

    atr_values = atr(
        [bar.high for bar in bars], [bar.low for bar in bars], closes, period=14
    )
    bar_by_ts = {bar.timestamp: (index, bar) for index, bar in enumerate(bars)}
    for signal in buys:
        index, bar = bar_by_ts[signal.timestamp]
        expected = max(0.5, atr_values[index] / bar.close * 100.0 * 1.5)
        assert signal.suggested_stop_pct == pytest.approx(expected)
        assert signal.suggested_stop_pct >= 0.5
        assert signal.suggested_take_profit_pct is None
        assert signal.indicator_snapshot["atr_14"] == pytest.approx(atr_values[index])


def test_rsi_suggested_stop_floor_on_tiny_atr() -> None:
    # Slow decline with hair-thin ranges: ATR ~0.02 on a ~100 price would give
    # a 0.03% stop — the 0.5% floor must apply.
    start = datetime(2026, 1, 1, tzinfo=UTC)
    bars = [
        BarInput(
            timestamp=start + timedelta(days=index),
            open=close,
            high=close + 0.01,
            low=close - 0.01,
            close=close,
            volume=1000,
        )
        for index, close in enumerate(100.0 - 0.01 * i for i in range(25))
    ]
    signals = run_strategy("rsi_mean_reversion", "AAPL", bars)
    buys = [signal for signal in signals if signal.direction == "BUY"]
    assert buys  # constant losses push RSI to 0
    assert all(signal.suggested_stop_pct == 0.5 for signal in buys)


def test_macd_crossover_generates_signals() -> None:
    closes = [100 + i for i in range(40)] + [140 - i for i in range(20)] + [120 + i for i in range(20)]
    signals = run_strategy("macd_crossover", "AAPL", _make_bars_from_closes(closes))
    assert len(signals) > 0


def test_sma_ema_crossover_generates_signals() -> None:
    closes = [100 + i * 0.1 for i in range(80)] + [108 - i * 0.4 for i in range(80)]
    signals = run_strategy("sma_ema_crossover", "AAPL", _make_bars_from_closes(closes))
    assert len(signals) > 0


def test_bollinger_breakout_generates_signal_on_breakout() -> None:
    closes = [100.0] * 30 + [130.0]
    signals = run_strategy("bollinger_breakout", "AAPL", _make_bars_from_closes(closes))
    assert any(signal.direction == "BUY" for signal in signals)
