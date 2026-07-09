from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class PaperPortfolioCreateRequest(BaseModel):
    # Minimum keeps the portfolio tradeable: below ~$1k the position sizing
    # rounds every proposal down to 0 shares and the cockpit looks dead.
    initial_cash: float = Field(default=100_000.0, ge=1_000, le=1_000_000_000)
    risk_settings: dict[str, object] | None = None


class RiskSettingsUpdateRequest(BaseModel):
    risk_settings: dict[str, object] = Field(default_factory=dict)


class PaperPortfolioResponse(BaseModel):
    id: int
    initial_cash: float
    cash: float
    equity: float
    risk_settings: dict[str, object]
    engine_running: bool
    kill_switch_active: bool
    kill_switch_reason: str | None
    created_at: datetime
    updated_at: datetime


class PaperOrderResponse(BaseModel):
    id: int
    symbol: str
    side: str
    quantity: float
    order_type: str
    status: str
    stop_loss_pct: float | None
    take_profit_pct: float | None
    signal_snapshot: dict[str, object]
    risk_snapshot: dict[str, object]
    data_liveness: str
    reject_reason: str | None
    proposed_at: datetime
    decided_at: datetime | None
    filled_at: datetime | None


class PaperPositionResponse(BaseModel):
    symbol: str
    quantity: float
    avg_entry_price: float
    realized_pnl: float
    last_price: float | None
    unrealized_pnl: float | None
    updated_at: datetime


class PaperTradeResponse(BaseModel):
    id: int
    order_id: int
    symbol: str
    side: str
    quantity: float
    price: float
    fee_paid: float
    fill_basis: str
    quote_age_seconds: float | None
    data_liveness: str
    realized_pnl: float | None
    executed_at: datetime


class PaperEventResponse(BaseModel):
    id: int
    event_type: str
    severity: str
    symbol: str | None
    message: str
    payload: dict[str, object]
    created_at: datetime


class PaperPnlResponse(BaseModel):
    equity: float
    cash: float
    unrealized_pnl: float
    realized_pnl_today: float
    fees_today: float
    day_pnl: float
    trades_today: int


class EngineStatusResponse(BaseModel):
    running: bool
    kill_switch_active: bool
    kill_switch_reason: str | None
    feed_status: str
    feed_reason: str | None
    feed_age_seconds: float | None
    data_liveness: str
    market_session: str
    tracked_symbols: list[str]
    pending_orders: int
    cooldown_until: str | None
