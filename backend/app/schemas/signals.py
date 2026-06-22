from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


StrategyName = Literal[
    "rsi_mean_reversion",
    "macd_crossover",
    "sma_ema_crossover",
    "bollinger_breakout",
]


class SignalGenerateRequest(BaseModel):
    symbol: str = Field(min_length=1, max_length=32)
    timeframe: str = Field(default="1d", min_length=1, max_length=16)
    strategy: StrategyName
    start: datetime | None = None
    end: datetime | None = None
    limit: int = Field(default=1000, ge=1, le=5000)


class SignalResponse(BaseModel):
    id: int
    symbol: str
    timeframe: str
    strategy: str
    direction: str
    strength: float
    rationale: str
    timestamp: datetime
    indicator_snapshot: dict[str, float | None]


class SignalsGenerateResponse(BaseModel):
    strategy: str
    symbol: str
    timeframe: str
    generated_count: int
    signals: list[SignalResponse]
