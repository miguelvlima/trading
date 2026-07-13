from __future__ import annotations

import threading
from collections.abc import Callable
from datetime import UTC, datetime, time
from decimal import Decimal

from app.services.data_feed.types import Tick
from app.services.paper_trading.types import QuoteSnapshot


class QuoteCache:
    """Latest merged quote per symbol, fed by stream ticks.

    Tick events carry price fields incrementally (bid may arrive without last
    and vice-versa — measured in the gateway probe), so each update merges into
    the previous snapshot instead of replacing it. Thread-safe because ticks
    arrive on the provider's thread while the engine reads from the API loop.
    """

    def __init__(self, *, now_fn: Callable[[], datetime] = lambda: datetime.now(UTC)) -> None:
        self._now_fn = now_fn
        self._lock = threading.Lock()
        self._quotes: dict[str, QuoteSnapshot] = {}
        self._liveness = "UNKNOWN"

    def set_liveness(self, liveness: str) -> None:
        self._liveness = liveness

    def update_from_tick(self, tick: Tick) -> QuoteSnapshot:
        symbol = tick.symbol.upper()
        now = self._now_fn()
        with self._lock:
            previous = self._quotes.get(symbol)

            def merged(new: Decimal | None, old: Decimal | None) -> Decimal | None:
                return new if new is not None else old

            snapshot = QuoteSnapshot(
                symbol=symbol,
                received_at=now,
                last=merged(tick.last, previous.last if previous else None),
                bid=merged(tick.bid, previous.bid if previous else None),
                ask=merged(tick.ask, previous.ask if previous else None),
                data_liveness=self._liveness,
            )
            self._quotes[symbol] = snapshot
            return snapshot

    def get(self, symbol: str) -> QuoteSnapshot | None:
        with self._lock:
            return self._quotes.get(symbol.upper())

    def freshest_age_seconds(self, symbols: list[str] | None = None) -> float | None:
        """Age of the most recent quote across ``symbols`` (or all), if any."""
        now = self._now_fn()
        with self._lock:
            pool = (
                [q for s, q in self._quotes.items() if not symbols or s in symbols]
                if symbols is not None
                else list(self._quotes.values())
            )
        if not pool:
            return None
        return min(quote.age_seconds(now) for quote in pool)


def market_session(now: datetime) -> str:
    """US equities regular trading hours in UTC: 13:30-20:00 Mon-Fri (summer).

    Deliberately coarse (no holiday calendar, fixed DST offset): it gates paper
    proposals/fills, where a false "open" on a holiday only means orders wait
    for fresh quotes that never come — the freshness gate still protects fills.
    """
    if now.weekday() >= 5:
        return "closed"
    utc_time = now.astimezone(UTC).time()
    if time(13, 30) <= utc_time < time(20, 0):
        return "rth"
    return "closed"
