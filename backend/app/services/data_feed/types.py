from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Protocol, runtime_checkable

# Duration of one bar per timeframe string. Used to derive a bar's *close time*
# (``timestamp + delta``) so we can tell whether its period has already ended.
TIMEFRAME_DELTAS: dict[str, timedelta] = {
    "1m": timedelta(minutes=1),
    "2m": timedelta(minutes=2),
    "5m": timedelta(minutes=5),
    "15m": timedelta(minutes=15),
    "30m": timedelta(minutes=30),
    "60m": timedelta(hours=1),
    "1h": timedelta(hours=1),
    "90m": timedelta(minutes=90),
    "2h": timedelta(hours=2),
    "4h": timedelta(hours=4),
    "1d": timedelta(days=1),
    "5d": timedelta(days=5),
    "1w": timedelta(weeks=1),
    "1wk": timedelta(weeks=1),
    "1mo": timedelta(days=30),
    "3mo": timedelta(days=90),
}


def timeframe_delta(timeframe: str) -> timedelta:
    delta = TIMEFRAME_DELTAS.get(timeframe.strip().lower())
    if delta is None:
        raise ValueError(f"Unsupported timeframe: {timeframe!r}")
    return delta


def timeframe_seconds(timeframe: str) -> float | None:
    """Bar interval in seconds, or None for an unknown timeframe."""
    delta = TIMEFRAME_DELTAS.get(timeframe.strip().lower())
    return delta.total_seconds() if delta is not None else None


def is_period_closed(timestamp: datetime, timeframe: str, *, now: datetime) -> bool:
    """Return True if the bar starting at ``timestamp`` has fully closed by ``now``.

    A bar is "final" once its period end (``timestamp + timeframe_delta``) is at or
    before ``now``. This is how the feed avoids persisting an in-formation bar
    whose ``close`` is still moving.
    """
    return timestamp + timeframe_delta(timeframe) <= now


@dataclass(frozen=True)
class BarQuote:
    """Normalized OHLCV quote returned by a market data provider.

    Mirrors the shape persisted in ``market_bars`` (see ``app.db.models.MarketBar``):
    ``symbol`` uppercase, ``timestamp`` timezone-aware UTC, OHLCV as ``Decimal``.

    ``is_final`` flags whether the bar's period has closed. Only final bars are
    persisted by the ingestion service, so backtests never read a ``close`` that
    is still changing (see contract in ``docs/realtime-data-feed-spec.md``).
    """

    symbol: str
    timestamp: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    is_final: bool = True


@dataclass(frozen=True)
class SymbolMatch:
    """A contract returned by a provider's symbol search (e.g. IBKR lookup)."""

    symbol: str
    name: str | None
    sec_type: str | None
    exchange: str | None
    currency: str | None


@dataclass(frozen=True)
class Tick:
    """A single real-time market-data update for one symbol.

    Pushed over the WebSocket as ticks arrive (IBKR ``reqMktData``). Every field
    except ``symbol``/``timestamp`` is optional because IBKR delivers price and
    size fields in separate tick events; the stream session merges them into the
    latest known snapshot. ``timestamp`` is provider/server time in UTC — never
    the local wall clock (see ``docs/realtime-data-feed-spec.md``).
    """

    symbol: str
    timestamp: datetime
    last: Decimal | None = None
    bid: Decimal | None = None
    ask: Decimal | None = None
    bid_size: Decimal | None = None
    ask_size: Decimal | None = None
    last_size: Decimal | None = None
    volume: Decimal | None = None  # cumulative day volume
    day_high: Decimal | None = None
    day_low: Decimal | None = None


@dataclass(frozen=True)
class IndexQuote:
    """A real-time value for a market index shown in the bottom strip.

    Indices use their own ``Index(...)`` contracts (a separate ``reqMktData``
    line each), so they count against the line budget alongside followed symbols.
    """

    symbol: str  # IBKR symbol, e.g. "SPX"
    name: str  # human label, e.g. "S&P 500"
    timestamp: datetime
    last: Decimal | None = None
    change_pct: Decimal | None = None


@runtime_checkable
class MarketDataProvider(Protocol):
    """Minimal contract every market data provider must implement.

    Implementations are responsible for their own rate-limiting / retry; the
    ingestion service and worker only depend on these two methods.
    """

    name: str

    def fetch_latest_quote(self, symbol: str) -> BarQuote | None:
        """Return the most recent bar for ``symbol`` or ``None`` if unavailable."""
        ...

    def fetch_recent_bars(self, symbol: str, timeframe: str, limit: int) -> list[BarQuote]:
        """Return up to ``limit`` recent bars for ``symbol`` at ``timeframe`` (oldest first)."""
        ...


# Callback signatures the streaming session registers with a provider. They are
# invoked from the provider's own thread/loop; the session is responsible for
# hopping back onto the WebSocket's event loop (``call_soon_threadsafe``).
TickCallback = Callable[[Tick], None]
IndexCallback = Callable[[IndexQuote], None]


@runtime_checkable
class StreamingProvider(Protocol):
    """A provider that can push live ticks/indices, on top of the REST contract.

    The WebSocket session drives subscriptions through this interface and never
    touches IBKR APIs directly, which keeps the session fully testable offline
    against a fake streaming provider. Implementations own their own event loop;
    each ``subscribe_*`` call corresponds to one market-data line (see the ~100
    line cap enforced by :class:`SubscriptionManager`).
    """

    def start(self, on_tick: TickCallback, on_index: IndexCallback) -> None:
        """Begin streaming, registering the tick/index sinks. Idempotent."""
        ...

    def stop(self) -> None:
        """Cancel every active subscription and release provider resources."""
        ...

    def subscribe(self, symbol: str) -> None:
        """Open a live market-data line for ``symbol`` (one line)."""
        ...

    def unsubscribe(self, symbol: str) -> None:
        """Cancel the live market-data line for ``symbol`` (frees one line)."""
        ...

    def subscribe_index(self, symbol: str) -> None:
        """Open a live line for an index contract (one line)."""
        ...
