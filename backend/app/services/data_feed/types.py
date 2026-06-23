from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class BarQuote:
    """Normalized OHLCV quote returned by a market data provider.

    Mirrors the shape persisted in ``market_bars`` (see ``app.db.models.MarketBar``):
    ``symbol`` uppercase, ``timestamp`` timezone-aware UTC, OHLCV as ``Decimal``.
    """

    symbol: str
    timestamp: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal


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
