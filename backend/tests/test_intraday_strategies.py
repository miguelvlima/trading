"""Estratégias intraday (Fase 4A): Opening Range Breakout e VWAP reversion,
com barras 5m sintéticas determinísticas e verificação anti-lookahead."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.services.strategy_engine import (
    BarInput,
    get_available_strategies,
    run_strategy,
)

SESSION_OPEN = datetime(2026, 7, 6, 13, 30, tzinfo=UTC)  # Monday 09:30 New York


def bars_5m(
    ohlcv: list[tuple[float, float, float, float, float]],
    *,
    start: datetime = SESSION_OPEN,
) -> list[BarInput]:
    return [
        BarInput(
            timestamp=start + timedelta(minutes=5 * index),
            open=o,
            high=h,
            low=l,
            close=c,
            volume=v,
        )
        for index, (o, h, l, c, v) in enumerate(ohlcv)
    ]


def flat_bars_5m(closes: list[float], *, start: datetime = SESSION_OPEN, volume: float = 100.0) -> list[BarInput]:
    """Bars where high=low=close: the zigzag/VWAP math reduces to the closes."""
    return bars_5m([(c, c, c, c, volume) for c in closes], start=start)


def test_new_strategies_are_registered() -> None:
    strategies = get_available_strategies()
    assert "opening_range_breakout" in strategies
    assert "vwap_reversion" in strategies


# -- Opening Range Breakout ---------------------------------------------------


def orb_session(breakout_bars: list[tuple[float, float, float, float, float]]) -> list[BarInput]:
    """First 30 min (6 bars) define the range 95-105; then the given bars."""
    opening = [
        (100.0, 105.0, 95.0, 100.0, 1000.0),
        (100.0, 104.0, 96.0, 101.0, 900.0),
        (101.0, 103.0, 97.0, 100.0, 800.0),
        (100.0, 102.0, 98.0, 99.0, 700.0),
        (99.0, 104.0, 96.0, 102.0, 600.0),
        (102.0, 103.0, 97.0, 100.0, 500.0),
    ]
    return bars_5m(opening + breakout_bars)


def test_orb_buy_and_sell_once_per_day() -> None:
    bars = orb_session(
        [
            (100.0, 106.5, 99.0, 106.0, 1200.0),  # close > 105: BUY here
            (106.0, 108.5, 105.0, 108.0, 1100.0),  # still above: no 2nd BUY
            (108.0, 108.0, 93.0, 94.0, 1500.0),  # close < 95: SELL here
            (94.0, 95.0, 92.0, 93.0, 1400.0),  # still below: no 2nd SELL
        ]
    )
    signals = run_strategy("opening_range_breakout", "AAPL", bars)

    buys = [s for s in signals if s.direction == "BUY"]
    sells = [s for s in signals if s.direction == "SELL"]
    assert len(buys) == 1 and len(sells) == 1

    buy = buys[0]
    assert buy.timestamp == bars[6].timestamp
    assert buy.strength == pytest.approx((106.0 - 105.0) / 10.0)  # distance / width
    assert buy.indicator_snapshot["range_high"] == 105.0
    assert buy.indicator_snapshot["range_low"] == 95.0
    # Stop at the far side of the range.
    assert buy.suggested_stop_pct == pytest.approx((106.0 - 95.0) / 106.0 * 100.0)

    sell = sells[0]
    assert sell.timestamp == bars[8].timestamp
    assert sell.strength == pytest.approx((95.0 - 94.0) / 10.0)
    assert sell.suggested_stop_pct == pytest.approx((105.0 - 94.0) / 94.0 * 100.0)


def test_orb_no_signal_inside_range_or_with_few_bars() -> None:
    inside = orb_session([(100.0, 104.0, 96.0, 103.0, 1000.0)] * 4)
    assert run_strategy("opening_range_breakout", "AAPL", inside) == []

    # The opening range itself (or less) can never signal.
    assert run_strategy("opening_range_breakout", "AAPL", orb_session([])) == []
    assert run_strategy("opening_range_breakout", "AAPL", []) == []


def test_orb_stays_silent_when_session_head_is_missing() -> None:
    """Cold start: history begins mid-session, so the first bars present are
    NOT the opening range — a breakout over that fake range must not signal."""
    mid_session = SESSION_OPEN + timedelta(hours=3)  # 12:30 New York
    bars = bars_5m(
        [
            (100.0, 105.0, 95.0, 100.0, 1000.0),
            (100.0, 104.0, 96.0, 101.0, 900.0),
            (101.0, 103.0, 97.0, 100.0, 800.0),
            (100.0, 102.0, 98.0, 99.0, 700.0),
            (99.0, 104.0, 96.0, 102.0, 600.0),
            (102.0, 103.0, 97.0, 100.0, 500.0),
            (100.0, 106.5, 99.0, 106.0, 1200.0),  # would "break" the fake range
        ],
        start=mid_session,
    )
    assert run_strategy("opening_range_breakout", "AAPL", bars) == []


def test_orb_resets_range_each_session() -> None:
    day1 = orb_session([(100.0, 106.5, 99.0, 106.0, 1200.0)])  # BUY on day 1
    day2 = orb_session([(100.0, 106.5, 99.0, 106.0, 1200.0)])
    next_day = SESSION_OPEN + timedelta(days=1)
    day2 = [
        BarInput(
            timestamp=next_day + timedelta(minutes=5 * index),
            open=bar.open,
            high=bar.high,
            low=bar.low,
            close=bar.close,
            volume=bar.volume,
        )
        for index, bar in enumerate(day2)
    ]
    signals = run_strategy("opening_range_breakout", "AAPL", day1 + day2)
    buys = [s for s in signals if s.direction == "BUY"]
    assert len(buys) == 2  # one per session, the daily cap resets


# -- VWAP reversion -----------------------------------------------------------


def vwap_bars(shock: float | None) -> list[BarInput]:
    """12 bars oscillating ±0.1 around 100, then an optional shock close."""
    closes = [100.1 if index % 2 == 0 else 99.9 for index in range(12)]
    if shock is not None:
        closes.append(shock)
    return flat_bars_5m(closes)


def test_vwap_reversion_buy_on_deep_negative_deviation() -> None:
    signals = run_strategy("vwap_reversion", "AAPL", vwap_bars(shock=98.0))
    assert len(signals) == 1
    signal = signals[0]
    assert signal.direction == "BUY"
    assert signal.strength == 1.0  # ~20 sigma: fully saturated
    assert signal.timestamp == SESSION_OPEN + timedelta(minutes=5 * 12)
    assert signal.indicator_snapshot["z_score"] < -1.5
    assert "abaixo do VWAP" in signal.rationale


def test_vwap_reversion_sell_symmetric() -> None:
    signals = run_strategy("vwap_reversion", "AAPL", vwap_bars(shock=102.0))
    assert len(signals) == 1
    assert signals[0].direction == "SELL"
    assert signals[0].indicator_snapshot["z_score"] > 1.5


def test_vwap_reversion_quiet_session_has_no_signals() -> None:
    assert run_strategy("vwap_reversion", "AAPL", vwap_bars(shock=None)) == []


def test_vwap_reversion_handles_zero_volume_and_few_bars() -> None:
    zero_volume = flat_bars_5m([100.0] * 20, volume=0.0)
    assert run_strategy("vwap_reversion", "AAPL", zero_volume) == []
    assert run_strategy("vwap_reversion", "AAPL", flat_bars_5m([100.0, 101.0])) == []
    assert run_strategy("vwap_reversion", "AAPL", []) == []


# -- double top / double bottom -------------------------------------------------

# Two tops at 110/110.2 (within 0.5%), neckline at the 100 low between them;
# the close below 100 only happens at the last bar.
DOUBLE_TOP_CLOSES = [
    102.0, 104.0, 108.0, 110.0, 106.0, 103.0, 100.0,
    104.0, 107.0, 110.2, 106.0, 103.0, 100.5, 99.0,
]

# Mirror image: bottoms at 110/109.9, neckline at the 120 high between them.
DOUBLE_BOTTOM_CLOSES = [
    118.0, 116.0, 112.0, 110.0, 114.0, 117.0, 120.0,
    116.0, 113.0, 109.9, 114.0, 117.0, 119.5, 121.0,
]


def test_double_top_signals_only_on_neckline_break() -> None:
    bars = flat_bars_5m(DOUBLE_TOP_CLOSES)

    # One bar before the break: the pattern exists but MUST stay silent.
    assert run_strategy("double_top_bottom", "AAPL", bars[:-1]) == []

    signals = run_strategy("double_top_bottom", "AAPL", bars)
    assert len(signals) == 1
    signal = signals[0]
    assert signal.direction == "SELL"
    assert signal.timestamp == bars[-1].timestamp  # the break bar, never earlier

    height = (110.0 + 110.2) / 2.0 - 100.0
    assert signal.indicator_snapshot["neckline"] == 100.0
    assert signal.indicator_snapshot["pattern_height"] == pytest.approx(height)
    assert signal.strength == pytest.approx(min(1.0, height / 99.0 * 10.0))
    # Stop above the second top; target = measured move below the neckline.
    assert signal.suggested_stop_pct == pytest.approx((110.2 - 99.0) / 99.0 * 100.0)
    assert signal.suggested_take_profit_pct == pytest.approx(
        (99.0 - (100.0 - height)) / 99.0 * 100.0
    )


def test_double_bottom_buy_on_neckline_break() -> None:
    bars = flat_bars_5m(DOUBLE_BOTTOM_CLOSES)
    assert run_strategy("double_top_bottom", "AAPL", bars[:-1]) == []

    signals = run_strategy("double_top_bottom", "AAPL", bars)
    assert len(signals) == 1
    signal = signals[0]
    assert signal.direction == "BUY"
    assert signal.timestamp == bars[-1].timestamp

    height = 120.0 - (110.0 + 109.9) / 2.0
    assert signal.suggested_stop_pct == pytest.approx((121.0 - 109.9) / 121.0 * 100.0)
    assert signal.suggested_take_profit_pct == pytest.approx(
        ((120.0 + height) - 121.0) / 121.0 * 100.0
    )


def test_double_top_requires_matching_tops() -> None:
    # Second "top" 2% above the first: not a double top, breaking the low is
    # just a pullback in an uptrend.
    closes = [
        102.0, 104.0, 108.0, 110.0, 106.0, 103.0, 100.0,
        104.0, 108.0, 112.5, 106.0, 103.0, 100.5, 99.0,
    ]
    assert run_strategy("double_top_bottom", "AAPL", flat_bars_5m(closes)) == []


def test_double_top_bottom_handles_few_bars() -> None:
    assert run_strategy("double_top_bottom", "AAPL", flat_bars_5m([100.0, 110.0])) == []
    assert run_strategy("double_top_bottom", "AAPL", []) == []


# -- anti-lookahead on intraday bars -------------------------------------------


def _intraday_synthetic(count: int) -> list[BarInput]:
    bars: list[BarInput] = []
    price = 100.0
    for index in range(count):
        drift = ((index * 13) % 9) - 4
        close = max(1.0, price + drift * 0.6)
        bars.append(
            BarInput(
                timestamp=SESSION_OPEN + timedelta(minutes=5 * index),
                open=price,
                high=max(price, close) + 0.8,
                low=min(price, close) - 0.8,
                close=close,
                volume=1000 + (index % 5) * 200,
            )
        )
        price = close
    return bars


@pytest.mark.parametrize(
    "strategy_name", ["opening_range_breakout", "vwap_reversion", "double_top_bottom"]
)
def test_intraday_strategies_are_prefix_invariant(strategy_name: str) -> None:
    """Same contract as test_strategy_lookahead, on genuinely intraday bars."""
    full_bars = _intraday_synthetic(60)
    prefix_bars = full_bars[:40]

    def fingerprint(bars: list[BarInput]) -> dict[datetime, tuple[str, float]]:
        return {
            s.timestamp: (s.direction, round(s.strength, 6))
            for s in run_strategy(strategy_name, "TEST", bars)
        }

    full_map = fingerprint(full_bars)
    for timestamp, mark in fingerprint(prefix_bars).items():
        assert full_map.get(timestamp) == mark
