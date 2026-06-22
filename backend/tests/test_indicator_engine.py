import pytest

from app.services.indicator_engine import (
    atr,
    bollinger_bands,
    ema,
    macd,
    relative_volume,
    rsi,
    sma,
    vwap,
)


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
