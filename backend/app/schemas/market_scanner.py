from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel


class HotMoverSpark(BaseModel):
    points: list[float]  # ~30 recent closes for the sparkline
    interval: str  # e.g. "5m"


class HotMover(BaseModel):
    symbol: str
    name: str | None = None
    last: Decimal
    change_pct: Decimal  # +/-, already a percentage
    volume: int
    rel_volume: Decimal | None = None  # RVol vs a 20d average (None when unavailable)
    spark: HotMoverSpark


class HotMoversResponse(BaseModel):
    as_of: datetime  # UTC
    sort: str
    items: list[HotMover]
