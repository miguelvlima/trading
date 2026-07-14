from types import SimpleNamespace

import pytest

from app.services.indicator_engine import (
    atr,
    bollinger_bands,
    ema,
    macd,
    relative_volume,
    rsi,
    sma,
    swing_pivots,
    vwap,
)


def _pivot_bars(closes: list[float]) -> list[SimpleNamespace]:
    return [
        SimpleNamespace(close=close, timestamp=index) for index, close in enumerate(closes)
    ]


def test_swing_pivots_on_known_zigzag() -> None:
    pivots = swing_pivots(_pivot_bars([100.0, 110.0, 100.0, 120.0, 100.0]), 5.0)
    assert [
        (p.index, p.price, p.kind, p.confirmed_at_index) for p in pivots
    ] == [
        (0, 100.0, "low", 1),  # the +10% move to 110 confirms the starting low
        (1, 110.0, "high", 2),
        (2, 100.0, "low", 3),
        (3, 120.0, "high", 4),
    ]
    # Strict alternation is the zigzag invariant.
    kinds = [p.kind for p in pivots]
    assert all(a != b for a, b in zip(kinds, kinds[1:], strict=False))


def test_swing_pivots_prefix_stability_and_edges() -> None:
    closes = [100.0, 110.0, 100.0, 120.0, 100.0, 130.0]
    full = swing_pivots(_pivot_bars(closes), 5.0)
    prefix = swing_pivots(_pivot_bars(closes[:4]), 5.0)
    assert full[: len(prefix)] == prefix  # adding future bars never rewrites the past

    assert swing_pivots([], 5.0) == []
    # A move below the threshold never confirms a pivot.
    assert swing_pivots(_pivot_bars([100.0, 101.0, 100.0, 101.0]), 5.0) == []
    with pytest.raises(ValueError):
        swing_pivots(_pivot_bars([100.0]), 0.0)


def test_sma_and_ema_small_series() -> None:
    values = [1.0, 2.0, 3.0, 4.0, 5.0]
    assert sma(values, 3) == [None, None, 2.0, 3.0, 4.0]
    assert ema(values, 3) == [None, None, 2.0, 3.0, 4.0]


def test_rsi_uptrend_reaches_100() -> None:
    values = [10.0, 11.0, 12.0, 13.0, 14.0]
    result = rsi(values, period=2)
    assert result[:2] == [None, None]
    assert result[2] == 100.0
    assert result[3] == 100.0
    assert result[4] == 100.0


def test_macd_returns_aligned_series() -> None:
    values = [float(index) for index in range(1, 50)]
    macd_line, signal_line, histogram = macd(values, fast_period=3, slow_period=6, signal_period=3)

    assert len(macd_line) == len(values)
    assert len(signal_line) == len(values)
    assert len(histogram) == len(values)
    assert macd_line[-1] is not None
    assert signal_line[-1] is not None
    assert histogram[-1] is not None


def test_bollinger_bands_known_values() -> None:
    upper, middle, lower = bollinger_bands([1.0, 2.0, 3.0, 4.0, 5.0], period=3, std_dev_multiplier=2.0)

    assert middle == [None, None, 2.0, 3.0, 4.0]
    assert upper[0] is None and lower[0] is None
    assert upper[2] == pytest.approx(3.632993, rel=1e-6)
    assert lower[2] == pytest.approx(0.367007, rel=1e-6)


def test_atr_vwap_and_relative_volume() -> None:
    atr_values = atr(
        high=[10.0, 12.0, 13.0, 14.0],
        low=[8.0, 9.0, 10.0, 12.0],
        close=[9.0, 11.0, 12.0, 13.0],
        period=2,
    )
    assert atr_values == [None, 2.5, 2.75, 2.375]

    vwap_values = vwap(
        high=[10.0, 12.0],
        low=[8.0, 10.0],
        close=[9.0, 11.0],
        volume=[100.0, 200.0],
    )
    assert vwap_values[0] == pytest.approx(9.0)
    assert vwap_values[1] == pytest.approx(10.333333, rel=1e-6)

    relative_volume_values = relative_volume([100.0, 100.0, 200.0], period=2)
    assert relative_volume_values[0] is None
    assert relative_volume_values[1] == 1.0
    assert relative_volume_values[2] == pytest.approx(1.333333, rel=1e-6)
