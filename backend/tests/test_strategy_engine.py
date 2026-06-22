from datetime import UTC, datetime, timedelta

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
