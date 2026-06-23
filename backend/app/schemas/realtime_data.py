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


class RealtimeHealthResponse(BaseModel):
    provider: str
    status: str
    last_update: datetime | None = None
    lag_seconds: float | None = None
    tracked_symbols: list[str]
    recent_errors: list[str]
