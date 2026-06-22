from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class InstrumentResponse(BaseModel):
    id: int
    symbol: str
    name: str | None = None
    exchange: str | None = None
    currency: str


class MarketBarResponse(BaseModel):
    timestamp: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal


class CsvImportRequest(BaseModel):
    symbol: str = Field(min_length=1, max_length=32)
    timeframe: str = Field(default="1d", min_length=1, max_length=16)
    csv_path: str = Field(min_length=1)
    instrument_name: str | None = Field(default=None, max_length=255)
    exchange: str | None = Field(default=None, max_length=64)
    currency: str = Field(default="USD", min_length=1, max_length=8)


class CsvImportResponse(BaseModel):
    symbol: str
    timeframe: str
    imported_rows: int


class IndicatorRowResponse(BaseModel):
    timestamp: datetime
    sma_20: float | None = None
    ema_20: float | None = None
    rsi_14: float | None = None
    macd: float | None = None
    macd_signal: float | None = None
    macd_histogram: float | None = None
    bollinger_upper: float | None = None
    bollinger_middle: float | None = None
    bollinger_lower: float | None = None
    atr_14: float | None = None
    vwap: float | None = None
    relative_volume_20: float | None = None


class IndicatorResponse(BaseModel):
    symbol: str
    timeframe: str
    rows: list[IndicatorRowResponse]
