"""Deterministic test doubles for the real-time data feed.

The suite must run fully offline, so endpoints/worker are always exercised
against :class:`FakeProvider` (injected via dependency override), never the real
IBKR/yfinance providers.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.services.data_feed.types import (
    BarQuote,
    IndexCallback,
    IndexQuote,
    SymbolMatch,
    Tick,
    TickCallback,
)


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
        search_results: list[SymbolMatch] | None = None,
        scan_results: list[SymbolMatch] | None = None,
    ) -> None:
        self._bars = {key.upper(): value for key, value in (bars or {}).items()}
        self._latest = {key.upper(): value for key, value in (latest or {}).items()}
        self._search_results = search_results
        self._scan_results = scan_results
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

    def search_symbols(self, query: str, limit: int = 25) -> list[SymbolMatch]:
        results = self._search_results or []
        return results[:limit]

    def scan_active(self, count: int = 25) -> list[SymbolMatch]:
        results = self._scan_results or []
        return results[:count]


# Backwards-compatible alias (earlier revision name).
FakeMarketDataProvider = FakeProvider


# Fixed timestamp so streaming tests are deterministic (no wall clock).
FAKE_TICK_TS = datetime(2026, 1, 2, 14, 30, tzinfo=UTC)


class FakeStreamingProvider:
    """In-memory StreamingProvider that emits one synthetic update per subscribe.

    Each ``subscribe``/``subscribe_index`` call immediately invokes the
    registered sink with a deterministic Tick/IndexQuote, which lets the
    WebSocket session be tested end-to-end without a Gateway or timers. The call
    logs (``subscribe_calls`` / ``unsubscribe_calls``) let tests assert the
    cancel-on-switch behaviour.
    """

    name = "fake-stream"

    def __init__(self, *, last: Decimal = Decimal("300.42")) -> None:
        self._last = last
        self._on_tick: TickCallback | None = None
        self._on_index: IndexCallback | None = None
        self.started = False
        self.stopped = False
        self.subscribed: set[str] = set()
        self.indices: set[str] = set()
        self.subscribe_calls: list[str] = []
        self.unsubscribe_calls: list[str] = []

    def start(self, on_tick: TickCallback, on_index: IndexCallback) -> None:
        self._on_tick = on_tick
        self._on_index = on_index
        self.started = True

    def stop(self) -> None:
        self.stopped = True
        self.subscribed.clear()
        self.indices.clear()

    def subscribe(self, symbol: str) -> None:
        key = symbol.upper()
        self.subscribed.add(key)
        self.subscribe_calls.append(key)
        if self._on_tick is not None:
            self._on_tick(
                Tick(
                    symbol=key,
                    timestamp=FAKE_TICK_TS,
                    last=self._last,
                    bid=self._last - Decimal("0.02"),
                    ask=self._last + Decimal("0.02"),
                    bid_size=Decimal("4"),
                    ask_size=Decimal("2"),
                    last_size=Decimal("100"),
                    volume=Decimal("1240000"),
                    day_high=self._last + Decimal("1.5"),
                    day_low=self._last - Decimal("2.0"),
                )
            )

    def unsubscribe(self, symbol: str) -> None:
        key = symbol.upper()
        self.subscribed.discard(key)
        self.unsubscribe_calls.append(key)

    def subscribe_index(self, symbol: str) -> None:
        key = symbol.upper()
        self.indices.add(key)
        self.subscribe_calls.append(key)
        if self._on_index is not None:
            self._on_index(
                IndexQuote(
                    symbol=key,
                    name=key,
                    timestamp=FAKE_TICK_TS,
                    last=Decimal("100.00"),
                    change_pct=Decimal("0.50"),
                )
            )
