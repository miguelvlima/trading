"""Endurecimento do paper engine para operação intraday (Fase 2):
sessão RTH com DST correto, TTL para ordens approved, flat EOD e preset
de day trading."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base
from app.db.models import (
    PaperEngineEvent,
    PaperOrder,
    PaperPortfolio,
    PaperPosition,
    User,
)
from app.services.data_feed.types import Tick
from app.services.paper_trading.engine import PaperEngine
from app.services.paper_trading.quotes import QuoteCache, in_eod_window, market_session
from app.services.paper_trading.types import (
    STATUS_APPROVED,
    STATUS_EXPIRED,
    STATUS_FILLED,
    STATUS_PROPOSED,
    STATUS_REJECTED_RISK,
    RiskSettings,
)

# Monday 2026-07-06, 15:00 UTC = 11:00 New York (EDT, UTC-4): mid-session.
SUMMER_RTH = datetime(2026, 7, 6, 15, 0, tzinfo=UTC)
# Monday 2026-07-06, 19:55 UTC = 15:55 New York: inside the 10-min EOD window.
SUMMER_EOD = datetime(2026, 7, 6, 19, 55, tzinfo=UTC)


class Clock:
    def __init__(self, now: datetime = SUMMER_RTH) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kwargs) -> None:
        self.now = self.now + timedelta(**kwargs)


def build_session_factory(tmp_path: Path) -> sessionmaker[Session]:
    engine = create_engine(f"sqlite:///{tmp_path / 'test_paper_hardening.db'}")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def seed_portfolio(
    session: Session, *, cash: float = 100_000.0, risk: dict | None = None
) -> PaperPortfolio:
    user = User(email="paper@example.com", password_hash="hash")
    session.add(user)
    session.flush()
    portfolio = PaperPortfolio(
        owner_user_id=user.id,
        initial_cash=Decimal(str(cash)),
        cash=Decimal(str(cash)),
        equity=Decimal(str(cash)),
        risk_settings=risk or {},
        engine_running=True,
    )
    session.add(portfolio)
    session.commit()
    return portfolio


def build_engine(portfolio: PaperPortfolio, clock: Clock) -> tuple[PaperEngine, QuoteCache]:
    cache = QuoteCache(now_fn=clock)
    cache.set_liveness("DELAYED")
    engine = PaperEngine(portfolio.id, quotes=cache, hub=None, now_fn=clock)
    return engine, cache


def feed_quote(
    cache: QuoteCache,
    symbol: str,
    *,
    last: float | None = None,
    bid: float | None = None,
    ask: float | None = None,
) -> None:
    cache.update_from_tick(
        Tick(
            symbol=symbol,
            timestamp=SUMMER_RTH,  # received_at comes from the cache clock, not this
            last=Decimal(str(last)) if last is not None else None,
            bid=Decimal(str(bid)) if bid is not None else None,
            ask=Decimal(str(ask)) if ask is not None else None,
        )
    )


def add_position(
    session: Session, portfolio: PaperPortfolio, symbol: str, quantity: str, entry: str
) -> PaperPosition:
    position = PaperPosition(
        portfolio_id=portfolio.id,
        symbol=symbol,
        quantity=Decimal(quantity),
        avg_entry_price=Decimal(entry),
    )
    session.add(position)
    session.flush()
    return position


def approved_order(
    session: Session,
    portfolio: PaperPortfolio,
    *,
    symbol: str,
    side: str,
    quantity: float,
    decided_at: datetime,
    origin: str | None = None,
) -> PaperOrder:
    snapshot: dict[str, object] = {"strategy": "test"}
    if origin is not None:
        snapshot["origin"] = origin
    order = PaperOrder(
        portfolio_id=portfolio.id,
        symbol=symbol,
        side=side,
        quantity=Decimal(str(quantity)),
        order_type="market",
        status=STATUS_APPROVED,
        signal_snapshot=snapshot,
        risk_snapshot={},
        data_liveness="DELAYED",
        proposed_at=decided_at,
        decided_at=decided_at,
    )
    session.add(order)
    session.flush()
    return order


def events_with_code(session: Session, portfolio_id: int, code: str) -> list[PaperEngineEvent]:
    return [
        event
        for event in session.execute(
            select(PaperEngineEvent)
            .where(PaperEngineEvent.portfolio_id == portfolio_id)
            .order_by(PaperEngineEvent.id)
        ).scalars()
        if (event.payload or {}).get("code") == code
    ]


# -- 1) market_session with correct DST ----------------------------------------


def test_market_session_winter_uses_est() -> None:
    # Thursday 2026-01-15 (EST, UTC-5): RTH = 14:30-21:00 UTC.
    assert market_session(datetime(2026, 1, 15, 14, 0, tzinfo=UTC)) == "closed"
    assert market_session(datetime(2026, 1, 15, 14, 30, tzinfo=UTC)) == "rth"
    assert market_session(datetime(2026, 1, 15, 15, 0, tzinfo=UTC)) == "rth"
    assert market_session(datetime(2026, 1, 15, 20, 59, tzinfo=UTC)) == "rth"
    assert market_session(datetime(2026, 1, 15, 21, 0, tzinfo=UTC)) == "closed"


def test_market_session_summer_uses_edt() -> None:
    # Monday 2026-07-06 (EDT, UTC-4): RTH = 13:30-20:00 UTC.
    assert market_session(datetime(2026, 7, 6, 13, 0, tzinfo=UTC)) == "closed"
    assert market_session(datetime(2026, 7, 6, 13, 30, tzinfo=UTC)) == "rth"
    assert market_session(datetime(2026, 7, 6, 19, 59, tzinfo=UTC)) == "rth"
    assert market_session(datetime(2026, 7, 6, 20, 0, tzinfo=UTC)) == "closed"


def test_market_session_weekend_is_closed() -> None:
    assert market_session(datetime(2026, 7, 4, 15, 0, tzinfo=UTC)) == "closed"  # Saturday
    assert market_session(datetime(2026, 7, 5, 15, 0, tzinfo=UTC)) == "closed"  # Sunday


def test_in_eod_window_boundaries() -> None:
    # Summer: close at 20:00 UTC; the 10-min window starts 19:50 UTC.
    assert in_eod_window(datetime(2026, 7, 6, 19, 49, tzinfo=UTC), 10) is False
    assert in_eod_window(datetime(2026, 7, 6, 19, 50, tzinfo=UTC), 10) is True
    assert in_eod_window(datetime(2026, 7, 6, 19, 59, tzinfo=UTC), 10) is True
    assert in_eod_window(datetime(2026, 7, 6, 20, 0, tzinfo=UTC), 10) is False  # closed
    # Winter: close at 21:00 UTC.
    assert in_eod_window(datetime(2026, 1, 15, 20, 51, tzinfo=UTC), 10) is True
    assert in_eod_window(datetime(2026, 1, 15, 20, 40, tzinfo=UTC), 10) is False
    # Weekend never has a window.
    assert in_eod_window(datetime(2026, 7, 4, 19, 55, tzinfo=UTC), 10) is False


# -- 2) TTL for approved orders ---------------------------------------------------


def test_stale_approved_buy_expires_but_closing_sells_never_do(tmp_path: Path) -> None:
    factory = build_session_factory(tmp_path)
    clock = Clock(SUMMER_RTH)
    with factory() as session:
        portfolio = seed_portfolio(session)  # approved_fill_timeout_minutes=10
        engine, _cache = build_engine(portfolio, clock)  # no quotes: fills impossible

        entry = approved_order(
            session, portfolio, symbol="AAPL", side="BUY", quantity=10, decided_at=clock.now
        )
        # Every SELL is position-closing (shorting disabled): none may expire,
        # whatever its origin — protective, flat EOD, manual or signal close.
        closing_sells = [
            approved_order(
                session,
                portfolio,
                symbol=symbol,
                side="SELL",
                quantity=5,
                decided_at=clock.now,
                origin=origin,
            )
            for symbol, origin in (
                ("MSFT", "protective"),
                ("NVDA", "flat_eod"),
                ("AMD", "manual"),
                ("TSLA", None),  # signal close: origin absent
            )
        ]

        clock.advance(minutes=11)
        expired = engine.expire_stale_orders(session, portfolio)
        session.commit()

        assert expired == 1
        assert entry.status == STATUS_EXPIRED
        assert entry.reject_reason is not None and "fill nunca foi possível" in entry.reject_reason
        assert all(order.status == STATUS_APPROVED for order in closing_sells)

        events = events_with_code(session, portfolio.id, "approved_fill_timeout")
        assert len(events) == 1
        assert events[0].event_type == "order_expired"
        assert events[0].payload["order_id"] == entry.id


def test_recently_approved_order_survives(tmp_path: Path) -> None:
    factory = build_session_factory(tmp_path)
    clock = Clock(SUMMER_RTH)
    with factory() as session:
        portfolio = seed_portfolio(session)
        engine, _cache = build_engine(portfolio, clock)
        order = approved_order(
            session, portfolio, symbol="AAPL", side="BUY", quantity=10, decided_at=clock.now
        )
        clock.advance(minutes=5)  # below the 10-min timeout
        assert engine.expire_stale_orders(session, portfolio) == 0
        assert order.status == STATUS_APPROVED


# -- 3) flat EOD -------------------------------------------------------------------


def test_flat_eod_is_opt_in(tmp_path: Path) -> None:
    """Default False: upgrading must never retroactively liquidate an existing
    swing portfolio whose persisted JSON predates the flag."""
    assert RiskSettings().flat_eod is False
    assert RiskSettings.from_json({"max_position_pct": 10.0}).flat_eod is False

    factory = build_session_factory(tmp_path)
    clock = Clock(SUMMER_EOD)
    with factory() as session:
        portfolio = seed_portfolio(session)  # risk JSON without the key
        engine, cache = build_engine(portfolio, clock)
        add_position(session, portfolio, "AAPL", "10", "100")
        feed_quote(cache, "AAPL", last=110.0, bid=109.9, ask=110.1)
        assert engine.flat_eod_sweep(session, portfolio) == []


def test_flat_eod_closes_position_inside_window(tmp_path: Path) -> None:
    factory = build_session_factory(tmp_path)
    clock = Clock(SUMMER_EOD)
    with factory() as session:
        portfolio = seed_portfolio(session, risk={"flat_eod": True})
        engine, cache = build_engine(portfolio, clock)
        add_position(session, portfolio, "AAPL", "10", "100")
        feed_quote(cache, "AAPL", last=110.0, bid=109.9, ask=110.1)

        trades = engine.flat_eod_sweep(session, portfolio)
        session.commit()

        assert len(trades) == 1
        assert float(trades[0].quantity) == 10.0
        order = session.execute(
            select(PaperOrder).where(PaperOrder.portfolio_id == portfolio.id)
        ).scalar_one()
        assert order.status == STATUS_FILLED
        assert order.signal_snapshot["origin"] == "flat_eod"
        position = session.execute(
            select(PaperPosition).where(PaperPosition.portfolio_id == portfolio.id)
        ).scalar_one()
        assert float(position.quantity) == 0.0


def test_flat_eod_sweep_noop_outside_window_or_disabled(tmp_path: Path) -> None:
    factory = build_session_factory(tmp_path)
    with factory() as session:
        portfolio = seed_portfolio(session, risk={"flat_eod": True})
        clock = Clock(SUMMER_RTH)  # mid-session: outside the window
        engine, cache = build_engine(portfolio, clock)
        add_position(session, portfolio, "AAPL", "10", "100")
        feed_quote(cache, "AAPL", last=110.0, bid=109.9, ask=110.1)
        assert engine.flat_eod_sweep(session, portfolio) == []

        clock.now = SUMMER_EOD  # inside the window but flat_eod disabled
        portfolio.risk_settings = {"flat_eod": False}
        session.flush()
        assert engine.flat_eod_sweep(session, portfolio) == []

        orders = list(
            session.execute(
                select(PaperOrder).where(PaperOrder.portfolio_id == portfolio.id)
            ).scalars()
        )
        assert orders == []


def test_flat_eod_sweep_does_not_stack_duplicate_sells(tmp_path: Path) -> None:
    factory = build_session_factory(tmp_path)
    clock = Clock(SUMMER_EOD)
    with factory() as session:
        portfolio = seed_portfolio(session, risk={"flat_eod": True})
        engine, _cache = build_engine(portfolio, clock)  # no quote: fill defers
        add_position(session, portfolio, "AAPL", "10", "100")

        assert engine.flat_eod_sweep(session, portfolio) == []  # deferred, no trade
        assert engine.flat_eod_sweep(session, portfolio) == []  # retried next poll
        session.commit()

        sells = list(
            session.execute(
                select(PaperOrder).where(
                    PaperOrder.portfolio_id == portfolio.id, PaperOrder.side == "SELL"
                )
            ).scalars()
        )
        assert len(sells) == 1  # one order total, still approved and retryable
        assert sells[0].status == STATUS_APPROVED


def test_flat_eod_sweep_ignores_merely_proposed_sell(tmp_path: Path) -> None:
    """A proposed SELL awaiting user decision must NOT block the flatten — it
    can outlive the whole window unapproved and leave the position overnight."""
    factory = build_session_factory(tmp_path)
    clock = Clock(SUMMER_EOD)
    with factory() as session:
        portfolio = seed_portfolio(session, risk={"flat_eod": True})
        engine, cache = build_engine(portfolio, clock)
        add_position(session, portfolio, "AAPL", "10", "100")
        feed_quote(cache, "AAPL", last=110.0, bid=109.9, ask=110.1)
        proposed = PaperOrder(
            portfolio_id=portfolio.id,
            symbol="AAPL",
            side="SELL",
            quantity=Decimal("10"),
            order_type="market",
            status="proposed",
            signal_snapshot={"strategy": "vwap_reversion"},
            risk_snapshot={},
            data_liveness="DELAYED",
            proposed_at=clock.now,
        )
        session.add(proposed)
        session.flush()

        trades = engine.flat_eod_sweep(session, portfolio)
        session.commit()

        assert len(trades) == 1  # flattened despite the pending proposal
        position = session.execute(
            select(PaperPosition).where(PaperPosition.portfolio_id == portfolio.id)
        ).scalar_one()
        assert float(position.quantity) == 0.0


def test_flat_eod_sweep_survives_multiple_open_sells(tmp_path: Path) -> None:
    """Two open SELLs for one symbol (proposed signal + approved protective)
    must not crash the sweep with MultipleResultsFound."""
    factory = build_session_factory(tmp_path)
    clock = Clock(SUMMER_EOD)
    with factory() as session:
        portfolio = seed_portfolio(session, risk={"flat_eod": True})
        engine, _cache = build_engine(portfolio, clock)
        add_position(session, portfolio, "AAPL", "10", "100")
        for order_status in ("proposed", "approved"):
            order = PaperOrder(
                portfolio_id=portfolio.id,
                symbol="AAPL",
                side="SELL",
                quantity=Decimal("10"),
                order_type="market",
                status=order_status,
                signal_snapshot={},
                risk_snapshot={},
                data_liveness="DELAYED",
                proposed_at=clock.now,
                decided_at=clock.now,
            )
            session.add(order)
        session.flush()

        # Approved SELL already covers the position: no new order, no crash.
        assert engine.flat_eod_sweep(session, portfolio) == []
        sells = session.execute(
            select(PaperOrder).where(
                PaperOrder.portfolio_id == portfolio.id, PaperOrder.side == "SELL"
            )
        ).scalars().all()
        assert len(sells) == 2


def test_protective_exits_do_not_stack_while_fill_defers(tmp_path: Path) -> None:
    factory = build_session_factory(tmp_path)
    clock = Clock(SUMMER_RTH)
    with factory() as session:
        portfolio = seed_portfolio(session)
        engine, cache = build_engine(portfolio, clock)
        feed_quote(cache, "AAPL", last=100.0, bid=99.95, ask=100.05)
        order = engine.propose_from_signal(
            session,
            portfolio,
            symbol="AAPL",
            direction="BUY",
            strength=0.9,
            strategy="rsi_mean_reversion",
            rationale="teste",
        )
        engine.approve_order(session, portfolio, order)

        # Price crosses the stop, but the quote is too old for a credible fill:
        # the protective SELL defers and must NOT be duplicated next poll.
        feed_quote(cache, "AAPL", last=90.0, bid=89.9, ask=90.1)
        clock.advance(minutes=10)  # stale vs quote_max_age_seconds=120
        assert engine.check_protective_exits(session, portfolio) == []
        assert engine.check_protective_exits(session, portfolio) == []
        session.commit()

        protective_sells = session.execute(
            select(PaperOrder).where(
                PaperOrder.portfolio_id == portfolio.id,
                PaperOrder.side == "SELL",
                PaperOrder.status == STATUS_APPROVED,
            )
        ).scalars().all()
        assert len(protective_sells) == 1


def test_new_entries_vetoed_inside_eod_window(tmp_path: Path) -> None:
    factory = build_session_factory(tmp_path)
    clock = Clock(SUMMER_EOD)
    with factory() as session:
        portfolio = seed_portfolio(session, risk={"flat_eod": True})
        engine, cache = build_engine(portfolio, clock)
        feed_quote(cache, "MSFT", last=300.0, bid=299.9, ask=300.1)

        order = engine.propose_from_signal(
            session,
            portfolio,
            symbol="MSFT",
            direction="BUY",
            strength=0.9,
            strategy="rsi_mean_reversion",
            rationale="teste",
        )
        session.commit()

        assert order is not None and order.status == STATUS_REJECTED_RISK
        assert "flat EOD" in order.reject_reason
        vetoes = events_with_code(session, portfolio.id, "eod_window")
        assert len(vetoes) == 1


def test_buy_approval_vetoed_inside_eod_window(tmp_path: Path) -> None:
    """Proposed at 15:49, approved at 15:52: filling would be an immediate
    roundtrip (the sweep closes it minutes later) — approval must veto."""
    factory = build_session_factory(tmp_path)
    clock = Clock(SUMMER_EOD - timedelta(minutes=6))  # 19:49 UTC, before window
    with factory() as session:
        portfolio = seed_portfolio(session, risk={"flat_eod": True})
        engine, cache = build_engine(portfolio, clock)
        feed_quote(cache, "MSFT", last=300.0, bid=299.9, ask=300.1)
        order = engine.propose_from_signal(
            session,
            portfolio,
            symbol="MSFT",
            direction="BUY",
            strength=0.9,
            strategy="rsi_mean_reversion",
            rationale="teste",
        )
        assert order is not None and order.status == STATUS_PROPOSED

        clock.advance(minutes=3)  # 19:52 UTC: inside the window now
        order, trade, deferral = engine.approve_order(session, portfolio, order)
        session.commit()

        assert (trade, deferral) == (None, None)
        assert order.status == STATUS_REJECTED_RISK
        assert "flat EOD" in order.reject_reason
        vetoes = events_with_code(session, portfolio.id, "eod_window")
        assert len(vetoes) == 1


def test_closing_sell_signal_passes_inside_eod_window(tmp_path: Path) -> None:
    factory = build_session_factory(tmp_path)
    clock = Clock(SUMMER_EOD)
    with factory() as session:
        portfolio = seed_portfolio(session, risk={"flat_eod": True})
        engine, cache = build_engine(portfolio, clock)
        add_position(session, portfolio, "AAPL", "10", "100")
        feed_quote(cache, "AAPL", last=110.0, bid=109.9, ask=110.1)

        order = engine.propose_from_signal(
            session,
            portfolio,
            symbol="AAPL",
            direction="SELL",
            strength=0.9,
            strategy="rsi_mean_reversion",
            rationale="teste",
        )
        session.commit()
        assert order is not None and order.status == STATUS_PROPOSED


# -- 4) day trading preset ----------------------------------------------------------


def test_day_trading_defaults_values() -> None:
    preset = RiskSettings.day_trading_defaults()
    assert preset.timeframe == "5m"
    assert preset.quote_max_age_seconds == 30.0
    assert preset.order_expiry_minutes == 5
    assert preset.approved_fill_timeout_minutes == 5
    assert preset.cooldown_minutes == 30
    assert preset.flat_eod is True  # opting into day trading IS the opt-in
    # Non-preset knobs keep the conservative defaults.
    assert preset.max_position_pct == RiskSettings().max_position_pct
