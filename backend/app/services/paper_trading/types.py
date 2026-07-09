from __future__ import annotations

from dataclasses import dataclass, field, fields
from datetime import datetime
from decimal import Decimal


@dataclass(frozen=True)
class QuoteSnapshot:
    """Latest known market state for one symbol, merged from stream ticks.

    ``received_at`` is the local UTC clock at arrival — the gateway probe showed
    broker tick timestamps are just the local receive time, so freshness is
    always measured against our own clock (docs/gateway-findings.md §4).
    """

    symbol: str
    received_at: datetime
    last: Decimal | None = None
    bid: Decimal | None = None
    ask: Decimal | None = None
    data_liveness: str = "UNKNOWN"  # REAL-TIME | DELAYED | ... (MarketDataType)

    def age_seconds(self, now: datetime) -> float:
        return max(0.0, (now - self.received_at).total_seconds())

    def spread_bps(self) -> float | None:
        if self.bid is None or self.ask is None:
            return None
        bid = float(self.bid)
        ask = float(self.ask)
        if bid <= 0 or ask < bid:
            return None
        mid = (ask + bid) / 2.0
        return (ask - bid) / mid * 10_000.0


# Order lifecycle states (PaperOrder.status).
STATUS_PROPOSED = "proposed"
STATUS_APPROVED = "approved"
STATUS_FILLED = "filled"
STATUS_REJECTED_RISK = "rejected_risk"
STATUS_REJECTED_USER = "rejected_user"
STATUS_CANCELLED = "cancelled"
STATUS_EXPIRED = "expired"

OPEN_STATUSES = (STATUS_PROPOSED, STATUS_APPROVED)
TERMINAL_STATUSES = (
    STATUS_FILLED,
    STATUS_REJECTED_RISK,
    STATUS_REJECTED_USER,
    STATUS_CANCELLED,
    STATUS_EXPIRED,
)


@dataclass(frozen=True)
class RiskSettings:
    """Risk limits and engine knobs, persisted as JSON on the portfolio.

    Defaults are deliberately conservative; every field can be overridden via
    the portfolio settings endpoint. Percentages are expressed 0-100.
    """

    max_position_pct: float = 10.0
    max_total_exposure_pct: float = 50.0
    require_stop_loss: bool = True
    default_stop_loss_pct: float = 2.0
    default_take_profit_pct: float = 4.0
    daily_loss_limit_pct: float = 3.0
    max_consecutive_losses: int = 3
    cooldown_minutes: int = 60

    position_sizing_model: str = "fixed_pct"  # fixed_pct | atr_risk
    position_size_pct: float = 10.0
    risk_per_trade_pct: float = 1.0

    fee_model: str = "ibkr_us_tiered"
    fee_bps: float = 1.0
    slippage_bps: float = 5.0

    quote_max_age_seconds: float = 120.0
    max_spread_bps: float = 50.0
    order_expiry_minutes: int = 30

    min_signal_strength: float = 0.3
    timeframe: str = "1d"
    symbols: tuple[str, ...] = ()
    strategies: tuple[str, ...] = ()
    rth_only: bool = True

    @classmethod
    def from_json(cls, raw: dict[str, object] | None) -> "RiskSettings":
        if not raw:
            return cls()
        known = {f.name for f in fields(cls)}
        kwargs: dict[str, object] = {}
        for key, value in raw.items():
            if key not in known:
                continue
            if key in ("symbols", "strategies") and isinstance(value, list):
                kwargs[key] = tuple(str(item).strip().upper() if key == "symbols" else str(item) for item in value)
            else:
                kwargs[key] = value
        return cls(**kwargs)  # type: ignore[arg-type]

    def to_json(self) -> dict[str, object]:
        data: dict[str, object] = {}
        for f in fields(self):
            value = getattr(self, f.name)
            data[f.name] = list(value) if isinstance(value, tuple) else value
        return data


@dataclass(frozen=True)
class RiskVeto:
    """A rejected order, with the machine code and the human (PT) reason."""

    code: str
    reason: str


@dataclass(frozen=True)
class FillComputation:
    """A computed simulated fill (not yet applied to the portfolio)."""

    price: float
    basis: str  # bid_ask | last_slippage
    fee: float
    quote_age_seconds: float
    data_liveness: str


@dataclass(frozen=True)
class FillDeferral:
    """Why an approved order could not be filled right now."""

    code: str  # no_quote | stale_quote | wide_spread
    reason: str


@dataclass
class EngineStatus:
    """Live status surfaced by GET /paper/engine/status and the WS stream."""

    running: bool
    kill_switch_active: bool
    kill_switch_reason: str | None
    feed_status: str  # fresh | stale | unavailable
    # Why the feed is not fresh, when diagnosable:
    # engine_stopped | no_provider | market_closed | no_ticks
    feed_reason: str | None
    feed_age_seconds: float | None
    data_liveness: str
    market_session: str  # rth | closed
    tracked_symbols: list[str] = field(default_factory=list)
    pending_orders: int = 0
    cooldown_until: str | None = None
    consecutive_losses: int = 0
    max_consecutive_losses: int = 0
