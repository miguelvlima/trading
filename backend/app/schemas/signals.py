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
    source: str = "historical"


class SignalFormingBarInput(BaseModel):
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float = Field(default=0.0, ge=0.0)
    is_forming: bool = True


class SignalBarInput(BaseModel):
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float = Field(default=0.0, ge=0.0)


class SignalLiveEvaluateRequest(BaseModel):
    symbol: str = Field(min_length=1, max_length=32)
    timeframe: str = Field(default="1d", min_length=1, max_length=16)
    strategies: list[str] = Field(min_length=1, max_length=8)
    start: datetime | None = None
    end: datetime | None = None
    limit: int = Field(default=500, ge=50, le=5000)
    min_strength: float = Field(default=0.0, ge=0.0, le=1.0)
    persist: bool = True
    context_bars: list[SignalBarInput] | None = Field(default=None, max_length=5000)
    forming_bar: SignalFormingBarInput | None = None


class SignalLiveEvaluateResponse(BaseModel):
    symbol: str
    timeframe: str
    evaluated_at: datetime
    bar_timestamp: datetime | None
    is_forming_bar: bool = False
    signals: list[SignalResponse]


class SignalsGenerateResponse(BaseModel):
    strategy: str
    symbol: str
    timeframe: str
    generated_count: int
    signals: list[SignalResponse]
