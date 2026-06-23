"""Deterministic test doubles for the real-time data feed.

The suite must run fully offline, so endpoints/worker are always exercised
against :class:`FakeProvider` (injected via dependency override), never the real
IBKR/yfinance providers.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.services.data_feed.types import BarQuote


def build_bar_quotes(
    symbol: str,
    *,
    count: int = 5,
    start: datetime | None = None,
    base_price: Decimal = Decimal("100"),
    step: Decimal = Decimal("1"),
    timeframe_delta: timedelta = timedelta(days=1),
    last_is_non_final: bool = False,
) -> list[BarQuote]:
    """Build ``count`` deterministic, monotonically-rising bars (oldest first).

    When ``last_is_non_final`` is set, the most recent bar is marked
    ``is_final=False`` to simulate the in-formation period bar.
    """
    start_ts = start or datetime(2026, 1, 1, tzinfo=UTC)
    quotes: list[BarQuote] = []
    for index in range(count):
        close = base_price + step * index
        is_final = not (last_is_non_final and index == count - 1)
        quotes.append(
            BarQuote(
                symbol=symbol.upper(),
                timestamp=start_ts + timeframe_delta * index,
                open=close - Decimal("0.5"),
                high=close + Decimal("1"),
                low=close - Decimal("1"),
                close=close,
                volume=Decimal("1000") + Decimal(index),
                is_final=is_final,
            )
        )
    return quotes


class FakeProvider:
    """In-memory provider returning preloaded quotes; no network access."""

    name = "fake"

    def __init__(
        self,
        *,
        bars: dict[str, list[BarQuote]] | None = None,
        latest: dict[str, BarQuote] | None = None,
    ) -> None:
        self._bars = {key.upper(): value for key, value in (bars or {}).items()}
        self._latest = {key.upper(): value for key, value in (latest or {}).items()}
        self.calls: list[tuple[str, str, int]] = []

    def fetch_recent_bars(self, symbol: str, timeframe: str, limit: int) -> list[BarQuote]:
        key = symbol.upper()
        self.calls.append((key, timeframe, limit))
        bars = self._bars.get(key, [])
        return bars[-limit:] if limit > 0 else list(bars)

    def fetch_latest_quote(self, symbol: str) -> BarQuote | None:
        key = symbol.upper()
        if key in self._latest:
            return self._latest[key]
        bars = self._bars.get(key, [])
        return bars[-1] if bars else None


# Backwards-compatible alias (earlier revision name).
FakeMarketDataProvider = FakeProvider
