"""Deterministic test doubles for the real-time data feed."""

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
) -> list[BarQuote]:
    """Build ``count`` deterministic, monotonically-rising bars (oldest first)."""
    start_ts = start or datetime(2026, 1, 1, tzinfo=UTC)
    quotes: list[BarQuote] = []
    for index in range(count):
        close = base_price + step * index
        quotes.append(
            BarQuote(
                symbol=symbol.upper(),
                timestamp=start_ts + timeframe_delta * index,
                open=close - Decimal("0.5"),
                high=close + Decimal("1"),
                low=close - Decimal("1"),
                close=close,
                volume=Decimal("1000") + Decimal(index),
            )
        )
    return quotes


class FakeMarketDataProvider:
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
