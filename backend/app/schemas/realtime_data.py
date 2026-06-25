from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel


class RealtimeQuoteResponse(BaseModel):
    symbol: str
    timestamp: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    is_final: bool


class SymbolMatchResponse(BaseModel):
    symbol: str
    name: str | None = None
    sec_type: str | None = None
    exchange: str | None = None
    currency: str | None = None


class RealtimeHealthResponse(BaseModel):
    provider: str
    status: str
    last_update: datetime | None = None
    lag_seconds: float | None = None
    tracked_symbols: list[str]
    recent_errors: list[str]


class IndexSpecResponse(BaseModel):
    """Static descriptor for one index in the bottom strip (live values arrive
    over the WebSocket)."""

    symbol: str
    name: str
