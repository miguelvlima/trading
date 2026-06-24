"""Lookahead audit: signals on a bar prefix must match the full-series run."""

from datetime import UTC, datetime, timedelta

import pytest

from app.services.strategy_engine import BarInput, get_available_strategies, run_strategy


def _synthetic_bars(count: int, *, seed: float = 100.0) -> list[BarInput]:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    bars: list[BarInput] = []
    price = seed
    for index in range(count):
        drift = ((index * 17) % 11) - 5
        open_ = price
        close = max(1.0, price + drift * 0.4)
        high = max(open_, close) + 1.5
        low = min(open_, close) - 1.5
        bars.append(
            BarInput(
                timestamp=start + timedelta(days=index),
                open=open_,
                high=high,
                low=low,
                close=close,
                volume=1000 + (index % 7) * 250,
            )
        )
        price = close
    return bars


def _signal_fingerprint(strategy: str, bars: list[BarInput]) -> dict[datetime, tuple[str, float]]:
    signals = run_strategy(strategy, "TEST", bars)
    return {
        signal.timestamp: (signal.direction, round(signal.strength, 6))
        for signal in signals
    }


@pytest.mark.parametrize("strategy_name", get_available_strategies())
def test_strategy_signals_are_prefix_invariant(strategy_name: str) -> None:
    """Adding future bars must not change past signals (no cross-bar lookahead)."""
    full_bars = _synthetic_bars(120)
    prefix_len = 80
    prefix_bars = full_bars[:prefix_len]

    full_map = _signal_fingerprint(strategy_name, full_bars)
    prefix_map = _signal_fingerprint(strategy_name, prefix_bars)

    for timestamp, fingerprint in prefix_map.items():
        assert full_map.get(timestamp) == fingerprint, (
            f"{strategy_name}: signal at {timestamp} changed when future bars were added"
        )


def test_bollinger_uses_prior_bar_bands() -> None:
    """Breakout compares close[T] to bands computed through T-1."""
    start = datetime(2024, 1, 1, tzinfo=UTC)
    bars: list[BarInput] = []
    for index in range(25):
        bars.append(
            BarInput(
                timestamp=start + timedelta(days=index),
                open=100,
                high=101,
                low=99,
                close=100,
                volume=1000,
            )
        )
    breakout_ts = start + timedelta(days=25)
    bars.append(
        BarInput(
            timestamp=breakout_ts,
            open=100,
            high=135,
            low=99,
            close=130,
            volume=5000,
        )
    )

    signals = run_strategy("bollinger_breakout", "TEST", bars)
    breakout = [signal for signal in signals if signal.timestamp == breakout_ts]
    assert len(breakout) == 1
    assert breakout[0].direction == "BUY"
    # Band snapshot must come from the prior bar (index 24), not the breakout bar itself.
    assert breakout[0].indicator_snapshot["bollinger_upper"] is not None
    assert breakout[0].indicator_snapshot["bollinger_upper"] < 110
