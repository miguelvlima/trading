from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class BacktestRunRequest(BaseModel):
    symbol: str = Field(min_length=1, max_length=32)
    timeframe: str = Field(default="1d", min_length=1, max_length=16)
    strategies: list[str] = Field(min_length=1, max_length=8)
    start: datetime | None = None
    end: datetime | None = None
    limit: int = Field(default=2000, ge=200, le=10000)
    initial_capital: float = Field(default=10_000.0, gt=0.0, le=10_000_000.0)
    fee_bps: float = Field(default=5.0, ge=0.0, le=500.0)
    slippage_bps: float = Field(default=2.0, ge=0.0, le=500.0)
    min_signal_strength: float = Field(default=0.1, ge=0.0, le=1.0)
    strategy_min_strengths: dict[str, float] = Field(default_factory=dict)
    min_consensus_strength: float | None = Field(default=None, ge=0.0, le=1.0)
    position_size_pct: float = Field(default=100.0, gt=0.0, le=100.0)
    entry_confirmation_bars: int = Field(default=1, ge=1, le=5)
    exit_mode: Literal["opposite_signal", "tp_sl_or_opposite", "tp_sl_only"] = "tp_sl_or_opposite"
    stop_loss_pct: float | None = Field(default=2.0, gt=0.0, le=100.0)
    take_profit_pct: float | None = Field(default=4.0, gt=0.0, le=100.0)
    max_bars_in_trade: int | None = Field(default=None, ge=1, le=500)
    walkforward_split_pct: float = Field(default=0.0, ge=0.0, le=80.0)
    benchmark_enabled: bool = True


class BacktestTradeResponse(BaseModel):
    id: int
    direction: str
    entry_timestamp: datetime
    exit_timestamp: datetime
    entry_price: float
    exit_price: float
    quantity: float
    gross_pnl: float
    fee_paid: float
    net_pnl: float
    return_pct: float
    bars_held: int
    entry_reason: str
    exit_reason: str


class BacktestRunSummaryResponse(BaseModel):
    id: int
    owner_user_id: int
    symbol: str
    timeframe: str
    strategy_names: list[str]
    start_at: datetime | None
    end_at: datetime | None
    initial_capital: float
    fee_bps: float
    slippage_bps: float
    min_signal_strength: float
    bars_processed: int
    trades_count: int
    net_pnl: float
    net_pnl_pct: float
    win_rate: float
    profit_factor: float
    max_drawdown_pct: float
    created_at: datetime
    result_summary: dict[str, object]


class BacktestRunDetailResponse(BacktestRunSummaryResponse):
    trades: list[BacktestTradeResponse]
